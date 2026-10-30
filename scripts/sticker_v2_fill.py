#!/usr/bin/env python3
"""表情包 v2 补齐：只做还没做的那几张，输出到 素材库/stickers/表情包v2。

复用 sticker_batch.py 的出图与叠字逻辑，保证风格一致。
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
spec = importlib.util.spec_from_file_location("sb", os.path.join(ROOT, "scripts", "sticker_batch.py"))
sb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sb)

OUT = os.path.join(ROOT, "data", "素材库", "stickers", "表情包v2")
DONE = {"nice", "umu", "cheer", "goodnight"}          # 01~04 已经做好
ORDER = [name for name, _, _ in sb.PACK]
LABEL = {name: text for name, _, text in sb.PACK}
DESC = {name: d for name, d, _ in sb.PACK}


def main():
    os.makedirs(OUT, exist_ok=True)
    todo = [n for n in ORDER if n not in DONE]
    print("要补 %d 张：%s" % (len(todo), ", ".join(todo)))
    for idx, name in enumerate(todo, start=5):
        prompt = "%s，%s" % (sb.STYLE, DESC[name])
        key = os.path.join(OUT, "%02d_%s_sq.png" % (idx, LABEL[name].rstrip("！？~…")))
        if os.path.exists(key):
            print("  跳过（已存在）:", os.path.basename(key)); continue
        png = sb.gen(prompt, seed=20261030 + idx)
        sb.caption(png, LABEL[name], key)
        print("  出图:", os.path.basename(key), flush=True)


if __name__ == "__main__":
    main()
