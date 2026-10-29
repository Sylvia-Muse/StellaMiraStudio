#!/usr/bin/env python3
"""出道视频封面：16:9（1146x717），左边字、右边人，风格和片子统一。"""
import os, subprocess
from PIL import Image, ImageFilter, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys as _sys
RATIO = _sys.argv[1] if len(_sys.argv) > 1 else "16x9"
W, H = (1146, 717) if RATIO == "16x9" else (1200, 900)
FG = (240, 253, 245)
ACCENT = (142, 230, 176)
DIM = (158, 186, 172)
FONT_BOLD = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_THIN = "/System/Library/Fonts/STHeiti Light.ttc"

def pick_frame():
    import glob
    for cand in ("f_0200.png", "test_0400.png", "test_0200.png"):
        p = os.path.join(ROOT, "data", "debut", "frames", cand)
        if os.path.exists(p):
            return p
    hits = sorted(glob.glob(os.path.join(ROOT, "data", "debut", "frames", "*.png")))
    if hits:
        return hits[len(hits) // 3]
    raise SystemExit("没有可用的成片帧，先跑 debut_build.py frame")

frame = pick_frame()
bg = os.path.join(ROOT, "data", "debut", "art", "bg.png")
out = os.path.join(ROOT, "data", "debut", "art", "cover_debut%s.png" % ("_4x3" if RATIO == "4x3" else ""))


def fit(path, size, blur=0):
    im = Image.open(path).convert("RGB")
    tw, th = size
    k = max(tw / im.width, th / im.height)
    im = im.resize((int(im.width * k) + 1, int(im.height * k) + 1), Image.LANCZOS)
    x = (im.width - tw) // 2
    y = (im.height - th) // 2
    im = im.crop((x, y, x + tw, y + th))
    return im.filter(ImageFilter.GaussianBlur(blur)) if blur else im


canvas = fit(bg, (W, H))
# 背景压暗一点给字留位置
dark = Image.new("RGB", (W, H), (4, 12, 12))
canvas = Image.blend(canvas, dark, 0.45)

# 右侧人物：从成片帧里裁头肩
person = Image.open(frame).convert("RGBA").crop((150, 330, 950, 1230))
mask = Image.new("L", person.size, 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, person.width - 1, person.height - 1], radius=0, fill=255)
# 边缘做一点渐变，别出现硬边
grad = Image.new("L", person.size, 0)
gd = ImageDraw.Draw(grad)
for i in range(person.width):
    gd.line([(i, 0), (i, person.height)], fill=int(255 * min(1, i / 90)))
mask = Image.composite(mask, Image.new("L", person.size, 0), grad)
person.putalpha(mask)
k = (H * 1.02) / person.height
person = person.resize((int(person.width * k), int(person.height * k)), Image.LANCZOS)
canvas.paste(person, (W - person.width - 20, H - person.height + 30), person)

d = ImageDraw.Draw(canvas)


def font(path, size, index=0):
    try:
        return ImageFont.truetype(path, size=size, index=index)
    except Exception:
        return ImageFont.truetype(path, size=size)


f_big = font(FONT_BOLD, 104, index=1)
f_mid = font(FONT_BOLD, 46, index=1)
f_small = font(FONT_THIN, 24, index=1)

d.text((72, 150), "清", font=f_big, fill=FG)
d.text((72, 262), "梦", font=f_big, fill=ACCENT)
d.text((72, 396), "清梦酱 / Sylvia Muse", font=f_mid, fill=FG)
d.text((72, 458), "LIVE2D MODEL SHOWCASE · DEBUT", font=f_small, fill=DIM)
d.line([(74, 500), (74 + 210, 500)], fill=ACCENT + (200,), width=2)
d.text((72, 522), "白发猫耳翠瞳虎牙的吸血鬼少女 · 13岁", font=f_small, fill=DIM)

canvas.convert("RGB").save(out, optimize=True)
print("封面:", out, os.path.getsize(out), "字节", "%dx%d" % (W, H))
