#!/usr/bin/env bash
# 把 DGX 上 ComfyUI-Inspyrenet-Rembg 節點的 Remover() 改為強制 CPU。
#
# 理由：DGX driver 450.216.04 (CUDA 11.0) 下，InSPyReNet 在 ComfyUI 進程內跑 GPU 會撞
#   `CUDA error: API call is not supported in the installed CUDA driver`（standalone/CPU 皆 OK，
#   屬 env-specific）。v1 Route A device 策略採 CPU 保底（見 P1 設計規格 §8.6 R-e）。
#
# 冪等：已 patch 則跳過。可重現：節點被 git pull 覆蓋後重跑此腳本。
# 在 DGX 上執行：bash patch_rembg_cpu.sh   （或本機 ssh ... 'bash -s' < patch_rembg_cpu.sh）
set -euo pipefail
NODE="/root/ComfyUI/custom_nodes/ComfyUI-Inspyrenet-Rembg/Inspyrenet_Rembg.py"

[ -f "$NODE" ] || { echo "❌ 找不到節點：$NODE"; exit 1; }

if grep -q 'device="cpu"' "$NODE"; then
  echo "ℹ️  已 patch（device=\"cpu\" 已存在），跳過"
  exit 0
fi

cp -n "$NODE" "${NODE}.orig"   # 首次備份原檔（-n 不覆蓋既有備份）
# Remover()        -> Remover(device="cpu")
# Remover(jit=True)-> Remover(jit=True, device="cpu")
sed -i \
  -e 's/Remover()/Remover(device="cpu")/g' \
  -e 's/Remover(jit=True)/Remover(jit=True, device="cpu")/g' \
  "$NODE"

if grep -q 'device="cpu"' "$NODE"; then
  echo "✅ patch 完成（Remover 強制 CPU）。原檔備份：${NODE}.orig"
  echo "   套用後須重啟 ComfyUI 才生效（節點 import 時建 Remover）。"
else
  echo "❌ patch 後仍找不到 device=\"cpu\"，請手動檢查 $NODE"; exit 1
fi
