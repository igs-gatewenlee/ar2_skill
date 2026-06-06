"""CLI entry: ar2:dgx-comfyui-plan.

Subcommands:
  --from-preset {preset_id}              → fork preset → new working plan
  --from-manifest {path|-} --title "..." [--id x] [--route-policy p]
                                         → comfyui-reskin-manifest JSON →
                                           genSize 分桶多 outline（換皮批次）
  --list                                 → list working plans
  --show                                 → list presets
  --show {preset_id}                     → cat preset detail
  --promote {working_id} [--tags x,y] [--desc "..."] [--overwrite]
                                         → working → preset

Implements BC-4 / BC-6 / BC-7 / BC-8 / BC-9 dispatch.

NOTE: The (no args) interactive 4-round-input() create flow has been
deprecated (issue #2): 0% real-world exercise — chat-driven sessions
always simulate via AskUserQuestion. Users wanting a new plan should
either --from-preset PRESET_ID (terminal stdin or chat simulate) or
ask Claude to author the outline.md directly from chat. plan_create
itself remains, used by plan_from_preset.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import plan_from_preset
import plan_manifest_import
import plan_promote
import plan_show
import plan_validate


def _plans_dir() -> Path:
    """Working plans live in `cwd/plans/` (cwd-driven, like other ar2 skills)."""
    return Path.cwd() / "plans"


def _presets_dir() -> Path:
    """Presets ship inside the skill: ar2:dgx-comfyui-plan/presets/."""
    return Path(__file__).resolve().parent.parent / "presets"


# Sentinel for `--show` with no preset_id (list mode). Using a sentinel
# (vs None) lets argparse distinguish "--show absent" from "--show present
# with no arg".
_SHOW_LIST_SENTINEL = "__LIST__"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ar2:dgx-comfyui-plan",
        description="Plan-driven batch image generation for ar2:dgx-* family.",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--from-preset", metavar="PRESET_ID",
                   help="Fork preset → new working plan (interactive 改)")
    g.add_argument("--from-manifest", metavar="PATH",
                   help="comfyui-reskin-manifest JSON（或 - 讀 stdin）→ "
                        "genSize 分桶產多份 outline（換皮批次產圖）")
    g.add_argument("--list", action="store_true",
                   help="List working plans in cwd/plans/")
    g.add_argument("--show", nargs="?", const=_SHOW_LIST_SENTINEL,
                   metavar="PRESET_ID",
                   help="List presets, or cat one preset detail")
    g.add_argument("--promote", metavar="WORKING_ID",
                   help="Promote working plan → preset")
    g.add_argument("--validate", metavar="PLAN_ID",
                   help="Lint plan (event density / dispatch / cast warnings, "
                        "non-blocking, BC-G5-4)")
    p.add_argument("--tags", default="",
                   help="Comma-separated tags (with --promote)")
    p.add_argument("--desc", default=None,
                   help="One-line description (with --promote)")
    p.add_argument("--overwrite", action="store_true",
                   help="Overwrite existing preset / outline "
                        "(with --promote / --from-manifest)")
    p.add_argument("--id", default=None, dest="manifest_plan_id",
                   help="Base plan id (with --from-manifest；缺省從 style id 衍生)")
    p.add_argument("--title", default=None,
                   help="Plan title (with --from-manifest，必填)")
    p.add_argument("--route-policy", default="conservative",
                   choices=["conservative", "aggressive"],
                   help="layerdiffuse_native 件的 route 策略 "
                        "(with --from-manifest；預設 conservative=無 alpha 平圖)")
    p.add_argument("--workflow", default="flux_basic",
                   help="route=none 件的 plan 級 workflow (with --from-manifest)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.from_preset is not None:
        return plan_from_preset.from_preset(
            _presets_dir(), _plans_dir(), args.from_preset
        )

    if args.from_manifest is not None:
        if not args.title:
            sys.stderr.write("ERROR: --from-manifest 需要 --title\n")
            return 2
        return plan_manifest_import.from_manifest(
            args.from_manifest,
            _plans_dir(),
            plan_id=args.manifest_plan_id,
            title=args.title,
            route_policy=args.route_policy,
            workflow=args.workflow,
            overwrite=args.overwrite,
        )

    if args.list:
        return plan_show.list_plans(_plans_dir())

    if args.show is not None:
        preset_id = None if args.show == _SHOW_LIST_SENTINEL else args.show
        return plan_show.show_presets(_presets_dir(), preset_id)

    if args.validate is not None:
        return plan_validate.validate(_plans_dir(), args.validate)

    if args.promote is not None:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] or None
        return plan_promote.promote(
            _plans_dir(),
            _presets_dir(),
            args.promote,
            description=args.desc,
            tags=tags,
            overwrite=args.overwrite,
        )

    # No-args interactive create is deprecated (issue #2): use --from-preset
    # for terminal-driven workflows, or have Claude simulate via chat.
    sys.stderr.write(
        "⚠️  Interactive create is deprecated.\n"
        "    Options:\n"
        "      --from-preset PRESET_ID   fork an existing preset\n"
        "      --show                    browse available presets\n"
        "    Or ask Claude to author plans/{id}_outline.md from chat.\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
