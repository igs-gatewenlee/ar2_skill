"""ai-toolkit log parser.

Parses lines from `nohup python /root/ai-toolkit/run.py config.yaml > train.log 2>&1`
to extract loss / step / lr metrics.

ai-toolkit log format (verified against ai-toolkit source at
`/root/ai-toolkit/jobs/process/BaseSDTrainProcess.py` line 2284):

The trainer uses a tqdm progress bar (`ToolkitProgressBar`). Postfix string
is built as `lr: {learning_rate:.1e}` then appended with each
`loss_dict.items()` entry as `{key}: {value:.3e}`. Each tqdm update writes
a line of the form:

    Epoch 0:  50%|███████| 750/1500 [12:34<12:34, 1.41s/it, lr: 1.0e-04 loss: 1.234e-01]

We anchor `step/total` on the tqdm `[elapsed` marker so we don't false-match
on description text (e.g. "Phase 1/2"). lr is always before loss because
ai-toolkit composes `prog_bar_string` that way.

v1 uses regex adapters. Future: add more trainers via adapter pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Match tqdm progress line. `step/total` immediately precedes `[elapsed`
# in tqdm format; lr is before loss in ai-toolkit's prog_bar_string.
_STEP_PATTERN = re.compile(
    r"(?P<step>\d+)\s*/\s*(?P<total>\d+)\s*\["  # tqdm step/total + [elapsed
    r".*?"
    r"lr:\s*(?P<lr>[-+]?\d*\.?\d+(?:e[-+]?\d+)?)"
    r".*?"
    r"loss:\s*(?P<loss>[-+]?\d*\.?\d+(?:e[-+]?\d+)?)",
    re.IGNORECASE,
)
# Standalone lr pattern (kept for callers that grep without step context)
_LR_PATTERN = re.compile(
    r"lr:\s*(?P<lr>[-+]?\d*\.?\d+(?:e[-+]?\d+)?)", re.IGNORECASE
)
# tqdm description often is "Epoch N" without total. Make total optional.
_EPOCH_PATTERN = re.compile(
    r"Epoch\s+(?P<epoch>\d+)(?:\s*/\s*(?P<total_epoch>\d+))?",
    re.IGNORECASE,
)

# Completion markers — ai-toolkit doesn't have a single canonical string;
# skill primarily relies on process exit (trainer.is_alive) so these
# are best-effort informational.
_COMPLETE_MARKERS = [
    re.compile(r"training\s+complete", re.IGNORECASE),
    re.compile(r"training\s+finished", re.IGNORECASE),
    re.compile(r"\bdone\b\s*$", re.IGNORECASE),
]

# ai-toolkit actual NaN/Inf messages (grepped from toolkit/style.py +
# TrainVAEProcess.py):  "Loss is NaN", "is nan", and tqdm postfix
# may show "loss: nan".
_CRITICAL_ERROR_MARKERS = [
    re.compile(r"\bERROR\b"),
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"CUDA out of memory", re.IGNORECASE),
    re.compile(r"loss\s+is\s+(?:nan|inf)", re.IGNORECASE),
    re.compile(r"loss[:=]\s*(?:nan|inf)\b", re.IGNORECASE),
]


@dataclass
class StepMetric:
    step: int
    total_steps: int
    loss: float
    lr: float | None = None
    epoch: int | None = None
    total_epochs: int | None = None


def parse_step_line(line: str) -> StepMetric | None:
    """Parse a single log line. Returns StepMetric if line matches, else None."""
    m = _STEP_PATTERN.search(line)
    if not m:
        return None
    try:
        step = int(m.group("step"))
        total = int(m.group("total"))
        loss = float(m.group("loss"))
    except (ValueError, KeyError):
        return None

    lr = None
    m_lr = _LR_PATTERN.search(line)
    if m_lr:
        try:
            lr = float(m_lr.group("lr"))
        except ValueError:
            pass

    epoch = total_epochs = None
    m_e = _EPOCH_PATTERN.search(line)
    if m_e:
        try:
            epoch = int(m_e.group("epoch"))
            te = m_e.group("total_epoch")
            if te is not None:
                total_epochs = int(te)
        except ValueError:
            pass

    return StepMetric(
        step=step,
        total_steps=total,
        loss=loss,
        lr=lr,
        epoch=epoch,
        total_epochs=total_epochs,
    )


def is_complete(line: str) -> bool:
    return any(p.search(line) for p in _COMPLETE_MARKERS)


def find_critical_errors(log_text: str) -> list[str]:
    """Return list of matched critical-error lines."""
    hits: list[str] = []
    for line in log_text.splitlines():
        for p in _CRITICAL_ERROR_MARKERS:
            if p.search(line):
                hits.append(line.strip())
                break
    return hits


def parse_full_log(log_text: str) -> list[StepMetric]:
    """Parse a complete log, return all step metrics in order."""
    metrics: list[StepMetric] = []
    for line in log_text.splitlines():
        m = parse_step_line(line)
        if m is not None:
            metrics.append(m)
    return metrics
