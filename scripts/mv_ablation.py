#!/usr/bin/env python3
"""对照实验：同一批无损 PNG 帧，走不同中间格式 / 不同 x264 参数，量化每一步损失。

变体（同一内容、同一 GOP 结构，只改一个变量）：
  png-qp0   PNG 帧 → x264 -qp 0            （无损，理论上=PNG 源，仅 4:2:0 色度损失）
  png-crf12 PNG 帧 → x264 -crf 12 slow     （本次交付用的档位）
  png-crf16 PNG 帧 → x264 -crf 16 medium   （旧 mv_sharp.mp4 的编码参数，但省掉 JPEG）
  jpg95-crf16  PNG → JPEG q95 4:2:0 → x264 -crf 16 medium  （完全复刻旧流水线）

用法：
  /usr/bin/python3 scripts/mv_ablation.py --frames-dir /tmp/ab10 --t 30 --t 5
"""
import argparse
import os
import subprocess
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mv_metrics import load, gray, sobel, laplacian, hf_ratio, psnr, ssim  # noqa: E402

FFMPEG = "/opt/homebrew/bin/ffmpeg"


def sh(cmd):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def make_jpeg(src_dir, dst_dir, quality=95, subsampling=2):
    os.makedirs(dst_dir, exist_ok=True)
    names = sorted(n for n in os.listdir(src_dir) if n.startswith("f_") and n.endswith(".png"))
    total = 0
    for n in names:
        im = Image.open(os.path.join(src_dir, n)).convert("RGB")
        p = os.path.join(dst_dir, n.replace(".png", ".jpg"))
        if not os.path.exists(p):
            im.save(p, quality=quality, subsampling=subsampling)
        total += os.path.getsize(p)
    return len(names), total / max(1, len(names))


def encode(src, out, t_end, crf, preset, gop=250):
    names = os.listdir(src)
    pat = os.path.join(src, "f_%05d.jpg") if any(n.endswith(".jpg") for n in names) else os.path.join(src, "f_%05d.png")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-framerate", "30",
           "-i", pat, "-t", "%.3f" % t_end, "-c:v", "libx264", "-preset", preset]
    cmd += ["-qp", "0"] if crf == 0 else ["-crf", str(crf)]
    cmd += ["-pix_fmt", "yuv420p", "-g", str(gop), "-movflags", "+faststart", out]
    sh(cmd)
    return os.path.getsize(out)


def grab_frame(video, n, out):
    sh([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", video,
        "-vf", "select=eq(n\\,%d)" % n, "-frames:v", "1", out])


def metrics_of(path, ref=None):
    a = load(path)
    g = gray(a)
    r = {"edge": float(sobel(g).mean()), "lap": float(laplacian(g).var()),
         "hf": hf_ratio(g), "mean": float(g.mean())}
    if ref is not None:
        b = load(ref)
        r["psnr"] = psnr(a, b)
        r["ssim"] = ssim(a, b)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", default="/tmp/ab10")
    ap.add_argument("--out-dir", default="/tmp/abl")
    ap.add_argument("--t", type=float, action="append", default=None,
                    help="在这些秒数上取帧比较（按帧号 n=t*fps）")
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args()
    times = a.t or [30.0]
    os.makedirs(a.out_dir, exist_ok=True)

    jdir = os.path.join(a.out_dir, "jpg95")
    n, avg = make_jpeg(a.frames_dir, jdir)
    print("JPEG q95 4:2:0: %d 帧，平均 %.0f KB/帧" % (n, avg / 1024), flush=True)

    t_end = n / a.fps
    sizes = {}
    variants = [
        ("png-qp0", a.frames_dir, 0, "slow"),
        ("png-crf12", a.frames_dir, 12, "slow"),
        ("png-crf16", a.frames_dir, 16, "medium"),
        ("jpg95-crf16", jdir, 16, "medium"),
    ]
    for name, src, crf, preset in variants:
        out = os.path.join(a.out_dir, name + ".mp4")
        sizes[name] = encode(src, out, t_end, crf, preset)

    print("\n== 体积（%.1f 秒片段）" % t_end)
    for k, v in sizes.items():
        print("  %-12s %8.1f MB  %6.1f Mbps" % (k, v / 1e6, v * 8 / t_end / 1e6))

    for t in times:
        nframe = int(round(t * a.fps))
        ref = os.path.join(a.frames_dir, "f_%05d.png" % nframe)
        if not os.path.exists(ref):
            print("跳过 t=%.1f（没有源帧）" % t)
            continue
        rows = [("PNG 源(参考)", metrics_of(ref))]
        for name, _, _, _ in variants:
            f = os.path.join(a.out_dir, "v_%s_t%g.png" % (name, t))
            grab_frame(os.path.join(a.out_dir, name + ".mp4"), nframe, f)
            rows.append((name, metrics_of(f, ref)))
        print("\n== t = %gs（帧 %d）" % (t, nframe))
        print("%-16s %8s %9s %8s %6s %7s %7s %8s" %
              ("变体", "edge", "lapvar", "hf", "Δedge", "psnr", "ssim", "mean"))
        base = rows[0][1]
        for name, r in rows:
            print("%-16s %8.4f %9.1f %8.4f %6.1f%% %7s %7s %8.2f" % (
                name, r["edge"], r["lap"], r["hf"],
                100 * (r["edge"] / base["edge"] - 1),
                ("%.2f" % r["psnr"]) if "psnr" in r else "-",
                ("%.4f" % r["ssim"]) if "ssim" in r else "-",
                r["mean"]))


if __name__ == "__main__":
    main()
