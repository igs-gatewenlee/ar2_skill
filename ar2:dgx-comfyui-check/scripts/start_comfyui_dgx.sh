#!/usr/bin/env bash
# 啟動 DGX (192.168.5.27) 的 ComfyUI —— 正規啟動方式。
#
# ⛔ 必須帶 --disable-cuda-malloc：
#   本機 GPU driver 是 450.216.04（CUDA 11.0）。ComfyUI 預設啟用 cuda-malloc
#   （cudaMallocAsync，需 driver ≥ CUDA 11.2）。在此舊 driver 上，**所有 GPU 模型推論**
#   （Flux 產圖 / InSPyReNet 去背 / CLIPTextEncode）會撞：
#     RuntimeError: CUDA error: API call is not supported in the installed CUDA driver
#   --disable-cuda-malloc 改用 native 分配器（cudaMalloc）即正常。
#   （standalone torch op 用 native 分配器，故診斷時誤以為 GPU 沒問題——真因是 ComfyUI 預設 allocator。）
#
# 部署：scp 到 DGX /root/start_comfyui.sh，chmod +x。DGX 重啟後跑此腳本啟動 ComfyUI。
# 用法（在 DGX 上）：bash /root/start_comfyui.sh
set -euo pipefail
PORT=8199
ROOT=/root/ComfyUI

if curl -sf "http://localhost:${PORT}/system_stats" >/dev/null 2>&1; then
  echo "ℹ️  ComfyUI 已在 :${PORT} 運行，不重複啟動。"
  exit 0
fi

cd "$ROOT"
setsid bash -c "cd '$ROOT' && exec python3 main.py --port ${PORT} --listen 0.0.0.0 --disable-cuda-malloc" \
  > /root/comfyui.log 2>&1 < /dev/null &

echo "ComfyUI 啟動中（--disable-cuda-malloc）→ log: /root/comfyui.log"
for i in $(seq 1 40); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${PORT}/system_stats" 2>/dev/null)" = "200" ]; then
    echo "✅ ComfyUI up (~$((i * 3))s) @ :${PORT}"
    exit 0
  fi
  sleep 3
done
echo "⚠️  啟動逾時（120s），檢查 /root/comfyui.log"
exit 1
