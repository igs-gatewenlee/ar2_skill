#!/usr/bin/env python3
"""ar2:dgx-comfyui-transparent 單發 PoC CLI（Route A 去背端到端）。

⚠️ PoC 階段刻意自包含（獨立 SSH submit+poll+scp），**不綁 gen/plan/check 版本同步**
   （P1 設計規格 §3.1 / 嫁接 MVP-first：YAGNI，等 Route A 真交付再談複用）。
   只複用本 skill 的本地後處理模組（transparent_postprocess / qc / asset_spec）。

流程：load route_a_rmbg.json → 注入 prompt/seed/size/steps/threshold + 替換 {run_subdir}
  → scp workflow 到 DGX → submit /prompt → poll /history → 依 subfolder 分類 source/mask
  → scp 兩檔 → 本地 compose_rgba(straight) → fix_alpha → auto_trim → 存 final → run_qc → 印 report。

用法：
  python3 transparent.py --poc --prompt "single gold coin, game icon, transparent background" \
      --slug gold_coin --category symbol --size 512 --steps 12 --asset-type opaque
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asset_spec
import qc as qcmod
import transparent_postprocess as pp
from PIL import Image

_SKILL_DIR = Path(__file__).resolve().parent.parent
_WF = _SKILL_DIR / "workflows" / "route_a_rmbg.json"
_OUT_ROOT = Path.cwd() / "outputs" / "ar2-dgx-comfyui-transparent"

# sibling check/gen config.py, co-located in plugin skills/ (transparent/ → skills/).
# config.py is gitignored but present on disk (intentional shared-DGX creds、不動內容)。
_CONFIG_CANDIDATES = [
    _SKILL_DIR.parent / "dgx-comfyui-check" / "config.py",
    _SKILL_DIR.parent / "dgx-comfyui-gen" / "config.py",
]


def _load_conn():
    for p in _CONFIG_CANDIDATES:
        if p.exists():
            spec = importlib.util.spec_from_file_location("ar2_config", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise SystemExit("找不到 ar2 config.py（連線參數來源）")


def _ssh(cfg, *args, **kw):
    if shutil.which("sshpass") is None:
        raise SystemExit("缺 sshpass：brew install esolitos/ipa/sshpass")
    base = ["sshpass", "-p", cfg.PASSWORD, "ssh", *cfg.SSH_OPTS, "-p", str(cfg.SSH_PORT), f"{cfg.USER}@{cfg.HOST}"]
    return subprocess.run(base + list(args), capture_output=True, text=True, **kw)


def _scp(cfg, src, dst):
    base = ["sshpass", "-p", cfg.PASSWORD, "scp", *cfg.SSH_OPTS, "-P", str(cfg.SSH_PORT)]
    return subprocess.run(base + [src, dst], capture_output=True, text=True)


def _inject(wf: dict, *, prompt, seed, width, height, steps, threshold, run_subdir):
    """依 class_type 注入參數；SaveImage 只替換 {run_subdir}（M-1：inject 不改前綴語意）。"""
    for nid, node in wf.items():
        if nid == "_comment":
            continue
        ct, ins = node["class_type"], node["inputs"]
        if ct == "CLIPTextEncode" and "text" in ins:
            ins["text"] = prompt
        elif ct == "RandomNoise":
            ins["noise_seed"] = seed
        elif ct == "EmptySD3LatentImage":
            ins["width"], ins["height"] = width, height
        elif ct == "BasicScheduler":
            ins["steps"] = steps
        elif ct == "InspyrenetRembgAdvanced":
            ins["threshold"] = threshold
        elif ct == "SaveImage":
            ins["filename_prefix"] = ins["filename_prefix"].replace("{run_subdir}", run_subdir)
    return wf


# 遠端 submit+poll：讀 /tmp 的 workflow、submit、輪詢 /history、回 JSON {prompt_id, outputs[]}
_REMOTE = r'''
import json, sys, time, urllib.request as U
API="http://localhost:8199"
wf=json.load(open("/tmp/ar2_transparent_poc_wf.json"))
r=json.load(U.urlopen(U.Request(API+"/prompt",
    data=json.dumps({"prompt":wf,"client_id":"transparent_poc"}).encode(),
    headers={"Content-Type":"application/json"}),timeout=30))
pid=r["prompt_id"]
hist=None
for i in range(200):  # Flux 產圖 + CPU 去背可能久
    h=json.load(U.urlopen(API+"/history/"+pid,timeout=15))
    if pid in h and h[pid].get("outputs"): hist=h[pid]; break
    st=h.get(pid,{}).get("status",{})
    if st.get("status_str")=="error":
        print(json.dumps({"error":st})); sys.exit(0)
    time.sleep(3)
if not hist: print(json.dumps({"error":"timeout"})); sys.exit(0)
outs=[]
for nid,o in hist["outputs"].items():
    for im in o.get("images",[]):
        outs.append({"subfolder":im.get("subfolder"),"filename":im.get("filename"),"type":im.get("type")})
print(json.dumps({"prompt_id":pid,"outputs":outs}))
'''


def run_poc(args):
    cfg = _load_conn()
    tag = args.tag or time.strftime("%Y%m%d_%H%M%S")
    run_subdir = f"transparent_{tag}"
    wf = json.loads(_WF.read_text())
    # 剝掉 _comment 等非節點 meta key：ComfyUI /prompt 迭代 prompt 期望每個 value 都是
    # 帶 class_type 的節點，混入字串會丟未處理例外 → HTTP 500（gen 的 strip_workflow_metadata 同理）。
    wf = {k: v for k, v in wf.items() if not k.startswith("_")}
    _inject(wf, prompt=args.prompt, seed=args.seed, width=args.size, height=args.size,
            steps=args.steps, threshold=args.threshold, run_subdir=run_subdir)

    # scp workflow → DGX
    tmp = Path("/tmp/ar2_transparent_poc_wf.json")
    tmp.write_text(json.dumps(wf))
    if _scp(cfg, str(tmp), f"{cfg.USER}@{cfg.HOST}:/tmp/ar2_transparent_poc_wf.json").returncode != 0:
        raise SystemExit("scp workflow 失敗")

    print(f"🔵 submit route_a（{args.size}px, {args.steps} steps, CPU 去背）run_subdir={run_subdir} ...")
    r = _ssh(cfg, "python3", "-", input=_REMOTE, timeout=900)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        raise SystemExit(f"遠端回應解析失敗：{r.stdout[-500:]}\n{r.stderr[-300:]}")
    if "error" in res:
        raise SystemExit(f"❌ DGX 執行失敗：{json.dumps(res['error'], ensure_ascii=False)[:400]}")

    # 依 subfolder 前綴契約分類（M-1）
    src = next((o for o in res["outputs"] if (o["subfolder"] or "").endswith("source")), None)
    msk = next((o for o in res["outputs"] if (o["subfolder"] or "").endswith("mask")), None)
    print(f"   outputs: {[(o['subfolder'], o['filename']) for o in res['outputs']]}")
    if not src or not msk:
        raise SystemExit(f"❌ source/mask 前綴契約缺漏（BC-11）：src={src} msk={msk}")

    # scp 兩檔
    folder = asset_spec.asset_folder(_OUT_ROOT, tag, args.category, args.slug)
    folder.mkdir(parents=True, exist_ok=True)
    out_dir = "/root/ComfyUI/output"
    for tagname, o in (("source", src), ("mask", msk)):
        remote = f"{cfg.USER}@{cfg.HOST}:{out_dir}/{o['subfolder']}/{o['filename']}"
        if _scp(cfg, remote, str(folder / f"{tagname}.png")).returncode != 0:
            raise SystemExit(f"scp {tagname} 失敗")
    print(f"   下載 source.png + mask.png → {folder}")

    # 本地：compose straight → alpha-fix → trim → final → QC
    source = Image.open(folder / "source.png")
    mask = Image.open(folder / "mask.png")
    rgba = pp.compose_rgba(source, mask)
    rgba = pp.edge_bleed(rgba)  # §5.2：blur 前填 alpha=0 RGB，避免邊緣黑/白暈
    rgba, warns = pp.fix_alpha(rgba, args.asset_type, shrink=(1 if args.asset_type == "opaque" else 0), blur=1.0)
    rgba = pp.auto_trim(rgba)
    version = asset_spec.next_version(folder, args.category, args.slug, args.size)
    final_name = asset_spec.asset_filename(args.category, args.slug, args.size, version)
    rgba.save(folder / final_name)

    report = qcmod.run_qc(folder / final_name, args.asset_type, route="rembg")
    if warns:
        report.setdefault("warnings", []).extend(warns)
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\n✅ Route A 端到端完成 → {folder / final_name}")
    print(f"   QC result = {report['result']}  | has_alpha={report['has_alpha']} "
          f"fake={report['fake_transparent']} midtone={report['midtone_alpha_ratio']} "
          f"bbox={report['content_bbox_ratio']}")
    if report.get("warnings"):
        print(f"   warnings: {report['warnings']}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="ar2:dgx-comfyui-transparent Route A 單發 PoC")
    ap.add_argument("--poc", action="store_true", help="跑單發 Route A PoC")
    ap.add_argument("--prompt", default="single isolated game asset, centered, clean object silhouette, "
                    "no background, no shadow, transparent background")
    ap.add_argument("--slug", default="poc_asset")
    ap.add_argument("--category", default="symbol")
    ap.add_argument("--asset-type", default="opaque", choices=["opaque", "semi"])
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--steps", type=int, default=12)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    if not args.poc:
        ap.error("v1 只支援 --poc 單發模式")
    return run_poc(args)


if __name__ == "__main__":
    raise SystemExit(main())
