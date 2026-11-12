"""Import MMD (PMX) character models so wogen can pose and animate them.

``import_pmx(path)`` loads the model with the mmd_tools add-on (meshes, armature, facial
morphs; not MMD's rigid-body physics) into the character collection, then:

- stores the VRM humanoid map (``wogen.mmd.humanoid_map``) on the armature (``HUMANOID_KEY``),
  which ``pose.humanoid_map`` reads when the armature has no VRM humanoid data;
- mutes the leg IK constraints mmd_tools adds and their knee rotation limits (wogen solves
  legs itself; the IK controllers would hold the legs, the limits bend the knees 0.5 deg),
  and the waist-cancel bones (so the legs follow the hips); stores the D-bone follow map
  for the mocap retarget (``FOLLOW_KEY``);
- converts the A-pose rest (arms 34-49 degrees down in the packages tried) into the T-pose
  rest wogen's poses, IK and mocap are defined against: the arm chains are posed straight
  along +-X, mmd_tools' constraints move the helper bones (arm/elbow assist, twist) as the
  model intends, then every bone's evaluated transform re-skins the meshes (all shape keys)
  and becomes its new rest. That keeps the shadow/dummy constraint pairs at identity:
  ``rest_error`` is ~0.002 mm and the rest mesh matches the original rig posed into the
  T-pose to the same tolerance;
- lifts the model so its lowest rest vertex is on the floor, and measures each shoe's heel
  and toe points for the mocap floor pass (``SOLES_KEY``).

Chat usage::

    from wogen.bl import mmd_import
    mmd_import.list_models()                  # character PMX files under imports/
    mmd_import.import_pmx(path)
"""

from __future__ import annotations

import json
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

from .. import mmd
from ..paths import REPO_ROOT
from .mocap import FOLLOW_KEY, SOLES_KEY

MMD_ADDON = "bl_ext.blender_org.mmd_tools"
HUMANOID_KEY = "wg_humanoid"
SOURCE_KEY = "wg_mmd_source"
GROUND_KEY = "wg_ground_shift"  # m the import raised the model to stand on the floor
NAMES_KEY = "wg_original_names" # {kind: {original: english}} from ``translate_names``
IMPORTS_DIR = REPO_ROOT / "imports"
SCALE = 0.08                    # MMD units -> metres (the mmd_tools default)
GROUND_TOL = 1e-4               # m: models closer than this to the floor aren't shifted
SOLE_BAND = 0.012               # m: foot vertices this low count as the sole (heel point)
TOE_BAND = 0.04                 # m: the toe tip may sit this high (heeled shoes curve up)


def ensure_addon() -> None:
    import addon_utils
    if not addon_utils.check(MMD_ADDON)[1]:          # (enabled by default, loaded now)
        addon_utils.enable(MMD_ADDON, default_set=False)
    if not addon_utils.check(MMD_ADDON)[1]:
        raise RuntimeError(f"{MMD_ADDON} could not be enabled; is mmd_tools installed?")


def list_models() -> list[str]:
    return [str(p) for p in mmd.list_models(IMPORTS_DIR)]


PHYSICS_LEAD_IN = 48            # frames simulated before the visible range (bodies settle)


def has_physics(arm) -> bool:
    """Whether the loaded model runs its own (MMD rigid-body) physics."""
    world = bpy.context.scene.rigidbody_world
    return arm is not None and SOURCE_KEY in arm and world is not None and world.enabled


def build_physics(arm) -> str:
    """Build the model's rigid bodies and joints into Blender rigid-body physics (mmd_tools'
    build_rig): the modelers' own hair, skirt, tail, accessory and soft-tissue setup, except
    the bust (``release_bust``, first, so the build never ties those bones to the sim)."""
    released = release_bust(arm)
    root = arm.parent
    layer = bpy.context.view_layer
    prev = layer.objects.active
    for o in layer.objects:
        o.select_set(False)
    root.select_set(True)
    layer.objects.active = root
    try:
        result = bpy.ops.mmd_tools.build_rig()
    finally:
        layer.objects.active = prev
    bodies = sum(1 for o in bpy.data.objects if getattr(o, "mmd_type", "") == "RIGID_BODY")
    return f"MMD physics built ({bodies} rigid bodies): {result}; {released}"


TISSUE_KEY = "wg_tissue_bones"  # bust bones the soft-tissue solver drives (release_bust)


def tissue_bones(arm) -> list[str]:
    return json.loads(arm.get(TISSUE_KEY, "[]")) if arm is not None else []


def release_bust(arm) -> str:
    """Hand the breasts from the model's rigid bodies to wogen's soft-tissue solver
    (``physics._Tissue``, the bounce tuned for the original characters). The packages tried
    build each side as a closed loop of light bodies on stiff springs (about 100 Hz), which
    barely moves in a walk. Per side this picks the driven bust bone carrying the skin
    (``mmd.bust_bones``) and turns the bust bodies joined to it into bone-following (static)
    bodies, so keys drive the bones and the bodies still push hair. Runs before
    ``build_rig``: built as dynamic, those bones would follow the simulation while chest
    colliders parented to them feed it (a dependency cycle)."""
    bodies = [o for o in bpy.data.objects if getattr(o, "mmd_type", "") == "RIGID_BODY"]
    joints = [o.rigid_body_constraint for o in bpy.data.objects
              if getattr(o, "mmd_type", "") == "JOINT" and o.rigid_body_constraint is not None]
    if not bodies:
        return "no bust physics"
    original = original_names(arm, "bones")
    dynamic = [o for o in bodies if o.mmd_rigid.type != "0" and o.mmd_rigid.bone in arm.data.bones]
    weights: dict[str, float] = {}
    from .character import character_meshes
    for obj in character_meshes():
        groups = {g.index: g.name for g in obj.vertex_groups}
        for v in obj.data.vertices:
            for g in v.groups:
                name = groups.get(g.group)
                if name is not None:
                    weights[name] = weights.get(name, 0.0) + g.weight
    chosen = mmd.bust_bones(_skeleton(arm), original, {o.mmd_rigid.bone for o in dynamic}, weights)
    bust = {o for o in dynamic if mmd.is_bust(original.get(o.mmd_rigid.bone, o.mmd_rigid.bone))}
    todo = [o for o in bust if o.mmd_rigid.bone in chosen]
    group: set = set()
    while todo:
        o = todo.pop()
        if o in group:
            continue
        group.add(o)
        for c in joints:
            if o in (c.object1, c.object2):
                other = c.object2 if c.object1 == o else c.object1
                if other in bust:
                    todo.append(other)
    for o in group:
        o.mmd_rigid.type = "0"
    arm[TISSUE_KEY] = json.dumps(chosen)
    return (f"bust on the soft-tissue solver: {', '.join(chosen) or 'none'} "
            f"({len(group)} bodies now follow their bones; {len(joints)} joints seen)")


def _animated(arm) -> list:
    """The character's IDs with keys: the armature and the meshes' shape keys."""
    from .character import character_meshes
    ids = [arm] + [o.data.shape_keys for o in character_meshes() if o.data.shape_keys]
    return [i for i in ids if i.animation_data is not None and i.animation_data.action]


def _shift_keys(ids, offset: int) -> None:
    from .anim import channelbag
    for idb in ids:
        bag = channelbag(idb)
        for fc in (bag.fcurves if bag else ()):
            for kp in fc.keyframe_points:
                kp.co.x += offset
                kp.handle_left.x += offset
                kp.handle_right.x += offset
            fc.update()


def _rest_value(path: str, index: int) -> float:
    if path.endswith("rotation_quaternion") and index == 0:
        return 1.0
    return 1.0 if path.endswith("scale") else 0.0


def _key_pose(arm, frame: int, rest: bool) -> None:
    """Key every pose bone's transform at ``frame``: its current values, or the rest pose."""
    for pb in arm.pose.bones:
        rot = "rotation_quaternion" if pb.rotation_mode == "QUATERNION" else "rotation_euler"
        for path in ("location", rot, "scale"):
            if rest:
                values = getattr(pb, path)
                for i in range(len(values)):
                    values[i] = _rest_value(path, i)
            pb.keyframe_insert(path, frame=frame)


def simulate(start: int, end: int, lead_in: int = PHYSICS_LEAD_IN) -> str:
    """Bake the rigid-body simulation over ``start``..``end`` with a ``lead_in``: the rigid
    bodies begin at their rest (T-pose) placement, so the animation is moved ``lead_in``
    frames later and eases in from the rest pose keyed at ``start`` (scenes can't start
    before frame 0, so the lead-in can't go before the clip). The scene range moves to the
    shifted clip. An unkeyed (still) pose is keyed at the end of the lead-in. Returns a
    summary."""
    scene = bpy.context.scene
    world = scene.rigidbody_world
    if world is None or not world.enabled:
        return "no MMD physics"
    from .character import character_armature
    arm = character_armature()
    still = arm.animation_data is None or arm.animation_data.action is None
    if still:
        _key_pose(arm, start + lead_in, rest=False)
    else:
        _shift_keys(_animated(arm), lead_in)
    _key_pose(arm, start, rest=True)
    scene.frame_start, scene.frame_end = start + lead_in, max(end + lead_in, start + lead_in)
    cache = world.point_cache
    with bpy.context.temp_override(point_cache=cache):
        bpy.ops.ptcache.free_bake()
    cache.frame_start, cache.frame_end = start, scene.frame_end
    first = scene.frame_start
    scene.frame_start = start                  # simulate from the rest key
    try:
        with bpy.context.temp_override(point_cache=cache, scene=scene):
            bpy.ops.ptcache.bake(bake=True)
    finally:
        scene.frame_start = first
    scene.frame_set(first)
    return (f"baked MMD physics: clip now frames {scene.frame_start}-{scene.frame_end} "
            f"after a {lead_in}-frame lead-in from rest")


def find_model(name: str) -> Path:
    """The PMX under ``imports/`` that ``name`` picks (a path, name or folder/name)."""
    return mmd.find_model(name, IMPORTS_DIR)


def prepare(name: str) -> bpy.types.Object:
    """Empty scene to a posable imported character (``import_pmx``), keeping the model's own
    materials (toon look for imported models: roadmap step 4). Returns the armature."""
    from .character import clear_default_scene
    clear_default_scene()
    arm = import_pmx(find_model(name), physics=True)
    print(f"[mmd] {build_physics(arm)}")
    return arm


def _skeleton(arm) -> dict[str, str | None]:
    return {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}


def _subtree(arm, root: str) -> set[str]:
    out, todo = set(), [arm.data.bones[root]]
    while todo:
        b = todo.pop()
        out.add(b.name)
        todo.extend(b.children)
    return out


def tpose_transforms(arm, hmap: dict[str, str]) -> dict[str, Matrix]:
    """Per-bone rest transforms (armature space) that straighten each arm along +-X."""
    transforms: dict[str, Matrix] = {}
    bones = arm.data.bones
    for side, sign in (("left", 1.0), ("right", -1.0)):
        names = [hmap.get(f"{side}_{part}") for part in mmd.ARM_CHAIN]
        names = [n for n in names if n]
        for i, name in enumerate(names):
            # Where this joint and the next are after the rotations applied so far.
            m = transforms.get(name, Matrix.Identity(4))
            head = m @ bones[name].head_local
            nxt = bones[names[i + 1]].head_local if i + 1 < len(names) else bones[name].tail_local
            direction = (m @ nxt) - head
            rot = direction.rotation_difference(Vector((sign, 0.0, 0.0))).to_matrix().to_4x4()
            pivot = Matrix.Translation(head) @ rot @ Matrix.Translation(-head)
            for b in _subtree(arm, name):
                transforms[b] = pivot @ transforms.get(b, Matrix.Identity(4))
    return transforms


def _pose_chains(arm, hmap: dict[str, str], transforms: dict[str, Matrix]) -> None:
    """Pose the arm chains by their rest transforms, parents first; everything else follows
    through parenting and mmd_tools' additional-rotation constraints (arm/elbow helpers)."""
    layer = bpy.context.view_layer
    for side in ("left", "right"):
        for part in mmd.ARM_CHAIN:
            name = hmap.get(f"{side}_{part}")
            if name and name in transforms:
                pb = arm.pose.bones[name]
                pb.matrix = transforms[name] @ pb.bone.matrix_local
                layer.update()


def _posed_transforms(arm, tol: float = 1e-6) -> dict[str, Matrix]:
    """Evaluated rest-to-pose transform (armature space) of every bone that moved."""
    bpy.context.view_layer.update()
    out = {}
    for pb in arm.pose.bones:
        m = pb.matrix @ pb.bone.matrix_local.inverted()
        if max(abs(m[i][j] - (i == j)) for i in range(4) for j in range(4)) > tol:
            out[pb.name] = m
    return out


def _move_bones(arm, transforms: dict[str, Matrix]) -> None:
    view_layer = bpy.context.view_layer
    prev = view_layer.objects.active
    view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        for eb in arm.data.edit_bones:
            m = transforms.get(eb.name)
            if m is not None:
                length = eb.length
                eb.matrix = m @ eb.matrix
                eb.length = length
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        view_layer.objects.active = prev


def _rest_coords(arm, obj) -> np.ndarray:
    """Basis vertex positions of ``obj`` in armature space."""
    n = len(obj.data.vertices)
    co = np.empty(n * 3, np.float32)
    obj.data.vertices.foreach_get("co", co)
    m = np.array(arm.matrix_world.inverted() @ obj.matrix_world)
    return (m[:3, :3] @ co.reshape(-1, 3).T).T + m[:3, 3]


def _ground(arm, meshes) -> float:
    """Shift the model (meshes with all shape keys, and bones) so its lowest rest vertex is on
    the floor: some packages stand a few cm into it. Returns the shift (m)."""
    low = min((float(_rest_coords(arm, o)[:, 2].min()) for o in meshes if o.data.vertices),
              default=0.0)
    if abs(low) < GROUND_TOL:
        return 0.0
    shift = Matrix.Translation((0.0, 0.0, -low))
    for obj in meshes:
        to_arm = arm.matrix_world.inverted() @ obj.matrix_world
        obj.data.transform(to_arm.inverted() @ shift @ to_arm, shape_keys=True)
        obj.data.update()
    _move_bones(arm, {b.name: shift for b in arm.data.bones})
    return -low


def _dominant_bones(obj, bones) -> list[str | None]:
    """Per vertex, the deform bone with the largest weight (None if unweighted)."""
    names = {vg.index: vg.name for vg in obj.vertex_groups}
    out = []
    for v in obj.data.vertices:
        best, top = None, 0.0
        for g in v.groups:
            name = names.get(g.group)
            if g.weight > top and name in bones and bones[name].use_deform:
                best, top = name, g.weight
        out.append(best)
    return out


def measure_soles(arm, meshes, hmap: dict[str, str],
                  follow: dict[str, str]) -> dict[str, dict[str, list[float]]]:
    """Per side, the shoe's heel (rearmost vertex within ``SOLE_BAND`` of the floor) and toe
    tip (frontmost vertex below ``TOE_BAND``; a heeled shoe's toe curves up off the floor),
    among vertices skinned mainly to that foot or its toes (or the D-bones copying them).
    Armature space, rest pose; the character faces -Y."""
    bones = arm.data.bones
    coords = [(_rest_coords(arm, o), _dominant_bones(o, bones)) for o in meshes if o.data.vertices]
    out = {}
    for side in ("left", "right"):
        roots = {hmap[f"{side}_foot"], hmap.get(f"{side}_toes")}
        roots |= {d for d, fk in follow.items() if fk in roots}
        foot = set().union(*(_subtree(arm, r) for r in roots if r))
        pts = np.concatenate([co[[b in foot for b in dom]] for co, dom in coords])
        heel_pts, toe_pts = pts[pts[:, 2] < SOLE_BAND], pts[pts[:, 2] < TOE_BAND]
        if not len(heel_pts) or not len(toe_pts):
            continue
        heel, toe = heel_pts[heel_pts[:, 1].argmax()], toe_pts[toe_pts[:, 1].argmin()]
        out[side] = {"heel": [float(c) for c in heel], "toe": [float(c) for c in toe]}
    return out


def _mute_ik(arm) -> int:
    """Mute the leg IK constraints and the rotation limits mmd_tools adds for them (the
    knee limit's 0.5 degree minimum would otherwise keep the knees bent at rest)."""
    muted, chain = 0, set()
    for pb in arm.pose.bones:
        for c in pb.constraints:
            if c.type == "IK" and c.subtarget and c.subtarget.split(".")[0] in mmd.IK_BONES:
                c.mute = True
                muted += 1
                b, depth = pb, c.chain_count or 1_000
                while b and depth > 0:
                    chain.add(b.name)
                    b, depth = b.parent, depth - 1
    for name in chain:
        for c in arm.pose.bones[name].constraints:
            if c.type == "LIMIT_ROTATION" and c.name == mmd.IK_LIMIT_CONSTRAINT:
                c.mute = True
    return muted


def _mute_cancel(arm) -> int:
    """Mute the waist-cancel bones' constraints so the legs follow the hips."""
    muted = 0
    for pb in arm.pose.bones:
        if pb.name.split(".")[0] in mmd.CANCEL_BONES:
            for c in pb.constraints:
                c.mute = True
                muted += 1
    return muted


def import_pmx(path: str | Path, replace: bool = True, morphs: bool = True,
               english: bool = True, physics: bool = False) -> bpy.types.Object:
    """Import a PMX character into the character collection; returns its armature. With
    ``english`` (default), names are translated last (``translate_names``); ``physics``
    also imports the model's rigid bodies and joints."""
    from . import character
    from .body import deform_mesh
    from .pose import reset_pose
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    ensure_addon()
    if replace:
        character.remove_character()
    scene = bpy.context.scene
    coll = bpy.data.collections.new(character.CHARACTER_COLLECTION)
    scene.collection.children.link(coll)
    layer = bpy.context.view_layer.layer_collection.children[coll.name]
    prev = bpy.context.view_layer.active_layer_collection
    bpy.context.view_layer.active_layer_collection = layer
    actions_before = set(bpy.data.actions)
    types = ({"MESH", "ARMATURE"} | ({"MORPHS"} if morphs else set())
             | ({"PHYSICS"} if physics else set()))
    try:
        result = bpy.ops.mmd_tools.import_model(filepath=str(path), types=types, scale=SCALE,
                                                log_level="ERROR")
    finally:
        bpy.context.view_layer.active_layer_collection = prev
    if "FINISHED" not in result:
        raise RuntimeError(f"PMX import failed: {result}")
    coll[character.IMPORTED_ACTIONS_KEY] = [a.name for a in set(bpy.data.actions) - actions_before]
    arm = next((o for o in coll.all_objects if o.type == "ARMATURE"), None)
    if arm is None:
        raise RuntimeError("Imported PMX has no armature")
    skeleton = _skeleton(arm)
    if not mmd.is_character(skeleton):
        raise ValueError(f"{path.name} isn't a humanoid character (a prop or weapon?)")
    hmap = mmd.humanoid_map(skeleton)
    arm[HUMANOID_KEY] = json.dumps(hmap, ensure_ascii=False)
    arm[FOLLOW_KEY] = json.dumps(mmd.follow_map(skeleton), ensure_ascii=False)
    arm[SOURCE_KEY] = str(path)
    arm["wogen_base"] = path.stem
    _mute_ik(arm)
    _mute_cancel(arm)
    reset_pose(arm)
    physics_objs = _physics_objects(coll)
    placed = _physics_placement(arm, physics_objs)
    _pose_chains(arm, hmap, tpose_transforms(arm, hmap))
    transforms = _posed_transforms(arm)
    reset_pose(arm)
    meshes = _model_meshes(coll)
    for obj in meshes:
        deform_mesh(obj, transforms, arm)
    _move_bones(arm, transforms)
    arm[GROUND_KEY] = _ground(arm, meshes)
    arm[SOLES_KEY] = json.dumps(measure_soles(arm, meshes, hmap, json.loads(arm[FOLLOW_KEY])))
    reset_pose(arm)
    if placed:
        shift = Matrix.Translation((0.0, 0.0, arm[GROUND_KEY]))
        _replace_physics(arm, placed, {b: shift @ m for b, m in transforms.items()}, shift)
    if english:
        translate_names(arm, coll)
    return arm


def _model_meshes(coll) -> list:
    """The model's meshes (not mmd_tools' rigid-body shapes, which are meshes too)."""
    return [o for o in coll.all_objects
            if o.type == "MESH" and getattr(o, "mmd_type", "NONE") in ("NONE", "")]


def _physics_objects(coll) -> list:
    return [o for o in coll.all_objects if getattr(o, "mmd_type", "") in ("RIGID_BODY", "JOINT")]


def _physics_placement(arm, objs) -> list[tuple]:
    """(object, bone, evaluated world matrix) of each rigid body and joint, before the rest
    changes. A joint goes with the bone of its first rigid body."""
    if not objs:
        return []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    out = []
    for o in objs:
        if o.mmd_type == "RIGID_BODY":
            bone = o.mmd_rigid.bone
        else:
            rbc = o.rigid_body_constraint
            body = rbc.object1 if rbc is not None else None
            bone = body.mmd_rigid.bone if body is not None else ""
        out.append((o, bone, o.evaluated_get(depsgraph).matrix_world.copy()))
    return out


def _replace_physics(arm, placed, transforms: dict[str, Matrix], default: Matrix) -> None:
    """Move rigid bodies and joints with their bones' rest changes (``transforms``, armature
    space; ``default`` for bones that didn't move) and re-bind their CHILD_OF constraints
    there (the import's binding is to the old rest)."""
    to_arm, from_arm = arm.matrix_world.inverted(), arm.matrix_world
    for o, bone, world in placed:
        o.matrix_world = from_arm @ transforms.get(bone, default) @ to_arm @ world
        for c in o.constraints:
            if c.type == "CHILD_OF":
                c.set_inverse_pending = True
    bpy.context.view_layer.update()


def original_names(arm, kind: str) -> dict[str, str]:
    """{english: original} for ``kind`` ("bones", "morphs", "materials", "objects") of an
    imported model renamed by ``translate_names``; empty for other rigs."""
    raw = arm.get(NAMES_KEY) if arm is not None else None
    return {new: old for old, new in json.loads(raw).get(kind, {}).items()} if raw else {}


def translate_names(arm, coll) -> dict[str, int]:
    """Rename the model's bones, morphs, materials, images and objects to English
    (``wogen.mmd_names``), keeping every reference consistent: Blender carries bone renames
    into vertex groups and constraints; the stored humanoid/follow maps and mmd_tools' own
    name references (morph data, additional-transform bones) are remapped here. The
    original names are stored on the armature (``NAMES_KEY``; mmd_tools keeps them in
    ``name_j`` too). Returns how many names changed per kind."""
    from .. import mmd_names as N
    meshes = _model_meshes(coll)
    root = arm.parent if arm.parent is not None and hasattr(arm.parent, "mmd_root") else None
    mr = root.mmd_root if root is not None else None

    bones = N.unique_names([b.name for b in arm.data.bones], N.translate)
    for old, new in bones.items():
        arm.data.bones[old].name = new
    for pb in arm.pose.bones:
        mb = getattr(pb, "mmd_bone", None)
        if mb is not None:
            for prop in ("additional_transform_bone", "display_connection_bone"):
                value = getattr(mb, prop, "")
                if value in bones:
                    setattr(mb, prop, bones[value])
    for key in (HUMANOID_KEY, FOLLOW_KEY):
        if key in arm:
            arm[key] = json.dumps({k: bones.get(v, v) for k, v in json.loads(arm[key]).items()}
                                  if key == HUMANOID_KEY else
                                  {bones.get(k, k): bones.get(v, v)
                                   for k, v in json.loads(arm[key]).items()})

    keys = {k.name for o in meshes if o.data.shape_keys for k in o.data.shape_keys.key_blocks}
    if mr is not None:
        for kind in ("vertex_morphs", "bone_morphs", "material_morphs", "uv_morphs",
                     "group_morphs"):
            keys |= {m.name for m in getattr(mr, kind, ())}
    morphs = N.unique_names(sorted(keys), N.translate_morph)
    for o in meshes:
        if o.data.shape_keys:
            for k in o.data.shape_keys.key_blocks:
                k.name = morphs.get(k.name, k.name)

    mats = sorted({m.name for o in meshes for m in o.data.materials if m})
    materials = N.unique_names(mats, lambda n: N.translate(n, {**N.BONE_TERMS, **N.MATERIAL_TERMS}))
    for old, new in materials.items():
        bpy.data.materials[old].name = new
    images = {i for o in meshes for m in o.data.materials if m and m.node_tree
              for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image for i in [n.image]}
    for img in images:
        if N.has_foreign(img.name):
            img.name = N.translate(img.name, {**N.BONE_TERMS, **N.MATERIAL_TERMS})

    all_terms = {**N.BONE_TERMS, **N.MATERIAL_TERMS, **N.MODEL_TERMS}
    physics = {o.name for o in _physics_objects(coll)}
    objects = N.unique_names([o.name for o in coll.all_objects],
                             lambda n: N.translate(n, all_terms) if n in physics
                             else N.translate_model(n))
    for o in list(coll.all_objects):
        rigid = getattr(o, "mmd_rigid", None)
        if getattr(o, "mmd_type", "") == "RIGID_BODY" and rigid.bone in bones:
            rigid.bone = bones[rigid.bone]
        if o.name in objects:
            o.name = objects[o.name]

    if mr is not None:
        for kind in ("vertex_morphs", "bone_morphs", "material_morphs", "uv_morphs",
                     "group_morphs"):
            for m in getattr(mr, kind, ()):
                m.name = morphs.get(m.name, m.name)
                for d in getattr(m, "data", ()):
                    for prop, table in (("bone", bones), ("material", materials),
                                        ("related_mesh", objects), ("morph", morphs)):
                        value = getattr(d, prop, None)
                        if isinstance(value, str) and value in table:
                            setattr(d, prop, table[value])
        if N.has_foreign(mr.name):
            mr.name = N.translate_model(mr.name)
    arm[NAMES_KEY] = json.dumps({"bones": bones, "morphs": morphs, "materials": materials,
                                 "objects": objects}, ensure_ascii=False)
    return {"bones": len(bones), "morphs": len(morphs), "materials": len(materials),
            "objects": len(objects), "images": len(images)}


def rest_error(arm) -> float:
    """Largest distance (m) between a mesh's rest vertices and its evaluated (armature-
    deformed) vertices with every bone at rest; ~0 when the rest conversion is consistent."""
    from .character import character_meshes
    from .pose import reset_pose
    reset_pose(arm)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    worst = 0.0
    for obj in character_meshes():
        if obj.data.shape_keys:
            keys = obj.data.shape_keys.key_blocks
            saved = [k.value for k in keys]
            for k in keys[1:]:
                k.value = 0.0
        ev = obj.evaluated_get(depsgraph)
        me = ev.to_mesh()
        n = min(len(me.vertices), len(obj.data.vertices))
        a = np.empty(n * 3, np.float32)
        b = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("co", a) if len(me.vertices) == n else None
        obj.data.vertices.foreach_get("co", b) if len(obj.data.vertices) == n else None
        if len(me.vertices) == len(obj.data.vertices):
            worst = max(worst, float(np.abs(a - b).max(initial=0.0)))
        ev.to_mesh_clear()
        if obj.data.shape_keys:
            for k, v in zip(keys, saved):
                k.value = v
    return worst
