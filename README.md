# qingmeng-studio

蝶清梦（Sylvia Muse）的视频制作工具集：把「台词」变成「能投稿的竖屏视频」的那一套。

> 这个仓库只放**我自己写的代码与文档**。模型、Live2D 运行时、参考音频、克隆声线全部不在仓库里，
> 需要使用者自备——原因见文末「不含什么」。

## 这套工具能干什么

| 能力 | 入口 | 说明 |
|---|---|---|
| 台词 → 音轨 + 时间轴 + 口型 | `scripts/debut_v2.py` | 逐句 TTS，算出字幕区间和 30fps 口型包络 |
| 逐帧渲染 Live2D | `scripts/debut_build.py render` | Playwright 驱动网页，确定性逐帧截图 |
| 混音成片 | `scripts/debut_build.py mux` | 人声 + 配乐，侧链闪避 |
| 配乐合成 | `scripts/debut_bgm.py` / `debut_bgm4.py` | 纯 Python，无需音源 |
| 封面 | `scripts/debut_cover.py` | 16:9 与 4:3 两版 |
| 表情包批量 | `scripts/sticker_batch.py` | 出无字图 + PIL 叠字 |
| 出图通用入口 | `scripts/img_gen.py` | 本地 / 云端双后端 |
| 谱曲 + MIDI | `scripts/song_midi.py` | 纯字节写 MIDI，带歌词文本事件 |
| 新作品脚手架 | `scripts/new_video.py` | 按日期建目录、填 meta 模板 |
| 音频体检 | `scripts/voice_analyze.py` | 规格 / 响度 / F0 中位数 |
| 唱歌试验 | `scripts/sing_poc.py` | TTS 逐音节贴音高（结论：不可行，留作教训） |
| MV 流水线 | `scripts/mv_build.py` / `mv_mux.py` | 官方音轨 + 官方 LRC + 人声分离 → 竖屏 MV |

## 目录约定

```
某条视频/
├── README.md      这条做了什么、怎么做、结果如何
├── meta.json      标题/简介/标签/分区/发布状态
├── script.json    段落实体：[表情, 台词, 字幕, 停顿类型, scale, y]
├── video.mp4      成片
└── cover_*.png    封面
```

`new_video.py <短名>` 会按 `YYYYMMDD_序号_短名` 建好这一整套。

## 快速开始

```bash
# 1) 写段落脚本
python3 new_video.py demo --title "【示例】测试"
vim <新目录>/script.json

# 2) 合成音轨 + 时间轴 + 口型
python3 scripts/debut_v2.py --voice <你的音色> --script <新目录>/script.json

# 3) 渲染（需要先按下面「依赖」准备好渲染页面与模型）
python3 scripts/debut_build.py render
python3 scripts/debut_build.py mux
```

## 依赖

- Python 3.10+，`pillow`、`playwright`（`playwright install chromium`）
- `ffmpeg`（带 libass）
- 一个 Live2D Cubism 4 模型（自备，放 `data/debut/site/assets/`）
- 一个 TTS 接口（脚本里默认走本地网关 `127.0.0.1:11091`，改成任意 OpenAI 兼容端点即可）

## 不含什么（重要）

| 内容 | 为什么不在 |
|---|---|
| `live2dcubismcore.min.js` | Live2D 专有运行时，再分发受其许可限制。请自行从 Live2D 官网取得并遵守协议 |
| Live2D 模型文件 | 模型是画师的作品，本仓库无权再分发 |
| 参考音频 / 克隆声线 | 涉及声音的人格权与训练来源授权 |
| 任何商业歌曲音频 | 版权 |

渲染页面 `index.html` 里的库引用保留为占位路径，把它们指向你自备的文件即可。

## 方法论

`docs/制作方法论.md` 记录了九类做法与六个坑，包括：

- 为什么必须 `app.ticker.stop()` 才能确定性逐帧
- 字幕为什么用 `silencedetect` 而不用字数比例
- 中文文字为什么一律 PIL 叠而不让模型写
- Seed-VC 的 `auto_f0_adjust` 为什么会让整条人声降调
- B站分区为什么要看 `tid_v2` 而不是 `tid`

## 许可

代码：MIT（见 `LICENSE`）。
`docs/` 下的文字：CC BY-NC 4.0（署名—非商业性使用）。

## packages/ink-particles

确定性的 WebGL2 粒子系统——同一时刻 `t` 永远渲染同一帧，专为"逐帧抓成 MV"设计。

```bash
cd packages/ink-particles/demo
python3 make-textures.py && python3 -m http.server 8080
```

## demos/ink-glyph-scroll

长卷水墨 MV 渲染器：歌词整句写在一张横卷上、写完保留、卷面推进；粒子累加进 RGBA16F 密度场做"墨"，笔压由骨架的距离变换量出来。

```bash
cd demos/ink-glyph-scroll && python3 -m http.server 8090
```

## docs/视频技法

- `视频技法库.md`：镜头/节奏/转场/构图/调色/声音，每条给可执行参数
- `视频自检清单.md`：发布前 20 条，每条附一条能跑的命令
- `自动化清单.md`：哪些能脚本化、哪些不能（含"自动切点检测为什么不能用"）
- `红昭愿-改造建议.md`：一个真实案例的病灶与改法

配套脚本在 `tools/视频自检/`（响度、字幕越界、景别、影调、相机路径）。
