"""Entry: refetch ar2:* family overview.

Scans → parses → renders → writes cache HTML → opens.
"""

import sys
from pathlib import Path

from opener import open_file
from parser import parse_overview
from renderer import render
from scanner import WorkspaceMissing, list_skills

# XDG-style cache (cross-project, doesn't pollute source repo).
CACHE_DIR = Path("~/.cache/ar2-skill-overview").expanduser()
CACHE_PATH = CACHE_DIR / "overview.html"
SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_DIR / "templates" / "overview-template.html"


def _log(msg: str) -> None:
    """Single-line progress log to stderr (refetch is interactive enough)."""
    print(msg, file=sys.stderr)


def main() -> int:
    _log("== ar2:skill-overview refetch ==")

    try:
        skills = list_skills()
    except WorkspaceMissing as exc:
        _log(str(exc))
        return 2

    _log(f"找到 {len(skills)} 個 ar2:* skill")

    overviews = [parse_overview(s) for s in skills]
    ok_count = sum(1 for o in overviews if o.parse_state == "ok")
    _log(f"  OK: {ok_count} · 待補/損壞: {len(overviews) - ok_count}")

    if not TEMPLATE_PATH.exists():
        _log(f"找不到 template: {TEMPLATE_PATH}")
        return 3

    html_str = render(overviews, TEMPLATE_PATH)

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(html_str, encoding="utf-8")
    except OSError as exc:
        # EH-6: cache 目錄不可寫
        _log(f"無法寫 cache: {exc}")
        return 3

    _log(f"✅ Cache 已生成：{CACHE_PATH}")
    open_file(CACHE_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
