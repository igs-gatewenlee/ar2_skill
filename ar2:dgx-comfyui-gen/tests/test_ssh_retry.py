"""Tests for ssh_client SCP retry logic (issue #1).

Covers BC-1, BC-2, BC-3, EH-1, EH-2 in P1-design-spec.md.
Mocks subprocess.run so no real DGX connection is needed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

# Path setup so `import ssh_client` works without installing the skill
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import ssh_client  # noqa: E402


@pytest.fixture(autouse=True)
def fake_sshpass(monkeypatch):
    """All tests assume sshpass exists locally so _check_sshpass doesn't raise."""
    monkeypatch.setattr(ssh_client.shutil, "which", lambda _name: "/usr/bin/sshpass")


@pytest.fixture
def record_sleeps(monkeypatch):
    """Capture time.sleep durations without actually sleeping."""
    sleeps: list[float] = []
    monkeypatch.setattr(ssh_client.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def _ok():
    """Simulated successful subprocess.run return."""
    return subprocess.CompletedProcess(args=["scp"], returncode=0, stdout=b"", stderr=b"")


def _cpe(cmd="scp"):
    return subprocess.CalledProcessError(returncode=1, cmd=[cmd], stderr=b"connection reset")


# -------- BC-1: first-try success ---------------------------------------

def _patch_run(monkeypatch, *, return_value=None, side_effect=None) -> mock.Mock:
    """Patch subprocess.run with either a return_value or a side_effect sequence."""
    if side_effect is not None:
        run_mock = mock.Mock(side_effect=side_effect)
    else:
        run_mock = mock.Mock(return_value=return_value)
    monkeypatch.setattr(ssh_client.subprocess, "run", run_mock)
    return run_mock


def test_scp_get_first_try_success_calls_subprocess_once(monkeypatch, record_sleeps):
    """BC-1: scp_get succeeds on first attempt → 1 subprocess.run call, no sleep."""
    run_mock = _patch_run(monkeypatch, return_value=_ok())

    ssh_client.scp_get("/remote/x.png", "/local/x.png")

    assert run_mock.call_count == 1
    assert record_sleeps == []


def test_scp_put_first_try_success_calls_subprocess_once(monkeypatch, record_sleeps):
    """BC-3 (put symmetry): scp_put succeeds on first attempt → 1 call, no sleep."""
    run_mock = _patch_run(monkeypatch, return_value=_ok())

    ssh_client.scp_put("/local/x.png", "/remote/x.png")

    assert run_mock.call_count == 1
    assert record_sleeps == []


# -------- BC-2: transient failure recovers --------------------------------

def test_scp_get_two_failures_then_success(monkeypatch, record_sleeps):
    """BC-2: 2 transient failures then success → 3 calls, 2 sleeps (1s + 2s)."""
    run_mock = _patch_run(monkeypatch, side_effect=[_cpe(), _cpe(), _ok()])

    ssh_client.scp_get("/remote/x.png", "/local/x.png")

    assert run_mock.call_count == 3
    assert record_sleeps == [1.0, 2.0]


def test_scp_put_one_timeout_then_success(monkeypatch, record_sleeps):
    """BC-3: scp_put timeout then success → 2 calls, 1 sleep."""
    run_mock = _patch_run(monkeypatch, side_effect=[
        subprocess.TimeoutExpired(cmd=["scp"], timeout=120),
        _ok(),
    ])

    ssh_client.scp_put("/local/x.png", "/remote/x.png")

    assert run_mock.call_count == 2
    assert record_sleeps == [1.0]


# -------- EH-1: all attempts fail → raise --------------------------------

def test_scp_get_all_attempts_fail_raises_last(monkeypatch, record_sleeps):
    """EH-1: 3 failures → raises the last CalledProcessError."""
    last = _cpe("final-failure")
    run_mock = _patch_run(monkeypatch, side_effect=[_cpe(), _cpe(), last])

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        ssh_client.scp_get("/remote/x.png", "/local/x.png")

    assert exc_info.value is last
    assert run_mock.call_count == 3


def test_scp_get_respects_max_attempts_parameter(monkeypatch, record_sleeps):
    """EH-1 (parameterized): max_attempts=2 → 2 calls, 1 sleep."""
    run_mock = _patch_run(monkeypatch, side_effect=[_cpe(), _cpe()])

    with pytest.raises(subprocess.CalledProcessError):
        ssh_client.scp_get("/remote/x.png", "/local/x.png", max_attempts=2)

    assert run_mock.call_count == 2
    assert record_sleeps == [1.0]


# -------- EH-2: SSHPassMissing is NOT retried -----------------------------

def test_sshpass_missing_raises_immediately_no_subprocess_call(monkeypatch, record_sleeps):
    """EH-2: missing sshpass binary → raises SSHPassMissing without running subprocess."""
    monkeypatch.setattr(ssh_client.shutil, "which", lambda _name: None)
    run_mock = _patch_run(monkeypatch, return_value=_ok())

    with pytest.raises(ssh_client.SSHPassMissing):
        ssh_client.scp_get("/remote/x.png", "/local/x.png")

    assert run_mock.call_count == 0
    assert record_sleeps == []


# -------- BC-7: existing-caller import compatibility ----------------------

def test_caller_imports_still_work():
    """BC-7: callers that imported scp_get/scp_put before retry can still import."""
    from ssh_client import scp_get, scp_put  # noqa: F401
