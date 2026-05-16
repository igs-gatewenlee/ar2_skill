#!/usr/bin/env bash
# install-to.sh
#
# Install ar2:* skills into a Claude Code project (.claude/skills/).
# Creates absolute symlinks pointing back to this repo, so updates to the
# source automatically reflect in installed projects.
#
# Usage:
#   bash install-to.sh /path/to/project
#
# What it does:
#   1. mkdir <project>/.claude/skills/
#   2. For each ar2:* skill, ln -s <this-repo>/ar2:NAME → <project>/.claude/skills/ar2:NAME
#   3. chmod 600 on each skill's config.py (DGX credentials)

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <project-root>"
  echo ""
  echo "Example: bash $0 ~/Code/ai_cards"
  exit 1
fi

if [ ! -d "$1" ]; then
  echo "❌ project root not found: $1"
  exit 1
fi

PROJECT="$(cd "$1" && pwd)"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SKILLS=(
  "ar2:dgx-comfyui-check"
  "ar2:dgx-comfyui-gen"
  "ar2:dgx-comfyui-plan"
  "ar2:dgx-comfyui-train"
  "ar2:skill-overview"
)

# Skills carrying DGX credentials to chmod 600 (plan skill is local-only, no config.py)
SECRET_SKILLS=(
  "ar2:dgx-comfyui-check"
  "ar2:dgx-comfyui-gen"
  "ar2:dgx-comfyui-train"
)

mkdir -p "$PROJECT/.claude/skills"

echo "== Installing ar2:* into $PROJECT =="
echo "   Source: $REPO"
echo ""

for s in "${SKILLS[@]}"; do
  src="$REPO/$s"
  if [ ! -d "$src" ]; then
    echo "❌ skill missing in repo: $src"
    exit 1
  fi

  target="$PROJECT/.claude/skills/$s"

  if [ -L "$target" ]; then
    current=$(readlink "$target")
    if [ "$current" = "$src" ]; then
      echo "✓ already linked: $s"
    else
      echo "⚠️  re-linking: $s (was: $current → now: $src)"
      rm "$target"
      ln -s "$src" "$target"
    fi
  elif [ -e "$target" ]; then
    echo "❌ $target exists but is not a symlink — refusing to overwrite"
    exit 1
  else
    ln -s "$src" "$target"
    echo "✅ linked: $s → $src"
  fi
done

echo ""
echo "== Locking config.py (DGX credentials) =="
echo ""

for s in "${SECRET_SKILLS[@]}"; do
  cfg="$REPO/$s/config.py"
  if [ -f "$cfg" ]; then
    chmod 600 "$cfg"
    echo "🔒 chmod 600: $cfg"
  else
    echo "(skip: $cfg not present — create it with DGX credentials before using $s)"
  fi
done

echo ""
echo "== Done =="
echo ""
echo "Restart Claude Code in $PROJECT and invoke ar2:skill-overview to verify."
echo ""
echo "Installed symlinks:"
ls -la "$PROJECT/.claude/skills/" | grep "ar2:"
