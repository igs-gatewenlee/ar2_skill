---
name: dgx-comfyui-gen
description: Use when the user asks to "產圖", "用 ComfyUI 生圖", "用 Flux 生 N 張", "generate image", or wants to run a ComfyUI workflow on DGX (192.168.5.27). Supports bundled Flux workflows (flux_basic, flux_pulid) or caller-supplied `--workflow path.json`. Auto-injects prompt/seed/steps/batch via class_type convention. Submits via /prompt API through SSH tunnel, polls /history until done, SCP-downloads images to ./outputs/ar2-dgx-comfyui-gen/{date}_{tag}/. NOT for: model inventory (use ar2:dgx-comfyui-check), LoRA training (use ar2:dgx-comfyui-train), editing workflow JSON.
---

# ar2:dgx-comfyui-gen

DGX ComfyUI 工作流執行 skill。家族 `ar2:dgx-*` 第二個 skill。

## 這個 skill 做什麼

1. 載入 workflow JSON（bundled `flux_basic` / `flux_pulid` 或 `--workflow` 自帶）
2. 替換參數（prompt / negative / seed / steps / batch / face_ref）—— `workflow_params.py` 用 class_type convention 自動找節點
3. 自動 patch `LoadImage` / `SaveImage` 對齊 `{date}_{tag}/` subdir
4. （opt-in `--check`）pre-flight 呼叫 `ar2:dgx-comfyui-check`
5. 確保 SSH tunnel（`localhost:8199 → DGX:8199`），既存就 reuse
6. 上傳 `--face-ref`（若有）到 `/root/ComfyUI/input/{subdir}/`
7. 生成 UUID `client_id`，POST 到 `http://localhost:8199/prompt`，回傳 `prompt_id` + queue position
8. Poll `/history/{prompt_id}` 直到 outputs 出現（每 1 秒）
9. SCP `/root/ComfyUI/output/{subdir}/*` → `./outputs/ar2-dgx-comfyui-gen/{subdir}/`
10. 回報結果 + 寫 cache `~/.cache/ar2-dgx-comfyui-gen/last-run.json`

## 何時觸發

- 「產 X 圖」「跑 ComfyUI workflow」「generate image」
- 「用 Flux 生 5 張，prompt: ...」
- 「用 character_xxx face_ref 產一張」

## 何時 **不** 觸發

- 想盤點模型 → `ar2:dgx-comfyui-check`
- 想訓練 LoRA → `ar2:dgx-comfyui-train`
- 想設計 / 編輯 workflow JSON → 自己手改、不在本 skill 範圍

## 如何執行

### 基本（純 text-to-image）

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/generate.py \
  --prompt "a serene mountain landscape at sunset" \
  --batch 4 \
  --tag landscape_test
```

### 加 face reference（PuLID 一致性臉部）

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/generate.py \
  --workflow flux_pulid \
  --face-ref ./refs/character.png \
  --prompt "the character in a coffee shop, anime style" \
  --tag char_coffee
```

### 帶 pre-flight 環境檢查

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/generate.py \
  --check \
  --prompt "..." \
  --tag verified
```

### 用自帶 workflow JSON

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/generate.py \
  --workflow /path/to/my_workflow.json \
  --prompt "..."
```

## CLI 參數

| Flag | 預設 | 說明 |
|------|------|------|
| `--prompt` | **必填** | 正向 prompt |
| `--negative-prompt` | (空) | 負向 prompt（若 workflow 有第二個 CLIPTextEncode） |
| `--workflow` | `flux_basic` | bundled name 或 absolute path |
| `--seed` | 隨機 32-bit int | KSampler / RandomNoise 的 seed |
| `--steps` | workflow 預設 | 採樣步數 |
| `--batch` | workflow 預設 | 一次產幾張 |
| `--face-ref` | (無) | 本地圖檔路徑；上傳到 DGX、所有 LoadImage 套用 |
| `--tag` | `{HHMMSS}_{4hex}` | run 識別 tag；最終 subdir = `{YYYYMMDD}_{tag}` |
| `--check` | off | pre-flight 跑 `-check` |
| `--poll-interval` | 1.0 | 查 /history 間隔（秒） |
| `--timeout` | 1800 | 最久等多久（秒） |

## Exit codes

- `0` 成功，圖已下載
- `1` 連線 / 載入 / 上傳失敗（看 references/connection.md）
- `2` workflow 被 ComfyUI 拒絕 / 完成但無 output

## 預期輸出

```
== ar2:dgx-comfyui-gen @ 192.168.5.27 ==
  workflow: flux_basic.json
  tag: landscape_test
  subdir: 20260514_landscape_test
  seed: 1234567890

Ensuring SSH tunnel...
Submitting workflow to ComfyUI...
  prompt_id: abc123def456...
  queue position: running
  ... still running (5.0s)
  ... still running (10.1s)
Downloading 4 image(s) to /Users/.../outputs/ar2-dgx-comfyui-gen/20260514_landscape_test ...

✅ Done in 14.2s
  files: 4
    /Users/.../outputs/ar2-dgx-comfyui-gen/20260514_landscape_test/img_00001_.png
    /Users/.../outputs/ar2-dgx-comfyui-gen/20260514_landscape_test/img_00002_.png
    ...
  prompt_id: abc123def456
  seed: 1234567890
  workflow: flux_basic.json
```

## 檔案結構

```
ar2:dgx-comfyui-gen/
├── SKILL.md                       ← this file
├── config.py                      ← 連線參數 + DGX/本地路徑（chmod 600）
├── .gitignore                     ← 排除 config.py、__pycache__、outputs/
├── hooks/pre-commit               ← 攔 PASSWORD literal
├── scripts/
│   ├── ssh_client.py              ← 移植自 -check（含 ensure_tunnel）
│   ├── comfyui_api.py             ← submit_prompt / wait / list_output_files
│   ├── workflow_params.py         ← class_type convention 注入器
│   └── generate.py                ← 主入口
├── references/
│   ├── connection.md              ← 故障診斷（移植自 -check）
│   ├── workflow-api.md            ← /prompt /history client_id 規約
│   └── workflow-schema.md         ← class_type convention 詳細對照
└── workflows/
    ├── flux_basic.json            ← Flux 純 text2img（無 LoadImage）
    ├── flux_basic.requirements.md ← 必備模型清單
    ├── flux_pulid.json            ← Flux + PuLID 臉部一致性
    └── flux_pulid.requirements.md ← 必備模型 + custom_node 清單
```

## 家族 ar2:dgx-*

| Skill | 狀態 | 與本 skill 的關係 |
|-------|------|-------------------|
| `ar2:dgx-comfyui-check` | ✅ 已實作 | 可作 `-gen` 的 opt-in pre-flight (`--check`) |
| `ar2:dgx-comfyui-gen` | ✅ 本 skill | 執行工作流 |
| `ar2:dgx-comfyui-train` | 🔜 規劃中 | 訓練完 LoRA → `models/loras/` → 本 skill 用名引用 |

三個 skill 透過 DGX 上的檔案系統交流，不互相 import；共用 tunnel 規約讓家族 skill 串連使用時不重複 SSH。

## 安全約束

⛔ **此 skill 不可 publish 到 ClawHub、不可 push 到任何公開 / 共享 repo**。
`config.py` 含明文密碼。技術防呆：`.gitignore` + `hooks/pre-commit` + `chmod 600`。

`-gen` 特有的提醒：
- 上傳 `--face-ref` 前確認本地檔案不含敏感個資 / 版權素材
- `./outputs/` 落地的圖檔可能含可辨識內容；自行控制該目錄不入 git

## 故障排除

- 連不上 → `references/connection.md` 故障樹
- workflow 被拒（node_errors）→ 跑 `-check` 比對 `.requirements.md` 模型清單
- 想知道哪個節點要對應哪個參數 → `references/workflow-schema.md`
- ComfyUI 卡住 → SSH 上 DGX 查 `nvidia-smi` 與 `tail -100 /root/ComfyUI/output.log`
