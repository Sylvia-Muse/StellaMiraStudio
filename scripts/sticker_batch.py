#!/usr/bin/env python3
"""表情包批量：本地 qwen-image 出图（无字）→ PIL 叠字 → 统一成贴纸。

为什么不让模型直接写字：中文在本地量化模型上容易糊、错字，叠字最稳，
而且字号/描边/位置能统一，一整套看起来才像一套。

用法：
  python3.14 scripts/sticker_batch.py            # 出整套 12 张
  python3.14 scripts/sticker_batch.py --only 3   # 只出第 4 张（调试）
"""
import argparse
import base64
import json
import os
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "stickers")
BASE = ["http://100.99.5.35:8211/v1", "http://192.168.1.197:8211/v1"]
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"

STYLE = ("Q版表情包贴纸，白发绿瞳猫耳少女，翠绿蝴蝶发饰，绿白渐变霓裳，"
         "白色描边贴纸，纯白背景，画面干净无文字")
NEG = "blurry, lowres, watermark, text, letters, logo, extra fingers"

# (文件名, 动作描述, 贴纸文字)
PACK = [
    ("nice",      "双手叉腰，得意地笑，头上冒小星星", "不错呢"),
    ("umu",       "歪头，一脸疑惑，手放在下巴",       "唔姆？"),
    ("angry",     "鼓起腮帮子，皱眉，抱着手臂",       "哼！"),
    ("sleepy",    "揉眼睛打哈欠，头顶一个小 Z",       "困了…"),
    ("wanna",     "双眼星星眼，双手合十",             "想要！"),
    ("ignore",    "背过身去，只露出侧脸，抱膝",       "不理你了"),
    ("cheer",     "握拳举手，元气满满地跳起来",       "加油！"),
    ("thanks",    "双手合十鞠躬，微微一笑",           "谢谢你~"),
    ("peek",      "从画面边缘探头，只露出上半张脸",   "在吗？"),
    ("yay",       "双手举高欢呼，闭眼笑",             "好耶！"),
    ("hungry",    "抱着一碗饭，眼巴巴看着",           "饿饿"),
    ("goodnight", "抱着枕头，闭眼微笑",               "晚安~"),
]


def gen(prompt, seed, timeout=900):
    payload = {"model": "qwen-image", "prompt": prompt, "size": "768x1024",
               "steps": 20, "cfg_scale": 2.5, "n": 1, "seed": seed,
               "negative_prompt": NEG}
    last = None
    for base in BASE:
        try:
            req = urllib.request.Request(base.rstrip("/") + "/images/generations",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            b64 = (d.get("data") or [{}])[0].get("b64_json")
            if not b64:
                raise RuntimeError("响应里没有 b64_json")
            return base64.b64decode(b64)
        except Exception as e:
            last = e
    raise RuntimeError("出图失败: %s" % last)


def font(size):
    for idx in (1, 0):
        try:
            return ImageFont.truetype(FONT, size=size, index=idx)
        except Exception:
            continue
    return ImageFont.load_default()


def caption(png_bytes, text, out_path):
    import io
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    W, H = im.size
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font(int(W * 0.15))
    # 顶部居中，带描边
    bb = d.textbbox((0, 0), text, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x = (W - tw) / 2 - bb[0]
    y = H * 0.045 - bb[1]
    for dx in (-4, 0, 4):
        for dy in (-4, 0, 4):
            d.text((x + dx, y + dy), text, font=f, fill=(255, 255, 255, 255))
    d.text((x, y), text, font=f, fill=(32, 40, 38, 255))
    im = Image.alpha_composite(im, layer)
    im.convert("RGB").save(out_path, optimize=True)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, help="只做第 N 张（从 0 数）")
    ap.add_argument("--seed-base", type=int, default=20261028)
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    todo = PACK if a.only is None else [PACK[a.only]]
    t_all = time.time()
    for i, (name, action, text) in enumerate(todo):
        idx = a.only if a.only is not None else i
        raw_path = os.path.join(OUT, "_raw_%s.png" % name)
        final = os.path.join(OUT, "%02d_%s.png" % (idx + 1, text.replace("？", "").replace("！", "").replace("~", "")))
        if os.path.exists(final):
            print("跳过（已存在）:", os.path.basename(final), flush=True)
            continue
        prompt = "%s，%s" % (STYLE, action)
        t0 = time.time()
        try:
            data = None
            for attempt in range(1, 4):
                try:
                    data = gen(prompt, a.seed_base + idx)
                    if attempt > 1:
                        print("%2d %-10s 第 %d 次重试成功" % (idx + 1, name, attempt), flush=True)
                    break
                except Exception as e:
                    print("%2d %-10s 第 %d 次失败: %s" % (idx + 1, name, attempt, str(e)[:80]), flush=True)
                    if attempt == 3:
                        raise
                    time.sleep(10)
            open(raw_path, "wb").write(data)
            caption(data, text, final)
            print("%2d %-10s %5.1fs -> %s" % (idx + 1, name, time.time() - t0, os.path.basename(final)), flush=True)
        except Exception as e:
            print("%2d %-10s 失败: %s" % (idx + 1, name, str(e)[:140]), flush=True)
    print("整套耗时 %.1f 分钟，输出目录 %s" % ((time.time() - t_all) / 60, OUT))


if __name__ == "__main__":
    main()
