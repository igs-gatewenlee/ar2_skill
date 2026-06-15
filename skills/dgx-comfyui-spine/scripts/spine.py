#!/usr/bin/env python3
"""ar2:dgx-comfyui-spine 單發半自動「部件包」CLI（P1 設計規格 §1.2）。

流程（半自動，人標粗框 hint 在環內）：
  Flux star-pose 白底 reference 生成（或 --reference 吃既有圖）
  → 每部件吃 hint PNG → SAM 精修切件 → compose_rgba(straight)+edge_bleed+fix_alpha
  → content_bbox(padding=0) 裁出帶 alpha part PNG → manifest.json → 8 閘 spine_qc → qc_report.json

v1 部件範圍（B-2 + R-1 否證後）：head/torso/upper_arm_l/upper_arm_r（無 legs，legs v2）。

⚠️ DGX 通訊 sibling-import gen 的 ssh_client+comfyui_api（PoC 已證），config 走 gen/config 單一
   來源（CC-3）；後處理 sibling-import transparent_postprocess（不 fork，CC-2）。**不放 ai_cards**。

用法：
  python3 spine.py --character-id babychar \
      --hint-dir <dir with head.png/torso.png/upper_arm_l.png/upper_arm_r.png> \
      [--reference ref.png | --prompt "..."] [--size 1024] [--seed 20260615]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

from PIL import Image

_SKILL_DIR = Path(__file__).resolve().parent.parent          # skills/dgx-comfyui-spine
_SKILLS = _SKILL_DIR.parent                                   # skills/
sys.path.insert(0, str(Path(__file__).resolve().parent))     # local: spine_sam/manifest_builder/spine_qc
sys.path.insert(0, str(_SKILLS / "dgx-comfyui-transparent" / "scripts"))  # transparent_postprocess
sys.path.insert(0, str(_SKILLS / "dgx-comfyui-gen" / "scripts"))          # ssh_client/comfyui_api

import comfyui_api  # noqa: E402
import ssh_client  # noqa: E402
import transparent_postprocess as pp  # noqa: E402
from config import COMFYUI_ROOT, INPUT_DIR  # noqa: E402  (gen/config 單一來源，CC-3)

import manifest_builder as mb  # noqa: E402
import spine_qc  # noqa: E402
import spine_qc_thresholds as T  # noqa: E402
import spine_sam  # noqa: E402

_FLUX_WF = _SKILL_DIR / "workflows" / "flux_starpose.json"


def _output_root() -> Path:
    """anchor outputs to CC project root（家族慣例，照抄 transparent._output_root）。"""
    for env in ("AR2_OUTPUT_ROOT", "CLAUDE_PROJECT_DIR"):
        v = os.environ.get(env)
        if v:
            return Path(v).expanduser()
    return Path.cwd()


def _gen_reference(out_ref: Path, prompt: str | None, seed: int, size: int) -> None:
    """跑 flux_starpose 產白底 star-pose reference → 下載到 out_ref。"""
    wf = json.loads(_FLUX_WF.read_text())
    wf = {k: v for k, v in wf.items() if isinstance(v, dict)}  # strip _comment（BC-6）
    if prompt:
        wf["3"]["inputs"]["text"] = prompt
    wf["6"]["inputs"]["noise_seed"] = seed
    wf["4"]["inputs"]["width"] = wf["4"]["inputs"]["height"] = size
    wf["13"]["inputs"]["filename_prefix"] = "spine_reference"
    pid, _, _ = comfyui_api.submit_prompt(wf, uuid.uuid4().hex)
    print(f"🔵 生成 reference (Flux {size}px, seed={seed}) prompt_id={pid} ...")
    outs = comfyui_api.wait_for_completion(pid, poll_interval=5.0, timeout=1800.0)
    files = comfyui_api.list_output_files(outs)
    if not files:
        raise SystemExit("❌ reference 生成無輸出")
    fn, sub = files[0]
    remote = f"{COMFYUI_ROOT}/output/{sub + '/' if sub else ''}{fn}"
    ssh_client.scp_get(remote, out_ref)
    print(f"   reference → {out_ref}")


def _cut_part(name: str, reference: Image.Image, hint_local: Path,
              char_remote_name: str, run_tag: str) -> tuple[Image.Image, tuple]:
    """跑 SAM 精修 → 下載 mask → compose/edge_bleed/fix_alpha → content_bbox 裁件。

    回 (part_rgba, bbox)。bbox = (x,y,w,h) 全圖座標，part_rgba.size==(w,h)（BC-1 同 bbox 保證）。
    """
    hint_remote = f"spine_hint_{run_tag}_{name}.png"
    ssh_client.scp_put(hint_local, f"{INPUT_DIR}/{hint_remote}")
    wf = spine_sam.build_sam_workflow(char_remote_name, hint_remote, f"spine_mask_{run_tag}_{name}")
    pid, _, _ = comfyui_api.submit_prompt(wf, uuid.uuid4().hex)
    outs = comfyui_api.wait_for_completion(pid, poll_interval=3.0, timeout=600.0)
    fn, sub = comfyui_api.list_output_files(outs)[0]
    remote = f"{COMFYUI_ROOT}/output/{sub + '/' if sub else ''}{fn}"
    mask_tmp = Path(f"/tmp/spine_mask_{run_tag}_{name}.png")
    ssh_client.scp_get(remote, mask_tmp)

    mask = Image.open(mask_tmp)
    rgba = pp.compose_rgba(reference, mask)       # straight：alpha=mask、RGB=reference
    rgba = pp.edge_bleed(rgba)                    # 填 alpha=0 RGB，避免裁切邊白暈
    rgba, _ = pp.fix_alpha(rgba, "opaque", shrink=1, blur=0.5)
    bbox = mb.content_bbox(rgba)                  # padding=0（BC-1）
    if bbox is None:
        raise SystemExit(f"❌ part {name} SAM mask 全透明（hint 沒命中？）")
    return mb.crop_part(rgba, bbox), bbox


def run(args) -> int:
    out_root = _output_root() / "outputs" / "ar2-dgx-comfyui-spine"
    run_tag = args.character_id or time.strftime("%H%M%S")
    folder = out_root / f"{time.strftime('%Y-%m-%d')}_{run_tag}"
    parts_dir = folder / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    ssh_client.ensure_tunnel()

    ref_path = folder / "reference.png"
    if args.reference:
        Image.open(args.reference).convert("RGB").save(ref_path)
        print(f"🔵 用既有 reference → {ref_path}")
    else:
        _gen_reference(ref_path, args.prompt, args.seed, args.size)

    reference = Image.open(ref_path).convert("RGB")
    char_remote = f"spine_ref_{run_tag}.png"
    ssh_client.scp_put(ref_path, f"{INPUT_DIR}/{char_remote}")

    hint_dir = Path(args.hint_dir)
    parts: dict = {}
    for name in T.EXPECTED_PARTS:
        hint = hint_dir / f"{name}.png"
        if not hint.exists():
            print(f"⚠️ 缺 hint {hint}（part {name} 跳過，QC 閘1 會標 missing）")
            continue
        print(f"🔵 切件 {name} ...")
        part_rgba, bbox = _cut_part(name, reference, hint, char_remote, run_tag)
        part_rgba.save(parts_dir / f"{name}.png")
        parts[name] = {"bbox": bbox, "draw_order": T.DEFAULT_DRAW_ORDER.get(name, 1)}

    manifest = mb.build_manifest("reference.png", reference.size, parts)
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    report = spine_qc.run_spine_qc(parts_dir, manifest, ref_path)
    (folder / "qc_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\n{'✅' if report['result'] == 'pass' else '⚠️' if report['result'] == 'warning' else '❌'} "
          f"spine 部件包完成 → {folder}")
    print(f"   parts: {sorted(parts)}  | QC result = {report['result']}  coverage={report.get('coverage')}")
    for g, v in report["gates"].items():
        mark = {"pass": "✅", "warning": "⚠️", "fail": "❌"}[v["status"]]
        print(f"   {mark} {g}: {v['detail']}")
    if report["fails"]:
        print(f"   ❌ fails: {report['fails']}")
    return 0 if report["result"] != "fail" else 2


def main():
    ap = argparse.ArgumentParser(description="ar2:dgx-comfyui-spine 半自動部件包 CLI")
    ap.add_argument("--character-id", default=None, help="輸出夾命名 + 遠端檔名 tag")
    ap.add_argument("--hint-dir", required=True, help="每部件一個 <slug>.png 粗框 hint 的目錄")
    ap.add_argument("--reference", default=None, help="既有 reference 圖（給了就不生成）")
    ap.add_argument("--prompt", default=None, help="覆寫 flux_starpose 內建白底 star-pose prompt")
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=20260615)
    return run(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
