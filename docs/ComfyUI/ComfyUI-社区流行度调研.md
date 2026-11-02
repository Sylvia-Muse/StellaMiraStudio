# ComfyUI 社区流行度调研（2026-11 · 到底大家在用什么）

> 这篇回答的是「**网上流行什么**」——真实做 MV/动画的人现在在用什么工作流。
> 上一份《ComfyUI-MV工作流调研.md》回答的是「我们机器能跑什么」，那是另一个问题，结论仍有参考价值。
>
> **取证方式**（本轮全部只读）：GitHub REST API 取 star/最后提交、Civitai 公开 API 取工作流下载量、
> B站搜索取播放量与标题、官方文档与第三方评测交叉比对。
> **没下权重、没装节点、没占显存、没重启服务**；未碰 `data/videos/`、`manifest.json`、`song.m4a`。
>
> 标注规则：`[实测数]` = 我这次直接 API 取到；`[未验证]` = 查不到硬证据，只写"传闻/未确认"。
>
> **指标口径（别过度解读）**：Civitai 的 `downloadCount` 是**累计下载次数**（含重复下载/更新版本），不是独立用户数；
> 它衡量"这东西被多少人拿去试过"，不等于"多少人在长期用"。GitHub `star` 同理。
> 所以本文用"多指标同向"来判断趋势（star + 下载量 + B站播放 + 官方模板收录），单一数字不下结论。

---

## 0. 三句话结论

1. **视频的主力仍是 Wan 2.x**（Wan2.2 18,319★、Wan2.1 17,359★），但**上升最快的是 LTX-2.3**（10 个月破万★、12GB 卡就能跑、原生带音频）。
2. **中文圈 2026 最热的是 MiniMax H3 + "AI 漫剧"**，而且**许可证是自定义的 H3 Community License（不是 Apache）**——这是商用红线。
3. **MV 不是"一个工作流出成片"**。社区做得好的 MV 全是：**分镜 + 节拍对齐 → 每句歌词一个 I2V 镜头 → 超分 → 代码合成（Remotion/ffmpeg）**。
   一体化 AIO 工作流（8 万下载那种）是"单镜头工厂"，不是 MV 流水线。

---

## 1. 事实标准总表

| 类别 | 2026 的事实标准 | 流行度证据 `[实测数]` | 趋势 |
|---|---|---|---|
| **文生 / 图生视频（主力）** | **Wan 2.2**（14B A14B / 5B TI2V）+ GGUF 量化 | Wan2.2 仓 **18,319★**（最后提交 2026-09-21）；Wan2.1 **17,359★**；Civitai：`【WAN2.1】IMG to VIDEO` **106,140 dl** / `WAN 2.2 Workflow T2V-I2V-T2I (Kijai Wrapper)` **66,086 dl** / `WAN 2.2 AIO` **83,596 dl** | 稳（仍在头部） |
| **快速 / 低显存视频** | **LTX-2.3（22B）+ GGUF** | `Lightricks/LTX-2` 仓 **10,032★**（2026-01 建仓）；Civitai：`LTX-2.3 All-In-One for RTX 3060 12GB` **31,827 dl**、`LTX-2 19B GGUF 12GB` **21,254 dl**、`LTX-2.3 22B GGUF 12GB` **20,716 dl**。评测口径：**8GB(GGUF) 即可跑、唯一原生带音频、最快** | **↑ 上升最快** |
| **新晋热点（中文圈尤其）** | **MiniMax H3** | ComfyUI 官方 Day-0 支持（2026-08 起）；Civitai：`Minimax H3 SEED HUNTER` **38,196 dl**、`H3 T2V/I2V/REF2V Advanced` **24,616 dl**；B站搜"ComfyUI 工作流 教程"前 20 条里 **6 条**标题/标签含 `MiniMaxH3`、`秋叶整合包`；专门资料仓 `iSk2y/awesome-minimax-h3` | **↑ 上升** |
| **首尾帧** | **不是独立品类**，是 I2V 工作流里的一个能力（社区叫 `FLF2V` / `F2LF` / `SVI keyframes`） | 专门的 FLF2V 工作流下载**很低**：1,015 / 1,242 / 1,300 / 1,413 / 1,577 / 1,640 dl；但只要把 FLF2V 写进标题的"全家桶"就高：`DaSiWa Wan2.2 / I2V / SVI 2.0 / FLF2V` **48,463 dl** | 功能级，非品类 |
| **长视频 / 多段衔接** | **SVI（Stable Video Infinity）系 + continuation / extend** | `vita-epfl/Stable-Video-Infinity` **2,617★**（最后提交 2026-09-17）；Civitai：`Wan 2.2 14b Long video Workflow (30s)` **18,765 dl**、`WAN 2.2 i2v workflow for LONG videos` **15,383 dl**、`Minimax H3 SEED HUNTER - Seamless Video Continuation` **38,196 dl**、`SVI extend video` 3,431 dl、`Smooth SVI Pro` 4,606 dl | **↑ 明显上升（MV 的命门）** |
| **放大** | **SeedVR2**（一步 4X、视频时间一致） | `numz/ComfyUI-SeedVR2_VideoUpscaler` **2,960★**；ComfyUI 已**原生内置**；Civitai `SeedVR2: one-step 4X video/image upscale` **5,822 dl** | 稳定，工具级 |
| **补帧** | ComfyUI **原生** FILM/RIFE 节点（插件时代结束） | `Fannovel16/ComfyUI-Frame-Interpolation` **1,092★**（最后提交 2026-03-29，之后基本静止）；Civitai 补帧类工作流 dl 仅 **181 ~ 1,814** | **↓ 被内置吸收** |
| **角色一致** | **训 LoRA**（主力）+ 参考图/多角度图；音频驱动用 **InfiniteTalk** | `MeiGen-AI/InfiniteTalk` **8,243★**（2025-08 建）；`seitanism/ComfyUI-H3-Motion-Context-MultiRef` **281★**；`cubiq/ComfyUI_IPAdapter_plus` **6,169★** 但**最后提交 2025-04-14（停更 1 年半）**；Civitai `SDXL LoRA trainer` **8,844 dl**；一致性专项工作流都很小（803 / 576 / 94 dl） | 稳态（LoRA 仍是主流，IPAdapter 停滞） |
| **风格化** | 换 **checkpoint / LoRA**（Illustrious、NoobAI、Z-Image、Krea 2），不是"工作流问题" | Civitai：`Z-Image Base & Turbo Pro Grade` **35,874 dl**、`Krea2 ...` **42,814 dl**、`Moody Zimage` 49,056 dl | 稳态 |
| ❌ **已过气 / 正在退场** | **AnimateDiff、SVD、HunyuanVideo 1.5** | AnimateDiff-Evolved **3,564★**、**代码仍在维护**（2026-07 还发了 v1.6.0 + v3 节点 API 重构），但**社区产出停滞**：Civitai 上 AnimateDiff 工作流全是 **2023~2024 版本**（`ipiv's Morph` 34,504 dl，版本仍写 `v3.0 Hyper-SD`）→ 结论是**生态被淘汰，不是代码死了**；HunyuanVideo **12,710★** 但 2026 横评结论是 *"no longer leads any category"*；**SVD 在 ComfyUI 里只剩一个 conditioning 节点**，官方仓 2024 年后无动作 | **↓ 淘汰中** |

**许可证**（照样要标，这是商用红线）：

| 模型 | 许可 | 能商用？ |
|---|---|---|
| Wan 2.1 / Wan 2.2（含 5B、14B、VACE、Animate） | **Apache-2.0** | ✅ |
| SeedVR2（3B/7B） | **Apache-2.0** | ✅ |
| ComfyUI 本体 | **GPL-3.0** | 自用出片 ✅；对外分发含 ComfyUI 的服务要注意传染 |
| ComfyUI-GGUF（city96） | **Apache-2.0** | ✅ |
| RIFE | **MIT** | ✅ |
| **LTX-2 / LTX-2.3** | **LTX-2 Community License**（自定义，含营收门槛/需向 ltx.io 申请授权的条款；有第三方文章称"commercial use permitted"，与 license 文本的 §2 商业条款**不一致**） | ⚠️ **必须逐条读，别默认能商用** |
| **MiniMax H3** | **H3 Community License**（官方明示：open weights，**但不是 OSI 开源**；Context-IR 与 2K 重生成部分**未发布**） | ⚠️ 有条件，需读 LICENSE + QA |
| HunyuanVideo 1.5 | Tencent Community License（受限） | ⚠️ |
| **SVI（Stable-Video-Infinity）** | 研究项目（EPFL VITA），仓库有 license 文件但条款未核 | **未验证** |
| InfiniteTalk | 未核 | **未验证** |
| 社区 checkpoint（Illustrious / NoobAI / Krea2 等） | sdxl-license / Fair-AI-Public-License-1.0-SD / 各自条款 | ⚠️ 逐个查 |

---

## 2. 热门仓库与模板（能拖进 ComfyUI 的）

| 名字 | 链接 | 热度 `[实测数]` | 解决什么问题 | 能直接拖进 ComfyUI？ |
|---|---|---|---|---|
| **Comfy-Org/ComfyUI** | github.com/Comfy-Org/ComfyUI | **144,591★**（最后提交 2026-11-02） | 本体 | — |
| **Comfy-Org/ComfyUI-Manager** | github.com/Comfy-Org/ComfyUI-Manager | **16,694★** | 装节点 | — |
| **Comfy-Org/workflow_templates** | github.com/Comfy-Org/workflow_templates | **1,405★** | **官方模板库：751 个模板 JSON（411 本地 + 340 云 API）+ 117 个 blueprint**（git tree API 实测） | ✅ 模板可在 GUI 里直接 Open；blueprint 是"子图"格式（需较新版本） |
| **kijai/ComfyUI-WanVideoWrapper** | github.com/kijai/ComfyUI-WanVideoWrapper | **6,802★**（最后提交 **2026-05-24**） | Wan 的高级封装（比原生多控制项），大量 Civitai 工作流依赖它 | ✅ 但**要先装插件**；⚠️ 半年未更新，注意与原生节点的重复 |
| city96/ComfyUI-GGUF | github.com/city96/ComfyUI-GGUF | **4,221★** | GGUF 量化加载（低显存必需品） | ✅ 装插件后可用 |
| **Civitai `WAN 2.2 AIO`** | civitai.red/models/1824027 | **83,596 dl / 1,987👍 / 21 个版本**（最新 2026-02-21） | 一个工作流里塞 T2V+I2V+S2V+T2I+MMAudio+4~6 步加速+循环+SVI 延展 | ✅ 下载 .json 拖进去（**注意：它依赖 WanVideoWrapper 等插件**） |
| **Civitai `WAN 2.2 Workflow T2V-I2V-T2I (Kijai Wrapper)`** | civitai.red/models/1818841 | **66,086 dl / 2,175👍 / 361 评论**（2025-07-28） | Wan2.2 三合一起步包，最常被当"标配"引用 | ✅ 同上依赖插件 |
| **Civitai `DaSiWa Wan2.2 / I2V / SVI 2.0 / FLF2V`** | civitai.red/models/1823089 | **48,463 dl** | I2V + 首尾帧 + 长视频延展合体 | ✅ |
| **Civitai `Minimax H3 SEED HUNTER`** | civitai.red/models/2881362 | **38,196 dl** | H3 + 潜空间放大 + **无缝视频续接** | ✅ 但要 MiniMax H3 权重 |
| **Civitai `LTX-2.3 All-In-One for RTX 3060 12GB`** | civitai.red/models/2354193 | **31,827 dl** | 12GB 卡上跑 LTX-2.3（低显存 AIO 的代表） | ✅ |
| **Civitai `Wan2.1(GGUF) only 4GB-VRAM`** | civitai.red/models/1309674 | **29,752 dl** | **4GB 显存**跑 Wan2.1 图生视频 | ✅（这条是我们"3.7GB"最接近的同类） |
| **`Inanis404/ai-mv-pipeline`** | github.com/Inanis404/ai-mv-pipeline | **22★**（2026-10-20 建） | **整条 MV 管线**：一首歌 → 节拍/段落分析 → 歌词对齐 → 分镜 → 角色一致关键帧 → **MiniMax H3 I2V（ComfyUI）** → 超分 → 代码合成（歌词排版+后期） | ⚠️ 它是"skill/脚本管线"，不是单个工作流 JSON；但有 B站配套讲解 |
| `mohammednabarawy/ComfyUI-MiniMax-H3-Music-Video` | github.com/mohammednabarawy/ComfyUI-MiniMax-H3-Music-Video | **8★**（2026-08 建） | "Resumable, identity-aware" 的 H3 音乐视频节点 | ✅ 装插件（但极早期，别指望稳定） |
| `MeiGen-AI/InfiniteTalk` | github.com/MeiGen-AI/InfiniteTalk | **8,243★** | 音频驱动角色说话/唱歌（对口型、无限时长） | ✅ 有 ComfyUI 接入 |
| `vita-epfl/Stable-Video-Infinity` | github.com/vita-epfl/Stable-Video-Infinity | **2,617★** | 长视频不漂移（论文实现，社区工作流基于它做 SVI Pro） | ⚠️ 研究代码，需自己接 |
| **`ZHO-ZHO-ZHO/ComfyUI-Workflows-ZHO`** | github.com/ZHO-ZHO-ZHO/ComfyUI-Workflows-ZHO | **7,942★** 但**最后提交 2024-12-20** | 曾经最出名的中文工作流合集 | ❌ **已过气**：里面的模型/节点大多是 2024 年的，别照抄 |

> **一个正在发生的结构性变化**：`IPAdapter_plus`（2025-04 停更）、`Frame-Interpolation`（被内置吸收）、
> `WanVideoWrapper`（2026-05 后无提交）——社区插件正在被 ComfyUI 原生节点吸收。
> 这跟当年 AnimateDiff 的路径一模一样。**选方案时优先原生节点，插件当补充。**

---

## 3. MV 工作流的通行做法（这一节最有价值）

社区里真做出成片 MV 的人，几乎**没有**用"一个工作流从提示词直接出 1080p 成片"的。通行结构是：

```
歌曲 → ①节拍/段落分析 + 逐字对时 → ②分镜（一句歌词 1~2 个画面）
     → ③角色定妆/关键帧（一致性锚点）→ ④逐镜 I2V/Wan 出 3~6 秒
     → ⑤超分(SeedVR2) + 补帧(需要时) → ⑥代码合成（卡点拼接 + 歌词排版 + 转场）→ 交付
```

**证据（中文社区，B站实测播放量 `[实测数]`）**：

| 案例 | 播放 | 它证明的通行做法 |
|---|---|---|
| 「我是小政zzzzz」《5 天做了 4 支 MV，一帧都没手绘｜AI 做 MV 全流程》 | **19,661** | ①**节拍网格 + 逐字对时** ②**一句歌词一个画面**，且"**先签字再出图**" ③出图阶段**保持角色一致** ④最后**用 Remotion 写代码做视频 + 后期特效**（不是 ComfyUI 出成片） |
| 「努力在爬的咸鱼二世」《[开源] 全自动 AI PV/MV 技能》（开源 `ai-mv-pipeline`） | 2,635 | 一条完整自动化链：**节拍/段落分析 → 歌词对齐 → 分镜(shots.py) → 角色一致关键帧 → MiniMax H3 图生视频(ComfyUI) → 超分 → 代码合成(歌词排版+后期) → 审片** |
| 「像素幻想Lab」《MiniMaxH3，女团舞台 MV 制作全流程 + 视频反推复刻 + **丝滑首尾帧**》 | **33,068** | ③④ 之间用**首尾帧**做镜头衔接；工作流跑在 **RunningHub 云端**而不是本地 |
| 「AI音乐库-」《AI 音乐 MV 制作全攻略》 | **88,260** | MV 是"流程教学"品类，不是"模型教学"品类 |

### 3.1 镜头间连贯：三层做法，按可靠性排序

| 层 | 做法 | 谁在用 | 可靠性 |
|---|---|---|---|
| 画面层 | **同一张定妆/关键帧当 I2V 首帧 + 同 seed** | 几乎所有教程 | 高（首帧被硬锁） |
| 长镜头层 | **SVI / continuation / extend**：把 5s 接成 30s+，用上一段末帧续下一段 | `Wan 2.2 14b Long video (30s)` 18,765 dl；`H3 SEED HUNTER - Seamless Video Continuation` 38,196 dl；`SVI Pro 2.0` | 中高（漂移可控） |
| 角色层 | **训角色 LoRA**（SDXL 8,844 dl 的 trainer 工作流是主流路径） | 稳定出系列的创作者 | 高但要训练成本 |
| 音频层 | **InfiniteTalk**（8,243★）：音频驱动口型/演唱 | VTuber、演唱类 MV | 中（对口型强，构图受限） |

> **跨镜头一致性在社区也仍然是"难点"**，不是已解决问题：一致性专项工作流的下载量只有几百（803 / 576 / 94），
> 说明大家并不靠"一致性工作流"，而靠 **LoRA + 定妆帧 + 手工挑选**。

### 3.2 卡音乐节拍：不在 ComfyUI 里做

- **没有任何主流 ComfyUI 工作流负责"卡点"**。社区做法是先拿到**节拍网格 + 逐字时间轴**（librosa / 打轴工具 / Suno 导出的时间戳），
  再让"一句歌词 = 一个镜头"的时长去贴节拍，最后在**剪辑/代码层**对齐。
- `ai-mv-pipeline` 把这个做成了流水线的一等公民（节拍/段落分析 + 歌词对齐在城市台词之前）。
- 对我们的意义：**这块我们本来就有优势**（程序化时间轴），不需要引入模型。

### 3.3 把多段 3 秒拼成 2 分钟：社区标准答卷

| 环节 | 常见工具 | 备注 |
|---|---|---|
| 拼接 + 转场 | **Remotion（代码）/ ffmpeg / PR/达芬奇** | 高端案例用 Remotion 写代码；大多数人还是剪辑软件 |
| 卡点对齐 | 剪辑软件的标记点 / 代码时间轴 | 与 3.2 同源 |
| 超分统一画质 | SeedVR2（ComfyUI 内）或 Topaz（外置） | 放大类工作流下载量低（5,822），说明很多人**在 ComfyUI 外做** |
| 补帧 | 原生 RIFE/FILM 节点，或外置 | 同上 |
| 歌词排版 | ASS/Remotion/剪辑软件 | 我们已有 ASS 流水线（`scripts/make_full_ass*.py`），直接复用 |

**⇒ 结论：MV = "AI 出镜头" + "代码/剪辑做片子"。一体化 AIO 工作流再火（8 万下载），产出的也只是镜头，不是 MV。**

---

## 4. 我们的位置：3.7GB 在这条生态里排第几档

### 4.1 社区常见的显存档位（按 Civitai 工作流标题/说明里的自述 `[实测数]`）

| 档位 | 社区对应方案 | 代表证据 |
|---|---|---|
| **4 GB** | Wan2.1 GGUF 极小分辨率 + 长 offload | `Wan2.1(GGUF) only 4GB-VRAM` **29,752 dl** |
| **8 GB** | LTX-2.3 GGUF / SVI Pro Low VRAM / Wan2.2 5B offload | `SVI Pro 2.0 for Low VRAM (8GB)`；官方口径 Wan2.2 5B "8GB 可跑" |
| **12 GB** | **LTX-2.3 主力档**、Wan 14B fp8 开 block swap | `LTX-2.3 AIO for RTX 3060 12GB` **31,827 dl**；`LTX-2 19B GGUF 12GB` **21,254 dl** |
| **16 GB** | LTX-2.3 FP8 舒适 / Wan 14B 基本可用 | 2026 横评：14–16GB "all three become usable" |
| **24 GB（4090/3090 档）** | Wan 2.2 14B 满血、MiniMax H3 pruned int8 舒适 | H3 社区实测：pruned int8 DiT ≈ **20.0 GB** @2.17 s/it |
| **32 GB（5090）** | H3 NVFP4 常驻、LTX 全精度 | `pruned NVFP4 ≈ 11.9 GB` @1.90 s/it（需 Blackwell） |
| **48 GB+ / A100·H100** | H3 全 int8（31.7GB）、bf16（61.7GB） | "datacenter territory" |

### 4.2 老实说：3.7GB 算什么档次

- **在"可用显存"这个维度：低于社区最低档（4GB）**。4GB 档的工作流存在且有人用（29,752 下载），
  但它跑的是 Wan2.1 GGUF + 极小分辨率 + 极端 offload，**出的是草稿不是成片**。
- **在"显卡上限"这个维度：我们是 24GB，也就是社区说的"comfortable"档**。
  这两个事实不矛盾——我们不是缺卡，是**卡被别人占着**。
- **社区里对应我们处境的解法不是"降级"，是"排队或上云"**：
  B站上带工作流的教程里，大量直接挂 **RunningHub（云端跑工作流）** 的体验链接；
  海外对应 runcomfy / comfy.icu / mimicpc 这类"托管工作流"平台。
  也就是说：**社区遇到"卡不够/被占"时，主流答案是"云端跑一次"，而不是"把模型降到能塞进 3.7GB"。**

### 4.3 我们能复刻到什么程度

| 社区做法 | 我们能不能复刻 | 条件 |
|---|---|---|
| 分镜 + 节拍对齐 + 一句歌词一画面 | ✅ **完全能，而且我们本来就有程序化时间轴优势** | 无 |
| 逐镜 I2V（Wan2.2 5B / GGUF） | ✅ 能 | 需 ≥6~7GB 空闲（GGUF Q4）或 ≥12GB（fp16） |
| 角色 LoRA / 定妆帧一致 | ✅ 定妆帧能；LoRA **被内部约定挡住**（自有素材不入模型） | 需用户拍板 |
| SeedVR2 超分到 1080p | ✅ 能 | 6~9GB 估算 |
| 原生 RIFE 补帧 | ✅ 能 | <1.5GB，随时 |
| 长视频 SVI / continuation | ⚠️ 部分能（Wan2.2 5B 的 extend 玩法可试；SVI Pro 是 Wan2.2 14B 系，要 24GB 独占） | 空机 |
| LTX-2.3（12GB 档最热） | ⚠️ 能跑，但**许可要逐条核**（LTX-2 Community License） | 需 ≥16GB 空闲较舒服 |
| MiniMax H3 "最好的那一档" | ❌ 常态做不到 | pruned int8 ≈20GB 驻留 + ~40GB 磁盘/任务族 |
| Wan 2.6 / 2.7 / 3.0 | ❌ **只能云端/API**（无开放权重） | 见 §5 |
| 一体化 AIO 工作流（8 万下载那种） | ⚠️ 能导入，但它依赖 WanVideoWrapper 等插件，且默认按 24GB 独占调参 | 空机 + 装插件 |

### 4.4 哪些只能云端做

1. **Wan 2.6 / 2.7 / 3.0**：官方只有 API（ComfyUI 模板里对应的是 `api_wan2_6_i2v.json` / `api_wan2_7_i2v.json` / `api_wan3_0_i2v.json`，`api_` 前缀=云 API，无本地权重）。
   **旁证**：官方模板库 751 个 JSON 里 **340 个是 `api_` 云模板**（本地 411）——官方模板本身已有近一半是"云端才能跑"的。
2. **MiniMax H3 的 2K 重生成 / Context-IR**：官方**未发布**这两个部件（H3 的 QA 文档明确）。
3. **需要"独占 24GB 且立刻出结果"的场合**（给客户看片、赶档期）。
4. **社区托管工作流平台**（RunningHub / runcomfy / comfy.icu / mimicpc）：它们的价值就是"不用自己有卡"。

---

## 5. 如果只学三件事

### 第一件：**分镜与节拍对齐**（0 显存，收益最大）

社区里 MV 与"AI 视频合集"的分水岭就在这里：**一句歌词一个画面 + 节拍网格 + 逐字对时 + 先定分镜再出图**。
B站 19,661 播放那支《5 天 4 支 MV》全程"一帧都没手绘"，靠的就是这套流程纪律；
`ai-mv-pipeline` 直接把它写成代码（节拍/段落分析 → 歌词对齐 → shots.py）。
**这块我们本来就强（程序化时间轴 + ASS），只是还没用在 AI 镜头上。**

### 第二件：**I2V + 关键帧定妆 + （需要时）continuation**

- I2V 是绝对主力（Civitai `IMG to VIDEO` 106,140 dl，是 FLF2V 类工作流的 **70 倍**）。
- 一致性靠"定妆帧 + 同 seed"，不是靠某个"一致性节点"。
- 想把 5s 变长，走 **SVI/continuation 系**（这是 2026 上升最快的技法之一），而不是硬拉长帧数。

### 第三件：**代码合成，而不是在 ComfyUI 里出成片**

做得好的 MV 都是"AI 出镜头 → 代码/剪辑合成"（Remotion / ffmpeg / 我们的 WebGL）。
**我们已有的最强资产恰恰是这一层**（WebGL 粒子/水墨、ASS 字幕、ffmpeg 流水线），
所以最省力的路径不是"换成一体化工作流"，而是**把 AI 镜头塞进现有渲染管线**。

---

## 6. 与上一份报告的关系（谁覆盖谁）

| 问题 | 看哪份 |
|---|---|
| 网上流行什么、大家在用什么、我们的位置 | **本文** |
| 我们这台机器具体能跑什么、显存/许可/下载命令/验证步骤 | 《ComfyUI-MV工作流调研.md》+《ComfyUI-落地清单.md》 |

**需要修正上一份的两处**（因为社区现状变了）：

1. 上一份把 **LTX-Video 0.9.8** 当成"许可坑、暂不碰"。现状是 **LTX-2.3 已是 12GB 档的主流之一**（31,827 dl），
   应当从"不推荐"改为"**在核清 LTX-2 Community License 之后可考虑**"。
2. 上一份完全没提 **MiniMax H3**。它已经是我们这台机器上**唯一预装好的 2026 新模型**
   （`minimax_h3_fl2va_pruned_int8_convrot.safetensors` 等，在 `models/diffusion_models/`），
   中文社区最热，但**许可非 OSI、显存需求 ~20GB 驻留**——属于"有条件可用"，需要单独立项评估。

---

## 7. 证据清单（可复核）

**GitHub（`/repos` API，2026-11-02 取值，star / 最后提交）**
- Comfy-Org/ComfyUI 144,591★ / 2026-11-02 — https://github.com/Comfy-Org/ComfyUI
- Comfy-Org/ComfyUI-Manager 16,694★ / 2026-11-01 — https://github.com/Comfy-Org/ComfyUI-Manager
- Wan-Video/Wan2.2 18,319★ / 2026-09-21 — https://github.com/Wan-Video/Wan2.2
- Wan-Video/Wan2.1 17,359★ / 2026-03-05 — https://github.com/Wan-Video/Wan2.1
- Tencent-Hunyuan/HunyuanVideo 12,710★ / 2026-10-08 — https://github.com/Tencent-Hunyuan/HunyuanVideo
- Lightricks/LTX-2 10,032★ / 2026-10-18（2026-01 建仓） — https://github.com/Lightricks/LTX-2
- Lightricks/ComfyUI-LTXVideo 4,236★ / 2026-10-20 — https://github.com/Lightricks/ComfyUI-LTXVideo
- MeiGen-AI/InfiniteTalk 8,243★ / 2026-05-22 — https://github.com/MeiGen-AI/InfiniteTalk
- kijai/ComfyUI-WanVideoWrapper 6,802★ / **2026-05-24** — https://github.com/kijai/ComfyUI-WanVideoWrapper
- cubiq/ComfyUI_IPAdapter_plus 6,169★ / **2025-04-14（停更）** — https://github.com/cubiq/ComfyUI_IPAdapter_plus
- city96/ComfyUI-GGUF 4,221★ / 2026-01-12 — https://github.com/city96/ComfyUI-GGUF
- ZHO-ZHO-ZHO/ComfyUI-Workflows-ZHO 7,942★ / **2024-12-20（过气）** — https://github.com/ZHO-ZHO-ZHO/ComfyUI-Workflows-ZHO
- Kosinkadink/ComfyUI-AnimateDiff-Evolved 3,564★ / 2026-07-28（仅维护） — https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved
- Fannovel16/ComfyUI-Frame-Interpolation 1,092★ / 2026-03-29 — https://github.com/Fannovel16/ComfyUI-Frame-Interpolation
- numz/ComfyUI-SeedVR2_VideoUpscaler 2,960★ / 2025-12-24 — https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler
- vita-epfl/Stable-Video-Infinity 2,617★ / 2026-09-17 — https://github.com/vita-epfl/Stable-Video-Infinity
- Inanis404/ai-mv-pipeline 22★ / 2026-10-20 — https://github.com/Inanis404/ai-mv-pipeline
- mohammednabarawy/ComfyUI-MiniMax-H3-Music-Video 8★ / 2026-09-10 — https://github.com/mohammednabarawy/ComfyUI-MiniMax-H3-Music-Video
- seitanism/ComfyUI-H3-Motion-Context-MultiRef 281★ / 2026-09-05 — https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef
- raindrop313/ComfyUI-WanVideoStartEndFrames 383★ / 2025-03-22（前首尾帧插件） — https://github.com/raindrop313/ComfyUI-WanVideoStartEndFrames

**Civitai（`/api/v1/models`，下载量 AllTime，2026-11-02 取值）**
- WAN 2.2 AIO — 83,596 dl / 1,987👍 / 21 版本 — https://civitai.red/models/1824027
- WAN 2.2 Workflow T2V-I2V-T2I (Kijai Wrapper) — 66,086 dl / 2,175👍 / 361 评论 — https://civitai.red/models/1818841
- DaSiWa Wan2.2 / I2V / SVI 2.0 / FLF2V — 48,463 dl — https://civitai.red/models/1823089
- Minimax H3 SEED HUNTER（潜空间放大 + 无缝续接）— 38,196 dl — https://civitai.red/models/2881362
- LTX-2.3 AIO for RTX 3060 12GB — 31,827 dl — https://civitai.red/models/2354193
- Wan2.1(GGUF) only 4GB-VRAM — 29,752 dl — https://civitai.red/models/1309674
- LTX-2 19B GGUF 12GB — 21,254 dl；LTX-2.3 22B GGUF 12GB — 20,716 dl
- Wan 2.2 14b Long video (30s) — 18,765 dl；WAN 2.2 i2v for LONG videos — 15,383 dl
- 【WAN2.1】IMG to VIDEO — 106,140 dl / 3,307👍
- FLF2V 专项工作流 — 1,015 / 1,242 / 1,300 / 1,413 / 1,577 / 1,640 dl（**说明是功能不是品类**）
- SeedVR2 one-step 4X — 5,822 dl；补帧类 — 181~1,814 dl；一致性专项 — 803 / 576 / 94 dl

**B站（搜索 API，2026-11-02 取值，播放量）**
- 《5 天做了 4 支 MV，一帧都没手绘｜AI 做 MV 全流程》19,661 播放 / 117 评论 — https://www.bilibili.com/video/BV1hhHi65EnQ
- 《[开源] 全自动 AI PV/MV 技能》2,635 播放（对应 ai-mv-pipeline）— https://www.bilibili.com/video/BV1XYnF6GErG
- 《MiniMaxH3，女团舞台表演 MV 制作全流程 + 视频反推复刻 + 丝滑首尾帧》33,068 播放 / 105 弹幕 — https://www.bilibili.com/video/BV1NWuB6CE6L
- 《AI 音乐 MV 制作全攻略》88,260 播放 — https://www.bilibili.com/video/BV1R9QcBdETs
- 《教你用 6G 显存纯手搓一部 AI 短剧》14,187 播放；《教你用 8G 显存流畅跑 AI 漫剧》426,993 播放（低显存是中文圈的"内容品类"）
- 搜"ComfyUI 工作流 教程"前 20 条：6 条标题/标签含 `MiniMaxH3` 或 `秋叶整合包`；播放量最高 961,374

**许可与生态**
- Wan2.2 官方教程（Apache-2.0 支持商用）：https://docs.comfy.org/tutorials/video/wan/wan2_2
- MiniMax H3 许可与 VRAM 档位（社区整理，含官方链接）：https://github.com/iSk2y/awesome-minimax-h3
- MiniMax H3 官方本地部署文档：https://platform.minimax.cn/docs/guides/local-deploy-h3.md
- ComfyUI Day-0 支持 MiniMax H3：https://blog.comfy.org/p/minimax-h3-day-0-support-in-comfyui
- LTX-2 许可文本：https://github.com/Lightricks/LTX-2/blob/main/LICENSE
- LTX-2 Community License 的"商业门槛"争议（第三方记录）：https://huggingface.co/xocialize/ltx-2.3-granules/commit/04754c9c891d71c27064cdd10d0a6701a8603b74
- 2026 三方横评（LTX-2.3 vs WAN 2.2 vs HunyuanVideo 1.5，含显存档位表）：https://www.earngenix.com/workflows/best-local-ai-video-model-2026
- Wan 版本"开放权重 vs 仅 API"对照：https://oneinfer.ai/models/family/wan
- Stable Video Infinity 工作流说明：https://www.runcomfy.com/comfyui-workflows/stable-video-infinity-in-comfyui-long-video-continuity-workflow

**未验证项（别当事实用）**
- SVI 仓库的具体许可条款（只看到有 LICENSE 文件，未逐条核）
- InfiniteTalk 的许可
- 各社区 checkpoint（Illustrious / NoobAI / Krea 2 / Z-Image）的商用条款
- "秋叶整合包"内各组件的确切来源与许可（**因此本文不建议使用任何整合包**）
