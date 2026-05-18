"""Tests for ComfyUI queue auto-clear (issue #6).

Covers BC-4, BC-5, BC-6, EH-3, EH-4 in P1-design-spec.md.
Mocks _get_json / _post_json so no ComfyUI tunnel is needed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import comfyui_api  # noqa: E402
import plan_runner  # noqa: E402


# -------- comfyui_api.get_queue_size --------------------------------------

def test_get_queue_size_empty(monkeypatch):
    monkeypatch.setattr(
        comfyui_api, "_get_json",
        lambda _p, **_kw: {"queue_pending": [], "queue_running": []},
    )
    assert comfyui_api.get_queue_size() == (0, 0)


def test_get_queue_size_with_items(monkeypatch):
    monkeypatch.setattr(
        comfyui_api, "_get_json",
        lambda _p, **_kw: {
            "queue_pending": [["n1", "id1"], ["n2", "id2"]],
            "queue_running": [["n3", "id3"]],
        },
    )
    assert comfyui_api.get_queue_size() == (2, 1)


def test_get_queue_size_api_error_returns_none(monkeypatch):
    """EH-3: GET /queue fails → None (does not raise)."""
    def boom(*_a, **_kw):
        raise comfyui_api.ComfyUIError("network down")
    monkeypatch.setattr(comfyui_api, "_get_json", boom)
    assert comfyui_api.get_queue_size() is None


def test_get_queue_size_unexpected_shape_returns_none(monkeypatch):
    """Defensive: unexpected response type returns None, not crash."""
    monkeypatch.setattr(comfyui_api, "_get_json", lambda _p, **_kw: "not a dict")
    assert comfyui_api.get_queue_size() is None


def test_get_queue_size_missing_keys_defaults_to_zero(monkeypatch):
    """Defensive: missing queue_pending/running keys -> (0, 0)."""
    monkeypatch.setattr(comfyui_api, "_get_json", lambda _p, **_kw: {})
    assert comfyui_api.get_queue_size() == (0, 0)


# -------- comfyui_api.clear_queue -----------------------------------------

def test_clear_queue_success(monkeypatch):
    posted = {}

    def fake_post(path, payload, **_kw):
        posted["path"] = path
        posted["payload"] = payload
        return {}
    monkeypatch.setattr(comfyui_api, "_post_json", fake_post)

    assert comfyui_api.clear_queue() is True
    assert posted == {"path": "/queue", "payload": {"clear": True}}


def test_clear_queue_failure_returns_false(monkeypatch):
    """EH-4: POST fail → False (does not raise)."""
    def boom(*_a, **_kw):
        raise comfyui_api.ComfyUIError("HTTP 500")
    monkeypatch.setattr(comfyui_api, "_post_json", boom)

    assert comfyui_api.clear_queue() is False


# -------- plan_runner._clear_stale_queue -----------------------------------

def _patch_queue_apis(monkeypatch, *, size, clear_returns=True):
    """Stub get_queue_size + clear_queue; return a list that records clear calls."""
    clear_calls: list[int] = []

    def fake_clear() -> bool:
        clear_calls.append(1)
        return clear_returns

    monkeypatch.setattr(plan_runner.api, "get_queue_size", lambda: size)
    monkeypatch.setattr(plan_runner.api, "clear_queue", fake_clear)
    return clear_calls


def test_clear_stale_queue_skips_when_empty(monkeypatch, capsys):
    """BC-5: queue empty → no clear, no warning."""
    clear_calls = _patch_queue_apis(monkeypatch, size=(0, 0))

    plan_runner._clear_stale_queue()

    out = capsys.readouterr().out
    assert "Found" not in out
    assert clear_calls == []


def test_clear_stale_queue_clears_when_non_empty(monkeypatch, capsys):
    """BC-6: queue non-empty → warning printed + clear_queue called."""
    clear_calls = _patch_queue_apis(monkeypatch, size=(3, 1))

    plan_runner._clear_stale_queue()

    out = capsys.readouterr().out
    assert "Found 4 stale queue items" in out
    assert "3 pending" in out
    assert "1 running" in out
    assert clear_calls == [1]


def test_clear_stale_queue_handles_size_api_failure(monkeypatch, capsys):
    """EH-3 propagation: get_queue_size returns None → warn + continue."""
    clear_calls = _patch_queue_apis(monkeypatch, size=None)

    plan_runner._clear_stale_queue()

    out = capsys.readouterr().out
    assert "queue check failed" in out
    assert clear_calls == []


def test_clear_stale_queue_handles_clear_api_failure(monkeypatch, capsys):
    """EH-4 propagation: clear_queue returns False → warn but don't raise."""
    _patch_queue_apis(monkeypatch, size=(2, 0), clear_returns=False)

    # Must not raise:
    plan_runner._clear_stale_queue()

    out = capsys.readouterr().out
    assert "Found 2 stale queue items" in out
    assert "queue clear POST failed" in out


# -------- BC-4: _clear_stale_queue called by _run --------------------------

def test_run_calls_clear_stale_queue_before_submit(monkeypatch):
    """BC-4: _run() invokes _clear_stale_queue exactly once before submit."""
    call_order: list[str] = []

    def record(name: str, result=None):
        """Build a stub that records its name into call_order and returns `result`."""
        def stub(*_a, **_kw):
            call_order.append(name)
            return result
        return stub

    class FakeLoaded:
        workflow = "flux_pulid"
        items = []
        face_ref = None
        size = (1024, 1024)
        steps = 20
        negative = ""
        mode = "plan"

    # Stub external dependencies of _run so we can run it offline.
    monkeypatch.setattr(plan_runner, "_resolve_workflow",
                        lambda _wf: Path("/tmp/fake.json"))
    monkeypatch.setattr(plan_runner.plan_loader, "strip_workflow_metadata",
                        lambda w: w)
    monkeypatch.setattr(plan_runner.json, "loads", lambda _s: {})
    monkeypatch.setattr(Path, "read_text", lambda _self: "{}")

    monkeypatch.setattr(plan_runner, "ensure_tunnel", record("tunnel"))
    monkeypatch.setattr(plan_runner, "_clear_stale_queue", record("clear"))
    monkeypatch.setattr(plan_runner, "_upload_face_ref", record("face_ref"))
    monkeypatch.setattr(plan_runner, "_submit_all", record("submit", result=[]))
    monkeypatch.setattr(plan_runner, "_write_history", lambda *_a, **_kw: None)

    rc = plan_runner._run(FakeLoaded(), Path("/tmp/h.jsonl"), Path("/tmp"), "demo")

    assert rc == 2  # no submissions succeeded with empty items
    # Order: ensure_tunnel → _clear_stale_queue → _upload_face_ref → _submit_all
    assert call_order[:4] == ["tunnel", "clear", "face_ref", "submit"]
