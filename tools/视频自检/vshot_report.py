#!/usr/bin/env python3
"""vshot_report —— 镜头 / 节奏 / 景别 自检。

回答四个问题，每问都落到一个数字上：
  C1 最长静止段？          —— 画面"什么都没变"能持续多久
  C2 静止占比？            —— 全片有多少时间是在原地
  C3 最长"一个取景"？      —— 从一次取景变化到下一次，最久多久没换构图
  C4 景别动态范围？        —— 主体高度占比的高位 / 低位；< 2× 基本等于"一个景别到底"
  C5 相邻镜头景别是否重复？—— 只在给了 --cuts（剪辑点表）时检查

关于"切点"：不用自动场景检测。ffmpeg 的 scdet/scene 在我们这种"纸上一行字慢慢写"
的素材上会把笔刷推进误报成剪辑（实测 MV 40s 报 15 个假切点）。所以这里量的是
"取景是否变了"（景别 / 主体水平重心 / 画面中位亮度 联合判断），真正的剪辑点由
--cuts 显式给出（build 脚本的 EDL，一行一个秒数）。

用法：
  python3.14 scripts/vshot_report.py <video.mp4>                    # 默认 mv 档
  python3.14 scripts/vshot_report.py <video> --profile slice        # 竖屏口播档
  python3.14 scripts/vshot_report.py <video> --cuts cuts.txt --json out.json

退出码：0 全 PASS / 1 有 FAIL。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vcommon as V  # noqa: E402

# 景别：主体高度 / 画面高度 → 名字
SCALE_TABLE = [(0.60, "大特写"), (0.42, "特写"), (0.30, "近景"),
               (0.20, "中景"), (0.09, "全景"), (0.00, "远景")]

# 档位预设：MV 要求景别必须有变化；竖屏口播允许一镜到底（靠口播节奏撑）
PROFILES = {
    # 静止用「最长单次 + 连续串」判，不用「占比」——占比量的是总量，
    # 而观感取决于"最长一次"和"是不是连着来"（详见 docs/视频自检清单.md A2）。
    "mv":     dict(max_static=3.00, max_static_cluster=3.00, max_hold=12.0,
                   min_scale_range=2.00, max_repeats=1),
    "slice":  dict(max_static=2.50, max_static_cluster=3.00, max_hold=40.0,
                   min_scale_range=1.20, max_repeats=99),
    "strict": dict(max_static=2.00, max_static_cluster=2.50, max_hold=6.0,
                   min_scale_range=2.50, max_repeats=0),
}


def scale_label(frac: float) -> str:
    for thr, name in SCALE_TABLE:
        if frac >= thr:
            return name
    return "远景"


def smooth_window(xs, k):
    out = []
    for i in range(len(xs)):
        lo, hi = max(0, i - k), min(len(xs), i + k + 1)
        out.append(sum(xs[lo:hi]) / (hi - lo))
    return out


def analyse(args):
    info = V.probe(args.video)
    W, H = info["width"], info["height"]
    aw = 320 if W >= H else max(64, int(320 * W / H))   # 长边 320，够量景别/帧差
    ah = max(48, int(aw * H / W))
    fps = args.sample_fps
    n_expect = int(round(info["duration"] * fps))
    thr = args.ink_thr_dark if args.dark else args.ink_thr

    prev = None
    diffs, fracs, cxs, lums, subs = [], [], [], [], []
    for i, fr in enumerate(V.gray_frames(args.video, aw, ah, fps)):
        if prev is not None:
            diffs.append(sum(abs(a - b) for a, b in zip(fr, prev)) / len(fr))
        prev = fr

        lums.append(V.median_of(fr))
        prof = V.row_profile(fr, aw, ah, thr, above=args.dark)
        bs = V.bands(prof, max(2, aw // 100), max(3, ah // 40))
        sub = None
        if bs:                                    # 剔掉底部的字幕带
            y0, y1 = bs[-1]
            if y0 / ah > 0.86 and (y1 - y0) / ah < 0.08:
                sub = (y0 / ah, y1 / ah)
                bs = bs[:-1]
        subs.append(sub)
        if bs:
            y0, y1 = max(bs, key=lambda b: b[1] - b[0])
            fracs.append((y1 - y0) / ah)
            s, c = 0, 0
            for y in range(y0, y1, 2):
                base = y * aw
                for x in range(aw):
                    v = fr[base + x]
                    if (v > thr) if args.dark else (v < thr):
                        s += x
                        c += 1
            cxs.append((s / c) / aw if c else 0.5)
        else:
            fracs.append(0.0)
            cxs.append(0.5)

        if n_expect and i + 1 >= n_expect:
            break

    n = len(diffs)
    T = n / fps if n else info["duration"]

    # ---- 静止段 ----
    static_thr = args.static_thr
    if args.auto_static and diffs:
        static_thr = max(0.5, min(args.static_thr,
                                  0.30 * sorted(diffs)[len(diffs) // 2]))

    def segments(mask, min_s):
        out, start = [], None
        for i, ok in enumerate(mask):
            if ok:
                if start is None:
                    start = i
            else:
                if start is not None and (i - start) / fps >= min_s:
                    out.append((start / fps, i / fps))
                start = None
        if start is not None and (n - start) / fps >= min_s:
            out.append((start / fps, n / fps))
        return out

    statics = segments([d < static_thr for d in diffs], args.min_static)
    static_total = sum(b - a for a, b in statics)
    longest_static = max((b - a for a, b in statics), default=0.0)
    # 静止"连续串"：两条静止之间隔着的**非静止**时长 < 0.20s 才算连着。
    # 阈值必须小于"任何一次有意的运镜"（我们最短的是 0.38s 的快速到位）——
    # 否则每次到位都会被当成"没动"，一轮 2s 停住 + 0.38s 推进 × 4 就会被并成 8.7s，
    # 那就不是"片子卡住了"，而是"镜头一次次到位"，两回事。实测：阈值 1.0s → 8.7s（假阳性），
    # 0.20s → 2.3s（与观感一致）。
    clusters = []
    for a, b in statics:
        if clusters and a - clusters[-1][1] < args.cluster_gap:
            clusters[-1] = (clusters[-1][0], b)
        else:
            clusters.append((a, b))
    longest_cluster = max((b - a for a, b in clusters), default=0.0)

    # ---- 取景变化点（像素代理）----
    # 注意：这是**代理指标**。`frac` 是主体带高、`cx` 是墨迹水平重心，
    # 二者都会被"笔在写"本身带偏（写着写着重心就右移了），所以它分不清
    # "镜头动了"和"字长了"。真正做 EDL 的片子请用 `vcamera_report.py`，
    # 那个直接读 cameraAt(t) 的路径，是精确值。
    k = max(1, int(round(0.45 * fps)))
    sf, sc, sl = (smooth_window(fracs, k), smooth_window(cxs, k),
                  smooth_window(lums, k))
    mask = [False]
    for i in range(1, n):
        ds = abs(sf[i] - sf[i - 1]) / max(1e-3, sf[i - 1])
        dc = abs(sc[i] - sc[i - 1])
        dl = abs(sl[i] - sl[i - 1])
        mask.append(ds >= args.reframe_scale or dc >= args.reframe_cx
                    or dl >= args.reframe_lum)
    reframes = []
    for a, b in segments(mask, 0.0):
        if reframes and a - reframes[-1] < args.reframe_merge:
            continue
        reframes.append(a)
    bounds = [0.0] + [c for c in reframes if c > 0] + [T]
    holds = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
    longest_hold = max(holds, default=T)

    # ---- 景别 ----
    fs = sorted(f for f in fracs if f > 0.005)
    lo = fs[int(0.10 * (len(fs) - 1))] if fs else 0.0
    hi = fs[int(0.90 * (len(fs) - 1))] if fs else 0.0
    scale_range = hi / lo if lo > 1e-4 else 0.0

    # ---- EDL（可选）：给了就按剪辑点分段查景别重复 ----
    cuts, shot_lens, per_shot, repeats = [], [], [], 0
    if args.cuts:
        cuts = sorted(float(x) for x in
                      open(args.cuts).read().replace(",", "\n").split()
                      if x.strip() and not x.startswith("#"))
        cuts = [c for c in cuts if 0 < c < T]
        cb = [0.0] + cuts + [T]
        shot_lens = [cb[i + 1] - cb[i] for i in range(len(cb) - 1)]
        for i in range(len(cb) - 1):
            seg = [fracs[j] for j in range(len(fracs))
                   if cb[i] <= j / fps < cb[i + 1]]
            per_shot.append(sorted(seg)[len(seg) // 2] if seg else 0.0)
        repeats = sum(1 for i in range(1, len(per_shot))
                      if scale_label(per_shot[i]) == scale_label(per_shot[i - 1]))

    return dict(info=info, T=T, n=n, static_thr=static_thr,
                diffs_mean=(sum(diffs) / n if n else 0.0),
                statics=statics, static_total=static_total,
                longest_static=longest_static, clusters=clusters,
                longest_cluster=longest_cluster,
                reframes=reframes, holds=holds, longest_hold=longest_hold,
                lo=lo, hi=hi, scale_range=scale_range, subs=subs,
                cuts=cuts, shot_lens=shot_lens, per_shot=per_shot,
                repeats=repeats)


def main():
    ap = argparse.ArgumentParser(description="镜头 / 节奏 / 景别 自检")
    ap.add_argument("video")
    ap.add_argument("--profile", choices=list(PROFILES), default="mv")
    ap.add_argument("--sample-fps", type=float, default=10.0)
    ap.add_argument("--static-thr", type=float, default=0.80,
                    help="帧差（0-255 灰度绝对差均值）低于它当静止")
    ap.add_argument("--auto-static", action="store_true")
    ap.add_argument("--min-static", type=float, default=1.0)
    ap.add_argument("--ink-thr", type=int, default=170)
    ap.add_argument("--ink-thr-dark", type=int, default=150)
    ap.add_argument("--dark", action="store_true", help="暗背景（主体是亮的）")
    ap.add_argument("--reframe-scale", type=float, default=0.12,
                    help="景别相对变化 >= 这个数算换取景")
    ap.add_argument("--reframe-cx", type=float, default=0.07,
                    help="主体水平重心移动 >= 画面宽的这个比例算换取景")
    ap.add_argument("--reframe-lum", type=float, default=6.0,
                    help="画面中位亮度变化 >= 这个数算换取景")
    ap.add_argument("--reframe-merge", type=float, default=0.80)
    ap.add_argument("--cuts", help="剪辑点表（一行一个秒数）")
    ap.add_argument("--camera", help="相机关键帧 json（页面渲染类作品）；给了就用它精确算 "
                                     "C3/C4，覆盖像素代理——避免『笔在写』被误当成『镜头在动』")
    ap.add_argument("--camera-offset", type=float, default=0.0,
                    help="相机关键帧是绝对歌曲时间时，片内 t = 歌曲 t - offset")
    ap.add_argument("--max-static", type=float, default=None)
    ap.add_argument("--max-static-cluster", type=float, default=None)
    ap.add_argument("--cluster-gap", type=float, default=0.20,
                    help="两条静止之间非静止时长 < 这个数才算连着（默认 0.2s，短于任何一次有意运镜）")
    ap.add_argument("--max-static-ratio", type=float, default=None)
    ap.add_argument("--max-hold", type=float, default=None)
    ap.add_argument("--min-scale-range", type=float, default=None)
    ap.add_argument("--max-repeats", type=int, default=None)
    ap.add_argument("--json")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        sys.exit("没有这个文件：" + args.video)
    p = dict(PROFILES[args.profile])
    for key in ("max_static", "max_static_cluster", "max_hold",
                "min_scale_range", "max_repeats"):
        v = getattr(args, key)
        if v is not None:
            p[key] = v
    args.max_static, args.max_static_cluster = p["max_static"], p["max_static_cluster"]
    args.max_hold, args.min_scale_range = p["max_hold"], p["min_scale_range"]
    args.max_repeats = p["max_repeats"]

    d = analyse(args)
    info, T = d["info"], d["T"]

    # 相机路径（精确）覆盖像素代理
    cam = None
    if args.camera:
        import json as _json
        _j = _json.load(open(args.camera))
        _k = _j["keys"] if isinstance(_j, dict) else _j
        import importlib.util as _iu
        _spec = _iu.spec_from_file_location(
            "vcam", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "vcamera_report.py"))
        _vc = _iu.module_from_spec(_spec)
        _spec.loader.exec_module(_vc)
        _k = sorted(_k, key=lambda x: x["t"])
        _off = args.camera_offset
        if _off:
            _k = [dict(x, t=x["t"] - _off) for x in _k]
        _k = [x for x in _k if -1e-6 <= x["t"] <= T + 1e-6]
        class _CamArgs:          # vcamera_report.analyse 需要的参数（给默认值）
            step_zoom = 0.12
            step_pan = 0.07
            merge = 0.80
        cam = _vc.analyse(_k, T, args.sample_fps, _CamArgs())

    print("== vshot_report ==  " + args.video)
    print("   %dx%d  %.3ffps  %.2fs  档位=%s  采样=%.0ffps  静阈=%.2f"
          % (info["width"], info["height"], info["fps"], T, args.profile,
             args.sample_fps, d["static_thr"]))
    print()

    fails = []

    print("-- C1/C2 静止 --")
    print("   平均帧差 %.2f（0-255 灰度）" % d["diffs_mean"])
    print("   静止段 %d 段，共 %.2fs = %.0f%%"
          % (len(d["statics"]), d["static_total"],
             100 * d["static_total"] / max(1e-6, T)))
    ok1 = d["longest_static"] <= args.max_static
    print(V.result_line("最长静止段", "%.2fs" % d["longest_static"],
                        "<=%.2fs" % args.max_static, ok1))
    ok2 = d["longest_cluster"] <= args.max_static_cluster
    print(V.result_line("最长连续静止串", "%.2fs" % d["longest_cluster"],
                        "<=%.2fs" % args.max_static_cluster, ok2))
    ratio = d["static_total"] / max(1e-6, T)
    print("   （参考值，不判）静止总量占比 %.0f%%   静止段 %d 段 → 连续串 %d 组"
          % (100 * ratio, len(d["statics"]), len(d["clusters"])))
    for a, b in sorted(d["statics"], key=lambda s: -(s[1] - s[0]))[:6]:
        print("      %7.2fs-%7.2fs %5.2fs%s"
              % (a, b, b - a, "  <<< 超限" if b - a > args.max_static else ""))
    if not ok1:
        fails.append("静止段超长")
    if not ok2:
        fails.append("静止段连续串过长")
    print()

    print("-- C3 取景 --" + ("（相机路径，精确）" if cam else "（像素代理）"))
    if cam:
        print("   取景变化点 %d 个 = %.2f 次/秒" % (len(cam["pts"]), len(cam["pts"]) / T))
        ok3 = cam["longest"] <= args.max_hold
        print(V.result_line("最长一个取景", "%.2fs" % cam["longest"],
                            "<=%.1fs" % args.max_hold, ok3))
        if not ok3:
            fails.append("一个取景顶太久")
        print()
        print("-- C4 景别（字高占画面高，相机路径）--")
        print("   %.1f%% -> %.1f%%（p10/p90）= %.2fx"
              % (cam["p10"] * 100, cam["p90"] * 100, cam["ratio"]))
        ok4 = cam["ratio"] >= args.min_scale_range
        print(V.result_line("景别动态范围", "%.2fx" % cam["ratio"],
                            ">=%.2fx" % args.min_scale_range, ok4))
        if not ok4:
            fails.append("景别呆板")
        print()
        print("-- 字幕带（供 vsubtitle_check 交叉核对）--")
        sb0 = [s for s in d["subs"] if s]
        if sb0:
            ys0 = sorted(s[0] for s in sb0)
            ye0 = sorted(s[1] for s in sb0)
            print("   %d/%d 帧检到字幕带；顶边中位 %.1f%%  底边中位 %.1f%%"
                  % (len(sb0), len(d["subs"]), ys0[len(ys0) // 2] * 100,
                     ye0[len(ye0) // 2] * 100))
        print()
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump({**d, "camera": cam}, f, ensure_ascii=False, indent=1)
            print("   原始数据 -> " + args.json)
        print("== 结论：" + ("全部 PASS" if not fails else "FAIL -> " + "、".join(fails)))
        return 0 if not fails else 1
    if d["reframes"]:
        print("   取景变化点 %d 个：%s" % (len(d["reframes"]),
              "、".join("%.1fs" % c for c in d["reframes"][:16])))
    else:
        print("   取景变化点 0 个（全片一个取景）")
    ok3 = d["longest_hold"] <= args.max_hold
    print(V.result_line("最长一个取景", "%.2fs" % d["longest_hold"],
                        "<=%.1fs" % args.max_hold, ok3))
    if not ok3:
        fails.append("一个取景顶太久")
    print()

    print("-- C4 景别（主体高度 / 画面高度）--")
    print("   %.1f%% -> %.1f%%（10/90 分位）= %.2fx   档位：%s -> %s"
          % (d["lo"] * 100, d["hi"] * 100, d["scale_range"],
             scale_label(d["lo"]), scale_label(d["hi"])))
    print("   注：判据只看**比例**（比值与画幅/题材无关）；'档位'名字按"
          "「单一主体高度」口径，9:16 全身人物 ~60% 在 16:9 口径下会误称'大特写'。")
    ok4 = d["scale_range"] >= args.min_scale_range
    print(V.result_line("景别动态范围", "%.2fx" % d["scale_range"],
                        ">=%.2fx" % args.min_scale_range, ok4))
    if not ok4:
        fails.append("景别呆板")
    print()

    if d["cuts"]:
        print("-- C5 剪辑点（EDL）--")
        print("   剪辑点 %d 个，镜头 %d 个" % (len(d["cuts"]), len(d["shot_lens"])))
        sl = sorted(d["shot_lens"])
        print("   镜头长度 中位 %.2fs  最短 %.2fs  最长 %.2fs"
              % (sl[len(sl) // 2], sl[0], sl[-1]))
        ok5 = d["repeats"] <= args.max_repeats
        print(V.result_line("相邻镜头同景别", "%d 次" % d["repeats"],
                            "<=%d" % args.max_repeats, ok5))
        seq = ["%d:%s@%.0f%%" % (i + 1, scale_label(f), f * 100)
               for i, f in enumerate(d["per_shot"])]
        for i in range(0, len(seq), 6):
            print("      " + "  ".join(seq[i:i + 6]))
        if not ok5:
            fails.append("相邻镜头同景别过多")
        print()

    print("-- 字幕带（供 vsubtitle_check 交叉核对）--")
    sb = [s for s in d["subs"] if s]
    if sb:
        ys = sorted(s[0] for s in sb)
        ye = sorted(s[1] for s in sb)
        print("   %d/%d 帧检到字幕带；顶边中位 %.1f%%  底边中位 %.1f%%"
              % (len(sb), len(d["subs"]), ys[len(ys) // 2] * 100,
                 ye[len(ye) // 2] * 100))
    else:
        print("   没有检到字幕带（无字幕 / 字幕过大 / 需要 --dark）")
    print()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print("   原始数据 -> " + args.json)

    print("== 结论：" + ("全部 PASS" if not fails else "FAIL -> " + "、".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
