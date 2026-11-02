#!/usr/bin/env python3
"""只读校验 ComfyUI API 格式工作流：不发任何生成任务、不占显存。

用法：
  python3 scripts/comfy/validate_workflow.py                    # 校验本目录所有 *.api.json
  python3 scripts/comfy/validate_workflow.py a.api.json b.api.json
  python3 scripts/comfy/validate_workflow.py --base http://100.99.5.35:8188

它做的事（全部是纯文本 + /object_info 只读请求）：
  1. 每个 class_type 是否存在于目标 ComfyUI
  2. 每个 required 输入是否被"字面值"或"连线"填满
  3. 连线的上游节点是否存在、slot 是否越界、类型是否对得上
  4. COMBO/enum 输入的取值是否在服务器的合法清单里
  5. 常见形状错误（length 不是 4n+1、宽高不是 32 的倍数）

退出码 0 = 全过；1 = 有问题。
"""
import argparse
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# 这些输入是"服务器上已有的文件清单"：值不在清单里 = 还没下载/还没上传，
# 属于"待准备资源"，不是图结构错误。默认只提示，不判 FAIL（--strict 才判）。
ASSET_INPUTS = {
    "unet_name", "vae_name", "clip_name", "lora_name", "control_net_name",
    "model_name", "clip_name1", "clip_name2", "image", "file", "video",
    "upscale_model_name", "ckpt_name", "style_model_name",
}


def fetch_object_info(base):
    url = base.rstrip("/") + "/object_info"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


def spec_inputs(node_spec):
    """返回 (required dict, optional dict)，兼容新旧两种 input 结构。"""
    inp = node_spec.get("input", {}) or {}
    return (inp.get("required") or {}), (inp.get("optional") or {})


def decl_type(spec_entry):
    if not isinstance(spec_entry, (list, tuple)) or not spec_entry:
        return None
    t = spec_entry[0]
    if isinstance(t, list):
        return "COMBO"
    return t


def enum_options(spec_entry):
    if not isinstance(spec_entry, (list, tuple)) or not spec_entry:
        return None
    t = spec_entry[0]
    if isinstance(t, list):
        return t
    return None


def validate_one(path, obj_info, strict_assets=False):
    problems = []
    assets = []
    graph = json.load(open(path, encoding="utf-8"))
    graph = {k: v for k, v in graph.items() if not k.startswith("_")}
    if not graph:
        return ["文件里没有节点"]

    present_nodes = set(graph)
    for nid, node in graph.items():
        ctype = node.get("class_type")
        inputs = node.get("inputs", {}) or {}
        if ctype not in obj_info:
            problems.append("%s: 节点类型 %r 不存在于该 ComfyUI（缺自定义节点？）" % (nid, ctype))
            continue
        req, opt = spec_inputs(obj_info[ctype])
        all_spec = dict(req)
        all_spec.update(opt)

        # 1) required 覆盖
        for name in req:
            if name not in inputs:
                problems.append("%s(%s): 缺 required 输入 %r" % (nid, ctype, name))

        # 2) 未知输入名
        for name in inputs:
            if name not in all_spec:
                problems.append("%s(%s): 服务器不认识输入 %r" % (nid, ctype, name))

        # 3) 连线 + enum 取值
        for name, val in inputs.items():
            spec = all_spec.get(name)
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str):
                src, slot = val
                if src not in present_nodes:
                    problems.append("%s(%s).%s: 连到不存在的节点 %r" % (nid, ctype, name, src))
                    continue
                src_type = graph[src].get("class_type")
                if src_type not in obj_info:
                    continue
                out_types = obj_info[src_type].get("output") or []
                if isinstance(slot, int) and slot >= len(out_types):
                    problems.append("%s(%s).%s: 上游 %s 只有 %d 个输出，取了 slot %d"
                                    % (nid, ctype, name, src_type, len(out_types), slot))
                    continue
                want = decl_type(spec) if spec else None
                got = out_types[slot] if isinstance(slot, int) else None
                if want and got and want != "*" and got != "*" and want != got:
                    problems.append("%s(%s).%s: 类型不符 期望 %s 实得 %s（来自 %s）"
                                    % (nid, ctype, name, want, got, src_type))
            else:
                opts = enum_options(spec) if spec else None
                if opts and isinstance(val, str) and val not in opts:
                    msg = ("%s(%s).%s: %r 不在服务器清单里（现有 %d 个：%s...）"
                           % (nid, ctype, name, val, len(opts), ", ".join(map(str, opts[:3]))))
                    if name in ASSET_INPUTS and not strict_assets:
                        assets.append(msg)
                    else:
                        problems.append(msg)

    # 4) 常见形状错误
    for nid, node in graph.items():
        if node.get("class_type") in ("Wan22ImageToVideoLatent", "WanImageToVideo",
                                      "WanFirstLastFrameToVideo", "WanVaceToVideo"):
            i = node.get("inputs", {})
            ln, w, h = i.get("length"), i.get("width"), i.get("height")
            if isinstance(ln, int) and ln % 4 != 1:
                problems.append("%s: length=%d 不是 4n+1（Wan 要求 4n+1）" % (nid, ln))
            if isinstance(w, int) and w % 32:
                problems.append("%s: width=%d 不是 32 的倍数" % (nid, w))
            if isinstance(h, int) and h % 32:
                problems.append("%s: height=%d 不是 32 的倍数" % (nid, h))
    return problems, assets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="要校验的 api json；留空=本目录 *.api.json")
    ap.add_argument("--base", default="http://127.0.0.1:8188")
    ap.add_argument("--strict", action="store_true", help="缺模型/缺输入文件也判 FAIL")
    a = ap.parse_args()

    files = a.files or sorted(
        os.path.join(HERE, f) for f in os.listdir(HERE) if f.endswith(".api.json"))
    if not files:
        print("没有找到要校验的文件")
        return 1

    print("拉取 %s/object_info ..." % a.base.rstrip("/"))
    obj_info = fetch_object_info(a.base)
    print("节点类型 %d 个\n" % len(obj_info))

    bad = 0
    for f in files:
        probs, assets = validate_one(f, obj_info, a.strict)
        name = os.path.basename(f)
        if probs:
            bad += 1
            print("[FAIL] %s  图结构有问题" % name)
            for p in probs:
                print("   x %s" % p)
        else:
            g = json.load(open(f, encoding="utf-8"))
            n = len([k for k in g if not k.startswith("_")])
            print("[PASS] %s  (%d 节点：required/类型/枚举/形状 全部通过)" % (name, n))
        for amsg in assets:
            print("   ! 待准备资源 %s" % amsg)
    print("\n%d/%d 通过" % (len(files) - bad, len(files)))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
