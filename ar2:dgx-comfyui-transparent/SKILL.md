---
name: ar2:dgx-comfyui-transparent
description: Use when the user asks to "產透明素材", "去背素材", "遊戲透明 PNG", "transparent game asset", "produce sprite/icon with alpha", or wants ComfyUI 產出帶真實 Alpha 的遊戲素材（去背路線 InSPyReNet / LayerDiffuse 路線）在 DGX (192.168.5.27)。Route A（去背）為 v1 交付；Route B（LayerDiffuse semi VFX）PoC-pending。NOT for：一般產圖（用 ar2:dgx-comfyui-gen）、模型盤點（ar2:dgx-comfyui-check）、LoRA 訓練（ar2:dgx-comfyui-train）。
---

# ar2:dgx-comfyui-transparent

把 ComfyUI 產出的圖轉成遊戲可直接用、帶真實 Alpha 的透明素材，並自動 QC。能力包（非獨立 runtime）：ComfyUI 端只負責 GPU 生成/去背，本地 Python 負責 alpha 修正/trim/深淺底 preview/QC。

## 三條路線

| 路線 (route) | 用途 | 狀態 |
|------|------|------|
| **A 去背 (`rembg`, InSPyReNet)** | 硬邊物件：icon / Symbol / 金幣 / 按鈕 / 道具 | ✅ v1 交付（端到端實測 QC pass） |
| **C 加色特效 (`vfx_additive`, luminance-matte)** | 發光類半透明：光暈 / 魔法光 / 火焰 / 能量 / 發光邊 / 粒子 | ✅ v1 交付（黑底產圖→亮度當 alpha，不需 LayerDiffuse；端到端實測真半透明） |
| **B LayerDiffuse (`layerdiffuse`, semi VFX)** | 吸收/折射類半透明：煙霧 / 玻璃 | ⚠️ PoC-pending（DGX 缺 LayerDiffuse 節點 + SDXL base + layer_model） |

> 半透明選路：**發光/加色** → Route C（現成、零額外 infra）；**煙霧/玻璃** → Route B（需設置 LayerDiffuse）。

## 如何使用

**單發 PoC（Route A）**：
```bash
python3 scripts/transparent.py --poc \
  --prompt "single gold coin, game icon, transparent background" \
  --slug gold_coin --category symbol --asset-type opaque --size 512
```
→ Flux 產圖 → InspyrenetRembg(CPU) 去背 → 雙 SaveImage(source/mask) → 下載 → 本地 compose_rgba(straight) → alpha-fix → trim → QC report。輸出 `outputs/ar2-dgx-comfyui-transparent/{date}_{tag}/{category}_{slug}/`。

**批次（plan 驅動）**：在 plan outline.md frontmatter 加 `transparent_assets` block（route/asset_type per slug），用 `ar2:dgx-comfyui-gen --plan` 跑（gen 依 route dispatch + 掛本地 postprocess hook）。

## DGX 前置（一次性）

driver 450/CUDA 11.0 下 InSPyReNet 在 ComfyUI 進程內跑 GPU 會撞 `CUDA error: API not supported`；v1 採 **CPU 去背**保底（見 P1 設計規格 §8.6 R-e）。安裝：
```bash
# 1. 裝去背節點 + 依賴
cd /root/ComfyUI/custom_nodes && git clone https://github.com/john-mnz/ComfyUI-Inspyrenet-Rembg.git
python3 -m pip install --break-system-packages transparent-background
# 2. patch 成 CPU（冪等，見 scripts/patch_rembg_cpu.sh）→ 重啟 ComfyUI
```
> ⚠️ Flux GPU 生成本身需 DGX GPU 正常（driver/CUDA 相容）。若 CLIPTextEncode 也撞 CUDA driver 錯，屬 DGX infra 問題（影響整條 card-gen），非本 skill。

## 檔案結構

```
scripts/
  transparent_postprocess.py  本地純函式：compose_rgba(straight) / un_premultiply / edge_bleed / fix_alpha / auto_trim / make_previews
  qc.py + qc_thresholds.py     QC engine（midtone 反向分流 opaque/semi、report.json）
  asset_spec.py                版本遞增不覆蓋 + 檔名 + category 保留字校驗
  transparent.py               單發 PoC CLI
  patch_rembg_cpu.sh           去背節點 CPU patch（冪等）
workflows/route_a_rmbg.json    Route A 節點圖（雙 SaveImage source/mask 子目錄前綴）
tests/                         fixture-driven 本地測試
```

## ⚠️ 跨 skill 部署約束（M-2）

本 skill 的批次路徑依賴 `ar2:dgx-comfyui-gen`（per-route dispatch + postprocess hook）與 `ar2:dgx-comfyui-plan`（transparent_assets schema）。**gen / plan / transparent 三者須同 commit 部署**——`plan_schema.SCHEMA_VERSION` 與 gen `plan_loader._REQUIRED_SCHEMA_VERSION` 有 fail-loud 版本 guard，版本不一致會在 import 階段 raise。

## 安全約束

⛔ 不可 publish / push 到公開 repo（連線 config 含明文密碼，承襲家族信任模型）。
