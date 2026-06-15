---
name: dgx-comfyui-spine
description: Use when the user asks to "把角色拆件 / 切成部件 / 做 Spine 部件包 / 角色多部件切件 / 產 part PNG + manifest / cutout 部件包" —— 把一張角色圖半自動切成帶 alpha 的部件 PNG + manifest.json（bbox/pivot/draw_order），供下游骨架/Spine 動畫用，在 DGX (192.168.5.27) 上跑 Flux 生成 + SAM 精修。NOT for：一般產圖（用 ar2:dgx-comfyui-gen）、單張物件去背/透明素材（用 ar2:dgx-comfyui-transparent）、模型盤點（ar2:dgx-comfyui-check）、LoRA 訓練（ar2:dgx-comfyui-train）。
---

# ar2:dgx-comfyui-spine

把一張角色圖**半自動**切成「部件包」：帶真實 alpha 的部件 PNG + `manifest.json`（bbox/pivot/rotation/draw_order）。中性資產，下游接骨架綁定 / Spine / 動畫由人或外部工具做。能力包（非獨立 runtime）：ComfyUI 端負責 GPU 生成 + SAM 精修，本地 Python 負責 compose/裁件/manifest/QC。

## scope 三道牆（硬邊界）

停在「部件包」中性資產，**不碰**：① 骨架綁定 / Spine 檔（.json/.skel）/ 程序動畫 / mesh 變形；② 補洞（inpaint 語意不可控，PoC 已否證）；③ LayerDiffuse 分層（DGX 缺節點+SDXL）。

## 部件範圍

- **QC 必備（gate1 分母）**：`head / torso / upper_arm_l / upper_arm_r`（`EXPECTED_PARTS`）。
- **可額外切（hint-dir 放對應 hint 即切）**：`skirt / leg_l / leg_r / legs / lower_arm_* / hand_* / foot_*` 等任意 slug。hintfg 在 **hint 邊界**切，故 **L/R 分腿 OK**（在中線切，不需 SAM 要的真實邊界 → SAM 的「大腿相連死點」對 hintfg 不成立）；多色部件（頭=髮+膚、穿衣）也不漏色。
- **仍不適**：全自動部位定位（半自動：切點/部位分界靠人標 hint）；非白底 reference（hintfg 前景判定靠白底）。

> 半自動：人標粗框 hint 在環內。預設 **hintfg**（part = hint ∩ 白底前景）；`--method sam` 為非白底/自動邊精修選項。

## 5 步半自動流程

```
1. Flux star-pose 白底 reference 生成（正向 prompt，無 negative 節點避 negation trap）
2. 人對每部件標一張粗框 hint PNG（<slug>.png，白=該部件大致範圍）
3. 逐部件切件：
   • 預設 hintfg —— part = hint ∩ 白底前景（純本地、無 DGX；多色部件不漏、瘦件不 over-grab）
   • --method sam —— SAM 精修（非白底 / 需自動邊精修時；單 seed 跨不過色彩斷層，白底不建議）
4. edge_bleed + fix_alpha 邊緣羽化 → content_bbox(padding=0) 裁出帶 alpha part PNG
5. 組 manifest.json → 8 閘 QC → qc_report.json
```

> ⚠️ **切件 primitive（demo 實證）**：白底 reference 用 **hintfg**（hint 定區域、白底前景定 alpha）最穩——SAM 單 seed 對「頭=髮+膚、穿衣=衣+膚」多色部件會漏一色，對瘦件會 over-grab 整身。SAM 對白底是過度設計（無內部自然邊可 snap），故降為 `--method sam` 選項。hintfg 前提：reference 須白底。

## 如何使用

```bash
python3 scripts/spine.py --character-id mychar \
  --hint-dir <dir 內放每部件一張 <slug>.png 粗框 hint（必備 4 件 + 可加 skirt/leg_l/leg_r…）> \
  [--reference ref.png]   # 給了就跳過生成（+白底 hintfg → 整條切件零 DGX）；否則用內建白底 star-pose prompt 生成
  [--method hintfg|sam] [--dilate 16] [--prompt "..."] [--size 1024] [--seed 20260615]
```

- `--dilate N`：關節 overlap 帶（各部件外擴 N px 夾前景，相鄰在關節縫重疊消縫）。實證 dilate 16~24 把覆蓋率從 ~0.77 推到 ~0.97。0=不擴。
- hint-dir 內**所有** `<slug>.png` 都會被切（不限必備 4 件）。

輸出 `outputs/ar2-dgx-comfyui-spine/{date}_{character_id}/{reference.png, parts/*.png, manifest.json, qc_report.json}`。

## manifest 契約

每部件：`name`(slug) / `bbox`[x,y,w,h]（trim padding=0、(w,h) 嚴格 = part PNG 尺寸、(x,y)=reference 全圖座標）/ `pivot`{x,y,**best_effort**} / `rotation`{deg,**best_effort**} / `draw_order`(整數·**允許同層重複**，L/R 對稱件天然同層) / `source`。

> ⚠️ **pivot / rotation 是 best-effort 視覺提示**（給人在 Spine Editor 建 bone 參考），**不保證可程式驅動旋轉**。下游勿當硬契約 driven。

## 8 閘 QC（任一硬閘 fail 不靜默）

齊全（⊇ 4 部件）/ 命名 bijection 雙向 / manifest 數值有效 / 上肢分離 ≤5% / L/R 對稱 / 部件內破洞 / 可組回 masked-SSIM ≥0.95（獨立純依 manifest 貼回器）/ **全圖前景覆蓋率 ≥0.97**（抓「相連區漏抓」假象——部件互不重疊但聯集沒蓋滿前景，如 PoC 腿 mask 0% 重疊卻只蓋 43%）。

> 閾值全標「暫定·待多角色樣本校準」。第 8 閘分母用白底閾值法 → **限定 v1 reference 為白底**；非白底降 warn（分母近似不可信）。

## DGX 前置（一次性）

生成 reference 需 DGX GPU（Flux）正常。**切件預設 `hintfg` 純本地、不需 DGX/SAM**——給 `--reference` 既有白底圖時整條切件零 DGX。僅 `--method sam` 才需 ComfyUI 裝 **ComfyUI-Impact-Pack**（SAMLoader/MaskToSEGS/SAMDetectorCombined）+ SAM 權重 `sam_vit_b_01ec64.pth`（放 `/root/ComfyUI/models/sams/`，目錄不存在先 `mkdir`）。check skill 不盤點 SAM 類節點，**不能靠 check 驗 SAM 在不在**。

## 檔案結構

```
scripts/
  spine.py               單發半自動 CLI 主編排（--method hintfg 預設 / sam 選項）
  spine_cut.py           hintfg 切件 primitive：part = hint ∩ 白底前景（純函式·白底預設）
  spine_sam.py           SAM 切件 workflow builder（--method sam 用·載 sam_part.json + 注入）
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
