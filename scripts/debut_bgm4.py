#!/usr/bin/env python3
"""配乐 v4：把「深沉」换成「活泼」。

v3 是长音铺底，听感偏闷。这版改成：
  · 120 BPM，八分音符的拨弦琶音（音乐盒音色）当主线
  · 和弦走 C – G – Am – F，明亮但不幼稚
  · 轻垫音只做背景，不再有长 drone
  · 每两拍一个很轻的低音拨弦（有律动、不压低频）

用法：/opt/homebrew/bin/python3.14 scripts/debut_bgm4.py [秒数] [输出路径]
"""
import math
import os
import struct
import sys
import wave

SR = 44100
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "debut", "audio", "bgm.wav")

BPM = 120.0
BEAT = 60.0 / BPM
# C - G - Am - F，每两拍换一个（一小节两和弦，节奏更碎、更欢）
CHORDS = [
    [523.25, 659.25, 783.99],   # C5 E5 G5
    [392.00, 587.33, 783.99],   # G4 D5 G5
    [440.00, 659.25, 880.00],   # A4 E5 A5
    [349.23, 523.25, 698.46],   # F4 C5 F5
]
BASS = [130.81, 98.00, 110.00, 87.31]   # C3 G2 A2 F2
ARP_PATTERN = [0, 1, 2, 1]              # 每拍四个音（十六分）
NOTE_LEN = 0.42                          # 拨弦衰减时间常数


def add_pluck(buf, start, freq, amp, decay=0.18, harm=0.25):
    """短促拨弦：基音 + 二次泛音，指数衰减"""
    n0 = int(start * SR)
    length = int(min(0.9, decay * 5) * SR)
    for k in range(length):
        idx = n0 + k
        if idx >= len(buf):
            break
        t = k / SR
        env = math.exp(-t / decay)
        v = math.sin(2 * math.pi * freq * t) + harm * math.sin(2 * math.pi * freq * 2 * t)
        buf[idx] += amp * env * v


def add_pad(buf, start, end, freqs, amp):
    """很轻的垫音，慢慢进出"""
    n0, n1 = int(start * SR), int(min(end, DUR) * SR)
    fade = int(0.35 * SR)
    for i in range(n0, n1):
        t = i / SR
        env = 1.0
        if i - n0 < fade:
            env = (i - n0) / fade
        elif n1 - i < fade:
            env = (n1 - i) / fade
        s = 0.0
        for f in freqs:
            s += math.sin(2 * math.pi * f * t) + 0.15 * math.sin(2 * math.pi * f * 2 * t)
        buf[i] += amp * env * s / len(freqs)


def main():
    n = int(SR * DUR)
    buf = [0.0] * n
    beat = 0
    t = 0.0
    while t < DUR:
        chord = CHORDS[(beat // 2) % len(CHORDS)]
        # 每拍 4 个十六分音符的琶音
        for j in range(4):
            tt = t + j * BEAT / 4
            if tt >= DUR:
                break
            note = chord[ARP_PATTERN[j] % len(chord)]
            add_pluck(buf, tt, note, 0.070, decay=NOTE_LEN * 0.35)
            add_pluck(buf, tt, note * 2, 0.028, decay=NOTE_LEN * 0.22, harm=0.15)
        # 每两拍一个低音拨弦
        if beat % 2 == 0:
            add_pluck(buf, t, BASS[(beat // 2) % len(BASS)], 0.045, decay=0.26, harm=0.10)
        beat += 1
        t += BEAT

    # 垫音：整段铺一层，音量压很低
    seg = 0.0
    while seg < DUR:
        idx = int(seg / (BEAT * 8)) % len(CHORDS)
        add_pad(buf, seg, min(seg + BEAT * 8, DUR), CHORDS[idx], 0.012)
        seg += BEAT * 8

    # 淡入淡出 + 归一化（留点余量，别顶到 0dB）
    fade_in, fade_out = 0.6, 2.0
    for i in range(n):
        tt = i / SR
        g = 1.0
        if tt < fade_in:
            g *= tt / fade_in
        if tt > DUR - fade_out:
            g *= max(0.0, (DUR - tt) / fade_out)
        buf[i] *= g
    peak = max(abs(v) for v in buf) or 1.0
    scale = 0.55 / peak

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with wave.open(OUT, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v * scale)) * 32767)) for v in buf))
    print("配乐 v4:", OUT, os.path.getsize(OUT), "字节", "%.1fs" % DUR)


if __name__ == "__main__":
    main()
