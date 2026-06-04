"""Tests for PuLID patch deploy + status (issue #5(b)).

Covers BC-1..12 and EH-1..5 in P1-design-spec.md. ssh_exec is mocked,
so no DGX connection is needed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pulid_patch  # noqa: E402


# ---------- Helpers ----------

def _cp(rc: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """Build a CompletedProcess for mocking ssh_exec."""
    return subprocess.CompletedProcess(args=["ssh"], returncode=rc, stdout=stdout, stderr=stderr)


def _ssh_sequence(monkeypatch, responses: list) -> mock.Mock:
    """Stub ssh_exec to return responses in order; record every call."""
    mock_exec = mock.Mock(side_effect=responses)
    monkeypatch.setattr(pulid_patch, "ssh_exec", mock_exec)
    return mock_exec


# Recurring response prefixes (probe + state-check pair from check_patch_status).
_PROBE_OK = _cp(0, "ok\n")
UNPATCHED_INIT = [_PROBE_OK, _cp(0, "0\n")]
PATCHED_INIT = [_PROBE_OK, _cp(0, "4\n")]


def _sent(mock_exec: mock.Mock) -> list[str]:
    """Extract the shell commands sent to the mocked ssh_exec."""
    return [c.args[0] for c in mock_exec.call_args_list]


# ---------- check_patch_status ----------

def test_check_status_patched(monkeypatch):
    """BC-1: marker count == 4 → patched."""
    _ssh_sequence(monkeypatch, PATCHED_INIT)
    assert pulid_patch.check_patch_status() == "patched"


def test_check_status_unpatched(monkeypatch):
    """BC-2: marker count == 0 → unpatched."""
    _ssh_sequence(monkeypatch, UNPATCHED_INIT)
    assert pulid_patch.check_patch_status() == "unpatched"


def test_check_status_mixed(monkeypatch):
    """BC-3: marker count between 1 and 3 → mixed."""
    _ssh_sequence(monkeypatch, [_PROBE_OK, _cp(0, "2\n")])
    assert pulid_patch.check_patch_status() == "mixed"


def test_check_status_missing_node(monkeypatch):
    """BC-4: custom_nodes dir absent → missing-node."""
    _ssh_sequence(monkeypatch, [_PROBE_OK, _cp(0, "MISSING_NODE\n")])
    assert pulid_patch.check_patch_status() == "missing-node"


def test_check_status_missing_file(monkeypatch):
    """BC-5: dir present, file absent → missing-file."""
    _ssh_sequence(monkeypatch, [_PROBE_OK, _cp(0, "MISSING_FILE\n")])
    assert pulid_patch.check_patch_status() == "missing-file"


def test_check_status_ssh_error_returncode_255(monkeypatch):
    """BC-11: ssh returncode 255 → ssh-error (not missing-node)."""
    _ssh_sequence(monkeypatch, [_cp(255, "", "ssh: connect to host: Connection refused")])
    assert pulid_patch.check_patch_status() == "ssh-error"


def test_check_status_ssh_error_connection_refused_in_stderr(monkeypatch):
    """BC-11: stderr contains 'Connection refused' (rc != 255) → ssh-error."""
    _ssh_sequence(monkeypatch, [_cp(1, "", "ssh_exchange_identification: Connection refused")])
    assert pulid_patch.check_patch_status() == "ssh-error"


def test_check_status_ssh_error_no_route(monkeypatch):
    """BC-11: stderr 'No route to host' → ssh-error."""
    _ssh_sequence(monkeypatch, [_cp(1, "", "ssh: connect to host 192.168.5.27: No route to host")])
    assert pulid_patch.check_patch_status() == "ssh-error"


def test_check_status_unexpected_shell_output_classified_as_ssh_error(monkeypatch):
    """Defensive: shell echoes garbage → ssh-error (treat as transport-class)."""
    _ssh_sequence(monkeypatch, [_PROBE_OK, _cp(0, "weird text\n")])
    assert pulid_patch.check_patch_status() == "ssh-error"


# ---------- apply_patch ----------

def test_apply_when_already_patched_is_noop(monkeypatch):
    """BC-6 (DR-4 behavioral assertion): patched → (True, "already patched")
    AND no `sed -i` command is sent."""
    mock_exec = _ssh_sequence(monkeypatch, PATCHED_INIT)
    ok, msg = pulid_patch.apply_patch()
    assert ok is True
    assert "already patched" in msg
    assert not any("sed -i" in cmd for cmd in _sent(mock_exec))


def test_apply_when_unpatched_with_no_backup_creates_backup_and_seds(monkeypatch):
    """BC-7 path (a): unpatched, no existing backup → cp + sed + verify."""
    mock_exec = _ssh_sequence(monkeypatch, [
        *UNPATCHED_INIT,                # initial check: unpatched
        _cp(0, "NO\n"),                 # backup test -f → not exists
        _cp(0),                         # cp succeeds
        _cp(0),                         # sed succeeds
        *PATCHED_INIT,                  # post-verify: patched
    ])
    ok, _msg = pulid_patch.apply_patch()
    assert ok is True
    sent = _sent(mock_exec)
    assert any(cmd.startswith("cp ") for cmd in sent), "cp backup not invoked"
    assert any("sed -i" in cmd for cmd in sent), "sed -i not invoked"


def test_apply_when_unpatched_with_pre_patch_backup_skips_cp_and_seds(monkeypatch):
    """BC-7 path (b) + BC-12: unpatched, backup exists + is pre-patch → skip cp, sed."""
    mock_exec = _ssh_sequence(monkeypatch, [
        *UNPATCHED_INIT,                # initial: unpatched
        _cp(0, "YES\n"),                # backup exists
        _cp(0, "0\n"),                  # backup grep count == 0 (pre-patch)
        _cp(0),                         # sed
        *PATCHED_INIT,                  # post-verify
    ])
    ok, _ = pulid_patch.apply_patch()
    assert ok is True
    assert not any(cmd.startswith("cp ") for cmd in _sent(mock_exec)), "should not re-create backup"


def test_apply_refuses_when_existing_backup_is_not_pre_patch(monkeypatch):
    """EH-5 (DR-3): existing backup has markers → refuse."""
    _ssh_sequence(monkeypatch, [
        *UNPATCHED_INIT,                # unpatched
        _cp(0, "YES\n"),                # backup exists
        _cp(0, "4\n"),                  # backup grep count == 4 (already-patched, suspicious)
    ])
    ok, msg = pulid_patch.apply_patch()
    assert ok is False
    assert "not pre-patch" in msg


def test_apply_dry_run_makes_no_changes(monkeypatch):
    """BC-8: dry_run=True → no cp, no sed, returns advisory message."""
    mock_exec = _ssh_sequence(monkeypatch, [
        *UNPATCHED_INIT,                # unpatched
        _cp(0, "NO\n"),                 # backup test -f → not exists
    ])
    ok, msg = pulid_patch.apply_patch(dry_run=True)
    assert ok is True
    assert "dry-run" in msg and "would" in msg
    sent = _sent(mock_exec)
    assert not any(cmd.startswith("cp ") for cmd in sent)
    assert not any("sed -i" in cmd for cmd in sent)


def test_apply_post_verify_failure(monkeypatch):
    """EH-2: sed runs but post-state is still not patched → (False, ...)."""
    _ssh_sequence(monkeypatch, [
        *UNPATCHED_INIT,                # unpatched
        _cp(0, "NO\n"),                 # no backup
        _cp(0),                         # cp ok
        _cp(0),                         # sed ok
        *UNPATCHED_INIT,                # post-verify still unpatched
    ])
    ok, msg = pulid_patch.apply_patch()
    assert ok is False
    assert "verification failed" in msg


def test_apply_when_mixed_refuses(monkeypatch):
    """EH-1: mixed → refuse, no sed."""
    mock_exec = _ssh_sequence(monkeypatch, [_PROBE_OK, _cp(0, "2\n")])
    ok, msg = pulid_patch.apply_patch()
    assert ok is False
    assert "partially patched" in msg
    assert not any("sed -i" in cmd for cmd in _sent(mock_exec))


def test_apply_when_missing_node(monkeypatch):
    """missing-node branch."""
    _ssh_sequence(monkeypatch, [_PROBE_OK, _cp(0, "MISSING_NODE\n")])
    ok, msg = pulid_patch.apply_patch()
    assert ok is False
    assert "not installed" in msg


def test_apply_when_missing_file(monkeypatch):
    """missing-file branch."""
    _ssh_sequence(monkeypatch, [_PROBE_OK, _cp(0, "MISSING_FILE\n")])
    ok, msg = pulid_patch.apply_patch()
    assert ok is False
    assert "missing" in msg


def test_apply_when_ssh_error(monkeypatch):
    """EH-3a (DR-1): SSH error → (False, 'cannot reach DGX')."""
    _ssh_sequence(monkeypatch, [_cp(255, "", "Connection refused")])
    ok, msg = pulid_patch.apply_patch()
    assert ok is False
    assert "cannot reach DGX" in msg


def test_apply_backup_creation_failure(monkeypatch):
    """cp failure → propagate as (False, ...)."""
    _ssh_sequence(monkeypatch, [
        *UNPATCHED_INIT,                # unpatched
        _cp(0, "NO\n"),                 # no backup
        _cp(1, "", "cp: cannot create"),  # cp fails
    ])
    ok, msg = pulid_patch.apply_patch()
    assert ok is False
    assert "backup creation failed" in msg


# ---------- status_summary_line ----------

def test_status_line_patched(monkeypatch):
    _ssh_sequence(monkeypatch, PATCHED_INIT)
    assert "✅ applied" in pulid_patch.status_summary_line()


def test_status_line_unpatched_mentions_flag(monkeypatch):
    _ssh_sequence(monkeypatch, UNPATCHED_INIT)
    line = pulid_patch.status_summary_line()
    assert "❌ unpatched" in line
    assert "--apply-pulid-patch" in line


def test_status_line_ssh_error(monkeypatch):
    _ssh_sequence(monkeypatch, [_cp(255, "", "Connection refused")])
    assert "SSH error" in pulid_patch.status_summary_line()
