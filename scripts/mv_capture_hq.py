#!/usr/bin/env python3
"""逐帧抓 MV：把页面变成「可重复渲染的帧机」，抓到无损 PNG，再编码。

和旧脚本（mv_capture.py / mv_record.py）的关键差别：

1. **帧由我们驱动**：把 requestAnimationFrame 换成队列，按固定 1/60s 步进。
   → 每一帧的 dt 恒定，粒子老化/字符墙滚动不会因为「截图慢」而跑飞；
     旧脚本里 rAF 跟着真实时钟跑、截图却要 0.1~0.4s，动画实际比歌快 3~12 倍。
2. **时间钉死**：A.time() 被替换成返回 __T，渲染用的 t 精确等于 i/fps，
   不会因为 seek 之后音频继续走而漂移（旧脚本每帧漂 20~300ms）。
3. **音频能量照旧来自页面自己的 AnalyserNode**：每帧 A.play(t) 让音源停在 t 附近，
   所以 bass/treble 驱动的脉冲与画面同步。
4. **歌词动画按 t 驱动**：CSS 的 .9s 淡入是真实时钟，逐帧抓会拍到半透明；
   这里接管 .en/.zh 的 opacity/transform/blur，用同样的 cubic-bezier 曲线按 t 算。
5. **截图走 CDP Page.captureScreenshot(optimizeForSpeed)**：PNG 无损，
   1920×1080 约 55ms/帧（Playwright 的 png 要 370ms）。
6. 编码：PNG 帧 → x264 crf 12（或 qp 0 无损），音频 -c:a copy 不重编码。

用法：
  # 30 秒试验段
  /usr/bin/python3 scripts/mv_capture_hq.py --pilot
  # 全片
  /usr/bin/python3 scripts/mv_capture_hq.py --all --out .../mv_hq.mp4
  # 换编码参数（不重抓）
  /usr/bin/python3 scripts/mv_capture_hq.py --encode-only --crf 14 --out .../x.mp4
"""
import argparse
import base64
import os
import shutil
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = "/Users/xhqm/Space/qqSpace"
FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
HTML_DIR = os.path.join(ROOT, "data/videos/20261016_00_world-execute-me-mv")
HTML = "world.execute(me)-MV.html"
AUDIO = os.path.join(HTML_DIR, "audio.mp3")
OUT_DIR = os.path.join(ROOT, "data/videos/20261029_04_world-execute-me-mv")

# ---------------------------------------------------------------- 注入的 JS

# 接管 rAF + 钉死时间 + 接管歌词动画
SETUP_JS = r"""
() => {
  // ---- 1. rAF 换成手动队列 ----
  window.__q = [];
  window.__vnow = performance.now();
  window.__err = null;
  window.requestAnimationFrame = function (cb) { window.__q.push(cb); return window.__q.length; };
  window.cancelAnimationFrame = function () {};
  window.__step = function (n, dtMs) {
    for (let i = 0; i < n; i++) {
      window.__vnow += dtMs;
      const q = window.__q; window.__q = [];
      for (let k = 0; k < q.length; k++) {
        try { q[k](window.__vnow); } catch (e) { window.__err = String(e && e.stack || e); }
      }
    }
    return window.__q.length;
  };

  // ---- 2. 渲染时间由外部钉住 ----
  const A = MV.Audio;
  A.pause();
  window.__T = 0;
  A.time = function () { return window.__T; };

  // ---- 3. 歌词：干掉 CSS 动画，改由 t 驱动同样的曲线 ----
  const style = document.createElement('style');
  style.textContent = '#lyr .en,#lyr .zh{animation:none!important}';
  document.head.appendChild(style);

  function bezier(x1, y1, x2, y2) {
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const fx = (s) => ((ax * s + bx) * s + cx) * s;
    const fy = (s) => ((ay * s + by) * s + cy) * s;
    return function (x) {
      if (x <= 0) return 0; if (x >= 1) return 1;
      let lo = 0, hi = 1, s = x;
      for (let i = 0; i < 24; i++) {
        const v = fx(s);
        if (Math.abs(v - x) < 1e-6) break;
        if (v < x) lo = s; else hi = s;
        s = (lo + hi) / 2;
      }
      return fy(s);
    };
  }
  const easeIn = bezier(0.16, 0.8, 0.3, 1);   // lyrIn
  const easeOut = bezier(0.25, 0.1, 0.25, 1); // lyrOut（ease）

  const lyr = document.getElementById('lyr');
  const en = lyr.querySelector('.en'), zh = lyr.querySelector('.zh');
  const cl01 = (v) => v < 0 ? 0 : (v > 1 ? 1 : v);

  window.__lyrSync = function (t) {
    const cue = MV.lyricAt(t);
    if (!cue) {
      en.style.opacity = 0; zh.style.opacity = 0;
      en.style.transform = 'translateY(14px)'; zh.style.transform = 'translateY(10px)';
      en.style.filter = 'blur(6px)'; zh.style.filter = 'blur(4px)';
      return;
    }
    const next = MV.LYR.find((l) => l[0] > cue[0] + 0.01);
    const life = Math.min(2.6, (next ? next[0] : cue[0] + 2.6) - cue[0]);
    const outAt = cue[0] + life;
    const eIn_en = easeIn(cl01((t - cue[0]) / 0.9));
    const eIn_zh = easeIn(cl01((t - cue[0] - 0.08) / 0.9));
    let opEn = eIn_en, opZh = eIn_zh;
    let tyEn = 14 * (1 - eIn_en), tyZh = 10 * (1 - eIn_zh);
    let blEn = 6 * (1 - eIn_en), blZh = 4 * (1 - eIn_zh);
    if (t > outAt) {                              // lyrOut：1 -> 0
      const e = easeOut(cl01((t - outAt) / 0.45));
      opEn = 1 - e; opZh = 1 - e;
      tyEn = -10 * e; tyZh = -10 * e;
      blEn = 7 * e; blZh = 7 * e;
    }
    en.style.opacity = opEn.toFixed(4);
    zh.style.opacity = opZh.toFixed(4);
    en.style.transform = 'translateY(' + tyEn.toFixed(2) + 'px)';
    zh.style.transform = 'translateY(' + tyZh.toFixed(2) + 'px)';
    en.style.filter = 'blur(' + blEn.toFixed(2) + 'px)';
    zh.style.filter = 'blur(' + blZh.toFixed(2) + 'px)';
    en.style.willChange = 'opacity,transform,filter';
  };

  // ---- 4. 清掉「怎么用这个页面」的帮助层与片头卡 ----
  const title = document.getElementById('title'); if (title) title.style.display = 'none';
  const hint = document.getElementById('hint'); if (hint) hint.style.opacity = '0';
  window.__ok = true;
  return { pending: window.__q.length };
}
"""

FRAME_JS = r"""
(a) => {
  window.__T = a.t;
  const A = MV.Audio;
  if (a.play) A.play(a.t);            // 让 AnalyserNode 吃到 t 处的真实能量
  window.__step(2, 1000 / 60);        // 两个 1/60 子步 = 1/30 的动画时间（与 60Hz 实时一致）
  window.__lyrSync(a.t);
  return {
    q: window.__q.length,
    t: MV.state().t,
    bass: A.bass, treble: A.treble,
    w: document.getElementById('gl').width,
    err: window.__err,
  };
}
"""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HTML_DIR, **kw)

    def log_message(self, *a):
        pass


def probe_duration(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def encode(frames_dir, out_path, fps, dur, crf, preset, scale, start_number=0, audio=AUDIO):
    vf = []
    if scale:
        vf.append("scale=%d:%d:flags=lanczos" % scale)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-framerate", str(fps), "-start_number", str(start_number),
           "-i", os.path.join(frames_dir, "f_%05d.png"),
           "-i", audio,
           "-map", "0:v", "-map", "1:a", "-t", "%.3f" % dur]
    if crf == 0:
        cmd += ["-c:v", "libx264", "-preset", preset, "-qp", "0"]
    else:
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest",
            "-movflags", "+faststart", out_path]
    print("编码:", " ".join(cmd), flush=True)
    t0 = time.time()
    subprocess.run(cmd, check=True)
    sz = os.path.getsize(out_path)
    print("成片 %s  %.1f MB  用时 %.1f 分钟" % (out_path, sz / 1e6, (time.time() - t0) / 60), flush=True)
    return sz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--dpr", type=float, default=1.5, help="页面像素比；1.5 = 2880x1620 超采样后降采样")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=0.0, help="0 = 到音频结尾")
    ap.add_argument("--frames-dir", default="/tmp/mv_frames_hq")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "mv_hq.mp4"))
    ap.add_argument("--ref-dir", default="/tmp/mv_ref")
    ap.add_argument("--ref-times", default="30,100,150")
    ap.add_argument("--crf", type=int, default=12)
    ap.add_argument("--preset", default="slow")
    ap.add_argument("--settle-ms", type=float, default=20.0)
    ap.add_argument("--pin-energy", action="store_true",
                    help="把 bass/mid/treble 钉成常数，用于完全确定性的对照实验")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--encode-only", action="store_true")
    ap.add_argument("--keep-frames", action="store_true")
    a = ap.parse_args()

    dur = probe_duration(AUDIO)
    n_total = int(round(dur * a.fps))
    i0 = int(round(a.start * a.fps))
    i1 = n_total if a.end <= 0 else min(n_total, int(round(a.end * a.fps)))
    scale = (1920, 1080) if abs(a.dpr - 1.0) > 1e-6 else None
    print("音频 %.3fs → %d 帧 @%dfps；本次抓 %d..%d（%d 帧）；dpr=%.2f"
          % (dur, n_total, a.fps, i0, i1, i1 - i0, a.dpr), flush=True)

    if not a.encode_only:
        os.makedirs(a.frames_dir, exist_ok=True)
        os.makedirs(a.ref_dir, exist_ok=True)
        ref_times = [float(x) for x in a.ref_times.split(",") if x.strip()]
        ref_idx = {int(round(t * a.fps)): t for t in ref_times}

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]

        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, args=[
                "--use-angle=metal",                      # GPU（swiftshader 只有 3~4fps）
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
                "--force-color-profile=srgb",
            ])
            ctx = b.new_context(viewport={"width": 1920, "height": 1080},
                                device_scale_factor=a.dpr)
            pg = ctx.new_page()
            cdp = ctx.new_cdp_session(pg)
            pg.goto("http://127.0.0.1:%d/%s" % (port, HTML), wait_until="commit", timeout=60000)
            pg.wait_for_function("() => window.MV && window.MV.ready", timeout=60000, polling=100)
            renderer = pg.evaluate("""() => { const c = document.createElement('canvas');
                const gl = c.getContext('webgl');
                const d = gl.getExtension('WEBGL_debug_renderer_info');
                return d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : 'unknown'; }""")
            print("GL renderer:", renderer, flush=True)

            pg.evaluate("""async () => {
                const r = await fetch('/audio.mp3'); const buf = await r.arrayBuffer();
                const f = new File([buf], 'audio.mp3', {type: 'audio/mpeg'});
                const dt = new DataTransfer(); dt.items.add(f);
                window.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
            }""")
            pg.wait_for_function("() => window.MV.Audio.ready", timeout=120000, polling=100)
            print("音频就绪 %.3fs" % pg.evaluate("() => MV.Audio.buffer.duration"), flush=True)
            print("setup:", pg.evaluate(SETUP_JS), flush=True)
            if a.pin_energy:
                print("钉住能量:", pg.evaluate("""() => { const A = MV.Audio;
                    A.tick = function () { A.bass = 1.2; A.mid = 0.5; A.treble = 0.8; A.level = 0.8; };
                    return 'bass=1.2 treble=0.8'; }"""), flush=True)
            print("canvas backing:", pg.evaluate("() => { const c=document.getElementById('gl'); return [c.width,c.height]; }"), flush=True)

            def grab():
                r = cdp.send("Page.captureScreenshot", {"format": "png", "optimizeForSpeed": True})
                return base64.b64decode(r["data"])

            def step(t, play=True):
                return pg.evaluate(FRAME_JS, {"t": t, "play": play})

            # 预跑 30 帧（1 秒动画时间）让着色器/贴图/粒子进入稳态
            for _ in range(30):
                step(0.0, play=False)
            print("预跑后 pending:", pg.evaluate("() => window.__q.length"), flush=True)

            t0 = time.time()
            done = 0
            for i in range(i0, i1):
                p = os.path.join(a.frames_dir, "f_%05d.png" % i)
                if a.resume and os.path.exists(p) and os.path.getsize(p) > 100000:
                    continue
                t = i / a.fps
                st = step(t, play=not a.pin_energy)
                if st["q"] < 1 or st["err"]:
                    raise RuntimeError("帧循环断了: %s" % st)
                if abs(st["t"] - t) > 1e-6:
                    raise RuntimeError("时间没钉住: %.6f vs %.6f" % (st["t"], t))
                if a.settle_ms > 0:
                    time.sleep(a.settle_ms / 1000.0)
                data = grab()
                with open(p, "wb") as fh:
                    fh.write(data)
                if i in ref_idx:
                    shutil.copy(p, os.path.join(a.ref_dir, "ref_t%06.1f.png" % ref_idx[i]))
                done += 1
                if done % 100 == 0:
                    el = time.time() - t0
                    rate = done / el
                    print("... %6d/%d  帧率 %.2f/s  已用 %.1f 分  预计剩余 %.1f 分  bass=%.2f"
                          % (i, i1, rate, el / 60, (i1 - i - 1) / rate / 60, st["bass"]), flush=True)
            print("抓帧完成 %d 帧，用时 %.1f 分钟，backing=%s"
                  % (done, (time.time() - t0) / 60, pg.evaluate("() => { const c=document.getElementById('gl'); return [c.width,c.height]; }")), flush=True)
            ctx.close()
            b.close()
        httpd.shutdown()

    seg_dur = (i1 - i0) / a.fps if a.end > 0 else dur - i0 / a.fps
    encode(a.frames_dir, a.out, a.fps, dur if a.end <= 0 else seg_dur, a.crf, a.preset,
           scale, start_number=i0)
    if not a.keep_frames:
        print("帧留在 %s（要删自己删）" % a.frames_dir)


if __name__ == "__main__":
    main()
