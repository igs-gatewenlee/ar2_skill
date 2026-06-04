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


# ---------- FU-2: _run_output_dir (date folder + C 單item省run) ----------

import datetime  # noqa: E402
import re  # noqa: E402

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def test_run_dir_single_item_omits_run_layer(monkeypatch, tmp_path):
    monkeypatch.setenv("AR2_OUTPUT_ROOT", str(tmp_path))
    p = plan_runner._run_output_dir("outputs/ar2-dgx-comfyui-transparent", "myrun", 1)
    date = datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
    # 單 item → <root>/outputs/ar2-dgx-comfyui-transparent/<date>（無 myrun）
    assert p == tmp_path / "outputs/ar2-dgx-comfyui-transparent" / date
    assert "myrun" not in str(p)


def test_run_dir_multi_item_keeps_run_layer(monkeypatch, tmp_path):
    monkeypatch.setenv("AR2_OUTPUT_ROOT", str(tmp_path))
    p = plan_runner._run_output_dir("outputs/ar2-dgx-comfyui-gen", "myrun", 5)
    date = datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
    # 多 item → <root>/outputs/ar2-dgx-comfyui-gen/<date>/myrun
    assert p == tmp_path / "outputs/ar2-dgx-comfyui-gen" / date / "myrun"


def test_run_dir_has_date_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("AR2_OUTPUT_ROOT", str(tmp_path))
    p = plan_runner._run_output_dir("outputs/x", "r", 1)
    # 路徑含 YYYY-MM-DD 日期夾
    assert _DATE_RE.search(p.name)
