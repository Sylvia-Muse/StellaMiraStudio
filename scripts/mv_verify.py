#!/usr/bin/env python3
"""终检：在 t=30/100/150 把「视频抽帧」和「同一 t 的 page.screenshot（无损 PNG）」对比。

用法：
  /usr/bin/python3 scripts/mv_verify.py \
      --video data/videos/.../mv_hq.mp4 \
      --sharp data/videos/.../mv_sharp.mp4 \
      --refdir /tmp/mv_ref --times 30,100,150
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mv_metrics import load, gray, sobel, laplacian, hf_ratio, psnr, ssim  # noqa: E402

FFMPEG = "/opt/homebrew/bin/ffmpeg"
HUD = (24, 214, 26, 66)      # "new World();" 文字行（静态 DOM 文本，跨版本可比）
CORE = (700, 1220, 250, 880)


def frame(video, n, out):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", video,
                    "-vf", "select=eq(n\\,%d)" % n, "-frames:v", "1", out], check=True)
    return out


def m(path, ref=None, box=None):
    a = load(path)
    if box:
        x0, x1, y0, y1 = box
        a = a[y0:y1, x0:x1]
    g = gray(a)
    r = {"edge": float(sobel(g).mean()), "lap": float(laplacian(g).var()),
         "mean": float(g.mean())}
    if ref is not None:
        b = load(ref)
        if box:
            x0, x1, y0, y1 = box
            b = b[y0:y1, x0:x1]
        r["psnr"] = psnr(a, b)
        r["ssim"] = ssim(a, b)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--sharp", default="")
    ap.add_argument("--refdir", default="/tmp/mv_ref")
    ap.add_argument("--times", default="30,100,150")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--tmp", default="/tmp/verify")
    a = ap.parse_args()
    os.makedirs(a.tmp, exist_ok=True)
    times = [float(x) for x in a.times.split(",")]

    print("%-6s %-22s %8s %10s %8s %7s %7s %7s" %
          ("t", "样品", "edge", "lapvar", "Δedge", "psnr", "ssim", "mean"))
    summary = []
    for t in times:
        n = int(round(t * a.fps))
        ref = os.path.join(a.refdir, "ref_t%06.1f.png" % t)
        if not os.path.exists(ref):
            print("缺参考帧", ref)
            continue
        base = m(ref)
        row = [("PNG 截图(无损)", base, ref)]
        f = frame(a.video, n, os.path.join(a.tmp, "hq_t%g.png" % t))
        row.append(("本次 mv_hq.mp4", m(f, ref), f))
        if a.sharp:
            fs = frame(a.sharp, n, os.path.join(a.tmp, "sharp_t%g.png" % t))
            row.append(("mv_sharp.mp4", m(fs), fs))   # 内容相位不同，只比绝对指标
        for name, r, _ in row:
            print("%-6g %-22s %8.4f %10.1f %7.1f%% %7s %7s %7.2f" % (
                t, name, r["edge"], r["lap"],
                100 * (r["edge"] / base["edge"] - 1),
                ("%.2f" % r["psnr"]) if "psnr" in r else "-",
                ("%.4f" % r["ssim"]) if "ssim" in r else "-", r["mean"]))
        # 静态文字行（跨版本可比）
        for name, _, path in row:
            rr = m(path, ref, HUD)
            print("      %-18s HUD文字行 edge %7.4f lapvar %8.1f psnr %6s ssim %6s" % (
                name, rr["edge"], rr["lap"],
                ("%.2f" % rr["psnr"]) if "psnr" in rr else "-",
                ("%.4f" % rr["ssim"]) if "ssim" in rr else "-"))
        summary.append((t, row))
    print()


if __name__ == "__main__":
    main()
