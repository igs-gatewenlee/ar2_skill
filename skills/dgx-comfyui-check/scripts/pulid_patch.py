"""PuLID-Flux-Enhanced dtype-cast patch deploy + status (issue #5(b)).

The ComfyUI-PuLID-Flux-Enhanced custom node ships an encoders_flux.py that
crashes on bf16/fp16 weights because it skips an explicit dtype cast before
norm. The local fix is four edits in two near-identical class methods.

`git pull` on the custom node would silently revert these edits. This
module:
- reports patch state in the standard ar2:dgx-comfyui-check inventory
- offers an idempotent `--apply-pulid-patch` flag to (re-)apply the patch

All remote operations go through ssh_client.ssh_exec (single SSH seam,
keeps tests mockable).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ssh_client import ssh_exec  # noqa: E402


PatchState = Literal[
    "patched",
    "unpatched",
    "mixed",
    "missing-node",
    "missing-file",
    "ssh-error",
]


PATCH_FILE = (
    "/root/ComfyUI/custom_nodes/ComfyUI-PuLID-Flux-Enhanced/encoders_flux.py"
)
PATCH_NODE_DIR = (
    "/root/ComfyUI/custom_nodes/ComfyUI-PuLID-Flux-Enhanced"
)
PATCH_MARKER = ".to(self.norm"
PATCH_MARKER_COUNT = 4  # 2 classes × 2 lines each (norm1 + norm2)

SED_CMD_TEMPLATE = (
    "sed -i "
    "-e 's|x = self\\.norm1(x)|x = self.norm1(x.to(self.norm1.weight.dtype))|g' "
    "-e 's|latents = self\\.norm2(latents)|latents = self.norm2(latents.to(self.norm2.weight.dtype))|g' "
    "{file}"
)


_SSH_ERROR_NEEDLES = ("Connection refused", "No route to host", "Could not resolve hostname")


def _is_ssh_layer_error(rc: int, stderr: str) -> bool:
    """Distinguish SSH transport failures from in-shell non-zero exits."""
    return rc == 255 or any(n in stderr for n in _SSH_ERROR_NEEDLES)


def check_patch_status() -> PatchState:
    """Two-phase classification (DR-1 fix prevents SSH-error → missing-node)."""
    probe = ssh_exec("echo ok")
    if _is_ssh_layer_error(probe.returncode, probe.stderr):
        return "ssh-error"

    # Combined existence + marker count check in one round-trip.
    cmd = (
        f"if [ ! -d {PATCH_NODE_DIR} ]; then echo MISSING_NODE; "
        f"elif [ ! -f {PATCH_FILE} ]; then echo MISSING_FILE; "
        f"else grep -c -F -- '{PATCH_MARKER}' {PATCH_FILE} || echo 0; "
        f"fi"
    )
    r = ssh_exec(cmd)
    if _is_ssh_layer_error(r.returncode, r.stderr):
        return "ssh-error"

    output = r.stdout.strip()
    if output == "MISSING_NODE":
        return "missing-node"
    if output == "MISSING_FILE":
        return "missing-file"

    try:
        count = int(output)
    except ValueError:
        # Defensive: shell echoed an integer-shaped count via grep -c, so
        # garbage here means the remote shell environment is misbehaving
        # (alias clobbering grep, hostile prompt leakage, etc.). Classify as
        # "ssh-error" — semantically not transport, but the safe response is
        # the same: bail out before any destructive op (R-3 by-decision).
        return "ssh-error"

    if count == PATCH_MARKER_COUNT:
        return "patched"
    if count == 0:
        return "unpatched"
    return "mixed"


def _backup_path() -> str:
    """Dated backup name. Same format as the existing manual backup."""
    today = date.today().strftime("%Y%m%d")
    return f"{PATCH_FILE}.bak.{today}"


def _backup_is_pre_patch(backup_path: str) -> bool | None:
    """Return True if backup contains 0 PATCH_MARKERs (pre-patch content),
    False if it contains any (mixed or already-patched), or None on SSH error.
    """
    r = ssh_exec(f"grep -c -F -- '{PATCH_MARKER}' {backup_path} || echo 0")
    if _is_ssh_layer_error(r.returncode, r.stderr):
        return None
    try:
        return int(r.stdout.strip()) == 0
    except ValueError:
        return None


def apply_patch(dry_run: bool = False) -> tuple[bool, str]:
    """Idempotent: see PatchState branches in module docstring."""
    state = check_patch_status()

    if state == "patched":
        return True, "already patched, no-op"
    if state == "ssh-error":
        return False, "cannot reach DGX (SSH connection error)"
    if state == "missing-node":
        return False, f"PuLID custom node not installed at {PATCH_NODE_DIR}"
    if state == "missing-file":
        return False, f"encoders_flux.py missing at {PATCH_FILE}"
    if state == "mixed":
        return False, (
            "encoders_flux.py is partially patched; manual inspection needed "
            "(some marker lines present, some absent)"
        )

    # state == "unpatched"
    backup = _backup_path()
    probe = ssh_exec(f"test -f {backup} && echo YES || echo NO")
    backup_exists = probe.stdout.strip() == "YES"

    if backup_exists:
        integrity = _backup_is_pre_patch(backup)
        if integrity is None:
            return False, f"could not verify existing backup integrity ({backup})"
        if not integrity:
            return False, (
                f"existing backup {backup} is not pre-patch content; "
                "manual inspection needed before applying patch"
            )

    if dry_run:
        action = "skip (exists)" if backup_exists else "create"
        return True, f"dry-run: would {action} backup, then sed-apply patch"

    if not backup_exists:
        cp_r = ssh_exec(f"cp {PATCH_FILE} {backup}")
        if cp_r.returncode != 0:
            return False, f"backup creation failed: {cp_r.stderr.strip()}"

    sed_r = ssh_exec(SED_CMD_TEMPLATE.format(file=PATCH_FILE))
    if sed_r.returncode != 0:
        return False, f"sed failed: {sed_r.stderr.strip()}"

    post_state = check_patch_status()
    if post_state != "patched":
        return False, f"post-apply verification failed: state is {post_state!r}"
    return True, "patch applied successfully"


def status_summary_line() -> str:
    """One-liner for inspect.py inventory report."""
    state = check_patch_status()
    return {
        "patched":      "PuLID patch: ✅ applied",
        "unpatched":    "PuLID patch: ❌ unpatched (run --apply-pulid-patch to fix)",
        "mixed":        "PuLID patch: ⚠️  mixed (manual inspection needed)",
        "missing-node": "PuLID patch: n/a (PuLID custom node not installed)",
        "missing-file": "PuLID patch: ⚠️  encoders_flux.py missing",
        "ssh-error":    "PuLID patch: ⚠️  SSH error (could not query DGX)",
    }[state]
