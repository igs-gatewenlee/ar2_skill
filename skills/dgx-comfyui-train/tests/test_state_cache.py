"""Tests for state_cache — training-run state persistence (local JSON cache).

Covers P3 coverage gaps:
- train-9:  write() — setdefault('run_id') 語意 + 無條件刷新 updated_at(float)
            + 自動建目錄 + JSON indent=2 有效性
- train-10: update() — partial merge / 新 key / timestamp refresh
            / non-existent run_id 走 existing={} / None 值合併 / 回傳==持久化
- train-11: read() — corrupted JSON / missing file → None（不拋例外）+ happy path
- train-12: list_recent() — updated_at 降序 + limit slice + 空 cache
            + 缺 updated_at 容錯沉底 + 壞 JSON 跳過

Hermetic（F-1 教訓）：所有測試 monkeypatch state_cache.CACHE_DIR 指向 tmp_path
（_cache_root() 以 module-global 名稱 CACHE_DIR 取值，setattr 可重導向），
並 delenv AR2_OUTPUT_ROOT / CLAUDE_PROJECT_DIR + chdir(tmp_path) 確保零 process 環境依賴。
受測 module 純本地檔案 I/O，無 DGX/GPU/SSH/網路依賴，無需 mock 實機。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import state_cache  # noqa: E402


@pytest.fixture
def cache_at_tmp(tmp_path, monkeypatch):
    """重導向 cache 根到 tmp_path 並隔離 process 環境（hermetic）。"""
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(state_cache, "CACHE_DIR", str(tmp_path))
    return tmp_path


# ---------- train-9: write() ----------

def test_write_new_run_returns_path_and_persists_payload(cache_at_tmp):
    """train-9(1): 新 run 寫入 → 回傳值 == cache_path 且檔案存在，
    payload 原欄位 + 注入 run_id + float updated_at 全到位。
    """
    before = time.time()
    p = state_cache.write("r1", {"state": "pending"})
    after = time.time()

    assert p == state_cache.cache_path("r1")
    assert p.exists()

    data = json.loads(p.read_text())
    assert data["state"] == "pending"
    assert data["run_id"] == "r1"
    assert isinstance(data["updated_at"], float)
    assert before <= data["updated_at"] <= after
    # 確認沒有混入其他鍵。
    assert set(data.keys()) == {"state", "run_id", "updated_at"}


def test_write_setdefault_does_not_overwrite_caller_run_id(cache_at_tmp):
    """train-9(2): setdefault 語意 — 呼叫端已給 run_id 時不被覆蓋。"""
    state_cache.write("r1", {"run_id": "EXPLICIT", "state": "x"})
    assert state_cache.read("r1")["run_id"] == "EXPLICIT"


def test_write_always_refreshes_updated_at(cache_at_tmp, monkeypatch):
    """train-9(3): updated_at 必刷新 — 連寫兩次同 run 取得不同 timestamp。"""
    fake_times = iter([1000.0, 2000.0])
    monkeypatch.setattr(state_cache.time, "time", lambda: next(fake_times))

    state_cache.write("r1", {"state": "a"})
    first = state_cache.read("r1")["updated_at"]
    state_cache.write("r1", {"state": "b"})
    second = state_cache.read("r1")["updated_at"]

    assert first == 1000.0
    assert second == 2000.0
    assert second != first


def test_write_auto_creates_missing_cache_dir(tmp_path, monkeypatch):
    """train-9(4): CACHE_DIR 子目錄不存在時 write() 自動建立。"""
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    nonexistent = tmp_path / "nonexistent_sub"
    assert not nonexistent.exists()
    monkeypatch.setattr(state_cache, "CACHE_DIR", str(nonexistent))

    state_cache.write("r1", {"state": "pending"})

    assert nonexistent.is_dir()
    assert (nonexistent / "r1.json").exists()


def test_write_emits_indented_valid_json(cache_at_tmp):
    """train-9(5): 寫出的是 indent=2 的合法 JSON（含換行 + 兩空格縮排）。"""
    p = state_cache.write("r1", {"state": "pending"})
    raw = p.read_text()
    assert "\n  " in raw  # indent=2 的縮排特徵
    # 不拋例外 = 有效 JSON。
    parsed = json.loads(raw)
    assert parsed["state"] == "pending"


# ---------- train-10: update() ----------

def test_update_merges_preserves_overwrites_adds_and_refreshes(cache_at_tmp, monkeypatch):
    """train-10(1): partial merge — 保留既有 / 覆蓋衝突 / 新增 key,
    刷新 updated_at, 且回傳的 merged 與持久化結果相等。
    """
    fake_times = iter([1000.0, 2000.0])
    monkeypatch.setattr(state_cache.time, "time", lambda: next(fake_times))

    state_cache.write("id1", {"state": "pending"})
    t0 = state_cache.read("id1")["updated_at"]

    merged = state_cache.update("id1", state="running", pid=12345)
    r = state_cache.read("id1")

    assert r["run_id"] == "id1"        # 保留
    assert r["state"] == "running"     # 覆蓋
    assert r["pid"] == 12345           # 新增
    assert r["updated_at"] > t0        # 刷新
    assert merged == r                 # 回傳值 == 持久化值
    assert set(r.keys()) == {"run_id", "state", "pid", "updated_at"}


def test_update_nonexistent_run_uses_empty_dict_path(cache_at_tmp):
    """train-10(2): 不存在的 run_id → existing={} 路徑，建立全新 entry。"""
    state_cache.update("ghost", state="deployed")
    r = state_cache.read("ghost")
    assert r["run_id"] == "ghost"
    assert r["state"] == "deployed"
    assert "updated_at" in r
    assert isinstance(r["updated_at"], float)


def test_update_merges_none_value(cache_at_tmp):
    """train-10(3): None 值正常合併（不被視為「缺值」丟棄）。"""
    state_cache.write("id1", {"state": "running"})
    state_cache.update("id1", failure_reason=None)
    r = state_cache.read("id1")
    assert "failure_reason" in r
    assert r["failure_reason"] is None


# ---------- train-11: read() error handling ----------

def test_read_corrupted_json_returns_none(cache_at_tmp):
    """train-11(1): 損壞 JSON → JSONDecodeError 被吞, 回 None（不拋例外）。"""
    state_cache.cache_path("rid").write_text("{broken")
    assert state_cache.read("rid") is None


def test_read_missing_file_returns_none(cache_at_tmp):
    """train-11(2): 檔案不存在 → path.exists() False 分支, 回 None。"""
    assert state_cache.read("nonexistent-id") is None


def test_read_happy_path_not_over_caught(cache_at_tmp):
    """train-11(3): 正常檔案 happy path 不被 over-catch 影響。"""
    state_cache.write("rid2", {"state": "finished"})
    entry = state_cache.read("rid2")
    assert entry is not None
    assert entry["state"] == "finished"


def test_read_empty_file_returns_none(cache_at_tmp):
    """train-11(4 可選): 空字串檔（非 chmod，避免 root/CI flaky）→ 回 None。"""
    state_cache.cache_path("empty").write_text("")
    assert state_cache.read("empty") is None


# ---------- train-12: list_recent() ----------
#
# 注意：write() 會以 time.time() 無條件覆寫 updated_at，無法控制值；
# 故排序相關測試直接 path.write_text(json.dumps(...)) 手寫檔以鎖定 updated_at。

def _seed_raw(root: Path, run_id: str, payload: dict) -> None:
    """直接寫一份 cache 檔（繞過 write()，保留指定的 updated_at）。"""
    (root / f"{run_id}.json").write_text(json.dumps(payload))


def test_list_recent_sorts_desc_and_applies_limit(cache_at_tmp):
    """train-12(1): updated_at 降序 + limit slice。
    [100,400,200,500,300] limit=3 → r4(500), r2(400), r5(300)。
    """
    ua = {"r1": 100, "r2": 400, "r3": 200, "r4": 500, "r5": 300}
    for rid, t in ua.items():
        _seed_raw(cache_at_tmp, rid, {"run_id": rid, "updated_at": t})

    result = state_cache.list_recent(limit=3)
    assert [e["run_id"] for e in result] == ["r4", "r2", "r5"]
    assert len(result) == 3


def test_list_recent_empty_cache_returns_empty_list(cache_at_tmp):
    """train-12(2): 空 cache 目錄 → []。"""
    assert state_cache.list_recent() == []


def test_list_recent_limit_exceeds_count_returns_all_sorted(cache_at_tmp):
    """train-12(3): limit > 檔案數 → 回全部, 仍降序。"""
    _seed_raw(cache_at_tmp, "a", {"run_id": "a", "updated_at": 10})
    _seed_raw(cache_at_tmp, "b", {"run_id": "b", "updated_at": 20})
    result = state_cache.list_recent(limit=10)
    assert [e["run_id"] for e in result] == ["b", "a"]
    assert len(result) == 2


def test_list_recent_missing_updated_at_sinks_to_bottom(cache_at_tmp):
    """train-12(4): 缺 updated_at 欄位 → .get(...,0) 容錯不拋例外, 沉底。"""
    _seed_raw(cache_at_tmp, "r_a", {"run_id": "r_a", "updated_at": 100})
    _seed_raw(cache_at_tmp, "r_b", {"run_id": "r_b"})  # 無 updated_at
    result = state_cache.list_recent()
    assert len(result) == 2
    assert result[-1]["run_id"] == "r_b"


def test_list_recent_skips_broken_json(cache_at_tmp):
    """train-12(5): 壞 JSON 檔被跳過, 只回合法那筆, 不拋例外。"""
    _seed_raw(cache_at_tmp, "good", {"run_id": "good", "updated_at": 1})
    (cache_at_tmp / "bad.json").write_text("not json")
    result = state_cache.list_recent()
    assert [e["run_id"] for e in result] == ["good"]
    assert len(result) == 1
