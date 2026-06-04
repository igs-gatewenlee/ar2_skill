#!/usr/bin/env bash
# install-to.sh — DEPRECATED (2026-06-04)
#
# ar2-skills has migrated from the symlink deployment model to a Claude Code
# **plugin** (name=ar2). The old `.claude/skills/ar2:*` symlink approach (and
# the colon-bearing directory names it required) is gone — those directories
# break `git checkout` on Windows (core.protectNTFS).
#
# Install via the bundled local-path marketplace instead (in Claude Code):
#
#   /plugin marketplace add /Users/gatewenlee/Code/ar2-skills
#   /plugin install ar2@ar2-marketplace
#
# After editing source, marketplace installs are copy-to-cache — run
# `/plugin update ar2` (bump version in .claude-plugin/plugin.json), or use
# `claude --plugin-dir /Users/gatewenlee/Code/ar2-skills` + `/reload-plugins`
# for live development. See README.md.

echo "⛔ install-to.sh is DEPRECATED — ar2-skills is now a Claude Code plugin."
echo ""
echo "Install via the bundled marketplace (run inside Claude Code):"
echo "   /plugin marketplace add $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "   /plugin install ar2@ar2-marketplace"
echo ""
echo "See README.md (Install section) for dev-mode (--plugin-dir) details."
exit 1
