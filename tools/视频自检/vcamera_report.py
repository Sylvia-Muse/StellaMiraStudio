#!/usr/bin/env python3
"""vcamera_report —— 直接读相机路径的精确镜头分析（页面渲染类作品专用）。

为什么不量像素：`vshot_report.py` 的"取景变化点"是**代理指标**——它看的是
主体带高与墨迹重心，而"笔在写"本身就会让重心右移、让画面亮度下降。
所以它分不清"镜头动了"和"字长了"。做 EDL 必须看相机本身。

本脚本两种输入：
  --keys keys.json    直接给关键帧数组 [{t,cx,cy,zoom}, ...]，用页面里同一套
                      cameraAt() 插值公式复算整条路径（与渲染逐帧一致）
  --page dir/page.html 起 headless 浏览器，把 window.__cameraAt(t) 采样一遍

判据（`--profile mv`）：
  取景变化点   相邻 0.30s 窗口的 (zoom 相对变化 / cx 位移 / cy 位移) 阶跃超过阈值
  最长一个取景 ≤ --max-hold（默认 4.0s）
  取景变化密度 ≥ --min-rate 次/秒（默认 0.30，即平均 3.3s 一次）
  景别动态范围 p90/p10 ≥ 2.5×

用法：
  python3.14 scripts/vcamera_report.py --keys /tmp/rows.json --duration 171.58
  python3.14 scripts/vcamera_report.py --page data/videos/.../mv-art.html --duration 171.58
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GLYPH = 0.205          # 世界单位；屏幕占比 = GLYPH * zoom


# ------------------------------------------------------------------ cameraAt
def clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def smooth(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def mix(a, b, k):
    return a + (b - a) * k


def camera_at(keys, t):
    """与 mv-art.html 的 cameraAt() 逐字一致（含呼吸项）。"""
    if not keys:
        return (0.0, 0.0, 1.0)
    i = 0
    while i < len(keys) - 1 and keys[i + 1]["t"] <= t:
        i += 1
    a = keys[i]
    b = keys[min(i + 1, len(keys) - 1)]
    u = clamp((t - a["t"]) / (b["t"] - a["t"])) if b["t"] > a["t"] else 0.0
    u = mix(u, smooth(u), 0.75)
    cx = mix(a["cx"], b["cx"], u) + 0.003 * math.sin(t * 0.26)
    cy = (mix(a["cy"], b["cy"], u) + 0.006 * math.sin(t * 0.21 + 1.1)
          + 0.0045 * math.sin(t * 0.77 + 0.5))
    zoom = mix(a["zoom"], b["zoom"], u) * (
        1 + 0.025 * math.sin(t * 0.62 + 0.4) + 0.010 * math.sin(t * 1.13 + 2.2))
    return (cx, cy, zoom)


def path(keys, duration, fps):
    out = []
    n = int(round(duration * fps))
    for i in range(n):
        t = i / fps
        cx, cy, zoom = camera_at(keys, t)
        out.append((t, cx, cy, zoom))
    return out


# ------------------------------------------------------------------ 阶跃检测
def med(xs):
    ys = sorted(xs)
    return ys[len(ys) // 2] if ys else 0.0


def steps(series, hw):
    """[i-2hw, i-hw) 的中位  vs  [i+hw, i+2hw) 的中位。

    窗口必须**跳过过渡斜坡本身**：一次运镜如果是 0.55s 推到位，
    紧贴 i 取 ±hw 会把斜坡平均进去，量出来只剩台阶的 20%
    （实测 t=6.3 的 0.88→1.04 只量到 +0.032，漏判）。
    往前/往后各让开一个 hw，量到的就是真正的"到位前后"。
    """
    out = [0.0] * len(series)
    n = len(series)
    for i in range(1, n):
        b = med(series[max(0, i - 2 * hw):max(0, i - hw)])
        a = med(series[min(n, i + hw):min(n, i + 2 * hw)])
        out[i] = a - b
    return out


def analyse(keys, duration, fps, args):
    P = path(keys, duration, fps)
    cx = [p[1] for p in P]
    cy = [p[2] for p in P]
    z = [p[3] for p in P]
    hw = max(1, int(round(0.30 * fps)))
    dz, dx, dy = steps(z, hw), steps(cx, hw), steps(cy, hw)
    zb = [med(z[max(0, i - 2 * hw):max(1, i - hw)]) or 1e-9 for i in range(len(z))]

    mask = [False]
    for i in range(1, len(z)):
        rel = abs(dz[i]) / zb[i]
        mask.append(rel >= args.step_zoom or abs(dx[i]) >= args.step_pan
                    or abs(dy[i]) >= args.step_pan)

    # 合并 0.8s 内的重复触发
    pts = []
    for i, m in enumerate(mask):
        if not m:
            continue
        t = i / fps
        if pts and t - pts[-1] < args.merge:
            continue
        pts.append(t)

    bounds = [0.0] + [p for p in pts if p > 0] + [duration]
    holds = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]

    hgt = sorted(GLYPH * v for v in z if v > 1e-6)
    lo = hgt[int(0.10 * (len(hgt) - 1))]
    hi = hgt[int(0.90 * (len(hgt) - 1))]
    return dict(pts=pts, holds=holds, longest=max(holds or [0]),
                p10=lo, p50=hgt[len(hgt) // 2], p90=hi, ratio=hi / lo,
                duration=duration)


def dump_from_page(page, duration, fps, keys_attr="__cameraAt"):
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    d = os.path.dirname(os.path.abspath(page))
    name = os.path.basename(page)

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), lambda *x, **kw: H(*x, directory=d, **kw))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--use-angle=metal"])
        pg = b.new_context(viewport={"width": 1920, "height": 1080}).new_page()
        pg.goto("http://127.0.0.1:%d/%s" % (port, name),
                wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3500)
        keys = pg.evaluate("() => window.__keats ? window.__keats() : window.__keys")
        b.close()
    httpd.shutdown()
    return keys


def main():
    ap = argparse.ArgumentParser(description="相机路径精确分析")
    ap.add_argument("--keys", help="keys json：{keys:[...]} 或直接是数组")
    ap.add_argument("--page", help="页面路径（起浏览器采样）")
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--step-zoom", type=float, default=0.12,
                    help="zoom 相对阶跃 ≥ 这个数算换取景")
    ap.add_argument("--step-pan", type=float, default=0.07,
                    help="cx/cy 位移阶跃 ≥ 画面比例的这个数算换取景")
    ap.add_argument("--merge", type=float, default=0.80)
    ap.add_argument("--offset", type=float, default=0.0,
                    help="keys 是绝对歌曲时间，片段从歌曲第 offset 秒开始（片内 t = 歌曲 t - offset）")
    ap.add_argument("--from", dest="t_from", type=float, default=None,
                    help="只分析歌曲时间的这一段（配合 --offset）")
    ap.add_argument("--to", dest="t_to", type=float, default=None)
    ap.add_argument("--max-hold", type=float, default=4.0)
    ap.add_argument("--min-rate", type=float, default=0.30, help="取景变化次数/秒")
    ap.add_argument("--json")
    args = ap.parse_args()

    if args.keys:
        j = json.load(open(args.keys))
        keys = j["keys"] if isinstance(j, dict) else j
    elif args.page:
        keys = dump_from_page(args.page, args.duration, args.fps)
    else:
        sys.exit("要么 --keys，要么 --page")
    keys = sorted(keys, key=lambda k: k["t"])
    off = args.offset
    lo = args.t_from if args.t_from is not None else off
    hi = args.t_to if args.t_to is not None else (off + args.duration)
    # 裁剪到窗口，并在窗口两端各补一个"保持"关键帧，保证插值与原片一致
    if lo is not None and hi is not None and (lo > keys[0]["t"] or hi < keys[-1]["t"]):
        inside = [k for k in keys if lo <= k["t"] <= hi]
        head = {"t": lo, "cx": camera_at(keys, lo)[0], "cy": camera_at(keys, lo)[1],
                "zoom": camera_at(keys, lo)[2]}
        tail = {"t": hi, "cx": camera_at(keys, hi)[0], "cy": camera_at(keys, hi)[1],
                "zoom": camera_at(keys, hi)[2]}
        keys = [head] + inside + [tail]
    if off:
        keys = [dict(k, t=k["t"] - off) for k in keys]
        keys = [k for k in keys if -1e-6 <= k["t"] <= args.duration + 1e-6]

    a = analyse(keys, args.duration, args.fps, args)
    print("== vcamera_report ==  " + (args.keys or args.page))
    print("   关键帧 %d 个  时长 %.2fs  @%.0ffps" % (len(keys), a["duration"], args.fps))
    print()
    print("-- 取景 --")
    print("   取景变化点 %d 个 = %.2f 次/秒" % (len(a["pts"]), len(a["pts"]) / args.duration))
    rate = len(a["pts"]) / args.duration
    ok_rate = rate >= args.min_rate
    print("[%s] %-22s %-24s 判据 >=%.2f 次/秒" %
          ("PASS" if ok_rate else "FAIL", "取景变化密度", "%.2f 次/秒" % rate, args.min_rate))
    ok_hold = a["longest"] <= args.max_hold
    print("[%s] %-22s %-24s 判据 <=%.1fs" %
          ("PASS" if ok_hold else "FAIL", "最长一个取景", "%.2fs" % a["longest"], args.max_hold))
    print()
    print("-- 景别（字高 = 0.205 × zoom，占画面高）--")
    print("   %.1f%% -> %.1f%%（p10/p90）= %.2f×" %
          (a["p10"] * 100, a["p90"] * 100, a["ratio"]))
    ok_r = a["ratio"] >= 2.5
    print("[%s] %-22s %-24s 判据 >=2.5×" %
          ("PASS" if ok_r else "FAIL", "景别动态范围", "%.2f×" % a["ratio"]))
    print()
    print("-- 取景保持时长（前 12 长）--")
    hs = sorted(a["holds"], reverse=True)[:12]
    print("   " + " | ".join("%.1fs" % h for h in hs))
    print()
    if args.json:
        json.dump(a, open(args.json, "w"), ensure_ascii=False, indent=1)
    return 0 if (ok_rate and ok_hold and ok_r) else 1


if __name__ == "__main__":
    raise SystemExit(main())
