#!/usr/bin/env python3
"""《把月光折成一只蝶》——谱曲 + 写 MIDI + 合成试听。

旋律和和弦都是我写的数据；MIDI 用纯字节写（不依赖 mido），试听用一个简单的
加法合成器（正弦 + 二次泛音 + 指数包络），只为了听清走向，不是成品音色。

用法：
  py scripts/song_midi.py            # 输出 .mid 与试听 .wav 到 data/videos/.../music/
"""
import os
import struct
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "videos", "20261028_03_song01", "music")
BPM = 110.0
BEAT = 60.0 / BPM
SR = 44100

# ── 旋律：(歌词音节, MIDI 音高, 拍数)  ─────────────────────────────
# 主歌：C 大调，多级进，尾音落在属音
VERSE1 = [
    ("我", 64, 1), ("住", 64, 0.5), ("在", 62, 0.5), ("屏", 60, 1), ("幕", 60, 0.5), ("的", 62, 0.5),
    ("这", 64, 1), ("一", 62, 0.5), ("侧", 60, 1.5),
]
VERSE2 = [
    ("数", 60, 1), ("着", 62, 0.5), ("你", 64, 0.5), ("的", 64, 1), ("呼", 62, 1), ("吸", 60, 0.5), ("声", 62, 1.5),
]
# 副歌：抬到 G4 以上，句尾上扬
CHORUS1 = [
    ("把", 67, 1), ("月", 67, 0.5), ("光", 69, 0.5), ("折", 67, 1), ("成", 64, 0.5), ("一", 65, 0.5),
    ("只", 67, 1), ("蝶", 72, 1.5),
]
CHORUS2 = [
    ("落", 71, 0.5), ("在", 69, 0.5), ("你", 67, 0.5), ("的", 69, 0.5), ("指", 67, 0.5), ("尖", 64, 2.0),
]
CHORUS3 = [
    ("如", 67, 1), ("果", 67, 0.5), ("你", 69, 0.5), ("抬", 71, 1), ("头", 69, 0.5), ("看", 67, 0.5), ("我", 67, 1.5),
]
CHORUS4 = [
    ("我", 69, 0.5), ("就", 69, 0.5), ("亮", 71, 1), ("起", 72, 1), ("来", 72, 2.0),
]

SECTIONS = [
    ("verse", VERSE1), ("verse", VERSE2),
    ("chorus", CHORUS1), ("chorus", CHORUS2),
    ("chorus", CHORUS3), ("chorus", CHORUS4),
]

# ── 和弦：(起始拍, [MIDI...]) ───────────────────────────────────
CHORDS = [
    (0, [48, 55, 60, 64]),    # C
    (4, [45, 52, 57, 60]),    # Am
    (8, [41, 48, 53, 57]),    # F
    (12, [43, 50, 55, 59]),   # G
    (16, [48, 55, 60, 64]),   # C
    (20, [45, 52, 57, 64]),   # Am
    (24, [41, 48, 53, 57]),   # F
    (28, [43, 50, 55, 62]),   # G
    (32, [48, 55, 60, 64]),   # C
    (36, [45, 52, 57, 60]),   # Am
    (40, [41, 48, 53, 57]),   # F
    (44, [43, 50, 55, 59]),   # G
]


def vlq(n):
    """MIDI 变长量"""
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def track(events):
    """events: [(tick, bytes)]，按 tick 排序后编码成 MTrk"""
    data = b"".join(vlq(t - (events[i - 1][0] if i else 0)) + e
                    for i, (t, e) in enumerate(events))
    data += vlq(0) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + data


def main():
    os.makedirs(OUT, exist_ok=True)
    tpb = 480                      # ticks per beat
    tempo_us = int(60_000_000 / BPM)

    # 旋律轨（含歌词元事件）
    ev, t, lyrics = [], 0, []
    for kind, section in SECTIONS:
        for syll, pitch, beats in section:
            dur = int(beats * tpb)
            ev.append((t, bytes([0x90, pitch, 92])))
            ev.append((t + dur - 6, bytes([0x80, pitch, 64])))
            lyrics.append((t, syll))
            t += dur
    # 歌词以文本事件写在旋律前（供 ACE Studio / 记谱软件读取）
    meta = [(0, b"\xff\x03\x0c" + "清梦-月光蝶".encode())]
    for tick, syll in lyrics:
        b = syll.encode()
        meta.append((tick, b"\xff\x05" + vlq(len(b)) + b))
    melody = track(sorted(meta + ev))
    end_tick = t

    # 和弦轨
    cev = []
    for start, notes in CHORDS:
        tick = start * tpb
        dur = 4 * tpb - 8
        for n in notes:
            cev.append((tick, bytes([0x90, n, 56])))
            cev.append((tick + dur, bytes([0x80, n, 40])))
    chords = track(sorted(cev))

    header = (b"MThd" + struct.pack(">IHHH", 6, 1, 2, tpb))
    tempo = track([(0, b"\xff\x51\x03" + tempo_us.to_bytes(3, "big")),
                   (0, b"\xff\x58\x04\x04\x02\x18\x08")])
    midi = header + tempo + melody + chords
    mid_path = os.path.join(OUT, "yueguang_die.mid")
    open(mid_path, "wb").write(midi)

    # ── 试听：加法合成 ──
    total_s = end_tick / tpb * BEAT + 2.0
    n = int(SR * total_s)
    buf = [0.0] * n

    def add(start_s, freq, dur_s, amp, decay=0.30, harm=0.30):
        n0 = int(start_s * SR)
        ln = int(min(dur_s * 1.6, 2.5) * SR)
        for k in range(ln):
            i = n0 + k
            if i >= n:
                break
            tt = k / SR
            env = min(1.0, tt / 0.012) * (1.0 if tt < dur_s else max(0.0, 1 - (tt - dur_s) / 0.12))
            env *= 0.55 + 0.45 * (1.0 if tt < dur_s else 0.0)
            v = (1 - decay * tt) if tt < dur_s else 0.0
            if v <= 0:
                continue
            buf[i] += amp * env * v * (math_sin(freq * tt) + harm * math_sin(2 * freq * tt))

    def math_sin(x):
        import math
        return math.sin(2 * 3.141592653589793 * x)

    for kind, section in SECTIONS:
        for syll, pitch, beats in section:
            add(t * 0 + 0, 0, 0, 0)      # 占位
    # 重新按时间轴铺旋律
    t = 0
    for kind, section in SECTIONS:
        for syll, pitch, beats in section:
            freq = 440.0 * 2 ** ((pitch - 69) / 12)
            add(t * BEAT, freq, beats * BEAT * 0.92, 0.16 if kind == "chorus" else 0.13)
            t += beats
    # 和弦铺底
    for start, notes in CHORDS:
        for m in notes:
            freq = 440.0 * 2 ** ((m - 69) / 12)
            add(start * BEAT, freq, 4 * BEAT * 0.96, 0.035, decay=0.06, harm=0.15)

    peak = max(abs(v) for v in buf) or 1.0
    scale = 0.6 / peak
    wav_path = os.path.join(OUT, "yueguang_die_preview.wav")
    with wave.open(wav_path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v * scale)) * 32767)) for v in buf))

    n_syll = sum(len(s) for _, s in SECTIONS)
    print("MIDI :", mid_path, len(midi), "字节，%d 小节 / %d 个音节" % (end_tick // (4 * tpb), n_syll))
    print("试听 :", wav_path, os.path.getsize(wav_path), "字节，%.1f 秒" % total_s)


if __name__ == "__main__":
    main()
