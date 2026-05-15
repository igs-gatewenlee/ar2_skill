"""Entry: show ar2:* family overview from cache.

BC-11: cache 不存在 → exit 1 提示 refetch
        cache 過期 → 印警告後 open
        cache 不過期 → 直接 open
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from opener import open_file
from scanner import WorkspaceMissing, list_skills

# XDG-style cache (matches refetch.py CACHE_DIR).
CACHE_PATH = Path("~/.cache/ar2-skill-overview/overview.html").expanduser()
REFETCH_SCRIPT = Path(__file__).parent / "refetch.py"
GENERATED_AT_RE = re.compile(r"<!--\s*generated_at:\s*([^>]+?)\s*-->")
SOURCE_FILES = ("OVERVIEW.md", "SKILL.md")


def _suggest_refetch(reason: str) -> None:
    """Print warning + the canonical refetch command to stderr."""
    print(reason, file=sys.stderr)
    print(f"  python3 {REFETCH_SCRIPT}", file=sys.stderr)


def _read_generated_at(cache_path: Path) -> datetime | None:
    """Extract generated_at from HTML head comment. None if missing/corrupt (EH-7)."""
    try:
        head = cache_path.read_text(encoding="utf-8")[:512]
    except Exception:
        return None
    match = GENERATED_AT_RE.search(head)
    if not match:
        return None
    try:
        # ISO8601 may include timezone; fromisoformat handles both
        return datetime.fromisoformat(match.group(1).strip())
    except ValueError:
        return None


def _max_source_mtime(skills) -> datetime:
    """BC-12 + BC-4: max mtime over OVERVIEW.md + SKILL.md in workspace skill dirs.

    Workspace is source of truth (BC-4) — installed paths are not scanned.
    Returns UTC tz-aware datetime so comparison with `gen_at` (also UTC tz-aware
    from ISO marker) is consistent regardless of system local timezone.
    """
    max_ts = 0.0
    for skill in skills:
        if skill.workspace_path is None:
            continue
        for fname in SOURCE_FILES:
            fp = skill.workspace_path / fname
            if fp.exists():
                max_ts = max(max_ts, fp.stat().st_mtime)
    return datetime.fromtimestamp(max_ts or 0, tz=timezone.utc)


def _is_stale(gen_at: datetime | None, max_src: datetime) -> bool:
    """True if cache is older than newest source. Both inputs are UTC tz-aware."""
    if gen_at is None:
        return False  # EH-7 handled separately (no marker → distinct branch)
    return gen_at < max_src


def main() -> int:
    if not CACHE_PATH.exists():
        _suggest_refetch("Cache 不存在。請先執行：")
        return 1

    try:
        skills = list_skills()
    except WorkspaceMissing as exc:
        print(str(exc), file=sys.stderr)
        return 2

    gen_at = _read_generated_at(CACHE_PATH)
    max_src = _max_source_mtime(skills)

    if gen_at is None:
        # EH-7: cache corrupt or old format
        _suggest_refetch("⚠️  Cache 無 generated_at 標記（可能是舊版），建議重整：")
    elif _is_stale(gen_at, max_src):
        _suggest_refetch("⚠️  Cache 可能過期（source 檔被修改過），建議重整：")

    open_file(CACHE_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
