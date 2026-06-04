"""Main entry for ar2:dgx-comfyui-train.

Modes:
  python train.py --train ...      → start new training (default if --status absent)
  python train.py --status [id]    → show status of a run (last if no id)
"""

from __future__ import annotations

import argparse
import datetime
import secrets
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    HOST,
    AITK_ROOT,
    AITK_RUN_PY,
    FLUX_BASE_PATH,
    TRAINING_ROOT,
    COMFYUI_LORAS_DIR,
    LOCAL_OUTPUT_DIR_NAME,
    MIN_VRAM_FREE_MB,
    MIN_DISK_FREE_GB,
)
from ssh_client import ssh_exec, scp_put, scp_get  # noqa: E402
import dataset_validator as dv  # noqa: E402
import trainer  # noqa: E402
import sanity_check as sc  # noqa: E402
import state_cache as cache  # noqa: E402
from log_parser import parse_step_line, is_complete  # noqa: E402


# ---------- helpers ----------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="train.py")
    p.add_argument("--status", nargs="?", const="LATEST", default=None,
                   help="Show status of a run. Pass run_id or omit for latest.")
    p.add_argument("--dataset",
                   help="Local dataset dir (containing image + .txt pairs). "
                        "Required for --train mode.")
    p.add_argument("--tag", default=None,
                   help="Run tag. Default: {HHMMSS}_{nonce}")
    p.add_argument("--preset", default="character_flux",
                   help="Preset name (without .yaml) under presets/")
    p.add_argument("--check", action="store_true",
                   help="Pre-flight via ar2:dgx-comfyui-check (default: off)")
    p.add_argument("--backup", action="store_true",
                   help="After deploy, SCP the LoRA back to local outputs/")
    p.add_argument("--poll-interval", type=float, default=5.0,
                   help="Seconds between log polls (default: 5)")
    return p.parse_args()


def make_tag_and_date(tag: str | None) -> tuple[str, str]:
    now = datetime.datetime.now()
    date = now.strftime("%Y%m%d")
    if not tag:
        tag = f"{now.strftime('%H%M%S')}_{secrets.token_hex(2)}"
    return tag, date


def humanize(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{int(s // 60)}m {int(s % 60)}s"
    return f"{int(s // 3600)}h {int((s % 3600) // 60)}m"


def resolve_tag_conflict(tag: str, date_str: str) -> str:
    """If {tag}_{date_str}.safetensors already exists, auto-append _v2/v3/..."""
    base = tag
    for suffix in ["", "_v2", "_v3", "_v4", "_v5", "_v6"]:
        candidate = f"{base}{suffix}"
        dest = f"{COMFYUI_LORAS_DIR}/{candidate}_{date_str}.safetensors"
        r = ssh_exec(f"test -e {dest} && echo EXISTS || true")
        if r.stdout.strip() != "EXISTS":
            if suffix:
                print(f"⚠️  tag conflict; auto-renamed: {base} → {candidate}")
            return candidate
    raise RuntimeError(
        f"too many tag collisions for {base} on {date_str}; bump manually"
    )


def preflight_train() -> bool:
    """Required train-specific pre-flight (always runs, not opt-in)."""
    print("[pre-flight] checking DGX training environment...", flush=True)

    # 1. ai-toolkit exists
    r = ssh_exec(f"test -f {AITK_RUN_PY} && echo OK")
    if r.stdout.strip() != "OK":
        print(f"❌ ai-toolkit not found at {AITK_RUN_PY}")
        return False

    # 2. Flux base model exists
    r = ssh_exec(f"test -d {FLUX_BASE_PATH} && echo OK")
    if r.stdout.strip() != "OK":
        print(f"❌ Flux base model not found at {FLUX_BASE_PATH}")
        return False

    # 3. VRAM
    r = ssh_exec(
        "nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits"
    )
    if r.returncode != 0:
        print(f"❌ nvidia-smi failed: {r.stderr.strip()}")
        return False
    parts = [p.strip() for p in r.stdout.strip().split(",")]
    used_mb = int(parts[0])
    free_mb = int(parts[1])
    print(f"  GPU: used {used_mb} MiB, free {free_mb} MiB")
    if free_mb < MIN_VRAM_FREE_MB:
        print(f"❌ VRAM insufficient: need ≥ {MIN_VRAM_FREE_MB} MiB free")
        return False
    if used_mb > 0:
        print(f"  ⚠️  GPU is in use by another process (used {used_mb} MiB), "
              f"but free VRAM is sufficient — proceeding")

    # 4. Disk
    r = ssh_exec("df -BG /root | tail -1 | awk '{print $4}' | tr -d 'G'")
    if r.returncode == 0:
        free_gb = int(r.stdout.strip() or 0)
        print(f"  disk: {free_gb} GB free on /root")
        if free_gb < MIN_DISK_FREE_GB:
            print(f"❌ disk insufficient: need ≥ {MIN_DISK_FREE_GB} GB free")
            return False

    print("  ✅ train pre-flight passed")
    return True


def preflight_check_skill() -> bool:
    """Opt-in: invoke ar2:dgx-comfyui-check."""
    # sibling skill co-located in plugin skills/ (train/scripts/ → train/ → skills/)
    check_skill = Path(__file__).resolve().parent.parent.parent / "dgx-comfyui-check"
    inspect_py = check_skill / "scripts" / "inspect.py"
    if not inspect_py.exists():
        print(f"⚠️  --check requested but {inspect_py} not found, skipping")
        return True
    print("Running --check pre-flight via -check skill...")
    r = subprocess.run([sys.executable, str(inspect_py)])
    return r.returncode == 0


def upload_dataset(local_dir: Path, workspace: str, run_id: str) -> None:
    """Tar local dataset, SCP, untar on DGX."""
    print(f"Packaging dataset {local_dir} ...", flush=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            for p in sorted(local_dir.iterdir()):
                if p.name.startswith("."):
                    continue
                if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".txt"}:
                    tar.add(p, arcname=p.name)

        remote_tar = f"/tmp/{run_id}.tar.gz"
        print(f"Uploading dataset → {remote_tar} ...", flush=True)
        scp_put(tmp_path, remote_tar, timeout=600)

        remote_data = f"{workspace}/data"
        print(f"Extracting to {remote_data} ...", flush=True)
        r = ssh_exec(
            f"mkdir -p {remote_data} && "
            f"tar -xzf {remote_tar} -C {remote_data} && "
            f"rm {remote_tar}"
        )
        if r.returncode != 0:
            raise RuntimeError(f"dataset extract failed: {r.stderr.strip()}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------- train mode ----------

def cmd_train(args: argparse.Namespace) -> int:
    if not args.dataset:
        print("❌ --dataset is required for training")
        return 1

    local_dataset = Path(args.dataset).expanduser().resolve()

    # 1. dataset validation
    print(f"Validating dataset: {local_dataset}", flush=True)
    val = dv.validate(local_dataset)
    if not val.ok:
        print(f"❌ dataset validation failed ({val.image_count} images):")
        for b in val.blockers:
            print(f"  - {b}")
        return 1
    for w in val.warnings:
        print(f"  ⚠️  {w}")
    print(f"  ✅ {val.image_count} images, captions paired")

    # 2. tag + date
    tag, date_str = make_tag_and_date(args.tag)
    print(f"\n== ar2:dgx-comfyui-train @ {HOST} ==")
    print(f"  preset: {args.preset}")
    print(f"  dataset: {local_dataset} ({val.image_count} images)")
    print(f"  tag (initial): {tag}")
    print(f"  date: {date_str}")

    # 3. preflight self (always) + opt-in check
    if not preflight_train():
        return 1
    if args.check:
        if not preflight_check_skill():
            print("❌ --check failed; aborting")
            return 1

    # 4. resolve tag conflict against existing LoRAs
    tag = resolve_tag_conflict(tag, date_str)
    workspace = f"{TRAINING_ROOT}/{date_str}_{tag}"
    config_name = f"{tag}_{date_str}"
    print(f"  final tag: {tag}")
    print(f"  workspace: {workspace}")

    # 5. prep cache entry
    run_id = str(uuid.uuid4())
    cache.write(run_id, {
        "state": "pending",
        "host": HOST,
        "tag": tag,
        "date": date_str,
        "config_name": config_name,
        "workspace": workspace,
        "preset": args.preset,
        "dataset_local": str(local_dataset),
        "dataset_image_count": val.image_count,
        "started_at": None,
        "pid": None,
        "log_path": None,
    })
    print(f"  run_id: {run_id}")

    # 6. upload dataset
    upload_dataset(local_dataset, workspace, run_id)

    # 7. generate + upload config
    preset_text = trainer.load_preset(args.preset)
    config_text = trainer.generate_config(
        preset_text, tag=tag, date_str=date_str, workspace=workspace,
    )
    remote_config = trainer.upload_config(config_text, workspace)
    print(f"  config: {remote_config}")

    # 8. launch
    print("\nLaunching training (background)...", flush=True)
    pid, log_path = trainer.launch(workspace, remote_config)
    print(f"  PID: {pid}", flush=True)
    print(f"  log: {log_path}", flush=True)
    started = time.time()
    cache.update(run_id,
                 state="running", started_at=started, pid=pid, log_path=log_path)

    # 9. poll log
    print(f"\nPolling log every {args.poll_interval}s. Ctrl-C to detach "
          f"(training will continue on DGX).\n", flush=True)
    offset = 0
    try:
        while trainer.is_alive(pid):
            time.sleep(args.poll_interval)
            chunk, offset = trainer.stream_log(log_path, since_byte=offset)
            if not chunk:
                continue
            for line in chunk.splitlines():
                m = parse_step_line(line)
                if m:
                    elapsed = time.time() - started
                    print(f"  [{humanize(elapsed)}] step {m.step}/{m.total_steps}, "
                          f"loss={m.loss:.4f}"
                          + (f", lr={m.lr:.2e}" if m.lr else ""),
                          flush=True)
                if is_complete(line):
                    print(f"  [done] {line.strip()}", flush=True)
                    break
    except KeyboardInterrupt:
        print("\n⚠️  detached from log polling; training continues on DGX")
        print(f"  resume with: train.py --status {run_id}")
        return 0

    # 10. process ended; do sanity check
    print("\nTraining process ended. Running sanity check...", flush=True)
    elapsed = time.time() - started
    cache.update(run_id, state="finished", finished_at=time.time(),
                 elapsed_sec=elapsed)

    lora_path = trainer.find_latest_lora_checkpoint(workspace, config_name)
    if lora_path is None:
        print(f"❌ no LoRA checkpoint found in {workspace}/output/{config_name}/")
        print("   (ai-toolkit failed to save — check log for errors)")
        cache.update(run_id, state="failed",
                     failure_reason="no lora checkpoint produced")
        return 2
    print(f"  latest checkpoint: {Path(lora_path).name}", flush=True)
    result = sc.check(lora_path, log_path)

    print(f"  total steps logged: {result.total_steps}")
    if result.final_loss is not None:
        print(f"  final loss: {result.final_loss:.4f}")
    if result.min_loss is not None:
        print(f"  min loss: {result.min_loss:.4f} @ step {result.min_loss_step}")

    for w in result.warnings:
        print(f"  ⚠️  {w}")

    if not result.passed:
        print("\n❌ sanity check FAILED:")
        for b in result.blockers:
            print(f"  - {b}")
        cache.update(run_id, state="failed", sanity_blockers=result.blockers,
                     lora_path=lora_path)
        print(f"\nLoRA left at: {lora_path}")
        print(f"Log at: {log_path}")
        return 2

    # 11. deploy
    print("\n✅ sanity check passed; deploying...", flush=True)
    dest_name = f"{config_name}.safetensors"
    ok, msg = sc.deploy(lora_path, dest_name)
    if not ok:
        print(f"❌ deploy failed: {msg}")
        cache.update(run_id, state="failed", failure_reason=msg)
        return 2

    deployed_path = msg
    print(f"  deployed: {deployed_path}")
    cache.update(run_id, state="deployed", deployed_path=deployed_path)

    # 12. optional backup
    if args.backup:
        local_root = Path.cwd() / LOCAL_OUTPUT_DIR_NAME / f"{date_str}_{tag}"
        local_root.mkdir(parents=True, exist_ok=True)
        local_lora = local_root / dest_name
        print(f"\nBacking up LoRA → {local_lora} ...", flush=True)
        scp_get(deployed_path, local_lora, timeout=600)
        print(f"  ✅ {local_lora}")

    # 13. final report
    print(f"\n✅ Done in {humanize(elapsed)}")
    print(f"  LoRA: {deployed_path}")
    print(f"  run_id: {run_id}")
    return 0


# ---------- status mode ----------

def cmd_status(args: argparse.Namespace) -> int:
    target = args.status
    if target == "LATEST":
        runs = cache.list_recent(limit=10)
        if not runs:
            print("(no cached runs)")
            return 0
        latest = runs[0]
        target = latest["run_id"]
        print(f"Latest run: {target}\n")

    entry = cache.read(target)
    if entry is None:
        print(f"❌ no cached entry for run_id {target}")
        return 1

    state = entry.get("state", "?")
    print(f"== run {target} ==")
    print(f"  state: {state}")
    print(f"  tag: {entry.get('tag')} (config_name: {entry.get('config_name')})")
    print(f"  workspace: {entry.get('workspace')}")
    started_at = entry.get("started_at")
    if started_at:
        print(f"  started: {datetime.datetime.fromtimestamp(started_at)}")

    pid = entry.get("pid")
    log_path = entry.get("log_path")

    if state == "running" and pid:
        if trainer.is_alive(pid):
            print(f"  PID {pid} alive")
            tail = trainer.tail_log(log_path, lines=20)
            print("  recent log:")
            for line in tail.splitlines()[-10:]:
                print(f"    {line}")
        else:
            print(f"  ⚠️  PID {pid} not alive; updating state to crashed")
            cache.update(target, state="crashed")

    elif state in ("deployed", "failed"):
        elapsed = entry.get("elapsed_sec")
        if elapsed:
            print(f"  duration: {humanize(elapsed)}")
        if state == "deployed":
            print(f"  deployed: {entry.get('deployed_path')}")
        else:
            print(f"  failure: {entry.get('failure_reason') or 'see blockers'}")
            for b in entry.get("sanity_blockers", []):
                print(f"    - {b}")
            print(f"  LoRA still at: {entry.get('lora_path')}")
            print(f"  log: {log_path}")

    return 0


def main() -> int:
    args = parse_args()
    if args.status is not None:
        return cmd_status(args)
    return cmd_train(args)


if __name__ == "__main__":
    raise SystemExit(main())
