"""transparent_assets frontmatter round-trip（M-3 / BC-8）。

whitelist serializer (_plan_to_frontmatter) 若漏加 transparent_assets，會在
re-serialize 時靜默丟失整個 block —— 這組測試守住三處同改後的 round-trip。
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import plan_schema as ps  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "bilingual_storyboard_mock.md"

_TA = {
    "defaults": {"bg_remove_strength": 0.5, "alpha_shrink": 1, "padding": 8},
    "items": {
        "gold_coin": {"category": "symbol", "route": "rembg", "asset_type": "opaque", "size": 512},
        "magic_smoke": {"category": "vfx", "route": "layerdiffuse", "asset_type": "semi", "size": 1024,
                        "params": {"alpha_feather": 2}},
    },
}


def test_schema_version_present():
    assert hasattr(ps, "SCHEMA_VERSION")
    # 1.3.0 起含 transparent_assets
    assert ps.SCHEMA_VERSION >= "1.3.0"


def test_bc8_transparent_assets_roundtrip(tmp_path):
    plan = ps.parse(FIX)
    assert plan.transparent_assets is None  # 原 fixture 無此 block

    plan.transparent_assets = _TA
    out = ps.serialize(plan)
    assert "transparent_assets" in out, "serialize 應輸出 transparent_assets（未被白名單丟失）"

    p2 = tmp_path / "roundtrip.md"
    p2.write_text(out)
    plan2 = ps.parse(p2)
    assert plan2.transparent_assets == _TA  # 完整保留（深度相等）


def test_absent_transparent_assets_not_emitted():
    """None → 不寫入 frontmatter（現役非透明 plan byte-level 不變，BC-7）。"""
    plan = ps.parse(FIX)
    assert plan.transparent_assets is None
    assert "transparent_assets" not in ps.serialize(plan)
