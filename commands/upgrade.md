---
description: 把本機 ar2 plugin 更新到最新版（bump 版本 + commit + 重整 marketplace + 更新已裝 plugin）。可從任何專案執行，免 cd 回 ar2-skills。
---

# /ar2:upgrade — 一鍵更新 ar2 plugin

把 ar2 plugin 更新到最新：在源碼 repo bump 版本號、commit、重整 local marketplace、更新已裝的 plugin（copy-to-cache）。

## 執行步驟（請嚴格照做、不要多做）

1. 源碼 repo 路徑：`/Users/gatewenlee/Code/ar2-skills`。
   先確認它存在；不存在 → 回報「找不到 ar2-skills 源碼 repo（路徑可能已搬移，請更新此 command）」並停止。

2. 執行（一條龍：bump patch 版本 + git commit + marketplace update + plugin update）：
   ```bash
   bash /Users/gatewenlee/Code/ar2-skills/bump-and-update.sh --commit
   ```

3. 回報腳本輸出的**新版本號**（例 `ar2 @ 1.0.x`）。

4. 提醒用戶：更新已進 plugin cache，但需 **`/reload-plugins`（同 session）或重啟 Claude Code** 才會套用。

## 注意
- 若 `bump-and-update.sh` 失敗（例如 `claude plugin update` 報錯），**原樣回報 stderr、不要自行猜修**。
- 這個 command 只負責更新 ar2 plugin，不要順便改其他東西。
- 開發頻繁迭代時的替代路徑：`claude --plugin-dir /Users/gatewenlee/Code/ar2-skills` + `/reload-plugins`（源檔即時生效、免 bump）。
