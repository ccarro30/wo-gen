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
        feet.append((frame, _foot_targets(arm, hmap, pose)))
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


def _foot_targets(arm, hmap, pose) -> dict:
    """``{chain: (target, pole, orient)}`` (armature space) for the IK feet of a key."""
    from mathutils import Vector

    from ..poses import IK_PREFIX
    from .pose import _anchor
    out = {}
    for chain in ("left_foot", "right_foot"):
        entry = pose.get(IK_PREFIX + chain)
        if entry is not None:
            target = _anchor(arm, hmap, entry["target"]) + Vector(entry["offset"])
            out[chain] = (target, entry["pole"], entry.get("orient", (0.0, 0.0, 0.0)))
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
    keys, options = build(name)
    clear()
    sequence(keys, fps)
    return options


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
    joints = {j.bone for sp in physics._springs(arm, physics.PhysicsSettings()) for j in sp.joints}
    closed = 0
    for bone in joints:
        path = f'pose.bones["{bone}"].rotation_quaternion'
        curves = [bag.fcurves.find(path, index=i) for i in range(4)]
        if any(c is None for c in curves):
            continue
        q0 = Quaternion([c.evaluate(start) for c in curves])
        q1 = Quaternion([c.evaluate(end) for c in curves])
        if q0.dot(q1) < 0:
            q1.negate()
        error = [a - b for a, b in zip(q0, q1)]
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
