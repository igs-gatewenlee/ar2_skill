"""ai-toolkit YAML config builder + background launcher.

- generate_config(): take preset YAML + caller params, fill placeholders, return text
- launch(): SCP config to DGX, nohup python /root/ai-toolkit/run.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    AITK_RUN_PY,
    FLUX_BASE_PATH,
    TRAINING_ROOT,
)
from ssh_client import ssh_exec, scp_put  # noqa: E402


SKILL_DIR = Path(__file__).resolve().parent.parent
PRESETS_DIR = SKILL_DIR / "presets"


def load_preset(name: str = "character_flux") -> str:
    """Load preset YAML text. `name` is the preset filename without .yaml."""
    path = PRESETS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"preset not found: {path}. Available: "
            f"{[p.stem for p in PRESETS_DIR.glob('*.yaml')]}"
        )
    return path.read_text()


def generate_config(
    preset_text: str,
    *,
    tag: str,
    date_str: str,
    workspace: str,
    overrides: dict | None = None,
) -> str:
    """Fill placeholders in preset YAML. Returns rendered YAML text.

    Placeholders supported:
      {{NAME}}            → {tag}_{date_str}
      {{TAG}}             → tag (used for trigger_word + sample prompt insertion)
      {{TRAINING_FOLDER}} → {workspace}/output
      {{DATASET_FOLDER}}  → {workspace}/data

    `overrides` is reserved for future use (e.g. inject --steps via post-YAML
    string replacement). v1 supports preset-only training.
    """
    name = f"{tag}_{date_str}"
    text = preset_text
    text = text.replace("{{NAME}}", name)
    text = text.replace("{{TAG}}", tag)
    text = text.replace("{{TRAINING_FOLDER}}", f"{workspace}/output")
    text = text.replace("{{DATASET_FOLDER}}", f"{workspace}/data")

    if overrides:
        # v1: not implemented; would parse YAML and patch fields like train.steps
        raise NotImplementedError(
            "CLI overrides not in v1; edit preset YAML or pass custom --preset path"
        )

    return text


def upload_config(config_text: str, workspace: str) -> str:
    """SCP the rendered config to DGX workspace/config.yaml. Returns remote path."""
    remote_path = f"{workspace}/config.yaml"

    # Write locally to temp, then scp
    with tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(config_text)
        tmp_path = tmp.name
    try:
        ssh_exec(f"mkdir -p {workspace}")
        scp_put(tmp_path, remote_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return remote_path


def launch(workspace: str, config_remote_path: str) -> tuple[int, str]:
    """Start ai-toolkit training as a background nohup process on DGX.

    Returns (pid, log_path). Caller writes both to state cache.
    """
    log_path = f"{workspace}/train.log"
    pid_path = f"{workspace}/train.pid"

    # </dev/null on stdin is essential — without it, SSH stays attached to
    # the nohup'd process's inherited stdin and the channel blocks until the
    # background process exits (causing this whole call to time out).
    # Verified empirically against ai-toolkit which doesn't read stdin but
    # still keeps the fd open. setsid further detaches from any tty/job-ctrl.
    cmd = (
        f"cd {workspace} && "
        f"setsid nohup python3 {AITK_RUN_PY} {config_remote_path} "
        f"</dev/null > {log_path} 2>&1 & "
        f"echo $! > {pid_path}"
    )
    r = ssh_exec(cmd, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"failed to launch training: {r.stderr.strip()}")

    # Read back PID
    r = ssh_exec(f"cat {pid_path}", timeout=5)
    pid_str = r.stdout.strip()
    if not pid_str.isdigit():
        raise RuntimeError(f"failed to read PID: '{pid_str}'")

    return int(pid_str), log_path


def is_alive(pid: int) -> bool:
    """Check DGX-side: is the training PID still running?"""
    r = ssh_exec(f"kill -0 {pid} 2>/dev/null && echo ALIVE")
    return r.stdout.strip() == "ALIVE"


def tail_log(log_path: str, lines: int = 200) -> str:
    """Get the last N lines of the DGX-side log."""
    r = ssh_exec(f"tail -n {lines} {log_path}", timeout=15)
    return r.stdout if r.returncode == 0 else ""


def stream_log(log_path: str, since_byte: int = 0) -> tuple[str, int]:
    """Read log content from byte offset to end. Returns (text, new_offset).

    Used for incremental polling.
    """
    r = ssh_exec(
        f"if [ -f {log_path} ]; then "
        f"  size=$(stat -c %s {log_path}); "
        f"  if [ $size -gt {since_byte} ]; then "
        f"    tail -c +$(({since_byte} + 1)) {log_path}; "
        f"  fi; "
        f"  echo \"__SIZE__$size\"; "
        f"fi"
    )
    text = r.stdout
    new_offset = since_byte
    if "__SIZE__" in text:
        body, _, size_part = text.rpartition("__SIZE__")
        size_str = size_part.strip().splitlines()[0]
        if size_str.isdigit():
            new_offset = int(size_str)
        text = body
    return text, new_offset


def find_latest_lora_checkpoint(workspace: str, config_name: str) -> str | None:
    """Find the latest ai-toolkit LoRA checkpoint on DGX.

    ai-toolkit naming (verified empirically 2026-05-15 against 50-step run):
      - `{config_name}.safetensors`              — final checkpoint after training
      - `{config_name}_{NNNNNNNNN}.safetensors`  — intermediate save_every snapshots
                                                   (9-digit zero-padded step,
                                                   kept up to max_step_saves_to_keep)
    Strategy: try step-suffixed first (preserves intent if a partial run was
    interrupted before legacy was written), fall back to legacy. Returns None
    only if neither is found (training likely failed to save).
    NOTE: full-length (1500-step) runs with save_every=500 not yet ground-truthed —
    whether legacy and step-suffix can coexist (and which is canonical) is
    still TBD; this matters only if you need the snapshot at step N rather
    than the final, which the current contract does not provide.
    """
    output_dir = f"{workspace}/output/{config_name}"
    # ai-toolkit default: step-suffixed checkpoints. Use `find -maxdepth 1`
    # rather than ls glob so an unmatched pattern yields empty stdout (not
    # the literal glob string).
    r = ssh_exec(
        f"find {output_dir} -maxdepth 1 -name '{config_name}_*.safetensors' "
        f"2>/dev/null | sort -V | tail -1"
    )
    candidate = r.stdout.strip()
    if candidate:
        return candidate
    # Fallback: legacy non-step-suffix name (in case ai-toolkit config differs)
    legacy = f"{output_dir}/{config_name}.safetensors"
    r = ssh_exec(f"test -f {legacy} && echo OK")
    if r.stdout.strip() == "OK":
        return legacy
    return None
