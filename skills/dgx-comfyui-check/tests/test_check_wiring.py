"""Wiring smoke tests for dgx-comfyui-check (coverage gaps check-24, check-25).

兩個缺口集中於此檔（皆純本地、零 DGX/網路）：

- check-24: ssh_client.ensure_tunnel() 背景 tunnel 建立邏輯（早退守衛 /
  Unix subprocess.run check=True 分支 / bounded poll loop）。
  既有 test_queue_clear.py 只把 ensure_tunnel 整個換掉驗呼叫順序、不碰內部；
  test_ssh_retry.py 只測 scp retry。此處補其控制流。
- check-25: config.py shim 的 import wiring（sys.path.insert + `from ar2_registry
  import *` 在 config 命名空間下 runtime import 成功；_SKILL 目錄名推導出的
  CACHE_DIR / LOCAL_OUTPUT_DIR_NAME 正確；__all__ 含 PASSWORD ∴ import * 時
  eager 解析、缺 secrets 即 import 階段 fail-loud）。
  既有 test_registry.py 的 test_ct1 只做靜態文字掃名、從不 runtime import shim。

subprocess / SSH / secrets 全部 mock 或用 env 控制，無真實 DGX 連線。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

# ---- import the (production, unmodified) ssh_client under test --------------
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import ssh_client  # noqa: E402

# .../skills（check / gen / train 三個 skill 的共同父目錄）
SKILLS_DIR = Path(__file__).resolve().parents[2]


# ===========================================================================
# check-24 : ssh_client.ensure_tunnel()
# ===========================================================================

@pytest.fixture
def unix_tooling(monkeypatch):
    """強制 Unix 路徑 + 假裝 sshpass 已安裝，使 _check_tooling 不 raise。"""
    monkeypatch.setattr(ssh_client, "IS_WIN", False)
    monkeypatch.setattr(ssh_client.shutil, "which", lambda _name: "/usr/bin/sshpass")


@pytest.fixture
def record_sleeps(monkeypatch):
    """把 time.sleep patch 成 no-op，並收集每次的秒數（破除 timing 顧慮）。"""
    sleeps: list[float] = []
    monkeypatch.setattr(ssh_client.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def _cp_ok():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")


def test_ensure_tunnel_early_return_when_already_present(
    monkeypatch, unix_tooling, record_sleeps
):
    """T1 早退守衛：tunnel_exists 已 True → 完全不 spawn subprocess。"""
    monkeypatch.setattr(ssh_client, "tunnel_exists", lambda: True)
    run_mock = mock.Mock()
    monkeypatch.setattr(ssh_client.subprocess, "run", run_mock)

    ssh_client.ensure_tunnel()

    assert run_mock.call_count == 0
    assert record_sleeps == []


def test_ensure_tunnel_unix_spawns_and_polls_to_success(
    monkeypatch, unix_tooling, record_sleeps
):
    """T2 Unix spawn + poll 成功：前置 False、poll 第一輪 True。

    斷言：run 呼叫一次、命令含 sshpass / -fN / 正確的 -L 轉發、check=True。
    """
    # [前置檢查 False, poll 第一輪 True]
    monkeypatch.setattr(
        ssh_client, "tunnel_exists", mock.Mock(side_effect=[False, True])
    )
    run_mock = mock.Mock(return_value=_cp_ok())
    monkeypatch.setattr(ssh_client.subprocess, "run", run_mock)

    ssh_client.ensure_tunnel()

    assert run_mock.call_count == 1
    args, kwargs = run_mock.call_args
    cmd = args[0]
    assert "sshpass" in cmd
    assert "-fN" in cmd
    fwd = f"{ssh_client.COMFYUI_PORT}:localhost:{ssh_client.COMFYUI_PORT}"
    assert fwd in cmd
    assert kwargs.get("check") is True
    # poll 第一輪即成功 → 不該 sleep
    assert record_sleeps == []


def test_ensure_tunnel_unix_spawn_failure_raises(
    monkeypatch, unix_tooling, record_sleeps
):
    """T3 Unix spawn 失敗：check=True 語意 → 應 raise CalledProcessError。"""
    monkeypatch.setattr(ssh_client, "tunnel_exists", lambda: False)
    run_mock = mock.Mock(
        side_effect=subprocess.CalledProcessError(returncode=1, cmd=["ssh"])
    )
    monkeypatch.setattr(ssh_client.subprocess, "run", run_mock)

    with pytest.raises(subprocess.CalledProcessError):
        ssh_client.ensure_tunnel()

    assert run_mock.call_count == 1


def test_ensure_tunnel_bounded_poll_loop_caps_at_20(
    monkeypatch, unix_tooling, record_sleeps
):
    """T4 poll loop 邊界：spawn 後 tunnel 始終沒起來 → 正常返回（不 raise）、

    sleep 恰 20 次（poll 上限），每次 0.25s。
    """
    # 前置檢查 False + 之後 poll 每輪都 False（給足夠多 False）
    monkeypatch.setattr(
        ssh_client, "tunnel_exists", mock.Mock(side_effect=[False] + [False] * 25)
    )
    run_mock = mock.Mock(return_value=_cp_ok())
    monkeypatch.setattr(ssh_client.subprocess, "run", run_mock)

    ssh_client.ensure_tunnel()  # 不應 raise

    assert run_mock.call_count == 1
    assert len(record_sleeps) == 20
    assert set(record_sleeps) == {0.25}


def test_ensure_tunnel_windows_uses_detached_popen(monkeypatch, record_sleeps):
    """T5（Windows 分支）：IS_WIN=True → 走 detached plink.exe Popen。

    斷言：subprocess.run 不被呼叫、Popen 被呼叫一次、命令含 plink.exe / -N，
    creationflags 含 DETACHED_PROCESS。
    """
    monkeypatch.setattr(ssh_client, "IS_WIN", True)
    # Windows tooling check 找 plink.exe / pscp.exe
    monkeypatch.setattr(
        ssh_client.shutil, "which", lambda name: f"C:\\PuTTY\\{name}"
    )
    # subprocess.DETACHED_PROCESS / CREATE_NEW_PROCESS_GROUP 僅存在於 win32 Python；
    # 在非 Windows host 跑此分支需把這兩個 flag 常數注入 module（生產碼 inline 取用），
    # 用 raising=False 確保 macOS/Linux 上也能 setattr，並於 case 結束自動還原。
    monkeypatch.setattr(
        ssh_client.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False
    )
    monkeypatch.setattr(
        ssh_client.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False
    )
    # 前置檢查 False、poll 第一輪 True（避免進 sleep loop）
    monkeypatch.setattr(
        ssh_client, "tunnel_exists", mock.Mock(side_effect=[False, True])
    )
    run_mock = mock.Mock(return_value=_cp_ok())
    popen_mock = mock.Mock()
    monkeypatch.setattr(ssh_client.subprocess, "run", run_mock)
    monkeypatch.setattr(ssh_client.subprocess, "Popen", popen_mock)

    ssh_client.ensure_tunnel()

    assert run_mock.call_count == 0, "Windows 路徑不該用 subprocess.run"
    assert popen_mock.call_count == 1
    args, kwargs = popen_mock.call_args
    cmd = args[0]
    assert "plink.exe" in cmd
    assert "-N" in cmd
    flags = kwargs.get("creationflags", 0)
    assert flags & subprocess.DETACHED_PROCESS


# ===========================================================================
# check-25 : config.py shim import wiring
# ===========================================================================

def _load_shim(skill: str, mod_name: str):
    """以唯一模組名動態 exec 指定 skill 的 config.py shim 並回傳模組物件。

    每次都先 pop ar2_registry，使其重新 import（重置 _PASSWORD_CACHE，
    讓 import * 對 PASSWORD 的 eager 解析依當下 env 重新發生）。
    """
    sys.modules.pop("ar2_registry", None)
    sys.modules.pop(mod_name, None)
    p = SKILLS_DIR / f"dgx-comfyui-{skill}" / "config.py"
    spec = importlib.util.spec_from_file_location(mod_name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _shim_env(monkeypatch):
    """check-25 預設：env 提供密碼（避免 import * eager 解析 PASSWORD 失敗）。

    fail-loud 測試會在 case 內自行 delenv 覆蓋。registry 走 co-located toml，不改。
    用 dummy 值即可（測試只需非空密碼讓 import * 不炸，不依賴真實密碼值、不洩漏）。
    """
    monkeypatch.setenv("AR2_DGX_PASSWORD", "dummy-pw")


def test_shim_imports_and_reexports():
    """check-25 核心：shim 真的 runtime import + import * 把 registry 扁平面帶入。

    HOST/COMFYUI_PORT 斷言驗的是「import * 確實把值帶進 shim 命名空間」（runtime，
    非 test_ct1 的靜態掃名），不是重測 registry 字面。
    """
    for skill in ("check", "gen", "train"):
        m = _load_shim(skill, f"config_shim_{skill}")
        assert m.HOST == "192.168.5.27", f"{skill}: import * 未帶入 HOST"
        assert m.COMFYUI_PORT == 8199, f"{skill}: import * 未帶入 COMFYUI_PORT"
        assert isinstance(m.EXPECTED_MODELS, dict)
        assert callable(m.cache_dir_for)


def test_shim_per_skill_cache_dir_derivation():
    """check-25 核心：_SKILL = 目錄名去前綴後，CACHE_DIR / LOCAL_OUTPUT_DIR_NAME
    由目錄名正確在地推導（壞掉的目錄名/推導會被 catch，ct2 用硬編 'gen' 抓不到）。
    """
    for skill in ("check", "gen", "train"):
        m = _load_shim(skill, f"config_shim_{skill}")
        assert m.CACHE_DIR == f"~/.cache/ar2-dgx-comfyui-{skill}", (
            f"{skill}: CACHE_DIR 推導錯 → {m.CACHE_DIR}"
        )
        assert m.LOCAL_OUTPUT_DIR_NAME == f"outputs/ar2-dgx-comfyui-{skill}", (
            f"{skill}: LOCAL_OUTPUT_DIR_NAME 推導錯 → {m.LOCAL_OUTPUT_DIR_NAME}"
        )
    # 三 skill 各異（擋『一個 flat attr 裝三值』假 drop-in）
    dirs = {
        _load_shim(s, f"config_shim_{s}").CACHE_DIR
        for s in ("check", "gen", "train")
    }
    assert len(dirs) == 3


def test_shim_import_fail_loud_without_secret(monkeypatch, tmp_path):
    """check-25 核心：PASSWORD 在 __all__ → import * 觸發 eager 解析；

    缺 env 密碼且 secrets.toml 不存在 → shim 應在 import 階段就 RuntimeError
    （fail-loud，不是延後到取用 PASSWORD 才炸）。
    """
    monkeypatch.delenv("AR2_DGX_PASSWORD", raising=False)
    monkeypatch.setenv("AR2_SECRETS_FILE", str(tmp_path / "nope.toml"))
    # _load_shim 已會 pop ar2_registry（重置 _PASSWORD_CACHE）
    with pytest.raises(RuntimeError):
        _load_shim("gen", "config_shim_faildload")
