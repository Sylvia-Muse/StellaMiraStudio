#!/usr/bin/env python3
"""vcommon —— 视频自检脚本共用的小工具（只依赖标准库 + PIL，不用 numpy）。

设计约束（和 docs/视频自检清单.md 对齐）：
  * 一律流式读帧（ffmpeg rawvideo → stdin），不落临时文件，4K 也不吃内存。
  * ffmpeg/ffprobe 路径可被环境变量 FFMPEG / FFPROBE 覆盖，默认按顺序探测。
  * 所有度量都输出成"数字 + 阈值 + PASS/FAIL"，不允许出现"看起来还行"。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

# ------------------------------------------------------------------ 外部程序

def _find(name: str, env: str) -> str:
    v = os.environ.get(env)
    if v and os.path.exists(v):
        return v
    for cand in (os.path.expanduser(f"~/bin/{name}"), f"/opt/homebrew/bin/{name}",
                 f"/usr/local/bin/{name}", shutil.which(name) or ""):
        if cand and os.path.exists(cand) and os.access(cand, os.X_OK):
            return cand
    sys.exit(f"[vcommon] 找不到 {name}：请设置环境变量 {env} 指向可执行文件")


FFMPEG = _find("ffmpeg", "FFMPEG")
FFPROBE = _find("ffprobe", "FFPROBE")


def run(cmd: list[str], stdin_data: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=stdin_data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=False)


# ------------------------------------------------------------------ 探测规格

def probe(path: str) -> dict:
    """返回 {width, height, fps, duration, frames, has_audio, sar}。"""
    r = run([FFPROBE, "-v", "error", "-show_streams", "-show_format",
             "-of", "json", path])
    if r.returncode == 0:
        j = json.loads(r.stdout.decode("utf-8", "replace"))
        out = {"has_audio": False}
        for s in j.get("streams", []):
            if s.get("codec_type") == "video" and "width" not in out:
                out.update(width=int(s["width"]), height=int(s["height"]),
                           frames=int(s.get("nb_frames") or 0))
                num, _, den = (s.get("r_frame_rate") or "30/1").partition("/")
                out["fps"] = float(num) / float(den or 1)
            elif s.get("codec_type") == "audio":
                out["has_audio"] = True
        fmt = j.get("format", {})
        out["duration"] = float(fmt.get("duration") or 0)
        return out
    # ffprobe 不可用时退回解析 ffmpeg -i 的 stderr
    r = run([FFMPEG, "-hide_banner", "-i", path])
    txt = r.stderr.decode("utf-8", "replace")
    out = {"has_audio": "Audio:" in txt}
    for line in txt.splitlines():
        if "Video:" in line and "x" in line:
            import re
            m = re.search(r"(\d{2,5})x(\d{2,5})", line)
            if m:
                out["width"], out["height"] = int(m.group(1)), int(m.group(2))
            m = re.search(r"([\d.]+) fps", line)
            out["fps"] = float(m.group(1)) if m else 30.0
        if "Duration:" in line:
            import re
            m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", line)
            if m:
                out["duration"] = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                                   + float(m.group(3)))
    out.setdefault("fps", 30.0)
    out.setdefault("width", 1920)
    out.setdefault("height", 1080)
    out["frames"] = int(round(out.get("duration", 0) * out["fps"]))
    return out


# ------------------------------------------------------------------ 抽帧

def gray_frames(path: str, width: int, height: int, fps: float,
                start: float | None = None, dur: float | None = None):
    """生成器：逐帧 yield 一个 bytes（length = width*height 的灰度）。"""
    cmd = [FFMPEG, "-v", "error", "-nostdin"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vf", f"scale={width}:{height}:flags=area,format=gray",
            "-r", f"{fps}", "-f", "rawvideo", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = width * height
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            yield buf
    finally:
        p.stdout.close()
        p.wait()


# ------------------------------------------------------------------ 灰度工具

def median_of(frame: bytes, step: int = 7) -> int:
    """采样直方图求中位数（不排序整帧，快）。"""
    hist = [0] * 256
    tot = 0
    for i in range(0, len(frame), step):
        hist[frame[i]] += 1
        tot += 1
    half = tot // 2
    acc = 0
    for v in range(256):
        acc += hist[v]
        if acc >= half:
            return v
    return 128


def percentile(hist: list[int], p: float) -> int:
    tot = sum(hist)
    if not tot:
        return 0
    target = p * tot
    acc = 0
    for v in range(256):
        acc += hist[v]
        if acc >= target:
            return v
    return 255


def row_profile(frame: bytes, w: int, h: int, thr: int, above: bool) -> list[int]:
    """每行的"墨迹"像素计数。above=True 表示亮于 thr 算主体（暗底），否则暗于 thr。"""
    prof = [0] * h
    if above:
        for y in range(h):
            base = y * w
            row = frame[base:base + w]
            prof[y] = sum(1 for v in row if v > thr)
    else:
        for y in range(h):
            base = y * w
            row = frame[base:base + w]
            prof[y] = sum(1 for v in row if v < thr)
    return prof


def bands(prof: list[int], thr_count: int, min_rows: int) -> list[tuple[int, int]]:
    """把行剖面切成 [y0, y1) 连续带。

    thr_count: 一行至少要有多少个"主体像素"才算这一行属于主体带
               （由调用方按 画面宽度 × 比例 算好传进来）。
    min_rows : 短于这个行数的带丢掉（滤掉单行噪声）。
    """
    out, start = [], None
    h = len(prof)
    for y in range(h):
        if prof[y] >= thr_count:
            if start is None:
                start = y
        else:
            if start is not None and y - start >= min_rows:
                out.append((start, y))
            start = None
    if start is not None and h - start >= min_rows:
        out.append((start, h))
    return out


def fmt_t(t: float) -> str:
    return f"{t:7.2f}s"


def verdict(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def result_line(name: str, value: str, rule: str, ok: bool) -> str:
    return f"[{verdict(ok)}] {name:<28} {value:<26} 判据 {rule}"
