---
display_name: 「家族總覽」
emoji: 🗂️
status: experimental
order: 1
category: meta
upstream: []
downstream: []
---

## 一句話：這 skill 解什麼問題？

幫你看清 `ar2:*` 家族每個 skill 怎麼用、何時用。

## 什麼時候會想到要用？

- 我忘記 `ar2:*` 家族目前有哪些 skill 了
- 我想知道某個 `ar2:*` skill 該怎麼用、什麼時機用
- 我新加了一個 `ar2:*` skill，想更新總覽
- 我寫新 skill 前想看現有家族的脈絡

## 最簡單的用法

```bash
# 看現有的總覽（最常用）
python3 ~/.claude/skills/ar2:skill-overview/scripts/show.py

# 改了某 skill 的 OVERVIEW.md 之後，重新整理
python3 ~/.claude/skills/ar2:skill-overview/scripts/refetch.py
```

## 常用參數

| 參數 | 白話 |
| --- | --- |
| （無）| 開現有的總覽 HTML — 沒生成過會提示你跑 refetch |
| `refetch` | 重新掃描 ar2:* 家族、重新生成 HTML、自動打開 |

## 跟家族裡其他 skill 怎麼配合？

- 上游：無
- 下游：不被其他 skill 直接用
- **特殊關係**：每次你新加一個 `ar2:*` skill 或改了某 skill 的 `OVERVIEW.md`，建議跑一次 `refetch`，讓總覽 HTML 反映最新狀態。

## 容易踩的坑

- **如果你看到「Cache 不存在」**：表示沒跑過 refetch — 第一次用時記得跑一次。
- **如果開出來內容是舊的**：cache 過期了。show 模式會印警告但不會自動 refetch，原因是「重新生成需要時間，你不一定每次都要等」。看到警告就跑一次 refetch。
- **如果某 skill 在「⚠️ 待補 / 損壞」區塊**：表示那個 skill 沒寫 OVERVIEW.md 或 frontmatter 格式錯。檢查該 skill 根目錄是否有符合 schema 的 `OVERVIEW.md`。
