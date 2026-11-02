#!/usr/bin/env python3
"""vaudio_check —— 响度 / 真峰值 / 动态范围 自检。

为什么必须先量再发：人耳在自家监听上"刚好"的配音，传到平台会被统一化成
"小一截"。平台做的是**整体响度归一**（不是峰值归一），所以唯一能控的是
integrated LUFS 与 true peak。

判据（默认 mv 档）：
  I   -14.0 LUFS ±1.0        （流媒体通行目标；MV / 音乐内容）
  TP  <= -1.0 dBTP           （留 1dB 给 AAC/Opus 重编码，避免解码端削波）
  LRA >= 3.0 LU              （整片动态；< 2 基本是"一条直线"，听着闷）
  削波：样本峰值 >= 0 dBFS 的帧数必须为 0

档位：
  --profile mv      -14 ±1.0 / TP<=-1.0 / LRA>=3.0
  --profile slice    -16 ±1.0 / TP<=-1.5 / LRA>=2.0   （竖屏口播，人声为主）
  --profile mv-loud  -12 ±1.0 / TP<=-1.0 / LRA>=3.0   （短影音，抢注意力）

用法：
  python3.14 scripts/vaudio_check.py <video-or-audio>
  python3.14 scripts/vaudio_check.py x.mp4 --profile slice --window 10
退出码：0 全 PASS / 1 有 FAIL。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vcommon as V  # noqa: E402

PROFILES = {
    "mv":     dict(I=-14.0, tol=1.0, tp=-1.0, lra=3.0),
    "slice":  dict(I=-16.0, tol=1.0, tp=-1.5, lra=2.0),
    "mv-loud": dict(I=-12.0, tol=1.0, tp=-1.0, lra=3.0),
}


def loudnorm(path: str, start=None, dur=None) -> dict:
    cmd = [V.FFMPEG, "-nostdin", "-hide_banner"]
    if start is not None:
        cmd += ["-ss", "%.3f" % start]
    cmd += ["-i", path]
    if dur is not None:
        cmd += ["-t", "%.3f" % dur]
    cmd += ["-af", "loudnorm=print_format=json", "-f", "null", "-"]
    r = V.run(cmd)
    txt = r.stderr.decode("utf-8", "replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", txt, re.S)
    if not m:
        return {}
    try:
        j = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return {k: (float(v) if re.match(r"^-?[\d.]+$", str(v).strip()) else v)
            for k, v in j.items()}


def peak_clip_count(path: str) -> int:
    """数有多少个音频块峰值贴到 0 dBFS。

    reset=1 很关键：reset=0 时 astats 打的是"累计最大值"，
    一旦碰到过 0 dBFS 后面每一帧都会继续报 0，数字会虚高几十倍（实测 565 vs 2）。
    """
    cmd = [V.FFMPEG, "-nostdin", "-hide_banner", "-i", path, "-af",
           "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.Peak_level:file=-",
           "-f", "null", "-"]
    r = V.run(cmd)
    txt = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    n = 0
    for line in txt.splitlines():
        m = re.search(r"Peak_level=(-?[\d.]+)", line)
        if m and float(m.group(1)) >= -0.01:
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="响度 / 真峰值 / 动态范围 自检")
    ap.add_argument("media")
    ap.add_argument("--profile", choices=list(PROFILES), default="mv")
    ap.add_argument("--window", type=float, default=10.0,
                    help="分段量响度的窗口秒数，0 = 不分段")
    ap.add_argument("--target", type=float, default=None, help="覆盖目标 LUFS")
    ap.add_argument("--json")
    args = ap.parse_args()

    if not os.path.exists(args.media):
        sys.exit("没有这个文件：" + args.media)
    p = dict(PROFILES[args.profile])
    if args.target is not None:
        p["I"] = args.target

    info = V.probe(args.media)
    if not info.get("has_audio"):
        sys.exit("[FAIL] 这条片子没有音轨 —— 发布版必须有音轨")

    print("== vaudio_check ==  " + args.media)
    print("   %dx%d  %.2fs  档位=%s  目标 I=%.1f±%.1f LUFS / TP<=%.1f dBTP / LRA>=%.1f"
          % (info["width"], info["height"], info["duration"], args.profile,
             p["I"], p["tol"], p["tp"], p["lra"]))
    print()

    g = loudnorm(args.media)
    if not g:
        sys.exit("[FAIL] loudnorm 没产出数据（音轨是静音？）")
    I, TP, LRA = g.get("input_i", 0.0), g.get("input_tp", 0.0), g.get("input_lra", 0.0)
    TH = g.get("input_thresh", 0.0)

    fails = []
    print("-- 整片 --")
    print("   Integrated %.2f LUFS    True peak %.2f dBTP    LRA %.2f LU    门限 %.1f LUFS"
          % (I, TP, LRA, TH))
    okI = abs(I - p["I"]) <= p["tol"]
    print(V.result_line("整片响度 I", "%.2f LUFS" % I,
                        "%.1f±%.1f" % (p["I"], p["tol"]), okI))
    okTP = TP <= p["tp"]
    print(V.result_line("真峰值 TP", "%.2f dBTP" % TP, "<=%.1f dBTP" % p["tp"], okTP))
    okLRA = LRA >= p["lra"]
    print(V.result_line("动态范围 LRA", "%.2f LU" % LRA, ">=%.1f LU" % p["lra"], okLRA))
    if not okI:
        fails.append("响度偏离目标 %.1f LU（应整体增益 %+.1f dB）" % (I - p["I"], p["I"] - I))
    if not okTP:
        fails.append("真峰值 %.2f dBTP 超线（应整体降 %.1f dB）" % (TP, TP - p["tp"]))
    if not okLRA:
        fails.append("动态范围偏平（LRA %.1f）" % LRA)

    clip = peak_clip_count(args.media)
    okC = clip == 0
    print(V.result_line("贴 0dBFS 的音频块", "%d" % clip, "==0", okC))
    if not okC:
        fails.append("有 %d 个音频块贴 0 dBFS" % clip)
    print()

    curve = []
    if args.window > 0 and info["duration"] > args.window * 1.5:
        print("-- 分段响度（%gs 窗口）--" % args.window)
        print("     起  止    I(LUFS)  相对全片")
        t = 0.0
        while t < info["duration"] - 1.0:
            seg = min(args.window, info["duration"] - t)
            w = loudnorm(args.media, start=t, dur=seg)
            if w and "input_i" in w:
                wi = w["input_i"]
                curve.append((t, t + seg, wi))
                print("   %5.1f %5.1f   %7.2f   %+5.1f dB%s"
                      % (t, t + seg, wi, wi - I,
                         "   <<< 整段比全片高 >3dB" if wi - I > 3.0 else ""))
            t += args.window
        spread = (max(c[2] for c in curve) - min(c[2] for c in curve)) if curve else 0.0
        print(V.result_line("分段响度极差", "%.1f dB" % spread, "<=12 dB", spread <= 12.0))
        if spread > 12.0:
            fails.append("分段响度极差 %.1f dB（忽大忽小 / 有段落被压死）" % spread)
        print()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(dict(integrated=I, true_peak=TP, lra=LRA, thresh=TH,
                           clip_frames=clip, curve=curve, profile=args.profile),
                      f, ensure_ascii=False, indent=1)

    print("== 结论：" + ("全部 PASS" if not fails else "FAIL -> " + "；".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
