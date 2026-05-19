"""Inject CLI parameters into a ComfyUI workflow dict by class_type convention.

Supports both Flux (RandomNoise / SamplerCustomAdvanced / EmptySD3LatentImage /
BasicScheduler) and legacy SD (KSampler / KSamplerAdvanced / EmptyLatentImage /
EmptyLatentImageFlux) patterns.

See references/workflow-schema.md for the full mapping table.
"""

from __future__ import annotations

import copy


class WorkflowParamError(ValueError):
    """No node matched the requested injection."""


# class_type → (input_field, group_priority)
# Lower priority = preferred when multiple groups exist (e.g. Flux RandomNoise wins
# over legacy KSampler if both are in the workflow, but typically only one is).
_SEED_TARGETS = [
    ("RandomNoise", "noise_seed", 0),
    ("KSampler", "seed", 1),
    ("KSamplerAdvanced", "noise_seed", 1),
]

_STEPS_TARGETS = [
    ("BasicScheduler", "steps", 0),
    ("KSampler", "steps", 1),
    ("KSamplerAdvanced", "steps", 1),
]

_BATCH_TARGETS = [
    ("EmptySD3LatentImage", "batch_size", 0),
    ("EmptyLatentImageFlux", "batch_size", 0),
    ("EmptyLatentImage", "batch_size", 1),
]


def _iter_nodes(workflow: dict):
    """Yield (node_id, node_dict) pairs, skipping non-dict entries (e.g. _comment)."""
    for nid, node in workflow.items():
        if isinstance(node, dict) and "class_type" in node:
            yield nid, node


def _find_nodes_by_class(workflow: dict, class_type: str) -> list[tuple[str, dict]]:
    """Find all nodes of a given class_type, sorted by node id (numeric if possible)."""
    matches = [(nid, n) for nid, n in _iter_nodes(workflow) if n["class_type"] == class_type]

    def sort_key(item):
        nid = item[0]
        try:
            return (0, int(nid))
        except ValueError:
            return (1, nid)

    matches.sort(key=sort_key)
    return matches


def _find_first_by_targets(
    workflow: dict, targets: list[tuple[str, str, int]]
) -> tuple[dict, str] | None:
    """Among possible (class_type, field, priority) targets, return (node, field) of
    the first matching node, preferring lower priority class types.
    """
    # Group by priority, take lowest-priority group that has any matches
    by_priority: dict[int, list[tuple[dict, str]]] = {}
    for class_type, field, priority in targets:
        for _nid, node in _find_nodes_by_class(workflow, class_type):
            by_priority.setdefault(priority, []).append((node, field))
    if not by_priority:
        return None
    best = min(by_priority)
    return by_priority[best][0]


def inject(
    workflow: dict,
    *,
    prompt: str | None = None,
    negative_prompt: str | None = None,
    seed: int | None = None,
    steps: int | None = None,
    batch_size: int | None = None,
    width: int | None = None,
    height: int | None = None,
    face_ref_filename: str | None = None,
    pulid_weight: float | None = None,
    output_subdir: str | None = None,
    filename_prefix_override: str | None = None,
    deep_copy: bool = True,
) -> dict:
    """Return a workflow dict with the given parameters injected.

    By default deep-copies the input so the original (e.g. bundled workflow
    template) is not modified. Pass deep_copy=False if caller already copied.
    """
    wf = copy.deepcopy(workflow) if deep_copy else workflow

    # --- seed ---
    if seed is not None:
        match = _find_first_by_targets(wf, _SEED_TARGETS)
        if match is None:
            raise WorkflowParamError(
                "no seed-bearing node found "
                "(expected one of: RandomNoise, KSampler, KSamplerAdvanced)"
            )
        node, field = match
        node["inputs"][field] = int(seed)

    # --- steps ---
    if steps is not None:
        match = _find_first_by_targets(wf, _STEPS_TARGETS)
        if match is None:
            raise WorkflowParamError(
                "no steps-bearing node found "
                "(expected one of: BasicScheduler, KSampler, KSamplerAdvanced)"
            )
        node, field = match
        node["inputs"][field] = int(steps)

    # --- batch_size ---
    if batch_size is not None:
        match = _find_first_by_targets(wf, _BATCH_TARGETS)
        if match is None:
            raise WorkflowParamError(
                "no batch_size-bearing node found "
                "(expected one of: EmptySD3LatentImage, EmptyLatentImageFlux, EmptyLatentImage)"
            )
        node, field = match
        node["inputs"][field] = int(batch_size)

    # --- width / height ---
    if width is not None or height is not None:
        # Same nodes as batch_size — width/height live on the latent image.
        targets = [(ct, "width", pr) for ct, _f, pr in _BATCH_TARGETS]
        match = _find_first_by_targets(wf, targets)
        if match is None:
            raise WorkflowParamError(
                "no width/height-bearing node found "
                "(expected one of: EmptySD3LatentImage, EmptyLatentImageFlux, EmptyLatentImage)"
            )
        node, _field = match
        if width is not None:
            node["inputs"]["width"] = int(width)
        if height is not None:
            node["inputs"]["height"] = int(height)

    # --- prompt / negative_prompt ---
    if prompt is not None or negative_prompt is not None:
        encoders = _find_nodes_by_class(wf, "CLIPTextEncode")
        if not encoders:
            raise WorkflowParamError("no CLIPTextEncode node found")
        if prompt is not None:
            encoders[0][1]["inputs"]["text"] = prompt
        if negative_prompt is not None:
            if len(encoders) < 2:
                raise WorkflowParamError(
                    "no second CLIPTextEncode for negative_prompt"
                )
            encoders[1][1]["inputs"]["text"] = negative_prompt

    # --- pulid_weight / ApplyPulidFlux ---
    if pulid_weight is not None:
        pulid_nodes = _find_nodes_by_class(wf, "ApplyPulidFlux")
        if not pulid_nodes:
            raise WorkflowParamError(
                "pulid_weight given but no ApplyPulidFlux node in workflow"
            )
        for _nid, node in pulid_nodes:
            node["inputs"]["weight"] = float(pulid_weight)

    # --- face_ref / LoadImage ---
    if face_ref_filename is not None:
        load_nodes = _find_nodes_by_class(wf, "LoadImage")
        if not load_nodes:
            raise WorkflowParamError(
                "face_ref_filename given but no LoadImage node in workflow"
            )
        # Apply to ALL LoadImage nodes (v1 limitation: cannot target specific node)
        image_path = (
            f"{output_subdir}/{face_ref_filename}" if output_subdir else face_ref_filename
        )
        for _nid, node in load_nodes:
            node["inputs"]["image"] = image_path

    # --- output_subdir + filename_prefix_override → SaveImage filename_prefix ---
    if output_subdir is not None or filename_prefix_override is not None:
        save_nodes = _find_nodes_by_class(wf, "SaveImage")
        if not save_nodes:
            raise WorkflowParamError("no SaveImage node found")
        if filename_prefix_override is not None:
            # Caller-provided full prefix (plan_runner uses
            # `{output_subdir}/{ch{N}/{NN}_{name}}` for chapter-encoded slugs)
            prefix = (
                f"{output_subdir}/{filename_prefix_override}"
                if output_subdir else filename_prefix_override
            )
        else:
            prefix = f"{output_subdir}/img"
        for _nid, node in save_nodes:
            node["inputs"]["filename_prefix"] = prefix

    return wf
