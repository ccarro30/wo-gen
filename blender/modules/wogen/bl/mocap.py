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

from .. import bvh, footlock

# BVH (x, y, z) -> ours: X stays (her left), BVH up (Y) -> Z, BVH forward (+Z) -> -Y.
AXES = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
AXES_INV = AXES.transposed()
TRAVEL_ALIGN = 0.8        # m: clips travelling further than this are turned to walk at the camera


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
             face_camera: bool = True, in_place: bool = False, rest_frame: int = 0,
             offset: tuple[float, float] = (0.0, 0.0)) -> int:
    """Key the character from ``motion`` at source ``frames`` (one per output frame, from
    ``start``). ``face_camera`` turns the motion so she starts facing the camera (-Y);
    she starts at ``offset`` (the hips' horizontal offset from rest, as ``hips_location``);
    ``in_place`` removes horizontal travel. Returns the last keyed frame."""
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
        # Travelling clips: head toward the camera; others: start facing it.
        travel = AXES @ _root_position(motion, frames[-1]) - origin
        travel.z = 0.0
        if travel.length * scale > TRAVEL_ALIGN:
            forward = travel.normalized()
        else:
            forward = deltas(frames[0], align)[hips_bone] @ Vector((0.0, -1.0, 0.0))
        yaw = math.atan2(forward.x, -forward.y)        # 0 when already facing -Y
        align = Matrix.Rotation(-yaw, 3, "Z")          # turn that direction onto -Y
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
        move.x += offset[0]
        move.y += offset[1]
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


HEEL_BACK = 0.02          # m: the heel's sole point sits this far behind the ankle joint
TOE_AHEAD = 0.04          # m: the toe tip sits this far ahead of the ball (toes joint)


def _sole_locals(arm, hmap, side: str) -> dict[str, tuple[str, Vector]]:
    """Heel and toe-tip points on the sole, as (bone, bone-local offset). At rest the sole is
    on the floor (z = 0); posed, ``pb.matrix @ offset`` follows the foot's roll."""
    out = {}
    for key, name, dy in (("heel", "foot", HEEL_BACK), ("toe", "toes", -TOE_AHEAD)):
        bone = arm.data.bones[hmap[f"{side}_{name}"]]
        point = Vector((bone.head_local.x, bone.head_local.y + dy, 0.0))
        out[key] = (bone.name, bone.matrix_local.inverted() @ point)
    return out


def _floor_offset(arm, hmap, start: int, end: int, lift: float) -> float:
    """How far the clip floats: the low percentile of the per-frame lowest sole point (heels
    and toe tips) above the floor. Contacts land on the floor; real airborne moments stay up."""
    soles = [p for side in ("left", "right") for p in _sole_locals(arm, hmap, side).values()]
    scene = bpy.context.scene
    lows = []
    for f in range(start, end + 1):
        scene.frame_set(f)
        lows.append(min((arm.pose.bones[b].matrix @ off).z for b, off in soles))
    lows.sort()
    low = lows[min(len(lows) - 1, int(len(lows) * FLOOR_PERCENTILE))]
    return low - lift                    # soles rest at z = 0, raised by the shoes' lift


def _foot_samples(arm, hmap, side: str, start: int, end: int) -> list[dict]:
    """Per frame (armature space): sole heel and toe-tip points, ankle, foot rotation, hip
    and knee positions."""
    scene = bpy.context.scene
    pb = arm.pose.bones
    foot = pb[hmap[f"{side}_foot"]]
    knee = pb[hmap[f"{side}_lower_leg"]]
    hip = pb[hmap[f"{side}_upper_leg"]]
    soles = _sole_locals(arm, hmap, side)
    out = []
    for f in range(start, end + 1):
        scene.frame_set(f)
        sample = {k: pb[b].matrix @ off for k, (b, off) in soles.items()}
        sample.update(ankle=foot.head.copy(), rot=foot.matrix.to_quaternion(),
                      knee=knee.head.copy(), hip=hip.head.copy())
        out.append(sample)
    return out


def lock_feet(start: int, end: int, armature=None) -> dict[str, float]:
    """Remove foot sliding: hold planted feet in place (``wogen.footlock``) and re-solve
    each leg with two-bone IK, keeping the captured knee direction and foot rotation. The
    actor's proportions differ from hers, so retargeted feet otherwise skate a little.
    Returns, per side, the largest correction applied (m)."""
    from .character import character_armature
    from .outfit import shoe_lift
    from .pose import CHAIN_BONES, humanoid_map, reach
    arm = armature or character_armature()
    hmap = humanoid_map(arm)
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base
    lift = shoe_lift()
    result = {}
    plans = {}
    for side in ("left", "right"):
        samples = _foot_samples(arm, hmap, side, start, end)
        offsets = footlock.contact_offsets(
            [{k: tuple(sample[k]) for k in ("heel", "toe")} for sample in samples], lift, fps)
        plans[side] = (samples, [Vector((dx, dy, 0.0)) for dx, dy in offsets])
        result[side] = max((o.length for o in plans[side][1]), default=0.0)
    foot_rest = {side: arm.data.bones[hmap[f"{side}_foot"]].matrix_local.to_quaternion()
                 for side in ("left", "right")}
    for i, f in enumerate(range(start, end + 1)):
        todo = [s for s in ("left", "right") if plans[s][1][i].length > 1e-5]
        if not todo:
            continue
        scene.frame_set(f)
        for side in todo:
            s, offset = plans[side][0][i], plans[side][1][i]
            line = (s["ankle"] - s["hip"]).normalized()
            pole = (s["knee"] - s["hip"]) - line * (s["knee"] - s["hip"]).dot(line)
            delta = (s["rot"] @ foot_rest[side].inverted()).to_euler("XYZ")
            reach(f"{side}_foot", s["ankle"] + offset, pole, arm, hmap,
                  orient=[math.degrees(a) for a in delta])
            for name in CHAIN_BONES[f"{side}_foot"]:
                arm.pose.bones[hmap[name]].keyframe_insert("rotation_quaternion", frame=f)
    return result


def foot_slide(start: int, end: int, armature=None) -> dict[str, float]:
    """Diagnostic: skating per foot, the total horizontal travel (m) of each sole point
    (heel, toe tip) while it touches the floor. Rolling over the heel or toe moves neither."""
    from .character import character_armature
    from .outfit import shoe_lift
    from .pose import humanoid_map
    arm = armature or character_armature()
    hmap = humanoid_map(arm)
    lift = shoe_lift()
    out = {}
    for side in ("left", "right"):
        samples = _foot_samples(arm, hmap, side, start, end)
        total = 0.0
        for a, b in zip(samples, samples[1:]):
            for k in ("heel", "toe"):
                if max(a[k].z, b[k].z) - lift < footlock.SKATE_HEIGHT:
                    total += Vector((b[k].x - a[k].x, b[k].y - a[k].y)).length
        out[side] = total
    return out


def animate_fingers(start: int, end: int, armature=None) -> dict[str, float]:
    """Key procedural finger motion (``wogen.hands``): open for raised or fast gestures, loose
    fists when running, relaxed otherwise, with a slow drift. Returns the peak open amount
    per side (a quick sanity check)."""
    from mathutils import Euler

    from .. import hands
    from .character import character_armature
    from .pose import humanoid_map
    arm = armature or character_armature()
    hmap = humanoid_map(arm)
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base
    pb = arm.pose.bones
    chest, head, hips = (pb[hmap[n]] for n in ("upper_chest", "head", "hips"))
    samples = {"left": [], "right": []}
    body = []
    for f in range(start, end + 1):
        scene.frame_set(f)
        body.append(hips.head.copy())
        for side in samples:
            hand_pos = pb[hmap[f"{side}_hand"]].head
            span = max(head.head.z - chest.head.z, 1e-3)
            samples[side].append(((hand_pos.z - chest.head.z) / span, hand_pos - chest.head))
    body_speed = [0.0] + [Vector((b.x - a.x, b.y - a.y)).length * fps for a, b in zip(body, body[1:])]
    peaks = {}
    rest = {n: pb[hmap[n]].bone.matrix_local.to_quaternion() for n in hands.FINGER_BONES if n in hmap}
    plans = {}
    for side, rows in samples.items():
        heights = [h for h, _ in rows]
        rel = [p for _, p in rows]
        speed = [0.0] + [(b - a).length * fps for a, b in zip(rel, rel[1:])]
        plans[side] = hands.openness(heights, speed, body_speed, fps)
        peaks[side] = max(o for o, _ in plans[side])
    for i, f in enumerate(range(start, end + 1)):
        t = (f - start) / fps
        for side in ("left", "right"):
            o, r = plans[side][i]
            for name, (x, y, z) in hands.finger_pose(side, o, r, t).items():
                if name not in rest:
                    continue
                bone = pb[hmap[name]]
                delta = Euler((math.radians(x), math.radians(y), math.radians(z)), "XYZ").to_quaternion()
                bone.rotation_mode = "QUATERNION"
                bone.rotation_quaternion = rest[name].inverted() @ delta @ rest[name]
                bone.keyframe_insert("rotation_quaternion", frame=f)
    return peaks


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


def segment(name: str, start: int = 1, root: tuple[float, float] = (0.0, 0.0),
            start_s: float = 0.0, end_s: float | None = None, fps: int = 24,
            face_camera: bool = True, in_place: bool = False,
            expression: str | None = "smile_soft", clear: bool = True, lock: bool = True,
            fingers: bool = True) -> tuple[int, tuple[float, float]]:
    """Key catalog clip ``name`` (or a .bvh path) from frame ``start``, beginning at floor
    offset ``root``, without clearing other animation (chains use this). ``lock`` stops
    planted feet skating (``lock_feet``); ``clear`` keeps arms out of skirts (each about
    0.15 s per frame); ``fingers`` animates the hands (the capture has no finger data).
    Returns (last frame, where she ends on the floor)."""
    from .character import character_armature
    from .face import expression as set_expression
    from .pose import humanoid_map
    motion = bvh.load(bvh.clip_path(name))
    frames = bvh.sample_frames(motion, fps, start_s, end_s)
    arm = character_armature()
    scene = bpy.context.scene
    scene.render.fps = fps
    end = retarget(motion, frames, arm, start=start, face_camera=face_camera,
                   in_place=in_place, offset=root)
    for f in (start, end):                     # presets key the ground offset; mocap has none
        arm.location.z = 0.0
        arm.keyframe_insert("location", index=2, frame=f)
    if expression:
        set_expression(expression, frame=start)
    if lock and not in_place:
        lock_feet(start, end, arm)
    if fingers:
        animate_fingers(start, end, arm)
    if clear:
        clear_garments(start, end, arm)
    hips = arm.pose.bones[humanoid_map(arm)["hips"]]
    scene.frame_set(end)
    move = hips.bone.matrix_local.to_3x3() @ hips.location
    return end, (move.x, move.y)


def apply(name: str, start_s: float = 0.0, end_s: float | None = None, fps: int = 24,
          face_camera: bool = True, in_place: bool = False, expression: str | None = "smile_soft",
          clear: bool = True, lock: bool = True, fingers: bool = True) -> dict:
    """Clear the animation and key one clip from frame 1 (see ``segment``); set the scene
    range. Returns clip options for physics/render."""
    from . import anim
    anim.clear()
    end, _ = segment(name, 1, (0.0, 0.0), start_s, end_s, fps, face_camera, in_place,
                     expression, clear, lock, fingers)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, end
    scene.frame_set(1)
    return {"follow": not in_place, "carry": 0.85, "substeps": 2}
