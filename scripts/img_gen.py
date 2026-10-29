#!/usr/bin/env python3
"""出图：本地（澪那台的 qwen-image GGUF）与云端（token-plan / galaxy 网关）两个后端。

本地后端（默认）：POST {base}/v1/images/generations，OpenAI 格式 + 几个顶层扩展参数
  size            768x1024 / 1024x1024（边长 8 的倍数）
  steps           默认 20
  seed            给了可复现
  negative_prompt blurry, lowres, watermark
  cfg_scale       2.5（Qwen-Image 官方配方，别动）
  n               1~16
  速度：768×1024 ≈42s/张，1024×1024 ≈57s/张 → 超时给 900s
  注意：出图期间她那边会把 TTS/变声/伴奏服务停掉腾显存，跑完空闲 5 分钟恢复

云端后端：走本机 galaxy 网关（127.0.0.1:11091）的 /v1/images/generations

用法：
  python3.14 scripts/img_gen.py --prompt "白发绿瞳猫耳少女，表情包" --n 4
  python3.14 scripts/img_gen.py --backend cloud --prompt "..." --size 1024x1024
"""
import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "img")
LOCAL_BASES = ["http://192.168.1.197:8211/v1", "http://100.99.5.35:8211/v1"]
CLOUD_BASE = "http://127.0.0.1:11091/v1"
CLOUD_KEY_FILE = os.path.join(ROOT, ".secrets", "tokenplan_tts_key.txt")


def post(url, payload, timeout, key=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def gen_local(a):
    payload = {
        "model": "qwen-image",
        "prompt": a.prompt,
        "size": a.size,
        "steps": a.steps,
        "cfg_scale": a.cfg_scale,
        "n": a.n,
    }
    if a.seed is not None:
        payload["seed"] = a.seed
    if a.negative:
        payload["negative_prompt"] = a.negative

    last = None
    for base in ([a.base] if a.base else LOCAL_BASES):
        url = base.rstrip("/") + "/images/generations"
        try:
            t0 = time.time()
            data = post(url, payload, timeout=a.timeout)
            dt = time.time() - t0
            print("本地出图成功 %s | %.1fs | params_used=%s" % (
                base, dt, json.dumps(data.get("params_used"), ensure_ascii=False)[:200]))
            return data
        except Exception as e:
            last = e
            print("  %s 失败: %s: %s" % (base, type(e).__name__, str(e)[:120]))
    raise SystemExit("本地后端都连不上：%s" % last)


def gen_cloud(a):
    key = open(CLOUD_KEY_FILE).read().strip()
    payload = {"model": "qwen-image-2.1-pro", "prompt": a.prompt,
               "size": a.size, "n": max(1, min(a.n, 4))}
    data = post(CLOUD_BASE + "/images/generations", payload, timeout=a.timeout, key=key)
    print("云端出图成功 | %s" % json.dumps({k: v for k, v in data.items() if k != "data"},
                                     ensure_ascii=False)[:200])
    return data


def save(data, tag):
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    paths = []
    items = data.get("data") or []
    for i, item in enumerate(items):
        b64 = item.get("b64_json")
        url = item.get("url")
        raw = None
        if b64:
            raw = base64.b64decode(b64)
        elif url:
            with urllib.request.urlopen(url, timeout=120) as r:
                raw = r.read()
        if not raw:
            continue
        p = os.path.join(OUT_DIR, "%s_%s_%02d.png" % (stamp, tag, i))
        open(p, "wb").write(raw)
        paths.append(p)
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--backend", choices=["local", "cloud"], default="local")
    ap.add_argument("--size", default="768x1024")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--cfg-scale", dest="cfg_scale", type=float, default=2.5)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--negative", default="blurry, lowres, watermark, text artifacts")
    ap.add_argument("--base", help="覆盖本地 base_url")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()

    data = gen_local(a) if a.backend == "local" else gen_cloud(a)
    paths = save(data, a.backend)
    print("共 %d 张：" % len(paths))
    for p in paths:
        print("  ", p)


if __name__ == "__main__":
    main()
