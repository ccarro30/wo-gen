"""Apply facial expressions and gaze to the loaded character (VRoid base or MMD import).

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

from .. import mmd
from ..expressions import PRESETS, list_expressions, resolve_weights  # noqa: F401 (re-export)

FACE_MESH = "Face"
EYE_BONES = ("J_Adj_L_FaceEye", "J_Adj_R_FaceEye")
MMD_FACE_CATEGORIES = ("EYEBROW", "EYE", "MOUTH")


def face_mesh() -> bpy.types.Object:
    """The VRoid ``Face`` mesh, or for an imported MMD model the mesh with its face morphs."""
    from .character import character_meshes
    meshes = [o for o in character_meshes() if o.data.shape_keys is not None]
    face = next((o for o in meshes if o.name == FACE_MESH), None)
    if face is None:
        originals = _original_morphs()
        with_morphs = [o for o in meshes
                       if any(originals.get(k.name, k.name) in mmd.MORPH_NAMES
                              for k in o.data.shape_keys.key_blocks)]
        face = max(with_morphs, key=lambda o: len(o.data.shape_keys.key_blocks), default=None)
    if face is None:
        raise RuntimeError("No character face mesh with shape keys (import_base() first)")
    return face


def _original_morphs() -> dict[str, str]:
    """{shape key: original MMD morph name} for a translated import (else empty)."""
    from .character import character_armature
    from .mmd_import import original_names
    return original_names(character_armature(), "morphs")


def _is_vroid(blocks) -> bool:
    return any(k.name.startswith("Fcl_") for k in blocks)


def _mmd_face_keys(blocks) -> set[str]:
    """Face morphs of the loaded MMD model, from mmd_tools' morph categories (hat, teeth and
    other ``OTHER`` morphs are left alone); the standard names if that data is missing."""
    from .character import character_armature
    arm = character_armature()
    root = arm.parent if arm is not None else None
    morphs = getattr(getattr(root, "mmd_root", None), "vertex_morphs", None)
    names = {m.name for m in morphs or () if m.category in MMD_FACE_CATEGORIES}
    if not names:
        originals = _original_morphs()
        names = {k.name for k in blocks[1:] if originals.get(k.name, k.name) in mmd.MORPH_NAMES}
    return {k.name for k in blocks[1:] if k.name in names}


def expression(spec: str | dict[str, float] = "neutral", weight: float = 1.0,
               reset: bool = True, frame: int | None = None) -> dict[str, float]:
    """Apply an expression. ``reset`` zeroes all other face keys; ``frame`` keyframes them.
    On an MMD model the Fcl weights become its standard morphs (``mmd.morph_weights``);
    parts the model has no morph for are skipped. Returns the shape key weights set."""
    blocks = face_mesh().data.shape_keys.key_blocks
    weights = resolve_weights(spec, weight)
    if _is_vroid(blocks):
        missing = [k for k in weights if k not in blocks]
        if missing:
            raise KeyError(f"Face mesh lacks shape keys: {missing}")
        face_keys = {k.name for k in blocks[1:]}
    else:
        to_original = _original_morphs()
        from_original = {to_original.get(k, k): k for k in blocks.keys()}
        weights = {from_original[k]: w for k, w in
                   mmd.morph_weights(weights, from_original).items()}
        face_keys = _mmd_face_keys(blocks) | set(weights)
    for block in blocks[1:]:   # skip Basis
        if block.name not in face_keys:
            continue
        if block.name in weights:
            block.value = weights[block.name]
        elif reset:
            block.value = 0.0
        if frame is not None and (reset or block.name in weights):
            block.keyframe_insert("value", frame=frame)
    return weights


def eye_bones(arm) -> list[str]:
    """The eye bones gaze turns: the humanoid map's, else VRoid's adjust bones."""
    from .pose import humanoid_map
    hmap = humanoid_map(arm)
    names = [hmap.get(n) for n in ("left_eye", "right_eye")]
    if not all(names):
        names = list(EYE_BONES)
    return [n for n in names if n in arm.pose.bones]


def gaze(yaw: float = 0.0, pitch: float = 0.0, max_yaw: float = 14.0,
         max_pitch: float = 10.0) -> None:
    """Turn both eyes: ``yaw`` + = character's left (degrees), ``pitch`` + = up."""
    from .character import character_armature
    arm = character_armature()
    if arm is None:
        raise RuntimeError("No character loaded")
    yaw = max(-max_yaw, min(max_yaw, yaw))
    pitch = max(-max_pitch, min(max_pitch, pitch))
    bones = [arm.pose.bones[n] for n in eye_bones(arm)]
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
