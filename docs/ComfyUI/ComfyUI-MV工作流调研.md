# ComfyUI MV 工作流调研（2026-11 现场版）

> 目标：给「蝶清梦 / Sylvia Muse」的二创 MV 加一条"AI 动起来"的生产线。
> 本文所有"实测"数字都标了来源；标"估算"的没有本机实测，别当承诺。
>
> 勘测时间：2026-11-02 20:50~21:10（本机 macOS + SSH 到 `100.99.5.35`）
> 调研纪律：本轮**只读**。没有下载权重、没有提交生成任务、没有重启服务。

---

## 0. 结论速览（先看这 10 行）

| 你的需求 | 现在该怎么办 | 为什么 |
|---|---|---|
| 一句歌词 → 3~5s 画面 | **Wan2.2 TI2V-5B**（原生节点，无需装任何插件） | 官方口径 8GB 显存可跑；Apache-2.0 可商用；本机节点已具备 |
| 静画 → 动起来 | 同一个 5B 模型 + `start_image`（T2V/I2V 是一体的） | 同上；换一张"定妆帧"就能靠住同一个角色 |
| 首尾帧插值 | **先别做模型版**。用 `ffmpeg minterpolate` 或 RIFE 补间（零显存） | 真正能跑 FLF2V 的是 14B 级，要 ≥20GB 空闲显存；本机常态只剩 3.7GB |
| 1080p30 不抖 | **SeedVR2 3B int8 放大 + RIFE/FILM 补帧**（都是原生节点） | 都是视频/时间一致的；SeedVR2 Apache-2.0、RIFE MIT，许可干净 |
| 水墨/宣纸风格 | **提示词 + 我们自己的 WebGL 后处理**，不要用 img2img 重绘 | 重绘会毁角色一致性，而且触碰"自有美术素材不入模型"的约定 |

**一句话**：这条链路今天就能开工，**最少要下 18.1GB 模型**（5B 那套），**零插件安装**，许可全部干净。
14B 那档画质更好，但必须等 GPU 空出来。

---

## 1. 现场勘测（实测）

### 1.1 硬件与显存实况

```
$ ssh xhqm@100.99.5.35 'nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv'
name, memory.total, memory.used, memory.free
NVIDIA GeForce RTX 3090 Ti, 24564 MiB, 20418 MiB, 3740 MiB
```

- **3090 Ti 24GB（Ampere sm_86）**，驱动 615.71.09。
- 勘测瞬间 **已用 20418 MiB / 剩 3740 MiB** —— 和你们说的"17~18GB 被占"一致，甚至更紧。
- 系统内存 67.3GB（`ram_total`），勘测时空闲 16.5GB —— **这条很关键**：ComfyUI 的 offload 是把权重丢到系统内存，内存不够时 offload 会退化成疯狂换页。
- `/home` 938G，已用 635G，**可用 261G** —— 放 40GB 级模型没问题。

### 1.2 一个必须纠正的前提：**8211 不是 ComfyUI**

任务书写"ComfyUI 服务在本机 8211 端口"。实测：

```
LISTEN 0.0.0.0:8211  users:(("python3",pid=3393105))   → /home/xhqm/Server/imgproxy/serve.py
LISTEN 127.0.0.1:8188 users:(("python",pid=2907072))   → /home/xhqm/Server/ComfyUI      ← 真正的 ComfyUI
LISTEN 127.0.0.1:8190 users:(("python",pid=3288489))   → /home/xhqm/Server/ComfyUI-nightly
```

- `8211` = **OpenAI 风格图片网关**（`imgproxy`），`GET /v1/models` 只回 `sd-cpp-local`；它把请求翻译成 stable-diffusion.cpp 的 `/sdapi/v1/txt2img`。
  所以 `scripts/img_gen.py` 走 `8211` 出 qwen-image 是**图片**通道，**它不能跑视频工作流**。
- **视频要打 `127.0.0.1:8188`**（ComfyUI 原生 API）。
- 注意 `8188/8190` 都只监听 `127.0.0.1`，**macOS 侧不能直连**，必须 `ssh -L 8188:127.0.0.1:8188` 或直接在服务器上跑。

### 1.3 ComfyUI 本体

```
comfyui_version: 0.38.0     python 3.11.18     torch 2.11.0+cu128
comfyui-frontend-package 1.53.6   workflow-templates 0.11.70
节点类型总数：971
```

已装自定义节点（两个实例都很少）：
- `~/Server/ComfyUI/custom_nodes/`: `moss-image`, `mvkit_mvbuild`
- `~/Server/ComfyUI-nightly/custom_nodes/`: 只有示例文件

### 1.4 原生节点盘点（决定"要不要装插件"）

用 `/object_info` 逐类扫描（971 个节点）：

| 家族 | 命中数 | 对我们的意义 |
|---|---|---|
| **Wan** | 44 | ✅ 含 `WanImageToVideo`、**`WanFirstLastFrameToVideo`**（首尾帧！）、`WanVaceToVideo`、`WanCameraImageToVideo`、`WanPhantomSubjectToVideo`、`WanAnimateToVideo`、`WanSoundImageToVideo` |
| **LTXV** | 33 | ✅ 但许可要查（见 §3） |
| **Hunyuan** | 16 | 含 `HunyuanVideo15ImageToVideo`，14B 级，暂时用不上 |
| **SeedVR2** | 5 | ✅ `SeedVR2Preprocess/Conditioning/PostProcessing/TemporalChunk/TemporalMerge` → 视频放大已原生 |
| **帧插值** | 4 | ✅ `FrameInterpolationModelLoader`（源码里认 **RIFE(IFNet)** 和 **FILM(FILMNet)**）+ `FrameInterpolate` |
| SVD | 1 | 只有 `SVD_img2vid_Conditioning`（许可 **非商用**，别碰） |
| Flux / Qwen-Image / ZImage | 多 | 图片线，与本轮无关 |
| **AnimateDiff** | **0** | ❌ 没有节点；生态也已过时 |
| **CogVideoX** | **0** | ❌ 没有节点 |
| **IP-Adapter** | **0** | ❌ 没有节点 → 一致性不能靠它 |
| **GGUF** | **0** | ⚠️ 要用 GGUF 量化必须装 `ComfyUI-GGUF` |

**结论：MVP 一个插件都不用装。** 全部用原生节点。

### 1.5 模型目录现状（决定"要下多少"）

| 目录 | 现有内容 | 对我们 |
|---|---|---|
| `checkpoints/` | `Illustrious-XL-v1.0`(6.5G)、`NoobAI-XL-Vpred-v1.0`(6.7G) | SDXL 系，只能做图 |
| `diffusion_models/` | `acestep_v1.5_turbo`（音频）、`minimax_h3_*`（int8） | 无 Wan |
| `text_encoders/` | qwen3vl 系列、qwen_0.6b/1.7b_ace15 | **无 umt5**（Wan 必需） |
| `vae/` | ace_1.5_vae、minimax、qwen_image_2.1 | **无 wan vae** |
| `loras/` `controlnet/` `clip/` `upscale_models/` `frame_interpolation/` | **全空** | 全要下 |
| 磁盘 | `/home` 剩 261G | 够 |

### 1.6 国内网络可达性（实测，两个方向都测了）

| 目标 | GPU 机 | 本机 macOS |
|---|---|---|
| `huggingface.co` | **code=000（8s 超时，不通）** | **code=000（不通）** |
| `hf-mirror.com` | 200 / 1.32s | 200 / 1.17s |
| `www.modelscope.cn` | 302 / 0.24s | 302 / 0.24s |
| `github.com` | 200 / 0.88s | 200 |

实际**吞吐**（各取 1MB 区间，follow redirect，只测了一次，方向性参考）：

| 源 | 结果 | 折算 |
|---|---|---|
| ModelScope | `206` 1MB / **0.33s** | ≈ 3.2 MB/s |
| hf-mirror（302 跳到 `cas-bridge.xethub.hf.co`） | `206` 1MB / **3.77s** | ≈ 0.28 MB/s |

**⇒ 18GB 从 ModelScope 约 1.5~2 小时；同样的量从 hf-mirror 要 18 小时。**
**所以：大权重走 ModelScope，小文件（<100MB）才用 hf-mirror。**

---

## 2. 按用途分类的方案

> 每条都按你要的四项写：**节点/模型名 · 显存 · 许可证 · 国内下载 · 预期效果 · 失败模式**。
> 显存数字标注 `实测` / `官方口径` / `估算` 三档。

### 2.1 用途一：一句歌词 → 3~6 秒可动画面

#### 方案 A（推荐，MVP）：Wan2.2 TI2V-5B fp16 + 原生节点

| 项 | 值 |
|---|---|
| 节点 | `UNETLoader` + `ModelSamplingSD3(shift=8)` + `CLIPLoader(type=wan)` + `VAELoader` + `Wan22ImageToVideoLatent` + `KSampler`(20步/cfg5/uni_pc/simple) + `VAEDecode` + `CreateVideo(24fps)` + `SaveVideo` |
| 模型 | `wan2.2_ti2v_5B_fp16.safetensors` **10.00 GB**、`umt5_xxl_fp8_e4m3fn_scaled.safetensors` **6.74 GB**、`wan2.2_vae.safetensors` **1.41 GB**（合计 **18.15 GB** 磁盘） |
| 显存 | **官方口径：8GB 可跑**（ComfyUI 官方教程原话 "should fit well on 8GB vram with the ComfyUI native offloading"，comfyui-wiki 同文）。**估算**本机 832×480×97 帧峰值 10~13GB；1280×704×121 帧峰值 13~16GB。⚠️ 但本机常态只剩 3.7GB → 见 §2.1 方案 B |
| 速度 | Wan-AI 官方：**单张消费级卡 5 秒 720p < 9 分钟**（4090 级）。3090 Ti 的 FP16 算力约为 4090 一半 → **估算** 720p/121帧 10~15 分钟；832×480/97帧 3~6 分钟 |
| 许可 | **Apache-2.0，官方明确支持商用**（ComfyUI 文档："Wan2.2 系列基于 Apache 2.0，支持商用"） |
| 国内下载 | ModelScope `Comfy-Org/Wan-2.2`（见 §4.1 精确命令） |
| 预期效果 | 3~5 秒、24fps、720p 级别的连贯镜头；水面波纹、衣摆飘动、镜头推移都能做；中文提示词直接可用（umt5 原生支持中文） |
| 失败模式 | ① 人物特写容易"脸变"（5B 的固有短板）；② 快速横摇/转身易糊；③ 超过 121 帧会明显漂移；④ 分辨率不是 32 倍数会直接报错；⑤ `length` 必须 `4n+1` |

#### 方案 B（显存只有 6~7GB 时的救命版）：同款 GGUF Q4_K_M

| 项 | 值 |
|---|---|
| 节点 | 同上，把 `UNETLoader` 换成 `UnetLoaderGGUF`（**需装 `ComfyUI-GGUF`**） |
| 模型 | `Wan2.2-TI2V-5B-Q4_K_M.gguf` **3.43 GB**（Q8_0 = 5.40GB / Q5_K_M = 3.81GB / Q2_K = 1.85GB） |
| 显存 | **估算 6~7GB** 可跑（权重 3.43GB + 文本编码器按需换入 + 激活） |
| 许可 | 模型 Apache-2.0；`ComfyUI-GGUF` **Apache-2.0**（city96，源码头部声明） |
| 国内下载 | ModelScope `QuantStack/Wan2.2-TI2V-5B-GGUF`（该仓库同时放了 `VAE/Wan2.2_VAE.safetensors`） |
| 代价 | 比 fp16 慢约 10~25%，细节略软；Q4 以下开始丢质感（Q2 别用） |
| 失败模式 | 忘装节点 → `UnetLoaderGGUF` 不存在；fp8 文本编码器与 GGUF 混用没问题，但别把 GGUF 塞进 `UNETLoader`（会报 unknown format） |

#### 方案 C（画质档，需空机）：Wan2.2 I2V-A14B fp8 + lightx2v 4 步 LoRA

| 项 | 值 |
|---|---|
| 模型 | `wan2.2_i2v_high_noise_14B_fp8_scaled` + `low_noise_14B_fp8_scaled`（各 **14.29 GB**）+ `wan2.2_i2v_lightx2v_4steps_lora_v1_{high,low}_noise`（各 1.23GB）+ umt5 fp8 + `wan_2.1_vae` ≈ **37.7 GB 磁盘** |
| 显存 | **实测（RTX 3090 24GB，2026-10-17，aidev.edu.vn）**：ComfyUI 跑 14B fp8 峰值 **21~24GB**；官方 Wan2.2 原生仓库口径是 **A14B 需 ≥80GB 单卡**（3090 上 347s 后 OOM） |
| 速度 | **实测**：640×640 / 20 步 = **992s**；加 4 步 LoRA = **110s**（快 9 倍） |
| 许可 | Apache-2.0（模型）；lightx2v Lightning 系列仓库声明 Apache-2.0（LoRA 权重从上游模型继承限制） |
| 结论 | 本机常态（剩 3.7GB）**跑不了**。必须预约"空机时段"（≥20GB 空闲）。质检用的 hero shot 值得，批量不行 |

**⇒ 2.1 选型：先 A，紧的时候切 B；C 只在深夜空机跑关键镜头。**

---

### 2.2 用途二：图生视频（水波 / 衣摆 / 墨扩散 / 镜头推移）

**和 2.1 是同一个模型** —— Wan2.2 TI2V-5B 是 T2V+I2V 合一，只要给 `Wan22ImageToVideoLatent.start_image` 接一张图。
所以：**不用为 I2V 再下一个模型**，这是本方案最省钱的一点。

| 项 | 值 |
|---|---|
| 节点 | `LoadImage` → `ImageScale`(832×480, lanczos) → `Wan22ImageToVideoLatent.start_image` |
| 现成文件 | `scripts/comfy/wan22_5b_i2v.api.json`（已校验通过） |
| 显存/许可 | 同 2.1 方案 A |
| 预期效果 | 首帧 100% 锁住（VAE 编码直接当条件），动作幅度由提示词控制；"镜头缓慢右移/推近"这类描述有效 |
| 失败模式 | ① 输入图不是 32 的倍数 → 先 `ImageScale`；② 提示词写"剧烈运动"会崩脸；③ 大幅推镜会带出背景伪影（5B 没有真 3D 理解）；④ **输入必须是我们自己拍的/画的原创画面**——见 §6 红线 |

补充手段（原生节点，值得试）：

- `WanCameraImageToVideo` + `camera_conditions`：显式控制运镜（推/拉/横移/旋转），比写提示词稳。
- `WanImageToVideo.ref_pad_image`：官方 tooltip 写的是 *"Fills the padding frames of the image conditioning with this image instead of gray, anchoring identity without pinning frames (SVI-style anti-drift padding)"* —— **这就是 5B 上最便宜的"同一角色不漂"手段**：把同一张定妆图同时喂 `start_image` 和 `ref_pad_image`。

### 2.3 用途三：首尾帧插值（两帧之间做过渡）

**老实说：这一类在我们现在的硬件上是最尴尬的。** 因为能做首尾帧的都是 14B 级。

#### 方案 A（便宜、零显存、今天就能用）：ffmpeg / RIFE 补间

不是生成，是插帧 + 轻微推拉。用于"镜头衔接"其实够用：

```bash
# 两帧之间做 24 帧的平滑过渡（minterpolate 光流，CPU/GPU 都行，不占 ComfyUI 显存）
ffmpeg -loop 1 -i a.png -loop 1 -i b.png -filter_complex \
"[0:v]scale=1920:1080,format=yuv420p[a];[1:v]scale=1920:1080,format=yuv420p[b];\
[a][b]blend=all_expr='A*(1-T/24)+B*(T/24)',minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc[out]" \
-map "[out]" -t 1 -c:v libx264 -crf 16 bridge.mp4
```

- 显存：**0**（不碰 ComfyUI）
- 许可：ffmpeg LGPL/GPL（自用无碍）
- 失败模式：两帧内容差太多时会出现"融脸"；只适合同机位/同角色的衔接

#### 方案 B（真模型，需空机）：Wan2.1 FLF2V-720P 14B fp8 + `WanFirstLastFrameToVideo`

| 项 | 值 |
|---|---|
| 节点 | `UNETLoader` + `ModelSamplingSD3(shift=8)` + **`WanFirstLastFrameToVideo`**（原生！outputs: positive/negative/latent）+ `KSampler` + `VAEDecode` |
| 模型 | `wan2.1_flf2v_720p_14B_fp8_e4m3fn.safetensors` **16.40 GB** + umt5 fp8 6.74 + `wan_2.1_vae` 0.25 |
| 显存 | **估算 18~22GB**（同量级 14B fp8 实测 21~24GB）→ **必须空机** |
| 许可 | Wan2.1 **Apache-2.0** |
| 国内下载 | ModelScope `Comfy-Org/Wan_2.1_ComfyUI_repackaged` |
| 现成文件 | `scripts/comfy/wan2_1_flf2v_720p.api.json`（图结构已校验通过，参数为起点值） |
| 失败模式 | ① 官方训练分布是 **720p/16fps**，硬拉 24fps 会抖；② 首尾差异过大（换场景）→ 中间糊成一团；③ 显存不够时 OOM 发生在 VAE decode 阶段（Wan2.2 issue #90 就是这么挂的） |

#### 方案 C（官方 blueprint 的走法，**不推荐**）

官方 `blueprints/flf2v_wan2_1_vace.json` 用的是 **Wan2.1 VACE 14B fp16 = 34.68 GB**（ModelScope 上这个仓库**没有 14B fp8**，只有 fp16 和 1.3B）。
fp16 34.7GB > 24GB，只能靠极端 offload，速度无法接受。同一仓库有 `wan2.1_vace_1.3B_fp16`（**4.31GB**，Apache-2.0，显存 ~6-8GB 估算）——能跑，但 1.3B 画质只配当**衔接草稿**，不能进成片。

**⇒ 2.3 选型：日常用 A（ffmpeg 光流）；真正的首尾帧镜头攒到空机时段用 B。C 只做草稿验证。**

---

### 2.4 用途四：放大 + 补帧（成片段子 → 1080p30 不抖）

这是**最划算的一块**：两个原生节点家族，显存都很小，许可都干净，可以立刻上。

#### 4a. 放大：SeedVR2 3B int8（推荐）

| 项 | 值 |
|---|---|
| 节点 | `UNETLoader(seedvr2_3b_int8_convrot)` + `VAELoader(seedvr2_ema_vae_fp16)` + `SeedVR2Preprocess` + `VAEEncodeTiled` + `SeedVR2Conditioning` + `KSampler(steps=1, cfg=1, euler, denoise=1)` + `VAEDecodeTiled` + `SeedVR2PostProcessing` |
| 模型 | `seedvr2_3b_int8_convrot.safetensors` **3.46 GB**（fp8 版 3.39GB / fp16 6.78GB）+ `seedvr2_ema_vae_fp16` |
| 显存 | **估算 6~9GB**（512 tile / 64 帧块）；官方把它定位为"低显存版"，且是**一步推理**（steps=1） |
| 许可 | **Apache-2.0（3B/7B 都是）**，可商用 |
| 国内下载 | hf-mirror `Comfy-Org/SeedVR2`（文件小，hf-mirror 够用）；**注意 SeedVR2 必须用它自己的 VAE**，不能用 wan vae |
| 现成文件 | `scripts/comfy/seedvr2_3b_upscale.api.json`（图结构已校验通过） |
| 预期效果 | 因为它是**视频修复模型**（时间一致），放大后不闪；比逐帧 ESRGAN 强一个档 |
| 失败模式 | ① 用错 VAE → 颜色全崩；② tile 太小 + overlap 太小 → 接缝；③ 一次塞 300 帧会爆内存 → 用 `SeedVR2TemporalChunk` 分块 |

7B 版更强但 `seedvr2_7b_fp8_e4m3fn` 8.24GB（nvfp4 4.76GB），显存要 12GB+ → 空机再说。

#### 4b. 轻量放大：RealESRGAN x4plus（便宜但不能单独用）

| 项 | 值 |
|---|---|
| 节点 | `UpscaleModelLoader` + `ImageUpscaleWithModel`（官方 blueprint `video_upscale_gan_x4.json` 就这一个模型） |
| 模型 | `RealESRGAN_x4plus.safetensors` ~64MB |
| 显存 | **< 2GB**，极快 |
| 许可 | **BSD-3-Clause**（xinntao/Real-ESRGAN），可商用 |
| 失败模式 | **逐帧处理、无时间一致 → 会闪**。只能当"先放大再让 SeedVR2 收一遍"的粗加工，或用于静态图 |

⚠️ 别用 `4x-UltraSharp` 之类社区放大模型：效果好但**许可来源不明**，商用有风险。

#### 4c. 补帧：RIFE / FILM（原生 `FrameInterpolate`）

| 项 | 值 |
|---|---|
| 节点 | `FrameInterpolationModelLoader` + `FrameInterpolate(multiplier=2)`；源码里认 **RIFE(IFNet)** 与 **FILM(FILMNet)** 两种权重 |
| 模型 | `frame_interpolation/film_net_fp16.safetensors`；或 `rife_v4.25/rife_v4.26`（含 `_lite` / `_heavy` 变体） |
| 显存 | **< 1.5GB**（模型本体几十 MB + 单对帧激活） |
| 许可 | **RIFE = MIT**（hzwer/Practical-RIFE，已核实 GitHub license=MIT）；**FILM = Apache-2.0**（google-research/frame-interpolation）。Comfy-Org 转存仓 `Comfy-Org/Frame-Interpolation` 的 license 字段标 `other` → **商用前建议再核一次**，但上游是干净的 |
| 国内下载 | hf-mirror `Comfy-Org/Frame-Interpolation`（单个文件几十 MB） |
| 现成文件 | `scripts/comfy/frame_interp_film.api.json`（图结构已校验通过） |
| 用法 | 16fps→32fps（multiplier=2）或 24fps→48fps；**先补帧后放大**更省显存，**先放大后补帧**细节更好（1080p 两遍都试一次，选你喜欢的） |
| 失败模式 | ① 快速运动 + 大位移 → 果冻/鬼影；② 帧数不是奇数时末帧处理；③ `multiplier` 上限 16，别贪 |

**⇒ 2.4 标准流水线：`Wan(480p/720p 16~24fps)` → `RIFE ×2` → `SeedVR2 3B → 1080p` → `ffmpeg 压 H.264`。全链路许可：Apache-2.0 + MIT + Apache-2.0。**

---

### 2.5 用途五（可选）：风格化（水墨 / 宣纸）

**老实说：这一类我建议"不要用扩散模型做"。** 三个理由：

1. **会毁一致性**：img2img 重绘 = 每帧重新解释画面，人物/线条必飘，MV 里会露馅。
2. **触碰内部约定**：把自有美术素材投进绘图模型再生成，正是你们明令禁止的那条。
3. **我们已经有更好的工具**：MV 现在就是 WebGL 粒子/水墨程序渲染 —— 那是**真正的确定性水墨**，比模型稳定一万倍。

可行的三条替代路（按推荐度）：

| 做法 | 显存 | 许可 | 说明 |
|---|---|---|---|
| ① **提示词层面**写风格（"水墨风格 / 宣纸质感 / 墨色扩散 / 留白构图"） | 0 额外 | — | 最安全：风格只影响生成的画面，不重绘我们的素材。umt5 对中文风格词响应不错 |
| ② **渲染后处理**：ffmpeg 滤镜（纸纹 overlay + `bilateral`/`guided` 保边 + 轻微去饱和/暖偏）+ 现有 WebGL 墨扩散 shader 叠一层 | 0 | ffmpeg LGPL | 完全确定性、可批量、可复现 |
| ③ SeedVR2 提细节后再叠 GLSL 墨扩散 | 6~9GB | Apache-2.0 | 想更"贵气"时用 |

**明确不做**：SDXL img2img 风格迁移（Illustrious/NoobAI 那条路）。除了毁一致性，Illustrious 走的是 `sdxl-license`、NoobAI 走 **Fair AI Public License 1.0-SD**，商用条款都要单独核，不值得为它冒险。

---

## 3. 对比表

| 方案 | 磁盘 | 显存（标注） | 速度 | 许可 | 角色一致性 | **现在能跑？** |
|---|---|---|---|---|---|---|
| **Wan2.2 TI2V-5B fp16** | 18.1 GB | 官方 8GB；估算 10~16GB | 5s/720p <9min(4090)；3090Ti 估 10~15min | **Apache-2.0 ✅** | 段内强（锁首帧）/段间靠定妆帧 | ⚠️ 要等下 18GB；显存得等空出 ~12GB |
| **Wan2.2 TI2V-5B GGUF Q4_K_M** | 11.6 GB | 估算 6~7GB | 比 fp16 慢 10~25% | Apache-2.0 + GGUF节点 Apache-2.0 ✅ | 同上 | ✅ **最接近"现在就能跑"** |
| Wan2.2 I2V-A14B fp8 + 4步LoRA | 37.7 GB | **实测 21~24GB** | **实测** 110s/640×640(4步)、992s(20步) | Apache-2.0 ✅ | 强（首帧 + 双专家） | ❌ 需 ≥20GB 空闲 |
| Wan2.1 FLF2V 14B fp8 | 23.4 GB | 估算 18~22GB | 估 6~12min/81帧 | Apache-2.0 ✅ | 很强（首尾双锁） | ❌ 需空机 |
| Wan2.1 VACE 14B fp16 | 41.7 GB | 34.7GB 权重，>24GB | 很慢 | Apache-2.0 ✅ | 强 | ❌ 不推荐 |
| Wan2.1 VACE 1.3B fp16 | 5.3 GB | 估算 6~8GB | 中 | Apache-2.0 ✅ | 弱（只够草稿） | ✅ 但画质不够成片 |
| **SeedVR2 3B int8** | 3.5 GB | 估算 6~9GB | 一步推理 | **Apache-2.0 ✅** | 时间一致（不闪） | ✅ 下 3.5GB 即可 |
| RealESRGAN x4plus | 64 MB | <2GB | 极快 | BSD-3 ✅ | 逐帧，会闪 | ✅ 立刻 |
| **RIFE / FILM 补帧** | 20~50 MB | <1.5GB | 极快 | MIT / Apache-2.0 ✅ | 时间一致 | ✅ 立刻 |
| LTX-Video 0.9.8 13B distilled | ~13 GB | 16~24GB | 很快 | **自定义 LTXV 许可 ⚠️ 不可默认可商用** | 中 | ⚠️ 许可坑，暂不碰 |
| SVD (img2vid-xt) | 9.5 GB | 10~16GB | 中 | **Stable Video Diffusion Community = 非商用 ❌** | — | ❌ 别碰 |
| AnimateDiff | — | 8~12GB | 中 | 生态权重许可混杂 ❌ | 靠 LoRA | ❌ 本机无节点，生态已过时 |
| CogVideoX-5B | — | 大 | 慢 | 自定义 CogVideoX 许可 ⚠️ | 中 | ❌ 无节点、已落后 |

图例：✅ 可商用且许可清楚 / ⚠️ 有条件或需自查 / ❌ 不能商用或不可用

---

## 4. 角色一致性：老实结论

这是**最容易自欺欺人**的一块，我把话说明白。

### 4.1 真能保持一致的做法（按"真·可靠"排序）

| 做法 | 真一致？ | 成本 | 适用 |
|---|---|---|---|
| **① 同一张"定妆帧"作 I2V 首帧 + 同模型 + 同 seed** | ✅ **真一致**（首帧被 VAE 编码硬锁） | 0（就是 Wan5B I2V） | 我们现在的正解 |
| ② 同上 + `ref_pad_image` 也喂同一张 | ✅ 真一致，且抗漂移（官方 tooltip 明写 "anchoring identity"） | 0 | 强烈建议一起用 |
| ③ Wan2.2 **Phantom**（`WanPhantomSubjectToVideo`）/ Animate 14B | ✅ 真一致（主体条件） | 14B 起，int8 18.4GB | 空机时 |
| ④ 训练角色 LoRA | ✅ 真一致 | Wan 视频 LoRA 训练 ≫24GB；SDXL LoRA 24GB 可训 | **被内部约定挡住**，见 4.3 |
| ⑤ 提示词描述角色（"白发绿瞳猫耳少女"） | ❌ **只是看起来差不多** | 0 | 只能当兜底 |
| ⑥ IP-Adapter / InstantID / PuLID | ❌ 本机**没有节点**；Wan 视频 DiT 也没有成熟实现 | — | 别指望 |
| ⑦ 换 seed 反复抽卡 | ❌ 抽到的是"不同的人" | 时间 | 别这么干 |

### 4.2 关键认知：**"跨镜头同一个人"和"同一个人换个动作"是两件事**

- Wan2.2 5B **没有**参考图身份条件（只有首帧条件）。所以：
  - **同一镜头内**：首帧是谁，这段就一直是这个人 → 稳。
  - **换镜头/换角度**：模型不知道"上一个是同一个人" → 必然飘。
- 因此 MV 层面的正确工序是：**先做一张/一组定妆帧（我们自己的美术产出），每个镜头都从对应的定妆帧出发**，镜头之间的"变化"由运镜提示词 + 场景提示词承担，而不是指望模型记住角色。
- 这条路还有一个额外好处：**它天然符合"不把自有素材投进生成模型"的约定** —— 定妆帧是**输入的运动起点**，不是被重绘的对象。

### 4.3 一条必须挑明的规矩冲突

内部约定：**自有美术素材不可投进绘图模型再生成**。

| 操作 | 是否触碰约定 | 我的判断 |
|---|---|---|
| 自有画作 → I2V 让它动起来 | ⚠️ **边界地带**。任务书说 I2V 输入必须是"我们自己拍的/画的原创画面"，但约定又说自有素材不入模型。**I2V 不重绘原图（首帧被硬锁），我倾向"可以做"，但这需要你们拍板** | **需要你确认** |
| 自有画作 → img2img / 风格迁移 / 局部重绘 | ❌ **明确触碰** | 不做 |
| 自有画作 → 训练 LoRA（含 `TrainLoraNode`） | ❌ **明确触碰**（把素材喂进模型学特征） | 不做 |
| 他人作品（动画截图/画师图） → I2V | ❌ 版权 + 约定双违规 | 绝对不做 |

**⇒ 建议：把"定妆帧"定义为"我们自己用程序（Live2D/WebGL/现有素材拼合）产出的原创画面"，用它当 I2V 首帧；不做任何 img2img/LoRA 训练。这样两条规矩都不破。**

---

## 5. 我们现阶段的短板 & 不该碰的东西

### 5.1 短板（按痛感排序）

1. **显存被人占着**：24GB 常态只剩 **3.7GB**。
   - 后果：14B 全系、SeedVR2 7B、LTX-13B 全部不可用；5B fp16 也要挑时间。
   - 唯一随时可跑：GGUF Q4（6~7GB）、RIFE 补帧（<1.5GB）、RealESRGAN（<2GB）。
2. **本机一个相关模型都没有**：无 umt5、无 wan vae、无 wan 主模型、`loras/controlnet/clip/upscale_models/frame_interpolation` 全空。
   - 后果：**第一次跑必须先下 11.6~18.1GB**（ModelScope 约 1~2 小时）。
3. **下载带宽偏科**：ModelScope ≈3.2MB/s 可用，hf-mirror ≈0.28MB/s（40GB 级等于不可用）。
   - 后果：优先 ModelScope；大文件别走 hf-mirror。
4. **ComfyUI 只听 127.0.0.1**，且 8211 是 sd.cpp 图片网关而不是 ComfyUI。
   - 后果：macOS 侧调视频必须 `ssh -L 8188:127.0.0.1:8188`（或者脚本丢到服务器上跑）。
5. **没有插件生态**：无 IP-Adapter、无 GGUF 节点、无 AnimateDiff、无 RIFE 专用插件。
   - 后果：一致性只能靠首帧；GGUF 想用得先装一个插件。
6. **ComfyUI 本体是 GPL-3.0**（这不是错，但要知道）：内部自用出片没问题；如果将来把"含 ComfyUI 的服务"对外分发，GPL 义务会传导。
7. **5B 的上限**：脸/手在特写下会崩，快速运动糊。这是模型规模决定的，不是参数能救的。

### 5.2 不该碰的东西（明确清单）

| 别碰 | 原因 |
|---|---|
| **SVD（Stable Video Diffusion）** | 许可 = `stable-video-diffusion-community`（**研究/非商用**）→ 我们的 MV 是要变现/长期运营的，直接违规 |
| **AnimateDiff 老生态** | 本机 0 个原生节点；权重多为 community/NC 混杂；画质被 Wan2.2 全面超越；**2026 年已经没有推荐理由** |
| **CogVideoX** | 本机无节点；许可为自定义 CogVideoX 条款；生态已落后两代 |
| **任何"整合包"/网盘打包权重** | 来源不可追溯、许可无法核、常夹带改过的节点 → 出片的风险归我们 |
| **4x-UltraSharp 等社区放大模型** | 效果诱人但**许可不明**；用 RealESRGAN(BSD-3) 或 SeedVR2(Apache-2.0) 替代 |
| **他人作品/动画截图做 I2V 输入** | 版权 + 内部约定双违规 |
| **SDXL img2img 做风格化** | 毁一致性 + 触碰"自有素材不入模型" |
| **用 8211 的 `/v1/images/generations` 调视频** | 那个网关是 stable-diffusion.cpp，只出图；视频必须打 8188 |
| **LTX-Video 商用** | `LTXV Open Weights License` 是自定义许可，条款未核前不要用于商用内容 |

---

## 6. 证据与出处

**官方文档 / 仓库（许可与参数依据）**
- ComfyUI Wan2.2 官方教程（含"5B 在 8GB 显存可跑"、Apache-2.0 支持商用）：https://docs.comfy.org/tutorials/video/wan/wan2_2
- ComfyUI SeedVR2 官方教程（3B/7B 均 Apache-2.0、文件放置路径）：https://docs.comfy.org/zh/tutorials/utility/seedvr2
- ComfyUI 帧插值官方教程（FILM / RIFE）：https://docs.comfy.org/tutorials/utility/frame-interpolation
- Wan2.2 主仓（A14B 需 ≥80GB 单卡、5B<9 分钟 720p）：https://github.com/Wan-Video/Wan2.2
- Wan2.2 TI2V-5B 模型卡：https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B
- Wan 2.2 on RTX 3090 实测（14B fp8 峰值 21~24GB；992s/110s）：https://aidev.edu.vn/blog/wan-2-2-vram-gpu
- Wan2.2 5B on RTX 3090 Ti 配方（含 issue #90 的 24GB VAE-decode OOM）：https://smeltcore.com/recipes/wan-2-2-ti2v-5b-on-rtx-3090-ti-720p-text-image-to-video-in-comfyui/
- Wan2.2 issue #90（3090 24GB CLI 在 VAE decode OOM）：https://github.com/Wan-Video/Wan2.2/issues/90
- ComfyUI-GGUF（city96，Apache-2.0）：https://github.com/city96/ComfyUI-GGUF
- Practical-RIFE（MIT）：https://github.com/hzwer/Practical-RIFE
- Real-ESRGAN（BSD-3）：https://github.com/xinntao/Real-ESRGAN
- 官方工作流/blueprint 源（本目录 `_official/` 即来自这里）：https://github.com/Comfy-Org/workflow_templates

**本机实测记录（可复现）**
- `nvidia-smi` / `system_stats` / `ss -ltnp` / `object_info` 的输出见 §1（命令在《落地清单》§1 可原样重跑）。
- 工作流图结构校验：`scripts/comfy/validate_workflow.py` → **5/5 通过**（详见《落地清单》§5）。

**许可证核实（API 直查 cardData，2026-11-02）**

| 模型 | license 字段 | 商用 |
|---|---|---|
| `Wan-AI/Wan2.2-TI2V-5B` | `apache-2.0` | ✅ |
| `ByteDance-Seed/SeedVR2-3B` | `apache-2.0` | ✅ |
| `Laxhar/noobai-XL-1.0` | `other` / `fair-ai-public-license-1.0-sd` | ⚠️ 有条件 |
| `OnomaAIResearch/Illustrious-XL-v1.0` | `other` / `sdxl-license` | ⚠️ 需核 |
| `stabilityai/stable-video-diffusion-img2vid-xt` | `other` / `stable-video-diffusion-community` | ❌ 非商用 |
| `Lightricks/LTX-Video-0.9.8-13B-distilled` | `other`（LTXV 自定义） | ⚠️ 需核 |
| `THUDM/CogVideoX-5b` | `other`（自定义） | ⚠️ 需核 |
