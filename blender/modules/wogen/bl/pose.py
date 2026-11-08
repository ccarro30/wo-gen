"""Apply/read poses on VRM characters (see ``wogen.poses`` for the format and axis conventions).

Chat usage::

    from wogen.bl import pose
    pose.apply_pose("peace")
    pose.apply_pose(["idle", "hand:peace:right"])
    pose.apply_pose({"head": (6, 8, 0)}, reset=False)      # tweak on top of the current pose
    pose.save_pose("my_pose")                              # current pose -> assets/poses/my_pose.toml
"""

from __future__ import annotations

import math

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from ..paths import ASSETS_DIR
from ..poses import (HIPS_LOCATION, IK_CHAINS, IK_PREFIX, REST_PREFIX, Pose,  # noqa: F401
                     PoseSpec, dump_pose, list_poses, resolve_pose)

POSES_DIR = ASSETS_DIR / "poses"
FOOT_BONES = ("left_foot", "right_foot", "left_toes", "right_toes")


def _armature(armature: bpy.types.Object | None = None) -> bpy.types.Object:
    if armature is not None:
        return armature
    from .character import character_armature
    arm = character_armature()
    if arm is None:
        raise RuntimeError("No character loaded")
    return arm


def humanoid_map(armature: bpy.types.Object | None = None) -> dict[str, str]:
    """VRM humanoid name -> Blender bone name (from the VRM add-on's humanoid data)."""
    arm = _armature(armature)
    bones = arm.data.vrm_addon_extension.vrm1.humanoid.human_bones
    out = {}
    for prop in bones.bl_rna.properties:
        item = getattr(bones, prop.identifier, None)
        node = getattr(item, "node", None)
        if node is not None and node.bone_name:
            out[prop.identifier] = node.bone_name
    return out


def _rest_rotation(bone: bpy.types.Bone) -> Quaternion:
    return bone.matrix_local.to_quaternion()


def reset_pose(armature: bpy.types.Object | None = None) -> None:
    arm = _armature(armature)
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()   # so later pb.matrix reads see the reset pose


def apply_pose(spec: PoseSpec = "a_pose", reset: bool = True, frame: int | None = None,
               ground: bool = True, armature: bpy.types.Object | None = None,
               clear: bool = True, settle: bool = True) -> Pose:
    """Apply a pose. ``reset`` clears other bones first (eyes keep their gaze);
    ``frame`` keyframes the posed bones; ``ground`` keeps the feet on the floor; ``clear``
    moves arms out of skirts and dresses (``wogen.bl.clearance``); ``settle`` drapes skirts
    around the legs for unkeyed (still) poses (``physics.settle``; clips bake instead)."""
    arm = _armature(armature)
    pose = resolve_pose(spec, POSES_DIR)
    hmap = humanoid_map(arm)
    rotations = {k: v for k, v in pose.items()
                 if k != HIPS_LOCATION and not k.startswith(IK_PREFIX)}
    iks = {k[len(IK_PREFIX):]: v for k, v in pose.items() if k.startswith(IK_PREFIX)}
    unknown = [n for n in rotations if n not in hmap]
    unknown += [v["target"] for v in iks.values()
                if v["target"].removeprefix(REST_PREFIX) not in hmap]
    unknown += [chain for chain in iks if chain not in IK_CHAINS]
    if unknown:
        raise KeyError(f"Unknown humanoid bones / IK chains {unknown}")
    if reset:
        eyes = {hmap.get(n) for n in ("left_eye", "right_eye")}
        for pb in arm.pose.bones:
            if pb.name not in eyes:
                pb.matrix_basis = Matrix.Identity(4)
        arm.location.z = 0.0
    for name, (x, y, z) in rotations.items():
        pb = arm.pose.bones[hmap[name]]
        rest = _rest_rotation(pb.bone)
        delta = Euler((math.radians(x), math.radians(y), math.radians(z)), "XYZ").to_quaternion()
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = rest.inverted() @ delta @ rest
    hips_offset = pose.get(HIPS_LOCATION)
    if hips_offset is not None:
        pb = arm.pose.bones[hmap["hips"]]
        pb.location = _rest_rotation(pb.bone).inverted() @ Vector(hips_offset)
    bpy.context.view_layer.update()
    # Feet first (they follow the hips), then hands (which may target knees).
    hand_targets = {}
    for chain in sorted(iks, key=lambda c: (not c.endswith("_foot"), c)):
        entry = iks[chain]
        anchor = _anchor(arm, hmap, entry["target"])
        orient = entry.get("orient", (0.0, 0.0, 0.0) if chain.endswith("_foot") else None)
        target = anchor + Vector(entry["offset"])
        reach(chain, target, entry["pole"], arm, hmap, orient)
        if chain.endswith("_hand"):
            hand_targets[chain.removesuffix("_hand")] = (target, entry["pole"], orient)
    if settle and frame is None:              # drape skirts first, then clear arms from them
        from .physics import settle as settle_skirts
        settle_skirts()
    if clear:
        from .clearance import clear_arms
        clear_arms(arm, hmap, hand_targets)
    if ground:
        ground_feet(arm)
    if frame is not None:
        # A reset pose defines every humanoid bone, so key them all (otherwise bones absent
        # from this pose would keep interpolating from earlier keys).
        keyed = {n for n in hmap if n not in ("left_eye", "right_eye")} if reset else set(rotations)
        for chain in iks:
            keyed |= set(CHAIN_BONES[chain])
        keyed |= {"left_upper_arm", "right_upper_arm"} & set(hmap)   # clearance may move them
        for name in keyed:
            arm.pose.bones[hmap[name]].rotation_mode = "QUATERNION"
            arm.pose.bones[hmap[name]].keyframe_insert("rotation_quaternion", frame=frame)
        hips = arm.pose.bones[hmap["hips"]]
        hips.keyframe_insert("location", frame=frame)
        arm.keyframe_insert("location", index=2, frame=frame)
    return pose


def _parent_delta(pb: bpy.types.PoseBone) -> Quaternion:
    """Accumulated pose rotation of the parent (armature space, relative to rest)."""
    if pb.parent is None:
        return Quaternion()
    return pb.parent.matrix.to_quaternion() @ _rest_rotation(pb.parent.bone).inverted()


def aim(pb: bpy.types.PoseBone, child_rest_head: Vector, direction: Vector) -> None:
    """Rotate ``pb`` (minimal rotation) so its joint segment points along ``direction``.

    The joint segment is head -> ``child_rest_head`` in rest pose; it doesn't rely on the
    bone's own Y axis (VRM imports orient bones arbitrarily).
    """
    rest_vec = child_rest_head - pb.bone.head_local
    local_dir = _parent_delta(pb).inverted() @ direction
    delta = rest_vec.rotation_difference(local_dir)
    rest = _rest_rotation(pb.bone)
    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = rest.inverted() @ delta @ rest
    bpy.context.view_layer.update()


CHAIN_BONES = {
    f"{side}_{end}": (f"{side}_upper_{limb}", f"{side}_lower_{limb}", f"{side}_{end}")
    for side in ("left", "right") for end, limb in (("hand", "arm"), ("foot", "leg"))
}


def _anchor(arm: bpy.types.Object, hmap: dict, target: str) -> Vector:
    """Posed head of a humanoid bone, or its rest head for ``rest:<bone>``."""
    if target.startswith(REST_PREFIX):
        return arm.data.bones[hmap[target[len(REST_PREFIX):]]].head_local.copy()
    return arm.pose.bones[hmap[target]].head.copy()


def orient_bone(pb: bpy.types.PoseBone, orient_deg) -> None:
    """Set the bone's absolute (accumulated) rotation relative to rest, in armature axes."""
    target = Euler([math.radians(c) for c in orient_deg], "XYZ").to_quaternion()
    local = _parent_delta(pb).inverted() @ target
    rest = _rest_rotation(pb.bone)
    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = rest.inverted() @ local @ rest
    bpy.context.view_layer.update()


def reach(chain: str, target: Vector, pole=(0.0, 0.0, -1.0),
          armature: bpy.types.Object | None = None, hmap: dict | None = None,
          orient=None) -> float:
    """Analytic two-bone IK: put the end of ``chain`` (``left_hand``, ``right_foot``, ...;
    a bare 'left'/'right' means the hand) at ``target`` (armature space).

    ``pole`` is the direction the elbow/knee should point; ``orient`` optionally fixes the
    end bone's absolute orientation. Returns the residual distance (m), > 0 when the target
    is out of reach.
    """
    arm = _armature(armature)
    hmap = hmap or humanoid_map(arm)
    if chain in ("left", "right"):
        chain = f"{chain}_hand"
    upper_name, lower_name, end_name = CHAIN_BONES[chain]
    upper = arm.pose.bones[hmap[upper_name]]
    lower = arm.pose.bones[hmap[lower_name]]
    hand_pb = arm.pose.bones[hmap[end_name]]
    a = (lower.bone.head_local - upper.bone.head_local).length
    b = (hand_pb.bone.head_local - lower.bone.head_local).length
    shoulder = upper.head.copy()
    to_target = Vector(target) - shoulder
    dist = max(abs(a - b) + 1e-4, min(to_target.length, a + b - 1e-4))
    u = to_target.normalized()
    p = Vector(pole) - u * Vector(pole).dot(u)
    if p.length < 1e-6:
        p = Vector((0.0, 0.0, -1.0)) - u * u.z
    p.normalize()
    x = (a * a - b * b + dist * dist) / (2 * dist)
    h = math.sqrt(max(a * a - x * x, 0.0))
    elbow = shoulder + u * x + p * h
    aim(upper, lower.bone.head_local, elbow - shoulder)
    aim(lower, hand_pb.bone.head_local, Vector(target) - lower.head)
    if orient is not None:
        orient_bone(hand_pb, orient)
    return (hand_pb.head - Vector(target)).length


def current_pose(armature: bpy.types.Object | None = None, min_angle: float = 0.05) -> Pose:
    """Read the current pose back into the canonical format (inverse of ``apply_pose``)."""
    arm = _armature(armature)
    out: Pose = {}
    for name, bone_name in humanoid_map(arm).items():
        pb = arm.pose.bones[bone_name]
        rest = _rest_rotation(pb.bone)
        delta = rest @ pb.matrix_basis.to_quaternion() @ rest.inverted()
        e = delta.to_euler("XYZ")
        deg = tuple(round(math.degrees(c), 2) for c in e)
        if max(abs(c) for c in deg) >= min_angle:
            out[name] = deg
    hips = arm.pose.bones[humanoid_map(arm)["hips"]]
    if hips.location.length > 1e-4:
        loc = _rest_rotation(hips.bone) @ hips.location
        out[HIPS_LOCATION] = tuple(round(c, 4) for c in loc)
    return out


def save_pose(name: str, description: str = "", armature: bpy.types.Object | None = None) -> str:
    """Save the current pose to ``assets/poses/<name>.toml`` (usable by name afterwards)."""
    POSES_DIR.mkdir(parents=True, exist_ok=True)
    path = POSES_DIR / f"{name}.toml"
    path.write_text(dump_pose(current_pose(armature), description), encoding="utf-8")
    return str(path)


def ground_feet(armature: bpy.types.Object | None = None) -> float:
    """Shift the armature vertically so the lowest foot joint is at its rest height, plus the
    lift the equipped shoes need (heels; see ``outfit.shoe_lift``)."""
    from .outfit import shoe_lift
    arm = _armature(armature)
    hmap = humanoid_map(arm)
    names = [hmap[n] for n in FOOT_BONES if n in hmap]
    if not names:
        return 0.0
    rest_min = min(arm.data.bones[n].head_local.z for n in names)
    posed_min = min((arm.matrix_world @ arm.pose.bones[n].head).z for n in names)
    dz = rest_min + shoe_lift() - posed_min
    arm.location.z += dz
    bpy.context.view_layer.update()
    return dz


def relax_arms(armature: bpy.types.Object | None = None, degrees: float = 68.0) -> None:
    """Back-compat helper: A-pose arms."""
    apply_pose({"left_upper_arm": (0, degrees, 0), "right_upper_arm": (0, -degrees, 0)},
               reset=False, armature=armature)


def solve_thumb(curls: dict[str, tuple[float, float, float]], over: list[str],
                armature: bpy.types.Object | None = None, samples: int = 6000,
                seed: int = 1, palm: float = 0.012, segment: int = 1,
                along: float = 0.5) -> tuple[tuple[int, int, int], ...]:
    """Solve a folded thumb for a hand shape: eulers (left-side convention, as in
    ``wogen.poses.hand(thumb=...)``) that rest the thumb tip on the palm side of the middle
    segments of the curled fingers in ``over`` (e.g. ``["ring"]`` for a peace sign).
    ``palm`` is how far below the finger (toward the palm) the tip rests; ``segment``
    (0 proximal, 1 intermediate) and ``along`` (0..1) pick the spot on the finger. A relaxed
    hand uses ``over=["index"], segment=0, along=0.8, palm=0.018`` (tip beside the index).

    Forward kinematics from the rest matrices (no scene changes): random search, then
    coordinate descent. Penalizes large angles and the thumb passing the back of the hand.
    """
    import random
    arm = _armature(armature)
    hmap = humanoid_map(arm)
    bones = arm.data.bones
    rest = {n: bones[hmap[n]].matrix_local for n in hmap if n.startswith("left_")}

    def basis(n, e):
        r = rest[n].to_quaternion()
        q = r.inverted() @ Euler([math.radians(a) for a in e], "XYZ").to_quaternion() @ r
        return q.to_matrix().to_4x4()

    def chain(names, eulers):
        m, prev, out = rest["left_hand"], "left_hand", []
        for n, e in zip(names, eulers):
            m = m @ (rest[prev].inverted() @ rest[n]) @ basis(n, e)
            out.append(m)
            prev = n
        return out

    def middle_of(finger):
        segs = [f"left_{finger}_{s}" for s in ("proximal", "intermediate", "distal")]
        m = chain(segs, [(0.0, a, 0.0) for a in curls[finger]])[segment]
        return m @ Vector((0.0, bones[hmap[segs[segment]]].length * along, 0.0))
    palm_down = Vector((0.0, 0.0, -palm))      # T-pose palms face down
    target = sum((middle_of(f) for f in over), Vector()) / len(over) + palm_down
    back_z = rest["left_hand"].translation.z + 0.005
    thumb = [f"left_thumb_{s}" for s in ("metacarpal", "proximal", "distal")]
    tip_len = bones[hmap[thumb[2]]].length

    def cost(p):
        ms = chain(thumb, [p[0:3], p[3:6], (0.0, p[6], p[7])])
        tip = ms[2] @ Vector((0.0, tip_len, 0.0))
        joints = [m.translation for m in ms] + [tip]
        through = sum(max(0.0, j.z - back_z) for j in joints)
        return (tip - target).length + 2.0 * through + 0.00008 * sum(abs(a) for a in p)

    rng = random.Random(seed)
    best_p = min(([rng.uniform(-60, 60) for _ in range(8)] for _ in range(samples)), key=cost)
    best_c, step = cost(best_p), 8.0
    while step > 0.25:
        improved = False
        for i in range(8):
            for d in (-step, step):
                q = list(best_p)
                q[i] = max(-90.0, min(90.0, q[i] + d))
                c = cost(q)
                if c < best_c:
                    best_p, best_c, improved = q, c, True
        if not improved:
            step /= 2
    p = [round(x) for x in best_p]
    return (tuple(p[0:3]), tuple(p[3:6]), (0, p[6], p[7]))
