"""ar2 家族跨 skill 守恆測試（registry ↔ workflow/preset/腳本 不漂移）。

可 `python3 test_conservation.py` 跑，也可 pytest discover。
補 test_registry.py（registry 內部）之外的「跨產物」鎖：
- CT-5  workflow JSON 模型 == registry.WORKFLOW_MODELS（JSON↔registry 不漂）
- CT-6  train preset name_or_path == registry.FLUX_BASE_PATH（修 4 site 漂移）
- CT-7  anti-fork：DGX IP 不得出現在非註解執行碼
- CT-11 required_nodes 覆蓋 workflow 用到的自訂節點（node 缺→炸 維度）
- LINT  DGX 端腳本/模板的 literal（runtime 不可讀 registry）== registry（靜態綁定）
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SHARED = _HERE.parent.parent
_SKILLS = _SHARED.parent
sys.path.insert(0, str(_SHARED))

import ar2_registry as reg  # noqa: E402

_MODEL_EXT = (".safetensors", ".pth", ".pt", ".onnx", ".ckpt")


def _wf_key(wf: Path) -> str:
    skill = wf.parent.parent.name.replace("dgx-comfyui-", "")
    return f"{skill}/{wf.stem}"


def _wf_models(d: dict) -> list[str]:
    out: set[str] = set()
    for v in d.values():
        if not isinstance(v, dict):
            continue
        for val in (v.get("inputs") or {}).values():
            if isinstance(val, str) and val.lower().endswith(_MODEL_EXT):
                out.add(val)
    return sorted(out)


def _wf_class_types(d: dict) -> set[str]:
    return {v["class_type"] for v in d.values()
            if isinstance(v, dict) and "class_type" in v}


def test_ct5_workflow_models_match_registry():
    """CT-5：每個 workflow JSON 的模型檔 == registry.WORKFLOW_MODELS[key]。"""
    wfs = list(_SKILLS.glob("dgx-comfyui-*/workflows/*.json"))
    assert wfs, "找不到任何 workflow JSON"
    for wf in wfs:
        key = _wf_key(wf)
        models = _wf_models(json.loads(wf.read_text(encoding="utf-8")))
        assert key in reg.WORKFLOW_MODELS, f"registry.workflow_models 缺 {key}"
        assert sorted(reg.WORKFLOW_MODELS[key]) == models, (
            f"{key} JSON↔registry 模型漂移：JSON={models} "
            f"registry={sorted(reg.WORKFLOW_MODELS[key])}"
        )


def test_ct6_train_presets_flux_base():
    """CT-6：3 train preset 的 model.name_or_path == registry.FLUX_BASE_PATH。"""
    presets = list((_SKILLS / "dgx-comfyui-train" / "presets").glob("*.yaml"))
    assert presets, "找不到 train presets"
    for p in presets:
        m = re.search(r'name_or_path:\s*["\']?([^"\'\n]+)["\']?', p.read_text(encoding="utf-8"))
        assert m, f"{p.name} 無 name_or_path"
        assert m.group(1).strip() == reg.FLUX_BASE_PATH, (
            f"{p.name} name_or_path={m.group(1).strip()} != registry {reg.FLUX_BASE_PATH}"
        )


def test_ct7_no_ip_literal_in_code():
    """CT-7 anti-fork：DGX IP 不得出現在非註解的執行碼（防再硬編連線值）。"""
    ip = reg.HOST
    offenders: list[str] = []
    for py in _SKILLS.glob("dgx-comfyui-*/scripts/*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if ip in line and not line.lstrip().startswith("#"):
                offenders.append(f"{py.relative_to(_SKILLS)}:{i}")
    assert not offenders, f"IP 字面出現在非註解程式碼（應改讀 registry）：{offenders}"


def test_ct11_required_nodes_cover_workflow_custom_nodes():
    """CT-11：active required_node 的 provides 確實出現在其 required_by workflow；
    且關鍵自訂節點都有登記（node 缺→workflow 炸 的獨立失敗維度）。"""
    wf_by_key = {
        _wf_key(wf): _wf_class_types(json.loads(wf.read_text(encoding="utf-8")))
        for wf in _SKILLS.glob("dgx-comfyui-*/workflows/*.json")
    }
    for node, meta in reg.REQUIRED_NODES.items():
        if meta.get("status") != "active":
            continue  # pending route 放行
        provides = set(meta.get("provides", []))
        seen: set[str] = set()
        for key in meta.get("required_by", []):
            seen |= wf_by_key.get(key, set())
        missing = provides - seen
        assert not missing, f"required_node {node} 宣告的 provides {missing} 未出現在 {meta.get('required_by')}"
    # 關鍵自訂節點必須有登記
    provided_all = {c for m in reg.REQUIRED_NODES.values() for c in m.get("provides", [])}
    key_custom = {"SAMLoader", "SAMDetectorCombined", "ApplyPulidFlux", "InspyrenetRembgAdvanced"}
    assert key_custom <= provided_all, f"required_nodes 漏關鍵節點：{key_custom - provided_all}"


# --- LINT：DGX 端執行 / 模板的 literal（runtime 不可讀 registry）靜態綁定 registry ---

def test_lint_start_script_matches_registry():
    s = (_SKILLS / "dgx-comfyui-check" / "scripts" / "start_comfyui_dgx.sh").read_text(encoding="utf-8")
    assert f"PORT={reg.COMFYUI_PORT}" in s, "start script PORT != registry.COMFYUI_PORT"
    assert f"ROOT={reg.COMFYUI_ROOT}" in s, "start script ROOT != registry.COMFYUI_ROOT"
    for flag in reg.COMFYUI_LAUNCH_FLAGS:
        assert flag in s, f"start script 缺 launch flag {flag}"


def test_lint_remote_api_port():
    t = (_SKILLS / "dgx-comfyui-transparent" / "scripts" / "transparent.py").read_text(encoding="utf-8")
    assert f"localhost:{reg.COMFYUI_PORT}" in t, "_REMOTE API port != registry.COMFYUI_PORT"


def test_lint_patch_node_path():
    s = (_SKILLS / "dgx-comfyui-transparent" / "scripts" / "patch_rembg_cpu.sh").read_text(encoding="utf-8")
    assert reg.CUSTOM_NODES_DIR in s, "patch_rembg NODE 路徑 != registry.CUSTOM_NODES_DIR"


def test_lint_plan_output_dir():
    name = reg.output_dir_name_for("gen")  # outputs/ar2-dgx-comfyui-gen
    for f in ("plan_create.py", "plan_manifest_import.py", "plan_promote.py"):
        p = _SKILLS / "dgx-comfyui-plan" / "scripts" / f
        assert name in p.read_text(encoding="utf-8"), f"{f} output_dir != registry"
    tmpl = (_SKILLS / "dgx-comfyui-plan" / "templates" / "default_outline.md").read_text(encoding="utf-8")
    assert name in tmpl, "default_outline.md output dir != registry"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  💥 {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
