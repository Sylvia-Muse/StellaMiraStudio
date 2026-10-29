#!/usr/bin/env python3
"""唱歌试验：把 TTS 逐音节合成，再按旋律做音高变换，拼成一段「唱」。

原理（没有 Seed-VC 时的土办法）：
  1) 每个音节单独合成（muse 音色），得到一个基准基频的短音
  2) 用 asetrate 改变采样率来整体升/降调，再用 atempo 把时长拉回目标值
  3) 按音符时长拼接，加淡入淡出，最后统一混响（aecho）

输出：data/debut/audio/sing_poc.wav

用法：py scripts/sing_poc.py
"""
import json
import math
import os
import subprocess
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = "/tmp/sing_poc"
OUT = os.path.join(ROOT, "data", "debut", "audio", "sing_poc.wav")
GATEWAY = "http://127.0.0.1:11091/v1"
CONF = os.path.expanduser("~/.dsh/mira_config/mira_qqbot/config.json")
FFMPEG = os.path.expanduser("~/bin/ffmpeg")
VOICE = "muse"

# 音节 → MIDI 音高 → 时值(秒)
# 用一句自拟旋律，先验证技术链路（不涉及原曲版权）
NOTES = [
    ("世", 60, 0.34), ("界", 64, 0.34), ("执", 67, 0.34), ("行", 72, 0.62),
    ("我", 71, 0.34), ("的", 69, 0.34), ("梦", 67, 0.75),
]


def midi_to_freq(m):
    return 440.0 * (2 ** ((m - 69) / 12))


def tts(text, out):
    key = json.load(open(CONF))["tts"]["key"]
    body = json.dumps({"model": "qwen3-tts-flash", "input": text, "voice": VOICE,
                       "response_format": "wav", "sample_rate": 24000}).encode()
    import urllib.request
    req = urllib.request.Request(GATEWAY + "/audio/speech", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + key})
    data = urllib.request.urlopen(req, timeout=120).read()
    if len(data) < 2000:
        raise SystemExit("合成失败: %r" % data[:120])
    open(out, "wb").write(data)


def f0_median(path):
    """量一下实际基频，验证移调有没有生效"""
    w = wave.open(path, "rb")
    sr, ch = w.getframerate(), w.getnchannels()
    raw = w.readframes(w.getnframes())
    w.close()
    import struct
    s = list(struct.unpack("<%dh" % (len(raw) // 2), raw))[::ch]
    step = max(1, sr // 16000); fs = sr // step
    x = [v / 32768.0 for v in s[::step]]
    win, hop = int(0.04 * fs), int(0.02 * fs)
    vals = []
    for st in range(0, max(1, len(x) - win), hop):
        fr = x[st:st + win]
        if sum(v * v for v in fr) / win < 0.002:
            continue
        best, bv = None, 0
        for lag in range(int(fs / 500), int(fs / 70)):
            c = nm = 0.0
            for i in range(0, win - lag, 3):
                c += fr[i] * fr[i + lag]; nm += fr[i] * fr[i]
            if nm <= 0: continue
            v = c / nm
            if v > bv: bv, best = v, lag
        if best and bv > 0.35:
            vals.append(fs / best)
    vals.sort()
    return vals[len(vals) // 2] if vals else 0.0


def tempo_chain(factor):
    """atempo 只接受 0.5~100，超出就拆成两段"""
    if 0.5 <= factor <= 2.0:
        return "atempo=%.6f" % factor
    if factor < 0.5:
        mid = math.sqrt(factor)
        return "atempo=%.6f,atempo=%.6f" % (mid, factor / mid)
    return "atempo=%.6f" % factor


def main():
    os.makedirs(WORK, exist_ok=True)
    segs = []
    print("%-4s %-6s %-8s %-8s %-8s" % ("音节", "目标Hz", "原始Hz", "移调后Hz", "时长"))
    for i, (ch, midi, dur) in enumerate(NOTES):
        raw = os.path.join(WORK, "%02d_raw.wav" % i)
        fixed = os.path.join(WORK, "%02d_fix.wav" % i)
        tts(ch, raw)
        base = f0_median(raw) or 300.0
        target = midi_to_freq(midi)
        ratio = target / base
        # 先改采样率升/降调，再用 atempo 拉回时长
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", raw,
                        "-af", "asetrate=24000*%.6f,aresample=24000,%s,"
                               "apad=whole_dur=%.3f,atrim=0:%.3f" % (ratio, tempo_chain(1 / ratio), dur, dur),
                        fixed], check=True)
        got = f0_median(fixed)
        print("%-4s %-6.0f %-8.0f %-8.0f %-8.2f" % (ch, target, base, got, dur))
        segs.append(fixed)

    listing = os.path.join(WORK, "list.txt")
    with open(listing, "w") as f:
        for s in segs:
            f.write("file '%s'\n" % s)
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                    "-safe", "0", "-i", listing,
                    "-af", "aecho=0.8:0.7:24:0.25", OUT], check=True)
    print("输出:", OUT, os.path.getsize(OUT), "字节")
    print("整段 F0 中位: %.0f Hz" % f0_median(OUT))


if __name__ == "__main__":
    main()
