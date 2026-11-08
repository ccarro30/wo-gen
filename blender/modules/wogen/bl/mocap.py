"""Retarget BVH motion capture onto the character (rotation-delta retargeting).

The cgspeed CMU files start with a T-pose frame, and our VRM rest pose is a T-pose too. So for
every mapped joint the motion is the world-space rotation *relative to that T-pose*,
``D = G(frame) * G(T)^-1``, converted from BVH axes (Y up, facing +Z) to ours (Z up, facing
-Y) and applied on top of each bone's rest orientation. Proportions don't matter for rotations;
the hips' travel is scaled by the ratio of hip heights.

Chat usage::

    from wogen.bl import mocap, physics, render
    opts = mocap.apply("happy_walk")                 # catalog name (wogen.bvh.catalog())
    physics.bake(physics.PhysicsSettings(carry=opts["carry"]))
    render.clip(r"...\\out\\happy_walk.mp4", framing="full", follow=opts["follow"])
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from .. import bvh

# BVH (x, y, z) -> ours: X stays (her left), BVH up (Y) -> Z, BVH forward (+Z) -> -Y.
AXES = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
AXES_INV = AXES.transposed()


def _local_rotation(channels: dict[str, float]) -> Matrix:
    m = Matrix.Identity(3)
    for name, value in channels.items():            # listed order = multiplication order
        if name.endswith("rotation"):
            m = m @ Matrix.Rotation(math.radians(value), 3, name[0])
    return m


def _world_rotations(motion: bvh.Motion, frame: int) -> list[Matrix]:
    out: list[Matrix] = []
    for i, joint in enumerate(motion.joints):         # parents always come first in BVH
        local = _local_rotation(motion.channels(i, frame))
        out.append(local if joint.parent is None else out[joint.parent] @ local)
    return out


def _root_position(motion: bvh.Motion, frame: int) -> Vector:
    c = motion.channels(0, frame)
    return Vector((c.get("Xposition", 0.0), c.get("Yposition", 0.0), c.get("Zposition", 0.0)))


def retarget(motion: bvh.Motion, frames: list[int], armature=None, start: int = 1,
             face_camera: bool = True, in_place: bool = False, rest_frame: int = 0) -> int:
    """Key the character from ``motion`` at source ``frames`` (one per output frame, from
    ``start``). ``face_camera`` turns the motion so she starts facing the camera (-Y) at the
    origin; ``in_place`` removes horizontal travel. Returns the last keyed frame."""
    from .character import character_armature
    from .outfit import shoe_lift
    from .pose import humanoid_map, reset_pose
    arm = armature or character_armature()
    hmap = humanoid_map(arm)
    reset_pose(arm)
    driven = {}                                       # blender bone -> bvh joint index
    for joint, human in bvh.CMU_TO_HUMANOID.items():
        if human in hmap:
            try:
                driven[hmap[human]] = motion.index(joint)
            except StopIteration:
                pass
    # Target bones in hierarchy order (parents first), limited to the driven ones' ancestry.
    order = [b for b in arm.data.bones if b.name in driven or
             any(c.name in driven for c in b.children_recursive)]
    rest = {b.name: b.matrix_local.to_3x3() for b in order}

    t_world = _world_rotations(motion, rest_frame)
    t_inv = {i: t_world[i].inverted() for i in driven.values()}
    hips_joint = motion.index("Hips")
    hips_bone = hmap["hips"]
    scale = (arm.data.bones[hips_bone].head_local.z /
             max(_root_position(motion, rest_frame).y, 1e-6))
    lift = shoe_lift()

    def deltas(frame: int, align: Matrix) -> dict[str, Matrix]:
        world = _world_rotations(motion, frame)
        return {bone: align @ AXES @ (world[i] @ t_inv[i]) @ AXES_INV for bone, i in driven.items()}

    align = Matrix.Identity(3)
    origin = AXES @ _root_position(motion, frames[0])
    if face_camera:
        forward = deltas(frames[0], align)[hips_bone] @ Vector((0.0, -1.0, 0.0))
        yaw = math.atan2(forward.x, -forward.y)        # 0 when already facing -Y
        align = Matrix.Rotation(yaw, 3, "Z")
    rest_height = (AXES @ _root_position(motion, rest_frame)).z

    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    previous: dict[str, Quaternion] = {}
    moves: list[Vector] = []
    frame_out = start
    for src in frames:
        d = deltas(src, align)
        world: dict[str, Matrix] = {}
        for bone in order:
            parent = bone.parent.name if bone.parent and bone.parent.name in world else None
            world[bone.name] = d.get(bone.name, world[parent] if parent else Matrix.Identity(3))
            if bone.name not in d:
                continue
            parent_delta = world[parent] if parent else Matrix.Identity(3)
            basis = rest[bone.name].inverted() @ parent_delta.inverted() @ d[bone.name] @ rest[bone.name]
            q = basis.to_quaternion()
            if bone.name in previous and previous[bone.name].dot(q) < 0:
                q.negate()
            previous[bone.name] = q
            pb = arm.pose.bones[bone.name]
            pb.rotation_quaternion = q
            pb.keyframe_insert("rotation_quaternion", frame=frame_out)
        # Hips travel: scaled, relative to the first frame horizontally and the T-pose height.
        p = AXES @ _root_position(motion, src)
        move = align @ Vector((p.x - origin.x, p.y - origin.y, 0.0)) * scale
        if in_place:
            move.x = move.y = 0.0
        move.z = (p.z - rest_height) * scale + lift
        moves.append(move)
        frame_out += 1
    _key_hips(arm, hips_bone, rest[hips_bone], moves, start)
    drop = _floor_offset(arm, hmap, start, frame_out - 1, lift)
    for m in moves:
        m.z -= drop
    _key_hips(arm, hips_bone, rest[hips_bone], moves, start)
    return frame_out - 1


FLOOR_PERCENTILE = 0.05     # share of frames whose lowest foot may dip slightly below the floor


def _key_hips(arm, bone: str, rest: Matrix, moves: list[Vector], start: int) -> None:
    pb = arm.pose.bones[bone]
    inv = rest.inverted()
    for i, move in enumerate(moves):
        pb.location = inv @ move
        pb.keyframe_insert("location", frame=start + i)


def _floor_offset(arm, hmap, start: int, end: int, lift: float) -> float:
    """How far the clip floats: the low percentile of the per-frame lowest foot joint above
    its rest height (contacts land on the floor; real airborne moments stay airborne)."""
    names = [hmap[n] for n in ("left_foot", "right_foot", "left_toes", "right_toes") if n in hmap]
    rest_min = min(arm.data.bones[n].head_local.z for n in names)
    scene = bpy.context.scene
    lows = []
    for f in range(start, end + 1):
        scene.frame_set(f)
        lows.append(min((arm.matrix_world @ arm.pose.bones[n].head).z for n in names))
    lows.sort()
    low = lows[min(len(lows) - 1, int(len(lows) * FLOOR_PERCENTILE))]
    return low - (rest_min + lift)       # the same floor target as pose.ground_feet


def clear_garments(start: int, end: int, armature=None) -> int:
    """Per frame, swing arms out of skirts/dresses about the shoulder (``wogen.bl.clearance``)
    and key the corrected upper arms. The capture actor wore no skirt, so hands at the sides or
    on the hips would otherwise sink into the cloth. Returns the number of frames corrected."""
    from . import clearance
    from .character import character_armature
    from .pose import humanoid_map
    arm = armature or character_armature()
    hmap = humanoid_map(arm)
    scene = bpy.context.scene
    corrected = 0
    for f in range(start, end + 1):
        scene.frame_set(f)
        done = clearance.clear_arms(arm, hmap)
        for side in ("left", "right"):
            if done.get(side):
                arm.pose.bones[hmap[f"{side}_upper_arm"]].keyframe_insert("rotation_quaternion", frame=f)
        corrected += bool(done)
    return corrected


def apply(name: str, start_s: float = 0.0, end_s: float | None = None, fps: int = 24,
          face_camera: bool = True, in_place: bool = False, expression: str | None = "smile_soft",
          clear: bool = True) -> dict:
    """Load catalog clip ``name`` (or a .bvh path), retarget ``start_s``..``end_s`` seconds at
    ``fps`` from frame 1, set the scene range. ``clear`` keeps arms out of skirts (about 0.2 s
    per frame). Returns clip options for physics/render."""
    from . import anim
    from .character import character_armature
    from .face import expression as set_expression
    motion = bvh.load(bvh.clip_path(name))
    frames = bvh.sample_frames(motion, fps, start_s, end_s)
    anim.clear()
    arm = character_armature()
    end = retarget(motion, frames, arm, face_camera=face_camera, in_place=in_place)
    if expression:
        set_expression(expression, frame=1)
    scene = bpy.context.scene
    scene.render.fps = fps
    scene.frame_start, scene.frame_end = 1, end
    if clear:
        clear_garments(1, end, arm)
    scene.frame_set(1)
    return {"follow": not in_place, "carry": 0.85, "substeps": 2}
