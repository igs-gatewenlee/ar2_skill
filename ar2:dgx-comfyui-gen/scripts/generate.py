"""Main entry for ar2:dgx-comfyui-gen.

Orchestrates plan v1 Section 4 steps 1-13:
1. load config + workflow JSON
2. deep-copy + inject params
3. auto-patch LoadImage / SaveImage subdir
5. opt-in -check pre-flight
6. ensure tunnel
7. upload inputs
8. POST /prompt, get prompt_id, queue position
9. poll /history until outputs
10. parse outputs
11. SCP back to local
12. report
13. error reporting via connection.md fault tree
"""

from __future__ import annotations

import argparse
import datetime
import json
import secrets
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    HOST,
    INPUT_DIR,
    OUTPUT_DIR,
    LOCAL_OUTPUT_DIR_NAME,
    CACHE_DIR,
    LAST_RUN_FILE,
)
from ssh_client import ssh_exec, ensure_tunnel, scp_get, scp_put  # noqa: E402
import comfyui_api as api  # noqa: E402
from workflow_params import inject, WorkflowParamError  # noqa: E402


SKILL_DIR = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = SKILL_DIR / "workflows"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="generate.py",
        description="Generate images via DGX ComfyUI workflow",
    )
    p.add_argument(
        "--workflow",
        default="flux_basic",
        help="Bundled workflow name (without .json) OR absolute path to .json. "
        "Default: flux_basic",
    )
    p.add_argument("--prompt", required=True, help="Positive prompt")
    p.add_argument("--negative-prompt", default=None)
    p.add_argument("--seed", type=int, default=None,
                   help="Default: random 32-bit int")
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--batch", type=int, default=None,
                   help="Number of images in one run (same prompt, sequential seeds via batch_size)")
    p.add_argument("--width", type=int, default=None,
                   help="Output image width (default: workflow's value, typically 1024)")
    p.add_argument("--height", type=int, default=None,
                   help="Output image height (default: workflow's value, typically 1024)")
    p.add_argument("--face-ref", default=None,
                   help="Local path to face_ref image (will be uploaded and "
                        "all LoadImage nodes will reference it)")
    p.add_argument("--tag", default=None,
                   help="Run tag for subdir naming. Default: {HHMMSS}_{nonce}")
    p.add_argument("--check", action="store_true",
                   help="Pre-flight via ar2:dgx-comfyui-check (default: off)")
    p.add_argument("--poll-interval", type=float, default=1.0)
    p.add_argument("--timeout", type=float, default=1800.0,
                   help="Max seconds to wait for completion")
    return p.parse_args()


def resolve_workflow_path(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.is_absolute() and p.exists():
        return p
    bundled = WORKFLOWS_DIR / f"{name_or_path}.json"
    if bundled.exists():
        return bundled
    raise FileNotFoundError(
        f"workflow not found: tried {p.resolve()} and {bundled}"
    )


def make_tag_subdir(tag: str | None) -> tuple[str, str]:
    """Return (tag, subdir) where subdir is {YYYYMMDD}_{tag}."""
    now = datetime.datetime.now()
    date = now.strftime("%Y%m%d")
    if not tag:
        tag = f"{now.strftime('%H%M%S')}_{secrets.token_hex(2)}"
    return tag, f"{date}_{tag}"


def random_seed() -> int:
    return int.from_bytes(secrets.token_bytes(4), "big")


def preflight_check() -> bool:
    """Invoke ar2:dgx-comfyui-check skill. Returns True if it exits 0."""
    check_skill = Path.home() / ".claude" / "skills" / "ar2:dgx-comfyui-check"
    inspect_py = check_skill / "scripts" / "inspect.py"
    if not inspect_py.exists():
        print(f"⚠️  --check requested but {inspect_py} not found, skipping")
        return True
    import subprocess
    print("Running pre-flight via -check...")
    r = subprocess.run([sys.executable, str(inspect_py)])
    return r.returncode == 0


def write_cache(payload: dict) -> Path:
    cache_dir = Path(CACHE_DIR).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / LAST_RUN_FILE
    path.write_text(json.dumps(payload, indent=2))
    return path


def humanize_seconds(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{int(s // 60)}m {int(s % 60)}s"
    return f"{int(s // 3600)}h {int((s % 3600) // 60)}m"


def main() -> int:
    args = parse_args()

    # --- 1. load workflow ---
    workflow_path = resolve_workflow_path(args.workflow)
    workflow = json.loads(workflow_path.read_text())

    # --- 3. resolve tag + subdir ---
    tag, subdir = make_tag_subdir(args.tag)
    seed = args.seed if args.seed is not None else random_seed()

    print(f"== ar2:dgx-comfyui-gen @ {HOST} ==")
    print(f"  workflow: {workflow_path.name}")
    print(f"  tag: {tag}")
    print(f"  subdir: {subdir}")
    print(f"  seed: {seed}")
    print()

    # --- 5. opt-in pre-flight ---
    if args.check:
        if not preflight_check():
            print("❌ pre-flight failed; aborting")
            return 1

    # --- 6. ensure tunnel ---
    print("Ensuring SSH tunnel...", flush=True)
    ensure_tunnel()

    # --- 7. upload face_ref if given ---
    face_ref_filename: str | None = None
    if args.face_ref:
        local_face = Path(args.face_ref).expanduser().resolve()
        if not local_face.exists():
            print(f"❌ --face-ref not found: {local_face}")
            return 1
        face_ref_filename = local_face.name
        remote_dir = f"{INPUT_DIR}/{subdir}"
        ssh_exec(f"mkdir -p {remote_dir}")
        remote_path = f"{remote_dir}/{face_ref_filename}"
        print(f"Uploading face_ref → {remote_path} ...", flush=True)
        scp_put(local_face, remote_path)

    # --- 2 + 4. deep-copy + inject params + auto-patch LoadImage / SaveImage ---
    try:
        patched = inject(
            workflow,
            prompt=args.prompt,
            negative_prompt=args.negative_prompt,
            seed=seed,
            steps=args.steps,
            batch_size=args.batch,
            width=args.width,
            height=args.height,
            face_ref_filename=face_ref_filename,
            output_subdir=subdir,
        )
    except WorkflowParamError as e:
        print(f"❌ workflow param injection failed: {e}")
        return 1

    # --- 8. submit ---
    client_id = str(uuid.uuid4())
    print("Submitting workflow to ComfyUI...", flush=True)
    started = time.time()
    try:
        prompt_id, queue_number, _ = api.submit_prompt(patched, client_id)
    except api.WorkflowRejected as e:
        print(f"❌ workflow rejected by ComfyUI:")
        print(json.dumps(e.node_errors, indent=2))
        return 2
    except api.ComfyUIError as e:
        print(f"❌ {e}")
        print("See references/connection.md for diagnosis.")
        return 1

    print(f"  prompt_id: {prompt_id}")
    if queue_number > 0:
        print(f"  queue position: #{queue_number} (waiting for earlier jobs)")
    else:
        print(f"  queue position: running")

    # --- 9. poll /history ---
    last_msg = 0.0

    def progress(elapsed: float):
        nonlocal last_msg
        if elapsed - last_msg >= 5.0:
            print(f"  ... still running ({humanize_seconds(elapsed)})", flush=True)
            last_msg = elapsed

    try:
        outputs = api.wait_for_completion(
            prompt_id,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            progress_cb=progress,
        )
    except api.ComfyUIError as e:
        print(f"❌ {e}")
        return 1

    elapsed = time.time() - started

    # --- 10. parse outputs ---
    files = api.list_output_files(outputs)
    if not files:
        print(f"❌ workflow completed but produced no images. "
              f"prompt_id={prompt_id}")
        return 2

    # --- 11. SCP back ---
    local_root = Path.cwd() / LOCAL_OUTPUT_DIR_NAME / subdir
    local_root.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {len(files)} image(s) to {local_root} ...", flush=True)
    downloaded: list[Path] = []
    for filename, subfolder in files:
        # ComfyUI returns subfolder relative to OUTPUT_DIR; we patched filename_prefix
        # to "{subdir}/img" so subfolder is typically "{subdir}"
        remote = f"{OUTPUT_DIR}/{subfolder}/{filename}".replace("//", "/")
        local = local_root / filename
        scp_get(remote, local)
        downloaded.append(local)

    # --- 12. report ---
    print()
    print(f"✅ Done in {humanize_seconds(elapsed)}")
    print(f"  files: {len(downloaded)}")
    for p in downloaded:
        print(f"    {p}")
    print(f"  prompt_id: {prompt_id}")
    print(f"  seed: {seed}")
    print(f"  workflow: {workflow_path.name}")

    # --- cache ---
    write_cache({
        "timestamp": time.time(),
        "host": HOST,
        "prompt_id": prompt_id,
        "client_id": client_id,
        "workflow": workflow_path.name,
        "tag": tag,
        "subdir": subdir,
        "seed": seed,
        "params": {
            "prompt": args.prompt,
            "negative_prompt": args.negative_prompt,
            "steps": args.steps,
            "batch": args.batch,
            "face_ref": args.face_ref,
        },
        "files": [str(p) for p in downloaded],
        "elapsed_sec": elapsed,
    })

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
