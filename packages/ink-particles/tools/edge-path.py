#!/usr/bin/env python3
"""把一张图（水墨画 / 字 / 剪影）变成"笔迹路径"点列，供 ink-particles 的 setPath() 用。

思路：
  1. 灰度 + 阈值 → 取"墨"的像素
  2. 网格降采样 → 几千个点
  3. 贪心最近邻串成折线 → 输出归一化坐标的 JSON

不追求精确描边，追求"看起来像一笔一笔画上去的"。
"""
import json
import math
import sys
from PIL import Image


def load_points(path, max_points=4000, threshold=128, grid=7):
    im = Image.open(path).convert("L")
    w, h = im.size
    px = im.load()
    pts = []
    for gy in range(0, h, grid):
        for gx in range(0, w, grid):
            if px[gx, gy] < threshold:
                pts.append((gx / w, gy / h))
    if len(pts) > max_points:
        step = len(pts) / max_points
        pts = [pts[int(i * step)] for i in range(max_points)]
    return pts, (w, h)


def chain(pts, max_jump=0.06):
    if not pts:
        return []
    start = min(pts, key=lambda p: (p[1], p[0]))
    left = set(pts)
    left.discard(start)
    out = [start]
    cur = start
    cell = 0.05
    buckets = {}
    for p in left:
        buckets.setdefault((int(p[0] / cell), int(p[1] / cell)), []).append(p)

    while left:
        cx, cy = int(cur[0] / cell), int(cur[1] / cell)
        best, bestd = None, 1e9
        for r in range(0, 4):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    for p in buckets.get((cx + dx, cy + dy), ()):
                        if p not in left:
                            continue
                        d = (p[0] - cur[0]) ** 2 + (p[1] - cur[1]) ** 2
                        if d < bestd:
                            best, bestd = p, d
            if best is not None:
                break
        if best is None or math.sqrt(bestd) > max_jump:
            best = next(iter(left))
        left.discard(best)
        out.append(best)
        cur = best
    return out


def main():
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "path.json"
    pts, size = load_points(src)
    path = chain(pts)
    json.dump({"size": size, "points": path}, open(dst, "w"))
    print("%s → %s：%d 个点（采样 %d）" % (src, dst, len(path), len(pts)))


if __name__ == "__main__":
    main()
