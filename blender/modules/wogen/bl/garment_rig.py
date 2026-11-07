"""Garment rigs: secondary bones (skirts, coat tails, ribbons) and their spring physics,
carried with a garment so it works on any character with the same base skeleton.

At harvest time ``extract()`` records, from the export's armature:
- bones the garment is weighted to that the reference skeleton lacks (+ ancestors and the
  ``_end`` bones of their spring chains), with rest matrices shifted onto the reference;
- the VRM spring chains using those bones (joint parameters) and the sphere colliders those
  chains collide with (VroidStudio adds hip/leg colliders for skirts), as bone-local offsets.
Bones are renamed ``<garment>.<bone>`` (and the garment's vertex groups with them) so two
garments with same-named skirt bones never clash.

At equip time ``install()`` adds the bones to the character armature; ``wogen.bl.physics``
simulates the chains of visible garments together with the character's own springs.
"""

from __future__ import annotations

import json

import bpy
from mathutils import Matrix, Vector

RIG_KEY = "wg_rig"


def _weighted_groups(obj: bpy.types.Object) -> set[str]:
    names = {vg.index: vg.name for vg in obj.vertex_groups}
    used = set()
    for v in obj.data.vertices:
        for g in v.groups:
            if g.weight > 0.0:
                used.add(names[g.group])
    return used


def extract(garment: bpy.types.Object, export_arm: bpy.types.Object, reference_bones: set[str],
            dz: float, prefix: str) -> dict:
    """Build the rig description for ``garment`` (and rename its vertex groups). Empty dict if
    the garment only uses reference bones."""
    bones = export_arm.data.bones
    extra = {n for n in _weighted_groups(garment) if n not in reference_bones and n in bones}
    if not extra:
        return {}
    # Ancestors up to the reference skeleton.
    for name in list(extra):
        b = bones[name].parent
        while b is not None and b.name not in reference_bones:
            extra.add(b.name)
            b = b.parent

    # Spring chains touching those bones (their end bones join the rig too).
    sb = export_arm.data.vrm_addon_extension.spring_bone1
    groups = {g.uuid: g for g in sb.collider_groups}
    colliders = {c.uuid: c for c in sb.colliders}
    springs, collider_specs = [], {}
    for sp in sb.springs:
        joint_names = [j.node.bone_name for j in sp.joints]
        if not any(n in extra for n in joint_names):
            continue
        extra.update(n for n in joint_names if n not in reference_bones)
        col_ids = []
        for ref in sp.collider_groups:
            group = groups.get(ref.collider_group_uuid)
            for cref in (group.colliders if group else []):
                c = colliders.get(cref.collider_uuid)
                if c is None or c.bpy_object is None or c.shape_type != "Sphere":
                    continue
                if c.uuid not in collider_specs:
                    bone = c.node.bone_name
                    rest = export_arm.matrix_world @ bones[bone].matrix_local
                    offset = rest.inverted() @ c.bpy_object.matrix_world.translation
                    collider_specs[c.uuid] = {
                        "bone": bone, "offset": list(offset), "radius": float(c.shape.sphere.radius)}
                col_ids.append(c.uuid)
        springs.append({
            "name": sp.vrm_name,
            "joints": [{"bone": j.node.bone_name, "stiffness": j.stiffness,
                        "drag_force": j.drag_force, "gravity_power": j.gravity_power,
                        "gravity_dir": list(j.gravity_dir), "hit_radius": j.hit_radius}
                       for j in sp.joints],
            "colliders": col_ids,
        })

    def rename(n: str) -> str:
        return f"{prefix}.{n}" if n in extra else n

    shift = Matrix.Translation((0.0, 0.0, -dz))
    ordered = sorted(extra, key=lambda n: len(bones[n].parent_recursive))
    rig_bones = []
    for n in ordered:
        b = bones[n]
        rig_bones.append({
            "name": rename(n),
            "parent": rename(b.parent.name) if b.parent else None,
            "matrix": [list(row) for row in (shift @ b.matrix_local)],
            "length": b.length,
        })
    for sp in springs:
        for j in sp["joints"]:
            j["bone"] = rename(j["bone"])
    cols = {cid: {**spec, "bone": rename(spec["bone"])} for cid, spec in collider_specs.items()}
    for vg in garment.vertex_groups:
        if vg.name in extra:
            vg.name = rename(vg.name)
    return {"bones": rig_bones, "springs": springs, "colliders": cols}


def get(garment: bpy.types.Object) -> dict:
    raw = garment.get(RIG_KEY)
    return json.loads(raw) if raw else {}


def store(garment: bpy.types.Object, rig: dict) -> None:
    if rig:
        garment[RIG_KEY] = json.dumps(rig)
    elif RIG_KEY in garment:
        del garment[RIG_KEY]


def install(arm: bpy.types.Object, rig: dict) -> int:
    """Add the rig's bones to ``arm`` (skips bones that already exist). Returns bones added."""
    missing = [b for b in rig.get("bones", []) if b["name"] not in arm.data.bones]
    if not missing:
        return 0
    view_layer = bpy.context.view_layer
    prev_active, prev_mode = view_layer.objects.active, arm.mode
    view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit = arm.data.edit_bones
        for spec in missing:
            eb = edit.new(spec["name"])
            m = Matrix(spec["matrix"])
            eb.head = m.translation
            eb.tail = m.translation + m.to_3x3() @ Vector((0.0, max(spec["length"], 1e-3), 0.0))
            eb.matrix = m          # restores roll exactly
            eb.use_deform = True
            if spec["parent"] and spec["parent"] in edit:
                eb.parent = edit[spec["parent"]]
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        if prev_mode == "POSE":
            bpy.ops.object.mode_set(mode="POSE")
        view_layer.objects.active = prev_active
    return len(missing)
