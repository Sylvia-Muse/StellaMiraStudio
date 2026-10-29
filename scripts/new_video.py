#!/usr/bin/env python3
"""给新视频开一个规范文件夹：data/videos/YYYYMMDD_序号_短名/

用法：
  py scripts/new_video.py slice02 --title "【清梦酱】……" [--tid 2047]
"""
import argparse, datetime, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "data", "videos")

META_TMPL = {
    "id": "", "title": "", "desc": "", "tags": ["vup", "vtuber", "虚拟主播"],
    "tid_v2": 2047, "declaration": "含AI生成内容",
    "status": "draft", "bvid": "", "published_at": "",
    "duration_sec": 0,
    "stats_snapshot": {"view": 0, "like": 0, "favorite": 0, "reply": 0},
}

README_TMPL = """# {short}

**状态**：draft
**时长**：待定　**规格**：1080×1920 / 30fps　**音色**：muse

## 内容

（写这一条讲什么）

## 怎么重做

```bash
py scripts/debut_v2.py --voice muse --script data/videos/{dirname}/script.json
py scripts/debut_build.py render
py scripts/debut_bgm4.py 60.0
py scripts/debut_build.py mux
```

## 备注

（发布链接、数据、踩的坑）
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("short", help="短名，字母数字连字符")
    ap.add_argument("--title", default="")
    ap.add_argument("--tid", type=int, default=2047)
    a = ap.parse_args()

    os.makedirs(BASE, exist_ok=True)
    today = datetime.date.today().strftime("%Y%m%d")
    # 序号：当天已有几个就 +1
    n = len([d for d in os.listdir(BASE)
             if os.path.isdir(os.path.join(BASE, d)) and d.startswith(today)]) + 1
    dirname = "%s_%02d_%s" % (today, n, a.short)
    path = os.path.join(BASE, dirname)
    if os.path.exists(path):
        raise SystemExit("已存在：" + path)
    os.makedirs(path)

    meta = dict(META_TMPL)
    meta["id"] = dirname
    meta["title"] = a.title
    meta["tid_v2"] = a.tid
    json.dump(meta, open(os.path.join(path, "meta.json"), "w"), ensure_ascii=False, indent=1)
    open(os.path.join(path, "README.md"), "w").write(
        README_TMPL.format(dirname=dirname, short=a.short))
    json.dump([], open(os.path.join(path, "script.json"), "w"), ensure_ascii=False, indent=1)
    print("已创建:", path)
    print("  meta.json / README.md / script.json")


if __name__ == "__main__":
    main()
