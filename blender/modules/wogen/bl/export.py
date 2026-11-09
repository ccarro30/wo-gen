"""Export the generated character as VRM 1.0 (VTubing / VRM apps) or FBX (game engines).

Exporters can't read wogen's toon shaders, and several wogen looks only exist as shader or
modifier tricks. So export always works on a *copy* of the scene (``export_character`` saves
a temp .blend and runs a headless Blender), where ``prepare()`` destructively:

1. resets the pose and drops animation, overlay, outline and mask modifiers;
2. bakes the procedural face shape keys (``wg_*``) into the mesh and its expression keys;
3. deletes skin hidden under clothes and garments that aren't worn;
4. restores the MToon materials, baking palette/garment recolors into new textures;
5. registers garment spring chains and colliders (skirts) in the VRM spring-bone data, and
   tunes the bust chains to approximate the soft-tissue bounce.

VRM keeps MToon materials (viewers draw cel shading and outlines themselves). FBX gets
plain Principled BSDF materials using the baked base-color textures.

Chat usage::

    from wogen.bl import export
    export.export_character(r"...\\out\\aiko.vrm")          # or .fbx; live scene untouched
"""

from __future__ import annotations

import colorsys
import json
from pathlib import Path

import bmesh
import bpy
import numpy as np

# ---------------------------------------------------------------- texture baking


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def _hsv_shift(lin: np.ndarray, hsv) -> np.ndarray:
    """Vectorised hue/saturation/value adjust (hue 0.5 = unchanged), like the shader node."""
    shift = (hsv[0] - 0.5) % 1.0
    flat = lin.reshape(-1, 3)
    out = np.empty_like(flat)
    for i, (r, g, b) in enumerate(flat):   # textures are <= 2k; fine for an export step
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        out[i] = colorsys.hsv_to_rgb((h + shift) % 1.0, min(1.0, s * hsv[1]), v * hsv[2])
    return out.reshape(lin.shape)


def bake_recolor(image: bpy.types.Image, recolor: dict, name: str) -> bpy.types.Image:
    """New packed image = ``image`` with wogen recolor ops applied (same math as the shader)."""
    w, h = image.size
    px = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    lin = _srgb_to_linear(px[:, :3].astype(np.float64))
    if recolor.get("colorize") is not None:
        lum = lin @ np.array([0.2126, 0.7152, 0.0722])
        mask = px[:, 3] > 0.5
        mean = float(lum[mask].mean()) if mask.any() else float(lum.mean())
        target = _srgb_to_linear(np.array(recolor["colorize"], dtype=np.float64))
        lin = target[None, :] * (lum / max(mean, 1e-3))[:, None]
    if recolor.get("hsv") is not None:
        lin = _hsv_shift(np.clip(lin, 0, 1), recolor["hsv"])
    if recolor.get("tint") is not None:
        lin = lin * _srgb_to_linear(np.array(recolor["tint"], dtype=np.float64))[None, :]
    px[:, :3] = _linear_to_srgb(lin)
    out = bpy.data.images.new(name, w, h, alpha=True)
    out.pixels.foreach_set(px.ravel())
    out.pack()
    return out


# ---------------------------------------------------------------- scene preparation


def _bake_face_keys(face: bpy.types.Object) -> int:
    keys = face.data.shape_keys
    if keys is None:
        return 0
    blocks = keys.key_blocks
    n = len(face.data.vertices)
    basis = np.empty(n * 3, dtype=np.float32)
    blocks[0].data.foreach_get("co", basis)
    offset = np.zeros(n * 3, dtype=np.float64)
    wg = [kb for kb in blocks if kb.name.startswith("wg_")]
    tmp = np.empty(n * 3, dtype=np.float32)
    for kb in wg:
        kb.data.foreach_get("co", tmp)
        offset += kb.value * (tmp.astype(np.float64) - basis)
    for kb in blocks:
        if kb.name.startswith("wg_"):
            continue
        kb.data.foreach_get("co", tmp)
        kb.data.foreach_set("co", (tmp + offset).astype(np.float32))
    for kb in wg:
        face.shape_key_remove(kb)
    face.data.vertices.foreach_set("co", (basis + offset).astype(np.float32))
    face.data.update()
    return len(wg)


def _delete_hidden_skin(body: bpy.types.Object) -> int:
    from .outfit import HIDDEN_GROUP, MASK_MOD
    md = body.modifiers.get(MASK_MOD)
    if md is not None:
        body.modifiers.remove(md)
    vg = body.vertex_groups.get(HIDDEN_GROUP)
    if vg is None:
        return 0
    bm = bmesh.new()
    bm.from_mesh(body.data)
    layer = bm.verts.layers.deform.verify()
    doomed = [v for v in bm.verts if vg.index in v[layer]]
    bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    bm.to_mesh(body.data)
    bm.free()
    body.vertex_groups.remove(vg)
    return len(doomed)


def _image_of(mat: bpy.types.Material):
    from .toon import _mtoon_inputs
    return _mtoon_inputs(mat)[0]


def _bake_material_recolors(meshes) -> int:
    """Give each recolored (object, material) a MToon copy whose textures carry the recolor."""
    from ..garments import strip_suffix
    from .toon import material_recolor
    cache: dict[tuple, bpy.types.Material] = {}
    baked = 0
    for obj in meshes:
        for i, mat in enumerate(obj.data.materials):
            if mat is None:
                continue
            rc = material_recolor(obj, mat.name)
            if not rc:
                continue
            key = (mat.name, json.dumps(rc, sort_keys=True))
            if key not in cache:
                image = _image_of(mat)
                if image is None:
                    continue
                # ".9NN" suffix: parseable as a Blender duplicate suffix on re-import.
                suffix = f".{900 + len(cache) % 100:03d}"
                new_img = bake_recolor(image, rc, f"{image.name}{suffix}")
                copy = mat.copy()
                copy.name = f"{strip_suffix(mat.name)}{suffix}"
                ext = copy.vrm_addon_extension.mtoon1
                ext.pbr_metallic_roughness.base_color_texture.index.source = new_img
                mt = ext.extensions.vrmc_materials_mtoon
                if mt.shade_multiply_texture.index.source == image:
                    mt.shade_multiply_texture.index.source = new_img
                if copy.node_tree:
                    for node in copy.node_tree.nodes:
                        if node.type == "TEX_IMAGE" and node.image == image:
                            node.image = new_img
                cache[key] = copy
                baked += 1
            obj.data.materials[i] = cache[key]
    return baked


def _tune_bust_springs(arm: bpy.types.Object) -> int:
    """Give the VRM bust chains the parameters that approximate the soft-tissue bounce."""
    from .physics import BUST_SPRING, BUST_SPRING_PARAMS
    tuned = 0
    for sp in arm.data.vrm_addon_extension.spring_bone1.springs:
        if sp.vrm_name != BUST_SPRING:
            continue
        for j in sp.joints[:-1]:            # the last joint is the chain's end
            for key, value in BUST_SPRING_PARAMS.items():
                setattr(j, key, value)
            tuned += 1
    return tuned


def _register_garment_springs(arm: bpy.types.Object) -> int:
    """Add worn garments' spring chains/colliders to the VRM spring-bone data."""
    from . import garment_rig
    from .outfit import garments
    sb = arm.data.vrm_addon_extension.spring_bone1
    added = 0
    for g in garments():
        rig = garment_rig.get(g)
        if not rig.get("springs"):
            continue
        bpy.ops.vrm.add_spring_bone1_collider_group(armature_object_name=arm.name)
        group_index = len(sb.collider_groups) - 1
        group = sb.collider_groups[group_index]
        group.vrm_name = g["wg_garment"]
        for spec in rig.get("colliders", {}).values():
            if spec["bone"] not in arm.data.bones:
                continue
            bpy.ops.vrm.add_spring_bone1_collider(armature_object_name=arm.name)
            c = sb.colliders[-1]
            c.node.bone_name = spec["bone"]
            c.shape_type = "Sphere"
            c.shape.sphere.offset = spec["offset"]
            c.shape.sphere.radius = spec["radius"]
            bpy.ops.vrm.add_spring_bone1_collider_group_collider(
                armature_object_name=arm.name, collider_group_index=group_index)
            group.colliders[-1].collider_uuid = c.uuid
        for spring in rig["springs"]:
            joints = [j for j in spring["joints"] if j["bone"] in arm.data.bones]
            if len(joints) < 2:
                continue
            bpy.ops.vrm.add_spring_bone1_spring(armature_object_name=arm.name)
            si = len(sb.springs) - 1
            sp = sb.springs[si]
            sp.vrm_name = f"{g['wg_garment']}:{spring['name']}"
            for j in joints:
                bpy.ops.vrm.add_spring_bone1_spring_joint(
                    armature_object_name=arm.name, spring_index=si, guess_properties=False)
                jj = sp.joints[-1]
                jj.node.bone_name = j["bone"]
                jj.stiffness, jj.drag_force = j["stiffness"], j["drag_force"]
                jj.gravity_power, jj.gravity_dir = j["gravity_power"], j["gravity_dir"]
                jj.hit_radius = j["hit_radius"]
            bpy.ops.vrm.add_spring_bone1_spring_collider_group(
                armature_object_name=arm.name, spring_index=si)
            sp.collider_groups[-1].collider_group_uuid = group.uuid
            added += 1
    return added


def prepare(name: str | None = None) -> list[str]:
    """Destructively turn the scene's wogen character into an exportable one."""
    from . import anim, outfit, overlay, physics, toon
    from .character import character_armature, character_meshes
    from .face import face_mesh
    from .pose import reset_pose
    log = []
    arm = character_armature()
    physics.clear(arm)
    anim.clear()
    reset_pose(arm)
    arm.location = (0.0, 0.0, 0.0)
    face = face_mesh()
    overlay.remove(face)
    from . import face_shading
    face_shading.strip(face)     # the baked custom normals stay
    for g in list(outfit.garments()):
        if g.hide_render:
            bpy.data.objects.remove(g, do_unlink=True)
    meshes = character_meshes()
    toon.remove_toon(meshes)                      # MToon back, outlines stripped
    log.append("MToon re-enabled on %d materials" % outfit.reenable_mtoon(
        {m for obj in meshes for m in obj.data.materials if m}))
    for obj in meshes:
        for md in list(obj.modifiers):
            if md.type != "ARMATURE":
                obj.modifiers.remove(md)
    log.append(f"face keys baked: {_bake_face_keys(face)}")
    log.append(f"hidden skin vertices deleted: {_delete_hidden_skin(outfit.body_mesh())}")
    log.append(f"recolored materials baked: {_bake_material_recolors(meshes)}")
    log.append(f"garment spring chains registered: {_register_garment_springs(arm)}")
    log.append(f"bust spring joints tuned: {_tune_bust_springs(arm)}")
    from .garment_rig import RIG_KEY
    for g in outfit.garments():       # chains now live in the VRM data; avoid double simulation
        if RIG_KEY in g:
            del g[RIG_KEY]             # (the VRM add-on round-trips custom properties)
    meta = arm.data.vrm_addon_extension.vrm1.meta
    if name:
        meta.vrm_name = name
    return log


# ---------------------------------------------------------------- writers


def write_vrm(path: str) -> str:
    from .character import character_armature
    arm = character_armature()
    result = bpy.ops.export_scene.vrm(filepath=path, armature_object_name=arm.name,
                                      ignore_warning=True, export_invisibles=False)
    if "FINISHED" not in result:
        raise RuntimeError(f"VRM export failed: {result}")
    return path


def _principled_from_mtoon(mat: bpy.types.Material) -> bpy.types.Material:
    from .toon import _mtoon_inputs
    image, factor, mode, cutoff = _mtoon_inputs(mat)
    out = bpy.data.materials.new(f"{mat.name}_fbx")
    out.use_nodes = True
    nodes, links = out.node_tree.nodes, out.node_tree.links
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = tuple(factor)
    bsdf.inputs["Roughness"].default_value = 0.9
    if image is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if mode != "OPAQUE":
            links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
            out.surface_render_method = "DITHERED" if mode == "MASK" else "BLENDED"
    return out


def write_fbx(path: str) -> str:
    from .character import character_armature, character_meshes
    arm = character_armature()
    meshes = character_meshes()
    cache = {}
    for obj in meshes:
        for i, mat in enumerate(obj.data.materials):
            if mat is not None:
                cache.setdefault(mat.name, _principled_from_mtoon(mat))
                obj.data.materials[i] = cache[mat.name]
    for img in bpy.data.images:
        if img.size[0] and not img.packed_file and img.source in ("GENERATED", "FILE"):
            try:
                img.pack()
            except RuntimeError:
                pass
    bpy.ops.object.select_all(action="DESELECT")
    for obj in [arm, *meshes]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = arm
    result = bpy.ops.export_scene.fbx(
        filepath=path, use_selection=True, object_types={"ARMATURE", "MESH"},
        add_leaf_bones=False, bake_anim=False, path_mode="COPY", embed_textures=True,
        mesh_smooth_type="FACE", use_armature_deform_only=False)
    if "FINISHED" not in result:
        raise RuntimeError(f"FBX export failed: {result}")
    return path


def export_prepared(path: str, name: str | None = None) -> list[str]:
    """In-process: prepare (destructive) and write ``path`` (.vrm or .fbx)."""
    log = prepare(name)
    suffix = Path(path).suffix.lower()
    if suffix == ".vrm":
        write_vrm(path)
    elif suffix == ".fbx":
        write_fbx(path)
    else:
        raise ValueError(f"Unsupported export format {suffix!r} (use .vrm or .fbx)")
    log.append(f"wrote {path}")
    return log


def export_character(path: str, name: str | None = None) -> str:
    """Safe export from any session: saves a temp copy and exports it headlessly."""
    import shutil

    from ..launcher import run_job
    from ..paths import scratch_dir
    work = scratch_dir("export")
    tmp = work / "scene.blend"
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(tmp), copy=True, compress=False)
        args = ["--out", str(Path(path).resolve())] + (["--name", name] if name else [])
        code = run_job("export", *args, blend_file=tmp)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if code != 0 or not Path(path).is_file():
        raise RuntimeError(f"export failed (blender exit code {code}); see console output")
    return str(path)
