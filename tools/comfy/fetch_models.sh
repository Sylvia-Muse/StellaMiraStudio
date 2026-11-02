#!/usr/bin/env bash
# 下载 ComfyUI 视频模型到 GPU 机器（100.99.5.35）。
#
#   ./fetch_models.sh --check mvp          # 只做 HEAD 检查，不下载（默认动作是 check）
#   ./fetch_models.sh --run mvp            # 真下载（可断点续传）
#   ./fetch_models.sh --run post mvp-gguf  # 多个档一起
#
# 档位：
#   mvp        Wan2.2 TI2V-5B fp16 全家桶（18.15 GB）—— 一条命令就能出片
#   mvp-gguf   GGUF Q4 版（11.58 GB）—— 显存只剩 6~7GB 时用（需先装 ComfyUI-GGUF）
#   post       补帧 + 放大（3.9 GB）—— 让片子到 1080p30 不抖
#   flf2v      首尾帧 14B（23.4 GB）—— 只在 GPU 空出来时用
#   hero       I2V-A14B fp8 + 4步 LoRA（37.7 GB）—— 只在 GPU 空出来时用
#
# 设计说明：
#   * 大文件走 ModelScope（实测 ~3.2MB/s），小文件走 hf-mirror（~0.28MB/s，只适合 <100MB）。
#   * huggingface.co 在本机**不通**，别直接 hf download。
#   * 目标目录用环境变量覆盖：COMFY_DIR（默认 ~/Server/ComfyUI）
set -uo pipefail

COMFY_DIR="${COMFY_DIR:-$HOME/Server/ComfyUI}"
MS="https://modelscope.cn/models"
HFM="https://hf-mirror.com"

MODE="check"
TIERS=()
for arg in "$@"; do
  case "$arg" in
    --run) MODE="run" ;;
    --check) MODE="check" ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) TIERS+=("$arg") ;;
  esac
done
[ ${#TIERS[@]} -eq 0 ] && TIERS=(mvp)

# 每条：档位|URL|落到 models/ 下的子目录|文件名|大小说明
ITEMS=(
  # ---- mvp: Wan2.2 TI2V-5B ----
  "mvp|$MS/Comfy-Org/Wan-2.2/resolve/master/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors|diffusion_models|wan2.2_ti2v_5B_fp16.safetensors|10.00 GB"
  "mvp|$MS/Comfy-Org/Wan-2.2/resolve/master/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors|text_encoders|umt5_xxl_fp8_e4m3fn_scaled.safetensors|6.74 GB"
  "mvp|$MS/Comfy-Org/Wan-2.2/resolve/master/split_files/vae/wan2.2_vae.safetensors|vae|wan2.2_vae.safetensors|1.41 GB"
  # ---- mvp-gguf: 低显存版 ----
  "mvp-gguf|$MS/QuantStack/Wan2.2-TI2V-5B-GGUF/resolve/master/Wan2.2-TI2V-5B-Q4_K_M.gguf|unet|Wan2.2-TI2V-5B-Q4_K_M.gguf|3.43 GB"
  "mvp-gguf|$MS/QuantStack/Wan2.2-TI2V-5B-GGUF/resolve/master/VAE/Wan2.2_VAE.safetensors|vae|Wan2.2_VAE.safetensors|1.41 GB"
  # ---- post: 补帧 + 放大 ----
  "post|$HFM/Comfy-Org/Frame-Interpolation/resolve/main/frame_interpolation/rife_v4.26.safetensors|frame_interpolation|rife_v4.26.safetensors|22.7 MB"
  "post|$HFM/Comfy-Org/Frame-Interpolation/resolve/main/frame_interpolation/film_net_fp16.safetensors|frame_interpolation|film_net_fp16.safetensors|68.9 MB"
  "post|$HFM/Comfy-Org/SeedVR2/resolve/main/diffusion_models/seedvr2_3b_int8_convrot.safetensors|diffusion_models|seedvr2_3b_int8_convrot.safetensors|3.46 GB"
  "post|$HFM/Comfy-Org/SeedVR2/resolve/main/vae/seedvr2_ema_vae_fp16.safetensors|vae|seedvr2_ema_vae_fp16.safetensors|0.50 GB"
  # ---- flf2v: 首尾帧 14B ----
  "flf2v|$MS/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/master/split_files/diffusion_models/wan2.1_flf2v_720p_14B_fp8_e4m3fn.safetensors|diffusion_models|wan2.1_flf2v_720p_14B_fp8_e4m3fn.safetensors|16.40 GB"
  "flf2v|$MS/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/master/split_files/vae/wan_2.1_vae.safetensors|vae|wan_2.1_vae.safetensors|0.25 GB"
  # ---- hero: I2V-A14B + 4 步 LoRA ----
  "hero|$MS/Comfy-Org/Wan-2.2/resolve/master/split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors|diffusion_models|wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors|14.29 GB"
  "hero|$MS/Comfy-Org/Wan-2.2/resolve/master/split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors|diffusion_models|wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors|14.29 GB"
  "hero|$MS/Comfy-Org/Wan-2.2/resolve/master/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors|loras|wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors|1.23 GB"
  "hero|$MS/Comfy-Org/Wan-2.2/resolve/master/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors|loras|wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors|1.23 GB"
)

sel() { # sel <tier>
  local t="$1"; for it in "${ITEMS[@]}"; do
    IFS='|' read -r tier url sub name size <<<"$it"
    [ "$tier" = "$t" ] && printf '%s\t%s\t%s\t%s\n' "$url" "$sub" "$name" "$size"
  done
}

fail=0
for tier in "${TIERS[@]}"; do
  echo "=== 档位: $tier  ($( [ "$MODE" = run ] && echo 下载 || echo 仅检查 ))"
  while IFS=$'\t' read -r url sub name size; do
    [ -z "${url:-}" ] && continue
    dest="$COMFY_DIR/models/$sub"
    if [ -s "$dest/$name" ]; then
      echo "  [已有] $sub/$name"
      continue
    fi
    if [ "$MODE" = check ]; then
      code=$(curl -sIL -o /dev/null -w '%{http_code}' --max-time 25 "$url")
      printf '  [%s] %-56s %s\n' "$code" "$sub/$name" "$size"
      [ "$code" = "200" ] || [ "$code" = "206" ] || fail=1
    else
      mkdir -p "$dest"
      echo "  → $sub/$name ($size)"
      if curl -L -C - --retry 5 --retry-delay 3 -o "$dest/$name" "$url"; then
        echo "    ok $(du -h "$dest/$name" | cut -f1)"
      else
        echo "    FAILED: $url"; fail=1
      fi
    fi
  done < <(sel "$tier")
done

if [ "$MODE" = check ]; then
  echo
  echo "检查完毕。全部 200/206 才算 URL 可用；确认无误后用 --run 真下载。"
  echo "ComfyUI 模型目录：$COMFY_DIR/models"
fi
exit $fail
