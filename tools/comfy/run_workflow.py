#!/usr/bin/env python3
"""提交 ComfyUI API 格式工作流并等结果、下载产物。

用法：
  # 1) 先挑个空闲时段确认显存（这一步是只读的）
  ssh xhqm@100.99.5.35 'nvidia-smi --query-gpu=memory.free --format=csv'

  # 2) 提交（会真正占显存！）
  python3 scripts/comfy/run_workflow.py scripts/comfy/wan22_5b_t2v.api.json \
      --base http://127.0.0.1:8188 --set 5:text='你的画面描述'

  # 3) 覆盖多个参数
  python3 scripts/comfy/run_workflow.py scripts/comfy/wan22_5b_i2v.api.json \
      --set 12:image=start.png --set 7:length=121 --set 8:seed=7

参数覆盖语法：--set 节点ID:字段=值
  值会按原字段类型自动转换（int/float/bool/str）。
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid


def post_json(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def get_json(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def coerce(old, new):
    if isinstance(old, bool):
        return new.lower() in ("1", "true", "yes", "on")
    if isinstance(old, int):
        return int(new)
    if isinstance(old, float):
        return float(new)
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow")
    ap.add_argument("--base", default="http://127.0.0.1:8188")
    ap.add_argument("--set", action="append", default=[], metavar="NODE:FIELD=VALUE")
    ap.add_argument("--timeout", type=int, default=7200, help="最长等待秒数")
    ap.add_argument("--outdir", default="data/comfy_out")
    a = ap.parse_args()

    base = a.base.rstrip("/")
    graph = json.load(open(a.workflow, encoding="utf-8"))
    graph = {k: v for k, v in graph.items() if not k.startswith("_")}

    for item in a.set:
        if "=" not in item or ":" not in item.split("=", 1)[0]:
            raise SystemExit("--set 格式应为 NODE:FIELD=VALUE，收到 %r" % item)
        head, val = item.split("=", 1)
        nid, field = head.split(":", 1)
        if nid not in graph:
            raise SystemExit("没有节点 %r（现有：%s）" % (nid, ",".join(sorted(graph))))
        old = graph[nid]["inputs"].get(field)
        graph[nid]["inputs"][field] = coerce(old, val)
        print("set %s.%s = %r" % (nid, field, graph[nid]["inputs"][field]))

    client_id = str(uuid.uuid4())
    t0 = time.time()
    resp = post_json(base + "/prompt", {"prompt": graph, "client_id": client_id})
    pid = resp.get("prompt_id")
    if not pid:
        print("提交被拒：%s" % json.dumps(resp, ensure_ascii=False)[:800])
        return 2
    print("已提交 prompt_id=%s（排队号 %s）" % (pid, resp.get("number")))

    deadline = t0 + a.timeout
    history = None
    while time.time() < deadline:
        time.sleep(3)
        try:
            hist = get_json("%s/history/%s" % (base, pid))
        except Exception as e:
            print("  轮询出错（继续）: %s" % e)
            continue
        if pid in hist:
            history = hist[pid]
            break
        try:
            q = get_json(base + "/queue")
            running = [x[1] for x in q.get("queue_running", [])]
            pending = len(q.get("queue_pending", []))
            print("  %5.1fs  %s  排队 %d" % (time.time() - t0,
                                            "运行中" if pid in running else "等待", pending))
        except Exception:
            pass

    if history is None:
        print("超时未完成（%ds）。任务可能还在跑。" % a.timeout)
        return 3

    status = (history.get("status") or {})
    print("\n状态: %s  用时 %.1fs" % (status.get("status_str"), time.time() - t0))
    if status.get("status_str") != "success":
        for m in status.get("messages", []):
            if m and m[0] in ("execution_error", "execution_interrupted"):
                print("错误详情: %s" % json.dumps(m[1], ensure_ascii=False)[:1500])
        return 4

    os.makedirs(a.outdir, exist_ok=True)
    got = 0
    for node_id, out in (history.get("outputs") or {}).items():
        for key in ("images", "videos", "gifs", "audio"):
            for item in out.get(key, []) or []:
                q = urllib.parse.urlencode({
                    "filename": item.get("filename"),
                    "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output"),
                })
                dest = os.path.join(a.outdir, item.get("filename") or "out.bin")
                with urllib.request.urlopen("%s/view?%s" % (base, q), timeout=600) as r, \
                        open(dest, "wb") as f:
                    f.write(r.read())
                print("产物: %s (%d bytes)" % (dest, os.path.getsize(dest)))
                got += 1
    print("\n完成，%d 个产物。" % got if got else "\n完成，但没有产物节点输出（检查 SaveVideo 是否接上）。")
    return 0 if got else 5


if __name__ == "__main__":
    sys.exit(main())
