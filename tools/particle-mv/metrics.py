#!/usr/bin/env python3
"""锐度/保真度客观测量。全部定义在 8bit sRGB 灰度上（不线性化，跟后处理链路一致）。

指标：
  edge    mean(|∇I|)：3x3 Sobel 梯度幅值全图平均。传统"边缘强度"，越大越锐。
  lapvar  var(∇²I)：3x3 四邻域 Laplacian 方差，经典清晰度指标。
  hf      高频能量占比：|FFT|² 在归一化半径 > 0.5 的环内能量 / 全频带。
  SER     strong-edge retention：只在参考图"强边"像素（梯度前 3%）上，
          比较待测图的梯度均值 / 参考图梯度均值。1.0=峰锐度保住，<1=被磨钝。
          （只在同一批像素上比，能避开 JPEG 振铃在别处凭空加的高频。）
  psnr/ssim  与参考图比较；SSIM 用 11x11 高斯窗（sigma=1.5）标准实现。

注意：edge / lapvar 对"振铃、噪点被增强"是**不单调**的——JPEG 的 Gibbs 振铃会让
edge 变大而画面变脏。所以对照实验里同时给 psnr/ssim/SER，别只看 edge。

用法：
  /usr/bin/python3 scripts/mv_metrics.py stats label=path [...]                 # 绝对指标
  /usr/bin/python3 scripts/mv_metrics.py vs ref.png label=path [...]           # 顺带算保真度
"""
import sys

import numpy as np
from PIL import Image

# 区域：(名字, x0, x1, y0, y1)，1080p 坐标
REGIONS = [
    ("all", 0, 1920, 0, 1080),
    ("lyric", 420, 1500, 880, 1000),   # 字幕带：DOM 文本，最能看出中间格式/重采样损失
    ("hud", 16, 340, 16, 150),         # 左上角代码 HUD：小字号，最考验编码
    ("core", 700, 1220, 250, 880),     # 中央粒子团：WebGL 细线/粒子
]


def load(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(np.float32)


def gray(a):
    return 0.2126 * a[:, :, 0] + 0.7152 * a[:, :, 1] + 0.0722 * a[:, :, 2]


def sobel(g):
    p = np.pad(g, 1, mode="edge")
    gx = ((p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) -
          (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])) / 8.0
    gy = ((p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) -
          (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])) / 8.0
    return np.hypot(gx, gy)


def laplacian(g):
    p = np.pad(g, 1, mode="edge")
    return (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] - 4 * g)


def hf_ratio(g):
    f = np.fft.fftshift(np.abs(np.fft.fft2(g - g.mean())) ** 2)
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot((yy - h / 2) / (h / 2), (xx - w / 2) / (w / 2))
    return float(f[r > 0.5].sum() / f.sum())


def _gk(sigma=1.5, r=5):
    x = np.arange(-r, r + 1)
    k = np.exp(-(x ** 2) / (2 * sigma ** 2))
    return k / k.sum()


def gblur(a, sigma=1.5):
    k = _gk(sigma)
    r = len(k) // 2
    p = np.pad(a, ((0, 0), (r, r)), mode="reflect")
    t = sum(k[i] * p[:, i:i + a.shape[1]] for i in range(len(k)))
    p = np.pad(t, ((r, r), (0, 0)), mode="reflect")
    return sum(k[i] * p[i:i + a.shape[0], :] for i in range(len(k)))


def ssim(a, b):
    ga, gb = gray(a), gray(b)
    muA, muB = gblur(ga), gblur(gb)
    sAA = gblur(ga * ga) - muA ** 2
    sBB = gblur(gb * gb) - muB ** 2
    sAB = gblur(ga * gb) - muA * muB
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    m = ((2 * muA * muB + c1) * (2 * sAB + c2)) / ((muA ** 2 + muB ** 2 + c1) * (sAA + sBB + c2))
    return float(m.mean())


def psnr(a, b):
    mse = float(np.mean((a - b) ** 2))
    return 99.0 if mse <= 1e-12 else float(10 * np.log10(255.0 ** 2 / mse))


def ser(codec_sm, ref_sm, frac=0.03):
    """强边保留率：只在参考图梯度最强的 frac 比例像素上比梯度。"""
    thr = np.quantile(ref_sm, 1 - frac)
    m = ref_sm >= thr
    return float(codec_sm[m].mean() / ref_sm[m].mean())


def stats(path, ref=None):
    a = load(path)
    g = gray(a)
    sm, lp = sobel(g), laplacian(g)
    row = {}
    for name, x0, x1, y0, y1 in REGIONS:
        row["edge_" + name] = float(sm[y0:y1, x0:x1].mean())
        row["lap_" + name] = float(lp[y0:y1, x0:x1].var())
    row["hf_all"] = hf_ratio(g)
    row["mean_all"] = float(g.mean())
    if ref is not None:
        r = load(ref)
        rg = gray(r)
        rsm = sobel(rg)
        row["psnr"] = psnr(a, r)
        row["ssim"] = ssim(a, r)
        row["ser"] = ser(sm, rsm)
        # 分区域保真度（区域小，按块算 psnr/ssim）
        for name, x0, x1, y0, y1 in REGIONS[1:]:
            row["psnr_" + name] = psnr(a[y0:y1, x0:x1], r[y0:y1, x0:x1])
            row["ser_" + name] = ser(sm[y0:y1, x0:x1], rsm[y0:y1, x0:x1])
    return row


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return
    ref = None
    if argv[0] == "vs":
        ref = argv[1]
        argv = argv[2:]
    elif argv[0] == "stats":
        argv = argv[1:]
    items = []
    for spec in argv:
        label, _, path = spec.partition("=")
        items.append((label, path))
    rows = [(label, stats(path, ref)) for label, path in items]
    keys = ["edge_all", "lap_all", "hf_all", "edge_lyric", "edge_hud", "edge_core", "mean_all"]
    if ref:
        keys += ["psnr", "ssim", "ser", "psnr_lyric", "ser_lyric", "psnr_hud", "ser_hud"]
    hdr = {"edge_all": "edge", "lap_all": "lapvar", "hf_all": "hf",
           "edge_lyric": "e_lyr", "edge_hud": "e_hud", "edge_core": "e_core",
           "mean_all": "mean"}
    print("%-22s " % "label" + " ".join("%9s" % hdr.get(k, k) for k in keys))
    for label, r in rows:
        cells = []
        for k in keys:
            v = r.get(k)
            cells.append("%9.4f" % v if v is not None else "%9s" % "-")
        print("%-22s " % label + " ".join(cells))
    if ref:
        print("\n参考 = %s" % ref)


if __name__ == "__main__":
    main()
