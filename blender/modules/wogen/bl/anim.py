"""Keyframed motion built from library poses and expressions.

Chat usage::

    from wogen.bl import anim
    anim.clear()
    anim.sequence([(1, "idle", "neutral"), (24, "wave", "happy"), (48, "idle", "smile_soft")])
    anim.preset("look_around")
"""

from __future__ import annotations

import bpy

from ..poses import merge, resolve_pose
from .pose import POSES_DIR, apply_pose


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


def sequence(keys: list[tuple], fps: int = 24) -> tuple[int, int]:
    """Key poses (and optional expressions) at frames.

    ``keys``: ``(frame, pose_spec[, expression_spec[, options]])``; ``options`` are passed
    to ``apply_pose`` (e.g. ``{"ground": False}`` for airborne frames).
    Sets the scene frame range to cover the keys. Returns (start, end).
    """
    from .face import expression
    scene = bpy.context.scene
    scene.render.fps = fps
    for key in keys:
        frame, pose_spec = key[0], key[1]
        options = key[3] if len(key) > 3 else {}
        apply_pose(pose_spec, frame=frame, **options)
        if len(key) > 2 and key[2] is not None:
            expression(key[2], frame=frame)
    frames = [k[0] for k in keys]
    scene.frame_start, scene.frame_end = min(frames), max(frames)
    scene.frame_set(scene.frame_start)
    return scene.frame_start, scene.frame_end


def _turn(pose: str, yaw: float, tilt: float = 0.0) -> dict:
    """``pose`` with the head/neck/chest turned by ``yaw`` degrees (+ = to her left)."""
    base = resolve_pose(pose, POSES_DIR)

    def add(bone, dz, dy=0.0):
        x, y, z = base.get(bone, (0.0, 0.0, 0.0))
        return {bone: (x, y + dy, z + dz)}

    return merge(base, add("head", yaw * 0.5, tilt), add("neck", yaw * 0.3), add("chest", yaw * 0.2))


def _hop(pose: str, height: float) -> dict:
    """``pose`` with the body raised/lowered by ``height``. Below 0 the feet stay planted
    (knees bend); above 0 the feet travel with the body (use ``ground: False``)."""
    from ..poses import plant
    base = resolve_pose(pose, POSES_DIR)
    lift = max(height, 0.0)
    feet = merge(plant("left", (0.0, 0.0, lift), (0.1, -1.0, 0.0)),
                 plant("right", (0.0, 0.0, lift), (-0.1, -1.0, 0.0)))
    arms = {"left_upper_arm": (0, 72 - 300 * lift, -6), "right_upper_arm": (0, -72 + 300 * lift, -6)}
    return merge(base, feet, arms if lift else {}, {"hips_location": (0.0, 0.0, height)})


PRESETS = {
    # Quick head turns: good for testing hair follow-through.
    "look_around": lambda: [
        (1, "idle", "neutral"), (10, _turn("idle", 50, 4), "neutral"),
        (22, _turn("idle", 50, 4), "smile_soft"), (32, _turn("idle", -50, -4), "smile_soft"),
        (44, _turn("idle", -50, -4), "neutral"), (54, "idle", "happy"), (72, "idle", "happy"),
    ],
    # Small bouncy hop in place (crouch -> up -> land).
    "hop": lambda: [
        (1, "idle", "neutral"), (8, _hop("idle", -0.07), "neutral"),
        (14, _hop("idle", 0.12), "happy", {"ground": False}),
        (20, _hop("idle", -0.06), "happy"),
        (28, "idle", "smile_soft"), (48, "idle", "smile_soft"),
    ],
    "wave_hello": lambda: [
        (1, "idle", "neutral"), (14, "wave", "happy"),
        (22, merge(resolve_pose("wave"), {"right_hand": (0, 0, -25)}), "happy"),
        (30, "wave", "happy"),
        (38, merge(resolve_pose("wave"), {"right_hand": (0, 0, -25)}), "happy"),
        (46, "wave", "happy"), (62, "idle", "smile_soft"), (80, "idle", "smile_soft"),
    ],
}


def preset(name: str, fps: int = 24) -> tuple[int, int]:
    clear()
    return sequence(PRESETS[name](), fps)
