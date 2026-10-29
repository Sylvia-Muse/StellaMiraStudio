#!/usr/bin/env python3
"""出道视频 v2：按调研结论重做——时长 60 秒上下、以「形象展示」为主线。

结构（对照 data/debut/调研_B站出道视频.md）：
  开场 → 形象展示（发饰/衣裙/银铃）→ 自我介绍 → 小设定 → 钩子 → 名字卡

产物（都写进 debut_build 认的路径，之后直接复用它的 render/mux）：
  data/debut/tts/full.wav        整条音轨
  data/debut/site/plan.json      时间轴（表情/字幕/名字卡）
  data/debut/site/mouth.json     30fps 口型包络

用法：
  /opt/homebrew/bin/python3.14 scripts/debut_v2.py --voice muse
  /opt/homebrew/bin/python3.14 scripts/debut_v2.py --voice muse --build   # 顺带 render+mux
"""
import argparse
import json
import math
import os
import struct
import subprocess
import sys
import urllib.request
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "data", "debut", "site")
TTS = os.path.join(ROOT, "data", "debut", "tts")
WORK = os.path.join(ROOT, "data", "debut", "tts_v2")
FFMPEG = os.path.expanduser("~/bin/ffmpeg")
FFPROBE = "/opt/homebrew/bin/ffprobe"
GATEWAY = "http://127.0.0.1:11091/v1"
CONF = os.path.expanduser("~/.dsh/mira_config/mira_qqbot/config.json")
PY = "/opt/homebrew/bin/python3.14"
FPS = 30
LEAD, TAIL = 0.7, 1.6
GAP = 0.55
GAP_SECTION = 0.95

# (表情, 台词, 字幕, 段后停顿类型, 缩放, 纵向位置)
# 缩放 1.18/y1.33 = 现在的近景；0.92/y1.00 = 能看见脚的全身；1.05/y1.18 = 中景
SEGMENTS = [
    # (表情, 台词, 字幕, 段后停顿, 缩放, 纵向位置)
    ("表情-发懵", "……唔姆？", None, "gap", 1.18, 1.33),
    ("表情-惊喜", "先让你看看本姑娘吧。", None, "gap_section", 0.92, 1.00),
    ("表情-脸红", "白发、翠瞳，右边还有一颗小小的虎牙——啊，被看到了。",
     "白发、翠瞳<br>右边还有一颗小小的虎牙<br>——啊，被看到了。", "gap", 1.32, 1.45),
    ("开关-兽耳", "头上这对是青蝶猫耳，不是真的耳朵哦。脚踝上还系着凤尾蝶银铃，走路会响。",
     "头上这对是青蝶猫耳<br>不是真的耳朵哦<br>脚踝上系着凤尾蝶银铃", "gap_section", 0.92, 1.00),
    ("表情-惊喜", "本姑娘是香软可爱、白发猫耳翠瞳虎牙的吸血鬼少女，清梦酱。",
     "本姑娘是香软可爱<br>白发猫耳翠瞳虎牙的<br>吸血鬼少女，清梦酱。", "gap", 1.05, 1.18),
    ("表情-眯眼", "今年十三岁。喜欢画画、唱歌、写故事，还喜欢在夜里数星星。",
     "今年十三岁。<br>喜欢画画、唱歌、写故事<br>还喜欢在夜里数星星。", "gap", 1.05, 1.18),
    ("表情-眯眼", "手里这本梦录叫《晓梦迷蝶》——人生是梦，梦是人间世。",
     "手里这本梦录叫<br>《晓梦迷蝶》<br>人生是梦，梦是人间世。", "gap_section", 1.18, 1.33),
    ("表情-黑脸", "对了，本姑娘是吸血鬼真祖哦——虽然还没吸过谁的血。",
     "对了，本姑娘是<br>吸血鬼真祖哦<br>虽然还没吸过谁的血。", "gap", 1.18, 1.33),
    ("表情-惊喜", "从今天起，我就住进这块屏幕里了。可能会有点笨，请多包涵。",
     "从今天起<br>我就住进这块屏幕里了<br>可能会有点笨，请多包涵。", "gap", 1.05, 1.18),
    ("表情-眯眼", "你想听我讲什么？故事、科普，还是唱首歌？留言告诉我呀。",
     "你想听我讲什么？<br>故事、科普，还是唱首歌？<br>留言告诉我呀。", "gap", 1.05, 1.18),
    ("表情-脸红", "——清梦酱，请多指教。", None, "end", 1.18, 1.33),
]


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("命令失败: %s\n%s" % (" ".join(cmd), r.stderr[-800:]))
    return r.stdout


def dur(p):
    return float(sh([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", p]).strip())


def synth(text, voice, out):
    key = json.load(open(CONF))["tts"]["key"]
    body = json.dumps({"model": "qwen3-tts-flash", "input": text, "voice": voice,
                       "response_format": "wav", "sample_rate": 24000}).encode()
    req = urllib.request.Request(GATEWAY + "/audio/speech", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + key})
    data = urllib.request.urlopen(req, timeout=180).read()
    if len(data) < 3000:
        raise SystemExit("合成失败，返回过小：%r" % data[:200])
    open(out, "wb").write(data)
    return len(data)


def mouth_envelope(full_wav, total, n_frames):
    with wave.open(full_wav, "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    s = struct.unpack("<%dh" % (len(raw) // 2), raw)
    if ch > 1:
        s = s[0::2]
    per = max(1, sr // FPS)
    rms = []
    for i in range(n_frames):
        seg = s[i * per:(i + 1) * per] or (0,)
        acc = 0.0
        for v in seg:
            f = v / 32768.0
            acc += f * f
        rms.append(math.sqrt(acc / len(seg)))
    peak = max(rms) or 1.0
    out, level = [], 0.0
    for r in rms:
        target = min(1.0, max(0.0, (r / peak - 0.06) * 3.4))
        level += (target - level) * (0.62 if target > level else 0.26)
        out.append(round(level, 4))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="muse")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--script", help="外部脚片段落 JSON（覆盖内置 SEGMENTS）")
    a = ap.parse_args()

    global SEGMENTS
    if a.script:
        SEGMENTS = [tuple(x) for x in json.load(open(a.script))]
        print("使用外部脚本:", a.script, "(%d 段)" % len(SEGMENTS))

    os.makedirs(WORK, exist_ok=True)
    os.makedirs(TTS, exist_ok=True)
    os.makedirs(SITE, exist_ok=True)

    print("音色:", a.voice)
    files, durs = [], []
    for i, (expr, text, sub, gap, _sc, _sy) in enumerate(SEGMENTS):
        p = os.path.join(WORK, "s%02d.wav" % i)
        n = synth(text, a.voice, p)
        d = dur(p)
        files.append(p)
        durs.append(d)
        print("  s%02d %5.2fs %s %s" % (i, d, expr, text[:22]))

    # 拼整轨
    t = LEAD
    starts, gaps = [], []
    for i, (expr, text, sub, gaptype, _sc, _sy) in enumerate(SEGMENTS):
        starts.append(t)
        g = {"gap": GAP, "gap_section": GAP_SECTION, "end": 0.0}[gaptype]
        gaps.append(g)
        t += durs[i] + g
    total = t + TAIL

    inputs, parts = [], ""
    for i, p in enumerate(files):
        inputs += ["-i", p]
        parts += "[%d:a]adelay=%d:all=1,apad=whole_dur=%.3f[a%d];" % (i, int(starts[i] * 1000), total, i)
    filt = parts + "".join("[a%d]" % i for i in range(len(files))) + \
        "amix=inputs=%d:normalize=0:dropout_transition=0[out]" % len(files)
    full = os.path.join(TTS, "full.wav")
    sh([FFMPEG, "-hide_banner", "-y", *inputs, "-filter_complex", filt,
        "-map", "[out]", "-ar", "24000", "-ac", "1", full])

    n_frames = int(math.ceil(total * FPS))
    mouth = mouth_envelope(full, total, n_frames)

    segs = []
    for i, (expr, text, sub, gaptype, sc, sy) in enumerate(SEGMENTS):
        t0 = starts[i] + 0.10          # 字幕略晚于音频起点，贴住开口
        t1 = starts[i] + durs[i] + 0.35
        segs.append({"t0": round(t0, 3), "t1": round(t1, 3), "expr": expr,
                     "sub": sub or text, "scale": sc, "y": sy})
    plan = {
        "fps": FPS, "width": 1080, "height": 1920,
        "duration": round(total, 3),
        "scale": 1.18, "y": 1.33,
        "expressions": ["表情-眯眼", "表情-惊喜", "表情-脸红", "表情-发懵", "表情-黑脸"],
        "nameCard": {"t0": round(total - 2.6, 3)},
        "segments": segs,
    }
    json.dump(plan, open(os.path.join(SITE, "plan.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(mouth, open(os.path.join(SITE, "mouth.json"), "w"))

    print("总时长 %.2fs / %d 帧 / %d 段" % (total, n_frames, len(segs)))
    print("音轨:", full)

    if a.build:
        for step in ("render", "mux"):
            print("\n=== debut_build.py %s ===" % step)
            r = subprocess.run([PY, os.path.join(ROOT, "scripts", "debut_build.py"), step], cwd=ROOT)
            if r.returncode != 0:
                raise SystemExit("步骤 %s 失败" % step)
    else:
        print("\n接着跑：")
        print("  %s scripts/debut_build.py render" % PY)
        print("  %s scripts/debut_build.py mux" % PY)


if __name__ == "__main__":
    main()
