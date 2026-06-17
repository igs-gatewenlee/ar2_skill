"""Tests for three-prong health checks (scripts/health.py).

Covers coverage gaps check-1, check-2, check-3, check-4, check-27,
check-31, check-40. health.py pulls ssh_exec into its own namespace via
`from ssh_client import ssh_exec`, so monkeypatch.setattr(health,
"ssh_exec", ...) fully intercepts every DGX call — tests run purely
offline, no DGX/GPU/SSH/network. (Same seam pattern as
test_pulid_patch.py.)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import health  # noqa: E402


# ---------- Helpers ----------

def _cp(rc: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """Build a CompletedProcess for mocking ssh_exec."""
    return subprocess.CompletedProcess(args=["ssh"], returncode=rc, stdout=stdout, stderr=stderr)


def _stub_ssh(monkeypatch, *, return_value=None, side_effect=None) -> mock.Mock:
    """Replace health.ssh_exec with a Mock; record every call."""
    m = mock.Mock(return_value=return_value, side_effect=side_effect)
    monkeypatch.setattr(health, "ssh_exec", m)
    return m


# ========== check-1 / check-27 : check_gpu() ==========

def test_gpu_normal_three_columns(monkeypatch):
    """check-1 (1): normal 3-col CSV → formatted name + used/free MiB."""
    _stub_ssh(monkeypatch, return_value=_cp(0, "Tesla V100-DGXS-32GB, 1024, 31510\n"))
    assert health.check_gpu() == (
        True,
        "Tesla V100-DGXS-32GB (used 1024 MiB / free 31510 MiB)",
    )


def test_gpu_multiline_takes_first_line(monkeypatch):
    """check-1 (2) / check-27 (2): multi-line output → only first line parsed."""
    _stub_ssh(
        monkeypatch,
        return_value=_cp(0, "Tesla A, 100, 200\nTesla B, 300, 400\n"),
    )
    ok, msg = health.check_gpu()
    assert ok is True
    # First line: name=Tesla A, used=100, free=200. Second line must be ignored.
    assert msg == "Tesla A (used 100 MiB / free 200 MiB)"
    assert "Tesla B" not in msg
    assert "300" not in msg and "400" not in msg


def test_gpu_failure_with_stderr(monkeypatch):
    """check-1 (3) / check-27 (4): returncode != 0 with stderr → fail msg includes stderr."""
    _stub_ssh(monkeypatch, return_value=_cp(1, "", "no devices"))
    ok, msg = health.check_gpu()
    assert ok is False
    assert "nvidia-smi failed" in msg
    assert "no devices" in msg


def test_gpu_failure_no_stderr(monkeypatch):
    """check-1 (4) / check-27 (5): returncode != 0, empty stderr → 'no stderr' fallback."""
    _stub_ssh(monkeypatch, return_value=_cp(1, "", ""))
    ok, msg = health.check_gpu()
    assert ok is False
    assert msg == "nvidia-smi failed: no stderr"


def test_gpu_empty_output(monkeypatch):
    """check-1 (5) / check-27 (6): rc=0 but blank stdout → empty-output guard."""
    _stub_ssh(monkeypatch, return_value=_cp(0, "   \n"))
    assert health.check_gpu() == (False, "nvidia-smi returned empty output")


def test_gpu_fewer_than_three_columns_returns_raw_line(monkeypatch):
    """check-1 (6) / check-27 (3): parts < 3 → still True, raw line unformatted."""
    _stub_ssh(monkeypatch, return_value=_cp(0, "only,two\n"))
    assert health.check_gpu() == (True, "only,two")


# ========== check-2 : check_comfyui_process() ==========

def test_proc_multi_pid_with_trailing_newline(monkeypatch):
    """check-2 (1): multiple PIDs → comma-joined 'pid a,b'."""
    _stub_ssh(monkeypatch, return_value=_cp(0, "12345\n23456\n"))
    assert health.check_comfyui_process() == (True, "pid 12345,23456")


def test_proc_single_pid(monkeypatch):
    """check-2 (2): single PID → 'pid 12345'."""
    _stub_ssh(monkeypatch, return_value=_cp(0, "12345\n"))
    assert health.check_comfyui_process() == (True, "pid 12345")


def test_proc_returncode_nonzero(monkeypatch):
    """check-2 (3): pgrep no-match exit code 1 → not found."""
    _stub_ssh(monkeypatch, return_value=_cp(1, ""))
    assert health.check_comfyui_process() == (
        False,
        "ComfyUI process not found (pgrep no match)",
    )


def test_proc_returncode_zero_but_blank_stdout(monkeypatch):
    """check-2 (4): rc=0 but only-whitespace stdout → `or not stdout.strip()` branch."""
    _stub_ssh(monkeypatch, return_value=_cp(0, "\n  \n"))
    assert health.check_comfyui_process() == (
        False,
        "ComfyUI process not found (pgrep no match)",
    )


# ========== check-3 / check-31 : check_comfyui_api() ==========

def test_api_success_and_command_contract(monkeypatch):
    """check-3 (1): success → (True, '/system_stats OK'); curl --max-time 5,
    port 8199, ssh_exec timeout=10 (default timeout+5)."""
    m = _stub_ssh(monkeypatch, return_value=_cp(0, '{"system":{}}'))
    assert health.check_comfyui_api() == (True, "/system_stats OK")
    cmd = m.call_args.args[0]
    assert "--max-time 5" in cmd
    assert f"localhost:{health.COMFYUI_PORT}/system_stats" in cmd
    assert "8199" in cmd
    assert m.call_args.kwargs["timeout"] == 10


def test_api_curl_failure_with_stderr(monkeypatch):
    """check-3 (2) / check-31 (4): rc != 0 with stderr → 'curl exit N: <stderr>'."""
    _stub_ssh(monkeypatch, return_value=_cp(7, "", "curl: timed out"))
    ok, msg = health.check_comfyui_api()
    assert ok is False
    assert "curl exit 7" in msg
    assert "curl: timed out" in msg


def test_api_empty_body(monkeypatch):
    """check-3 (3) / check-31 (3): rc=0 but blank body → empty-body branch."""
    _stub_ssh(monkeypatch, return_value=_cp(0, "   "))
    assert health.check_comfyui_api() == (False, "API returned empty body")


def test_api_custom_timeout_propagation(monkeypatch):
    """check-3 (4) / check-31 (1): custom timeout=12 → curl --max-time 12,
    ssh_exec timeout=17 (timeout+5 padding so ssh outlives curl)."""
    m = _stub_ssh(monkeypatch, return_value=_cp(0, '{"ok":1}'))
    health.check_comfyui_api(timeout=12)
    cmd = m.call_args.args[0]
    assert "--max-time 12" in cmd
    assert m.call_args.kwargs["timeout"] == 17


def test_api_failure_empty_stderr_placeholder(monkeypatch):
    """check-31 (5): rc != 0, empty stderr → '(empty stderr)' placeholder."""
    _stub_ssh(monkeypatch, return_value=_cp(1, "", ""))
    assert health.check_comfyui_api() == (
        False,
        "API not responsive (curl exit 1: (empty stderr))",
    )


# ========== check-4 / check-40 : run_all() reconciliation ==========
# check-4 mocks the three check_* functions directly; check-40 drives the
# real check_* via ssh_exec side_effect (gpu, proc, api order).


def test_run_all_override_triggers_when_api_live_proc_dead(monkeypatch):
    """check-4 case 1: api_ok and not proc_ok → proc forced True + msg rewritten."""
    monkeypatch.setattr(health, "check_gpu", lambda: (True, "gpu"))
    monkeypatch.setattr(health, "check_comfyui_process", lambda: (False, "pgrep no match"))
    monkeypatch.setattr(health, "check_comfyui_api", lambda: (True, "/system_stats OK"))
    r = health.run_all()
    assert r["comfyui_api"]["ok"] is True
    assert r["comfyui_process"]["ok"] is True
    assert r["comfyui_process"]["msg"] == "(API live, pgrep no match)"
    assert r["gpu"] == {"ok": True, "msg": "gpu"}


def test_run_all_no_override_when_api_also_dead(monkeypatch):
    """check-4 case 2: api down → proc stays False, original msg untouched (asymmetry)."""
    monkeypatch.setattr(health, "check_gpu", lambda: (True, "gpu"))
    monkeypatch.setattr(health, "check_comfyui_process", lambda: (False, "pgrep no match"))
    monkeypatch.setattr(health, "check_comfyui_api", lambda: (False, "API not responsive"))
    r = health.run_all()
    assert r["comfyui_process"]["ok"] is False
    assert r["comfyui_process"]["msg"] == "pgrep no match"


def test_run_all_proc_alive_msg_not_rewritten(monkeypatch):
    """check-4 case 3: proc already ok → reconciliation only fires on not proc_ok."""
    monkeypatch.setattr(health, "check_gpu", lambda: (True, "gpu"))
    monkeypatch.setattr(health, "check_comfyui_process", lambda: (True, "pid 123"))
    monkeypatch.setattr(health, "check_comfyui_api", lambda: (True, "/system_stats OK"))
    r = health.run_all()
    assert r["comfyui_process"]["ok"] is True
    assert r["comfyui_process"]["msg"] == "pid 123"


def test_run_all_functional_reconciliation_via_ssh_exec(monkeypatch):
    """check-40 Test 1: real check_* driven by ssh_exec side_effect
    (gpu, proc, api order); reconciliation override surfaces end-to-end."""
    _stub_ssh(
        monkeypatch,
        side_effect=[
            _cp(0, "Tesla V100-DGXS-32GB, 1024, 31510"),  # gpu success
            _cp(1, "", ""),                                # proc pgrep no match
            _cp(0, '{"system":1}'),                        # api success
        ],
    )
    r = health.run_all()
    assert r == {
        "gpu": {
            "ok": True,
            "msg": "Tesla V100-DGXS-32GB (used 1024 MiB / free 31510 MiB)",
        },
        "comfyui_process": {"ok": True, "msg": "(API live, pgrep no match)"},
        "comfyui_api": {"ok": True, "msg": "/system_stats OK"},
    }


def test_run_all_functional_all_fail_no_override(monkeypatch):
    """check-40 Test 2: all three fail → reconciliation does NOT fire;
    proc keeps original 'process not found' msg."""
    _stub_ssh(
        monkeypatch,
        side_effect=[
            _cp(1, "", "nvidia-smi failed"),  # gpu fail
            _cp(1, "", ""),                   # proc fail
            _cp(7, "", "conn refused"),       # api fail
        ],
    )
    r = health.run_all()
    assert r["gpu"]["ok"] is False
    assert r["comfyui_process"]["ok"] is False
    assert r["comfyui_process"]["msg"] == "ComfyUI process not found (pgrep no match)"
    assert r["comfyui_api"]["ok"] is False
    # All three structural keys present, each with ok + msg.
    assert set(r) == {"gpu", "comfyui_process", "comfyui_api"}
    for v in r.values():
        assert set(v) == {"ok", "msg"}


def test_run_all_functional_proc_alive_msg_preserved(monkeypatch):
    """check-40 Test 3: api ok AND proc ok → real pid msg must not be clobbered."""
    _stub_ssh(
        monkeypatch,
        side_effect=[
            _cp(0, "GPU, 1, 2"),     # gpu
            _cp(0, "12345\n"),       # proc alive
            _cp(0, "body"),          # api
        ],
    )
    r = health.run_all()
    assert r["comfyui_process"]["msg"] == "pid 12345"
    assert r["comfyui_process"]["ok"] is True
