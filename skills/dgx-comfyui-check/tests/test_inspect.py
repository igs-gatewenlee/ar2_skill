"""Tests for inspect.py (dgx-comfyui-check) — coverage gaps check-5..48.

Covers list_models / compare_to_expected / storage_summary / version_summary /
humanize_bytes / humanize_ago / format_report / load_last_cache / write_cache /
main() orchestration + argparse routing.

⚠️ 模組名 `inspect.py` 與 stdlib `inspect` 撞名（unittest.mock 依賴 stdlib
inspect.signature），故一律用 importlib.util.spec_from_file_location 以非 'inspect'
別名載入，不汙染 sys.modules['inspect']。ssh_exec / ping_host / 協作者全 mock，
測試純本地離線可跑，零 DGX/GPU/SSH/網路依賴。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _SKILL_ROOT / "scripts"

# config.py（skill root）→ _shared/ar2_registry 的 import 鏈需要這兩條 path。
for _p in (str(_SCRIPTS_DIR), str(_SKILL_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_inspect():
    """以非 'inspect' 別名載入受測 inspect.py（避開 stdlib shadow）。"""
    spec = importlib.util.spec_from_file_location(
        "dgx_inspect_under_test", _SCRIPTS_DIR / "inspect.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def insp():
    """每個測試拿到全新 module 物件，monkeypatch 互不汙染。"""
    return _load_inspect()


@pytest.fixture(autouse=True)
def _restore_pulid_patch_module():
    """還原全域共享的真實 pulid_patch 模組狀態。

    本檔部分測試以裸賦值 `insp.pulid_patch.<attr> = ...`（繞過 monkeypatch）
    替換 apply_patch / status_summary_line。insp 雖每次新建，但 insp.pulid_patch
    指向 sys.modules['pulid_patch'] 這個跨檔共享的真實模組——裸賦值會永久污染它，
    連累同目錄後跑的 test_pulid_patch.py（apply_patch 變 Mock）。
    此 fixture 在每個測試後還原該模組的原始屬性，杜絕跨檔污染。"""
    import pulid_patch as _pp  # 真實共享模組（scripts 已在 sys.path）
    _saved = dict(vars(_pp))
    yield
    _cur = vars(_pp)
    for _k in [k for k in _cur if k not in _saved]:
        del _cur[_k]
    _cur.update(_saved)


def _cp(rc: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """Build a CompletedProcess for mocking ssh_exec."""
    return subprocess.CompletedProcess(args=["ssh"], returncode=rc, stdout=stdout, stderr=stderr)


# =========================================================================
# list_models()  — check-5, check-28
# =========================================================================

def test_list_models_normal_multi_category(insp):
    """check-5 Test 1：多類正常解析，name/size 對應、size 為 int、空類為 []，
    keys 覆蓋全部 EXPECTED。"""
    insp.EXPECTED = {
        "diffusion_models": ["flux1-dev.safetensors"],
        "clip": ["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"],
        "sams": [],
    }

    def fake_ssh(cmd):
        if "/diffusion_models" in cmd:
            return _cp(0, "flux1-dev.safetensors\t23802932552\n")
        if "/clip" in cmd:
            return _cp(0, "t5xxl.safetensors\t9787841024\nclip_l.safetensors\t246144152\n")
        return _cp(0, "")

    insp.ssh_exec = fake_ssh
    result = insp.list_models()

    assert set(result.keys()) == set(insp.EXPECTED)
    assert result["diffusion_models"] == [
        {"name": "flux1-dev.safetensors", "size": 23802932552}
    ]
    assert result["clip"] == [
        {"name": "t5xxl.safetensors", "size": 9787841024},
        {"name": "clip_l.safetensors", "size": 246144152},
    ]
    assert result["sams"] == []
    # 所有 size 皆為 int
    for items in result.values():
        assert all(isinstance(it["size"], int) for it in items)


def test_list_models_skips_line_without_tab(insp):
    """check-5 Test 2 / check-28 Case A：無 tab 的行被略過。"""
    insp.EXPECTED = {"clip": ["x"]}
    insp.ssh_exec = lambda cmd: _cp(0, "no_tab_line\nvalid.safetensors\t100\n")
    result = insp.list_models()
    assert result["clip"] == [{"name": "valid.safetensors", "size": 100}]


def test_list_models_skips_unparseable_size(insp):
    """check-5 Test 3 / check-28 Case A：非整數 size 被略過、不崩潰。"""
    insp.EXPECTED = {"clip": ["x"]}
    insp.ssh_exec = lambda cmd: _cp(0, "bad.bin\tNOTANUMBER\ngood.bin\t512\n")
    result = insp.list_models()
    assert result["clip"] == [{"name": "good.bin", "size": 512}]


def test_list_models_empty_output_yields_empty_lists(insp):
    """check-5 Test 4 / check-28 Case B：空輸出每類為 []，keys 仍完整，
    ssh_exec 每類呼叫一次。"""
    insp.EXPECTED = {"clip": ["x"], "vae": ["y"], "sams": []}
    calls: list[str] = []

    def fake_ssh(cmd):
        calls.append(cmd)
        return _cp(0, "")

    insp.ssh_exec = fake_ssh
    result = insp.list_models()
    assert set(result.keys()) == set(insp.EXPECTED)
    assert all(v == [] for v in result.values())
    assert len(calls) == len(insp.EXPECTED)


def test_list_models_filename_with_tab_dropped(insp):
    """check-5 Test 5：檔名含 tab → split(maxsplit=1) 使 size_str 非數字 → 該項略過
    （記錄現行行為，非 bug）。"""
    insp.EXPECTED = {"clip": ["x"]}
    insp.ssh_exec = lambda cmd: _cp(0, "weird\tname.ckpt\t999\n")
    result = insp.list_models()
    assert result["clip"] == []


def test_list_models_combined_malformed_lines(insp):
    """check-28 Case A 合併：無 tab 行 + 非整數 size 行皆被略過，僅留 good_file。"""
    insp.EXPECTED = {"checkpoints": [], "loras": []}
    insp.ssh_exec = lambda cmd: _cp(
        0, "filename_no_tab\nvalidfile\tnot_an_int\ngood_file\t1000\n"
    )
    result = insp.list_models()
    for cat in insp.EXPECTED:
        assert result[cat] == [{"name": "good_file", "size": 1000}]


# =========================================================================
# compare_to_expected()  — check-6, check-34, check-48
# =========================================================================

def test_compare_missing_and_extra(insp):
    """check-6 Case 1：closed 類別同時報 missing+extra；open-ended 空類別不入 diff。"""
    insp.EXPECTED = {"clip": ["clip_l", "t5xxl_fp8"], "loras": []}
    inventory = {"clip": [{"name": "clip_l"}, {"name": "extra.bin"}]}
    diff = insp.compare_to_expected(inventory)
    assert diff == {"clip": {"missing": ["t5xxl_fp8"], "extra": ["extra.bin"]}}
    assert "loras" not in diff


def test_compare_open_ended_never_reports_extra(insp):
    """check-6 Case 2 / check-34 測 2：EXPECTED=[] 的開放類別有檔也不報 extra。"""
    insp.EXPECTED = {"clip": ["clip_l", "t5xxl_fp8"], "loras": []}
    inventory = {
        "clip": [{"name": "clip_l"}, {"name": "t5xxl_fp8"}],
        "loras": [{"name": "my_char.safetensors"}],
    }
    diff = insp.compare_to_expected(inventory)
    assert "loras" not in diff


def test_compare_missing_is_sorted(insp):
    """check-6 Case 3 / check-48：missing 為排序後的 list。"""
    insp.EXPECTED = {"clip": ["clip_l", "t5xxl_fp8"]}
    diff = insp.compare_to_expected({"clip": []})
    assert diff["clip"]["missing"] == ["clip_l", "t5xxl_fp8"]
    assert diff["clip"]["extra"] == []
    assert isinstance(diff["clip"]["missing"], list)


def test_compare_no_diff_category_omitted(insp):
    """check-6 Case 4 / check-34 測 4：完全符合的類別被 `if missing or extra` 省略。"""
    insp.EXPECTED = {"clip": ["clip_l", "t5xxl_fp8"]}
    diff = insp.compare_to_expected(
        {"clip": [{"name": "clip_l"}, {"name": "t5xxl_fp8"}]}
    )
    assert "clip" not in diff


def test_compare_empty_inventory_all_required_missing(insp):
    """check-34 測 1：空 inventory → 所有必備類別 missing；空 EXPECTED 類別不入 diff。"""
    insp.EXPECTED = {
        "diffusion_models": ["flux1-dev.safetensors"],
        "clip": ["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"],
        "loras": [],
        "sams": [],
    }
    diff = insp.compare_to_expected({})
    assert diff["diffusion_models"]["missing"] == ["flux1-dev.safetensors"]
    assert sorted(diff["clip"]["missing"]) == [
        "clip_l.safetensors",
        "t5xxl_fp8_e4m3fn.safetensors",
    ]
    assert "loras" not in diff and "sams" not in diff


def test_compare_closed_category_reports_extra(insp):
    """check-34 測 3：closed 類別（EXPECTED 非空）多餘檔報 extra。"""
    insp.EXPECTED = {"vae": ["flux_ae.safetensors"]}
    diff = insp.compare_to_expected(
        {"vae": [{"name": "flux_ae.safetensors"}, {"name": "rogue.safetensors"}]}
    )
    assert diff["vae"]["extra"] == ["rogue.safetensors"]
    assert diff["vae"]["missing"] == []


def test_compare_extra_sorted_deterministic(insp):
    """check-48：extra 為排序後 list（亂序輸入也輸出有序）。"""
    insp.EXPECTED = {"clip": ["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"]}
    inv = {
        "clip": [
            {"name": "t5xxl_fp8_e4m3fn.safetensors", "size": 1},
            {"name": "zzz_extra.safetensors", "size": 1},
            {"name": "aaa_extra.safetensors", "size": 1},
        ],
    }
    diff = insp.compare_to_expected(inv)
    assert diff["clip"]["extra"] == [
        "aaa_extra.safetensors",
        "zzz_extra.safetensors",
    ]
    assert "clip_l.safetensors" in diff["clip"]["missing"]
    assert diff["clip"]["missing"] == sorted(diff["clip"]["missing"])


# =========================================================================
# storage_summary()  — check-7, check-46
# =========================================================================

def test_storage_summary_normal(insp):
    """check-7 Test 1 / check-46 案例1：正常雙行解析 + df free。"""
    insp.ssh_exec = mock.Mock(
        side_effect=[_cp(0, "2\n1048576\n"), _cp(0, "3\n2097152\n"), _cp(0, "15G\n")]
    )
    assert insp.storage_summary() == {
        "output_entries": 2,
        "output_bytes": 1048576,
        "training_entries": 3,
        "training_bytes": 2097152,
        "free": "15G",
    }


def test_storage_summary_parse_guards(insp):
    """check-7 Test 2：非數字/負號/小數 isdigit()=False → 0；df rc!=0 → '?'。"""
    insp.ssh_exec = mock.Mock(
        side_effect=[_cp(0, "abc\nxyz\n"), _cp(0, "-5\n3.5\n"), _cp(1, "")]
    )
    assert insp.storage_summary() == {
        "output_entries": 0,
        "output_bytes": 0,
        "training_entries": 0,
        "training_bytes": 0,
        "free": "?",
    }


def test_storage_summary_empty_output(insp):
    """check-7 Test 3 / check-46 案例4：完全空輸出 → entries/bytes 全 0、free 仍解析。"""
    insp.ssh_exec = mock.Mock(side_effect=[_cp(0, ""), _cp(0, ""), _cp(0, "1G\n")])
    res = insp.storage_summary()
    assert res["output_entries"] == 0 and res["output_bytes"] == 0
    assert res["training_entries"] == 0 and res["training_bytes"] == 0
    assert res["free"] == "1G"


def test_storage_summary_single_line_no_index_error(insp):
    """check-46 案例2：du 失敗只回 1 行 → bytes=0（len(out)>1 guard 擋 IndexError）。"""
    insp.ssh_exec = mock.Mock(
        side_effect=[_cp(0, "5\n"), _cp(0, "5\n"), _cp(0, "100G\n")]
    )
    res = insp.storage_summary()
    assert res["output_entries"] == 5 and res["output_bytes"] == 0
    assert res["training_entries"] == 5 and res["training_bytes"] == 0


# =========================================================================
# version_summary()  — check-8
# =========================================================================

def test_version_summary_happy_path(insp):
    """check-8 Test 1：comfy short hash + custom_nodes 名/hash 解析。"""
    insp.ssh_exec = mock.Mock(
        side_effect=[
            _cp(0, "abc1234\n"),
            _cp(0, "node1 def5678\nnode2 ghi9012\n"),
        ]
    )
    assert insp.version_summary() == {
        "comfyui": "abc1234",
        "custom_nodes": {"node1": "def5678", "node2": "ghi9012"},
    }


def test_version_summary_comfy_unknown(insp):
    """check-8 Test 2：comfy git 失敗回 '?'。"""
    insp.ssh_exec = mock.Mock(side_effect=[_cp(0, "?\n"), _cp(0, "")])
    assert insp.version_summary()["comfyui"] == "?"


def test_version_summary_no_custom_nodes(insp):
    """check-8 Test 3：custom_nodes 空輸出 → {}。"""
    insp.ssh_exec = mock.Mock(side_effect=[_cp(0, "abc1234\n"), _cp(0, "")])
    assert insp.version_summary()["custom_nodes"] == {}


def test_version_summary_malformed_node_line_dropped(insp):
    """check-8 Test 4：單 token 行（無空白）len(parts)!=2 被略過。"""
    insp.ssh_exec = mock.Mock(
        side_effect=[_cp(0, "abc1234\n"), _cp(0, "node1 def5678\nbadline_no_space\n")]
    )
    assert insp.version_summary()["custom_nodes"] == {"node1": "def5678"}


# =========================================================================
# humanize_bytes()  — check-9
# =========================================================================

def test_humanize_bytes_unit_boundaries(insp):
    """check-9：各單位邊界（實測值）。"""
    assert insp.humanize_bytes(512) == "512.0B"
    assert insp.humanize_bytes(1023) == "1023.0B"
    assert insp.humanize_bytes(1024) == "1.0KB"
    assert insp.humanize_bytes(1048576) == "1.0MB"
    assert insp.humanize_bytes(1073741824) == "1.0GB"
    assert insp.humanize_bytes(1099511627776) == "1.0TB"
    assert insp.humanize_bytes(0) == "0.0B"


def test_humanize_bytes_tb_capped_pb_dead_code(insp):
    """check-9：TB 封頂——超過 TB 不進位到 PB（PB 分支為 dead code）。"""
    assert insp.humanize_bytes(1125899906842624) == "1024.0TB"
    assert insp.humanize_bytes(int(1e30)).endswith("TB")


def test_humanize_bytes_negative_defensive(insp):
    """check-9：負值不爆（防禦性，非預期輸入）。"""
    assert insp.humanize_bytes(-512) == "-512.0B"


# =========================================================================
# humanize_ago()  — check-10
# =========================================================================

def test_humanize_ago_boundaries(insp):
    """check-10 / check-41：秒/分鐘/小時/天四段 threshold + int vs :.1f 格式不對稱。"""
    assert insp.humanize_ago(0) == "0 秒前"
    assert insp.humanize_ago(30) == "30 秒前"
    assert insp.humanize_ago(59) == "59 秒前"
    assert insp.humanize_ago(60) == "1 分鐘前"
    assert insp.humanize_ago(120) == "2 分鐘前"
    assert insp.humanize_ago(3599) == "59 分鐘前"
    assert insp.humanize_ago(3600) == "1.0 小時前"
    assert insp.humanize_ago(7200) == "2.0 小時前"
    assert insp.humanize_ago(86399) == "24.0 小時前"
    assert insp.humanize_ago(86400) == "1.0 天前"
    assert insp.humanize_ago(90000) == "1.0 天前"
    assert insp.humanize_ago(172800) == "2.0 天前"


# =========================================================================
# format_report()  — check-11, check-29, check-41
# =========================================================================

def _green_health() -> dict:
    return {
        "gpu": {"ok": True, "msg": ""},
        "comfyui_process": {"ok": True, "msg": ""},
        "comfyui_api": {"ok": True, "msg": ""},
    }


def _storage() -> dict:
    return {
        "output_entries": 0,
        "output_bytes": 0,
        "training_entries": 0,
        "training_bytes": 0,
        "free": "1G",
    }


def test_format_report_unhealthy_and_missing(insp):
    """check-11 案例1：api 失敗 → 🔴 Health + ❌ API；missing → ❌ cat + 標註；
    humanize 進位；green-cats 折疊；首次盤點。"""
    insp.pulid_patch.status_summary_line = lambda: "PuLID patch: ✅ applied"
    insp.EXPECTED = {"checkpoints": ["a.safetensors"], "loras": []}
    health = {
        "gpu": {"ok": True, "msg": "V100"},
        "comfyui_process": {"ok": True, "msg": "running"},
        "comfyui_api": {"ok": False, "msg": "no response"},
    }
    inventory = {"checkpoints": [], "loras": [{"name": "x", "size": 5 * 1024 * 1024}]}
    diff = {"checkpoints": {"missing": ["a.safetensors"], "extra": []}}
    storage = {
        "output_entries": 3,
        "output_bytes": 1024,
        "training_entries": 1,
        "training_bytes": 2048,
        "free": "100G",
    }
    versions = {"comfyui": "abc1234", "custom_nodes": {"PuLID": "deadbee"}}
    out = insp.format_report(health, inventory, diff, storage, versions, None)

    assert "🔴 Health" in out
    assert "ComfyUI API  ❌" in out
    assert "❌ checkpoints" in out
    assert "missing: a.safetensors" in out
    assert "5.0MB" in out
    assert "(首次盤點)" in out
    assert "✅ (1 個分類全綠 → 折成統計列)" in out
    assert "ComfyUI @ abc1234" in out
    # 頭尾各一 '=='
    assert out.count("==") >= 2


def test_format_report_extra_warns_and_all_green_health(insp):
    """check-11 案例2：extra → ⚠️ + 全綠 health；checkpoints 落入折疊區；no .git nodes。"""
    insp.pulid_patch.status_summary_line = lambda: "PuLID patch: ✅ applied"
    insp.EXPECTED = {"checkpoints": ["a.safetensors"], "loras": []}
    inventory = {
        "checkpoints": [{"name": "a.safetensors", "size": 100}],
        "loras": [{"name": "junk", "size": 100}],
    }
    diff = {"loras": {"missing": [], "extra": ["junk"]}}
    versions = {"comfyui": "x", "custom_nodes": {}}
    out = insp.format_report(_green_health(), inventory, diff, _storage(), versions, None)

    assert "🟢 Health" in out
    assert "⚠️ loras" in out
    assert "1 unexpected" in out
    assert "100.0B" in out
    assert "custom_nodes: (none with .git)" in out
    # checkpoints 落入折疊統計區（在標頭之後）
    green_section = out.split("個分類全綠")[1]
    assert "checkpoints" in green_section


def test_format_report_three_category_collapse_and_emoji(insp):
    """check-29：三分類 green/missing/extra 的 collapse + emoji 分支。"""
    insp.pulid_patch.status_summary_line = lambda: "PuLID patch: ✅ applied"
    insp.EXPECTED = {
        "cat_green": [],
        "cat_missing": ["a.safetensors"],
        "cat_extra": ["keep.safetensors"],
    }
    inventory = {
        "cat_green": [{"name": "g", "size": 1}],
        "cat_missing": [],
        "cat_extra": [
            {"name": "keep.safetensors", "size": 1},
            {"name": "x.safetensors", "size": 1},
        ],
    }
    diff = {
        "cat_missing": {"missing": ["a.safetensors"], "extra": []},
        "cat_extra": {"missing": [], "extra": ["x.safetensors"]},
    }
    out = insp.format_report(_green_health(), inventory, diff, _storage(), {"comfyui": "x", "custom_nodes": {}}, None)
    lines = out.splitlines()

    # cat_green 不在主明細行（以 ❌/⚠️ 開頭），只在折疊區
    assert "✅ (1 個分類全綠 → 折成統計列)" in out
    green_section = out.split("個分類全綠")[1]
    assert "cat_green" in green_section

    # cat_missing 行：含 ❌ + missing 標註
    missing_line = next(l for l in lines if "cat_missing" in l)
    assert "❌" in missing_line
    assert "missing: a.safetensors" in missing_line

    # cat_extra 行：含 ⚠️ + 1 unexpected，且不含 missing:
    extra_line = next(l for l in lines if "cat_extra" in l)
    assert "⚠️" in extra_line
    assert "1 unexpected" in extra_line
    assert "missing:" not in extra_line


def test_format_report_all_green_collapse_count(insp):
    """check-29 附加：所有 EXPECTED 類別皆無 diff → 主明細無逐項 emoji 行，
    折疊區計數 == len(EXPECTED)。"""
    insp.pulid_patch.status_summary_line = lambda: "PuLID patch: ✅ applied"
    insp.EXPECTED = {"a": [], "b": [], "c": []}
    inventory = {"a": [{"name": "x", "size": 1}], "b": [], "c": []}
    out = insp.format_report(_green_health(), inventory, {}, _storage(), {"comfyui": "x", "custom_nodes": {}}, None)
    assert f"✅ ({len(insp.EXPECTED)} 個分類全綠 → 折成統計列)" in out
    # 主明細無 ❌ / ⚠️ 逐項行
    assert "❌" not in out
    assert "⚠️" not in out


def test_format_report_strftime_and_zero_truthiness(insp):
    """check-41：strftime 零填格式 + last_seen_at=0.0 走「首次盤點」（truthiness 邊界）。"""
    from datetime import datetime

    insp.pulid_patch.status_summary_line = lambda: "PuLID patch: ✅ applied"
    insp.EXPECTED = {"a": []}
    inventory = {"a": []}
    versions = {"comfyui": "x", "custom_nodes": {}}

    ts = datetime(2024, 3, 5, 9, 7).timestamp()
    out_ts = insp.format_report(_green_health(), inventory, {}, _storage(), versions, ts)
    assert "(上次盤點：03/05 09:07," in out_ts

    # last_seen_at=0.0 因 `if last_seen_at:` truthiness → 走首次盤點分支（記錄現況）
    out_zero = insp.format_report(_green_health(), inventory, {}, _storage(), versions, 0.0)
    assert "(首次盤點)" in out_zero
    assert "(上次盤點" not in out_zero


# =========================================================================
# load_last_cache() / write_cache()  — check-12, check-13, check-37
# =========================================================================

def test_load_last_cache_missing_returns_none(insp, tmp_path, monkeypatch):
    """check-12 / check-37 Case B：檔案不存在 → None（不拋）。"""
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    insp.CACHE_DIR = str(tmp_path / "nonexist")
    insp.LAST_INVENTORY_FILE = "last-inventory.json"
    assert insp.load_last_cache() is None


def test_load_last_cache_valid_json(insp, tmp_path, monkeypatch):
    """check-12 / check-37 Case A：合法 JSON → 回傳對應 dict。"""
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    insp.CACHE_DIR = str(tmp_path)
    insp.LAST_INVENTORY_FILE = "last-inventory.json"
    (tmp_path / "last-inventory.json").write_text(
        json.dumps({"timestamp": 123.0, "host": "dgx"})
    )
    result = insp.load_last_cache()
    assert result == {"timestamp": 123.0, "host": "dgx"}
    assert result["timestamp"] == 123.0


def test_load_last_cache_corrupt_returns_none(insp, tmp_path, monkeypatch):
    """check-12 / check-37 Case C：損毀 JSON → None（吞 JSONDecodeError，守住 main 退化路徑）。"""
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    insp.CACHE_DIR = str(tmp_path)
    insp.LAST_INVENTORY_FILE = "last-inventory.json"
    (tmp_path / "last-inventory.json").write_text("{not json")
    assert insp.load_last_cache() is None


def test_write_cache_schema_contract(insp, tmp_path, monkeypatch):
    """check-13：write_cache mkdir(parents) + schema key 契約 + versions→env_versions 映射。"""
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    nested = tmp_path / "a" / "b"  # 順帶驗 mkdir(parents=True)
    insp.CACHE_DIR = str(nested)
    insp.LAST_INVENTORY_FILE = "last-inventory.json"

    inventory = {"loras": [{"name": "x", "size": 1}]}
    versions = {"comfyui": "abc"}
    insp.write_cache(inventory, {"gpu": {"ok": True}}, versions, {"free": "10G"})

    cache_file = nested / "last-inventory.json"
    assert cache_file.exists()
    payload = json.loads(cache_file.read_text())
    assert set(payload.keys()) == {
        "timestamp",
        "host",
        "inventory",
        "health",
        "env_versions",
        "storage",
    }
    assert payload["host"] == insp.HOST
    assert payload["inventory"] == inventory
    assert payload["env_versions"] == versions  # versions→env_versions key 映射不漂
    assert isinstance(payload["timestamp"], (int, float))


def test_write_then_load_roundtrip(insp, tmp_path, monkeypatch):
    """check-13 + check-12：writer/reader 契約對 — 寫入後 load 取回同 payload。"""
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    insp.CACHE_DIR = str(tmp_path / "c")
    insp.LAST_INVENTORY_FILE = "last-inventory.json"
    insp.write_cache({"loras": []}, {"gpu": {"ok": True}}, {"comfyui": "z"}, {"free": "5G"})
    loaded = insp.load_last_cache()
    assert loaded is not None
    assert loaded["host"] == insp.HOST
    assert loaded["env_versions"] == {"comfyui": "z"}


# =========================================================================
# main() orchestration + routing  — check-14, check-26, check-42
# =========================================================================

def _stub_main_collaborators(insp, *, ping=True, health=None, diff=None):
    """共用 stub：把 main() 的下游協作者全 mock，回最小 dict。"""
    insp.ping_host = mock.Mock(return_value=ping)
    insp.load_last_cache = mock.Mock(return_value=None)
    insp.write_cache = mock.Mock()
    insp.format_report = mock.Mock(return_value="")
    insp.list_models = mock.Mock(return_value={})
    insp.storage_summary = mock.Mock(return_value={})
    insp.version_summary = mock.Mock(return_value={})
    insp.run_health = mock.Mock(
        return_value=health
        if health is not None
        else {
            "gpu": {"ok": True, "msg": ""},
            "comfyui_process": {"ok": True, "msg": ""},
            "comfyui_api": {"ok": True, "msg": ""},
        }
    )
    insp.compare_to_expected = mock.Mock(return_value=diff if diff is not None else {})


def test_main_healthy_returns_0_and_writes_cache(insp):
    """check-14 (a)：全健康 + 無 diff → 0，write_cache 被呼叫一次。"""
    _stub_main_collaborators(insp)
    assert insp.main([]) == 0
    assert insp.write_cache.call_count == 1


def test_main_ping_fails_returns_1_and_short_circuits(insp, capsys):
    """check-14 (b) / check-42 (1)：ping 失敗 → 1 + 訊息，run_health 不被呼叫（早退）。"""
    _stub_main_collaborators(insp, ping=False)
    assert insp.main([]) == 1
    captured = capsys.readouterr()
    assert "Cannot reach DGX @ 192.168.5.27" in captured.out
    assert insp.run_health.call_count == 0


def test_main_unhealthy_returns_2(insp):
    """check-14 (c-1)：health 有一項 ok=False → 2。"""
    _stub_main_collaborators(
        insp,
        health={
            "gpu": {"ok": False, "msg": ""},
            "comfyui_process": {"ok": True, "msg": ""},
            "comfyui_api": {"ok": True, "msg": ""},
        },
    )
    assert insp.main([]) == 2


def test_main_missing_models_returns_2(insp):
    """check-14 (c-2)：全 health ok 但有 missing → 2。"""
    _stub_main_collaborators(
        insp, diff={"loras": {"missing": ["x.safetensors"], "extra": []}}
    )
    assert insp.main([]) == 2


def test_main_extra_only_returns_0(insp):
    """check-14 (c-3) 邊界：只有 extra 無 missing + health 全綠 → 0
    （has_missing 用 d['missing'] 而非 diff 非空）。"""
    _stub_main_collaborators(insp, diff={"loras": {"missing": [], "extra": ["y"]}})
    assert insp.main([]) == 0


def test_main_apply_pulid_patch_routes_to_patch_flow(insp):
    """check-14 (d) / check-26 測1 / check-42 (2)：--apply-pulid-patch → 0，
    不走 ping/run_health（R-2 bypass 契約）。"""
    insp.ping_host = mock.Mock(side_effect=AssertionError("ping_host must not be called"))
    insp.run_health = mock.Mock(side_effect=AssertionError("run_health must not be called"))
    insp.pulid_patch.apply_patch = mock.Mock(return_value=(True, "done"))
    assert insp.main(["--apply-pulid-patch"]) == 0
    assert insp.pulid_patch.apply_patch.called
    assert insp.ping_host.call_count == 0
    assert insp.run_health.call_count == 0


def test_main_apply_pulid_patch_failure_returns_1(insp, capsys):
    """check-14 (d) / check-26 測2 / check-42 (3)：apply_patch 失敗 → 1 + ❌。"""
    insp.ping_host = mock.Mock(side_effect=AssertionError("ping_host must not be called"))
    insp.pulid_patch.apply_patch = mock.Mock(return_value=(False, "boom"))
    assert insp.main(["--apply-pulid-patch"]) == 1
    assert "❌" in capsys.readouterr().out


def test_main_no_flag_enters_inventory_flow(insp):
    """check-26 測3：無 flag → inventory flow，ping_host 短路（False）→ 1，
    證明不走 patch 分支（apply_patch 未被呼叫）。"""
    _stub_main_collaborators(insp, ping=False)
    insp.pulid_patch.apply_patch = mock.Mock()
    assert insp.main([]) == 1
    assert insp.ping_host.called
    assert insp.run_health.call_count == 0
    assert insp.pulid_patch.apply_patch.call_count == 0
