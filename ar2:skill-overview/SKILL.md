---
name: ar2:skill-overview
description: Use when the user asks to "看 ar2 家族總覽", "打開 ar2 文件", "ar2:* 怎麼用", "ar2 skill 說明", "ar2 list", "ar2 cheatsheet", "重新整理 ar2 總覽", "refetch ar2 文件", or wants a visual knowledge-base index of all ar2:* skills (how to use, when to use, common pitfalls). Default action opens cached HTML; passing `refetch` arg rescans ar2:* family and regenerates HTML. NOT for: invoking specific ar2:* skill (those have their own invocation), editing OVERVIEW.md content (use direct file edit).
---

# ar2:skill-overview

`ar2:*` 家族的視覺化知識庫入口。掃描 workspace + installed 兩邊的 `ar2:*` skill，整理成單頁 HTML（含 pipeline 圖、索引 cards、每個 skill 的白話 6 段詳細說明），用系統 browser 打開。

## 這個 skill 做什麼

兩種行為：

1. **無參數**（show 模式）— 開現有 cache HTML
   - cache 不存在 → 提示先跑 refetch（exit 1）
   - cache 存在 → 用 `open` 打開 file://
   - 偵測 cache 是否過期（cache `generated_at` < 任何 source `OVERVIEW.md/SKILL.md` 的 mtime）→ 印警告但仍打開

2. **`refetch` 參數** — 重新掃描 + 生成 HTML + 打開
   - 掃 `<workspace>/skills/ar2:*`（source）+ `<workspace>/.claude/skills/ar2:*`（project install，優先）+ `~/.claude/skills/ar2:*`（user install，fallback）
   - 用 `Path.resolve()` 比對 canonical path → 判定狀態（installed / workspace_only / orphan_install）
   - 讀每個 skill workspace 版的 `OVERVIEW.md`（IF-1 schema），解析 frontmatter + 6 大段
   - 缺 OVERVIEW.md 或解析失敗 → fallback meta，集中在「⚠️ 待補 / 損壞」區塊
   - 渲染 HTML 寫入 `~/.cache/ar2-skill-overview/overview.html`
   - 自動 `open` 打開

## 何時觸發

- 「看 ar2 家族總覽」「打開 ar2 文件」「ar2 list」
- 「ar2:* 怎麼用」「ar2 skill 說明」「ar2 cheatsheet」
- 「重新整理 ar2 總覽」「refetch ar2 文件」「ar2 文件更新」
- 新加了 ar2:* skill 後想更新總覽

## 何時 **不** 觸發

- 想實際 invoke 某個 ar2:* skill → 直接呼叫對應 skill（如 `ar2:dgx-comfyui-check`）
- 想改某 skill 的 OVERVIEW.md 內容 → 直接編輯該檔，refetch 會自動撿到

## 如何執行

```bash
# Show（無參數）
python3 ~/.claude/skills/ar2:skill-overview/scripts/show.py

# Refetch（重新生成）
python3 ~/.claude/skills/ar2:skill-overview/scripts/refetch.py
```

Exit codes：

- `0` 正常
- `1` show 模式 cache 不存在
- `2` workspace 目錄不存在
- `3` cache 目錄不可寫 / template 不存在

## 預期輸出（示例）

### show 模式（cache 存在不過期）

```
（無 stdout 輸出，直接開啟 browser）
```

### show 模式（cache 過期）

```
⚠️  Cache 可能過期（source 檔被修改過），建議重整：
  python3 .../refetch.py
（隨後仍開啟 browser）
```

### refetch 模式

```
== ar2:skill-overview refetch ==
找到 4 個 ar2:* skill
  OK: 3 · 待補/損壞: 1
✅ Cache 已生成：~/.cache/ar2-skill-overview/overview.html
```

## 檔案結構

```
ar2:skill-overview/
├── SKILL.md                              ← this file
├── OVERVIEW.md                           ← 給 ar2:skill-overview 自己用的白話介紹（dogfooding）
├── .gitignore                            ← 排除 __pycache__
├── scripts/
│   ├── show.py                           ← entry: 無參數
│   ├── refetch.py                        ← entry: refetch
│   ├── scanner.py                        ← BC-1 ~ BC-3：列舉 workspace + installed
│   ├── parser.py                         ← BC-4 ~ BC-6：解析 OVERVIEW.md
│   ├── renderer.py                       ← BC-7 ~ BC-8：HTML 生成
│   └── opener.py                         ← EH-5：跨平台開 file://
└── templates/
    └── overview-template.html            ← HTML 骨架（CSS 內聯、Placeholder 由 renderer 替換）
```

## OVERVIEW.md 撰寫契約（給其他 ar2:* skill 寫者）

要被本 skill 收錄，每個 `ar2:*` skill 都要在 skill 根目錄放一份 `OVERVIEW.md`，按以下 schema：

```markdown
---
display_name: 「白話標題」
emoji: 🩺
status: stable | beta | experimental
order: 1
category: workflow | meta
upstream: ["ar2:..."]
downstream: ["ar2:..."]
---

## 一句話：這 skill 解什麼問題？
（建議 20-30 字）

## 什麼時候會想到要用？
- 場景 1
- 場景 2

## 最簡單的用法
（一行指令）

## 常用參數
| 參數 | 白話 |
| --- | --- |
| --x | ... |

## 跟家族裡其他 skill 怎麼配合？
- 上游：...
- 下游：...

## 容易踩的坑
- ...
```

**規則**：

- 6 大段「有則寫滿、沒料則省略」（renderer 自動略過空段）
- frontmatter 7 個欄位都必要、不符合驗證 → 該 skill 被標 `parse_error` 進入「待補/損壞」區
- `category: workflow` 進主 pipeline；`meta` 進輔助工具區
- `order` 升序排序，同 order fallback 按 skill 名稱字母順序

## 家族（ar2:*）

| Skill | 用途 |
|-------|------|
| `ar2:skill-overview` | 本 skill（家族文件入口）|
| `ar2:dgx-comfyui-check` | DGX 體檢 + 模型盤點 |
| `ar2:dgx-comfyui-gen` | 在 DGX 上跑 ComfyUI 產圖 |
| `ar2:dgx-comfyui-train` | 在 DGX 上訓 LoRA |

## 安全約束

- 本 skill 純本機檔案操作，不連網路、不存敏感資料、不執行 user input → **可** publish 到 ClawHub
- cache 路徑寫死絕對路徑（與 invoke cwd 無關），不會誤寫到其他位置
