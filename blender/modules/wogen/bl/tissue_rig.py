"""Helper bones for soft tissue that VroidStudio gives no bones: butt, thighs and belly.

``ensure()`` adds one helper bone per region, side and source bone (``softtissue.REGIONS``)
and moves a share of the source bone's skin weights onto it, on the body and on every
garment. A helper takes weight only from its own parent, so nothing changes until
``wogen.bl.physics`` shifts the helper with the soft-tissue solver. Garments are weighted by
the same rule as the skin under them, so they move together.

The falloff is evaluated in the base model's rest space (the body transforms of
``wogen.bl.body`` are undone first), so regions keep covering the same skin at any
proportions.
"""

from __future__ import annotations

import json

import bpy
from mathutils import Matrix, Vector

from .. import softtissue

RIG_KEY = "wg_tissue"            # on the armature: the helpers; on a mesh: weights are split
PREFIX = "wg_tissue."
BONE_LENGTH = 0.03


def helpers(arm: bpy.types.Object) -> list[dict]:
    """Installed helpers: {"bone", "region", "side", "source"} (empty before ``ensure``)."""
    raw = arm.get(RIG_KEY)
    return [h for h in json.loads(raw) if h["bone"] in arm.data.bones] if raw else []


def _plan(arm: bpy.types.Object) -> list[dict]:
    """Helpers this armature should have, with their centre in the current rest space."""
    from .body import stored_transforms
    from .pose import humanoid_map
    hmap = humanoid_map(arm)
    transforms = stored_transforms(arm)
    out = []
    for region in softtissue.REGIONS:
        for side in softtissue.sides(region):
            anchor = hmap.get(region.anchor.format(side=side))
            if anchor is None:
                continue
            fit = transforms.get(anchor, Matrix.Identity(4))       # base rest -> current rest
            base_head = fit.inverted() @ arm.data.bones[anchor].head_local
            mirror = -1.0 if side == "right" else 1.0
            c = region.center
            head = fit @ (base_head + Vector((c[0] * mirror, c[1], c[2])))
            for source in region.sources:
                bone = hmap.get(source.format(side=side))
                if bone is None:
                    continue
                tag = {"left": "L", "right": "R", "": "C"}[side]
                out.append({"bone": f"{PREFIX}{region.name}.{tag}.{bone}", "region": region.name,
                            "side": side, "source": bone, "head": list(head),
                            "unfit": [list(r) for r in fit.inverted()],
                            "origin": list(base_head)})
    return out


def _add_bones(arm: bpy.types.Object, plan: list[dict]) -> int:
    missing = [h for h in plan if h["bone"] not in arm.data.bones]
    if not missing:
        return 0
    view_layer = bpy.context.view_layer
    prev_active, prev_mode = view_layer.objects.active, arm.mode
    view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit = arm.data.edit_bones
        for h in missing:
            eb = edit.new(h["bone"])
            eb.head = Vector(h["head"])
            eb.tail = eb.head + Vector((0.0, 0.0, BONE_LENGTH))
            eb.roll = 0.0
            eb.use_deform = True
            eb.parent = edit[h["source"]]
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        if prev_mode == "POSE":
            bpy.ops.object.mode_set(mode="POSE")
        view_layer.objects.active = prev_active
    return len(missing)


def _split_weights(obj: bpy.types.Object, arm: bpy.types.Object, plan: list[dict]) -> int:
    """Move each helper's share of its source group's weights onto the helper's group."""
    regions = {r.name: r for r in softtissue.REGIONS}
    by_source: dict[str, list[tuple]] = {}
    to_arm = arm.matrix_world.inverted() @ obj.matrix_world
    for h in plan:
        if obj.vertex_groups.get(h["source"]) is None:
            continue
        group = obj.vertex_groups.get(h["bone"]) or obj.vertex_groups.new(name=h["bone"])
        by_source.setdefault(h["source"], []).append(
            (group, Matrix(h["unfit"]) @ to_arm, Vector(h["origin"]), regions[h["region"]],
             h["side"]))
    if not by_source:
        return 0
    source_of = {obj.vertex_groups[name].index: obj.vertex_groups[name] for name in by_source}
    moved = 0
    for v in obj.data.vertices:
        for index, weight in [(g.group, g.weight) for g in v.groups]:
            source = source_of.get(index)
            if source is None or weight <= 0.0:
                continue
            parts = []
            for group, to_base, origin, region, side in by_source[source.name]:
                f = softtissue.falloff(tuple(to_base @ v.co - origin), region, side)
                if f > 1e-4:
                    parts.append((group, f))
            if not parts:
                continue
            total = sum(f for _, f in parts)
            scale = min(1.0, softtissue.SHARE_CAP / total)
            for group, f in parts:
                group.add([v.index], weight * f * scale, "REPLACE")
            source.add([v.index], weight * (1.0 - total * scale), "REPLACE")
            moved += 1
    return moved


def ensure(arm: bpy.types.Object | None = None) -> str:
    """Add the helper bones and split the weights of every character mesh that hasn't been
    done yet (idempotent; call again after equipping garments)."""
    from .character import character_armature, character_meshes
    arm = arm or character_armature()
    plan = _plan(arm)
    added = _add_bones(arm, plan)
    arm[RIG_KEY] = json.dumps([{k: h[k] for k in ("bone", "region", "side", "source")}
                               for h in plan])
    meshes = verts = 0
    for obj in character_meshes():
        if obj.get(RIG_KEY):
            continue
        n = _split_weights(obj, arm, plan)
        obj[RIG_KEY] = 1
        if n:
            meshes, verts = meshes + 1, verts + n
    return f"tissue rig: {added} bones added, {verts} vertices on {meshes} meshes weighted"
