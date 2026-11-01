#!/usr/bin/env python3
"""从「有透明通道或深色笔迹」的图里提取笔迹路径（比 edge-path 更好用）。

两种模式：
  --mode alpha   用 alpha 通道当墨（适合立绘、剪影、PNG 素材）
  --mode dark    用亮度阈值当墨（适合扫描的水墨画、白底黑字）

输出与 edge-path.py 同样格式：{"size":[w,h], "points":[[x,y],...]}
"""
import json
import sys
from PIL import Image, ImageFilter

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from importlib import import_module
edge = import_module("edge-path".replace("-", "_")) if False else None


def load_mask(path, mode="alpha", threshold=128, invert=False):
    im = Image.open(path)
    if mode == "alpha":
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        m = im.split()[-1]
    else:
        m = im.convert("L")
        if invert:
            m = m.point(lambda v: 255 - v)
    # 去掉噪点，让轮廓干净
    m = m.filter(ImageFilter.MedianFilter(3))
    return m


def sample(mask, max_points=6000, grid=6, threshold=110):
    w, h = mask.size
    px = mask.load()
    pts = []
    for gy in range(0, h, grid):
        for gx in range(0, w, grid):
            if px[gx, gy] > threshold:
                pts.append((gx / w, gy / h))
    if len(pts) > max_points:
        step = len(pts) / max_points
        pts = [pts[int(i * step)] for i in range(max_points)]
    return pts, (w, h)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst", nargs="?", default="mask-path.json")
    ap.add_argument("--mode", choices=["alpha", "dark"], default="alpha")
    ap.add_argument("--edge", action="store_true", help="只取轮廓（描边），而不是填满")
    ap.add_argument("--threshold", type=int, default=110)
    ap.add_argument("--grid", type=int, default=6)
    ap.add_argument("--max", type=int, default=6000)
    ap.add_argument("--invert", action="store_true")
    ap.add_argument("--smooth", type=int, default=0,
                    help="形态学闭运算的核大小：把内部细节抹掉，只留外轮廓（建议 9~21）")
    a = ap.parse_args()

    mask = load_mask(a.src, a.mode, a.threshold, a.invert)
    if a.smooth > 0:
        # 闭运算：先膨胀再腐蚀 —— 填掉内部的小洞和细节，让轮廓只剩最外一圈
        k = a.smooth | 1
        for _ in range(2):
            mask = mask.filter(ImageFilter.MaxFilter(k))
        for _ in range(2):
            mask = mask.filter(ImageFilter.MinFilter(k))
    if a.edge:
        mask = mask.filter(ImageFilter.FIND_EDGES)
        # 边缘滤波后值很弱，乘一次
        mask = mask.point(lambda v: min(255, v * 6))
    pts, size = sample(mask, a.max, a.grid, a.threshold)
    json.dump({"size": size, "points": pts}, open(a.dst, "w"))
    print("%s → %s：%d 点（mode=%s）" % (a.src, a.dst, len(pts), a.mode))


if __name__ == "__main__":
    main()
