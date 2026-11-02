#!/opt/homebrew/bin/python3.14
"""出画自检：任何一帧，墨迹（灰度 < 阈值）的左右包围盒都不能碰到画面边缘 3% 以内。

用法：
  check_overflow.py <video.mp4> [--step 0.5] [--thr 170] [--margin 0.03] [--start 0]

输出：越界帧数 / 总帧数、最严重的 5 个时间点、越界像素占画面宽度的比例，
以及**越界列上的墨迹浓度证据**。

为什么要浓度证据："越界 0.5% 画面宽"是个几何量，它说不清那点墨到底是"几乎看不见的
淡影"还是"一块实墨"。所以对被判越界的那几列，额外统计它们最暗像素的
**alpha 等效值 = (255 - gray) / 255**：

  越界列中位 alpha  < 0.35   → 通过（肉眼不可见的淡影）
  任一帧出现 alpha > 0.6     → 直接判 FAIL（那是实墨贴着边，必须重渲）
"""
import argparse, os, subprocess, tempfile
from PIL import Image

FF = "/opt/homebrew/bin/ffmpeg"


def _stat(vals):
    if not vals:
        return None
    xs = sorted(vals)
    n = len(xs)
    return {
        "n": n,
        "mean": sum(xs) / n,
        "min": xs[0],
        "median": xs[n // 2],
        "max": xs[-1],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--thr", type=int, default=170,
                    help="灰度低于它算墨迹（默认 170：暗角会把纸压到约 199，用 200 会把暗角误判成墨）")
    ap.add_argument("--margin", type=float, default=0.03, help="安全区百分比")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    tmp = tempfile.mkdtemp()
    # 精确抽帧：按 1/step fps 抽，避免 -ss 反复seek的精度问题
    fps = 1.0 / a.step
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", a.video, "-vf", "fps=%g,scale=960:540" % fps,
                    os.path.join(tmp, "f_%04d.png")], check=True)
    files = sorted(os.listdir(tmp))
    W = H = None
    rows = []
    for i, f in enumerate(files):
        t = a.start + i * a.step
        im = Image.open(os.path.join(tmp, f)).convert("L")
        if W is None:
            W, H = im.size
        px = im.load()
        # 逐列找墨迹，同时记下每列最暗的像素（浓度证据要用）
        col_has = [False] * W
        col_min = [255] * W
        total_ink = 0
        for x in range(W):
            best = 255
            for y in range(0, H, 2):
                v = px[x, y]
                if v < a.thr:
                    col_has[x] = True
                    total_ink += 1
                    if v < best:
                        best = v
            col_min[x] = best
        cols = [x for x in range(W) if col_has[x]]
        if not cols or total_ink == 0:
            rows.append((t, None, None, 0, 0.0, None))
            continue
        x0, x1 = cols[0], cols[-1]
        left_lim = int(W * a.margin)
        right_lim = int(W * (1 - a.margin))
        over_idx = []
        if x0 <= left_lim:
            over_idx += [x for x in range(0, left_lim + 1) if col_has[x]]
        if x1 >= right_lim:
            over_idx += [x for x in range(right_lim, W) if col_has[x]]
        over = len(over_idx)
        frac = over / W                          # 越界像素占**画面宽度**的比例（验收口径）

        # 浓度留到原分辨率再量（见后处理 pass）
        rows.append((t, x0 / W, x1 / W, over, frac, None))

    bad = [r for r in rows if r[1] is not None and r[3] > 0]

    # ---- 原分辨率复核浓度 ----
    # 上面是 960 宽抽帧，**2×2 平均会把边缘那一两个像素淡影平均掉**：
    # 同一批帧在 960 宽量到中位 alpha 0.349（刚好"通过"），回原分辨率是 0.357（不通过）。
    # 浓度这种"一两个像素"的量必须在原分辨率上量。
    if bad:
        nat = os.path.join(tmp, "nat.png")
        fixed = []
        for t, x0, x1, over, frac, _ in bad:
            subprocess.run([FF, "-v", "error", "-y", "-ss", "%.3f" % t, "-i", a.video,
                            "-frames:v", "1", nat], check=True)
            nim = Image.open(nat).convert("L")
            NW, NH = nim.size
            npx = nim.load()
            nl = int(NW * a.margin)
            idx = list(range(0, nl + 1)) + list(range(NW - nl, NW))
            al = []
            for x in idx:
                best = 255
                for y in range(NH):
                    v = npx[x, y]
                    if v < best:
                        best = v
                if best < a.thr:
                    al.append((255 - best) / 255.0)
            if al:
                al.sort()
                fixed.append((t, x0, x1, over, frac, (al[len(al) // 2], al[-1], len(al))))
            else:
                fixed.append((t, x0, x1, over, frac, (0.0, 0.0, 0)))
        bad = fixed
    print("== 出画自检 %s ==" % a.tag)
    print("视频 %s  抽帧 %d（每 %.1fs） margin=%.0f%% thr=%d"
          % (os.path.basename(a.video), len(rows), a.step, a.margin * 100, a.thr))
    print("越界帧：%d / %d" % (len(bad), len(rows)))
    if bad:
        bad.sort(key=lambda r: -r[4])
        print("最严重 5 帧（附越界列浓度证据）：")
        print("   %-10s %-20s %-14s %-9s %-9s %s" %
              ("时间", "墨迹 x 范围", "越界/960列", "中位alpha", "最暗alpha", "原分辨率越界列"))
        for t, x0, x1, over, frac, al in bad[:8]:
            am, ax, ncol = al if al else (None, None, 0)
            print("   t=%6.2fs  x∈[%.3f, %.3f]      %3d 列       %-9s %-9s %d 列   越界 %.2f%%"
                  % (t, x0, x1, over,
                     ("%.3f" % am) if am is not None else "-",
                     ("%.3f" % ax) if ax is not None else "-",
                     ncol, frac * 100))
    if bad:
        print("   全部越界帧时间：" + "、".join("%.1fs" % r[0] for r in bad))
    worst = max((r[4] for r in bad), default=0.0)

    # ---- 浓度证据汇总 ----
    meds = [r[5][0] for r in bad if r[5] and r[5][0] is not None]
    maxs = [r[5][1] for r in bad if r[5] and r[5][1] is not None]
    print()
    print("-- 越界列浓度证据（alpha 等效值 = (255-gray)/255）--")
    if meds:
        st = _stat(meds)
        print("   越界列的『每列最暗像素』alpha：中位 %.3f  均值 %.3f  最小 %.3f  最大 %.3f"
              % (st["median"], st["mean"], st["min"], st["max"]))
        print("   全部越界帧的最暗 alpha：%.3f" % max(maxs))
        ok_alpha = st["median"] < 0.35 and max(maxs) <= 0.60
        print("   判据：越界列中位 alpha < 0.35 且 无任一帧 alpha > 0.60  ->  %s"
              % ("PASS" if ok_alpha else "FAIL"))
        if max(maxs) > 0.60:
            print("   ！有帧在越界列上出现 alpha=%.3f 的实墨 —— 必须重渲" % max(maxs))
    else:
        ok_alpha = True
        print("   无越界帧，无需浓度证据。")

    print("最严重的一帧越界 %.2f%% 画面宽度" % (worst * 100))
    ok = len(bad) <= 2 and worst < 0.01
    print("判定-几何（≤2 帧 且 越界 < 1%）:", "PASS" if ok else "FAIL")
    print("判定-浓度（越界有多淡）      :", "PASS" if ok_alpha else "FAIL", flush=True)
    return rows, bad


if __name__ == "__main__":
    main()
