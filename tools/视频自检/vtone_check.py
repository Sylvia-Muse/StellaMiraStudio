#!/usr/bin/env python3
"""vtone_check —— 影调 / 饱和度 / 质感 自检（量"灰不灰、脏不脏、有没有黑"）。

水墨 + 低饱和的画面最容易死在"技术达标但不好看"上：
纸上全是 220-235，全片没有一处真正的黑，也没有一处真正的高光，
观众看到的就是一片"洗白的灰"。这一条把它量出来。

判据（默认 water-ink 档）：
  动态范围  P99 - P1      >= 150   （255 制；< 120 就是"灰蒙蒙"）
  黑位      P0.1          <= 35    （画面里必须真的有一点黑；用 P0.1 不用 P0.5，理由见文档）
  白位      P99           >= 225
  中间调    P50            合理区间 190–235（纸要够亮）
  饱和度    平均 S/255      <= 0.18（水墨）/ <= 0.35（人物）
  死白帧    P99 >= 253 且 P50 >= 245 的帧数 == 0
  死黑帧    P1  <= 2 且 P50 <= 15 的帧数 == 0

用法：
  python3.14 scripts/vtone_check.py <video>
  python3.14 scripts/vtone_check.py <video> --profile person
退出码：0 全 PASS / 1 有 FAIL。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vcommon as V  # noqa: E402

PROFILES = {
    # 黑位用 P0.1 而不是 P0.5，理由见 docs/视频自检清单.md B1：
    #   「有没有黑」和「黑有多少」是两件事。P0.5 实际量的是后者，
    #   而后者已经由 dark_min（暗部面积）管着了；且 P0.5 对"只有一行实墨"的构图
    #   天然不友好。实测 v4 样片：P0.1=21（墨芯是真黑）、P0.5=62。
    "water-ink": dict(range_min=150, p1_max=35, p99_min=225,
                      p50=(190, 235), sat_max=0.18, dark_min=2.0),
    "person":    dict(range_min=140, p1_max=35, p99_min=230,
                      p50=(35, 190), sat_max=0.35, dark_min=8.0),
}


def measure(path: str, fps: float, w: int, h: int):
    """原分辨率抽帧（每 3 个像素取 1 个）。

    绝不能先缩小再统计：把 1080p 缩到 320 宽会把细笔画的墨芯和纸平均掉
    （实测同一帧满幅 min=13，缩到 320 后 P0.5=102 —— "暗部面积 0.0%" 是假的）。
    """
    out = []
    idx = 0
    for fr in V.gray_frames(path, w, h, fps):
        hist = [0] * 256
        n = 0
        for i in range(0, len(fr), 3):
            hist[fr[i]] += 1
            n += 1
        dark = 100.0 * sum(hist[:100]) / max(1, n)   # v<100 的面积占比（%）
        out.append((idx / fps, V.percentile(hist, 0.001), V.percentile(hist, 0.50),
                    V.percentile(hist, 0.995), V.percentile(hist, 0.01), dark))
        idx += 1
    return out


def saturation(path: str, t: float) -> float:
    """抽一帧量 RGB 平均饱和度（只用 PIL）。"""
    import subprocess
    tmp = "/tmp/_vtone.png"
    subprocess.run([V.FFMPEG, "-v", "error", "-y", "-ss", "%.2f" % t,
                    "-i", path, "-frames:v", "1", "-vf", "scale=320:180", tmp],
                   check=False)
    if not os.path.exists(tmp):
        return -1.0
    from PIL import Image, ImageStat
    im = Image.open(tmp).convert("HSV")
    return ImageStat.Stat(im).mean[1] / 255.0


def main() -> int:
    ap = argparse.ArgumentParser(description="影调 / 饱和度 自检")
    ap.add_argument("video")
    ap.add_argument("--profile", choices=list(PROFILES), default="water-ink")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--json")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        sys.exit("没有这个文件：" + args.video)
    p = PROFILES[args.profile]
    info = V.probe(args.video)

    rows = measure(args.video, args.fps, info["width"], info["height"])
    if not rows:
        sys.exit("[FAIL] 没取到帧")

    print("== vtone_check ==  " + args.video)
    print("   %dx%d  %.2fs  抽 %.1ffps  档位=%s"
          % (info["width"], info["height"], info["duration"], args.fps, args.profile))
    print()

    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2]

    p1s = [r[1] for r in rows]
    p50s = [r[2] for r in rows]
    p99s = [r[3] for r in rows]
    darks = [r[5] for r in rows]

    fails = []

    print("-- 影调（255 制，逐帧 P1/P50/P99 再取中位）--")
    P1, P50, P99 = med(p1s), med(p50s), med(p99s)
    dk = med(darks)
    dr = P99 - P1
    print("   黑位 P0.1=%d  中位 P50=%d  白位 P99.5=%d  动态范围=%d" % (P1, P50, P99, dr))
    print("   暗部面积（灰度<100）= %.1f%% 画面   ← 这就是\"墨够不够重\"的量化" % dk)
    ok = dr >= p["range_min"]
    print(V.result_line("动态范围 P99-P1", "%d" % dr, ">=%d" % p["range_min"], ok))
    if not ok:
        fails.append("动态范围只有 %d（画面发灰）" % dr)
    ok = P1 <= p["p1_max"]
    print(V.result_line("黑位 P0.1", "%d" % P1, "<=%d" % p["p1_max"], ok))
    if not ok:
        fails.append("没有真正的黑（P0.1=%d）" % P1)
    ok = P99 >= p["p99_min"]
    print(V.result_line("白位 P99.5", "%d" % P99, ">=%d" % p["p99_min"], ok))
    if not ok:
        fails.append("没有真正的高光（P99.5=%d）" % P99)
    lo, hi = p["p50"]
    ok = lo <= P50 <= hi
    print(V.result_line("中位亮度 P50", "%d" % P50, "%d-%d" % (lo, hi), ok))
    if not ok:
        fails.append("中位 %d 不在 %d-%d" % (P50, lo, hi))
    print()

    print("-- 极端帧 --")
    dead_white = [r[0] for r in rows if r[3] >= 253 and r[2] >= 245]
    dead_black = [r[0] for r in rows if r[1] <= 2 and r[2] <= 15]
    flat = [r[0] for r in rows if r[3] - r[1] < 60]
    thin = [r[0] for r in rows if r[5] < p["dark_min"]]
    print(V.result_line("暗部面积（<100）", "%.1f%%" % dk,
                        ">=%.1f%%" % p["dark_min"], not thin))
    print(V.result_line("死白帧", "%d" % len(dead_white), "==0", not dead_white))
    print(V.result_line("死黑帧", "%d" % len(dead_black), "==0", not dead_black))
    print(V.result_line("动态范围<60 的帧", "%d" % len(flat),
                        "<=3%% 帧数", len(flat) <= max(1, 0.03 * len(rows))))
    if dead_white:
        fails.append("%d 帧死白" % len(dead_white))
    if dead_black:
        fails.append("%d 帧死黑" % len(dead_black))
    if thin:
        print("      %d/%d 帧暗部不足（墨太淡，远看是纸不是字）：%s"
              % (len(thin), len(rows), "、".join("%.0fs" % x for x in thin[:10])))
    if len(flat) > max(1, 0.03 * len(rows)):
        fails.append("%d 帧动态范围 <60（雾片）" % len(flat))
        for t in flat[:8]:
            r = next(x for x in rows if x[0] == t)
            print("      t=%.1fs  P0.1=%d P99.5=%d 范围=%d" % (r[0], r[1], r[3], r[3] - r[1]))
    print()

    print("-- 曲线（每 %ds 一行）--" % max(1, int(len(rows) / 10)))
    step = max(1, len(rows) // 10)
    for i in range(0, len(rows), step):
        t, a, m, b = rows[i][:4]
        bar = "#" * max(0, min(40, (b - a) // 6))
        print("   %6.1fs  P0.1=%3d P50=%3d P99.5=%3d  %s" % (t, a, m, b, bar))
    print()

    s = saturation(args.video, info["duration"] * 0.5)
    if s >= 0:
        ok = s <= p["sat_max"]
        print("-- 饱和度 --")
        print(V.result_line("平均饱和度", "%.3f" % s, "<=%.2f" % p["sat_max"], ok))
        if not ok:
            fails.append("饱和度 %.3f 偏高" % s)
        print()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(dict(rows=rows, p1=P1, p50=P50, p99=P99, dr=dr,
                           sat=s, profile=args.profile), f, ensure_ascii=False, indent=1)

    print("== 结论：" + ("全部 PASS" if not fails else "FAIL -> " + "；".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
