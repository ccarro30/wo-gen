"""Hairstyle library: VroidStudio hairstyles as swappable modules.

A hairstyle is stored like a garment (``assets/garments/<name>.blend``, slot ``hair``): one
mesh made of the export's ``Hair###`` objects plus the ``HairBack`` layer VroidStudio merges
into ``Body``, with its bones, spring chains and colliders carried as a garment rig (bones
renamed ``<name>.J_Sec_Hair...`` so styles never clash). Equipping one through
``outfit.equip`` first removes the base model's own hair (``strip_base``), then fits the
style to the generated body; ``generate.set_palette`` recolors it like any hair.

Exports named ``<reference>_hair*.vrm`` (same body, other hairstyle) are hair sources; the
reference export's own hair is harvested too, so every style can be swapped back.

Chat usage::

    from wogen.bl import hair
    hair.list_styles()
    hair.equip("hair_long_straight")
"""

from __future__ import annotations

import bmesh
import bpy

from ..garments import strip_suffix

SLOT = "hair"
HAIR_BONE_PREFIX = "J_Sec_Hair"
HAIRBACK = "HairBack"
STRIPPED_KEY = "wg_base_hair_removed"


def _source_name(mat) -> str:
    from . import toon
    src = toon._source_of(mat) if mat else None
    return strip_suffix(src.name) if src else ""


def _is_hair_material(mat) -> bool:
    name = _source_name(mat)
    return name.endswith("_HAIR") or "_HAIR_" in name


def base_hair_objects() -> list[bpy.types.Object]:
    """The base model's hair meshes (not garments, every material a ``_HAIR`` one)."""
    from .character import character_meshes
    return [o for o in character_meshes()
            if not o.get("wg_garment") and o.name not in ("Body", "Face") and o.data.materials
            and all(_is_hair_material(m) for m in o.data.materials)]


def _hairback_indices(body: bpy.types.Object) -> set[int]:
    return {i for i, m in enumerate(body.data.materials) if HAIRBACK in _source_name(m)}


def _delete_faces(obj: bpy.types.Object, material_indices: set[int]) -> int:
    from .outfit import _compact_slots
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    doomed = [f for f in bm.faces if f.material_index in material_indices]
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    _compact_slots(obj)
    return len(doomed)


def strip_base() -> str:
    """Remove the base model's hair: meshes, Body's HairBack faces, hair spring chains and hair
    bones. Idempotent. Needed before equipping a hairstyle module."""
    from .character import character_armature
    from .outfit import body_mesh
    arm = character_armature()
    if arm.get(STRIPPED_KEY):
        return "base hair already removed"
    meshes = base_hair_objects()
    for obj in meshes:
        bpy.data.objects.remove(obj, do_unlink=True)
    body = body_mesh()
    faces = _delete_faces(body, _hairback_indices(body)) if _hairback_indices(body) else 0
    sb = arm.data.vrm_addon_extension.spring_bone1
    removed = 0
    for i in range(len(sb.springs) - 1, -1, -1):
        names = [j.node.bone_name for j in sb.springs[i].joints]
        if names and all(n.startswith(HAIR_BONE_PREFIX) for n in names):
            sb.springs.remove(i)
            removed += 1
    bones = _delete_bones(arm, [b.name for b in arm.data.bones
                                if b.name.startswith(HAIR_BONE_PREFIX)])
    arm[STRIPPED_KEY] = True
    return (f"base hair removed: {len(meshes)} meshes, {faces} HairBack faces, "
            f"{removed} spring chains, {bones} bones")


def _delete_bones(arm: bpy.types.Object, names: list[str]) -> int:
    if not names:
        return 0
    view_layer = bpy.context.view_layer
    prev_active, prev_mode = view_layer.objects.active, arm.mode
    view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit = arm.data.edit_bones
        for n in names:
            if n in edit:
                edit.remove(edit[n])
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        if prev_mode == "POSE":
            bpy.ops.object.mode_set(mode="POSE")
        view_layer.objects.active = prev_active
    return len(names)


def build_module(name: str) -> bpy.types.Object:
    """Join the current character's hair (meshes + Body's HairBack faces) into one garment
    object ``Garment_<name>`` (slot ``hair``). The base hair objects are consumed."""
    from . import toon
    from .outfit import GARMENT_PREFIX, _extract, body_mesh, prune_transparent
    pieces = base_hair_objects()
    if not pieces:
        raise RuntimeError("No hair meshes on the character")
    body = body_mesh()
    back = _hairback_indices(body)
    toon.remove_toon(pieces + [body])           # join on the MToon source materials
    if back:
        shell = _extract(body, back, "wg_hairback_tmp")
        if shell.data.shape_keys:
            shell.shape_key_clear()
        for md in list(shell.modifiers):
            if md.type != "ARMATURE":
                shell.modifiers.remove(md)
        for vg in [vg for vg in shell.vertex_groups if vg.name.startswith("wg_")]:
            shell.vertex_groups.remove(vg)
        prune_transparent(shell)
        pieces.append(shell)
        _delete_faces(body, back)
    target = pieces[0]
    with bpy.context.temp_override(active_object=target, object=target,
                                   selected_objects=pieces, selected_editable_objects=pieces):
        bpy.ops.object.join()
    target.name = target.data.name = GARMENT_PREFIX + name
    target["wg_garment"], target["wg_item"], target["wg_slot"] = name, SLOT, SLOT
    toon.apply_toon([target, body])
    return target


def harvest(names: list[str] | None = None, reference: str = "base_f01",
            fresh: bool = False) -> list[str]:
    """Save the hairstyle of each export (default: ``<reference>`` and ``<reference>_hair*``)
    to the library as ``hair_<n>``; duplicates of library styles are skipped.

    Rename to descriptive names with ``outfit.rename({"hair_3": "hair_twin_tails"})``.
    """
    import contextlib
    import io

    from . import garment_rig, toon
    from .character import BASE_DIR, character_armature, import_base
    from .outfit import _read_index, _write_index, garment_signature, rename, save_garment
    names = names or [reference] + sorted(p.stem for p in BASE_DIR.glob(f"{reference}_hair*.vrm"))
    index = _read_index()
    sigs, slots = index["signatures"], index["slots"]
    if fresh:
        for k in [k for k in sigs if slots.get(k) == SLOT]:
            del sigs[k]
    log = []
    for name in names:
        with contextlib.redirect_stdout(io.StringIO()):
            import_base(name)
            toon.apply_toon()
        arm = character_armature()
        suffix = name.removeprefix(reference).lstrip("_").removeprefix("hair") or "1"
        hid = f"hair_{suffix}"
        g = build_module(hid)
        sig = garment_signature(g)
        match = next((k for k, v in sigs.items() if v == sig), None)
        if match:
            log.append(f"{name}: hair = existing {match}")
            continue
        reference_bones = {b.name for b in arm.data.bones if not b.name.startswith(HAIR_BONE_PREFIX)}
        rig = garment_rig.extract(g, arm, reference_bones, 0.0, hid)
        garment_rig.store(g, rig)
        save_garment(hid)
        sigs[hid] = sig
        slots[hid] = SLOT
        log.append(f"{name}: saved {hid} ({len(g.data.polygons)} faces, "
                   f"{len(rig.get('bones', []))} bones, {len(rig.get('springs', []))} chains)")
    _write_index(index)
    log += [f"renamed {line}" for line in rename()]
    return log


def list_styles() -> list[str]:
    from .outfit import _read_index, list_library
    slots = _read_index()["slots"]
    return [n for n in list_library() if slots.get(n) == SLOT]


def equip(name: str) -> str:
    """Wear a library hairstyle (replaces the base hair and any other style)."""
    from . import outfit
    if name not in list_styles():
        raise KeyError(f"No hairstyle {name!r}. Have: {list_styles()}")
    return outfit.equip(name)
