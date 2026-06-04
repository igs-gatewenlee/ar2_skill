# P3 審查彙整報告

- 日期：2026-06-04
- 分支：feature/transparent-asset-route-a
- 範圍：Plan Y v1.3（雙模組大型閉環）— plan_schema / plan_validate / plan_loader / plan_runner + 透明素材 route
- 審查視角：correctness / security / repro+quality（三 lens parallel 審查 + 異源 skeptic 對抗驗證）

---

## 1. High findings（severity high → 必修）

**無。**

通過獨立 skeptic 對抗驗證、確認為真的 high findings 清單為空。本次改動在「本地單操作者 CLI、plan YAML/markdown 由操作者撰寫、DGX 為信任內網、SSH 憑證既有」的 trust model 下，無達 high 嚴重度的問題。

---

## 2. Medium findings（建議 / 需用戶決策）

**無。**

無經確認的 medium findings。

---

## 3. Low findings 摘要（未經對抗驗證，僅摘要、不要求修）

以下 11 項為各 lens 自審產出、未經獨立 skeptic 升級確認的低嚴重度觀察。屬「邊界 / defense-in-depth / 測試覆蓋 / 設計-spec 一致性」性質，不影響主路徑產圖正確性。是否處理由維護者決定。

### correctness（邊界 / 一致性）

- **L1 空 dict `pulid: {}` 誤升 v13 dispatch**
  `plan_schema.py:651-673 (_item_engages_v13_pulid_dispatch)`。`pulid: {}`（空 dict）被 parse 成 `item.pulid_override = {}`（非 None），`is not None` 判定為 True → 該 item 由 legacy 升為 v13 dispatch，連帶套用 BC-G2-7 force-None 與 EH-G1-2 gate，可能令原本可跑的 plan 觸發 EH-G1-2 抛錯。panel_taxonomy 的 `pulid: {}` 同理。建議將判斷收緊為「非空 dict」（空 dict falsy），或在 _validate_pulid_override 對空 dict 回 None。

- **L2 顯式 `strength: null` 跳過 fallback 鏈**
  `plan_schema.py:368-370` + `:600-616`。`pulid: {enabled: true, strength: null}` 時 strength 寫成 None 但 key 存在，_dispatch_candidates 以 `key in override` 判存在（不檢值非 None），結果 enabled=true 卻 strength=None，跳過 item > panel_type > plan.pulid_weight > default 1.0 三層 fallback，與 BC-G2-3 不符（顯式 null 應視為未提供）。建議：strength is None 時不寫入 out，或候選 append 條件改為「key in override 且值非 None」。

- **L3 dead route：layerdiffuse 宣告為合法但 workflow 檔不存在**
  `plan_runner.py:37 (_TRANSPARENT_ROUTE_WF)` + `plan_loader.py:206 (_TRANSPARENT_ROUTES)`。route 'layerdiffuse' 映射到 `route_b_layerdiffuse_sdxl.json` 並列為合法值，但 transparent/workflows/ 下僅有 `route_a_rmbg.json` 與 `vfx_additive.json`（已實機確認 route_b 檔缺）。設 route=layerdiffuse 會 per-item raise WorkflowParamError。屬 graceful per-item 失敗非崩潰，但宣告-實作不一致。建議：若 Route B 為未來工作則移除宣告，或給「Route B 尚未實作」明確訊息。

- **L4 spec BC-G5-4 C2 字面與實作出入（spec 不精確、實作正確）**
  `plan_validate.py:130 (_C2_DIMS)`。spec C2 文字列 cast_in_panel 應做 taxonomy 雙寫警示，但 PanelTypeConfig 無 cast_in_panel 欄位、不可能雙寫。實作 _C2_DIMS 正確排除之。無需改 code，建議補註記避免日後被當漏實作補回。

### security（trust model 下無 high，以下為 defense-in-depth / 共享 plan 情境）

- **L5 face_ref 無 basename 約束（路徑穿越 / 敏感檔外送）**
  `plan_runner.py:289-313 (_resolve_face_ref)` + `plan_schema.py:954-960`。v1.3 將 face_ref 從 plan-level 單一擴張為每 item / 每 panel_type 可指定。schema 只驗 non-empty string，dispatch 後對其 `Path(...).resolve()` 讀本地任意路徑再 scp 上傳 DGX。共享/LLM 產生的 plan 若寫 `../../.ssh/id_rsa` 或 `~/.aws/credentials` 可致本機敏感檔外送。建議加 basename 約束（拒 `/`、`\`、`..`、絕對路徑、`~`）或 _upload_face_ref 解析後 assert 落在白名單根；既有 plan-level face_ref 一併補。

- **L6 透明後處理無 decompression bomb 防護（OOM/DoS）**
  `plan_runner.py:484-490 (_postprocess_transparent: Image.open)` + `qc.py:68`。對 DGX 下載回的圖直接 PIL Image.open 全圖載入，未設 Image.MAX_IMAGE_PIXELS。透過 workflow_override 指向自訂 workflow 產出超大像素 PNG 可觸發本機 OOM；OOM 為進程級，try/except 攔不住。建議統一設 MAX_IMAGE_PIXELS（如 64M px）並 catch DecompressionBombError 降級該 item。

- **L7 硬編 home fallback + sys.path 前插 + bare module 名（弱化載入路徑風險）**
  `plan_runner.py:39-46 (_transparent_skill_dir)` + `:60-71 (_load_transparent_modules)`。fallback 到硬編 `Path.home()/Code/ar2-skills/ar2:dgx-comfyui-transparent`，sys.path.insert(0,...) 後以 bare 名 import transparent_postprocess / qc / asset_spec（asset_spec 尤為通用名）。同名惡意 .py 置於該路徑可於處理首個透明 item 時以操作者權限執行。本機受信屬低風險。建議改用 importlib spec_from_file_location 絕對路徑載入、移除硬編 fallback、模組名加 skill 前綴。

### repro+quality（測試覆蓋 / 語意一致）

- **L8 validate B1 與 gen-side legacy 之 PuLID 真值語意縫隙**
  `plan_validate.py:89` + `plan_loader.py:300-311`。validate B1 用 _resolve_per_item_config 的「宣告意圖」模型（從 character_consistency 派生）；gen-side legacy 分支不論 enabled 真值都把 plan.pulid_weight/face_ref 直送 inject。cards_a11c 型（flux_pulid + face_ref + prompt_only）runtime PuLID 實際生效，但 B1 因 enabled 派生為 False 不觸發多角色衝突警示。屬 warning-only lint、不影響產圖。建議 B1 補 legacy-aware 條件，或於 SKILL/docstring 明示 B1 僅涵蓋 v1.3 顯式宣告。

- **L9 legacy ResolvedItem.pulid_enabled 為誤導值**
  `plan_loader.py:310-311` + `:36`。legacy 分支回傳 _pulid_enabled_from_consistency（cards_a11c=False）但同分支仍把 face_ref/weight 送 inject、PuLID 實際生效，欄位語意自相矛盾。目前唯一 consumer _check_pulid_alignment 對 legacy 早退故惰性無害，但新 consumer 會踩雷。建議 legacy 分支回語意明確值（以 face_ref is not None 推 effective active）或 docstring 明示「legacy 下此欄無意義，須先檢 pulid_dispatch=='v13'」。

- **L10 v13 strength default 1.0 路徑無端到端測試覆蓋**
  `plan_schema.py:1206-1208 (_DISPATCH_DEFAULTS['pulid.strength']=1.0)`。v13 enabled=true 但三層皆缺 strength 時回 default 1.0，覆寫 template default（spec ground-truth 0.9）。因 v13 為 opt-in，非 backward-compat regression。但 1.0 屬 BC-G2-3 直譯未必符實戰，且無測試覆蓋「v13 enabled=true 完全不指定 strength」流經 inject 的端到端後果（現有 test 只測 _resolve_per_item_config 回 1.0）。建議補端到端 unit test，或評估改回 None 讓 inject 保留 template 0.9。

> 註：L2 與 L10 同源於 strength fallback / default 語意，若處理建議一併釐清「顯式 null vs 未提供 vs default」三態。

---

## 4. 誤報記錄（記錄、不要求修）

**無。**

本次審查未產生被 skeptic 駁回的誤報。

---

## 5. 整體 verdict

**pass（with low-severity notes）**

理由：
- 無 high、無 medium findings；無經確認的正確性回歸。
- v13 PuLID dispatch 為 opt-in，legacy 路徑行為維持（L8/L9 為語意縫隙而非行為錯誤）。
- 11 項 low 均屬邊界 / defense-in-depth / 測試覆蓋 / spec-實作字面一致性，不阻擋合併。

維護者可選擇性處理的優先建議（非阻擋）：
1. **L5（face_ref basename 約束）** — security 面影響最直接、修復成本低，建議優先。
2. **L1 + L2（pulid 空 dict / 顯式 null 邊界）** — 影響 dispatch 行為可預期性，修復局部。
3. **L3（layerdiffuse dead route）** — 宣告-實作一致性，二擇一（移除宣告 or 明確未實作訊息）。

其餘（L4/L6/L7/L8/L9/L10）列為 backlog / defense-in-depth，依排程處理即可。
