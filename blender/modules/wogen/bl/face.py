"""Apply facial expressions and gaze to the loaded VRoid-based character.

Chat usage::

    from wogen.bl import face
    face.list_expressions()
    face.expression("smile_soft")
    face.expression({"shy": 1.0, "aa": 0.3})       # mix presets / raw Fcl_ keys
    face.expression("happy", frame=12)              # keyframe for animation
    face.gaze(yaw=10, pitch=-5)
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix

from ..expressions import PRESETS, list_expressions, resolve_weights  # noqa: F401 (re-export)

FACE_MESH = "Face"
EYE_BONES = ("J_Adj_L_FaceEye", "J_Adj_R_FaceEye")


def face_mesh() -> bpy.types.Object:
    from .character import character_meshes
    face = next((o for o in character_meshes() if o.name == FACE_MESH), None)
    if face is None or face.data.shape_keys is None:
        raise RuntimeError("No character Face mesh with shape keys (import_base() first)")
    return face


def expression(spec: str | dict[str, float] = "neutral", weight: float = 1.0,
               reset: bool = True, frame: int | None = None) -> dict[str, float]:
    """Apply an expression. ``reset`` zeroes all other face keys; ``frame`` keyframes them."""
    blocks = face_mesh().data.shape_keys.key_blocks
    weights = resolve_weights(spec, weight)
    missing = [k for k in weights if k not in blocks]
    if missing:
        raise KeyError(f"Face mesh lacks shape keys: {missing}")
    for block in blocks[1:]:   # skip Basis
        if block.name in weights:
            block.value = weights[block.name]
        elif reset:
            block.value = 0.0
        if frame is not None and (reset or block.name in weights):
            block.keyframe_insert("value", frame=frame)
    return weights


def gaze(yaw: float = 0.0, pitch: float = 0.0, max_yaw: float = 14.0,
         max_pitch: float = 10.0) -> None:
    """Turn both eyes: ``yaw`` + = character's left (degrees), ``pitch`` + = up."""
    from .character import character_armature
    arm = character_armature()
    if arm is None:
        raise RuntimeError("No character loaded")
    yaw = max(-max_yaw, min(max_yaw, yaw))
    pitch = max(-max_pitch, min(max_pitch, pitch))
    bones = [arm.pose.bones[n] for n in EYE_BONES if n in arm.pose.bones]
    for pb in bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    # Character faces -Y: yaw about Z (+ turns toward +X, the character's left);
    # pitch about X (a negative angle tilts the -Y forward vector upward).
    rot = Matrix.Rotation(math.radians(yaw), 4, "Z") @ Matrix.Rotation(math.radians(-pitch), 4, "X")
    for pb in bones:
        pivot = pb.head.copy()
        pb.matrix = Matrix.Translation(pivot) @ rot @ Matrix.Translation(-pivot) @ pb.matrix
    bpy.context.view_layer.update()
