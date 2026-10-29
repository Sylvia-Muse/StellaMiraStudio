#!/usr/bin/env python3
"""出道视频的配乐 v2：把「夜庭」从深沉抬到清亮。

第一版太暗（A3 起、只挂低音 drone、铃音稀疏）听着沉重。这一版：
  · 主垫抬到 A4/C5/E5 一带，低音只留很薄的一层；
  · 和声走 Am → F → C，每段交叉淡入淡出，有往前走的感觉；
  · 铃音用高八度（A5 起），并加一层轻颤的「风铃」；
  · 整体亮度靠泛音叠出来，不靠加音量。

用法：/opt/homebrew/bin/python3.14 scripts/debut_bgm.py [秒数] [输出路径]
"""
import math
import os
import struct
import sys
import wave

SR = 44100
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 21.0
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "debut", "audio", "bgm.wav")

# 三个和弦块：Am - F - C
CHORDS = [
    ([(440.00, 0.055), (523.25, 0.045), (659.25, 0.038)], 0.0, 7.6),    # Am : A4 C5 E5
    ([(349.23, 0.050), (440.00, 0.045), (523.25, 0.040)], 7.0, 14.6),   # F  : F4 A4 C5
    ([(392.00, 0.048), (523.25, 0.045), (659.25, 0.040)], 14.0, 21.5),  # C  : G4 C5 E5
]
DRONE = 110.0
BELLS = [(0.9, 880.00), (3.2, 1046.50), (5.4, 1318.51), (7.8, 1046.50),
         (9.9, 880.00), (12.2, 1318.51), (14.5, 1046.50), (16.7, 1567.98), (18.9, 1046.50)]
NEAR = [(2.4, 1760.00, 0.35), (8.6, 2093.00, 0.28), (15.1, 1760.00, 0.30)]  # 很轻的风铃


def window(t, start, end, edge=0.9):
    """块状淡入淡出窗口"""
    if t <= start or t >= end:
        return 0.0
    return min(1.0, (t - start) / edge, (end - t) / edge)


def env_ad(t, attack, decay):
    if t < 0:
        return 0.0
    if t < attack:
        return t / attack
    return math.exp(-(t - attack) / decay)


def main():
    n = int(SR * DUR)
    buf = [0.0] * n
    tp = 2 * math.pi

    for i in range(n):
        t = i / SR
        s = 0.0
        # 轻微的呼吸起伏（0.85~1.0），不再是大起大落
        breathe = 0.85 + 0.15 * math.sin(tp * t / 7.5)
        for notes, c0, c1 in CHORDS:
            g = window(t, c0, c1)
            if g <= 0:
                continue
            for idx, (freq, amp) in enumerate(notes):
                a = amp * (0.72 + 0.28 * math.sin(tp * t / (11.0 + idx * 2.3) + idx * 1.7))
                # 基音 + 一点二次泛音提亮度（不是放大音量）
                s += g * a * (math.sin(tp * freq * t) + 0.22 * math.sin(tp * freq * 2 * t))
        s *= breathe
        # 很薄的低音，只做「地板」
        s += 0.008 * math.sin(tp * DRONE * t) + 0.006 * math.sin(tp * DRONE * 1.5 * t + 0.3)
        buf[i] = s

    # 高频微光：2~3kHz 的慢速簇音，只做亮度，不抢主体
    for i in range(n):
        t = i / SR
        s = buf[i]
        s += 0.010 * math.sin(tp * 2093.0 * t) * (0.5 + 0.5 * math.sin(tp * t / 6.1))
        s += 0.007 * math.sin(tp * 2637.0 * t + 0.8) * (0.5 + 0.5 * math.sin(tp * t / 7.3 + 1.2))
        s += 0.005 * math.sin(tp * 3136.0 * t + 2.1) * (0.5 + 0.5 * math.sin(tp * t / 5.4 + 2.4))
        buf[i] = s

    # 高八度铃音
    for start, freq in BELLS:
        base = int(start * SR)
        length = int(1.4 * SR)
        for k in range(length):
            idx = base + k
            if idx >= n:
                break
            t = k / SR
            g = env_ad(t, 0.005, 0.40)
            if g <= 0:
                continue
            v = (math.sin(tp * freq * t)
                 + 0.30 * math.sin(tp * freq * 2.0 * t)
                 + 0.12 * math.sin(tp * freq * 3.01 * t))
            buf[idx] += 0.055 * g * v
        for delay, gain in ((0.26, 0.30), (0.52, 0.10)):
            off = int(delay * SR)
            for k in range(length):
                idx = base + off + k
                if idx >= n:
                    break
                t = k / SR
                g = env_ad(t, 0.005, 0.40)
                if g > 0:
                    buf[idx] += 0.055 * gain * g * math.sin(tp * freq * t)

    # 风铃：极轻的高音点缀，带颤音
    for start, freq, amp in NEAR:
        base = int(start * SR)
        length = int(2.2 * SR)
        for k in range(length):
            idx = base + k
            if idx >= n:
                break
            t = k / SR
            g = env_ad(t, 0.004, 0.70)
            if g <= 0:
                continue
            trem = 1.0 + 0.12 * math.sin(tp * 5.2 * t)
            buf[idx] += amp * 0.05 * g * trem * math.sin(tp * freq * t)

    fade_in, fade_out = 0.9, 2.6
    for i in range(n):
        t = i / SR
        g = 1.0
        if t < fade_in:
            g *= t / fade_in
        if t > DUR - fade_out:
            g *= max(0.0, (DUR - t) / fade_out)
        buf[i] *= g
    peak = max(abs(v) for v in buf) or 1.0
    scale = 0.44 / peak

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with wave.open(OUT, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v * scale)) * 32767)) for v in buf))
    print("配乐 v2:", OUT, os.path.getsize(OUT), "字节", "%.1fs" % DUR)


if __name__ == "__main__":
    main()
