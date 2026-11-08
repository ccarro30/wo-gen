"""Outfits: split VroidStudio's merged Body into skin + garments, hide covered skin,
recolor, and save/equip garments from a library.

Chat usage::

    from wogen.bl import outfit
    outfit.split()                                   # Body -> Body (skin) + Garment_* objects
    outfit.list_garments()
    outfit.recolor("onepiece_010_01", hsv=(0.55, 1.0, 1.0))   # hue shift
    outfit.save_garment("onepiece_010_01")           # -> assets/garments/onepiece_010_01.blend
    outfit.unequip("shoes"); outfit.equip("onepiece_010_01")
"""

from __future__ import annotations

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

from ..garments import CONFLICTS, display_name, garment_key, skeleton_mismatch, slot_for  # noqa: F401
from ..paths import ASSETS_DIR

GARMENTS_DIR = ASSETS_DIR / "garments"
GARMENT_PREFIX = "Garment_"
BODY = "Body"
HIDDEN_GROUP = "wg_hidden_by_garments"
MASK_MOD = "wg_hide_covered"


def _character():
    from .character import CHARACTER_COLLECTION, character_armature
    return bpy.data.collections[CHARACTER_COLLECTION], character_armature()


def body_mesh() -> bpy.types.Object:
    coll, _ = _character()
    obj = coll.all_objects.get(BODY)
    if obj is None:
        raise RuntimeError("No Body mesh in the character")
    return obj


def garments() -> list[bpy.types.Object]:
    coll, _ = _character()
    return [o for o in coll.all_objects if o.type == "MESH" and o.get("wg_garment")]


def list_garments() -> list[str]:
    return [f"{o['wg_garment']} ({o['wg_slot']}){'' if o.visible_get() else ' [hidden]'}"
            for o in garments()]


# ---------------------------------------------------------------- split

def _extract(src: bpy.types.Object, keep: set[int], name: str) -> bpy.types.Object:
    """Copy of ``src`` containing only faces whose material index is in ``keep``."""
    obj = src.copy()
    obj.data = src.data.copy()
    obj.name = obj.data.name = name
    for coll in src.users_collection:
        coll.objects.link(obj)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index not in keep],
                     context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    _compact_slots(obj)
    return obj


def _compact_slots(obj: bpy.types.Object) -> None:
    """Drop unused material slots, keeping each face's material."""
    import numpy as np
    me = obj.data
    idx = np.empty(len(me.polygons), dtype=np.int32)
    me.polygons.foreach_get("material_index", idx)
    used = sorted(set(idx.tolist()))
    mats = [me.materials[i] for i in used]
    lookup = np.zeros(max(used, default=0) + 1, dtype=np.int32)
    lookup[used] = np.arange(len(used), dtype=np.int32)
    me.materials.clear()            # note: this resets polygon material indices
    for m in mats:
        me.materials.append(m)
    me.polygons.foreach_set("material_index", lookup[idx])
    me.update()


_alpha_cache: dict[int, object] = {}   # by ID.session_uid; cleared by remove_character()


def _alpha_grid(image):
    import numpy as np
    if image.session_uid not in _alpha_cache:
        w, h = image.size
        px = np.empty(w * h * 4, dtype=np.float32)
        image.pixels.foreach_get(px)
        _alpha_cache[image.session_uid] = px.reshape(h, w, 4)[:, :, 3].copy()
    return _alpha_cache[image.session_uid]


def prune_transparent(obj: bpy.types.Object) -> int:
    """Delete faces whose layer texture is transparent everywhere on them (corners + centre).

    VroidStudio garments are full-body shells whose visible part is cut out by texture alpha;
    pruning turns them into real garment geometry.
    """
    import numpy as np
    from . import toon
    me = obj.data
    uv = me.uv_layers.active
    if uv is None:
        return 0
    layers = []
    for m in me.materials:
        src = toon._source_of(m) if m else None
        image, factor, mode, cutoff = toon._mtoon_inputs(src) if src else (None, None, "OPAQUE", 0)
        if mode == "OPAQUE" or image is None or image.size[0] == 0:
            layers.append(None)
        else:
            layers.append((_alpha_grid(image) * factor[3], max(cutoff, 0.01) if mode == "MASK" else 0.05))
    uvs = np.empty(len(me.loops) * 2, dtype=np.float32)
    uv.data.foreach_get("uv", uvs)
    uvs = uvs.reshape(-1, 2)
    doomed = []
    for poly in me.polygons:
        layer = layers[poly.material_index] if poly.material_index < len(layers) else None
        if layer is None:
            continue
        grid, cut = layer
        h, w = grid.shape
        pts = uvs[poly.loop_start:poly.loop_start + poly.loop_total]
        samples = np.vstack([pts, pts.mean(axis=0, keepdims=True)])
        xs = (samples[:, 0] % 1.0 * w).astype(int).clip(0, w - 1)
        ys = (samples[:, 1] % 1.0 * h).astype(int).clip(0, h - 1)
        if grid[ys, xs].max() <= cut:
            doomed.append(poly.index)
    if doomed:
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.faces[i] for i in doomed], context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
        bm.to_mesh(me)
        bm.free()
        _compact_slots(obj)
    return len(doomed)


def split(apply_names: bool = True) -> str:
    """Separate garments out of ``Body`` (idempotent: does nothing if already split).

    ``apply_names`` maps VroidStudio ids to the library's descriptive names/slots (correct for
    the reference export; harvesting passes False and renames files afterwards)."""
    from . import toon
    body = body_mesh()
    if garments():
        return "already split: " + ", ".join(list_garments())
    toon.remove_toon([body])                      # split on the original MToon materials
    groups: dict[str, set[int]] = {}
    for i, mat in enumerate(body.data.materials):
        key = garment_key(mat.name) if mat else None
        if key:
            groups.setdefault(key, set()).add(i)
    skin = set(range(len(body.data.materials))) - set().union(*groups.values()) if groups \
        else set(range(len(body.data.materials)))
    made = []
    index = _read_index() if apply_names else {"renames": {}, "slots": {}}
    for item, indices in groups.items():
        name = display_name(item)
        name = index["renames"].get(name, name)       # descriptive library name, if any
        g = _extract(body, indices, GARMENT_PREFIX + name)
        g["wg_garment"], g["wg_item"] = name, item
        g["wg_slot"] = index["slots"].get(name, slot_for(item))
        g["wg_pruned_faces"] = prune_transparent(g)
        made.append(g)
    skin_obj = _extract(body, skin, BODY + "_skin_tmp")
    old_data = body.data
    body.data = skin_obj.data
    bpy.data.objects.remove(skin_obj, do_unlink=True)
    body.data.name = BODY
    bpy.data.meshes.remove(old_data)
    toon.apply_toon()
    update_hidden_skin()
    return f"split Body into skin + {len(made)} garments: {[g['wg_garment'] for g in made]}"


# ---------------------------------------------------------------- hide covered skin

class _Coverage:
    """Triangulated garment (rest pose, body space) that can answer 'is this point under
    opaque cloth?' using each layer's texture alpha at the exact surface point."""

    def __init__(self, garment: bpy.types.Object, to_body):
        from . import toon
        me = garment.data
        me.calc_loop_triangles()
        mat = to_body @ garment.matrix_world
        self.verts = [mat @ v.co for v in me.vertices]
        self.tris = [tuple(t.vertices) for t in me.loop_triangles]
        self.loops = [tuple(t.loops) for t in me.loop_triangles]
        self.mat_index = [t.material_index for t in me.loop_triangles]
        uv = me.uv_layers.active
        self.uvs = [tuple(d.uv) for d in uv.data] if uv else None
        self.layers = []
        for m in me.materials:
            src = toon._source_of(m) if m else None
            image, factor, mode, cutoff = (toon._mtoon_inputs(src) if src
                                           else (None, (1, 1, 1, 1), "OPAQUE", 0.5))
            self.layers.append(None if mode == "OPAQUE" or image is None or self.uvs is None
                               else (_alpha_grid(image), factor[3], cutoff if mode == "MASK" else 0.5))
        self.tree = BVHTree.FromPolygons(self.verts, self.tris)

    def _opaque(self, tri: int, point) -> bool:
        from mathutils.interpolate import poly_3d_calc
        layer = self.layers[self.mat_index[tri]]
        if layer is None:
            return True
        grid, alpha_scale, cut = layer
        corners = [self.verts[i] for i in self.tris[tri]]
        weights = poly_3d_calc(corners, point)
        u = sum(w * self.uvs[li][0] for w, li in zip(weights, self.loops[tri]))
        v = sum(w * self.uvs[li][1] for w, li in zip(weights, self.loops[tri]))
        h, w = grid.shape
        return grid[min(h - 1, int(v % 1.0 * h)), min(w - 1, int(u % 1.0 * w))] * alpha_scale > cut

    def covers(self, co, margin: float) -> bool:
        for loc, normal, tri, _dist in self.tree.find_nearest_range(co, margin):
            if (co - loc).dot(normal) < 0 and self._opaque(tri, loc):
                return True
        return False


def update_hidden_skin(margin: float = 0.02, erode: int = 1) -> int:
    """Mask body vertices that lie just behind opaque cloth of a visible garment (rest pose).

    A vertex is hidden when, within ``margin`` metres, some garment surface point is in front
    of it (vertex on the inner side) *and* that garment layer's texture is opaque there.
    The hidden set is then eroded by ``erode`` vertex rings so faces at hems stay visible
    (the Mask modifier drops every face touching a hidden vertex). Prevents skin poking
    through clothes in poses; recomputed whenever the outfit changes.
    """
    body = body_mesh()
    group = body.vertex_groups.get(HIDDEN_GROUP) or body.vertex_groups.new(name=HIDDEN_GROUP)
    group.remove(list(range(len(body.data.vertices))))
    to_body = body.matrix_world.inverted()
    coverage = [_Coverage(g, to_body) for g in garments()      # hair moves: never hides skin
                if not g.hide_render and g.get("wg_slot") != "hair"]
    hidden = {v.index for v in body.data.vertices
              if any(c.covers(v.co, margin) for c in coverage)}
    if erode and hidden:
        neighbours: dict[int, set[int]] = {}
        for e in body.data.edges:
            a, b = e.vertices
            neighbours.setdefault(a, set()).add(b)
            neighbours.setdefault(b, set()).add(a)
        for _ in range(erode):
            hidden = {i for i in hidden if neighbours.get(i, set()) <= hidden}
    hidden = sorted(hidden)
    if hidden:
        group.add(hidden, 1.0, "REPLACE")
    md = body.modifiers.get(MASK_MOD) or body.modifiers.new(MASK_MOD, "MASK")
    md.vertex_group = HIDDEN_GROUP
    md.invert_vertex_group = True
    md.show_viewport = md.show_render = bool(hidden)
    body.modifiers.move(body.modifiers.find(MASK_MOD), 0)   # before armature/outline
    return len(hidden)


# ---------------------------------------------------------------- recolor

def recolor(name: str, tint=None, hsv=None, colorize=None, layer: str | int | None = None) -> str:
    """Recolor a garment or one of its texture layers.

    ``tint``: sRGB multiply (or "#hex"); ``hsv``: (hue 0..1, 0.5 = no shift, sat x, value x);
    ``colorize``: target sRGB/"#hex" keeping the painted shading. ``layer``: a layer index or
    key from ``list_layers()`` (e.g. 2 or "CLOTH_03"); ``None`` = whole garment.
    Calling with no colors resets that scope.
    """
    import json

    from . import toon
    obj = _garment(name)
    conv = lambda v: list(toon.hex_to_srgb(v)) if isinstance(v, str) else (list(v) if v else None)  # noqa: E731
    key = _layer_key(obj, layer) if layer is not None else "CLOTH"
    rules = json.loads(obj["wg_recolor"]) if obj.get("wg_recolor") else {}
    rule = {k: v for k, v in (("tint", conv(tint)), ("hsv", list(hsv) if hsv else None),
                              ("colorize", conv(colorize))) if v is not None}
    if layer is None:                      # whole garment: also clear the legacy object props
        obj.pop("wg_tint", None)
        obj.pop("wg_hsv", None)
    if rule:
        rules[key] = rule
    else:
        rules.pop(key, None)
    if rules:
        obj["wg_recolor"] = json.dumps(rules)
    else:
        obj.pop("wg_recolor", None)
    toon.apply_toon([obj])
    return f"{name} [{key}]: {rule or 'reset'}"


def _layer_key(obj: bpy.types.Object, layer: str | int) -> str:
    keys = [entry["key"] for entry in _layers(obj)]
    if isinstance(layer, int):
        return keys[layer]
    if layer not in keys:
        raise KeyError(f"{obj['wg_garment']} has layers {keys}")
    return layer


def _layers(obj: bpy.types.Object) -> list[dict]:
    """One entry per texture layer (garment material): key, texture, mean colour, coverage."""
    import re

    import numpy as np

    from ..garments import strip_suffix
    from . import toon
    out, seen = [], set()
    for m in obj.data.materials:
        if m is None or m.name.startswith("wgo_"):
            continue
        src = toon._source_of(m)
        match = re.search(r"([A-Z]+_\d+)$", strip_suffix(src.name))
        key = match.group(1) if match else strip_suffix(src.name)
        if key in seen:
            continue
        seen.add(key)
        image = toon._mtoon_inputs(src)[0]
        info = {"key": key, "texture": image.name if image else None}
        if image is not None and image.size[0]:
            px = np.empty(image.size[0] * image.size[1] * 4, dtype=np.float32)
            image.pixels.foreach_get(px)
            px = px.reshape(-1, 4)[::7]
            opaque = px[:, 3] > 0.5
            info["coverage"] = round(float(opaque.mean()), 3)
            mean = px[opaque, :3].mean(axis=0) if opaque.any() else px[:, :3].mean(axis=0)
            info["mean_color"] = "#" + "".join(f"{int(c * 255):02x}" for c in mean)
        out.append(info)
    return out


def list_layers(name: str) -> list[dict]:
    """Texture layers of a garment, for per-layer recoloring."""
    return _layers(_garment(name))


def _garment(name: str) -> bpy.types.Object:
    for g in garments():
        if g["wg_garment"] == name:
            return g
    raise KeyError(f"No garment {name!r}. Have: {list_garments()}")


# ---------------------------------------------------------------- library

def save_garment(name: str) -> str:
    """Write the garment (mesh, materials, packed textures) to assets/garments/<name>.blend."""
    from . import toon
    obj = _garment(name)
    GARMENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = GARMENTS_DIR / f"{name}.blend"
    # Write a standalone copy: no parent / armature reference (libraries.write follows
    # dependencies, so the original would drag in the whole rig), original MToon materials.
    toon.remove_toon([obj])
    standalone = obj.copy()
    standalone.data = obj.data.copy()
    standalone.parent = None
    standalone.matrix_world = obj.matrix_world.copy()
    for md in standalone.modifiers:
        if md.type == "ARMATURE":
            md.object = None
    try:
        images = set()
        for m in standalone.data.materials:
            if m and m.node_tree:
                for n in m.node_tree.nodes:
                    if n.type == "TEX_IMAGE" and n.image is not None:
                        images.add(n.image)
        for img in images:
            if not img.packed_file:
                img.pack()
        bpy.data.libraries.write(str(path), {standalone}, path_remap="NONE", compress=True)
    finally:
        mesh = standalone.data
        bpy.data.objects.remove(standalone, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        toon.apply_toon([obj])
    return str(path)


def garment_signature(obj: bpy.types.Object) -> str:
    """Content hash (geometry size + downsampled textures) to spot duplicate garments."""
    import hashlib

    import numpy as np
    h = hashlib.sha1(f"{len(obj.data.vertices)}:{len(obj.data.polygons)}".encode())
    from . import toon
    for m in obj.data.materials:
        src = toon._source_of(m) if m else None
        image = toon._mtoon_inputs(src)[0] if src else None
        if image is not None and image.size[0]:
            px = np.empty(image.size[0] * image.size[1] * 4, dtype=np.float32)
            image.pixels.foreach_get(px)
            h.update((px[::997] * 255).astype(np.uint8).tobytes())
    return h.hexdigest()[:16]


def _read_index() -> dict:
    """``{"signatures": {garment: sig}, "sets": {set: [garments]}, "slots": {garment: slot},
    "renames": {harvested id: name}, "set_renames": {export: set name}}``."""
    import json
    path = GARMENTS_DIR / "index.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if data and "signatures" not in data:          # first format: a flat signature map
        data = {"signatures": data}
    return {k: data.get(k, {}) for k in ("signatures", "sets", "slots", "renames", "set_renames")}


def rename(mapping: dict[str, str | tuple[str, str]] | None = None,
           set_names: dict[str, str] | None = None) -> list[str]:
    """Give library garments (and outfit sets) descriptive names, optionally fixing slots.

    ``mapping``: ``{old: new}`` or ``{old: (new, slot)}``. The map is remembered in the index
    so ``harvest(fresh=True)`` re-applies it. Called with no arguments, re-applies the stored
    maps (used at the end of harvesting).
    """
    from ..garments import CONFLICTS, validate_name
    index = _read_index()
    log = []
    for old, value in (mapping or {}).items():
        new, slot = (value if isinstance(value, tuple) else (value, None))
        validate_name(new)
        if slot is not None and slot not in CONFLICTS:
            raise ValueError(f"Unknown slot {slot!r}; choose from {sorted(CONFLICTS)}")
        index["renames"][old] = new
        if slot:
            index["slots"][new] = slot
    for old, new in (set_names or {}).items():
        index["set_renames"][old] = validate_name(new)
    # Apply garment renames: files, signatures, set membership.
    for old, new in index["renames"].items():
        src, dst = GARMENTS_DIR / f"{old}.blend", GARMENTS_DIR / f"{new}.blend"
        if src.is_file():
            if dst.is_file():
                dst.unlink()            # a fresh harvest rewrote the old id; replace stale copy
            src.rename(dst)
            log.append(f"{old} -> {new}")
        if old in index["signatures"]:
            index["signatures"][new] = index["signatures"].pop(old)
        if old in index["slots"]:
            index["slots"].setdefault(new, index["slots"].pop(old))
        for members in index["sets"].values():
            members[:] = [new if m == old else m for m in members]
    for old, new in index["set_renames"].items():
        if old in index["sets"]:
            index["sets"][new] = index["sets"].pop(old)
            log.append(f"set {old} -> {new}")
    _write_index(index)
    return log


def _write_index(index: dict) -> None:
    import json
    GARMENTS_DIR.mkdir(parents=True, exist_ok=True)
    (GARMENTS_DIR / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n",
                                             encoding="utf-8")


def list_sets() -> dict[str, list[str]]:
    """Outfit sets: the garments each VroidStudio export was wearing."""
    return _read_index()["sets"]


def equip_set(name: str) -> str:
    """Wear exactly the garments of one harvested export (other garments are hidden; the
    hairstyle is kept)."""
    sets = list_sets()
    if name not in sets:
        raise KeyError(f"No outfit set {name!r}. Sets: {sorted(sets)}")
    for g in garments():
        if g.get("wg_slot") != "hair":
            g.hide_render = g.hide_viewport = True
    for garment in sets[name]:
        equip(garment, exclusive=False)   # sets may layer several items of one slot
    return f"wearing {name}: {sets[name]}"


def skeleton_signature(arm: bpy.types.Object) -> dict[str, tuple[float, float, float]]:
    """Rest head positions of the humanoid deform bones (J_Bip_*), armature space."""
    return {b.name: tuple(b.head_local) for b in arm.data.bones if b.name.startswith("J_Bip_")}


def harvest(names: list[str] | None = None, reference: str = "base_f01",
            restore: bool = True, fresh: bool = False) -> list[str]:
    """Import each ``assets/base/<name>.vrm``, split it, and save new garments to the library.

    Defaults to every ``<reference>*.vrm``. Garments identical to a library entry are skipped;
    a different garment with a taken name gets a ``_<export>`` suffix. Exports whose skeleton
    doesn't match ``reference`` (different body proportions) are skipped: garments wouldn't fit.
    Skin vertex counts are *not* compared; VroidStudio removes body faces hidden by some outfits.
    """
    import contextlib
    import io

    from .character import BASE_DIR, character_armature, import_base
    # Exports named <reference>_hair* only differ in hairstyle: wogen.bl.hair harvests those.
    names = names or sorted(p.stem for p in BASE_DIR.glob(f"{reference}*.vrm")
                            if not p.stem.startswith(f"{reference}_hair"))
    # ``fresh`` ignores the existing index and overwrites library files by name.
    index = _read_index()
    if fresh:                                  # keep names/slots (and hairstyles), rebuild contents
        index["signatures"] = {k: v for k, v in index["signatures"].items()
                               if index["slots"].get(k) == "hair"}
        index["sets"] = {}
    sigs, sets = index["signatures"], index["sets"]
    if not fresh:
        for existing in list_library():      # library entries saved before the index existed
            sigs.setdefault(existing, "")
    from . import garment_rig
    with contextlib.redirect_stdout(io.StringIO()):
        import_base(reference)
    ref_skeleton = skeleton_signature(character_armature())
    ref_bones = set(character_armature().data.bones.keys())
    log = []
    for name in names:
        with contextlib.redirect_stdout(io.StringIO()):
            import_base(name)
            from . import toon
            toon.apply_toon()
            split(apply_names=False)
        dz, mismatch = skeleton_mismatch(ref_skeleton, skeleton_signature(character_armature()))
        if mismatch is not None:
            log.append(f"{name}: SKIPPED (skeleton differs from {reference}: {mismatch})")
            continue
        worn = []
        sets[name] = worn
        for g in garments():
            if abs(dz) > 1e-6:
                # Re-seat on the reference skeleton; shoes remember the lift they need.
                from mathutils import Matrix
                g.data.transform(Matrix.Translation((0.0, 0.0, -dz)))
                g.data.update()
            if g["wg_slot"] == "shoes":
                g["wg_lift"] = dz
            sig = garment_signature(g)
            base = g["wg_garment"]
            match = next((k for k, v in sigs.items() if v == sig), None)
            if match:
                worn.append(match)
                log.append(f"{name}: {base} = existing {match}")
                continue
            # Free name, or a pre-index library entry with unknown signature: (re)save as-is.
            taken = bool(sigs.get(base))
            target = f"{base}_{name.removeprefix(reference + '_')}" if taken else base
            if target != base:
                g["wg_garment"] = target
                g.name = GARMENT_PREFIX + target
            rig = garment_rig.extract(g, character_armature(), ref_bones, dz, target)
            garment_rig.store(g, rig)
            if rig:
                log.append(f"{name}: {target} carries {len(rig['bones'])} bones, "
                           f"{len(rig['springs'])} spring chains, {len(rig['colliders'])} colliders")
            save_garment(target)
            sigs[target] = sig
            worn.append(target)
            log.append(f"{name}: saved {target} ({g['wg_slot']}, {len(g.data.polygons)} faces)")
    _write_index(index)
    log += [f"renamed {line}" for line in rename()]      # re-apply stored descriptive names
    if restore:
        with contextlib.redirect_stdout(io.StringIO()):
            from .character import prepare
            prepare(reference)
    return log


def shoe_lift() -> float:
    """Vertical lift (m) the equipped shoes need relative to the reference export."""
    try:
        return max((float(g.get("wg_lift", 0.0)) for g in garments()
                    if g["wg_slot"] == "shoes" and not g.hide_render), default=0.0)
    except (KeyError, RuntimeError):
        return 0.0


def list_library() -> list[str]:
    return sorted(p.stem for p in GARMENTS_DIR.glob("*.blend")) if GARMENTS_DIR.is_dir() else []


def reenable_mtoon(materials) -> int:
    """Library round-trips keep a material's MToon data but drop ``mtoon1.enabled``; without
    it the VRM exporter writes plain glTF materials (no cel look, alpha lost)."""
    count = 0
    for m in materials:
        if m is None:
            continue
        ext = getattr(m, "vrm_addon_extension", None)
        mt = ext.mtoon1 if ext else None
        if mt is not None and not mt.enabled and mt.pbr_metallic_roughness.base_color_texture.index.source:
            mt.enabled = True
            count += 1
    return count


def unequip(slot_or_name: str) -> list[str]:
    """Hide garments by slot (e.g. 'shoes') or garment name."""
    removed = []
    for g in garments():
        if slot_or_name in (g["wg_slot"], g["wg_garment"]):
            g.hide_render = g.hide_viewport = True
            removed.append(g["wg_garment"])
    update_hidden_skin()
    _reground()
    return removed


def _reground() -> None:
    """Re-apply the foot grounding (shoe lift may have changed)."""
    from .pose import ground_feet
    ground_feet()


def equip(name: str, exclusive: bool = True) -> str:
    """Show a garment already on the character, or load it from the library and bind it.

    ``exclusive`` hides other visible garments in conflicting slots."""
    from . import toon
    coll, arm = _character()
    existing = next((g for g in garments() if g["wg_garment"] == name), None)
    if existing is None:
        path = GARMENTS_DIR / f"{name}.blend"
        if not path.is_file():
            raise FileNotFoundError(f"{path} (library: {list_library()})")
        with bpy.data.libraries.load(str(path), link=False) as (src, dst):
            dst.objects = [n for n in src.objects if n.startswith(GARMENT_PREFIX)][:1]
        if not dst.objects:
            raise RuntimeError(f"{path} contains no {GARMENT_PREFIX}* object")
        existing = dst.objects[0]
        coll.objects.link(existing)
        existing.parent = arm
        existing["wg_garment"] = name          # the file name is authoritative (renames)
        existing.name = GARMENT_PREFIX + name
        slot = _read_index()["slots"].get(name)
        if slot:
            existing["wg_slot"] = slot
        reenable_mtoon(existing.data.materials)
        for md in existing.modifiers:
            if md.type == "ARMATURE":
                md.object = arm
        from . import garment_rig
        from .body import fit_garment, fit_rig
        rig = fit_rig(garment_rig.get(existing), arm)     # follow the generated body
        if rig:
            garment_rig.install(arm, rig)
        fit_garment(existing, arm, rig)
        missing = sorted(n for n in garment_rig._weighted_groups(existing)
                         if n not in arm.data.bones and not n.startswith("wg_"))
        if missing:
            print(f"[wogen] {name}: weighted vertex groups without bones: {missing[:8]}")
        toon.apply_toon([existing])
    if existing["wg_slot"] == "hair":
        from .hair import strip_base
        strip_base()                           # a hairstyle module replaces the base hair
    for g in garments():
        if (exclusive and g is not existing and not g.hide_render
                and g["wg_slot"] in CONFLICTS[existing["wg_slot"]]):
            g.hide_render = g.hide_viewport = True
    existing.hide_render = existing.hide_viewport = False
    update_hidden_skin()
    _reground()
    return f"equipped {name} ({existing['wg_slot']})"
