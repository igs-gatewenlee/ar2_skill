"""Batch run for gen --plan / --preset (BC-13, BC-14, BC-15, BC-16, BC-17).

Loads plan, expands items, submits all to ComfyUI in single SSH session
(12-zodiac verified pattern), polls outputs, SCPs back, writes history.jsonl.

EH-7  ComfyUI rejects single item → record items_failed, continue.
EH-10 SCP single failure → record, continue (ssh_client now retries
      transient errors internally before raising).
EH-12 Queue pre-clear API failure → log warning, continue (best-effort).
BC-17 Exit codes: 0 = all OK, 1 = SSH conn failure, 2 = workflow rejected
      (the whole batch can't even submit), 3 = partial failure.
EH-9  Ctrl-C during polling → detach, training continues on DGX.
"""

from __future__ import annotations

import datetime
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import HOST, INPUT_DIR, OUTPUT_DIR, LOCAL_OUTPUT_DIR_NAME  # noqa: E402
from ssh_client import ensure_tunnel, ssh_exec, scp_get, scp_put  # noqa: E402
import comfyui_api as api  # noqa: E402
from workflow_params import inject, WorkflowParamError  # noqa: E402
import plan_loader  # noqa: E402


def run_plan(plan_id: str, plans_dir: Path, items_spec: str | None = None) -> int:
    """Entry for `gen --plan {id}`. Optional items_spec filters subset."""
    loaded = plan_loader.load_working(plans_dir, plan_id)
    if items_spec:
        loaded = plan_loader.filter_items(loaded, items_spec)
    history_path = plans_dir / f"{plan_id}.history.jsonl"
    return _run(loaded, history_path, plans_dir, run_dir_name=plan_id)


def run_preset(
    preset_id: str,
    presets_dir: Path,
    plans_dir: Path,
    items_spec: str | None = None,
) -> int:
    """Entry for `gen --preset {id}`. Optional items_spec filters subset."""
    loaded = plan_loader.load_preset(presets_dir, preset_id)
    if items_spec:
        loaded = plan_loader.filter_items(loaded, items_spec)
    ts = datetime.datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    run_dir_name = f"{preset_id}_{ts}"
    history_dir = plans_dir / "preset_runs"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{run_dir_name}.history.jsonl"
    return _run(loaded, history_path, plans_dir, run_dir_name=run_dir_name)


def _run(
    loaded: plan_loader.LoadedPlan,
    history_path: Path,
    plans_dir: Path,
    run_dir_name: str,
) -> int:
    workflow_path = _resolve_workflow(loaded.workflow)
    workflow_template = json.loads(workflow_path.read_text())
    workflow_template = plan_loader.strip_workflow_metadata(workflow_template)

    print(f"== ar2:dgx-comfyui-gen --{loaded.mode} @ {HOST} ==")
    print(f"  workflow: {workflow_path.name}")
    print(f"  items: {len(loaded.items)}")
    print(f"  run_dir: {run_dir_name}")
    print()

    print("Ensuring SSH tunnel...", flush=True)
    ensure_tunnel()

    # EH-12: best-effort clear any stale queue items from a previous run
    # before starting this batch. Placement note: before _upload_face_ref so
    # face_ref upload failure doesn't waste a queue-clear cycle.
    _clear_stale_queue()

    # R-2 code fix: upload face_ref once before batch submit
    face_ref_filename = _upload_face_ref(loaded.face_ref, run_dir_name)

    started_at = _now_tz()
    started_ts = time.time()

    submissions = _submit_all(workflow_template, loaded, run_dir_name,
                              face_ref_filename)
    succeeded_prompts = [s for s in submissions if s["prompt_id"]]
    print(f"\nSubmitted {len(succeeded_prompts)}/{len(loaded.items)} items.")

    if not succeeded_prompts:
        print("❌ all submissions failed; aborting.")
        _write_history(history_path, loaded, run_dir_name,
                       started_at, submissions, downloaded=[])
        return 2

    # Poll + SCP per prompt sequentially (ComfyUI queues anyway).
    local_root = Path.cwd() / LOCAL_OUTPUT_DIR_NAME / run_dir_name
    local_root.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []
    print(f"\nPolling /history + SCP → {local_root}/ ...")
    print("  (Ctrl-C to detach; jobs continue on DGX)")
    try:
        for sub in succeeded_prompts:
            _process_prompt(sub, local_root, run_dir_name, downloaded)
    except KeyboardInterrupt:
        print("\n⚠️  detached from polling; DGX continues running queued items.")
        return 1

    elapsed = time.time() - started_ts
    print(f"\n✅ Done in {_humanize(elapsed)}")
    print(f"  succeeded: {len(downloaded)}/{len(loaded.items)}")

    _write_history(history_path, loaded, run_dir_name,
                   started_at, submissions, downloaded)

    # BC-17 exit code
    failed = len(loaded.items) - len(downloaded)
    return 3 if failed > 0 else 0


def _clear_stale_queue() -> None:
    """EH-12: best-effort clear of any pending+running ComfyUI items.

    If /queue check or POST fails, log a warning and continue. Never raises —
    queue cleanup is a courtesy, not a correctness requirement.
    """
    size = api.get_queue_size()
    if size is None:
        print("⚠️  queue check failed, skipping pre-clear", flush=True)
        return
    pending, running = size
    total = pending + running
    if total == 0:
        return
    print(f"⚠️  Found {total} stale queue items ({pending} pending, "
          f"{running} running), clearing...", flush=True)
    if not api.clear_queue():
        print("⚠️  queue clear POST failed, continuing anyway", flush=True)


def _upload_face_ref(face_ref_local: str | None, run_dir_name: str) -> str | None:
    """R-2 code fix: propagate plan.face_ref. Upload once before batch.

    Returns the basename for inject(), or None if no face_ref configured.
    Skips upload if face_ref equals the sanitized placeholder (preset case).
    """
    if not face_ref_local:
        return None
    if face_ref_local.startswith("<") and face_ref_local.endswith(">"):
        # sanitized placeholder, e.g. "<set face_ref locally>" — preset case
        print(f"⚠️  face_ref is placeholder '{face_ref_local}'; set it locally "
              "before --preset, or fork with --from-preset to customize")
        return None
    local = Path(face_ref_local).expanduser().resolve()
    if not local.exists():
        print(f"❌ face_ref not found: {local}")
        raise FileNotFoundError(face_ref_local)
    remote_dir = f"{INPUT_DIR}/{run_dir_name}"
    ssh_exec(f"mkdir -p {remote_dir}")
    remote_path = f"{remote_dir}/{local.name}"
    print(f"Uploading face_ref → {remote_path} ...", flush=True)
    scp_put(local, remote_path)
    return local.name


def _submit_all(
    workflow_template: dict,
    loaded: plan_loader.LoadedPlan,
    run_dir_name: str,
    face_ref_filename: str | None,
) -> list[dict]:
    """Submit each item; tolerate per-item failure (EH-7)."""
    submissions: list[dict] = []
    for item in loaded.items:
        tag = f"  [{item.index:02d}] {item.slug}"
        try:
            patched = inject(
                workflow_template,
                prompt=item.final_prompt,
                negative_prompt=(loaded.negative or None),
                seed=item.seed,
                steps=loaded.steps,
                batch_size=1,
                width=loaded.size[0],
                height=loaded.size[1],
                face_ref_filename=face_ref_filename,
                output_subdir=run_dir_name,
                filename_prefix_override=item.filename_prefix,
            )
        except WorkflowParamError as e:
            print(f"{tag}: inject failed: {e}")
            submissions.append(
                {"item": item, "prompt_id": None, "error": f"inject: {e}"}
            )
            continue
        try:
            prompt_id, queue_n, _ = api.submit_prompt(patched, str(uuid.uuid4()))
        except (api.WorkflowRejected, api.ComfyUIError) as e:
            print(f"{tag}: ComfyUI rejected: {e}")
            submissions.append({
                "item": item,
                "prompt_id": None,
                "error": f"reject: {type(e).__name__}",
            })
            continue
        print(f"{tag}: prompt_id={prompt_id[:8]}... queue={queue_n}")
        submissions.append(
            {"item": item, "prompt_id": prompt_id, "queue": queue_n}
        )
    return submissions


def _process_prompt(
    sub: dict,
    local_root: Path,
    run_dir_name: str,
    downloaded: list[str],
) -> None:
    item = sub["item"]
    tag = f"  [{item.index:02d}] {item.slug}"
    try:
        outputs = api.wait_for_completion(
            sub["prompt_id"], poll_interval=2.0, timeout=900.0,
        )
    except api.ComfyUIError as e:
        print(f"{tag}: wait failed: {e}")
        sub["error"] = f"wait: {e}"
        return
    files = api.list_output_files(outputs)
    if not files:
        print(f"{tag}: no output files")
        sub["error"] = "no-output"
        return
    for filename, subfolder in files:
        remote = f"{OUTPUT_DIR}/{subfolder}/{filename}".replace("//", "/")
        # Preserve subdir structure under local_root (e.g. ch1/, ch2/ for
        # chapter-encoded slugs). Strip the run_dir_name prefix that ComfyUI
        # echoes back in subfolder.
        rel_sub = subfolder or ""
        prefix = f"{run_dir_name}/"
        if rel_sub.startswith(prefix):
            rel_sub = rel_sub[len(prefix):]
        elif rel_sub == run_dir_name:
            rel_sub = ""
        target_dir = local_root / rel_sub if rel_sub else local_root
        target_dir.mkdir(parents=True, exist_ok=True)
        local = target_dir / filename
        try:
            scp_get(remote, local)
        except Exception as e:  # EH-10
            print(f"{tag}: SCP failed: {e}")
            sub["error"] = f"scp: {e}"
            return
        downloaded.append(str(local))
        print(f"{tag}: {(rel_sub + '/' if rel_sub else '') + filename}")


def _write_history(
    history_path: Path,
    loaded: plan_loader.LoadedPlan,
    run_dir_name: str,
    started_at: str,
    submissions: list[dict],
    downloaded: list[str],
) -> None:
    """EH-11: history.jsonl uses O_APPEND single-line write."""
    succeeded = sum(
        1 for s in submissions if s["prompt_id"] and "error" not in s
    )
    finished_at = _now_tz()
    prompt_records = [
        {
            "slug": s["item"].slug,
            "prompt_id": s.get("prompt_id"),
            "failed": "error" in s,
        }
        for s in submissions
    ]
    record = {
        "run_id": run_dir_name,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": _duration(started_at, finished_at),
        "mode": loaded.mode,
        "items_total": len(loaded.items),
        "items_succeeded": succeeded,
        "items_failed": len(loaded.items) - succeeded,
        "comfyui_prompt_ids": prompt_records,
        "output_dir": str(Path(LOCAL_OUTPUT_DIR_NAME) / run_dir_name),
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _now_tz() -> str:
    """Delegate to plan_schema.now_iso for single source of truth (R-1 fix)."""
    return plan_loader._import_plan_schema().now_iso()


def _resolve_workflow(workflow: str) -> Path:
    p = Path(workflow)
    if p.is_absolute() and p.exists():
        return p
    skill_dir = Path(__file__).resolve().parent.parent
    bundled = skill_dir / "workflows" / f"{workflow}.json"
    if bundled.exists():
        return bundled
    raise FileNotFoundError(f"workflow not found: {workflow}")


def _duration(a: str, b: str) -> float:
    da = datetime.datetime.fromisoformat(a)
    db = datetime.datetime.fromisoformat(b)
    return (db - da).total_seconds()


def _humanize(s: float) -> str:
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s / 60:.1f}m"
    return f"{s / 3600:.1f}h"
