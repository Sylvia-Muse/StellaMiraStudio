# particle-mv · 把一首歌变成粒子 MV

一套工具，配合 `demos/particle-mv.html`（单文件粒子 MV 播放器）使用：
**LRC → 歌词时间轴 → 逐帧抓取 → 成片**。

## 它解决什么问题

用网页做 MV 很自由，但**"逐帧抓成视频"这件事坑很多**，而且坑都不报错：

| 坑 | 后果 | 本工具怎么处理 |
|---|---|---|
| 页面 rAF 跟真实时钟跑 | 截图慢时动画快好几倍，且每次不同 | 接管 rAF，`dt` 固定 1/60，每输出帧 2 子步 |
| seek 之后音频还在播 | 每帧画面漂 20~300ms | 把 `A.time()` 钉死为 `i/fps`，逐帧断言 |
| CSS 淡入用真实时钟 | 逐帧抓必然拍到半透明发虚 | 接管 opacity/blur，按 `t` 自己算 |
| 截图用 JPEG | 单帧就掉到 29dB，后面编码救不回 | 用 CDP 的 PNG 截图（40~55ms/帧，比 Playwright png 快 7 倍） |
| 页面自带掉帧降档 | 帧率低时自动降 pixelRatio，画面变糊 | 固定 dt 让页面以为跑 60fps，全程断言 canvas 尺寸 |

## 用法

```bash
# 1) 预览页（浏览器打开，拖一首歌进去）
open demos/particle-mv.html

# 2) 抓帧 + 编码（需要 playwright）
python3 tools/particle-mv/capture.py \
  --html index.html --audio song.mp3 --out out.mp4 --crf 12

# 3) 量锐度（可选）
python3 tools/particle-mv/metrics.py out.mp4 --times 30,100,150
```

## 歌词怎么进去

页面里的 `MV.LYR = [[秒, 原文, 译文], ...]` 就是时间轴。
最省事的来源是**官方 LRC**（别用 ASR，英文专有名词容易错）：

```
[00:07.446]Fill in my data parameters
```

一条 LRC 对应一条数组；短句可以合并，但**时间要取第一句的**。

⚠️ 如果页面自带的词表和你手上的音轨对不上，**不要平移**：
取几个锚点算差值，差值不是常数就说明词表是按别的版本标的，必须整表替换。

## 许可

代码 MIT。页面里的模型/配色/分镜是示例，换成你自己的就行。
**音频与歌词版权归原作者**——本仓库不含任何音频，演示里的歌词已替换为占位符。
