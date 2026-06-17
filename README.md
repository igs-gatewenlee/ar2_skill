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

源碼 repo：`git@github.com:igs-gatewenlee/ar2_skill.git`（**PUBLIC**——自 1.2.5 SSOT registry 遷移起，repo 內零密碼字面：連線/路徑/模型在 `dgx-registry.toml`、密碼移到 repo 外 `~/.config/ar2/secrets.toml`，故可公開。詳見下方「安全」段）。本 repo 自帶 `.claude-plugin/marketplace.json`，clone 下來即是 local marketplace。

**任何機器首裝**：
```bash
git clone git@github.com:igs-gatewenlee/ar2_skill.git <你的位置>   # Mac: ~/Code/ar2-skills；Win 例: I:\ar2-skills
# config.py 現為 tracked 零密值 shim（讀 dgx-registry.toml SSOT），隨 clone 帶來，無需手動放
```
在 Claude Code 內：
```
/plugin marketplace add <你的位置>
/plugin install ar2@ar2-marketplace
```
裝好後 5 個 `ar2:dgx-comfyui-*` skill 自動發現 + `/ar2:upgrade` command。

**⚠️ 連 DGX 前：設定密碼（每台機一次性，永久有效）**

密碼不在 repo 內，所以**每台要連 DGX 的機器**第一次都得提供密碼，否則 check/gen/train/spine/transparent 存取密碼時會 fail-loud。內網共用預設為 `root`。二選一：
```bash
# A. 環境變數 — 最快（加進 ~/.zshrc / ~/.bashrc 永久生效）
export AR2_DGX_PASSWORD=root

# B. 密碼檔 — loader 預設讀 ~/.config/ar2/secrets.toml（TOML，[machine] 區段的 password 欄位）
mkdir -p ~/.config/ar2
DGX_PW=root                                    # ← 換成你的 DGX 密碼
{ echo '[machine]'; echo "password = \"$DGX_PW\""; } > ~/.config/ar2/secrets.toml
chmod 600 ~/.config/ar2/secrets.toml
```
> 只用 `plan`（純本地、不連 DGX）的機器**不需要**——密碼是惰性解析，`import` 不觸發。

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
├── .gitignore                       ← 排除 __pycache__ / cache（config.py 已改 tracked 零密值 shim）
├── dgx-registry.toml                ← DGX 部署參數 SSOT（連線/路徑/模型，零密值、git-tracked）
├── .githooks/pre-commit             ← 擋密碼字面進 git（需 git config core.hooksPath .githooks）
├── .claude-plugin/
│   ├── plugin.json                  ← plugin 元資料（name=ar2）
│   └── marketplace.json             ← local-path marketplace 清單
└── skills/
    ├── _shared/                     ← ar2_registry.py（registry loader, PEP 562 惰性密碼）+ 守恆測試
    ├── dgx-comfyui-check/           ← SKILL.md, OVERVIEW.md, config.py(零密值 shim), scripts/, references/, tests/
    ├── dgx-comfyui-gen/
    ├── dgx-comfyui-plan/
    ├── dgx-comfyui-train/
    └── dgx-comfyui-transparent/
```

## 安全（SSOT registry + 私網信任模型）

自 **1.2.5** 起，DGX 部署參數收斂為 SSOT：
- **`dgx-registry.toml`**（git-tracked、**零密碼**）：連線 metadata（`192.168.5.27` / port / `root` / hostkey）、路徑、模型。
- **`~/.config/ar2/secrets.toml`**（**repo 外**、每台機本機）：密碼。`config.py` 是讀 registry 的零密值 shim；`PASSWORD` 由 `_shared/ar2_registry` 惰性解析（PEP 562）。

DGX 是**刻意共用機**（私網內人人可用、`root/root`），非洩漏——共用憑證為設計選擇，**不做換密碼**；DGX 內網隔離為主防線。

- ✅ **repo 可公開**：密碼字面從未進 git；registry / config.py / shim 全零密值（守恆測試 CT-8 把關）。公開面僅內網 IP/port/`root`/hostkey + well-known `root/root` default——低敏感。
- ✅ **防線**：`skills/_shared/tests`（CT-8 等 16 守恆測試，CI/pytest 必跑、主守衛）+ `.githooks/pre-commit`（第二層，需 `git config core.hooksPath .githooks`；best-effort、可被 `--no-verify` 繞）。
- ⚠️ **舊 cache 殘留**：1.2.5 之前（1.0.0–1.2.4）裝過的 plugin cache 仍含舊肥 `config.py`（明文密碼），因 local-path marketplace install 是**逐字 filesystem 複製、不遵守 .gitignore**。1.2.5 後 tracked shim 零密值，新裝 cache 已乾淨；舊 cache 可選清理：`find ~/.claude/plugins/cache -path '*dgx-comfyui*' -name config.py`。

密碼旋轉（若需要）：先改 DGX → 改各機 `~/.config/ar2/secrets.toml`（不再碰 config.py）→ 跑 `ar2:dgx-comfyui-check` 驗證。

## 與 ai_cards workspace 的關係

本 repo 從 `~/Code/ai_cards/skills/ar2:*` 抽離（2026-05-15），2026-06-04 遷移為 plugin。ai_cards 是 dogfooding workspace（閉環方法論 + 在此消費 ar2 plugin）；ar2-skills 是 source repo + marketplace，可被多 project 共用。

ai_cards 仍保有 `CLAUDE.md`（閉環方法論）/ `.claudedocs/` / `.claude-loop/`（artifacts + learning-log）。消費端改接 plugin 後，舊 `.claude/skills/ar2:*` symlink 已不需要（見遷移 spec S7）。
