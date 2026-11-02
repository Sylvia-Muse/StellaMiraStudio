# scripts/comfy — MV 视频工作流资产

配套文档：`docs/ComfyUI-MV工作流调研.md`、`docs/ComfyUI-落地清单.md`（先看这两份）。

**这里的每个 JSON 都已用 `validate_workflow.py` 对着线上 ComfyUI（`127.0.0.1:8188`，971 个节点）校验过图结构**：
节点类型 / 必填项 / 连线类型 / 枚举取值 / `length=4n+1` / 宽高 32 倍数 —— 5/5 通过。
（模型文件本轮**没有下载**，所以校验输出里会有 `! 待准备资源` 行，下完模型后消失。）

| 文件 | 用途 | 模型（磁盘） | 显存档位 |
|---|---|---|---|
| `wan22_5b_ti2v.ui.json` | 官方 UI 工作流，可直接拖进 ComfyUI 画布 | Wan2.2 TI2V-5B 三件套 | ≥12GB 空闲 |
| `wan22_5b_t2v.api.json` | 一句歌词 → 3~5s 画面 | 同上 | 同上 |
| `wan22_5b_i2v.api.json` | 静画 → 动起来 | 同上 | 同上 |
| `wan2_1_flf2v_720p.api.json` | 首尾帧插值 | Wan2.1 FLF2V-14B fp8 | ≥20GB 空闲（要空机） |
| `frame_interp_film.api.json` | 补帧（RIFE/FILM） | 22.7~68.9 MB | <1.5GB，随时 |
| `seedvr2_3b_upscale.api.json` | 放大到 1080p（时间一致） | SeedVR2 3B int8 + 专用 VAE | 6~9GB |
| `_official/` | Comfy-Org 官方 blueprint 原件（含子图格式） | — | 参考用 |

工具：

```bash
# 只读校验（不占显存）
python3 validate_workflow.py --base http://127.0.0.1:8188

# 提交并下载产物
python3 run_workflow.py wan22_5b_t2v.api.json --set 5:text='你的画面描述' --set 7:length=49

# 分档下载模型（先 --check 再 --run）
./fetch_models.sh --check mvp post
./fetch_models.sh --run mvp
```
