# DGX 連線與故障診斷

`ar2:dgx-comfyui-check` 的連線層在出錯時，主邏輯依本檔的故障樹分流回報。

---

## 連線基礎

| 項目 | 值 |
|------|----|
| Host | `192.168.5.27` |
| SSH Port | `7915` |
| User | `root` |
| Auth | 僅接受 password（伺服器設定強制） |
| ComfyUI Port | `8199`（非標準 8188） |

**本機需安裝** `sshpass`：

```bash
brew install esolitos/ipa/sshpass
```

---

## 標準 SSH 指令模板

```bash
sshpass -p 'root' ssh \
  -o PubkeyAuthentication=no \
  -o PreferredAuthentications=password \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -p 7915 root@192.168.5.27 "$REMOTE_CMD"
```

兩個 `-o` 強制 flag **缺一不可**，否則 SSH client 會先嘗試 publickey 並被拒，沒機會試 password。

---

## SCP 模板

```bash
# 下載
sshpass -p 'root' scp \
  -o PubkeyAuthentication=no \
  -o PreferredAuthentications=password \
  -P 7915 root@192.168.5.27:/remote/path /local/path

# 上傳
sshpass -p 'root' scp \
  -o PubkeyAuthentication=no \
  -o PreferredAuthentications=password \
  -P 7915 /local/path root@192.168.5.27:/remote/path
```

注意：SCP 用 `-P`（大寫）指定 port，SSH 用 `-p`（小寫）。

---

## 故障樹

```
連線失敗 / 操作失敗
│
├─ "ping 192.168.5.27 timeout"
│    → 網路不通；診斷：
│      • 確認本機在公司 VPN 內（DGX 在私網）
│      • 試 `ping 192.168.5.1`（gateway）
│      • 若 gateway 通 DGX 不通 → DGX 開機狀態 / 網路設定
│
├─ "ssh: connect to host port 7915: Connection refused"
│    → port 阻塞或服務沒在跑
│    → 診斷：`nc -zv 192.168.5.27 7915`
│    → 若 nc 也失敗 → 防火牆 / DGX SSH 服務未啟動
│
├─ "Permission denied (publickey,password)"
│    → 99% 原因：缺 `-o PreferredAuthentications=password`
│    → 1% 原因：密碼被改了，跟 DGX 管理者確認
│
├─ "sshpass: command not found"
│    → 本機未裝 sshpass
│    → 安裝：`brew install esolitos/ipa/sshpass`
│
├─ ComfyUI process not found（pgrep 空）
│    → ComfyUI 沒在跑
│    → 手動啟動（在 DGX 端）：
│      cd /root/ComfyUI && nohup python3 main.py \
│        --port 8199 --listen 0.0.0.0 \
│        > /root/comfyui.log 2>&1 &
│
├─ ComfyUI API not responsive（curl 失敗）
│    → process 在跑但 API 沒回應
│    → 可能原因：剛啟動還沒 ready / hang 住 / port 被別的服務占
│    → 診斷：`ssh ... 'tail -50 /root/comfyui.log'`
│
└─ models dir not found
     → ComfyUI 安裝損壞或路徑改了
     → 診斷：`ssh ... 'ls /root/ComfyUI/'`
```

---

## SSH Tunnel（家族共用 · v1 不開）

未來 `ar2:dgx-comfyui-gen` 需要本機呼叫 ComfyUI API，會用背景 tunnel：

```bash
sshpass -p 'root' ssh -fN \
  -o PubkeyAuthentication=no \
  -o PreferredAuthentications=password \
  -L 8199:localhost:8199 \
  -p 7915 root@192.168.5.27
```

`ssh_client.py` 的 `ensure_tunnel()` 在第一次呼叫時建立，後續 skill 偵測既存 tunnel（`lsof -i:8199`）便 reuse，結束時**不主動 kill**，讓家族其他 skill 接著用。

---

## DGX 端目錄速查

| 用途 | 路徑 |
|------|------|
| ComfyUI 根 | `/root/ComfyUI/` |
| 模型 | `/root/ComfyUI/models/{checkpoints,loras,vae,clip,clip_vision,pulid,...}/` |
| 輸出（產圖） | `/root/ComfyUI/output/` |
| 輸入（face refs 等） | `/root/ComfyUI/input/` |
| 自訂 nodes | `/root/ComfyUI/custom_nodes/` |
| LoRA 訓練工作區 | `/root/lora_training/` |

## ⛔ 啟動 ComfyUI（重啟後必讀）

DGX 重啟後須用 **`/root/start_comfyui.sh`** 啟動 ComfyUI（源碼：`scripts/start_comfyui_dgx.sh`），**不可裸跑 `python3 main.py`**。

原因：本機 GPU driver 為 **450.216.04（CUDA 11.0）**。ComfyUI 預設啟用 cuda-malloc（`cudaMallocAsync`，需 driver ≥ CUDA 11.2），此舊 driver 不支援 → **所有 GPU 模型推論**（Flux 產圖 / 去背 / CLIPTextEncode）撞：

```
RuntimeError: CUDA error: API call is not supported in the installed CUDA driver
```

啟動腳本已帶 **`--disable-cuda-malloc`**（改 native 分配器）解決。

> ⚠️ 診斷陷阱：standalone torch op（matmul/conv/fp8）用 native 分配器，故單測「GPU 正常」會誤導——真因是 ComfyUI 進程的預設 allocator。`nvidia-smi`/SSH 正常 ≠ GPU 推論正常。
>
> 自動開機啟動（可選）：可加 systemd unit 或 `@reboot` cron 跑此腳本，免重啟後手動啟動。
