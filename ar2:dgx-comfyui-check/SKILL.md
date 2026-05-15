---
name: ar2:dgx-comfyui-check
description: Use when the user asks to "log into DGX", "登入 DGX", "連 DGX", "看 DGX 模型", "DGX 有什麼 LoRA", "盤點 DGX ComfyUI", "檢查 DGX", or wants to verify the DGX (192.168.5.27) GPU machine is healthy and inventory installed ComfyUI models. SSH-connects, runs 3-prong health check (GPU/process/API), inventories 13 model categories, compares against expected core models, and reports storage + version summary. NOT for: generating images, training LoRA, downloading models.
---

# ar2:dgx-comfyui-check

DGX GPU machine 連線 + ComfyUI 模型盤點 skill。家族 `ar2:dgx-*` 的第一個 skill。

## 這個 skill 做什麼

1. SSH 登入 DGX (`192.168.5.27:7915`)
2. 三項健康檢查
   - GPU：`nvidia-smi --query-gpu=...`
   - ComfyUI process：`pgrep -f "python.*ComfyUI/main.py"`
   - ComfyUI API：`curl http://localhost:8199/system_stats`
   - **Reconciliation**：API 為 ground truth。若 API ✅ 但 pgrep 找不到（ComfyUI 用 launcher / conda / container 啟動），process 檢查降為 informational（msg 加 `(API live, pgrep no match: ...)` 註記），不再標 ❌。
3. 盤點 `/root/ComfyUI/models/` 下的 13 個分類
4. 對照 `references/models.md` 的「核心必備清單」（❌ 缺失、⚠️ 多餘）
5. 環境摘要：output/ 與 lora_training/ 統計、ComfyUI commit、custom_nodes commits、磁碟剩餘
6. 寫 cache 到 `~/.cache/ar2-dgx-comfyui-check/last-inventory.json`（下次跑會顯示「上次盤點 X 分鐘前」）

## 何時觸發

- 「登入 DGX」「連 DGX」「看 DGX 狀態」「檢查 DGX」
- 「DGX 上有什麼模型」「DGX 的 LoRA 有哪些」
- 產圖 / 訓練前的環境驗證

## 何時 **不** 觸發（會走別的 skill）

- 產圖 → `ar2:dgx-comfyui-gen`（未來）
- LoRA 訓練 → `ar2:dgx-comfyui-train`（未來）
- 下載 / 安裝模型 → 其他 skill 或手動處理

## 如何執行

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-check/scripts/inspect.py
```

Exit codes：
- `0` 一切正常
- `1` 連不上 DGX（ping fail）
- `2` 連得上但有問題（健康檢查失敗 或 核心模型缺失）

## 預期輸出（示例）

```
== ar2:dgx-comfyui-check @ 192.168.5.27 ==
(上次盤點：5/14 21:00, 13 分鐘前)

🟢 Health
  GPU          ✅ Tesla V100-DGXS-32GB (used 1024 MiB / free 31510 MiB)
  ComfyUI proc ✅ pid 12345
  ComfyUI API  ✅ /system_stats OK

📦 Models (13 cats / 47 files / 87.3GB)
  ❌ clip               0 files,        —  ← missing: clip_l.safetensors, t5xxl_fp8_e4m3fn.safetensors
  ⚠️ controlnet         2 files,    1.8GB  ← ⚠ 1 unexpected

  ✅ (11 個分類全綠 → 折成統計列)
     checkpoints        3 files, 19.4GB
     diffusion_models   1 files, 17.2GB
     ...

📊 Environment
  ComfyUI @ a1b2c3d
  custom_nodes: ComfyUI-PuLID-Flux-Enhanced@f4e5d6, comfyui-reactor-node@789abc
  output/  42 entries, 8.7GB · lora_training/ 3 entries, 1.2GB · free 723G
==
```

## 檔案結構

```
ar2:dgx-comfyui-check/
├── SKILL.md              ← this file
├── config.py             ← 連線參數（不入 git，chmod 600）
├── .gitignore            ← 排除 config.py、__pycache__
├── hooks/pre-commit      ← 攔 PASSWORD literal commit
├── scripts/
│   ├── ssh_client.py     ← SSH/SCP/tunnel 層
│   ├── health.py         ← 三項健康檢查
│   └── inspect.py        ← 主入口（呼叫此檔）
└── references/
    ├── connection.md     ← 故障診斷樹
    └── models.md         ← 13 分類 + 核心必備
```

## 家族（ar2:dgx-*）

| Skill | 狀態 | 用途 |
|-------|------|------|
| `ar2:dgx-comfyui-check` | ✅ 本案 | 健康檢查 + 模型盤點 |
| `ar2:dgx-comfyui-gen` | 🔜 規劃中 | 產圖 |
| `ar2:dgx-comfyui-train` | 🔜 規劃中 | LoRA 訓練 |

三個 skill 各有獨立 `config.py`（連線資訊重複，達門檻才抽 `ar2:dgx-base`）。`scripts/ssh_client.py` 設計時已預留 tunnel reuse，讓家族 skill 連續呼叫不會重複 SSH。

## 安全約束

⛔ **此 skill 不可 publish 到 ClawHub、不可 push 到任何公開 / 共享 repo**。
`config.py` 含明文密碼，是基於「DGX 在私網 + 本機個人使用」的信任模型。

技術防呆：
- `.gitignore` 第一行就是 `config.py`
- `hooks/pre-commit` 偵測 PASSWORD literal commit
- 安裝後 `chmod 600 config.py`

密碼旋轉：先改 DGX → 改 `config.py` → 跑本 skill 確認 → （未來）同步改家族其他 skill。

## 故障排除

連不上 / 失敗時 → 看 `references/connection.md` 的故障樹（IP 不通 / port 阻塞 / 認證失敗 / sshpass 缺失 / ComfyUI 不在 / models dir 不存在 → 各自不同對應）。
