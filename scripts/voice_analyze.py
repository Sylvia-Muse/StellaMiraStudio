#!/usr/bin/env python3
"""音色体检：一个 wav 的采样率/声道/时长/基频/音量，一次量清楚。

为什么写这个：2026-10-27 量 rosy.wav 时忘了立体声要去交织，把左右交错的样本
当成单序列做自相关，算出来正好是一半频率（137.8Hz 实为 ~275Hz），还据此下了
「音色深沉」的错结论。这个脚本把「按声道分开、取第一个可信峰」写死，免得再犯。

用法：
  python3.14 scripts/voice_analyze.py a.wav b.wav ...
  python3.14 scripts/voice_analyze.py --text "唔姆，本姑娘是清梦酱。" a.wav   # 顺便算字/秒
"""
import argparse
import math
import os
import struct
import sys
import wave

MAX_SEC = 30.0


def load(path, max_sec=MAX_SEC):
    w = wave.open(path, "rb")
    sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
    raw = w.readframes(int(sr * max_sec))
    w.close()
    # 网关（以及不少 TTS 服务）返回的 wav 头里 data 长度是流式写的 0x3FFFFFFF，
    # wave 会把它当真、算出上万秒的假时长；所以时长一律按**实际读到的字节**算。
    real_frames = len(raw) // (2 * ch)
    dur = real_frames / sr if sr else 0.0
    data = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
    # 关键：按声道分开，绝不把交错样本当一条序列
    chans = [data[c::ch] for c in range(ch)]
    return sr, ch, dur, chans


def rms(x):
    if not x:
        return 0.0
    return math.sqrt(sum(v * v for v in x) / len(x)) / 32768.0


def f0_stats(x, sr, win_ms=40, hop_ms=20, fmin=70, fmax=500, thr=0.30):
    """归一化自相关 + 「取第一个可信峰」抑制低八度错误。"""
    step = max(1, sr // 16000)
    fs = sr // step
    xx = [v / 32768.0 for v in x[::step]]
    win, hop = int(win_ms / 1000 * fs), int(hop_ms / 1000 * fs)
    if win < 8:
        return None
    lo, hi = int(fs / fmax), int(fs / fmin)
    f0 = []
    for st in range(0, max(0, len(xx) - win), hop):
        fr = xx[st:st + win]
        energy = sum(v * v for v in fr) / win
        if energy < 0.0008:
            continue
        ac = []
        for lag in range(lo, hi + 1):
            c = 0.0
            nm = 0.0
            for i in range(0, win - lag, 2):
                c += fr[i] * fr[i + lag]
                nm += fr[i] * fr[i]
            ac.append((c / nm) if nm > 0 else 0.0)
        # 取第一个过阈值的局部峰（而不是全局最大），避免落到 1/2 频率上
        pick = None
        for k in range(1, len(ac) - 1):
            if ac[k] > thr and ac[k] >= ac[k - 1] and ac[k] >= ac[k + 1]:
                pick = k
                break
        if pick is None:
            continue
        # 抛物线插值细化
        y0, y1, y2 = ac[pick - 1], ac[pick], ac[pick + 1]
        denom = (y0 - 2 * y1 + y2) or 1e-9
        delta = 0.5 * (y0 - y2) / denom
        lag = lo + pick + max(-1.0, min(1.0, delta))
        f0.append(fs / lag)
    if not f0:
        return None
    f0.sort()
    n = len(f0)
    return {
        "n": n,
        "med": f0[n // 2],
        "p10": f0[n // 10],
        "p90": f0[n * 9 // 10],
    }


def report(path, text=None):
    if not os.path.exists(path):
        print("%-28s 不存在" % os.path.basename(path))
        return
    sr, ch, dur, chans = load(path)
    print("=" * 74)
    print("文件: %s" % path)
    print("规格: %dHz / %d 声道 / %.2fs%s" % (sr, ch, dur, "（wav 头长度字段是流式占位，时长按实际字节算）" if dur < 3600 else ""))
    best = None
    for idx, c in enumerate(chans):
        r = rms(c)
        st = f0_stats(c, sr)
        tag = "ch%d" % idx if ch > 1 else "mono"
        vol_db = 20 * math.log10(r) if r > 0 else -99
        if st:
            print("  %-5s RMS %.1f dB | F0 中位 %.1f Hz (P10-P90 %.1f-%.1f, %d 帧)" % (
                tag, vol_db, st["med"], st["p10"], st["p90"], st["n"]))
            if best is None or st["n"] > best[1]["n"]:
                best = (tag, st)
        else:
            print("  %-5s RMS %.1f dB | 没测到稳定基频" % (tag, vol_db))
    if best and text:
        chars = len([c for c in text if not c.isspace()])
        rate = chars / dur if dur > 0 else 0
        print("  语速: %d 字 / %.2fs = %.2f 字/秒" % (chars, dur, rate))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--text", help="这段音频对应的文本（用来算字/秒）")
    a = ap.parse_args()
    for f in a.files:
        report(f, a.text)


if __name__ == "__main__":
    main()
