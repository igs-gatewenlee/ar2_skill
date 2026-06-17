"""SSH connection layer for DGX (cross-platform).

Public surface (unchanged):
- ssh_exec(cmd, timeout) -> CompletedProcess
- scp_get(remote, local, timeout) -> None
- scp_put(local, remote, timeout) -> None
- ping_host(timeout) -> bool
- ensure_tunnel(timeout) -> None
- tunnel_exists() -> bool

Linux/macOS: sshpass + ssh/scp + lsof (original behavior).
Windows: PuTTY plink.exe + pscp.exe; socket-based port probe.
PuTTY tools must be in PATH (default install: C:\\Program Files\\PuTTY\\).
First DGX connection auto-accepts the host key (idempotent, registry-cached).
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    HOST,
    SSH_PORT,
    USER,
    PASSWORD,
    SSH_OPTS,
    COMFYUI_PORT,
    DGX_HOSTKEY,
)


IS_WIN = sys.platform == "win32"

# Windows-only DGX SSH host key fingerprint (plink/pscp 用 -hostkey 略過 PuTTY
# registry cache)。值來自 SSOT registry（machine.ssh_hostkey_sha256），不再三份各抄；
# 僅 DGX SSH server host key 改變時更新該欄。


class SSHToolingMissing(RuntimeError):
    """Required SSH tooling is not installed on the local machine."""


SSHPassMissing = SSHToolingMissing  # backwards-compat alias for callers


def _check_tooling() -> None:
    if IS_WIN:
        missing = [t for t in ("plink.exe", "pscp.exe") if shutil.which(t) is None]
        if missing:
            raise SSHToolingMissing(
                f"PuTTY tools missing: {', '.join(missing)}.\n"
                "Install PuTTY (https://www.putty.org/) and ensure plink.exe and "
                "pscp.exe are reachable via PATH."
            )
        return
    if shutil.which("sshpass") is None:
        raise SSHToolingMissing(
            "sshpass is required but not installed.\n"
            "macOS: brew install esolitos/ipa/sshpass\n"
            "Linux: apt-get install sshpass"
        )


def _ssh_base() -> list[str]:
    if IS_WIN:
        return [
            "plink.exe", "-ssh", "-batch",
            "-hostkey", DGX_HOSTKEY,
            "-pw", PASSWORD,
            "-P", str(SSH_PORT),
            f"{USER}@{HOST}",
        ]
    return [
        "sshpass", "-p", PASSWORD, "ssh",
        *SSH_OPTS,
        "-p", str(SSH_PORT),
        f"{USER}@{HOST}",
    ]


def _scp_base() -> list[str]:
    if IS_WIN:
        return [
            "pscp.exe", "-batch", "-scp",
            "-hostkey", DGX_HOSTKEY,
            "-pw", PASSWORD,
            "-P", str(SSH_PORT),
        ]
    return [
        "sshpass", "-p", PASSWORD, "scp",
        *SSH_OPTS,
        "-P", str(SSH_PORT),
    ]


def ssh_exec(cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a shell command on DGX. Does NOT raise on non-zero exit;
    caller inspects .returncode / .stderr.
    """
    _check_tooling()
    return subprocess.run(
        _ssh_base() + [cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def scp_get(remote: str, local: str | Path, timeout: int = 120) -> None:
    """Download a single file from DGX. Raises CalledProcessError on failure."""
    _check_tooling()
    subprocess.run(
        _scp_base() + [f"{USER}@{HOST}:{remote}", str(local)],
        check=True,
        capture_output=True,
        timeout=timeout,
    )


def scp_put(local: str | Path, remote: str, timeout: int = 120) -> None:
    """Upload a single file to DGX. Raises CalledProcessError on failure."""
    _check_tooling()
    subprocess.run(
        _scp_base() + [str(local), f"{USER}@{HOST}:{remote}"],
        check=True,
        capture_output=True,
        timeout=timeout,
    )


def ping_host(timeout: int = 2) -> bool:
    """Returns True if DGX responds to a single ICMP ping within timeout."""
    if IS_WIN:
        # Windows ping: -n count, -w timeout-ms
        cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), HOST]
    else:
        # macOS/Linux: -c count, -W timeout
        # Original script passed ms here, which is the macOS interpretation.
        cmd = ["ping", "-c", "1", "-W", str(timeout * 1000), HOST]
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout + 1,
    )
    return result.returncode == 0


def tunnel_exists() -> bool:
    """True if local port COMFYUI_PORT accepts a TCP connection.

    Replaces the original `lsof -ti :PORT` with a portable socket probe:
    if something is listening (our tunnel or a foreign process), we treat
    it as "tunnel present" — same semantics as the original.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.connect(("127.0.0.1", COMFYUI_PORT))
        return True
    except (ConnectionRefusedError, OSError):
        return False
    finally:
        sock.close()


def ensure_tunnel(timeout: int = 5) -> None:
    """Open a background SSH tunnel localhost:COMFYUI_PORT -> DGX:COMFYUI_PORT.

    No-op if a tunnel/listener is already present. Caller should treat this
    as best-effort: function returns once tunnel is verified open, or after
    ~5s wait if the background process is slow.
    """
    if tunnel_exists():
        return
    _check_tooling()
    if IS_WIN:
        # Detach plink so the parent script doesn't block on it.
        subprocess.Popen(
            ["plink.exe", "-ssh", "-batch", "-N",
             "-hostkey", DGX_HOSTKEY,
             "-pw", PASSWORD,
             "-L", f"{COMFYUI_PORT}:localhost:{COMFYUI_PORT}",
             "-P", str(SSH_PORT),
             f"{USER}@{HOST}"],
            creationflags=(
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
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
    # Brief wait for the tunnel to come up (handles slow plink spawn on Win).
    for _ in range(20):
        if tunnel_exists():
            return
        time.sleep(0.25)
