# ComfyUI 落地清单（从零到能跑 · 2026-11）

> 配套《ComfyUI-MV工作流调研.md》。本文只讲**怎么做**，每一步都有可复制命令。
> 前置事实（实测，别再按旧假设走）：
>
> | 事 | 实际 |
> |---|---|
> | ComfyUI 真实地址 | **`127.0.0.1:8188`**（v0.38.0，只监听本机回环） |
> | `8211` 是什么 | `imgproxy` 网关 → stable-diffusion.cpp，**只能出图，不能跑视频** |
> | 另一实例 | nightly 在 `127.0.0.1:8190` |
> | 模型根目录 | `~/Server/ComfyUI/models/` |
> | 磁盘 | `/home` 剩 261G |
> | 显存 | 3090 Ti 24GB，勘测时**已用 20.4GB / 剩 3.7GB** |
>
> 本轮调研**没有**下载、没有占显存、没有重启。下面所有 `--run` 都是留给你的动作。

---

## 1. 开工前的三条只读自检（不占显存，先确认环境没变）

```bash
# ① 显存现在有多少空闲
ssh xhqm@100.99.5.35 'nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv'

# ② ComfyUI 活着吗 + 版本
ssh xhqm@100.99.5.35 'curl -s http://127.0.0.1:8188/system_stats | head -c 400; echo'

# ③ 端口真相（防止又去调 8211）
ssh xhqm@100.99.5.35 'ss -ltnp | grep -E ":(8188|8190|8211)"'
```

**期望**：① `memory.free` ≥ 12000 MiB 才考虑 5B fp16；只有 6000~7000 就走 §4 的 GGUF；
② 返回含 `"comfyui_version": "0.38.0"`；③ 8211 那一行是 `python3`（imgproxy），8188 是 `python`（ComfyUI）。

---

## 2. 下模型（唯一需要耐心的一步）

### 2.1 用脚本（推荐；每个 URL 都已 HEAD 验证 200）

仓库里已经放好：`scripts/comfy/fetch_models.sh`

```bash
# 把脚本传到服务器（或随便放，脚本只管下载路径）
scp scripts/comfy/fetch_models.sh xhqm@100.99.5.35:/tmp/

# 第一步：只检查 URL 通不通（不下载，10 秒）
ssh xhqm@100.99.5.35 'cd /tmp && chmod +x fetch_models.sh && ./fetch_models.sh --check mvp post'

# 第二步：真下载（可断点续传，Ctrl-C 再跑会接着下）
ssh xhqm@100.99.5.35 'cd /tmp && ./fetch_models.sh --run mvp'
```

`--check` 的真实输出（2026-11-02 实测）：

```
=== 档位: mvp  (仅检查)
  [200] diffusion_models/wan2.2_ti2v_5B_fp16.safetensors         10.00 GB
  [200] text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors     6.74 GB
  [200] vae/wan2.2_vae.safetensors                               1.41 GB
=== 档位: post  (仅检查)
  [200] frame_interpolation/rife_v4.26.safetensors               22.7 MB
  [200] frame_interpolation/film_net_fp16.safetensors            68.9 MB
  [200] diffusion_models/seedvr2_3b_int8_convrot.safetensors     3.46 GB
  [200] vae/seedvr2_ema_vae_fp16.safetensors                     0.50 GB
```

档位总表：

| 档位 | 内容 | 磁盘 | 用途 |
|---|---|---|---|
| `mvp` | Wan2.2 TI2V-5B fp16 + umt5 fp8 + wan2.2_vae | **18.15 GB** | 出片主力（T2V+I2V 一体） |
| `mvp-gguf` | 同上换 GGUF Q4_K_M + Wan2.2_VAE | **4.84 GB**（+共用 umt5） | 只剩 6~7GB 显存时 |
| `post` | RIFE + FILM + SeedVR2 3B int8 + 其 VAE | **3.9 GB** | 补帧 + 1080p 放大 |
| `flf2v` | Wan2.1 FLF2V 720P 14B fp8 + wan2.1_vae | **16.65 GB** | 首尾帧（要空机） |
| `hero` | I2V-A14B fp8 high/low + 4 步 LoRA ×2 | **31.04 GB** | 关键镜头（要空机） |

### 2.2 不想用脚本时的等价 curl（一条一条贴）

```bash
M=https://modelscope.cn/models          # 大文件：ModelScope（实测 ~3.2MB/s）
H=https://hf-mirror.com                 # 小文件：hf-mirror（实测 ~0.28MB/s，别下大文件）
cd ~/Server/ComfyUI/models

# --- mvp ---
curl -L -C - -o diffusion_models/wan2.2_ti2v_5B_fp16.safetensors \
  $M/Comfy-Org/Wan-2.2/resolve/master/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors
curl -L -C - -o text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors \
  $M/Comfy-Org/Wan-2.2/resolve/master/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
curl -L -C - -o vae/wan2.2_vae.safetensors \
  $M/Comfy-Org/Wan-2.2/resolve/master/split_files/vae/wan2.2_vae.safetensors

# --- post（补帧+放大）---
curl -L -C - -o frame_interpolation/rife_v4.26.safetensors \
  $H/Comfy-Org/Frame-Interpolation/resolve/main/frame_interpolation/rife_v4.26.safetensors
curl -L -C - -o diffusion_models/seedvr2_3b_int8_convrot.safetensors \
  $H/Comfy-Org/SeedVR2/resolve/main/diffusion_models/seedvr2_3b_int8_convrot.safetensors
curl -L -C - -o vae/seedvr2_ema_vae_fp16.safetensors \
  $H/Comfy-Org/SeedVR2/resolve/main/vae/seedvr2_ema_vae_fp16.safetensors
```

### 2.3 下完的三个检查

```bash
# ① 文件大小对不对（对照上表，差太多就是没下完）
ssh xhqm@100.99.5.35 'ls -lh ~/Server/ComfyUI/models/{diffusion_models,text_encoders,vae,frame_interpolation} | grep -v put_'

# ② safetensors 头部能不能读（!= 更稳的完整性检查）
ssh xhqm@100.99.5.35 'python3 - <<PY
import json,struct,glob
for f in glob.glob("/home/xhqm/Server/ComfyUI/models/**/*.safetensors", recursive=True):
    if "seedvr2" not in f and "wan" not in f and "umt5" not in f: continue
    with open(f,"rb") as fh:
        n=struct.unpack("<Q", fh.read(8))[0]
        hdr=json.loads(fh.read(n))
    print("%-60s tensors=%d" % (f.split("models/")[1], len(hdr)-1))
PY'

# ③ ComfyUI 认不认（不需要重启：folder_paths 按目录 mtime 失效）
ssh xhqm@100.99.5.35 'curl -s http://127.0.0.1:8188/object_info/UNETLoader | head -c 600; echo'
```

**期望**：③ 返回的 `unet_name` 枚举里出现 `wan2.2_ti2v_5B_fp16.safetensors`。
如果没出现：UI 里点一次 "Refresh"，或者 `touch` 一下 models 子目录再查。

---

## 3. 自定义节点：**MVP 一个都不用装**

现状：`custom_nodes/` 只有 `moss-image` 和 `mvkit_mvbuild`，而我们要的东西**全是原生**：

| 要用 | 原生节点 | 要装插件？ |
|---|---|---|
| Wan2.2 T2V/I2V | `Wan22ImageToVideoLatent`、`WanImageToVideo` | ❌ 不用 |
| 首尾帧 | `WanFirstLastFrameToVideo` | ❌ 不用 |
| 运镜 | `WanCameraImageToVideo` | ❌ 不用 |
| 补帧 | `FrameInterpolationModelLoader` + `FrameInterpolate` | ❌ 不用 |
| 放大 | `SeedVR2*` 五件套 | ❌ 不用 |
| **GGUF 量化** | `UnetLoaderGGUF` | ✅ **只有走 GGUF 才要装** |

只有走低显存 GGUF 时才需要装一个（Apache-2.0）：

```bash
# 装（不重启正在跑的服务；装完需要重启进程才会加载新节点——所以挑没人的时候做）
cd ~/Server/ComfyUI/custom_nodes
git clone https://github.com/city96/ComfyUI-GGUF          # github 可达，实测 200
cd ComfyUI-GGUF && ~/Server/ComfyUI/.venv/bin/pip install -r requirements.txt

# 装完重启（**这一步会打断别人，务必先打招呼**）
#   推荐放到夜间；重启用 screen/tmux 或你们现有的 supervisor，别用 kill -9
```

> ⚠️ 本轮调研**没有**装、也**没有**重启。装 GGUF 节点这件事建议等真正需要时再做——
> 因为 mvp 的 fp16 路线（显存 ≥12GB 空闲）本来就能跑。

---

## 4. 显存不够时的降级路径（按"先降什么"排序）

**顺序原则：先降分辨率 → 再降帧数 → 再量化 → 再搬文本编码器 → 最后换小模型。**
（先降帧数反而比降分辨率更毁观感，因为 Wan 对帧数敏感度低于分辨率）

| 级别 | 动作 | 省多少 | 命令/改法 | 代价 |
|---|---|---|---|---|
| L0 | 什么都不改 | — | `832×480, length=97, 20步` | 需 ~12GB 空闲 |
| L1 | **降分辨率** 832×480 → 640×384 | ~30~40% 激活 | `"width":640,"height":384`（32 倍数） | 细节少，远景点可接受 |
| L2 | **降帧数 + 补帧回填** 97→49 帧，出片后用 RIFE ×2 | ~50% | `"length":49` 再跑 `frame_interp_film.api.json` | 动作幅度变小；49→98 帧@48fps 放回 24fps 时间线≈4s |
| L3 | **GGUF Q4_K_M** 替 fp16 | 权重 10.0→3.43GB | `UnetLoaderGGUF` + `Wan2.2-TI2V-5B-Q4_K_M.gguf` | 慢 10~25%，细节略软；需装插件+重启 |
| L4 | **文本编码器搬 CPU** | 省 ~6.7GB | `CLIPLoader.device = "cpu"`（枚举里有才用） | 编码慢一点，显存立省一大块 |
| L5 | **分块解码**：`VAEDecode` → `VAEDecodeTiled` | 解码峰值大降 | `tile_size=256/320, overlap=64` | 极慢，只在 OOM 卡在 decode 时用 |
| L6 | **换更小模型** | 大幅 | `wan2.1_vace_1.3B_fp16`（4.31GB） | 画质只够草稿 |
| L7 | **不跑模型** | 0 | ffmpeg `minterpolate` 光流做衔接 | 不生成新内容 |

**必开的保险**（OOM 时先加这个，实测有效）：
```bash
# 启动参数里加（需要重启，且会打断别人）
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
# 或者给 ComfyUI 留出余量
python main.py --reserve-vram 2.0 --listen 127.0.0.1 --port 8188
```
> 参考：Wan2.2 issue #90 里 3090 24GB 正是卡在 VAE decode 阶段，加 `expandable_segments:True` 是社区通行解法。

**"只剩 6~7GB" 的推荐组合**：
`mvp-gguf 档 + L1（640×384）+ L2（49 帧）+ L4（文本编码器 CPU）+ L5（分块解码）`
—— 这条组合能出 2 秒左右的草稿，用来定构图/运镜，最终镜头再挑空机时段用 fp16 重跑。

---

## 5. 怎么验证它真的跑通了（五步，逐步加码）

### 第 1 步：图结构校验（**不占显存**，随时可以做）

```bash
scp scripts/comfy/validate_workflow.py scripts/comfy/*.api.json xhqm@100.99.5.35:/tmp/comfy_check/
ssh xhqm@100.99.5.35 'cd /tmp/comfy_check && python3 validate_workflow.py --base http://127.0.0.1:8188'
```

**本次实测输出（模型还没下的时候，2026-11-02）**：

```
拉取 http://127.0.0.1:8188/object_info ...
节点类型 971 个

[PASS] frame_interp_film.api.json  (6 节点：required/类型/枚举/形状 全部通过)
[PASS] seedvr2_3b_upscale.api.json  (13 节点：required/类型/枚举/形状 全部通过)
   ! 待准备资源 1(UNETLoader).unet_name: 'seedvr2_3b_int8_convrot.safetensors' 不在服务器清单里（现有 6 个：...）
[PASS] wan22_5b_i2v.api.json  (13 节点：required/类型/枚举/形状 全部通过)
[PASS] wan22_5b_t2v.api.json  (11 节点：required/类型/枚举/形状 全部通过)
[PASS] wan2_1_flf2v_720p.api.json  (13 节点：required/类型/枚举/形状 全部通过)

5/5 通过
```

**怎么读**：
- `[PASS]` + 全部节点通过 = 节点类型、必填项、连线类型、枚举取值、`length=4n+1`、宽高 32 倍数 **都对**。
- `! 待准备资源` = 模型文件还没下（不是图错了）。
- **模型下完后再跑一次，`!` 行应该消失**。加 `--strict` 则缺模型也判 FAIL（适合当 CI 门禁）。

### 第 2 步：极小样跑通（49 帧 / 8 步，只验证通路，约 1~3 分钟）

```bash
scp scripts/comfy/run_workflow.py xhqm@100.99.5.35:/tmp/comfy_check/
ssh xhqm@100.99.5.35 'cd /tmp/comfy_check && \
  python3 run_workflow.py wan22_5b_t2v.api.json \
    --base http://127.0.0.1:8188 \
    --set 7:length=49 --set 8:steps=8 --set 11:filename_prefix=mv/smoke_test'
```

**期望输出**（关键行）：

```
set 7.length = 49
set 8.steps = 8
已提交 prompt_id=xxxxxxxx-...（排队号 0）
   12.3s  运行中  排队 0
状态: success  用时 96.4s
产物: data/comfy_out/wan22_5b_t2v_00xxx.mp4 (xxxxxxx bytes)
```

判定标准（三条全中才算跑通）：
1. `状态: success`（不是 `error`）；
2. 有 `产物: ...mp4` 且字节数 > 100KB；
3. 下面 `ffprobe` 显示 **49 帧、24fps、832×480**。

### 第 3 步：验收产物（在服务器上跑）

```bash
ssh xhqm@100.99.5.35 'ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,nb_frames,duration \
  -of default=nw=1 /tmp/comfy_check/data/comfy_out/wan22_5b_t2v_00001_.mp4'
```

**期望**：
```
codec_name=h264
width=832
height=480
r_frame_rate=24/1
nb_frames=49
duration=2.041667
```
> 49 帧 @24fps ≈ 2.04s。如果 `nb_frames` 明显少于 49，说明 `length` 没被接受（记住必须是 4n+1）。

### 第 4 步：显存峰值对照（验证降级档位是否够用）

```bash
# 一边跑第 2 步，一边另开一个 shell：
ssh xhqm@100.99.5.35 'nvidia-smi --query-gpu=memory.used --format=csv,noheader -l 1 | sort -n | tail -1'
```

把峰值和这张表对一下（首次实测后请把真实数字填进来）：

| 配置 | 预期峰值（估算/官方） | 我们实测 |
|---|---|---|
| 832×480×49，8 步（smoke） | 8~11 GB | ☐ 待填 |
| 832×480×97，20 步 | 10~13 GB | ☐ 待填 |
| 1280×704×121，20 步 | 13~16 GB（官方称 8GB 可跑，靠 offload） | ☐ 待填 |
| GGUF Q4 640×384×49 | 6~7 GB | ☐ 待填 |

> 只要"实测 > 当时空闲显存"，就会 OOM。降级路径见 §4。

### 第 5 步：全链路（真实成片流程）

```bash
# ① 出片（从定妆帧出发，I2V）
python3 run_workflow.py wan22_5b_i2v.api.json --set 12:image=dingzhuang.png \
        --set 7:length=97 --set 8:seed=1 --set 11:filename_prefix=mv/shot01

# ② 补帧 24→48fps
#    ⚠️ LoadVideo 只认 ComfyUI/input/ 下的文件，所以先把产物拷进去
cp ~/Server/ComfyUI/output/mv/shot01_00001_.mp4 ~/Server/ComfyUI/input/
python3 run_workflow.py frame_interp_film.api.json --set 2:file=shot01_00001_.mp4 --set 4:multiplier=2

# ③ 放大到 1080p（SeedVR2 3B）
cp ~/Server/ComfyUI/output/mv/interp_00001_.mp4 ~/Server/ComfyUI/input/
python3 run_workflow.py seedvr2_3b_upscale.api.json --set 3:file=interp_00001_.mp4

# ④ 落到成片
ffmpeg -i upscaled_1080p_00001.mp4 -vf "fps=30,unsharp=5:5:0.4" -c:v libx264 -crf 17 shot01_final.mp4
```

---

## 6. 六个 JSON 的用法（都在 `scripts/comfy/`）

| 文件 | 格式 | 怎么用 | 输入 | 输出 |
|---|---|---|---|---|
| `wan22_5b_ti2v.ui.json` | **UI 格式**（官方模板原样） | 拖进 ComfyUI 画布，或 菜单 → Workflows → Open | 无（纯文字提示词） | `output/video/ComfyUI_*.mp4` |
| `wan22_5b_t2v.api.json` | API 格式 | `run_workflow.py` / `POST /prompt` | 提示词 | `output/mv/wan22_5b_t2v_*.mp4` |
| `wan22_5b_i2v.api.json` | API 格式 | 同上，多一个 `12:image=` | `input/` 下的图 | `output/mv/wan22_5b_i2v_*.mp4` |
| `wan2_1_flf2v_720p.api.json` | API 格式 | 同上（**要空机**） | 两张图 | `output/mv/flf2v_wan21_*.mp4` |
| `frame_interp_film.api.json` | API 格式 | 同上（输入视频要先拷进 `ComfyUI/input/`） | `input/` 下的视频 | `output/mv/interp_*.mp4` |
| `seedvr2_3b_upscale.api.json` | API 格式 | 同上 | `input/` 下的视频 | `output/mv/upscaled_1080p_*.mp4` |
| `_official/*.json` | 官方 blueprint（含子图） | 在 GUI 里导入，或当参考 | — | — |

**GUI 里导入 API 格式的注意**：ComfyUI 画布**不吃** API 格式（那是给 `/prompt` 用的）。
要图形界面改参数，用 `wan22_5b_ti2v.ui.json` 或 `_official/` 里的官方文件。

**直接 curl 调 API**（不想用脚本时）：

```bash
ssh xhqm@100.99.5.35 'cd /tmp/comfy_check && \
python3 -c "
import json,sys
g=json.load(open(\"wan22_5b_t2v.api.json\"))
g={k:v for k,v in g.items() if not k.startswith(\"_\")}
g[\"7\"][\"inputs\"][\"length\"]=49
print(json.dumps({\"prompt\":g}))
" > /tmp/payload.json && \
curl -s -X POST http://127.0.0.1:8188/prompt -H "Content-Type: application/json" -d @/tmp/payload.json'
```

**期望**：`{"prompt_id": "...", "number": 0, "node_errors": {}}`
—— 注意 `node_errors` 必须是空对象。非空就是参数/模型名有问题，直接看里面的提示。

查结果：
```bash
curl -s http://127.0.0.1:8188/history/<prompt_id> | python3 -m json.tool | head -40
# status.status_str == "success"，outputs 里能看到 SaveVideo 的 filename
curl -s "http://127.0.0.1:8188/view?filename=<filename>&subfolder=mv&type=output" -o out.mp4
```

---

## 7. 优先级：先用哪个、后加哪个（时间有限版）

### 🚩 最快看到效果的一条路（约 2.5 小时，其中 2 小时是在等下载）

| 时段 | 做什么 | 命令 | 产出 |
|---|---|---|---|
| T+0:00 | 自检 + 建目录 | §1 | 确认显存/端口 |
| T+0:05 | 起下载（后台） | `./fetch_models.sh --run mvp post &` | 18.15+3.9 GB |
| T+0:10 | 期间做**定妆帧**：挑 1 张确定要动的原创造型图放 `ComfyUI/input/dingzhuang.png` | — | I2V 的锚点 |
| T+2:00 | 图结构校验（模型下完应无 `!`） | §5 第 1 步 | `5/5 通过` |
| T+2:10 | **smoke test 49 帧** | §5 第 2 步 | 第一条 mp4 |
| T+2:20 | 出第一段真镜头（97 帧） | `--set 7:length=97` | 4 秒素材 |
| T+2:35 | 补帧 → 放大 → 成片 | §5 第 5 步 | 1080p30 片段 |

**这条路的唯一门槛**：此刻显存要 ≥12GB。若只有 6~7GB，把 `mvp` 换成 `mvp-gguf`（多一步装插件+重启，挑夜间）。

### 后面再加（按性价比）

| 顺序 | 加什么 | 为什么排这个位置 | 前置 |
|---|---|---|---|
| ① | **SeedVR2 3B 放大**（已经在 `post` 档里） | 立刻把片子从"AI 味 480p"拉到"能用 1080p"，成本 3.9GB | mvp 跑通 |
| ② | **RIFE 补帧** | 消抖、把 16/24fps 变 32/48fps，几乎零成本 | 同上 |
| ③ | **定妆帧体系**（每个角色/每套衣服一张） | 一致性唯一可靠解法，纯管理不需要技术 | ① ② 稳定后 |
| ④ | **hero 14B（I2V-A14B + 4 步 LoRA）** | 画质跃升最明显的一档，但要 ≥20GB 空闲；4 步 LoRA 让单镜头 110s（实测）可接受 | 找空机时段 |
| ⑤ | **flf2v 首尾帧** | 解决"镜头衔接"，但只在有明确两帧时才用得上 | ④ 之后，同上要空机 |
| ⑥ | 风格化后处理（ffmpeg + 现有 GLSL） | 不急：现在的 WebGL 水墨已经够，别为它冒一致性风险 | 全片成型后 |
| ❌ | 训角色 LoRA / img2img 风格迁移 | **不做**（触碰"自有素材不入模型"的约定） | — |

### 两条内容的用法差异

- **vlog 切片（30~60s）**：1~2 个 AI 镜头就够，其余仍是 Live2D。用 I2V 把"定妆帧/Live2D 截图"动起来，单段 4~5s，成本最低。
- **二创 MV（2~3min）**：需要 **6~10 个 3~6s 片段**拼接。按 5B/97帧 每段 3~6 分钟算，一条 MV 的 AI 生成时间约 **0.5~1 小时**（不含重抽）。这个节奏是可行的——**但每段都要先有定妆帧**，否则一定换人。

---

## 8. 红线与约定（写进流程，别靠记性）

1. **输入必须是原创**：I2V 的输入图只能是**我们自己拍的/画的**画面。他人作品、动画截图、画师图 —— 一律不进。
2. **不把自有美术素材投进生成模型**：
   - ✅ 允许（待你确认）：自有原创帧 → **I2V 当运动起点**（首帧被 VAE 硬锁，不重绘）
   - ❌ 禁止：自有素材 → img2img / 局部重绘 / 风格迁移 / 训练 LoRA
3. **不动的东西**：`data/videos/`、`manifest.json`、`song.m4a` —— 本清单里所有命令都不碰它们（产物一律进 `output/mv/` 或 `data/comfy_out/`）。
4. **不装不明来源的东西**：只用 ComfyUI 原生 + `city96/ComfyUI-GGUF`（Apache-2.0）。不要"整合包"。
5. **不能商用的，记下来**：SVD（社区许可=非商用）、LTX-Video（自定义许可，未核前别商用）、NoobAI（Fair AI 1.0-SD）、Illustrious（sdxl-license）。
   **能商用的**：Wan2.2 / Wan2.1（Apache-2.0）、SeedVR2（Apache-2.0）、RIFE（MIT）、FILM（Apache-2.0）、Real-ESRGAN（BSD-3）。
6. **别把别人的显存当免费的**：14B 之前先 `nvidia-smi` 看空闲，或跟同事打招呼。跑完不要留模型常驻。

---

## 9. 故障排查速查

| 现象 | 最可能的原因 | 处置 |
|---|---|---|
| `node_errors` 里说 `Value not in list: unet_name` | 模型没下 / 名字拼错 / 目录放错 | §2.3 检查；`models/diffusion_models/` |
| `KSampler` 报 shape 不匹配 | `length` 不是 `4n+1`，或宽高不是 32 倍数 | 改成 49/81/97/121；宽高 640/832/1280×384/480/704 |
| `CUDA out of memory` 在采样阶段 | 显存不够 | §4 L1→L2→L3 |
| `CUDA out of memory` 在 **VAE decode** | 解码峰值（Wan2.2 issue #90 同款） | `VAEDecodeTiled` + `expandable_segments:True` |
| 出片全灰 / 全黑 | 用错 VAE（SeedVR2 用了 wan vae，或反之） | SeedVR2 必须 `seedvr2_ema_vae_fp16`；Wan2.2 5B 必须 `wan2.2_vae`；Wan2.1 用 `wan_2.1_vae` |
| 人物每帧都在变脸 | 没用首帧条件 / 抽卡不同 seed | 用 `wan22_5b_i2v` + 固定 `seed` + 同一定妆帧 |
| 画面抖/闪 | 直接放大未补帧；或用了 RealESRGAN 逐帧放大 | 走 SeedVR2（时间一致）+ RIFE |
| 调 `8211` 报错/没反应 | 那是 sd.cpp 图片网关，不是 ComfyUI | 改用 `127.0.0.1:8188` |
| macOS 连不上 8188 | 只监听回环 | `ssh -L 8188:127.0.0.1:8188 xhqm@100.99.5.35` |
| 下载卡在 0 B | 走了 huggingface.co | 换 ModelScope（见 §2） |
| `UnetLoaderGGUF` 不存在 | 没装插件 / 装了没重启 | §3 |

---

## 附：本次交付文件清单

```
docs/
  ComfyUI-MV工作流调研.md          # 方案/显存/许可/对比表/短板
  ComfyUI-落地清单.md              # 本文
scripts/comfy/
  wan22_5b_ti2v.ui.json            # 官方 UI 工作流（可直接导入）
  wan22_5b_t2v.api.json            # 歌词→画面      ✅ 图结构已校验
  wan22_5b_i2v.api.json            # 图生视频        ✅ 图结构已校验
  wan2_1_flf2v_720p.api.json       # 首尾帧（要空机） ✅ 图结构已校验
  frame_interp_film.api.json       # 补帧（RIFE/FILM）✅ 图结构已校验
  seedvr2_3b_upscale.api.json      # 放大到 1080p     ✅ 图结构已校验
  validate_workflow.py             # 只读校验器（不占显存）
  run_workflow.py                  # 提交/轮询/下载产物
  fetch_models.sh                  # 分档下载（URL 全部 HEAD 验证 200）
  _official/                       # 官方 blueprint 原件（Wan2.2 I2V/T2V、VACE FLF2V、补帧、SeedVR2、GAN放大）
```
