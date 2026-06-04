"""Completion sanity check + auto-deploy mv.

Plan v1 Section 4.A step 13-14 + Section 11.3 / 11.4.

Strict sanity: file_exists ∧ last_k_loss_not_nan ∧ loss_trend_descending ∧
no_critical_error → auto-deploy.

Warnings (do NOT block): loss_plateau, final_loss_above_threshold,
no_sample_generated.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import COMFYUI_LORAS_DIR  # noqa: E402
from ssh_client import ssh_exec  # noqa: E402
from log_parser import find_critical_errors, parse_full_log  # noqa: E402


_LAST_K_STEPS = 20
_LOSS_PLATEAU_SLOPE_THRESHOLD = -1e-6
_FINAL_LOSS_THRESHOLD = 0.5


@dataclass
class SanityResult:
    passed: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    final_loss: float | None = None
    min_loss: float | None = None
    min_loss_step: int | None = None
    total_steps: int = 0


def _linear_slope(values: list[float]) -> float:
    """Simple linear regression slope of values vs index."""
    if len(values) < 2:
        return 0.0
    n = len(values)
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den else 0.0


def check(lora_path: str, log_path: str) -> SanityResult:
    """Run sanity check on completed training. Both paths are DGX-side."""
    result = SanityResult(passed=False)

    # 1. File exists
    r = ssh_exec(f"test -f {lora_path} && echo OK")
    if r.stdout.strip() != "OK":
        result.blockers.append(f"LoRA file not found: {lora_path}")

    # 2-4. Read log and analyze
    r = ssh_exec(f"cat {log_path}", timeout=30)
    if r.returncode != 0:
        result.blockers.append(f"cannot read log: {log_path}")
        return result

    log_text = r.stdout
    metrics = parse_full_log(log_text)
    result.total_steps = len(metrics)

    if metrics:
        result.final_loss = metrics[-1].loss
        min_m = min(metrics, key=lambda m: m.loss)
        result.min_loss = min_m.loss
        result.min_loss_step = min_m.step

    # 2. last K loss not NaN
    last_k = metrics[-_LAST_K_STEPS:] if metrics else []
    nan_losses = [m for m in last_k if math.isnan(m.loss) or math.isinf(m.loss)]
    if nan_losses:
        result.blockers.append(
            f"{len(nan_losses)}/{len(last_k)} of last {_LAST_K_STEPS} steps had "
            f"NaN/Inf loss"
        )

    # 3. loss trend descending
    if len(last_k) >= 2 and not nan_losses:
        slope = _linear_slope([m.loss for m in last_k])
        if slope > 0:
            result.blockers.append(
                f"loss trend is ascending over last {len(last_k)} steps "
                f"(slope = {slope:.6f})"
            )
        elif slope > _LOSS_PLATEAU_SLOPE_THRESHOLD:
            result.warnings.append(
                f"loss is plateauing (slope = {slope:.6f}, near zero) — "
                f"may indicate training is done or stuck"
            )

    # 4. no critical errors in log
    errors = find_critical_errors(log_text)
    if errors:
        # Filter noise: "nan" inside model names like "antelopev2" can match too
        # Stricter: only show errors that have certain leading words
        real_errors = [e for e in errors if "ERROR" in e or "Traceback" in e
                        or "out of memory" in e.lower()]
        if real_errors:
            result.blockers.append(
                f"log contains {len(real_errors)} critical error line(s); "
                f"first: {real_errors[0][:200]}"
            )

    # Warnings (non-blocking)
    if result.final_loss is not None and result.final_loss > _FINAL_LOSS_THRESHOLD:
        result.warnings.append(
            f"final loss {result.final_loss:.4f} > {_FINAL_LOSS_THRESHOLD} threshold"
        )

    # Sample images check. lora_path = .../{workspace}/output/{name}/file ; its
    # parent dir contains samples/ peer. Empirically verified 2026-05-15:
    # ai-toolkit writes samples to .../output/{name}/samples/ (sibling of LoRA).
    samples_dir = str(Path(lora_path).parent / "samples")
    r = ssh_exec(
        f"ls {samples_dir} 2>/dev/null | wc -l"
    )
    sample_count = int(r.stdout.strip() or 0) if r.returncode == 0 else 0
    if sample_count == 0:
        result.warnings.append("no sample images generated during training")

    result.passed = not result.blockers
    return result


def deploy(lora_path: str, dest_filename: str) -> tuple[bool, str]:
    """Atomic mv on DGX from training workspace to ComfyUI loras dir.

    Returns (ok, message). dest_filename should be "{tag}_{YYYYMMDD}.safetensors".
    """
    dest = f"{COMFYUI_LORAS_DIR}/{dest_filename}"
    r = ssh_exec(f"test -e {dest} && echo EXISTS || true")
    if r.stdout.strip() == "EXISTS":
        return False, f"destination already exists: {dest}"

    r = ssh_exec(f"mv {lora_path} {dest}")
    if r.returncode != 0:
        return False, f"mv failed: {r.stderr.strip()}"

    return True, dest
