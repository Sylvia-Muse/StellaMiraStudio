#!/usr/bin/env python3
"""MV 构建：把官方音轨 + 官方 LRC 歌词 + Live2D 渲染页拼成一条 MV。

做三件事：
  1. 解析 LRC，把碎句合并成「一行字幕」（每行 2~3 个短句，太短的行并到下一行）
  2. 按时间轴切段，给每段配表情与镜头（主歌中景、副歌推近、间奏拉远）
  3. 从官方音轨算口型包络，写进 site/mouth.json；把音轨转成 tts/full.wav 给 mux 用

产物写进 data/debut/site（沿用现有渲染页），原 plan 会被备份成 plan.debut.bak.json。
"""
import json
import math
import os
import re
import shutil
import struct
import subprocess
import wave

ROOT = "/Users/xhqm/Space/qqSpace"
VDIR = os.path.join(ROOT, "data/videos/20261029_04_world-execute-me-mv")
SITE = os.path.join(ROOT, "data/debut/site")
TTS = os.path.join(ROOT, "data/debut/tts")
FFMPEG = os.path.expanduser("~/bin/ffmpeg")
FPS = 30

AUDIO_MP3 = os.path.join(VDIR, "audio", "world.execute(me)_320k.mp3")
VOCAL_WAV = os.path.join(VDIR, "audio", "world.execute(me)_人声轨.wav")
LRC = os.path.join(VDIR, "lyrics.lrc")

META_PAT = re.compile(r"作曲|作词|编曲|混音|演唱|制作|^\s*world\.execute", re.I)


def parse_lrc(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\[(\d+):(\d+\.\d+)\](.*)", line.strip())
        if not m:
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        txt = m.group(3).strip()
        if not txt or META_PAT.search(txt):
            continue
        rows.append((t, txt))
    rows.sort()
    return rows


def merge_lines(rows, min_chars=14, max_chars=34):
    """把过短的行并成一行，避免字幕频繁跳"""
    out = []
    buf_t, buf_s = None, ""
    for t, txt in rows:
        if buf_t is None:
            buf_t, buf_s = t, txt
            continue
        cand = buf_s + " " + txt
        caps = buf_s.isupper() and len(buf_s) <= 12
        if (not caps) and len(buf_s) < min_chars and len(cand) <= max_chars:
            buf_s = cand
        else:
            out.append((buf_t, buf_s))
            buf_t, buf_s = t, txt
    if buf_t is not None:
        out.append((buf_t, buf_s))
    return out


def mouth_envelope(audio, total, n_frames, attack=0.55, release=0.24, gain=2.6):
    tmp = "/tmp/mv_mouth.wav"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", audio,
                    "-ac", "1", "-ar", "24000", tmp], check=True)
    w = wave.open(tmp, "rb")
    sr = w.getframerate()
    raw = w.readframes(w.getnframes())
    w.close()
    s = struct.unpack("<%dh" % (len(raw) // 2), raw)
    per = max(1, sr // FPS)
    rms = []
    for i in range(n_frames):
        seg = s[i * per:(i + 1) * per] or (0,)
        rms.append(math.sqrt(sum((v / 32768.0) ** 2 for v in seg) / len(seg)))
    peak = max(rms) or 1.0
    out, level = [], 0.0
    for r in rms:
        target = min(1.0, max(0.0, (r / peak - 0.10) * gain))
        level += (target - level) * (attack if target > level else release)
        out.append(round(level, 4))
    return out


def main():
    rows = merge_lines(parse_lrc(LRC))
    total = float(subprocess.run(["/opt/homebrew/bin/ffprobe", "-v", "error", "-show_entries",
                                  "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                                  AUDIO_MP3], capture_output=True, text=True).stdout.strip())
    print("字幕 %d 行 / 总长 %.2fs" % (len(rows), total))

    # 段落 → 表情 / 镜头
    def mood(t):
        if t < 16:
            return ("表情-发懵", 1.05, 1.18)
        if t < 59:
            return ("表情-眯眼", 1.12, 1.26)
        if t < 106:
            return ("表情-惊喜", 1.20, 1.34)
        if t < 132:
            return ("表情-脸红", 1.10, 1.22)
        if t < 176:
            return ("表情-眯眼", 1.16, 1.30)
        if t < 196:
            return ("表情-眼泪", 1.22, 1.36)
        return ("表情-脸红", 1.08, 1.20)

    segs = []
    for i, (t0, txt) in enumerate(rows):
        t1 = rows[i + 1][0] if i + 1 < len(rows) else total - 0.4
        expr, sc, yy = mood(t0)
        segs.append({"t0": round(t0, 3), "t1": round(min(t1, total), 3),
                     "expr": expr, "sub": txt, "scale": sc, "y": yy})

    n_frames = int(round(total * FPS))
    # 口型跟「人声轨」，身体跟「整首」的节拍能量
    mouth = mouth_envelope(VOCAL_WAV if os.path.exists(VOCAL_WAV) else AUDIO_MP3, total, n_frames)
    music = mouth_envelope(AUDIO_MP3, total, n_frames, attack=0.30, release=0.12, gain=2.0)
    json.dump(music, open(os.path.join(SITE, "music.json"), "w"))

    plan = {
        "fps": FPS, "width": 1080, "height": 1920,
        "duration": round(total, 3),
        "scale": 1.12, "y": 1.26,
        "expressions": ["表情-眯眼", "表情-惊喜", "表情-脸红", "表情-发懵", "表情-眼泪", "表情-黑脸"],
        "nameCard": {"t0": total + 999},
        "bgVideo": "/bg.webm",
        "subtitleScale": 0.78,
        "brand": "◈ SYLVIA MUSE ◈",
        "segments": segs,
    }

    bak = os.path.join(SITE, "plan.debut.bak.json")
    if os.path.exists(os.path.join(SITE, "plan.json")) and not os.path.exists(bak):
        shutil.copy(os.path.join(SITE, "plan.json"), bak)
    json.dump(plan, open(os.path.join(SITE, "plan.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(mouth, open(os.path.join(SITE, "mouth.json"), "w"))

    # 音轨给 mux 用：把背景乐文件移开，避免侧链闪避把原曲压掉
    os.makedirs(TTS, exist_ok=True)
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", AUDIO_MP3,
                    "-ac", "2", "-ar", "48000", os.path.join(TTS, "full.wav")], check=True)
    bgm = os.path.join(ROOT, "data/debut/audio/bgm.wav")
    if os.path.exists(bgm):
        os.rename(bgm, bgm + ".mv-bak")

    # 背景视频：拷到 site 根，循环用
    src = os.path.join(ROOT, "data/videos/20261016_00_world-execute-me-mv/clips/mv_raw_110s.webm")
    if os.path.exists(src):
        shutil.copy(src, os.path.join(SITE, "bg.webm"))
        print("背景视频已就位:", os.path.join(SITE, "bg.webm"))
    print("plan.json / mouth.json / full.wav 已生成；帧数 %d（约 %.0f 分钟渲染）" % (n_frames, n_frames / 3.7 / 60))


if __name__ == "__main__":
    main()
