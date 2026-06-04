#!/usr/bin/env bash
# bump-and-update.sh
#
# ar2 plugin 維護腳本：bump 版本 → 重整 local marketplace → 更新已裝 plugin。
# 因 marketplace install 是 copy-to-cache，源碼改完需 bump 版本才會被
# `claude plugin update` 認得（它比對 源版本 vs 已裝版本）。
#
# Usage:
#   bash bump-and-update.sh [patch|minor|major|X.Y.Z] [--commit] [--dry-run]
#
#   patch (預設) / minor / major  → 自動遞增；或直接給 X.Y.Z 指定版號
#   --commit    → 連同 git commit 版本 bump
#   --dry-run   → 只顯示會做什麼，不改檔、不呼叫 claude
#
# 開發頻繁改動時，改用免 bump 的 dev 模式：
#   claude --plugin-dir "$(dirname "$0")"   然後 session 內 /reload-plugins
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_JSON="$REPO/.claude-plugin/plugin.json"
MARKET_JSON="$REPO/.claude-plugin/marketplace.json"

BUMP="patch"
COMMIT=0
DRY=0
for a in "$@"; do
  case "$a" in
    --commit) COMMIT=1 ;;
    --dry-run) DRY=1 ;;
    patch|minor|major) BUMP="$a" ;;
    [0-9]*.[0-9]*.[0-9]*) BUMP="$a" ;;
    *) echo "❌ unknown arg: $a"; exit 2 ;;
  esac
done

[ -f "$PLUGIN_JSON" ] || { echo "❌ not found: $PLUGIN_JSON"; exit 1; }
[ -f "$MARKET_JSON" ] || { echo "❌ not found: $MARKET_JSON"; exit 1; }

# 算新版本 + 讀 plugin/marketplace 名（單一 python 來源，避免 jq 依賴）
read -r PLUGIN_NAME MARKET_NAME OLD_VER NEW_VER < <(
  python3 - "$PLUGIN_JSON" "$MARKET_JSON" "$BUMP" <<'PY'
import json, re, sys
pj, mj, bump = sys.argv[1], sys.argv[2], sys.argv[3]
p = json.load(open(pj))
m = json.load(open(mj))
old = str(p.get("version", "0.0.0"))
if re.fullmatch(r"\d+\.\d+\.\d+", bump):
    new = bump
else:
    a = [int(x) for x in (old.split(".") + ["0", "0", "0"])[:3]]
    if bump == "major":
        a = [a[0] + 1, 0, 0]
    elif bump == "minor":
        a = [a[0], a[1] + 1, 0]
    else:
        a = [a[0], a[1], a[2] + 1]
    new = ".".join(map(str, a))
print(p["name"], m["name"], old, new)
PY
)

echo "🔼 $PLUGIN_NAME: $OLD_VER → $NEW_VER   (marketplace: $MARKET_NAME)"

if [ "$DRY" = "1" ]; then
  echo "   [dry-run] 會寫 $PLUGIN_JSON version=$NEW_VER"
  [ "$COMMIT" = "1" ] && echo "   [dry-run] 會 git commit 版本 bump"
  echo "   [dry-run] 會跑：claude plugin marketplace update $MARKET_NAME"
  echo "   [dry-run] 會跑：claude plugin update $PLUGIN_NAME"
  exit 0
fi

command -v claude >/dev/null || { echo "❌ claude CLI 不在 PATH"; exit 1; }

# 寫回新版本（保留 2-space indent + 結尾換行）
python3 - "$PLUGIN_JSON" "$NEW_VER" <<'PY'
import json, sys
pj, new = sys.argv[1], sys.argv[2]
p = json.load(open(pj))
p["version"] = new
open(pj, "w").write(json.dumps(p, ensure_ascii=False, indent=2) + "\n")
PY

if [ "$COMMIT" = "1" ]; then
  git -C "$REPO" add "$PLUGIN_JSON"
  git -C "$REPO" commit -q -m "chore(plugin): bump $PLUGIN_NAME → $NEW_VER"
  echo "📝 committed: bump $PLUGIN_NAME → $NEW_VER"
fi

echo "🔄 claude plugin marketplace update $MARKET_NAME ..."
claude plugin marketplace update "$MARKET_NAME"
echo "⬆️  claude plugin update $PLUGIN_NAME ..."
claude plugin update "$PLUGIN_NAME"

echo "✅ done ($PLUGIN_NAME @ $NEW_VER) — 重啟 Claude Code 或在 session 內 /reload-plugins 套用"
