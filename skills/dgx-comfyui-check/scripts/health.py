"""Three-prong health checks for DGX + ComfyUI.

All checks run on DGX side via ssh_exec (no local tunnel needed).

Each check returns (ok: bool, msg: str) so the report layer can render
✅ / ❌ + a one-line summary per check.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import COMFYUI_PORT  # noqa: E402
from ssh_client import ssh_exec  # noqa: E402


def check_gpu() -> tuple[bool, str]:
    """nvidia-smi query for GPU name + memory."""
    r = ssh_exec(
        "nvidia-smi --query-gpu=name,memory.used,memory.free "
        "--format=csv,noheader,nounits"
    )
    if r.returncode != 0:
        return False, f"nvidia-smi failed: {r.stderr.strip() or 'no stderr'}"
    line = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
    if not line:
        return False, "nvidia-smi returned empty output"
    # line example: "Tesla V100-DGXS-32GB, 1024, 31510"
    parts = [p.strip() for p in line.split(",")]
    if len(parts) >= 3:
        name, used, free = parts[0], parts[1], parts[2]
        return True, f"{name} (used {used} MiB / free {free} MiB)"
    return True, line


def check_comfyui_process() -> tuple[bool, str]:
    """pgrep for the ComfyUI main.py process."""
    r = ssh_exec('pgrep -f "python.*ComfyUI/main.py"')
    if r.returncode != 0 or not r.stdout.strip():
        return False, "ComfyUI process not found (pgrep no match)"
    pids = r.stdout.strip().splitlines()
    return True, f"pid {','.join(pids)}"


def check_comfyui_api(timeout: int = 5) -> tuple[bool, str]:
    """curl /system_stats endpoint inside DGX (loopback, no tunnel needed)."""
    r = ssh_exec(
        f'curl -sf --max-time {timeout} '
        f'http://localhost:{COMFYUI_PORT}/system_stats',
        timeout=timeout + 5,
    )
    if r.returncode != 0:
        err = r.stderr.strip() or "(empty stderr)"
        return False, f"API not responsive (curl exit {r.returncode}: {err})"
    if not r.stdout.strip():
        return False, "API returned empty body"
    return True, "/system_stats OK"


def run_all() -> dict[str, dict]:
    """Run all three checks; return structured result.

    Reconciliation: API is ground truth for ComfyUI liveness. If API
    responds OK but pgrep fails to match the launcher pattern (e.g.
    ComfyUI started via a wrapper script, conda env python, or inside
    a container the host can't see), the process check is downgraded
    to informational rather than treated as a hard failure.
    """
    gpu_ok, gpu_msg = check_gpu()
    proc_ok, proc_msg = check_comfyui_process()
    api_ok, api_msg = check_comfyui_api()

    if api_ok and not proc_ok:
        # API ground truth says ComfyUI is alive; override pgrep false-negative.
        proc_msg = "(API live, pgrep no match)"
        proc_ok = True

    return {
        "gpu": {"ok": gpu_ok, "msg": gpu_msg},
        "comfyui_process": {"ok": proc_ok, "msg": proc_msg},
        "comfyui_api": {"ok": api_ok, "msg": api_msg},
    }
