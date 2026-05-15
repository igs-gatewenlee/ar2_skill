# ar2-skills

`ar2:*` 家族 — 個人 Claude Code skill 集。獨立 git repo，可被任何 project 透過 `.claude/skills/` symlink install。

## 家族成員

| Skill | 用途 | Status |
|-------|------|--------|
| 🩺 `ar2:dgx-comfyui-check` | DGX 機器體檢 + ComfyUI 13 分類模型盤點 | stable |
| 🎨 `ar2:dgx-comfyui-gen` | 在 DGX 上跑 ComfyUI workflow 產圖，成品拉回本機 | stable |
| 🎓 `ar2:dgx-comfyui-train` | 在 DGX 上訓 Flux LoRA + 訓完自動部署 | beta |
| 🗂️ `ar2:skill-overview` | 家族視覺化知識庫入口（這個 HTML 就是它生的）| experimental |

典型工作流：**check** → **gen** / **train**（check 確認環境健康後再產圖或訓練）。

## Install 到一個 project

在你的 Claude Code project 根目錄執行：

```bash
bash /path/to/ar2-skills/install-to.sh /path/to/your-project
```

這會：
1. 在 project 內建 `.claude/skills/` 目錄（如不存在）
2. 為每個 `ar2:*` skill 建 absolute symlink 指向 `~/Code/ar2-skills/ar2:*`
3. 為 `ar2:dgx-comfyui-*` 的 `config.py` 設 chmod 600（含 DGX 密碼）

完成後重啟 Claude Code 在該 project 內，4 個 `ar2:*` slash command 就會出現。

驗證：對話內試「打開 ar2 家族總覽」（會 invoke `ar2:skill-overview`）。

## 個別 skill 文件

- 每個 `ar2:*/` 下都有：
  - `SKILL.md`（給 Claude Code 看的 invocation 指令 + 行為描述）
  - `OVERVIEW.md`（給用戶看的白話介紹 — 一句話 / 何時用 / 怎麼用 / 踩坑）

讀 `ar2:*/OVERVIEW.md` 認識每個 skill。或 install 後 invoke `ar2:skill-overview` 看 HTML 總覽。

## 結構

```
ar2-skills/
├── README.md                       ← this
├── .gitignore                      ← 排除 config.py / __pycache__ / cache
├── install-to.sh                   ← 把 ar2:* symlink 到指定 project
├── ar2:dgx-comfyui-check/
│   ├── SKILL.md, OVERVIEW.md, config.py (gitignored), .gitignore, hooks/, scripts/, references/
├── ar2:dgx-comfyui-gen/
├── ar2:dgx-comfyui-train/
└── ar2:skill-overview/
```

## 安全

`ar2:dgx-comfyui-{check,gen,train}` 內各有 `config.py` 含 DGX 明文密碼（私網信任模型）：

- ⛔ **不要** push 到任何公開 / 共享 repo
- ⛔ **不要** publish 個別 skill 到 ClawHub / skill marketplace
- ✅ `config.py` 在每個 skill 的 `.gitignore` 第一行 + 本 repo top-level `.gitignore` 也排除
- ✅ install-to.sh 自動 chmod 600 限制權限
- 各 skill 都有 `hooks/pre-commit` 攔 PASSWORD literal commit

密碼旋轉：先改 DGX → 改 4 個 skill 的 config.py（同一密碼複製 4 份）→ 跑 `ar2:dgx-comfyui-check` 驗證。

## 與 ai_cards workspace 的關係

本 repo 從 `~/Code/ai_cards/skills/ar2:*` 抽離（2026-05-15）。歷史 commit 在 ai_cards repo 內保留，本 repo 從現狀起跑。

ai_cards 仍保有：
- `CLAUDE.md`（閉環方法論）
- `.claudedocs/`（補充文檔）
- `design/`（ar2:dgx-comfyui-* 設計 plan v1）
- `.claude-loop/`（閉環 artifacts + learning-log）
- `.claude/skills/ar2:*`（symlink 指向本 repo）

ai_cards 是 dogfooding workspace（開發閉環方法論 + 在此 workspace 內 install ar2:*）；ar2-skills 是 source repo 可被多 project 共用。
