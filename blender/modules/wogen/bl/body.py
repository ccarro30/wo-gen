"""Body proportions and shape by rest-pose retargeting; procedural face shape keys.

``apply_body(params)`` computes one affine transform per bone (rest space), deforms every
character mesh's rest geometry with its own skin weights (linear blend skinning, applied to
each shape key too), then moves the bones to their new rest positions. Because poses, IK and
physics are all defined relative to the rest pose, they keep working. The transforms are
stored on the armature so garments equipped later are fitted the same way.

Per-bone scale kinds (about the bone's head, in the joint-segment frame):
- axial: stretch along the segment (limb/torso length); not inherited by children;
- radial: scale perpendicular to the segment (waist, hips, thighs); not inherited;
- uniform: whole subtree scales (head, bust); inherited by children (hair follows the head).
Children's heads always follow their parent's transform, so stretching a thigh moves the knee.
"""

from __future__ import annotations

import json

import bpy
import numpy as np
from mathutils import Matrix, Vector

from ..body import BodyParams, FaceParams

TRANSFORMS_KEY = "wg_body_transforms"
PARAMS_KEY = "wg_body_params"

# humanoid bone -> humanoid child defining its joint segment
SEGMENT_CHILD = {
    "hips": "spine", "spine": "chest", "chest": "upper_chest", "upper_chest": "neck",
    "neck": "head",
    **{f"{s}_{a}": f"{s}_{b}" for s in ("left", "right") for a, b in (
        ("upper_leg", "lower_leg"), ("lower_leg", "foot"), ("shoulder", "upper_arm"),
        ("upper_arm", "lower_arm"), ("lower_arm", "hand"))},
}


def _scale_specs(p: BodyParams) -> dict[str, dict]:
    """humanoid bone -> {"axial": a, "radial": r} or {"uniform": u}."""
    specs: dict[str, dict] = {}

    def add(bone, kind, value):
        if abs(value - 1.0) > 1e-6:
            specs.setdefault(bone, {})[kind] = value
    for side in ("left", "right"):
        for seg in ("upper_leg", "lower_leg"):
            add(f"{side}_{seg}", "axial", p.leg_length)
        add(f"{side}_upper_leg", "radial", p.thigh)
        for seg in ("upper_arm", "lower_arm"):
            add(f"{side}_{seg}", "axial", p.arm_length)
            add(f"{side}_{seg}", "radial", p.arm_thickness)
        add(f"{side}_shoulder", "axial", p.shoulder_width)
    for seg in ("spine", "chest", "upper_chest"):
        add(seg, "axial", p.torso_length)
    add("spine", "radial", p.waist)
    add("hips", "radial", p.hip_width)
    add("neck", "axial", p.neck_length)
    add("head", "uniform", p.head_scale)
    return specs


def _local_scale(head: Vector, direction: Vector | None, spec: dict) -> Matrix:
    """4x4 scale about ``head``: uniform, or axial/radial in the segment frame."""
    if "uniform" in spec:
        lin = Matrix.Diagonal((spec["uniform"],) * 3)
    else:
        d = direction.normalized()
        ddt = Matrix(((d.x * d.x, d.x * d.y, d.x * d.z),
                      (d.y * d.x, d.y * d.y, d.y * d.z),
                      (d.z * d.x, d.z * d.y, d.z * d.z)))
        a, r = spec.get("axial", 1.0), spec.get("radial", 1.0)
        lin = Matrix.Identity(3) + ddt * (a - 1.0) + (Matrix.Identity(3) - ddt) * (r - 1.0)
    return Matrix.Translation(head) @ lin.to_4x4() @ Matrix.Translation(-head)


def compute_transforms(arm: bpy.types.Object, params: BodyParams) -> tuple[dict, set]:
    """Per-bone affine transforms (armature rest space) and the set of 'uniform' bones."""
    from .pose import humanoid_map
    hmap = humanoid_map(arm)
    by_bone = {hmap[h]: spec for h, spec in _scale_specs(params).items() if h in hmap}
    for b in arm.data.bones:            # bust (non-humanoid VroidStudio bones)
        if b.name.endswith("Bust1") and abs(params.bust - 1.0) > 1e-6:
            by_bone[b.name] = {"uniform": params.bust}
    child_of = {hmap[h]: hmap[c] for h, c in SEGMENT_CHILD.items() if h in hmap and c in hmap}

    transforms: dict[str, Matrix] = {}
    inherit: dict[str, bool] = {}
    for b in sorted(arm.data.bones, key=lambda b: len(b.parent_recursive)):
        head = b.head_local.copy()
        parent = b.parent
        pa = transforms.get(parent.name, Matrix.Identity(4)) if parent else Matrix.Identity(4)
        if parent is not None and inherit.get(parent.name):
            base = pa
        else:
            base = Matrix.Translation((pa @ head) - head)
        spec = by_bone.get(b.name)
        if spec:
            child = child_of.get(b.name)
            direction = (arm.data.bones[child].head_local - head) if child else None
            local = _local_scale(head, direction, spec) if ("uniform" in spec or direction) \
                else Matrix.Identity(4)
        else:
            local = Matrix.Identity(4)
        transforms[b.name] = base @ local
        inherit[b.name] = bool(spec and "uniform" in spec) or bool(parent and inherit.get(parent.name))
    uniform = {n for n, v in inherit.items() if v}
    return transforms, uniform


# ---------------------------------------------------------------- mesh deformation

def deform_mesh(obj: bpy.types.Object, transforms: dict[str, Matrix], arm: bpy.types.Object,
                parent_of: dict[str, str] | None = None) -> int:
    """Apply rest-space linear blend skinning to ``obj`` (all shape keys). Vertex groups that
    aren't bones resolve through ``parent_of`` (garment-rig bones); unweighted vertices stay."""
    to_arm = np.array(arm.matrix_world.inverted() @ obj.matrix_world, dtype=np.float64)
    from_arm = np.linalg.inv(to_arm)
    me = obj.data
    names = {vg.index: vg.name for vg in obj.vertex_groups}

    def resolve(name):
        seen = 0
        while name not in transforms and parent_of and name in parent_of and seen < 64:
            name, seen = parent_of[name], seen + 1
        return transforms.get(name)

    group_mats = {i: resolve(n) for i, n in names.items()}
    group_mats = {i: np.array(m, dtype=np.float64) for i, m in group_mats.items() if m is not None}
    n = len(me.vertices)
    blended = np.zeros((n, 4, 4))
    total = np.zeros(n)
    for v in me.vertices:
        for g in v.groups:
            m = group_mats.get(g.group)
            if m is not None and g.weight > 0.0:
                blended[v.index] += g.weight * m
                total[v.index] += g.weight
    moved = total > 1e-8
    blended[moved] /= total[moved, None, None]
    blended[~moved] = np.eye(4)
    blended = from_arm[None] @ blended @ to_arm[None]   # mesh space -> armature -> back

    def apply(co_flat: np.ndarray) -> np.ndarray:
        co = co_flat.reshape(-1, 3)
        homo = np.concatenate([co, np.ones((len(co), 1))], axis=1)
        out = np.einsum("nij,nj->ni", blended, homo)[:, :3]
        return out.astype(np.float32).ravel()

    co = np.empty(n * 3, dtype=np.float32)
    if me.shape_keys:
        for kb in me.shape_keys.key_blocks:
            kb.data.foreach_get("co", co)
            kb.data.foreach_set("co", apply(co))
        me.shape_keys.key_blocks[0].data.foreach_get("co", co)
    else:
        me.vertices.foreach_get("co", co)
    me.vertices.foreach_set("co", co if me.shape_keys else apply(co))
    me.update()
    return int(moved.sum())


def _move_bones(arm: bpy.types.Object, transforms: dict[str, Matrix], uniform: set[str]) -> None:
    view_layer = bpy.context.view_layer
    prev_active, prev_mode = view_layer.objects.active, arm.mode
    view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        for eb in arm.data.edit_bones:
            m = transforms.get(eb.name)
            if m is None:
                continue
            head, tail = eb.head.copy(), eb.tail.copy()
            roll = eb.roll
            new_head = m @ head
            eb.head = new_head
            eb.tail = (m @ tail) if eb.name in uniform else new_head + (tail - head)
            eb.roll = roll
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        if prev_mode == "POSE":
            bpy.ops.object.mode_set(mode="POSE")
        view_layer.objects.active = prev_active


def apply_body(params: BodyParams) -> str:
    """Retarget the loaded character's rest pose (call right after import, once)."""
    from .character import character_armature, character_meshes
    arm = character_armature()
    if arm.get(PARAMS_KEY):
        raise RuntimeError("Body already applied to this character; re-import to change it")
    if params.is_identity():
        arm[PARAMS_KEY] = json.dumps(params.__dict__)
        return "body: base proportions"
    transforms, uniform = compute_transforms(arm, params)
    from .pose import reset_pose
    reset_pose(arm)
    moved = sum(deform_mesh(obj, transforms, arm) for obj in character_meshes())
    _move_bones(arm, transforms, uniform)
    arm[TRANSFORMS_KEY] = json.dumps({n: [list(r) for r in m] for n, m in transforms.items()})
    arm[PARAMS_KEY] = json.dumps(params.__dict__)
    return f"body applied: {moved} vertices deformed, {len(transforms)} bones moved"


def stored_transforms(arm: bpy.types.Object) -> dict[str, Matrix]:
    raw = arm.get(TRANSFORMS_KEY)
    return {n: Matrix(m) for n, m in json.loads(raw).items()} if raw else {}


def fit_garment(garment: bpy.types.Object, arm: bpy.types.Object, rig: dict | None) -> None:
    """Fit a garment loaded from the library to the current body (and its rig bones)."""
    transforms = stored_transforms(arm)
    if not transforms:
        return
    parent_of = {b["name"]: b["parent"] for b in (rig or {}).get("bones", []) if b["parent"]}
    deform_mesh(garment, transforms, arm, parent_of)


def fit_rig(rig: dict, arm: bpy.types.Object) -> dict:
    """Return a copy of ``rig`` whose bone rest matrices follow the body transforms."""
    transforms = stored_transforms(arm)
    if not transforms or not rig:
        return rig
    parent_of = {b["name"]: b["parent"] for b in rig["bones"] if b["parent"]}

    def resolve(name):
        while name not in transforms and name in parent_of:
            name = parent_of[name]
        return transforms.get(name, Matrix.Identity(4))
    out = json.loads(json.dumps(rig))
    for b in out["bones"]:
        m = Matrix(b["matrix"])
        head = m.translation.copy()
        moved = resolve(b["name"]) @ head
        m.translation = moved
        b["matrix"] = [list(r) for r in m]
    return out


# ---------------------------------------------------------------- face shape keys

FACE_EYE_MATERIALS = ("EyeIris", "EyeWhite", "EyeHighlight", "FaceEyelash", "FaceEyeline")


def _smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


EYE_SCALE = 0.16            # wg_eye_size = 1 scales the eye region by 16 %
EYE_FIX_KEY = "wg_eye_size_applied"


def _eye_falloff(co: np.ndarray, c: np.ndarray, eye_r: float) -> np.ndarray:
    r = np.linalg.norm((co - c)[:, [0, 2]], axis=1)
    front = (co[:, 1] < c[1] + 0.03).astype(np.float64)   # front of the head only
    # Fade out toward the midline so the two eyes never push the nose bridge across it.
    midline = _smoothstep(0.0, 0.6 * abs(c[0]), np.abs(co[:, 0]))
    return (1.0 - _smoothstep(eye_r * 1.05, eye_r * 1.9, r)) * front * midline


def _face_basis(face: bpy.types.Object):
    me = face.data
    basis = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.shape_keys.key_blocks[0].data.foreach_get("co", basis)
    return basis.reshape(-1, 3).astype(np.float64)


def _eye_geometry(face: bpy.types.Object, co: np.ndarray, mats: list[str]):
    """(eye centres by side, eye radius) from the eye materials' vertices."""
    me = face.data
    eye_slots = {i for i, n in enumerate(mats) if any(e in n for e in FACE_EYE_MATERIALS)}
    eye_verts = sorted({v for p in me.polygons if p.material_index in eye_slots for v in p.vertices})
    e = co[eye_verts]
    centers = {s: e[(e[:, 0] > 0) == (s > 0)].mean(axis=0) for s in (1, -1)}
    left_eye = e[e[:, 0] > 0]
    eye_r = float(((left_eye.max(axis=0) - left_eye.min(axis=0)) / 2)[[0, 2]].max())
    return centers, eye_r


def _material_names(face: bpy.types.Object) -> list[str]:
    from . import toon
    return [toon._source_of(m).name if m else "" for m in face.data.materials]


def build_face_keys(face: bpy.types.Object) -> list[str]:
    """Create procedural ``wg_*`` face shape keys (idempotent). Values -1..1."""
    me = face.data
    if me.shape_keys is None:
        face.shape_key_add(name="Basis", from_mix=False)
    keys = me.shape_keys.key_blocks
    co = _face_basis(face)
    mats = _material_names(face)
    centers, eye_r = _eye_geometry(face, co, mats)
    eye_z = float((centers[1][2] + centers[-1][2]) / 2)
    chin_z = float(co[:, 2].min())
    mouth_z = eye_z + 0.70 * (chin_z - eye_z)

    def eye_falloff(c):
        return _eye_falloff(co, c, eye_r)

    shapes: dict[str, np.ndarray] = {}
    d = np.zeros_like(co)
    for s in (1, -1):
        c = centers[s]
        side = (co[:, 0] > 0) == (s > 0)
        d += ((co - c) * EYE_SCALE) * (eye_falloff(c) * side)[:, None]
    shapes["wg_eye_size"] = d
    d = np.zeros_like(co)
    for s in (1, -1):
        side = (co[:, 0] > 0) == (s > 0)
        d[:, 2] += 0.004 * eye_falloff(centers[s]) * side
    shapes["wg_eye_height"] = d
    below = _smoothstep(eye_z, chin_z + 0.25 * (eye_z - chin_z), co[:, 2])   # 0 at eyes -> 1 near jaw
    d = np.zeros_like(co)
    d[:, 0] = co[:, 0] * 0.07 * below
    shapes["wg_face_width"] = d
    chin = _smoothstep(mouth_z, chin_z, co[:, 2])
    d = np.zeros_like(co)
    d[:, 2] = -0.010 * chin
    shapes["wg_chin_length"] = d

    # Brows: only the brow faces move (they're drawn over the skin and through the bangs).
    brow_slots = {i for i, n in enumerate(mats) if "FaceBrow" in n}
    brow = np.zeros(len(co), bool)
    brow[sorted({v for p in me.polygons if p.material_index in brow_slots for v in p.vertices})] = True
    d = np.zeros_like(co)
    d[brow, 2] = 0.006
    shapes["wg_brow_height"] = d
    d = np.zeros_like(co)     # + raises the outer ends (sharper), - the inner ends (softer)
    for s in (1, -1):
        side = brow & ((co[:, 0] > 0) == (s > 0))
        if side.any():
            cx = co[side, 0].mean()
            d[side, 2] = 0.22 * (co[side, 0] - cx) * s
    shapes["wg_brow_tilt"] = d

    # Nose: scale the skin around the nose tip (the frontmost skin point between eyes and mouth).
    skin_slots = {i for i, n in enumerate(mats) if n.endswith("_SKIN") or "_SKIN." in n}
    skin = np.zeros(len(co), bool)
    skin[sorted({v for p in me.polygons if p.material_index in skin_slots for v in p.vertices})] = True
    band = skin & (co[:, 2] > mouth_z) & (co[:, 2] < eye_z) & (np.abs(co[:, 0]) < 0.3 * eye_r + 0.01)
    tip = co[band][np.argmin(co[band, 1])] if band.any() else np.array([0.0, co[:, 1].min(), mouth_z])
    pivot = tip + np.array([0.0, 0.012, 0.005])          # behind and slightly above the tip
    r = np.linalg.norm((co - pivot) / np.array([1.0, 1.0, 0.8]), axis=1)
    d = (co - pivot) * (0.40 * (1.0 - _smoothstep(0.008, 0.017, r)) * skin)[:, None]
    shapes["wg_nose_size"] = d

    # Mouth: widen the mouth (inside and lips) and the skin around it, sideways only.
    mouth_slots = {i for i, n in enumerate(mats) if "FaceMouth" in n}
    mouth_v = sorted({v for p in me.polygons if p.material_index in mouth_slots for v in p.vertices})
    if mouth_v:
        m = co[mouth_v]
        mc = np.array([0.0, m[:, 1].min(), (m[:, 2].min() + m[:, 2].max()) / 2])
        half_w = float(np.abs(m[:, 0]).max())
        r = np.hypot(co[:, 0] / (half_w * 1.6), (co[:, 2] - mc[2]) / (half_w * 0.9))
        # Front only: the mouth interior reaches back near the cheek skin and would poke out.
        front = 1.0 - _smoothstep(mc[1] + 0.006, mc[1] + 0.018, co[:, 1])
        d = np.zeros_like(co)
        d[:, 0] = co[:, 0] * 0.18 * (1.0 - _smoothstep(0.7, 1.0, r)) * front
        shapes["wg_mouth_width"] = d

    for name, delta in shapes.items():
        kb = keys.get(name) or face.shape_key_add(name=name, from_mix=False)
        kb.slider_min, kb.slider_max = -1.0, 1.0
        kb.data.foreach_set("co", (co + delta).astype(np.float32).ravel())
    return list(shapes)


def scale_expressions_to_eyes(face: bpy.types.Object, eye_size: float) -> int:
    """Scale the expression keys' deltas around the eyes to match ``wg_eye_size``.

    ``wg_eye_size`` enlarges the eye region about each eye's centre by (1 + k), so a blink
    delta authored for the base eye must grow by the same factor to close the lids fully.
    The applied value is stored on the mesh, so repeated calls rescale exactly. Returns the
    number of keys changed.
    """
    me = face.data
    old = float(me.get(EYE_FIX_KEY, 0.0))
    if abs(old - eye_size) < 1e-9:
        return 0
    co = _face_basis(face)
    centers, eye_r = _eye_geometry(face, co, _material_names(face))
    k = np.zeros(len(co))
    for s in (1, -1):
        side = (co[:, 0] > 0) == (s > 0)
        k += EYE_SCALE * _eye_falloff(co, centers[s], eye_r) * side
    ratio = ((1.0 + k * eye_size) / (1.0 + k * old))[:, None]
    region = k > 1e-6
    tmp = np.empty(len(co) * 3, dtype=np.float32)
    changed = 0
    for kb in me.shape_keys.key_blocks[1:]:
        if kb.name.startswith("wg_"):
            continue
        kb.data.foreach_get("co", tmp)
        delta = tmp.reshape(-1, 3).astype(np.float64) - co
        if not np.abs(delta[region]).max(initial=0.0) > 1e-7:
            continue
        kb.data.foreach_set("co", (co + delta * ratio).astype(np.float32).ravel())
        changed += 1
    me[EYE_FIX_KEY] = eye_size
    return changed


def apply_face(params: FaceParams) -> str:
    from .face import face_mesh
    face = face_mesh()
    names = build_face_keys(face)
    keys = face.data.shape_keys.key_blocks
    for name in names:
        keys[name].value = getattr(params, name.removeprefix("wg_"))
    scale_expressions_to_eyes(face, params.eye_size)
    return "face: " + ", ".join(f"{n.removeprefix('wg_')}={keys[n].value:+.2f}" for n in names)
