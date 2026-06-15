"""SAM 切件 workflow builder（P1 設計規格 §1.3）。

載入 workflows/sam_part.json + 注入 char/hint/prefix（家族慣例：JSON on disk + inject，
仿 transparent 載 route_a_rmbg.json）。**自寫注入，不擴 gen 的 workflow_params.inject**
（CC-4：gen inject class_type 表不含 SAMLoader/MaskToSEGS/SAMDetectorCombined，擴它會讓
gen 批次路徑吃 SAM 語意 → 範圍蔓延、破壞 6 個既有 inject 呼叫點）。
"""
from __future__ import annotations

import json
from pathlib import Path

_WF = Path(__file__).resolve().parent.parent / "workflows" / "sam_part.json"


def build_sam_workflow(char_filename: str, hint_filename: str, prefix: str) -> dict:
    """回可送 /prompt 的 SAM workflow dict（已 strip 非 dict key，BC-6）。"""
    wf = json.loads(_WF.read_text())
    wf = {k: v for k, v in wf.items() if isinstance(v, dict)}  # strip _comment（BC-6）
    wf["1"]["inputs"]["image"] = char_filename
    wf["2"]["inputs"]["image"] = hint_filename
    wf["7"]["inputs"]["filename_prefix"] = prefix
    return wf
