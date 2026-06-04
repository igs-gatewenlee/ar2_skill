"""plan_loader 透明素材映射 + 跨 skill version guard（BC-6 / BC-12 / M-2）。"""
import sys
import types
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import plan_loader  # noqa: E402


# ── BC-6：route≠none 缺 asset_type → raise ──────────────────────

def test_bc6_missing_asset_type_raises():
    with pytest.raises(ValueError):
        plan_loader._resolve_transparent("coin", {"coin": {"route": "rembg"}}, {})


def test_route_none_when_slug_absent():
    route, atype, params = plan_loader._resolve_transparent("nope", {}, {})
    assert route == "none" and atype is None and params is None


def test_resolve_merges_defaults_and_params():
    route, atype, params = plan_loader._resolve_transparent(
        "coin",
        {"coin": {"route": "rembg", "asset_type": "opaque", "size": 512,
                  "params": {"alpha_blur": 2}}},
        {"bg_remove_strength": 0.5, "alpha_blur": 1},
    )
    assert route == "rembg" and atype == "opaque"
    assert params["bg_remove_strength"] == 0.5   # 來自 defaults
    assert params["size"] == 512                 # 來自 entry
    assert params["alpha_blur"] == 2             # entry.params 覆蓋 defaults


# ── BC-12 / M-2：SCHEMA_VERSION guard ───────────────────────────

def test_version_tuple_numeric_compare():
    # 字串比較會誤判 "1.10" < "1.9"；tuple 比較須正確
    assert plan_loader._version_tuple("1.10.0") > plan_loader._version_tuple("1.9.0")


def test_bc12_old_schema_version_raises(monkeypatch):
    fake = types.SimpleNamespace(SCHEMA_VERSION="1.0.0")
    monkeypatch.setattr(plan_loader, "_import_sibling_module", lambda *a, **k: fake)
    monkeypatch.delitem(sys.modules, plan_loader._PLAN_SCHEMA_MODULE_NAME, raising=False)
    with pytest.raises(RuntimeError, match="版本過舊"):
        plan_loader._import_plan_schema()


def test_real_schema_version_meets_requirement():
    mod = plan_loader._import_plan_schema()  # 真實 plan_schema 不應 raise
    assert (plan_loader._version_tuple(mod.SCHEMA_VERSION)
            >= plan_loader._version_tuple(plan_loader._REQUIRED_SCHEMA_VERSION))
