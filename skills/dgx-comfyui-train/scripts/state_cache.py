"""Local cache for training run state.

One JSON file per run_id: ~/.cache/ar2-dgx-comfyui-train/{run_id}.json

State lifecycle (plan v1 Section 11.1):
  pending → running → finished → deployed | failed
                              ↘ crashed (PID died but state stale)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CACHE_DIR  # noqa: E402


def _cache_root() -> Path:
    root = Path(CACHE_DIR).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_path(run_id: str) -> Path:
    return _cache_root() / f"{run_id}.json"


def write(run_id: str, payload: dict) -> Path:
    path = cache_path(run_id)
    payload.setdefault("run_id", run_id)
    payload["updated_at"] = time.time()
    path.write_text(json.dumps(payload, indent=2))
    return path


def update(run_id: str, **fields) -> dict:
    """Merge fields into existing cache entry. Returns the merged dict."""
    existing = read(run_id) or {}
    existing.update(fields)
    write(run_id, existing)
    return existing


def read(run_id: str) -> dict | None:
    path = cache_path(run_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_recent(limit: int = 10) -> list[dict]:
    """Return up to `limit` most recent runs, sorted by updated_at desc."""
    root = _cache_root()
    entries: list[dict] = []
    for p in root.glob("*.json"):
        try:
            entries.append(json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    entries.sort(key=lambda e: e.get("updated_at", 0), reverse=True)
    return entries[:limit]
