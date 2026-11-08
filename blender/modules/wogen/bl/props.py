"""Simple scene props (cel-shaded), e.g. a seat for sitting poses.

Chat usage::

    from wogen.bl import props
    props.seat(height=0.45)      # box under the hips for pose "sit_chair"
    props.clear()
"""

from __future__ import annotations

import bpy

from .toon import add_flat_outline, make_cel_material

COLLECTION = "wogen_props"


def _collection() -> bpy.types.Collection:
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(COLLECTION)
        bpy.context.scene.collection.children.link(coll)
    return coll


def seat(height: float = 0.45, width: float = 0.46, depth: float = 0.42,
         y: float = 0.06, color=(0.32, 0.30, 0.36)) -> bpy.types.Object:
    """A box seat whose top is at ``height`` m, centred under the hips (front edge at y-depth/2)."""
    import bmesh
    name = "wg_seat"
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(width, depth, height), verts=bm.verts)   # unit scale for the outline
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = (0.0, y + depth / 2 - 0.05, height / 2)
    shadow = tuple(c * 0.7 for c in color)
    mat = bpy.data.materials.get("wg_prop_seat") or make_cel_material("wg_prop_seat", color, shadow)
    mesh.materials.append(mat)
    add_flat_outline(obj, color)
    _collection().objects.link(obj)
    return obj


def clear() -> None:
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None:
        return
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
