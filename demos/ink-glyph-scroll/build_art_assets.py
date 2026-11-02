#!/opt/homebrew/bin/python3.14
# -*- coding: utf-8 -*-
"""mv-art 美术素材生成器 —— 全部由程序/系统字型生成，不使用任何绘图模型。

产出（art/ 目录）：
  glyphs.json   每个"字"的**笔顺化笔画路径**：有序点列 + 法线 + 笔压 + 书写进度 u
  cursive.json  程序生成的草书笔迹（用于间奏，非汉字）
  layout.json   60 行歌词 → 画面里写哪个字 / 写在哪 / 多大 / 是否朱砂
  paper.png     宣纸纸纹（多尺度：大块水渍 + 细纤维 + 颗粒）
  inkdot.png    墨点贴图（密度核 + 洇边纤维 + 溅点）
  drybrush.png  飞白噪声（各向异性拉长的噪声，用来切出枯笔白丝）
  seal.png      朱砂印章「红昭愿」

字型：系统里的 行楷体(Xingkai) 做笔画骨架，魏碑体做印章。
笔画提取：字型轮廓 → 阈值 → Zhang-Suen 细化 → 骨架图分解成弧 → 按书写顺序排序
         → 等间距重采样；笔压取距离变换的半宽（字型本身的粗细），再乘入笔/收笔的提按。
"""
import json, math, os, random, sys, glob
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "art")
os.makedirs(ART, exist_ok=True)

# ---------------------------------------------------------------- 字型
F8 = "/System/Library/AssetsV2/com_apple_MobileAsset_Font8"


def find_font(name):
    for f in glob.glob(F8 + "/*/AssetData/" + name):
        return f
    return None


FONT_STROKE = find_font("Xingkai.ttc") or find_font("Kaiti.ttc") or "/System/Library/Fonts/Supplemental/Songti.ttc"
FONT_SEAL = find_font("WeibeiSC-Bold.otf") or FONT_STROKE
print("笔画字型:", FONT_STROKE)
print("印章字型:", FONT_SEAL)

# ---------------------------------------------------------------- 布局表（60 行）
# 语法：  "字@cx,cy,size,rot,red"   多个用 | 分隔
#   cx,cy 画面归一化中心；size 字框边长（单位=画面高度）；rot 角度；red 朱砂占比 0..1
LAYOUT = [
    # ---- 主歌一 0..14
    "花@0.50,0.455,0.560,-2.0,0",          # 0 手中雕刻生花
    "刀@0.445,0.445,0.600,3.0,0",          # 1 刀锋千转蜿蜒成画
    "塔@0.535,0.455,0.520,0.0,0",          # 2 盛名功德塔
    "家@0.470,0.470,0.500,1.5,0",          # 3 是桥畔某处人家
    "红@0.500,0.440,0.560,-3.0,0.9",       # 4 春风绕过发梢红纱   ← 朱砂
    "绣@0.500,0.460,0.480,0.0,0.35",       # 5 刺绣赠他
    "眉@0.460,0.450,0.540,0.0,0",          # 6 眉目刚烈拟作妆嫁
    "沙@0.550,0.470,0.500,2.0,0",          # 7 轰烈流沙枕上白发
    "酒@0.500,0.460,0.480,0.0,0",          # 8 杯中酒比划
    "马@0.500,0.450,0.560,-2.5,0.45",      # 9 年少风雅鲜衣怒马
    "刹@0.485,0.460,0.500,0.0,0",          # 10 也不过一刹那
    "檐@0.520,0.450,0.540,0.0,0",          # 11 难免疏漏儿时檐下
    "变@0.500,0.465,0.490,0.0,0",          # 12 莫测变化
    "山@0.395,0.470,0.360,0,0 | 海@0.590,0.440,0.420,0,0",   # 13 隔却山海
    "茶@0.520,0.460,0.500,0.0,0",          # 14 转身从容煎茶
    # ---- 副歌一 15..24
    "长@0.500,0.450,0.520,0.0,0",          # 15 一生长
    "寄@0.500,0.460,0.500,0.0,0",          # 16 重寄一段过往
    "放@0.545,0.450,0.520,-2.0,0",         # 17 将希冀都流放
    "荒@0.470,0.455,0.520,0.0,0",          # 18 可曾添些荒唐
    "你@0.505,0.450,0.540,1.0,0",          # 19 才记得你的模样
    "霜@0.500,0.450,0.500,0.0,0",          # 20 一身霜
    "笔@0.500,0.445,0.560,-2.0,0",         # 21 谁提笔只两行
    "康@0.500,0.455,0.520,0.0,0",          # 22 换一隅你安康
    "沧@0.520,0.450,0.500,0.0,0.25",       # 23 便销得这沧桑
    "心@0.500,0.450,0.500,-2.0,0.95",      # 24 你还在我的心上   ← 朱砂
    # ---- 主歌二 25..39（重复段：换字、换构图，让重唱不是重播）
    "雕@0.545,0.450,0.540,2.0,0",          # 25 手中雕刻生花
    "画@0.470,0.465,0.500,0.0,0",          # 26 刀锋千转蜿蜒成画
    "塔@0.460,0.470,0.480,1.5,0",          # 27 盛名功德塔
    "桥@0.545,0.450,0.520,0.0,0",          # 28 是桥畔某处人家
    "纱@0.500,0.450,0.560,0.0,0.8",        # 29 春风绕过发梢红纱
    "绣@0.520,0.465,0.430,0.0,0",          # 30 刺绣赠他
    "嫁@0.480,0.450,0.540,0.0,0",          # 31 眉目刚烈拟作妆嫁
    "发@0.520,0.460,0.500,0.0,0",          # 32 轰烈流沙枕上白发
    "酒@0.480,0.450,0.520,-2.0,0",         # 33 杯中酒比划
    "马@0.530,0.455,0.540,2.0,0",          # 34 年少风雅鲜衣怒马
    "刹@0.500,0.450,0.520,0.0,0",          # 35 也不过一刹那
    "檐@0.470,0.460,0.500,0.0,0",          # 36 难免疏漏儿时檐下
    "变@0.530,0.450,0.510,-2.0,0",         # 37 莫测变化
    "海@0.500,0.450,0.600,0.0,0",          # 38 隔却山海
    "茶@0.480,0.465,0.480,0.0,0",          # 39 转身从容煎茶
    # ---- 副歌二 40..49（同一批词，构图推近、偏侧）
    "长@0.560,0.440,0.600,-2.0,0",         # 40 一生长
    "往@0.455,0.465,0.520,0.0,0",          # 41 重寄一段过往
    "冀@0.520,0.450,0.560,0.0,0",          # 42 将希冀都流放
    "唐@0.475,0.455,0.520,1.0,0",          # 43 可曾添些荒唐
    "模@0.510,0.450,0.540,0.0,0",          # 44 才记得你的模样
    "霜@0.560,0.450,0.520,0.0,0",          # 45 一身霜
    "行@0.500,0.445,0.560,0.0,0",          # 46 谁提笔只两行
    "安@0.470,0.455,0.520,0.0,0",          # 47 换一隅你安康
    "桑@0.525,0.450,0.540,0.0,0",          # 48 便销得这沧桑
    "心@0.500,0.440,0.560,0.0,1.0",        # 49 你还在我的心上   ← 朱砂
    # ---- 副歌三 50..59（收束：越写越小，最后只剩一个心）
    "长@0.480,0.460,0.460,0.0,0",          # 50 一生长
    "寄@0.520,0.455,0.440,0.0,0",          # 51 重寄一段过往
    "放@0.470,0.465,0.420,0.0,0",          # 52 将希冀都流放
    "荒@0.520,0.455,0.440,0.0,0",          # 53 可曾添些荒唐
    "你@0.490,0.460,0.440,0.0,0",          # 54 才记得你的模样
    "霜@0.515,0.462,0.380,0.0,0",          # 55 一身霜
    "笔@0.485,0.455,0.420,0.0,0",          # 56 谁提笔只两行
    "康@0.515,0.462,0.380,0.0,0",          # 57 换一隅你安康
    "沧@0.495,0.460,0.360,0.0,0",          # 58 便销得这沧桑
    "心@0.500,0.455,0.400,0.0,1.0",        # 59 你还在我的心上
]

EXTRA_CHARS = "红昭愿蝶清梦"     # 印章 / 片头片尾用

# ================================================================= 字形 → 笔画
N = 200          # 栅格分辨率
SPACING = 2.1    # 重采样点距（像素）
MAXPTS = 1500


def glyph_mask(ch, size=N):
    """把字渲染成 0/1 掩码（字号铺满，留 6% 边白）。返回 (bytes, size)。"""
    f = ImageFont.truetype(FONT_STROKE, int(size * 0.80))
    img = Image.new("L", (size * 2, size * 2), 0)
    d = ImageDraw.Draw(img)
    d.text((size, size), ch, font=f, fill=255, anchor="mm")
    bb = img.getbbox()
    if not bb:
        return None, size
    img = img.crop(bb)
    w, h = img.size
    s = max(w, h)
    canvas = Image.new("L", (s, s), 0)
    canvas.paste(img, ((s - w) // 2, (s - h) // 2))
    pad = int(s * 0.06)
    canvas = canvas.resize((size, size), Image.LANCZOS)
    inner = Image.new("L", (size, size), 0)
    k = int(size * 0.88)
    inner.paste(canvas.resize((k, k), Image.LANCZOS), ((size - k) // 2, (size - k) // 2))
    return inner.load(), size


def binarize(px, size, thr=110, min_area=26):
    m = bytearray(size * size)
    for y in range(size):
        for x in range(size):
            if px[x, y] >= thr:
                m[y * size + x] = 1
    # 去掉孤立的小碎块（行楷边上那些毛刺岛），只留真正的笔画
    seen = bytearray(size * size)
    for start in range(size * size):
        if not m[start] or seen[start]:
            continue
        stack, comp = [start], []
        seen[start] = 1
        while stack:
            i = stack.pop()
            comp.append(i)
            y, x = divmod(i, size)
            for dy, dx in NB8:
                yy, xx = y + dy, x + dx
                if 0 <= yy < size and 0 <= xx < size:
                    j = yy * size + xx
                    if m[j] and not seen[j]:
                        seen[j] = 1
                        stack.append(j)
        if len(comp) < min_area:
            for i in comp:
                m[i] = 0
    return m


def zhang_suen(mask, size):
    """Zhang-Suen 细化。返回 skeleton bytearray。"""
    W = size
    m = bytearray(mask)
    nb = (-W - 1, -W, -W + 1, -1, 1, W - 1, W, W + 1)
    changed = True
    it = 0
    while changed and it < 60:
        changed = False
        it += 1
        for step in (0, 1):
            dele = []
            for y in range(1, W - 1):
                base = y * W
                for x in range(1, W - 1):
                    i = base + x
                    if not m[i]:
                        continue
                    p2 = m[i + nb[1]]; p3 = m[i + nb[2]]; p4 = m[i + nb[4]]
                    p5 = m[i + nb[7]]; p6 = m[i + nb[6]]; p7 = m[i + nb[5]]
                    p8 = m[i + nb[3]]; p9 = m[i + nb[0]]
                    b = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
                    if b < 2 or b > 6:
                        continue
                    seq = (p2, p3, p4, p5, p6, p7, p8, p9, p2)
                    a = 0
                    for k in range(8):
                        if seq[k] == 0 and seq[k + 1] == 1:
                            a += 1
                    if a != 1:
                        continue
                    if step == 0:
                        if p2 * p4 * p6 != 0 or p4 * p6 * p8 != 0:
                            continue
                    else:
                        if p2 * p4 * p8 != 0 or p2 * p6 * p8 != 0:
                            continue
                    dele.append(i)
            for i in dele:
                m[i] = 0
            if dele:
                changed = True
    return m


def dist_map(mask, size):
    """倒角距离变换（内外都算），返回每像素到边界的半宽（内部为正）。"""
    INF = 1e6
    d = [INF] * (size * size)
    for i, v in enumerate(mask):
        if not v:          # 背景为 0，字形内部从 INF 开始 → 得到内部半宽
            d[i] = 0.0
    for y in range(size):
        for x in range(size):
            i = y * size + x
            if d[i] == 0.0:
                continue
            best = d[i]
            for dy, dx in ((-1, 0), (-1, -1), (0, -1), (1, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < size and 0 <= xx < size:
                    c = d[yy * size + xx] + (1.4142 if dy and dx else 1.0)
                    if c < best:
                        best = c
            d[i] = best
    for y in range(size - 1, -1, -1):
        for x in range(size - 1, -1, -1):
            i = y * size + x
            if d[i] == 0.0:
                continue
            best = d[i]
            for dy, dx in ((1, 0), (1, 1), (0, 1), (-1, 1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < size and 0 <= xx < size:
                    c = d[yy * size + xx] + (1.4142 if dy and dx else 1.0)
                    if c < best:
                        best = c
            d[i] = best
    return d


NB8 = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def trace_strokes(skel, size, min_len=7):
    """骨架 → 有序折线。先按节点(度≠2)切弧，再按书写顺序排序。"""
    pts = [i for i, v in enumerate(skel) if v]
    S = set(pts)

    def neigh(i):
        """8 邻域，但去掉"切角"的斜邻（两条正交路径同时存在时斜向是多余的）"""
        y, x = divmod(i, size)
        orth, diag = [], []
        for dy, dx in NB8:
            yy, xx = y + dy, x + dx
            if not (0 <= yy < size and 0 <= xx < size):
                continue
            j = yy * size + xx
            if j not in S:
                continue
            (diag if (dy and dx) else orth).append((dy, dx, j))
        orth_set = {(dy, dx) for dy, dx, _ in orth}
        out = [j for _, _, j in orth]
        for dy, dx, j in diag:
            # 两边都有正交邻居 → 斜边是角点冗余
            if (dy, 0) in orth_set and (0, dx) in orth_set:
                continue
            out.append(j)
        return out

    deg = {i: len(neigh(i)) for i in pts}
    nodes = {i for i in pts if deg[i] != 2}
    visited_edge = set()
    arcs = []

    def walk(start, second):
        path = [start]
        prev, cur = start, second
        visited_edge.add((min(prev, cur), max(prev, cur)))
        path.append(cur)
        while cur not in nodes:
            nxt = None
            for j in neigh(cur):
                if j == prev:
                    continue
                key = (min(cur, j), max(cur, j))
                if key in visited_edge:
                    continue
                nxt = j
                break
            if nxt is None:
                break
            visited_edge.add((min(cur, nxt), max(cur, nxt)))
            path.append(nxt)
            prev, cur = cur, nxt
            if len(path) > 4000:
                break
        return path

    starts = list(nodes) if nodes else [pts[0]]
    for i in starts:
        for j in neigh(i):
            key = (min(i, j), max(i, j))
            if key in visited_edge:
                continue
            arcs.append(walk(i, j))
    # 纯环（无节点）剩下的部分也走一遍
    for i in pts:
        for j in neigh(i):
            key = (min(i, j), max(i, j))
            if key in visited_edge:
                continue
            arcs.append(walk(i, j))

    # 剪掉短毛刺：短于 min_len 的弧直接丢
    arcs = [a for a in arcs if len(a) >= min_len]

    # 把在交叉点被切碎的弧接回成长笔画：挑"最像同一笔"的一对合并
    arcs = [list(a) for a in arcs]
    for _ in range(400):
        ends = {}
        for k, a in enumerate(arcs):
            if a is None:
                continue
            for e, pix in ((0, a[0]), (1, a[-1])):
                ends.setdefault(pix, []).append((k, e))

        best = None
        for pix, lst in ends.items():
            if len(lst) < 2:
                continue
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    (ki, ei), (kj, ej) = lst[i], lst[j]
                    if ki == kj:
                        continue
                    a, c = arcs[ki], arcs[kj]
                    if a is None or c is None or len(a) < 3 or len(c) < 3:
                        continue
                    # 离开交叉点的切向（整数像素差；用 divmod 还原坐标）
                    ia = a[1] if ei == 0 else a[-2]
                    ja = a[0] if ei == 0 else a[-1]
                    ic = c[1] if ej == 0 else c[-2]
                    jc = c[0] if ej == 0 else c[-1]
                    ay, ax = divmod(ia, size); by_, bx = divmod(ja, size)
                    cy__, cx = divmod(ic, size); dy_, dx = divmod(jc, size)
                    ax -= bx; ay -= by_
                    cx -= dx; cy__ -= dy_
                    na = math.hypot(ax, ay) or 1
                    nc = math.hypot(cx, cy__) or 1
                    score = -(ax * cx + ay * cy__) / (na * nc)   # 反向 = 更连贯
                    if score > 0.28 and (best is None or score > best[0]):
                        best = (score, ki, ei, kj, ej)
        if best is None:
            break
        _, ki, ei, kj, ej = best
        a, c = arcs[ki], arcs[kj]
        if ei == 0:
            a = a[::-1]
        if ej == 1:
            c = c[::-1]
        arcs[ki] = a + c[1:]
        arcs[kj] = None
    arcs = [a for a in arcs if a is not None and len(a) >= min_len]

    # 书写顺序：先按 x 分 4 个竖带（左→右），带内按 y（上→下）
    def order_key(a):
        xs = [p % size for p in a]
        ys = [p // size for p in a]
        cx = sum(xs) / len(xs)
        cy = min(ys)
        band = int(cx / size * 4.0)
        return (band, cy)
    arcs.sort(key=order_key)

    # 弧的朝向：让上一笔的落点尽量接近下一笔的起点（笔不到纸不抬太远）
    out, last = [], None
    for a in arcs:
        if last is not None:
            d_fwd = math.hypot(a[0] % size - last[0], a[0] // size - last[1])
            d_bwd = math.hypot(a[-1] % size - last[0], a[-1] // size - last[1])
            if d_bwd < d_fwd:
                a = a[::-1]
        last = (a[-1] % size, a[-1] // size)
        out.append(a)
    return out


def path_coverage(points, mask, ds, size):
    """把笔迹按笔压"刷"到栅格上，量一下盖住了字形面积的百分之多少。
    低于阈值就说明骨架/合并出了问题（缺笔），要回退成按字形填充。"""
    cov = bytearray(size * size)
    maxr = max(ds) if ds else 4.0
    for (x, y, nx, ny, press, u) in points:
        cx, cy = x * size, y * size
        r = max(0.9, press * maxr)
        r2 = r * r
        x0, x1 = int(cx - r), int(cx + r) + 1
        y0, y1 = int(cy - r), int(cy + r) + 1
        for yy in range(max(0, y0), min(size, y1)):
            dy2 = (yy - cy) ** 2
            for xx in range(max(0, x0), min(size, x1)):
                if (xx - cx) ** 2 + dy2 <= r2:
                    cov[yy * size + xx] = 1
    hit = tot = 0
    for i in range(size * size):
        if mask[i]:
            tot += 1
            if cov[i]:
                hit += 1
    return hit / max(1, tot)


def build_raster_glyph(mask, ds, size, band=6):
    """回退：直接按字形填充（列带左→右、带内上→下），保证一个笔画都不缺。"""
    pts = []
    maxh = max(ds) or 1.0
    bx = 0
    while bx < size:
        col = []
        for y in range(0, size, 4):
            for x in range(bx, min(size, bx + band), 3):
                if mask[y * size + x]:
                    col.append((x, y))
        col.sort(key=lambda t: t[1])
        pts.extend(col)
        bx += band
    if len(pts) < 2:
        return None
    out = []
    n = len(pts)
    for i, (x, y) in enumerate(pts):
        v = ds[y * size + x] / maxh
        out.append([x / size, y / size, 1.0, 0.0, max(0.25, v), i / (n - 1)])
    return {"points": out, "fallback": True}


def rdp(points, eps):
    if len(points) < 3:
        return points
    ax, ay = points[0]
    bx, by = points[-1]
    dx, dy = bx - ax, by - ay
    L = math.hypot(dx, dy) or 1e-9
    imax, dmax = 0, -1
    for i in range(1, len(points) - 1):
        px, py = points[i]
        d = abs(dy * (px - ax) - dx * (py - ay)) / L
        if d > dmax:
            imax, dmax = i, d
    if dmax > eps:
        left = rdp(points[:imax + 1], eps)
        right = rdp(points[imax:], eps)
        return left[:-1] + right
    return [points[0], points[-1]]


def build_glyph(ch):
    px, size = glyph_mask(ch)
    if px is None:
        print("  !! 空白字型:", ch)
        return None
    mask = binarize(px, size)
    ds = dist_map(mask, size)
    skel = zhang_suen(mask, size)
    arcs = trace_strokes(skel, size)
    if not arcs:
        print("  !! 无骨架:", ch)
        return None

    # 弧 → 折线 → 等距重采样
    sampled = []
    for a in arcs:
        poly = [(p % size, p // size) for p in a]
        poly = rdp(poly, 1.15)
        if len(poly) < 2:
            continue
        # 沿折线等距取点
        acc = 0.0
        pts = [poly[0]]
        for k in range(1, len(poly)):
            x0, y0 = pts[-1]
            x1, y1 = poly[k]
            seg = math.hypot(x1 - x0, y1 - y0)
            while seg >= SPACING:
                tt = SPACING / seg
                x0 = x0 + (x1 - x0) * tt
                y0 = y0 + (y1 - y0) * tt
                pts.append((x0, y0))
                seg = math.hypot(x1 - x0, y1 - y0)
        pts.append(poly[-1])
        if len(pts) >= 2:
            sampled.append(pts)

    if not sampled:
        return None

    # 全局书写进度 u：按弧顺序累加弧长
    lens = []
    for pts in sampled:
        L = 0.0
        for k in range(1, len(pts)):
            L += math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
        lens.append(max(L, 1e-6))
    total = sum(lens)

    maxr = max(ds)          # 最大半宽（像素）——用来把笔压换算成延出长度
    out = []
    acc = 0.0
    for si, pts in enumerate(sampled):
        L = lens[si]
        # 笔压：先用距离变换的半宽（字型自身的粗细），再乘入笔/收笔提按
        press_raw = []
        for (x, y) in pts:
            xi = min(size - 1, max(0, int(x)))
            yi = min(size - 1, max(0, int(y)))
            press_raw.append(ds[yi * size + xi])
        mx = max(press_raw) or 1.0
        press_raw = [min(1.0, v / mx) for v in press_raw]
        # 沿弧平滑（3 点滑动平均）
        sm = press_raw[:]
        for k in range(1, len(sm) - 1):
            sm[k] = (press_raw[k - 1] + 2 * press_raw[k] + press_raw[k + 1]) / 4.0
        # 两端各延出一小段（长度 ∝ 笔压），让交叉点处两笔接得上、不露缝
        def extend(pts, sm, at_start):
            if len(pts) < 2:
                return pts, sm
            if at_start:
                x0, y0 = pts[0]; x1, y1 = pts[1]; pr = sm[0]
            else:
                x0, y0 = pts[-1]; x1, y1 = pts[-2]; pr = sm[-1]
            dx, dy = x0 - x1, y0 - y1
            L = math.hypot(dx, dy) or 1.0
            dx, dy = dx / L, dy / L
            want = 0.95 * pr * maxr
            nadd = int(min(8, want / SPACING))
            extra = [(x0 + dx * SPACING * (i + 1), y0 + dy * SPACING * (i + 1)) for i in range(nadd)]
            if at_start:
                return extra[::-1] + pts, [pr] * nadd + sm
            # 收笔：延出段越往外越细（笔提起来的"尖"）
            tail = [pr * (1.0 - 0.82 * (i + 1) / (nadd + 1.0)) for i in range(nadd)]
            return pts + extra, sm + tail
        pts, sm = extend(pts, sm, True)
        pts, sm = extend(pts, sm, False)
        n = len(pts)
        for k in range(n):
            x, y = pts[k]
            kp = min(n - 1, k + 1)
            km = max(0, k - 1)
            tx = pts[kp][0] - pts[km][0]
            ty = pts[kp][1] - pts[km][1]
            tl = math.hypot(tx, ty) or 1.0
            nx, ny = -ty / tl, tx / tl
            tt = k / max(1, n - 1)
            press = sm[k]
            press *= min(1.0, tt / 0.07 + 0.25)                 # 起笔略提
            press *= 1.0 - 0.58 * (max(0.0, (tt - 0.58) / 0.42) ** 1.6)   # 收笔渐细
            u = (acc + L * tt) / total
            out.append([x / size, y / size, nx, ny, press, u])
        acc += L

    cov = path_coverage(out, mask, ds, size)
    tag = ""
    if cov < 0.80:
        fb = build_raster_glyph(mask, ds, size)
        if fb:
            print("  %s: 覆盖率 %.2f 偏低 → 回退按字形填充（%d 点）" % (ch, cov, len(fb["points"])))
            return fb
    print("  %s: %d 弧 %d 点  覆盖 %.2f" % (ch, len(sampled), len(out), cov))
    return {"points": out}


# ================================================================= 草书（间奏用）
def build_cursive(seed):
    rnd = random.Random(seed)
    # 随机游走生成一条有笔势的轨迹（方向连续，转笔平滑）
    ang = rnd.uniform(-0.6, 0.6) + (math.pi / 2 if rnd.random() < 0.25 else 0)
    x, y = rnd.uniform(-0.55, -0.2), rnd.uniform(-0.5, 0.4)
    ctrl = [(x, y)]
    n = rnd.randint(4, 8)
    step = rnd.uniform(0.35, 0.55)
    for _ in range(n):
        ang += rnd.gauss(0, 0.55)
        # 大致向右走，避免原地打转
        ang = 0.35 * ang + 0.65 * (rnd.choice([-0.35, 0.0, 0.35, 0.6]))
        ang = max(-1.35, min(1.35, ang))
        x += math.cos(ang) * step
        y += math.sin(ang) * step
        ctrl.append((x, y))
    # Catmull-Rom
    P = [ctrl[0]] + ctrl + [ctrl[-1]]
    path = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(14):
            t = k / 14.0
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
                       (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
                       (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
                       (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
                       (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            path.append((x, y))
    # 归一到 [-0.5,0.5] 方框
    xs = [p[0] for p in path]; ys = [p[1] for p in path]
    cx = (min(xs) + max(xs)) / 2; cy = (min(ys) + max(ys)) / 2
    s = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    path = [((p[0] - cx) / s + 0.5, (p[1] - cy) / s + 0.5) for p in path]

    m = len(path) - 1
    out = []
    for k in range(m + 1):
        x, y = path[k]
        kp = min(m, k + 1); km = max(0, k - 1)
        tx, ty = path[kp][0] - path[km][0], path[kp][1] - path[km][1]
        tl = math.hypot(tx, ty) or 1.0
        tt = k / m
        # 笔压：中段最重，两端提起来；再叠一点提按的起伏
        press = 0.32 + 0.68 * (math.sin(math.pi * min(1.0, tt * 1.02)) ** 0.65)
        press *= 0.82 + 0.30 * math.sin(tt * math.pi * rnd.uniform(2, 3.4) + seed)
        press = max(0.12, min(1.0, press))
        out.append([x, y, -ty / tl, tx / tl, press, tt])
    return {"points": out}


# ================================================================= 纸 / 墨点 / 飞白 / 印
def gen_paper(w=1536, h=864):
    """宣纸：多尺度（大块水渍 / 中频云斑 / 细颗粒 / 纤维）。全部是"很轻"的变化。"""
    rnd = random.Random(7)
    base = Image.new("RGB", (w, h), (245, 238, 225))

    def var(img, amp):
        """噪声图 → 以 255 为中心的亮度图；amp 是峰值百分比（如 3 = ±3/255）"""
        g = img.point(lambda v: max(0, min(255, int(255 + amp * (v - 128) / 42.0))))
        return g.convert("RGB")

    def noise(sz, sigma=42.0):
        return Image.effect_noise(sz, sigma)

    out = base
    # 大块（低频）：纸的云斑
    n1 = noise((18, 10)).resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(40))
    out = ImageChops.multiply(out, var(n1, 4.5))
    # 中频：抄纸的薄厚
    n2 = noise((max(2, w // 12), max(2, h // 12))).resize((w, h), Image.BICUBIC).filter(
        ImageFilter.GaussianBlur(7))
    out = ImageChops.multiply(out, var(n2, 3.0))
    # 细颗粒
    n3 = noise((w, h))
    out = ImageChops.multiply(out, var(n3, 2.2))

    # 纤维：细长、成簇、方向大致水平（楮皮纸的特征）
    fib = Image.new("L", (w, h), 128)
    d = ImageDraw.Draw(fib)
    for _ in range(5200):
        x, y = rnd.uniform(-40, w), rnd.uniform(0, h)
        a = rnd.gauss(0, 0.09) + (0 if rnd.random() < 0.85 else 1.5708)
        L = rnd.uniform(18, 130)
        g = 128 + (rnd.choice([-1, 1]) * rnd.uniform(6, 22))
        d.line([(x, y), (x + math.cos(a) * L, y + math.sin(a) * L)], fill=int(g), width=1)
    fib = fib.filter(ImageFilter.GaussianBlur(0.8))
    out = ImageChops.multiply(out, var(fib, 2.6))

    # 几处极淡的洇渍（像隔了一层的水痕）
    stain = Image.new("L", (w, h), 128)
    ds = ImageDraw.Draw(stain)
    for _ in range(5):
        cx, cy = rnd.uniform(0, w), rnd.uniform(0, h)
        rx, ry = rnd.uniform(120, 380), rnd.uniform(90, 300)
        ds.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=128 - int(rnd.uniform(4, 10)))
    stain = stain.filter(ImageFilter.GaussianBlur(90))
    out = ImageChops.multiply(out, var(stain, 3.4))

    # 上下暖冷渐变（上略冷，下略暖）
    grad = Image.new("L", (1, h))
    gp = grad.load()
    for y in range(h):
        t = y / (h - 1)
        gp[0, y] = int(253.0 - 9 * t)
    grad = grad.resize((w, h), Image.BILINEAR).convert("RGB")
    out = ImageChops.multiply(out, grad)

    out.save(os.path.join(ART, "paper.png"))
    print("paper.png", out.size)


def gen_inkdot(s=32):
    """墨点：致密核 + 不规则的半透明洇边 + 边缘纤维 + 几粒溅点。"""
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    px = img.load()
    rnd = random.Random(3)
    waves = [(2.0, rnd.uniform(0, 6.28), 0.055),
             (3.0, rnd.uniform(0, 6.28), 0.045),
             (5.0, rnd.uniform(0, 6.28), 0.030),
             (7.0, rnd.uniform(0, 6.28), 0.020)]
    fibp = [rnd.uniform(0, 6.28) for _ in range(6)]
    for y in range(s):
        for x in range(s):
            dx = (x + 0.5) / s * 2 - 1
            dy = (y + 0.5) / s * 2 - 1
            r = math.hypot(dx, dy)
            a = math.atan2(dy, dx)
            edge = 0.58
            for (f, ph, amp) in waves:
                edge += amp * math.sin(a * f + ph)
            if r < edge:
                # 核：中心接近 1，往外幂次衰减
                v = (1.0 - (r / edge) ** 2.4) ** 0.62
            else:
                # 洇边：很薄的一圈
                v = 0.0
            # 边缘纤维（放射状细丝）
            fib = 0.0
            for k, ph in enumerate(fibp):
                fib = max(fib, max(0.0, math.sin(a * (13 + k * 4) + ph)) ** 10)
            v += 0.30 * fib * math.exp(-((r - edge * 0.92) / 0.16) ** 2)
            v *= 0.86 + 0.14 * math.sin(a * 2.0 + r * 7.0)
            px[x, y] = (255, 255, 255, int(max(0, min(255, v * 255))))
    d = ImageDraw.Draw(img)
    for _ in range(4):
        a = rnd.uniform(0, 6.28); rr = rnd.uniform(0.40, 0.50)
        cx, cy = (0.5 + math.cos(a) * rr) * s, (0.5 + math.sin(a) * rr) * s
        rad = rnd.uniform(0.5, 1.7)
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(255, 255, 255, rnd.randint(45, 140)))
    img.save(os.path.join(ART, "inkdot.png"))
    print("inkdot.png")


def gen_drybrush(s=512):
    """飞白噪声：轻微各向异性的颗粒噪声（不是长条；长条在暗处会变成"条纹故障"）。"""
    n = Image.effect_noise((96, 288), 58.0).resize((s, s), Image.BICUBIC)
    n = n.filter(ImageFilter.GaussianBlur(1.0))
    n = n.rotate(-16, resample=Image.BICUBIC)
    n = n.point(lambda v: max(0, min(255, int((v - 108) * 1.9 + 64))))
    n.convert("RGB").save(os.path.join(ART, "drybrush.png"))
    print("drybrush.png")


def gen_seal(s=420):
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    red = (168, 42, 30, 255)
    # 边框（手刻的不齐）
    rnd = random.Random(5)
    m = 18
    for i in range(4):
        d.rectangle([m, m, s - m, s - m], outline=red, width=13)
    f = ImageFont.truetype(FONT_SEAL, int(s * 0.40))
    chars = "红昭愿"
    for i, ch in enumerate(chars):
        d.text((s * 0.5, s * (0.30 + i * 0.235)), ch, font=f, fill=red, anchor="mm")
    # 做旧：随机挖掉一些小点
    px = img.load()
    for _ in range(2600):
        x, y = rnd.randrange(s), rnd.randrange(s)
        r, g, b, a = px[x, y]
        if a > 0 and rnd.random() < 0.75:
            px[x, y] = (r, g, b, 0)
    # 边缘略糊（印泥渗）
    img = img.filter(ImageFilter.GaussianBlur(0.55))
    img.save(os.path.join(ART, "seal.png"))
    print("seal.png")


# ================================================================= main
def all_chars():
    """歌词里出现的全部字（长卷版要把每一句整句写出来）+ 标题字"""
    need = set(EXTRA_CHARS)
    for row in LAYOUT:
        for item in row.split("|"):
            need.add(item.split("@")[0].strip())
    mf = os.path.join(HERE, "manifest.json")
    if os.path.exists(mf):
        man = json.load(open(mf))
        for r in man.get("lrc", []):
            for c in (r.get("text") or ""):
                if "\u4e00" <= c <= "\u9fff":
                    need.add(c)
    return need


def char_metrics(ch):
    """字的墨迹包围盒（相对字身框），用来按"墨迹"排字距，而不是按字身框。"""
    px, size = glyph_mask(ch, 200)
    if px is None:
        return 0.7, 0.7
    xs, ys = [], []
    for y in range(size):
        for x in range(size):
            if px[x, y] > 96:
                xs.append(x); ys.append(y)
    if not xs:
        return 0.7, 0.7
    return (max(xs) - min(xs) + 1) / size, (max(ys) - min(ys) + 1) / size


def u_channels(px, size, points, maxr):
    """把"笔顺进度 u"画进字模：每个字形像素记下它被写到时的 u。
    这样字模四边形也能"一笔一笔"地显现，而且是**锐利**的（不再靠粒子糊）。"""
    from PIL import ImageDraw as _ID
    u_img = Image.new("L", (size, size), 255)
    d = _ID.Draw(u_img)
    for (x, y, nx, ny, press, u) in points:
        cx, cy = x * size, y * size
        r = max(1.2, press * maxr * 1.45)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=int(round(255 * u)))
    raw = list(u_img.getdata())
    # 字形里没被笔迹盖到的小角落：用邻域里最小的 u 补上（补几轮就够）
    for _ in range(6):
        nxt = raw[:]
        changed = 0
        for y in range(1, size - 1):
            for x in range(1, size - 1):
                i = y * size + x
                if not px[x, y] or raw[i] != 255:
                    continue
                best = 255
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        v = raw[(y + dy) * size + x + dx]
                        if v < best:
                            best = v
                if best < 255:
                    nxt[i] = best
                    changed += 1
        raw = nxt
        if not changed:
            break
    return raw


def build_mask_atlas(chars, glyphs, cell=160, cols=12):
    """图集：R = 字形覆盖，G = 笔顺进度 u（255 = 未涉及）。
    渲染时 alpha = R * (写到了吗?)，所以"正在写"和"已写完"是同一个锐利的源。"""
    chars = sorted(chars)
    rows = (len(chars) + cols - 1) // cols
    W, H = cell * cols, cell * rows
    atlas = Image.new("RGB", (W, H), 0)
    rects, metrics = {}, {}
    for i, ch in enumerate(chars):
        px, size = glyph_mask(ch, 200)
        if px is None:
            continue
        pts = glyphs.get(ch, {}).get("points", [])
        mask = [int(px[x % 200, x // 200]) for x in range(size * size)]
        uc = u_channels(px, size, pts, 200 * 0.05) if pts else [0] * (size * size)
        img = Image.new("RGB", (200, 200))
        img.putdata([(mask[j], uc[j], 0) for j in range(len(mask))])
        small = img.resize((cell - 8, cell - 8), Image.LANCZOS)
        cx, cy = (i % cols) * cell, (i // cols) * cell
        atlas.paste(small, (cx + 4, cy + 4))
        pad = 1.0 / W
        rects[ch] = [round((cx + 4) / W + pad, 6), round((cy + 4) / H + pad, 6),
                     round((cx + cell - 4) / W - pad, 6), round((cy + cell - 4) / H - pad, 6)]
        w, h = char_metrics(ch)
        metrics[ch] = [round(w, 4), round(h, 4)]
    atlas.save(os.path.join(ART, "masks.png"))
    json.dump({"rects": rects, "metrics": metrics},
              open(os.path.join(ART, "masks.json"), "w"), separators=(",", ":"))
    print("masks.png %dx%d  %d 字" % (W, H, len(rects)))


def main():
    force = "--force" in sys.argv
    gp = os.path.join(ART, "glyphs.json")
    glyphs = {}
    if os.path.exists(gp) and not force:
        glyphs = json.load(open(gp))

    need = all_chars()
    todo = sorted(c for c in need if c not in glyphs)
    if todo:
        print("提取笔画:", "".join(todo))
        for c in todo:
            g = build_glyph(c)
            if g:
                glyphs[c] = g
        json.dump(glyphs, open(gp, "w"), ensure_ascii=False, separators=(",", ":"))
    print("glyphs.json: %d 字" % len(glyphs))
    build_mask_atlas(need, glyphs)

    # 草书
    cur = {"c%d" % i: build_cursive(100 + i * 37) for i in range(10)}
    json.dump(cur, open(os.path.join(ART, "cursive.json"), "w"), separators=(",", ":"))

    # 布局 → 结构化
    lay = []
    for row in LAYOUT:
        items = []
        for item in row.split("|"):
            ch, rest = item.split("@")
            cx, cy, sz, rot, red = [float(v) for v in rest.split(",")]
            items.append({"c": ch.strip(), "x": cx, "y": cy, "s": sz, "rot": rot, "red": red})
        lay.append(items)
    assert len(lay) == 60, len(lay)
    json.dump(lay, open(os.path.join(ART, "layout.json"), "w"), ensure_ascii=False, separators=(",", ":"))

    if not os.path.exists(os.path.join(ART, "paper.png")) or force:
        gen_paper()
    if not os.path.exists(os.path.join(ART, "inkdot.png")) or force:
        gen_inkdot()
    if not os.path.exists(os.path.join(ART, "drybrush.png")) or force:
        gen_drybrush()
    if not os.path.exists(os.path.join(ART, "seal.png")) or force:
        gen_seal()
    print("done")


if __name__ == "__main__":
    main()
