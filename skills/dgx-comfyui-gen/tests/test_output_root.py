"""FU-1: output root anchoring (產物落 CC 專案根/outputs，不跟 cwd 漂)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import plan_runner  # noqa: E402


def test_priority_ar2_output_root(monkeypatch):
    monkeypatch.setenv("AR2_OUTPUT_ROOT", "/tmp/proj_a")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/tmp/proj_b")
    assert plan_runner._output_root() == Path("/tmp/proj_a")


def test_priority_claude_project_dir(monkeypatch):
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/tmp/proj_b")
    assert plan_runner._output_root() == Path("/tmp/proj_b")


def test_fallback_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    # no env anchor → falls back to cwd (compare to Path.cwd() to avoid
    # macOS /tmp→/private/tmp symlink-resolution mismatch).
    assert plan_runner._output_root() == Path.cwd()


def test_expanduser(monkeypatch):
    monkeypatch.setenv("AR2_OUTPUT_ROOT", "~/somewhere")
    assert plan_runner._output_root() == Path("~/somewhere").expanduser()
