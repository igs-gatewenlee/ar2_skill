"""SSH connection layer for DGX.

Public surface:
- ssh_exec(cmd, timeout) -> CompletedProcess
- scp_get(remote, local, timeout) -> None (raises on failure)
- scp_put(local, remote, timeout) -> None (raises on failure)
- ping_host(timeout) -> bool
- ensure_tunnel(timeout) -> None (idempotent, reuses existing tunnel)
- tunnel_exists() -> bool

Imports config from the sibling config.py (skill-local). Each skill in the
ar2:dgx-* family has its own copy until the family hits the extract-base
threshold (see plan v1 Section 10.7).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

# Make sibling-level import work whether called as script or imported.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    HOST,
    SSH_PORT,
    USER,
    PASSWORD,
    SSH_OPTS,
    COMFYUI_PORT,
)


class SSHPassMissing(RuntimeError):
    """sshpass binary is not installed on the local machine."""


def _check_sshpass() -> None:
    if shutil.which("sshpass") is None:
        raise SSHPassMissing(
            "sshpass is required but not installed.\n"
            "Install on macOS: brew install esolitos/ipa/sshpass"
        )


def _ssh_base() -> list[str]:
    return [
        "sshpass", "-p", PASSWORD, "ssh",
        *SSH_OPTS,
        "-p", str(SSH_PORT),
        f"{USER}@{HOST}",
    ]


def _scp_base() -> list[str]:
    return [
        "sshpass", "-p", PASSWORD, "scp",
        *SSH_OPTS,
        "-P", str(SSH_PORT),
    ]


def ssh_exec(cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a shell command on DGX. Does NOT raise on non-zero exit;
    caller inspects .returncode / .stderr.
    """
    _check_sshpass()
    return subprocess.run(
        _ssh_base() + [cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _scp_with_retry(
    args: list[str],
    timeout: int,
    max_attempts: int = 3,
    backoff_sec: float = 1.0,
) -> None:
    """Run an scp subprocess with linear-backoff retry on transient failures.

    Retries on CalledProcessError or TimeoutExpired up to max_attempts;
    sleeps backoff_sec * attempt between tries (1s, 2s, ...). Raises the
    last exception after max_attempts. SSHPassMissing is NOT handled here —
    callers must run _check_sshpass() first so missing-binary errors fail fast.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            subprocess.run(args, check=True, capture_output=True, timeout=timeout)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == max_attempts:
                raise
            time.sleep(backoff_sec * attempt)


def scp_get(
    remote: str,
    local: str | Path,
    timeout: int = 120,
    max_attempts: int = 3,
) -> None:
    """Download a single file from DGX. Raises on final failure after retries."""
    _check_sshpass()
    _scp_with_retry(
        _scp_base() + [f"{USER}@{HOST}:{remote}", str(local)],
        timeout=timeout,
        max_attempts=max_attempts,
    )


def scp_put(
    local: str | Path,
    remote: str,
    timeout: int = 120,
    max_attempts: int = 3,
) -> None:
    """Upload a single file to DGX. Raises on final failure after retries."""
    _check_sshpass()
    _scp_with_retry(
        _scp_base() + [str(local), f"{USER}@{HOST}:{remote}"],
        timeout=timeout,
        max_attempts=max_attempts,
    )


def ping_host(timeout: int = 2) -> bool:
    """Returns True if DGX responds to a single ICMP ping within timeout."""
    result = subprocess.run(
        ["ping", "-c", "1", "-W", str(timeout * 1000), HOST],
        capture_output=True,
        timeout=timeout + 1,
    )
    return result.returncode == 0


def tunnel_exists() -> bool:
    """True if local port COMFYUI_PORT is bound (assumes ours)."""
    result = subprocess.run(
        ["lsof", "-ti", f":{COMFYUI_PORT}"],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def ensure_tunnel(timeout: int = 5) -> None:
    """Open a background SSH tunnel localhost:COMFYUI_PORT -> DGX:COMFYUI_PORT.

    No-op if tunnel already exists. Family skills should call this before
    making local HTTP requests against ComfyUI.
    """
    if tunnel_exists():
        return
    _check_sshpass()
    subprocess.run(
        [
            "sshpass", "-p", PASSWORD, "ssh", "-fN",
            *SSH_OPTS,
            "-L", f"{COMFYUI_PORT}:localhost:{COMFYUI_PORT}",
            "-p", str(SSH_PORT),
            f"{USER}@{HOST}",
        ],
        check=True,
        timeout=timeout,
    )
