# ar2-skills

`ar2:*` 家族 — 個人 Claude Code **plugin**（name=`ar2`）。獨立 git repo，同時是自己的 local-path marketplace。磁碟目錄零冒號（跨平台可攜，含 Windows）；呼叫名 `ar2:dgx-comfyui-*` 由 plugin namespace 合成。

## 家族成員

| Skill（呼叫名） | 用途 | Status |
|-------|------|--------|
| 🩺 `ar2:dgx-comfyui-check` | DGX 機器體檢 + ComfyUI 13 分類模型盤點 | stable |
| 🎨 `ar2:dgx-comfyui-gen` | 在 DGX 上跑 ComfyUI workflow 產圖，成品拉回本機 | stable |
| 🗂️ `ar2:dgx-comfyui-plan` | 計畫驅動批次產圖（outline.md plan / preset 庫 / Design Dimensions） | stable |
| 🎓 `ar2:dgx-comfyui-train` | 在 DGX 上訓 Flux LoRA + 訓完自動部署 | beta |
| 🖼️ `ar2:dgx-comfyui-transparent` | 產帶真實 Alpha 的透明遊戲素材（去背 / VFX 加色） | beta |

典型工作流：**check** → **plan** → **gen** / **train** / **transparent**。

## Install（plugin marketplace · 多機）

源碼 repo：`git@github.com:igs-gatewenlee/ar2_skill.git`（**私有**——含 DGX 私網明文密碼文件，⛔ 不可轉公開）。本 repo 自帶 `.claude-plugin/marketplace.json`，clone 下來即是 local marketplace。

**任何機器首裝**：
```bash
git clone git@github.com:igs-gatewenlee/ar2_skill.git <你的位置>   # Mac: ~/Code/ar2-skills；Win 例: I:\ar2-skills
# ⚠️ config.py 是 gitignored、不會跟著 clone —— check/gen/train 3 個 skill 的 config.py 要手動放一次
```
在 Claude Code 內：
```
/plugin marketplace add <你的位置>
/plugin install ar2@ar2-marketplace
```
裝好後 5 個 `ar2:dgx-comfyui-*` skill 自動發現 + `/ar2:upgrade` command。

**之後更新（任何機器、消費用）**：
```
/ar2:upgrade        # = git pull → marketplace update → plugin update（不 bump）
/reload-plugins     # 套用
```

**開發發布（改完源碼的那台機）**：
```
/ar2:upgrade dev    # = bump patch + commit + push + update
# 或在 repo 內：bash bump-and-update.sh [patch|minor|major] --push
```
> bump 只該發生在開發機；消費機永遠用同步模式，否則多機版本歷史會分岔。

> **copy-to-cache**：marketplace 安裝是把 plugin 複製到 `~/.claude/plugins/cache/`，源檔 Edit 不即時生效——所以才需要上面的 update 流程。`/ar2:upgrade` 的源碼路徑是從本機 marketplace 註冊**動態解析**（`known_marketplaces.json`），跨機不用改。

**開發模式（源檔即時生效、免 bump）**：
```bash
claude --plugin-dir <你的位置>
# 改完源碼後在 session 內：/reload-plugins
```

## 個別 skill 文件

每個 `skills/<skill>/` 下都有：
- `SKILL.md`（給 Claude Code 看的 invocation 指令 + 行為描述；`name:` 為裸名、呼叫時加 `ar2:` 前綴）
- `OVERVIEW.md`（給用戶看的白話介紹 — 一句話 / 何時用 / 怎麼用 / 踩坑）

## 結構

```
ar2-skills/
├── README.md                        ← this
├── .gitignore                       ← 排除 config.py / __pycache__ / cache
├── .claude-plugin/
│   ├── plugin.json                  ← plugin 元資料（name=ar2）
│   └── marketplace.json             ← local-path marketplace 清單
└── skills/
    ├── dgx-comfyui-check/           ← SKILL.md, OVERVIEW.md, config.py(gitignored), scripts/, references/, hooks/
    ├── dgx-comfyui-gen/
    ├── dgx-comfyui-plan/
    ├── dgx-comfyui-train/
    └── dgx-comfyui-transparent/
```

## 安全（私網信任模型）

`dgx-comfyui-{check,gen,train}` 內各有 `config.py` 含 DGX（`192.168.5.27`）明文密碼。DGX 是**刻意共用機**（私網內人人可用、`root/root`），非洩漏——明文密碼為設計選擇，**不做 secret scrub / 換密碼**。

- ⛔ **不要** push 到任何**公開** repo（私網信任模型只在內網成立；公開分享或 DGX 對外暴露才需重審）
- ✅ `config.py` 在每個 skill 的 `.gitignore` 第一行 + 本 repo top-level `.gitignore` 也排除
- ✅ 各 skill 保留 `hooks/pre-commit` 攔 PASSWORD literal commit（既有安全網）
- ⚠️ **plugin cache 暴露面**：local-path marketplace install 是**逐字 filesystem 複製、不遵守 .gitignore**——`config.py`（含明文密碼）會連同被複製進 `~/.claude/plugins/cache/`。gitignore 只擋 git，**擋不住 cache**。在共用 DGX 信任模型下（同機本地、刻意共享）可接受；但 ⛔ **不要分享該 cache 目錄、也不要用 `--plugin-dir *.zip` 打包散佈**（會把明文密碼嵌入散佈物）。需更強隔離時，改讓 check/gen/train/transparent 從 plugin tree 外（如 `~/.config/ar2/config.py`）讀 config。

密碼旋轉（若需要）：先改 DGX → 改各 skill 的 config.py → 跑 `ar2:dgx-comfyui-check` 驗證。

## 與 ai_cards workspace 的關係

本 repo 從 `~/Code/ai_cards/skills/ar2:*` 抽離（2026-05-15），2026-06-04 遷移為 plugin。ai_cards 是 dogfooding workspace（閉環方法論 + 在此消費 ar2 plugin）；ar2-skills 是 source repo + marketplace，可被多 project 共用。

ai_cards 仍保有 `CLAUDE.md`（閉環方法論）/ `.claudedocs/` / `.claude-loop/`（artifacts + learning-log）。消費端改接 plugin 後，舊 `.claude/skills/ar2:*` symlink 已不需要（見遷移 spec S7）。
