"""Main entry: SSH + health + inventory + compare + report + cache.

Usage:
    python3 inspect.py                      # full inventory (default)
    python3 inspect.py --apply-pulid-patch  # apply PuLID dtype patch only

Output format spec: see plan v1 Section 4.1.
Cache spec:        see plan v1 Section 4.2.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    HOST,
    COMFYUI_ROOT,
    MODELS_DIR,
    OUTPUT_DIR,
    CUSTOM_NODES_DIR,
    TRAINING_DIR,
    CACHE_DIR,
    LAST_INVENTORY_FILE,
)
from ssh_client import ssh_exec, ping_host  # noqa: E402
import pulid_patch  # noqa: E402
from health import run_all as run_health  # noqa: E402


# 13 categories + minimum expected files.
# Keep this in sync with references/models.md "核心必備模型".
EXPECTED: dict[str, list[str]] = {
    "checkpoints": [],
    "diffusion_models": ["flux1-dev.safetensors"],
    "clip": ["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"],
    "vae": ["flux_ae.safetensors"],
    "loras": [],
    "controlnet": [],
    "embeddings": [],
    "upscale_models": [],
    "pulid": ["pulid_flux_v0.9.1.safetensors"],
    "clip_vision": [
        "EVA02_CLIP_L_336_psz14_s6B.safetensors",
        "sigclip_vision_patch14_384.safetensors",
    ],
    "style_models": ["flux1-redux-dev.safetensors"],
    "insightface": [],
    "facerestore_models": [],
}


# --- Inventory ---

def list_models() -> dict[str, list[dict]]:
    """Return {category: [{name, size}, ...]}.

    Only counts top-level files (not nested dirs). Subdirs like
    insightface/models/antelopev2/ are not recursed in v1.
    """
    inventory: dict[str, list[dict]] = {}
    for cat in EXPECTED:
        cat_path = f"{MODELS_DIR}/{cat}"
        r = ssh_exec(
            f"find {cat_path} -maxdepth 1 -type f "
            f"-printf '%f\\t%s\\n' 2>/dev/null"
        )
        items: list[dict] = []
        for line in r.stdout.strip().splitlines():
            if "\t" not in line:
                continue
            name, size_str = line.split("\t", 1)
            try:
                items.append({"name": name, "size": int(size_str)})
            except ValueError:
                continue
        inventory[cat] = items
    return inventory


def compare_to_expected(inventory: dict) -> dict[str, dict]:
    """Returns {category: {"missing": [...], "extra": [...]}}.

    Categories whose EXPECTED list is empty get no "extra" flag (the
    category is open-ended, e.g. user-trained loras).
    """
    diff: dict[str, dict] = {}
    for cat, expected in EXPECTED.items():
        actual = {item["name"] for item in inventory.get(cat, [])}
        expected_set = set(expected)
        missing = sorted(expected_set - actual)
        extra = sorted(actual - expected_set) if expected else []
        if missing or extra:
            diff[cat] = {"missing": missing, "extra": extra}
    return diff


# --- Environment summary ---

def storage_summary() -> dict:
    """Output/ + training/ subdir counts, sizes, and free disk."""
    def count_and_size(path: str) -> tuple[int, int]:
        # Count both subdirs and top-level files. ComfyUI output/ is often
        # files-only (no per-session subdir), so type=d alone hides content.
        r = ssh_exec(
            f"echo \"$(find {path} -maxdepth 1 -mindepth 1 \\( -type d -o -type f \\) 2>/dev/null | wc -l)\"; "
            f"echo \"$(du -sb {path} 2>/dev/null | cut -f1)\""
        )
        out = r.stdout.strip().splitlines()
        n = int(out[0]) if out and out[0].strip().isdigit() else 0
        size = int(out[1]) if len(out) > 1 and out[1].strip().isdigit() else 0
        return n, size

    out_n, out_size = count_and_size(OUTPUT_DIR)
    train_n, train_size = count_and_size(TRAINING_DIR)

    r = ssh_exec("df -BG /root | tail -1 | awk '{print $4}'")
    free = r.stdout.strip() if r.returncode == 0 else "?"

    return {
        "output_entries": out_n,
        "output_bytes": out_size,
        "training_entries": train_n,
        "training_bytes": train_size,
        "free": free,
    }


def version_summary() -> dict:
    """ComfyUI commit + each custom_node commit (short hashes)."""
    r = ssh_exec(
        f"cd {COMFYUI_ROOT} && git rev-parse --short HEAD 2>/dev/null || echo '?'"
    )
    comfy = r.stdout.strip() or "?"

    r = ssh_exec(
        f"for d in {CUSTOM_NODES_DIR}/*/; do "
        f"  name=$(basename \"$d\"); "
        f"  if [ -d \"$d/.git\" ]; then "
        f"    hash=$(cd \"$d\" && git rev-parse --short HEAD 2>/dev/null || echo '?'); "
        f"    echo \"$name $hash\"; "
        f"  fi; "
        f"done"
    )
    nodes: dict[str, str] = {}
    for line in r.stdout.strip().splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            nodes[parts[0]] = parts[1]
    return {"comfyui": comfy, "custom_nodes": nodes}


# --- Format helpers ---

def humanize_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def humanize_ago(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} 秒前"
    if seconds < 3600:
        return f"{int(seconds / 60)} 分鐘前"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} 小時前"
    return f"{seconds / 86400:.1f} 天前"


# --- Report ---

def format_report(
    health: dict,
    inventory: dict,
    diff: dict,
    storage: dict,
    versions: dict,
    last_seen_at: float | None,
) -> str:
    out: list[str] = []
    out.append(f"== ar2:dgx-comfyui-check @ {HOST} ==")

    if last_seen_at:
        ago_sec = time.time() - last_seen_at
        last_str = datetime.fromtimestamp(last_seen_at).strftime("%m/%d %H:%M")
        out.append(f"(上次盤點：{last_str}, {humanize_ago(ago_sec)})")
    else:
        out.append("(首次盤點)")

    out.append("")
    all_healthy = all(c["ok"] for c in health.values())
    out.append("🟢 Health" if all_healthy else "🔴 Health")
    out.append(
        f"  GPU          {'✅' if health['gpu']['ok'] else '❌'} "
        f"{health['gpu']['msg']}"
    )
    out.append(
        f"  ComfyUI proc {'✅' if health['comfyui_process']['ok'] else '❌'} "
        f"{health['comfyui_process']['msg']}"
    )
    out.append(
        f"  ComfyUI API  {'✅' if health['comfyui_api']['ok'] else '❌'} "
        f"{health['comfyui_api']['msg']}"
    )

    total_files = sum(len(items) for items in inventory.values())
    total_size = sum(item["size"] for items in inventory.values() for item in items)
    out.append("")
    out.append(
        f"📦 Models (13 cats / {total_files} files / {humanize_bytes(total_size)})"
    )

    green_cats: list[tuple[str, int, int]] = []
    for cat in EXPECTED:
        items = inventory.get(cat, [])
        cat_size = sum(item["size"] for item in items)
        cat_diff = diff.get(cat)

        if cat_diff is None:
            green_cats.append((cat, len(items), cat_size))
            continue

        emoji = "❌" if cat_diff["missing"] else "⚠️"
        notes: list[str] = []
        if cat_diff["missing"]:
            notes.append(f"missing: {', '.join(cat_diff['missing'])}")
        if cat_diff["extra"]:
            notes.append(f"⚠ {len(cat_diff['extra'])} unexpected")
        note_str = "  ← " + "; ".join(notes) if notes else ""
        size_str = humanize_bytes(cat_size) if cat_size else "—"
        out.append(
            f"  {emoji} {cat:<18s} {len(items)} files, {size_str:>9s}{note_str}"
        )

    if green_cats:
        out.append("")
        out.append(f"  ✅ ({len(green_cats)} 個分類全綠 → 折成統計列)")
        for cat, n, size in green_cats:
            size_str = humanize_bytes(size) if size else "—"
            out.append(f"     {cat:<18s} {n} files, {size_str}")

    out.append("")
    out.append("📊 Environment")
    out.append(f"  ComfyUI @ {versions['comfyui']}")
    if versions["custom_nodes"]:
        nodes_str = ", ".join(
            f"{name}@{h}" for name, h in versions["custom_nodes"].items()
        )
        out.append(f"  custom_nodes: {nodes_str}")
    else:
        out.append("  custom_nodes: (none with .git)")
    out.append(
        f"  output/  {storage['output_entries']} entries, "
        f"{humanize_bytes(storage['output_bytes'])} · "
        f"lora_training/ {storage['training_entries']} entries, "
        f"{humanize_bytes(storage['training_bytes'])} · "
        f"free {storage['free']}"
    )
    out.append(f"  {pulid_patch.status_summary_line()}")
    out.append("==")

    return "\n".join(out)


# --- Cache ---

def load_last_cache() -> dict | None:
    path = Path(CACHE_DIR).expanduser() / LAST_INVENTORY_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_cache(
    inventory: dict, health: dict, versions: dict, storage: dict
) -> None:
    cache_dir = Path(CACHE_DIR).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / LAST_INVENTORY_FILE
    payload = {
        "timestamp": time.time(),
        "host": HOST,
        "inventory": inventory,
        "health": health,
        "env_versions": versions,
        "storage": storage,
    }
    path.write_text(json.dumps(payload, indent=2))


# --- Entry ---

def _apply_pulid_patch_flow() -> int:
    """Standalone flow for --apply-pulid-patch (no inventory).

    No ping_host() preflight here (R-2 fix): apply_patch() already does its
    own SSH probe via check_patch_status(), so an ICMP-only preflight would
    just produce a misleading 'cannot reach' message when ICMP is blocked
    but SSH works.
    """
    print("Applying PuLID dtype-cast patch...", flush=True)
    ok, msg = pulid_patch.apply_patch()
    print(("✅ " if ok else "❌ ") + msg)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ar2:dgx-comfyui-check",
        description="DGX ComfyUI health + inventory; PuLID patch deploy.",
    )
    parser.add_argument(
        "--apply-pulid-patch",
        action="store_true",
        help="Apply the PuLID dtype-cast patch to encoders_flux.py "
        "(idempotent; creates a dated backup of pre-patch content).",
    )
    args = parser.parse_args(argv)

    if args.apply_pulid_patch:
        return _apply_pulid_patch_flow()

    # Preflight: can we reach DGX at all?
    if not ping_host():
        print(
            f"❌ Cannot reach DGX @ {HOST}. "
            f"See references/connection.md for diagnosis."
        )
        return 1

    last = load_last_cache()
    last_seen_at = last["timestamp"] if last else None

    print("Running health checks...", flush=True)
    health = run_health()

    print("Inventorying models...", flush=True)
    inventory = list_models()

    print("Comparing against expected...", flush=True)
    diff = compare_to_expected(inventory)

    print("Gathering storage + version info...", flush=True)
    storage = storage_summary()
    versions = version_summary()

    print()
    print(format_report(health, inventory, diff, storage, versions, last_seen_at))

    write_cache(inventory, health, versions, storage)

    # Non-zero exit if something is broken
    has_unhealthy = not all(c["ok"] for c in health.values())
    has_missing = any(d["missing"] for d in diff.values())
    return 2 if (has_unhealthy or has_missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
