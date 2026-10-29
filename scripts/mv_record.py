#!/usr/bin/env python3
"""用粒子 MV 那个 HTML 直接录一条 MV。

思路：页面是「拖入音频 → 播放 → 粒子与歌词跟着音乐动」的实时程序，
不是逐帧可控的渲染器，所以这里用**实时录制**（Playwright 录视频），录完再把原音轨贴回去。

用法：
  py scripts/mv_record.py [--out 路径] [--html 页面] [--audio 音频]
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = "/Users/xhqm/Space/qqSpace"
FFMPEG = os.path.expanduser("~/bin/ffmpeg")
DEFAULT_HTML_DIR = os.path.join(ROOT, "data/videos/20261016_00_world-execute-me-mv")
DEFAULT_HTML = "world.execute(me)-MV.html"
DEFAULT_AUDIO = os.path.join(ROOT, "data/videos/20261029_04_world-execute-me-mv/audio/world.execute(me)_320k.mp3")
W, H = 1920, 1080          # 横屏：这个 HTML 是为 16:9 设计的
REC_W, REC_H = W, H        # 录制与输出同尺寸（放大录会把内容挤在左上角）


def serve(directory):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=directory, **kw)

        def log_message(self, *a):
            pass
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "data/videos/20261029_04_world-execute-me-mv/mv_html.mp4"))
    ap.add_argument("--html-dir", default=DEFAULT_HTML_DIR)
    ap.add_argument("--html", default=DEFAULT_HTML)
    ap.add_argument("--audio", default=DEFAULT_AUDIO)
    a = ap.parse_args()

    # 音频放进同目录，页面用相对路径取
    local_audio = os.path.join(a.html_dir, "audio.mp3")
    shutil.copy(a.audio, local_audio)
    dur = float(subprocess.run(["/opt/homebrew/bin/ffprobe", "-v", "error", "-show_entries",
                                "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                                a.audio], capture_output=True, text=True).stdout.strip())
    print("音频时长 %.1fs" % dur)

    httpd, port = serve(a.html_dir)
    from playwright.sync_api import sync_playwright
    rec_dir = "/tmp/mv_rec"
    shutil.rmtree(rec_dir, ignore_errors=True)
    os.makedirs(rec_dir, exist_ok=True)

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=[
            "--autoplay-policy=no-user-gesture-required", "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": W, "height": H},
                            record_video_dir=rec_dir,
                            record_video_size={"width": REC_W, "height": REC_H},
                            device_scale_factor=1)
        pg = ctx.new_page()
        pg.goto("http://127.0.0.1:%d/%s" % (port, a.html), wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        # 用 drop 事件喂音频（页面监听 window 的 drop）
        ok = pg.evaluate("""async () => {
            const r = await fetch('/audio.mp3');
            const buf = await r.arrayBuffer();
            const f = new File([buf], 'audio.mp3', {type: 'audio/mpeg'});
            const dt = new DataTransfer(); dt.items.add(f);
            window.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
            return f.size;
        }""")
        print("喂给页面:", ok, "字节")
        pg.wait_for_timeout(2500)
        clicked = pg.evaluate("""() => { const b = document.getElementById('startBtn'); if (b) { b.click(); return true; } return false; }""")
        print("点 START:", clicked)
        pg.wait_for_timeout(int((dur + 3) * 1000))
        video_path = pg.video.path()
        ctx.close()
        b.close()
    httpd.shutdown()
    print("录屏:", video_path)

    subprocess.run([FFMPEG, "-hide_banner", "-y", "-i", video_path, "-i", a.audio,
                    "-t", "%.2f" % dur, "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", a.out],
                   check=True)
    print("成片:", a.out, os.path.getsize(a.out), "字节")


if __name__ == "__main__":
    main()
