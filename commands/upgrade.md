---
description: 同步本機 ar2 plugin 到最新（git pull → marketplace update → plugin update，不 bump、消費機安全）。加 `dev` 引數＝開發發布（bump+commit+push+update）。跨機通用——源碼路徑從本機 marketplace 註冊動態解析、不硬編。
---

# /ar2:upgrade — 同步 / 發布 ar2 plugin

`$ARGUMENTS` 含 `dev` → **dev 發布模式**；否則 → **同步模式**（預設）。
請嚴格照下列步驟、不要多做；任何指令失敗時**原樣回報輸出、不要自行猜修**。

## 第 1 步（兩種模式共同）：動態解析源碼 repo 路徑

從**本機** marketplace 註冊讀出 ar2-marketplace 的 source 路徑（每台機器不同，Mac/Windows 皆適用、不硬編）：

```bash
python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.claude/plugins/known_marketplaces.json')))['ar2-marketplace']['source']['path'])"
```

- 若無 python3：跑 `claude plugin marketplace list`，找 `ar2-marketplace` 列的 `Source: Directory (<path>)` 取出 `<path>`。
- 解析失敗、或該路徑不存在 → 回報「本機未註冊 ar2-marketplace 或源碼路徑不存在；請先 git clone repo 並 `/plugin marketplace add <path>`」並**停止**。

以下用 `<SRC>` 代表解析出的路徑。

## 同步模式（預設）：把本機 plugin 同步到最新（**不 bump**）

1. `git -C <SRC> pull --ff-only`
   - 無 remote 或 pull 失敗 → 照實回報但**繼續**（本地既有版本仍可同步）。
2. `claude plugin marketplace update ar2-marketplace`
3. `claude plugin update ar2@ar2-marketplace`
   - 回「已是最新 / no update」也是正常結果，照實回報。
4. 回報目前版本，提醒：**`/reload-plugins`（同 session）或重啟 Claude Code** 才會套用。

## dev 發布模式（`/ar2:upgrade dev`）：改完源碼後一鍵發布（開發機用）

1. `git -C <SRC> status --short` 給用戶看一眼有哪些變更。
2. `bash <SRC>/bump-and-update.sh --commit --push`
   （bump patch 版本 + git commit + **git push** + marketplace update + plugin update）
3. 回報新版本號，提醒 `/reload-plugins` 或重啟。

> 消費機（只用不開發）**永遠用同步模式**；版本 bump 只該發生在開發機，否則多機版本歷史會分岔。

## 注意

- 這個 command 只負責 ar2 plugin 的同步/發布，不要順手改其他東西。
- 開發頻繁迭代的替代路徑：`claude --plugin-dir <SRC>` + `/reload-plugins`（源檔即時生效、免 bump）。
