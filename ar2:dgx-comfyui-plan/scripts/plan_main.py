"""CLI entry: ar2:dgx-comfyui-plan.

Subcommands:
  --from-preset {preset_id}              → fork preset → new working plan
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
import plan_promote
import plan_show


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
    g.add_argument("--list", action="store_true",
                   help="List working plans in cwd/plans/")
    g.add_argument("--show", nargs="?", const=_SHOW_LIST_SENTINEL,
                   metavar="PRESET_ID",
                   help="List presets, or cat one preset detail")
    g.add_argument("--promote", metavar="WORKING_ID",
                   help="Promote working plan → preset")
    p.add_argument("--tags", default="",
                   help="Comma-separated tags (with --promote)")
    p.add_argument("--desc", default=None,
                   help="One-line description (with --promote)")
    p.add_argument("--overwrite", action="store_true",
                   help="Overwrite existing preset (with --promote)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.from_preset is not None:
        return plan_from_preset.from_preset(
            _presets_dir(), _plans_dir(), args.from_preset
        )

    if args.list:
        return plan_show.list_plans(_plans_dir())

    if args.show is not None:
        preset_id = None if args.show == _SHOW_LIST_SENTINEL else args.show
        return plan_show.show_presets(_presets_dir(), preset_id)

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
