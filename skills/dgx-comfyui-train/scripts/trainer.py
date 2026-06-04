"""ai-toolkit YAML config builder + background launcher.

- generate_config(): take preset YAML + caller params, fill placeholders, return text
- launch(): SCP config to DGX, nohup python /root/ai-toolkit/run.py
"""

from __future__ import annotations

import subprocess
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

    # SSH + backgrounded nohup is famously hard to detach cleanly: even with
    # setsid + </dev/null on the inner process, the outer SSH session can fail
    # to close until something happens on the channel. Empirically the
    # detached python *does* start (verified across 2 real runs 2026-05-15);
    # SSH client just blocks waiting for the wrapper shell. So: treat SSH
    # TimeoutExpired as expected, then verify via the pid file written by the
    # remote shell as its last action — if the file has a digit, the launch
    # succeeded and the SSH session closing is the only thing missing.
    cmd = (
        f"cd {workspace} && "
        f"setsid nohup python3 {AITK_RUN_PY} {config_remote_path} "
        f"</dev/null > {log_path} 2>&1 & "
        f"echo $! > {pid_path}"
    )
    try:
        r = ssh_exec(cmd, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"failed to launch training: {r.stderr.strip()}")
    except subprocess.TimeoutExpired:
        pass  # fall through to pid-file verification

    # Authoritative success signal: pid file is written iff the remote shell
    # reached `echo $!`, which is the last command after the background job
    # was spawned.
    r = ssh_exec(f"cat {pid_path}", timeout=5)
    pid_str = r.stdout.strip()
    if not pid_str.isdigit():
        raise RuntimeError(
            f"launch verification failed: pid file empty or missing "
            f"({pid_path}). The remote shell did not complete `echo $!`."
        )

    # The `$!` written into train.pid is the bash wrapper that SSH server
    # spawned to run `bash -c "..."`, NOT the detached python child. The
    # wrapper can later be SIGHUP'd by the SSH server side while the
    # setsid-detached python keeps running, causing kill -0 false negatives
    # in is_alive() and a spurious "Training process ended". Resolve the
    # real python PID here and overwrite train.pid so polling tracks the
    # right process.
    real_pid = _resolve_python_pid(config_remote_path)
    if real_pid is not None:
        ssh_exec(f"echo {real_pid} > {pid_path}", timeout=5)
        return real_pid, log_path

    # pgrep didn't find it — fall back to wrapper PID and warn caller via
    # raise. (Unlikely under normal conditions; ai-toolkit always spawns a
    # python that matches the config path.)
    raise RuntimeError(
        f"launch verification failed: no python process matched config "
        f"path {config_remote_path}. Wrapper PID was {pid_str} but its "
        f"child python could not be located."
    )


def _resolve_python_pid(config_remote_path: str, retries: int = 5) -> int | None:
    """Find the ai-toolkit python PID by matching the config path.

    `pgrep -f` matches *anywhere* in the cmdline, so it picks up both the
    bash -c wrapper (whose cmdline contains the full inner command) and the
    real python process. Filter for cmdlines that *start* with `python3` so
    the wrapper is excluded. Retries a few times because the python process
    may not appear in pgrep until ~hundreds of ms after `&` returns.
    """
    import time
    for _ in range(retries):
        r = ssh_exec(
            f"pgrep -af 'run.py.*{config_remote_path}'",
            timeout=10,
        )
        for line in r.stdout.splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                continue
            pid_str, cmd = parts
            if cmd.startswith(("python3 ", "python ")) and pid_str.isdigit():
                return int(pid_str)
        time.sleep(1)
    return None


def is_alive(pid: int) -> bool:
    """Check DGX-side: is the training PID still running?

    Returns True when SSH succeeds and the process is alive, OR when SSH
    is transiently unavailable (timeout, transient auth/network failure).
    Only returns False when SSH succeeds and reports the process is gone.
    This asymmetric default avoids long-running trainings being killed
    locally by spurious is_alive=False from transient SSH hiccups
    (the actual ai-toolkit process keeps running detached on DGX).
    """
    import time as _time
    for attempt in range(3):
        try:
            r = ssh_exec(f"kill -0 {pid} 2>/dev/null && echo ALIVE", timeout=10)
        except subprocess.TimeoutExpired:
            _time.sleep(2)
            continue
        if r.returncode != 0:
            _time.sleep(2)
            continue
        # SSH succeeded — stdout is authoritative
        return r.stdout.strip() == "ALIVE"
    # 3 SSH attempts all failed — assume alive (don't exit polling)
    return True


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

    ai-toolkit naming (ground-truthed empirically 2026-05-16 against 200-step
    run with save_every=50 / max_step_saves_to_keep=2):
      - `{config_name}.safetensors`              — final checkpoint, written
                                                   exactly once when training
                                                   completes (step == total)
      - `{config_name}_{NNNNNNNNN}.safetensors`  — save_every snapshots
                                                   (9-digit zero-padded step,
                                                   kept up to max_step_saves_to_keep)
    Coexistence: after a clean run with save_every < total_steps, BOTH forms
    are present. The legacy file is the canonical "final" — the step-suffixed
    snapshots are older intermediates.

    Strategy: prefer legacy (canonical final). Fall back to highest step-suffix
    only when legacy is absent (training was interrupted before final write).
    Returns None when neither is present (training failed to save anything).
    """
    output_dir = f"{workspace}/output/{config_name}"
    # 1. Prefer legacy — written exactly at training completion.
    legacy = f"{output_dir}/{config_name}.safetensors"
    r = ssh_exec(f"test -f {legacy} && echo OK")
    if r.stdout.strip() == "OK":
        return legacy
    # 2. Fallback: highest step-suffixed snapshot (training was interrupted).
    r = ssh_exec(
        f"find {output_dir} -maxdepth 1 -name '{config_name}_*.safetensors' "
        f"2>/dev/null | sort -V | tail -1"
    )
    candidate = r.stdout.strip()
    if candidate:
        return candidate
    return None
