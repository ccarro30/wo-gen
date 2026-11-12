"""Keyframed motion built from library poses and expressions.

Chat usage::

    from wogen.bl import anim
    anim.clear()
    anim.sequence([(1, "idle", "neutral"), (24, "wave", "happy"), (48, "idle", "smile_soft")])
    anim.preset("look_around")

Presets and motion generators live in ``wogen.motions`` (pure, testable without Blender).
"""

from __future__ import annotations

import bpy

from ..motions import PRESET_OPTIONS, PRESETS, build, walk_keys  # noqa: F401 - re-exported
from .pose import apply_pose


def channelbag(obj: bpy.types.ID, create: bool = False):
    """The F-curve container for ``obj``'s active action slot (Blender 5.x layered actions)."""
    from bpy_extras import anim_utils
    ad = obj.animation_data
    if ad is None or ad.action is None:
        return None
    return anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)


def remove_fcurves(obj: bpy.types.ID, match) -> int:
    """Delete F-curves whose data_path satisfies ``match(data_path)``."""
    bag = channelbag(obj)
    if bag is None:
        return 0
    doomed = [fc for fc in bag.fcurves if match(fc.data_path)]
    for fc in doomed:
        bag.fcurves.remove(fc)
    return len(doomed)


def clear() -> None:
    """Remove the character's body and face animation (keeps the current pose)."""
    from .character import character_armature
    from .face import face_mesh
    arm = character_armature()
    if arm is not None and arm.animation_data is not None:
        arm.animation_data.action = None
    keys = face_mesh().data.shape_keys
    if keys.animation_data is not None:
        keys.animation_data.action = None


def sequence(keys: list[tuple], fps: int = 24, plant_feet: bool = True) -> tuple[int, int]:
    """Key poses (and optional expressions) at frames.

    ``keys``: ``(frame, pose_spec[, expression_spec[, options]])``; ``options`` are passed
    to ``apply_pose`` (e.g. ``{"ground": False}`` for airborne frames).
    ``plant_feet`` re-solves foot IK on every in-between frame (see ``_plant_pass``), so a
    planted foot stays put and a stepping foot follows a lifted arc.
    Sets the scene frame range to cover the keys. Returns (start, end).
    """
    from .character import character_armature
    from .face import expression
    from .pose import humanoid_map
    scene = bpy.context.scene
    scene.render.fps = fps
    arm = character_armature()
    hmap = humanoid_map(arm)
    feet = []
    for key in keys:
        frame, pose_spec = key[0], key[1]
        options = key[3] if len(key) > 3 else {}
        pose = apply_pose(pose_spec, frame=frame, **options)
        feet.append((frame, _foot_targets(arm, hmap, pose, options.get("ground", True))))
        if len(key) > 2 and key[2] is not None:
            expression(key[2], frame=frame)
    if plant_feet:
        _plant_pass(arm, hmap, sorted(feet, key=lambda f: f[0]))
    _quaternion_continuity(arm)
    frames = [k[0] for k in keys]
    scene.frame_start, scene.frame_end = min(frames), max(frames)
    scene.frame_set(scene.frame_start)
    return scene.frame_start, scene.frame_end


def _quaternion_continuity(arm) -> int:
    """Flip quaternion keys that sit in the opposite hemisphere from the previous key (q and
    -q are the same rotation, but interpolating between them plays a full extra turn, e.g.
    after a 360-degree spin). Returns the number of keys flipped."""
    bag = channelbag(arm)
    if bag is None:
        return 0
    flipped = 0
    paths = {fc.data_path for fc in bag.fcurves if fc.data_path.endswith("rotation_quaternion")}
    for path in paths:
        curves = [bag.fcurves.find(path, index=i) for i in range(4)]
        if any(c is None for c in curves) or len({len(c.keyframe_points) for c in curves}) != 1:
            continue
        points = [sorted(c.keyframe_points, key=lambda k: k.co.x) for c in curves]
        prev = None
        for i in range(len(points[0])):
            q = [p[i].co.y for p in points]
            if prev is not None and sum(a * b for a, b in zip(prev, q)) < 0:
                for p in points:
                    kp = p[i]
                    kp.co.y, kp.handle_left.y, kp.handle_right.y = (
                        -kp.co.y, -kp.handle_left.y, -kp.handle_right.y)
                q = [-x for x in q]
                flipped += 1
            prev = q
        for c in curves:
            c.update()
    return flipped


FLOOR_FOOT = 0.03       # m: an FK foot this close to its standing height counts as planted


def _foot_targets(arm, hmap, pose, grounded: bool = True) -> dict:
    """``{chain: (target, pole, orient)}`` (armature space) for the feet of a key: IK feet as
    authored, and (grounded keys) FK feet standing on the floor where they are, so the foot
    pass keeps them still between keys instead of letting them drift with the hips."""
    import math

    from mathutils import Vector

    from ..poses import IK_PREFIX
    from .outfit import shoe_lift
    from .pose import _anchor
    out = {}
    lift = shoe_lift()
    for chain in ("left_foot", "right_foot"):
        entry = pose.get(IK_PREFIX + chain)
        if entry is not None:
            target = _anchor(arm, hmap, entry["target"]) + Vector(entry["offset"])
            out[chain] = (target, entry["pole"], entry.get("orient", (0.0, 0.0, 0.0)))
            continue
        if not grounded:
            continue
        side = chain.removesuffix("_foot")
        foot = arm.pose.bones[hmap[chain]]
        world_z = (arm.matrix_world @ foot.head).z
        if world_z - (foot.bone.head_local.z + lift) > FLOOR_FOOT:
            continue
        hip = arm.pose.bones[hmap[f"{side}_upper_leg"]].head
        knee = arm.pose.bones[hmap[f"{side}_lower_leg"]].head
        line = (foot.head - hip).normalized()
        pole = tuple((knee - hip) - line * (knee - hip).dot(line))
        delta = foot.matrix.to_quaternion() @ foot.bone.matrix_local.to_quaternion().inverted()
        out[chain] = (foot.head.copy(), pole, tuple(math.degrees(a) for a in delta.to_euler("XYZ")))
    return out


SWING_LIFT = 0.06       # metres: peak foot lift for a step between two floor contacts


def _plant_pass(arm, hmap, feet: list[tuple[int, dict]]) -> int:
    """Between consecutive keys where a foot is IK-placed in both, solve that foot on every
    frame: the target eases from one key to the next (unchanged = stays planted; moved along
    the floor = a lifted arc), and the leg bones are keyed. Fixes feet sliding or lifting
    while the rest of the body interpolates."""
    from mathutils import Vector

    from .pose import CHAIN_BONES, reach
    scene = bpy.context.scene
    keyed = 0
    for (f0, t0), (f1, t1) in zip(feet, feet[1:]):
        chains = [c for c in t0 if c in t1]
        for f in range(f0 + 1, f1):
            u = (f - f0) / (f1 - f0)
            e = u * u * (3 - 2 * u)
            scene.frame_set(f)
            for chain in chains:
                (a, pole, oa), (b, _, ob) = t0[chain], t1[chain]
                target = a.lerp(b, e)
                step = (b - a).length
                if step > 0.01 and abs(a.z - b.z) < 0.01:      # a step along the floor
                    target = target + Vector((0.0, 0.0, 4 * u * (1 - u) * min(SWING_LIFT, step * 0.25)))
                orient = tuple(x + (y - x) * e for x, y in zip(oa, ob))
                reach(chain, target, pole, arm, hmap, orient)
                for name in CHAIN_BONES[chain]:
                    pb = arm.pose.bones[hmap[name]]
                    pb.rotation_mode = "QUATERNION"
                    pb.keyframe_insert("rotation_quaternion", frame=f)
                    keyed += 1
    return keyed


def preset(name: str, fps: int = 24) -> dict:
    """Key a preset, or a chain like ``"wave_hello,spin,bow"``. Returns its clip options
    (``follow``, ``carry``, ``substeps``, ``loop``; see ``wogen.motions.PRESET_OPTIONS``)."""
    from ..motions import parse_chain
    segments = parse_chain(name)
    if any(s[0] == "mocap" for s in segments):
        return _mixed_chain(segments, fps)
    keys, options = build(name)
    clear()
    sequence(keys, fps)
    return options


def _mixed_chain(segments: list[tuple], fps: int = 24, expression: str = "smile_soft") -> dict:
    """Presets and mocap clips in one action: each part starts ``STEP_GAP`` frames after the
    previous one ends, where she stands then (mocap clips also turn to face the camera);
    the feet step across each transition (``_step_transition``)."""
    from ..motions import (MOCAP_OPTIONS, drop_trailing_hold, end_root,
                           merge_options, placed)
    from . import mocap
    from .character import character_armature
    clear()
    scene = bpy.context.scene
    scene.render.fps = fps
    end, root, options = 0, (0.0, 0.0), {}
    boundaries = []
    for i, seg in enumerate(segments):
        start = end + STEP_GAP if end else 1
        if end:
            boundaries.append((end, start))
        last = i == len(segments) - 1
        if seg[0] == "preset":
            name = seg[1]
            keys = PRESETS[name]()
            if not last:
                drop_trailing_hold(keys)
            keys = placed(keys, start, root)
            sequence(keys, fps)
            end = keys[-1][0]
            opts = PRESET_OPTIONS.get(name, {})
            if opts.get("travel"):
                root = end_root(keys)
        else:
            _, clip, start_s, end_s = seg
            end, root = mocap.segment(clip, start, root, start_s, end_s, fps,
                                      expression=expression)
            opts = MOCAP_OPTIONS
        options = merge_options(options, opts)
    arm = character_armature()
    _quaternion_continuity(arm)
    for f0, f1 in boundaries:
        _step_transition(arm, f0, f1)
    scene.frame_start, scene.frame_end = 1, end
    scene.frame_set(1)
    return options


STEP_GAP = 14            # frames between parts of a mixed chain: room for a step with each foot
STEP_HOLD = 0.02         # m: a foot that moves less than this across a transition just holds


def _step_transition(arm, f0: int, f1: int) -> None:
    """Between two chain parts, move each foot from where part A leaves it to where part B
    wants it by stepping (lifted arc, one foot after the other) instead of sliding both
    along the floor. Keys the leg bones on the in-between frames."""
    import math

    from mathutils import Vector

    from .pose import CHAIN_BONES, humanoid_map, reach
    hmap = humanoid_map(arm)
    scene = bpy.context.scene
    pb = arm.pose.bones

    def foot_state(f):
        scene.frame_set(f)
        out = {}
        for side in ("left", "right"):
            foot = pb[hmap[f"{side}_foot"]]
            out[side] = (foot.head.copy(), foot.matrix.to_quaternion())
        return out

    a, b = foot_state(f0), foot_state(f1)
    moves = {s: (b[s][0] - a[s][0]).length for s in a}
    order = sorted((s for s in moves if moves[s] > STEP_HOLD), key=lambda s: -moves[s])
    windows = {s: (0.0, 1.0) for s in a}            # holding feet blend over the whole gap
    if len(order) == 2:
        windows[order[0]], windows[order[1]] = (0.0, 0.6), (0.4, 1.0)
    rest = {s: pb[hmap[f"{s}_foot"]].bone.matrix_local.to_quaternion() for s in a}
    for f in range(f0 + 1, f1):
        u = (f - f0) / (f1 - f0)
        scene.frame_set(f)
        for side in ("left", "right"):
            w0, w1 = windows[side]
            t = min(1.0, max(0.0, (u - w0) / (w1 - w0)))
            e = t * t * (3 - 2 * t)
            (pa, qa), (pb_, qb) = a[side], b[side]
            target = pa.lerp(pb_, e)
            if side in order:                        # a real step: lift the foot on the way
                target = target + Vector((0.0, 0.0, 4 * t * (1 - t) * min(0.06, moves[side] * 0.3)))
            hip = pb[hmap[f"{side}_upper_leg"]].head
            knee = pb[hmap[f"{side}_lower_leg"]].head
            line = (target - hip).normalized()
            pole = (knee - hip) - line * (knee - hip).dot(line)
            delta = (qa.slerp(qb, e) @ rest[side].inverted()).to_euler("XYZ")
            reach(f"{side}_foot", target, pole, arm, hmap, [math.degrees(x) for x in delta])
            for name in CHAIN_BONES[f"{side}_foot"]:
                pb[hmap[name]].keyframe_insert("rotation_quaternion", frame=f)


def loop_range(options: dict) -> tuple[int, int] | None:
    """Narrow the scene range to the final seamless cycle of a loop preset (call after
    ``physics.bake()``, so the springs were simulated through the warm-up cycles)."""
    n = options.get("loop")
    if not n:
        return None
    scene = bpy.context.scene
    scene.frame_start = scene.frame_end - n
    scene.frame_end -= 1                      # the last frame equals the first: don't repeat it
    _close_spring_loop(scene.frame_start, scene.frame_end + 1)
    scene.frame_set(scene.frame_start)
    return scene.frame_start, scene.frame_end


def _close_spring_loop(start: int, end: int) -> int:
    """Make baked spring keys at ``end`` match ``start`` by spreading the leftover difference
    linearly over the cycle (springs that swing slowly never quite settle into the period)."""
    from mathutils import Quaternion

    from . import physics
    from .character import character_armature
    arm = character_armature()
    bag = channelbag(arm)
    if bag is None:
        return 0
    joints = set(physics.spring_bone_names(arm))      # chains, bust and tissue helper bones
    closed = 0
    channels = [(bone, prop, n) for bone in joints
                for prop, n in (("rotation_quaternion", 4), ("location", 3))]  # tissue: location
    for bone, prop, n in channels:
        curves = [bag.fcurves.find(f'pose.bones["{bone}"].{prop}', index=i) for i in range(n)]
        if any(c is None for c in curves):
            continue
        v0 = [c.evaluate(start) for c in curves]
        v1 = [c.evaluate(end) for c in curves]
        if n == 4 and Quaternion(v0).dot(Quaternion(v1)) < 0:
            v1 = [-v for v in v1]
        error = [a - b for a, b in zip(v0, v1)]
        span = end - start
        for c, err in zip(curves, error):
            for kp in c.keyframe_points:
                f = kp.co.x
                if start < f <= end:
                    kp.co.y += err * (f - start) / span
                    kp.handle_left.y += err * (f - start) / span
                    kp.handle_right.y += err * (f - start) / span
            c.update()
        closed += 1
    return closed
