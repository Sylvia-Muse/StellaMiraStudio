#!/usr/bin/env python3
"""vsubtitle_check —— 字幕排版自检（安全区 / 行数 / 字号 / 底边距 / 与主体打架）。

怎么找字幕：用**横向梯度**而不是亮度阈值。
  墨点、人物、裙子都是大块平滑区域，横向梯度接近 0；
  汉字笔画在这种尺度上是高频的，一行字会有几百个"边"。
  这样亮底（水墨）和暗底（人物）用同一套逻辑，不需要切模式。

判据（默认 16:9 横屏）：
  行数        <= 2
  字号高度    3.0% – 7.0% 画面高
  左右安全区  >= 5% 画面宽（SMPTE action safe 88%，取更严的 90%）
  底边距      >= 10% 画面高（B 站网页/H5 进度条 + 弹幕输入框会压住底部）
  字幕带      不得进入最底部 8%（UI 区）
  与主体重叠  字幕 bbox 上方 4% 高度内，主体像素占比 > 3% → 警告（不判 FAIL）

用法：
  python3.14 scripts/vsubtitle_check.py <video>
  python3.14 scripts/vsubtitle_check.py <video> --band-y0 0.70 --debug /tmp/sub.png
退出码：0 全 PASS / 1 有 FAIL。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vcommon as V  # noqa: E402


def frames_with_grad(path, aw, ah, fps, band_y0):
    """yield (t, rows_grad, frame) —— rows_grad 只算 band_y0 以下那些行。"""
    n = 0
    for fr in V.gray_frames(path, aw, ah, fps):
        y0 = int(band_y0 * ah)
        rows = []
        for y in range(y0, ah):
            base = y * aw
            c = 0
            for x in range(2, aw):
                if abs(fr[base + x] - fr[base + x - 2]) >= 28:
                    c += 1
            rows.append(c)
        yield n / fps, rows, fr
        n += 1


def find_text_bands(rows, aw, ah, band_y0, min_h_frac, max_h_frac):
    """把梯度剖面切成"文字行"。返回 [(y0,y1)] 的绝对行号。

    阈值必须**跟着这帧自己的噪声走**。绝对阈值在"裙子褶子 / 星空 / 纸纹"这类
    有底噪的画面上会把整片主体都当字（实测竖屏切片：底噪 10–35，真字幕 57–140，
    固定阈值 3 完全分不开）；噪声很低时（水墨纸面，底噪 1–3）固定阈值又会把
    纸纹当字。所以用两条：
        thr = max(6, 2.5 × 该区行梯度的中位数)     —— 行级门槛
        带内峰值 >= max(thr, 8 × 中位数)          —— 带级门槛（真汉字笔画很尖）
    """
    y_off = int(band_y0 * ah)
    if not rows:
        return []
    srt = sorted(rows)
    base = srt[len(srt) // 2]
    thr = max(6, int(round(2.5 * base)))
    peak_need = max(thr, int(round(8.0 * base)))
    min_rows = max(2, int(min_h_frac * ah))
    max_rows = int(max_h_frac * ah)

    out, start = [], None
    for i, c in enumerate(rows + [0]):
        if c >= thr:
            if start is None:
                start = i
        else:
            if start is not None:
                seg = rows[start:i]
                if min_rows <= i - start <= max_rows and max(seg) >= peak_need:
                    out.append((y_off + start, y_off + i))
                start = None
    return out


def group_lines(bands, ah, gap_frac=0.030):
    """把上下相邻（间隙 < gap_frac）的行合成"字幕块"。"""
    blocks = []
    for b in bands:
        if blocks and b[0] - blocks[-1][-1][1] < gap_frac * ah:
            blocks[-1].append(b)
        else:
            blocks.append([b])
    return blocks


def col_coverage(fr, aw, y0, y1):
    """这一带里"有边"的列占比。汉字有字距/笔间空隙（0.3–0.8）；
    连续的边缘线（裙摆、地平线、边框）几乎是 1.0。用来区分"字"和"线"。"""
    cols = [0] * aw
    for y in range(y0, y1):
        base = y * aw
        for x in range(2, aw):
            if abs(fr[base + x] - fr[base + x - 2]) >= 28:
                cols[x] = 1
    return sum(cols) / aw


def x_extent(fr, aw, y0, y1, gap_frac=0.015):
    """这一带的横向范围 = **最长的一段连续"有边"列**（允许字距小空隙）。

    为什么不能取 min/max：人物剪影、袖口、裙摆的竖边在一整带里每一行都有梯度，
    一两根孤立的列就能把 bbox 从 30–70% 撑成 7–92%（实测竖屏切片）。
    汉字的列是**成片连续**的（字距 3–8%），剪影的列是**孤立**的 —— 只留最长的那一段。
    """
    counts = [0] * aw
    for y in range(y0, y1):
        base = y * aw
        for x in range(2, aw):
            if abs(fr[base + x] - fr[base + x - 2]) >= 28:
                counts[x] += 1
    on = [c > 0 for c in counts]
    gap = max(1, int(gap_frac * aw))
    runs, start, miss = [], None, 0
    for x in range(aw):
        if on[x]:
            if start is None:
                start = x
            miss = 0
        elif start is not None:
            miss += 1
            if miss > gap:
                runs.append((start, x - miss))
                start, miss = None, 0
    if start is not None:
        runs.append((start, aw - 1))
    if not runs:
        return (0, 0)
    return max(runs, key=lambda r: r[1] - r[0])


def main() -> int:
    ap = argparse.ArgumentParser(description="字幕排版自检")
    ap.add_argument("video")
    ap.add_argument("--fps", type=float, default=2.0, help="抽帧率")
    ap.add_argument("--width", type=int, default=640, help="分析宽度")
    ap.add_argument("--band-y0", type=float, default=0.66,
                    help="从画面高度的这个比例往下找字幕")
    ap.add_argument("--min-h", type=float, default=0.008,
                    help="单行字幕的最小高度（占画面高）")
    ap.add_argument("--max-h", type=float, default=0.055,
                    help="单行字幕的最大高度（占画面高）；超过就是主体不是字")
    ap.add_argument("--max-lines", type=int, default=2)
    ap.add_argument("--min-bottom", type=float, default=0.78,
                    help="字幕带底边至少在画面高度的这个比例以下")
    ap.add_argument("--align", choices=["center", "any"], default="center",
                    help="只认水平居中的行（默认 center，排掉主体/左对齐装饰字）")
    ap.add_argument("--center-tol", type=float, default=0.22)
    ap.add_argument("--max-col-cov", type=float, default=0.85,
                    help="带内'有边的列'占比上限；连续横线接近 1.0，汉字 0.3-0.8")
    ap.add_argument("--min-font", type=float, default=0.030)
    ap.add_argument("--max-font", type=float, default=0.070)
    ap.add_argument("--safe-x", type=float, default=0.05)
    ap.add_argument("--safe-bottom", type=float, default=0.10)
    ap.add_argument("--ui-zone", type=float, default=0.08)
    ap.add_argument("--ink-thr", type=int, default=170)
    ap.add_argument("--debug", help="把某一帧画上检测框存成 PNG")
    ap.add_argument("--json")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        sys.exit("没有这个文件：" + args.video)
    info = V.probe(args.video)
    W, H = info["width"], info["height"]
    aw = args.width
    ah = max(48, int(round(aw * H / W)))
    bg_light = True

    worst = dict(lines=0, font=0.0, x0=1.0, x1=0.0, bottom=1.0, top=1.0, n=0)
    overlaps = 0
    seen = 0
    sample = None
    dbg = None

    for t, rows, fr in frames_with_grad(args.video, aw, ah, args.fps, args.band_y0):
        seen += 1
        med = V.median_of(fr)
        bg_light = med > 128
        bs = find_text_bands(rows, aw, ah, args.band_y0, args.min_h, args.max_h)
        # 只要"像一行字幕"的带：
        #   宽度 15%–93%、底边在画面下部 22% 内、水平居中（字幕默认居中）
        # 后两条是为了把"正在写的字""人物轮廓"这类主体排除掉。
        keep = []
        for y0, y1 in bs:
            lo, hi = x_extent(fr, aw, y0, y1)
            if hi <= lo:
                continue
            wfrac = (hi - lo) / aw
            if not (0.15 <= wfrac <= 0.93):
                continue
            if y1 / ah < args.min_bottom:
                continue
            if col_coverage(fr, aw, y0, y1) > args.max_col_cov:
                continue        # 整条横线（裙摆/边框），不是字
            if args.align == "center":
                if abs((lo + hi) / 2 / aw - 0.5) > args.center_tol:
                    continue
            keep.append((y0, y1, lo, hi))
        # 按垂直相邻分组，取"最高的那一块"当字幕（其它都当装饰/主体）
        if keep:
            blocks = group_lines([(k[0], k[1]) for k in keep], ah)
            best = max(blocks, key=lambda bk: bk[-1][1] - bk[0][0])
            keep = [k for k in keep if any(k[0] == b[0] and k[1] == b[1] for b in best)]
        if not keep:
            continue
        # 主体重叠：字幕顶边上方 4% 高度内是否还有大量"墨"
        y_sub_top = min(k[0] for k in keep)
        up0 = max(0, y_sub_top - int(0.04 * ah))
        prof = V.row_profile(fr, aw, ah, args.ink_thr, above=not bg_light)
        above_ink = sum(prof[up0:y_sub_top])
        above_area = max(1, (y_sub_top - up0) * aw)
        if above_ink / above_area > 0.03:
            overlaps += 1

        if len(keep) > worst["lines"] or sample is None:
            sample = (t, keep, fr)
        worst["lines"] = max(worst["lines"], len(keep))
        worst["font"] = max(worst["font"], max((k[1] - k[0]) / ah for k in keep))
        worst["x0"] = min(worst["x0"], min(k[2] for k in keep) / aw)
        worst["x1"] = max(worst["x1"], max(k[3] for k in keep) / aw)
        worst["bottom"] = min(worst["bottom"], max(k[1] for k in keep) / ah)
        worst["top"] = min(worst["top"], min(k[0] for k in keep) / ah)
        worst["n"] += 1

        if args.debug and dbg is None and len(keep) >= worst["lines"]:
            dbg = (t, keep)

    print("== vsubtitle_check ==  " + args.video)
    print("   %dx%d  %.2fs  抽 %.1ffps  分析宽 %d  找字幕区 y>=%.0f%%"
          % (W, H, info["duration"], args.fps, aw, args.band_y0 * 100))
    print()

    if worst["n"] == 0:
        print("[FAIL] 没检到任何字幕行。")
        print("       若无字幕是有意的，请跳过本条；若有字幕，调 --band-y0 / --min-h。")
        return 1

    fails = []
    print("-- 字幕几何（%d/%d 帧检到字幕）--" % (worst["n"], seen))
    print("   行数上限 %d   字号 %.2f%%H   横向 x %.1f%%→%.1f%%   "
          "自己 bbox 底边距 %.1f%%"
          % (worst["lines"], worst["font"] * 100, worst["x0"] * 100,
             worst["x1"] * 100, (1 - worst["bottom"]) * 100))
    okL = worst["lines"] <= args.max_lines
    print(V.result_line("字幕行数", "%d 行" % worst["lines"],
                        "<=%d 行" % args.max_lines, okL))
    okF = args.min_font <= worst["font"] <= args.max_font
    print(V.result_line("字号高度", "%.2f%%" % (worst["font"] * 100),
                        "%.1f%%-%.1f%%" % (args.min_font * 100, args.max_font * 100), okF))
    okX = worst["x0"] >= args.safe_x and (1 - worst["x1"]) >= args.safe_x
    print(V.result_line("左右安全区", "左%.1f%% 右%.1f%%"
                        % (worst["x0"] * 100, (1 - worst["x1"]) * 100),
                        "各>=%.0f%%" % (args.safe_x * 100), okX))
    okB = (1 - worst["bottom"]) >= args.safe_bottom
    print(V.result_line("底边距", "%.1f%%" % ((1 - worst["bottom"]) * 100),
                        ">=%.0f%%" % (args.safe_bottom * 100), okB))
    okU = worst["bottom"] <= 1 - args.ui_zone
    print(V.result_line("不进底部 UI 区", "最低点 %.1f%%"
                        % (worst["bottom"] * 100),
                        "<=%.0f%%" % ((1 - args.ui_zone) * 100), okU))
    if not okL:
        fails.append("字幕超过 %d 行" % args.max_lines)
    if not okF:
        fails.append("字号不在区间")
    if not okX:
        fails.append("字幕越左右安全区")
    if not okB:
        fails.append("字幕压到底部 UI 区")
    if not okU:
        fails.append("字幕进入底部 %.0f%% UI 带" % (args.ui_zone * 100))
    print()

    print("-- 与主体打架 --")
    ratio = overlaps / max(1, worst["n"])
    print("   %d/%d 帧字幕紧贴主体（上方 4%% 高度内墨迹 >3%%）= %.0f%%"
          % (overlaps, worst["n"], ratio * 100))
    print("   %s（警告项，不判 FAIL：字幕压人物是审美选择，但要知道自己在做）"
          % ("[WARN] 字幕压在主体上" if ratio > 0.30 else "[PASS] 字幕与主体分离"))
    print()

    if sample:
        t, keep, fr = sample
        print("-- 最深的一帧（t=%.2fs，%d 行）--" % (t, len(keep)))
        for y0, y1, lo, hi in keep:
            print("   y %.1f%%-%.1f%%   x %.1f%%-%.1f%%   高 %.2f%%H"
                  % (y0 / ah * 100, y1 / ah * 100, lo / aw * 100, hi / aw * 100,
                     (y1 - y0) / ah * 100))
        print()

    if args.debug and dbg:
        from PIL import Image, ImageDraw
        t = dbg[0]
        import subprocess
        tmp = "/tmp/_vsub_frame.png"
        subprocess.run([V.FFMPEG, "-v", "error", "-y", "-ss", "%.3f" % t,
                        "-i", args.video, "-frames:v", "1", tmp], check=False)
        if os.path.exists(tmp):
            im = Image.open(tmp).convert("RGB")
            dr = ImageDraw.Draw(im)
            sx, sy = im.width / aw, im.height / ah
            for y0, y1, lo, hi in dbg[1]:
                dr.rectangle([lo * sx, y0 * sy, hi * sx, y1 * sy],
                             outline=(255, 0, 0), width=3)
            dr.rectangle([0, (1 - args.ui_zone) * im.height,
                          im.width, im.height], outline=(0, 120, 255), width=2)
            dr.rectangle([args.safe_x * im.width, 0,
                          (1 - args.safe_x) * im.width,
                          (1 - args.safe_bottom) * im.height],
                         outline=(0, 200, 0), width=2)
            im.save(args.debug)
            print("   调试图（红=字幕框 绿=安全区 蓝=UI 区）-> " + args.debug)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(worst, f, ensure_ascii=False, indent=1)

    print("== 结论：" + ("全部 PASS" if not fails else "FAIL -> " + "；".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
