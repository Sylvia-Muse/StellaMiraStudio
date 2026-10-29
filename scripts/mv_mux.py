#!/usr/bin/env python3
"""MV 混流：逐帧 PNG + 粒子背景视频（screen 叠加）+ 原曲音轨。

页面只画角色与字幕，背景由这里叠——这样换背景不用重渲 6370 帧。
用法：py scripts/mv_mux.py [输出路径]
"""
import json, os, subprocess, sys

ROOT = "/Users/xhqm/Space/qqSpace"
FFMPEG = os.path.expanduser("~/bin/ffmpeg")
SITE = os.path.join(ROOT, "data/debut/site")
FRAMES = os.path.join(ROOT, "data/debut/frames")
VDIR = os.path.join(ROOT, "data/videos/20261029_04_world-execute-me-mv")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(VDIR, "mv_draft.mp4")
BG_SRC = os.path.join(ROOT, "data/videos/20261016_00_world-execute-me-mv/clips/mv_raw_110s.webm")
BG_MP4 = "/tmp/mv_bg.mp4"
AUDIO = os.path.join(ROOT, "data/debut/tts/full.wav")


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr[-800:])
    return r.stdout


def main():
    plan = json.load(open(os.path.join(SITE, "plan.json")))
    total = float(plan["duration"])
    # 背景：循环到总时长、裁成竖屏、降亮
    if not os.path.exists(BG_MP4):
        sh([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-stream_loop", "-1", "-i", BG_SRC, "-t", "%.2f" % total,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                   "eq=brightness=-0.05:saturation=1.05,gblur=sigma=18,fps=30",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            BG_MP4])
        print("背景预渲染完成:", BG_MP4)
    sh([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-framerate", str(plan["fps"]), "-i", os.path.join(FRAMES, "f_%04d.png"),
        "-i", BG_MP4, "-i", AUDIO,
        "-filter_complex",
        "[0:v]format=rgba[base];"
        "[1:v]format=rgba,colorchannelmixer=aa=0.22[bg];"
        "[base][bg]overlay=0:0,format=yuv420p[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", OUT])
    print("MV:", OUT, os.path.getsize(OUT), "字节")


if __name__ == "__main__":
    main()
