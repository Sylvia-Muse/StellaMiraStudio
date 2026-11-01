#!/usr/bin/env python3
"""生成 demo 用的两张贴图：墨点（带飞白）与宣纸纹理。

只用 PIL，无网络依赖；都是「程序纹理」，不涉及任何绘图模型。
"""
from PIL import Image, ImageDraw, ImageFilter
import random, math

def ink_dot(size=512, seed=7):
    random.seed(seed)
    img = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)
    cx = cy = size / 2
    # 主墨团：多次偏移的软圆，形成飞白
    for i in range(900):
        r = size * 0.5 * math.sqrt(random.random()) * 0.92
        a = random.random() * math.tau
        x = cx + math.cos(a) * r * random.uniform(0, 0.55)
        y = cy + math.sin(a) * r * random.uniform(0, 0.55)
        rad = size * random.uniform(0.010, 0.055)
        v = int(185 + random.random() * 70)
        d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=v)
    # 边缘的飞白颗粒
    for i in range(700):
        a = random.random() * math.tau
        rr = size * (0.30 + 0.20 * random.random())
        x = cx + math.cos(a) * rr
        y = cy + math.sin(a) * rr
        rad = size * random.uniform(0.002, 0.010)
        d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=random.randint(40, 160))
    img = img.filter(ImageFilter.GaussianBlur(size * 0.012))
    # 圆形遮罩，去掉方角
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(size * 0.02))
    out = Image.composite(img, Image.new("L", (size, size), 0), mask)
    rgba = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rgba.putalpha(out)
    return rgba

def paper(size=512, seed=3):
    random.seed(seed)
    img = Image.new("RGB", (size, size), (239, 230, 214))
    d = ImageDraw.Draw(img)
    for i in range(2600):
        x, y = random.randrange(size), random.randrange(size)
        w = random.randint(1, 26)
        v = random.randint(-16, 8)
        c = tuple(max(0, min(255, base + v)) for base in (239, 230, 214))
        d.line([x, y, x + w, y + random.choice([0, 0, 1, -1])], fill=c)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    return img

if __name__ == "__main__":
    ink_dot().save("ink-dot.png")
    paper().save("paper.png")
    print("已生成 ink-dot.png / paper.png")
