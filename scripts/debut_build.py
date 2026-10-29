#!/usr/bin/env python3
"""清梦《出道视频》样板：音频拼装 → 口型包络 → 时间轴 → 逐帧渲染 → 混流。

用法：
  /opt/homebrew/bin/python3.14 scripts/debut_build.py assets     # 拼音频、算口型、写 plan.json
  /opt/homebrew/bin/python3.14 scripts/debut_build.py frame 120  # 单帧试渲染（调构图用）
  /opt/homebrew/bin/python3.14 scripts/debut_build.py render     # 全片逐帧
  /opt/homebrew/bin/python3.14 scripts/debut_build.py mux        # 帧 + 音轨 → mp4
"""
import base64
import http.server
import json
import math
import os
import socketserver
import struct
import subprocess
import sys
import threading
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEBUT = os.path.join(ROOT, "data", "debut")
SITE = os.path.join(DEBUT, "site")
FRAMES = os.path.join(DEBUT, "frames")
TTS = os.path.join(DEBUT, "tts")
FFMPEG = os.path.expanduser("~/bin/ffmpeg")
FFPROBE = "/opt/homebrew/bin/ffprobe"
FPS = 30

LEAD, GAP, TAIL = 0.55, 0.42, 0.85
LINES = [
    ("L1.wav", "唔姆，初次见面呀！"),
    ("L2.wav", "本姑娘是香软可爱、白发猫耳翠瞳虎牙"),
    ("L3.wav", "的吸血鬼少女——清梦酱！"),  # 占位，真正按 L2 内部切分
]
# 真正的三段台词（L2 里第一个小句 + 剩下那句拆成两条字幕，表情换一次）
SUBS = {
    "L1": ["唔姆，初次见面呀！"],
    "L2": ["本姑娘是香软可爱<br>白发猫耳翠瞳虎牙的吸血鬼少女", "——清梦酱！"],
    "L3": ["从今天起，就住进这个屏幕里啦<br>请多指教哦！"],
}


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise SystemExit("命令失败: %s\n%s\n%s" % (" ".join(cmd), r.stdout[-2000:], r.stderr[-2000:]))
    return r.stdout


def dur(path):
    return float(sh([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", path]).strip())


def silences(path, noise="-40dB", min_d=0.25):
    """返回 [(start, end), ...]：给换声后的台词找气口，别再用写死的比例切字幕。

    注意：silencedetect 的信息打在 **stderr**，不能用只收 stdout 的 sh()。
    """
    proc = subprocess.run([FFMPEG, "-hide_banner", "-i", path, "-af",
                           "silencedetect=noise=%s:d=%s" % (noise, min_d), "-f", "null", "-"],
                          capture_output=True, text=True)
    out = (proc.stderr or "") + (proc.stdout or "")
    starts, ends = [], []
    for line in out.splitlines():
        if "silence_start:" in line:
            try:
                starts.append(float(line.split("silence_start:")[1].split()[0]))
            except ValueError:
                pass
        elif "silence_end:" in line:
            try:
                ends.append(float(line.split("silence_end:")[1].split()[0]))
            except ValueError:
                pass
    return list(zip(starts, ends))


def speech_start(path, total):
    """这句台词真正开口的时刻（跳过开头那段静音）；找不到就返回 0。"""
    for s0, s1 in silences(path):
        if s0 < 0.05 and s1 < total * 0.4:
            return s1
    return 0.0


def split_at_pause(path, total):
    """L2 里最长的中间停顿（跳过首尾），返回停顿中点；找不到返回 None。"""
    cands = [(s0, s1) for s0, s1 in silences(path)
             if s0 > 0.5 and s1 < total - 0.15]
    if not cands:
        return None
    s0, s1 = max(cands, key=lambda p: p[1] - p[0])
    if (s1 - s0) < 0.18:
        return None
    return (s0 + s1) / 2


def build_assets():
    os.makedirs(TTS, exist_ok=True)
    d = {k: dur(os.path.join(TTS, k + ".wav")) for k in ("L1", "L2", "L3")}
    t1 = LEAD
    t2 = t1 + d["L1"] + GAP
    t3 = t2 + d["L2"] + GAP
    total = t3 + d["L3"] + TAIL

    # 1) 拼音轨：每条按偏移叠加（互不重叠，直接 amix 不归一化）
    delays = [t1, t2, t3]
    inputs = []
    for k in ("L1", "L2", "L3"):
        inputs += ["-i", os.path.join(TTS, k + ".wav")]
    parts = "".join(
        "[%d:a]adelay=%d:all=1,apad=whole_dur=%.3f[a%d];" % (i, int(delays[i] * 1000), total, i)
        for i in range(3)
    )
    filt = parts + "[a0][a1][a2]amix=inputs=3:normalize=0:dropout_transition=0[out]"
    full = os.path.join(TTS, "full.wav")
    sh([FFMPEG, "-hide_banner", "-y", *inputs, "-filter_complex", filt, "-map", "[out]",
        "-ar", "24000", "-ac", "1", full])

    # 2) 口型包络：30fps RMS → 0..1，带上升/下落不对称平滑
    n_frames = int(math.ceil(total * FPS))
    with wave.open(full, "rb") as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1 and w.getsampwidth() == 2
        raw = w.readframes(w.getnframes())
    samples = struct.unpack("<%dh" % (len(raw) // 2), raw)
    per = 24000 // FPS
    rms = []
    for i in range(n_frames):
        seg = samples[i * per:(i + 1) * per] or (0,)
        s = 0.0
        for v in seg:
            f = v / 32768.0
            s += f * f
        rms.append(math.sqrt(s / len(seg)))
    peak = max(rms) or 1.0
    mouth, level = [], 0.0
    for i in range(n_frames):
        target = min(1.0, max(0.0, (rms[i] / peak - 0.06) * 3.4))
        k = 0.62 if target > level else 0.26
        level += (target - level) * k
        mouth.append(round(level, 4))

    # 3) 时间轴
    p1, p2, p3 = (os.path.join(TTS, k + ".wav") for k in ("L1", "L2", "L3"))
    lead1, lead2, lead3 = speech_start(p1, d["L1"]), speech_start(p2, d["L2"]), speech_start(p3, d["L3"])
    pause = split_at_pause(p2, d["L2"])
    split = t2 + (pause if pause is not None else d["L2"] * 0.753)

    segs = []
    segs.append({"t0": 0.0, "t1": t1, "expr": "表情-眯眼", "sub": ""})
    # 字幕卡在真正开口那一刻，而不是每句音频的起点（起点里常带半秒静音）
    segs.append({"t0": t1 + lead1, "t1": t2, "expr": "表情-惊喜", "sub": SUBS["L1"][0]})
    segs.append({"t0": t2 + lead2, "t1": split, "expr": "表情-脸红", "sub": SUBS["L2"][0]})
    segs.append({"t0": split, "t1": t3, "expr": "表情-惊喜", "sub": SUBS["L2"][1]})
    segs.append({"t0": t3 + lead3, "t1": total, "expr": "表情-眯眼", "sub": SUBS["L3"][0]})
    plan = {
        "fps": FPS, "width": 1080, "height": 1920,
        "duration": round(total, 3),
        "scale": 1.18, "y": 1.33,
        "expressions": ["表情-眯眼", "表情-惊喜", "表情-脸红", "表情-发懵"],
        "nameCard": {"t0": round(total - 2.4, 3)},
        "segments": segs,
    }
    with open(os.path.join(SITE, "plan.json"), "w") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    with open(os.path.join(SITE, "mouth.json"), "w") as f:
        json.dump(mouth, f)

    print(json.dumps({"leads": [round(lead1, 3), round(lead2, 3), round(lead3, 3)],
                      "pause_split": round(split - t2, 3), "durations": d, "t1": round(t1, 3), "t2": round(t2, 3),
                      "t3": round(t3, 3), "total": round(total, 3),
                      "frames": n_frames, "wav": full,
                      "peak_frame": max(range(len(mouth)), key=lambda i: mouth[i])},
                     ensure_ascii=False))
    return plan


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=SITE, **kw)

    def log_message(self, *a):
        pass


def serve():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def open_page(pw, port, width=1080, height=1920):
    b = pw.chromium.launch(args=["--enable-unsafe-swiftshader",
                                 "--autoplay-policy=no-user-gesture-required"])
    pg = b.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
    pg.goto("http://127.0.0.1:%d/index.html" % port, wait_until="load")
    for _ in range(200):
        st = pg.evaluate("() => ({r: window.debut && window.debut.ready, e: window.debut && window.debut.error})")
        if st.get("e"):
            raise SystemExit("页面报错: " + str(st["e"]))
        if st.get("r"):
            break
        pg.wait_for_timeout(100)
    else:
        raise SystemExit("模型加载超时")
    return b, pg


def frame(i):
    from playwright.sync_api import sync_playwright
    os.makedirs(FRAMES, exist_ok=True)
    httpd, port = serve()
    with sync_playwright() as pw:
        b, pg = open_page(pw, port)
        pg.evaluate("(i) => window.__frame(i)", i)
        out = os.path.join(FRAMES, "test_%04d.png" % i)
        pg.screenshot(path=out)
        print("帧:", out)
        b.close()
    httpd.shutdown()


def render():
    from playwright.sync_api import sync_playwright
    plan = json.load(open(os.path.join(SITE, "plan.json")))
    n = int(round(plan["duration"] * FPS))
    os.makedirs(FRAMES, exist_ok=True)
    for f in os.listdir(FRAMES):
        if f.startswith("f_") and f.endswith(".png"):
            os.remove(os.path.join(FRAMES, f))
    httpd, port = serve()
    with sync_playwright() as pw:
        b, pg = open_page(pw, port)
        for i in range(n):
            pg.evaluate("(i) => window.__frame(i)", i)
            pg.screenshot(path=os.path.join(FRAMES, "f_%04d.png" % i))
            if i % 60 == 0:
                print("...%d/%d" % (i, n), flush=True)
        b.close()
    httpd.shutdown()
    print("渲染完成", n, "帧")


def mux():
    plan = json.load(open(os.path.join(SITE, "plan.json")))
    total = float(plan["duration"])
    out = os.path.join(DEBUT, "debut_sample.mp4")
    voice = os.path.join(TTS, "full.wav")
    bgm = os.path.join(DEBUT, "audio", "bgm.wav")

    cmd = [FFMPEG, "-hide_banner", "-y", "-framerate", str(FPS),
           "-i", os.path.join(FRAMES, "f_%04d.png"), "-i", voice]
    if os.path.exists(bgm):
        # 配乐垫在下面：先降音量，再用配音当侧链把它压下去（说话时自动闪避）
        cmd += ["-i", bgm]
        fade_out_at = max(0.0, total - 2.2)
        chain = (
            "[1:a]asplit=2[v1][v2];"
            "[2:a]atrim=0:%.3f,volume=0.30,afade=t=in:st=0:d=1.0,"
            "afade=t=out:st=%.3f:d=2.2[bg];"
            "[bg][v1]sidechaincompress=threshold=0.04:ratio=8:attack=10:release=420[bgd];"
            "[bgd][v2]amix=inputs=2:normalize=0:dropout_transition=0,alimiter=limit=0.95[aout]"
        ) % (total, fade_out_at)
        cmd += ["-filter_complex", chain, "-map", "0:v", "-map", "[aout]"]
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-shortest", "-movflags", "+faststart", out]
    sh(cmd)
    print(out, os.path.getsize(out), "字节", round(dur(out), 2), "秒",
          "（含配乐）" if os.path.exists(bgm) else "（无配乐）")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "assets"
    if cmd == "assets":
        build_assets()
    elif cmd == "frame":
        frame(int(sys.argv[2]) if len(sys.argv) > 2 else 120)
    elif cmd == "render":
        render()
    elif cmd == "mux":
        mux()
    else:
        raise SystemExit("未知子命令: " + cmd)
