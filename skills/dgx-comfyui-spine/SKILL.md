---
name: dgx-comfyui-spine
description: Use when the user asks to "把角色拆件 / 切成部件 / 做 Spine 部件包 / 角色多部件切件 / 產 part PNG + manifest / cutout 部件包" —— 把一張角色圖半自動切成帶 alpha 的部件 PNG + manifest.json（bbox/pivot/draw_order），供下游骨架/Spine 動畫用，在 DGX (192.168.5.27) 上跑 Flux 生成 + SAM 精修。NOT for：一般產圖（用 ar2:dgx-comfyui-gen）、單張物件去背/透明素材（用 ar2:dgx-comfyui-transparent）、模型盤點（ar2:dgx-comfyui-check）、LoRA 訓練（ar2:dgx-comfyui-train）。
---

# ar2:dgx-comfyui-spine

把一張角色圖**半自動**切成「部件包」：帶真實 alpha 的部件 PNG + `manifest.json`（bbox/pivot/rotation/draw_order）。中性資產，下游接骨架綁定 / Spine / 動畫由人或外部工具做。能力包（非獨立 runtime）：ComfyUI 端負責 GPU 生成 + SAM 精修，本地 Python 負責 compose/裁件/manifest/QC。

## scope 三道牆（硬邊界）

停在「部件包」中性資產，**不碰**：① 骨架綁定 / Spine 檔（.json/.skel）/ 程序動畫 / mesh 變形；② 補洞（inpaint 語意不可控，PoC 已否證）；③ LayerDiffuse 分層（DGX 缺節點+SDXL）。

## v1 部件範圍（已 PoC 拍板）

| 納入 v1（已端到端實證可切） | 不在 v1（留 v2） |
|------|------|
| `head` / `torso` / `upper_arm_l` / `upper_arm_r` | **legs**（合併件實測覆蓋率僅 63%、衣物色彩斷層通病）、L/R 分腿（死點：大腿相連無真實邊界）、lower_arm/hand/foot（小件未測）、全自動部位定位（DGX 缺 detector/CLIPSeg/human-parser） |

> v1 是**半自動**：人標粗框 hint 在環內。SAM 是「精修器」（粗框進、貼合輪廓出），**切點/部位分界靠人標 hint**，非全自動定位。

## 5 步半自動流程

```
1. Flux star-pose 白底 reference 生成（正向 prompt，無 negative 節點避 negation trap）
2. 人對每部件標一張粗框 hint PNG（<slug>.png，白=該部件大致範圍）
3. 逐部件 SAM 精修（sam_vit_b + MaskToSEGS + SAMDetectorCombined）貼合輪廓
4. compose_rgba(straight)+edge_bleed+fix_alpha → content_bbox(padding=0) 裁出帶 alpha part PNG
5. 組 manifest.json → 8 閘 QC → qc_report.json
```

## 如何使用

```bash
python3 scripts/spine.py --character-id mychar \
  --hint-dir <dir 內含 head.png/torso.png/upper_arm_l.png/upper_arm_r.png 粗框 hint> \
  [--reference ref.png]   # 給了就跳過生成；否則用內建白底 star-pose prompt 生成
  [--prompt "..."] [--size 1024] [--seed 20260615]
```

輸出 `outputs/ar2-dgx-comfyui-spine/{date}_{character_id}/{reference.png, parts/*.png, manifest.json, qc_report.json}`。

## manifest 契約

每部件：`name`(slug) / `bbox`[x,y,w,h]（trim padding=0、(w,h) 嚴格 = part PNG 尺寸、(x,y)=reference 全圖座標）/ `pivot`{x,y,**best_effort**} / `rotation`{deg,**best_effort**} / `draw_order`(整數·**允許同層重複**，L/R 對稱件天然同層) / `source`。

> ⚠️ **pivot / rotation 是 best-effort 視覺提示**（給人在 Spine Editor 建 bone 參考），**不保證可程式驅動旋轉**。下游勿當硬契約 driven。

## 8 閘 QC（任一硬閘 fail 不靜默）

齊全（⊇ 4 部件）/ 命名 bijection 雙向 / manifest 數值有效 / 上肢分離 ≤5% / L/R 對稱 / 部件內破洞 / 可組回 masked-SSIM ≥0.95（獨立純依 manifest 貼回器）/ **全圖前景覆蓋率 ≥0.97**（抓「相連區漏抓」假象——部件互不重疊但聯集沒蓋滿前景，如 PoC 腿 mask 0% 重疊卻只蓋 43%）。

> 閾值全標「暫定·待多角色樣本校準」。第 8 閘分母用白底閾值法 → **限定 v1 reference 為白底**；非白底降 warn（分母近似不可信）。

## DGX 前置（一次性）

ComfyUI 需裝 **ComfyUI-Impact-Pack**（提供 SAMLoader/MaskToSEGS/SAMDetectorCombined）+ SAM 權重 `sam_vit_b_01ec64.pth`（放 `/root/ComfyUI/models/sams/`，目錄不存在先 `mkdir`）。Flux 生成需 DGX GPU 正常。check skill 不盤點 SAM 類節點，**不能靠 check 驗 SAM 在不在**（須照本段自裝）。

## 檔案結構

```
scripts/
  spine.py               單發半自動 CLI 主編排（sibling-import gen 通訊 + transparent 後處理）
  spine_sam.py           SAM 切件 workflow builder（載 sam_part.json + 注入）
  manifest_builder.py    content_bbox(padding=0) + manifest 組裝 + 校驗（純函式）
  spine_recompose.py     獨立「純依 manifest」貼回器（QC desync 偵測用，純函式）
  spine_qc.py + spine_qc_thresholds.py   8 閘 QC engine（純函式）
workflows/
  flux_starpose.json     Flux 生成圖（無 negative 節點）
  sam_part.json          單部件 SAM 精修節點圖
tests/                   fixture-driven 本地 BC 測試（DGX 無關）
```

> 無自帶 `config.py`：sibling-borrow `ar2:dgx-comfyui-gen/config.py`（連線單一來源）。共用後處理 `compose_rgba/edge_bleed/fix_alpha` sibling-import `ar2:dgx-comfyui-transparent`（不複製、不物理遷移）。

## ⚠️ 部署約束

依賴 `ar2:dgx-comfyui-gen`（ssh_client/comfyui_api/config）與 `ar2:dgx-comfyui-transparent`（transparent_postprocess）co-located 於同 plugin。三者須同 commit 部署（sibling-import 路徑依賴）。

## 安全約束

⛔ 不可 publish / push 到公開 repo（連線 config 含明文密碼，承襲家族信任模型）。
