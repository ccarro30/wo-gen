"""Anime face shading: smooth ellipsoid normals for the Face mesh's skin.

Real face geometry (nose, lips, cheekbones) makes cel shading blotchy. Anime pipelines replace
the face's shading normals with those of a simple rounded shape, so the light/shadow boundary
sweeps cleanly across the face as the light moves. We use the normals of an ellipsoid fitted
to the face skin:

- wide in X and Y, so the shadow comes in from the side and curves around the cheek;
- very tall in Z, so lights from above don't darken the lower face (no "moustache" shadow);
- faded back to the original normals near the outer edge of the face skin, so the seam with
  the neck and ears stays continuous.

Two layers:

1. The normals are baked into the mesh's custom normals (stored relative to the surface).
   That's what export keeps, and a fallback.
2. For rendering, a geometry-nodes modifier after the armature sets them again from rest-space
   attributes, rotated with the head (``wg_head_frame``, an empty bone-parented to the head).
   Surface-relative normals would tilt with every shape key (expressions, nose/mouth sliders)
   and leave shadow patches; head-space normals don't.

Call ``setup_face_normals()`` once after import and after the body is retargeted.
"""

from __future__ import annotations

import numpy as np

import bpy

BAKED_KEY = "wg_face_normals"
NORMAL_ATTR = "wg_face_normal"
WEIGHT_ATTR = "wg_face_normal_w"
MODIFIER = GROUP = "wg_face_normals"
FRAME = "wg_head_frame"
HEAD_BONE = "J_Bip_C_Head"

# Ellipsoid relative to the face skin's height (0.219 m on base_f01): centre behind the face
# front and a little below mid-height; radii (X, Y, Z).
CENTER_BEHIND_FRONT = 0.60
CENTER_HEIGHT = 0.44
RADII = (0.41, 0.50, 1.83)
# Lean the normals toward the face's forward direction: the face stays lit until the key
# light is well to the side, as in anime, and the shadow claims only the far edge.
FORWARD_BIAS = 0.8
FADE = (0.018, 0.115)         # from the outer edge: original normals .. full ellipsoid
OUTER_EDGE_BEHIND_FRONT = 0.19  # skin boundary this far behind the front is the outer edge


def _skin_slots(face) -> set[int]:
    from . import toon
    out = set()
    for i, mat in enumerate(face.data.materials):
        src = toon._source_of(mat)
        if src is not None and toon.classify(src.name) == "SKIN":
            out.add(i)
    return out


def _compute(face):
    """(ellipsoid normal per corner, weight per corner, original corner normals)."""
    import bmesh
    from mathutils.kdtree import KDTree
    me = face.data
    nv, nl, npoly = len(me.vertices), len(me.loops), len(me.polygons)
    co = np.empty(nv * 3, np.float32)
    source = me.shape_keys.key_blocks[0].data if me.shape_keys else me.vertices
    source.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    orig = np.empty(nl * 3, np.float32)
    me.corner_normals.foreach_get("vector", orig)
    orig = orig.reshape(-1, 3).astype(np.float64)
    mat_index = np.empty(npoly, np.int32)
    me.polygons.foreach_get("material_index", mat_index)
    loop_total = np.empty(npoly, np.int32)
    me.polygons.foreach_get("loop_total", loop_total)
    loop_vert = np.empty(nl, np.int32)
    me.loops.foreach_get("vertex_index", loop_vert)
    skin_loop = np.isin(np.repeat(mat_index, loop_total), list(_skin_slots(face)))
    skin_verts = np.unique(loop_vert[skin_loop])
    if not len(skin_verts):
        return None

    s = co[skin_verts]
    lo, hi = s.min(axis=0), s.max(axis=0)
    height = hi[2] - lo[2]
    front = lo[1]                         # the character faces -Y
    center = np.array([(lo[0] + hi[0]) / 2, front + CENTER_BEHIND_FRONT * height,
                       lo[2] + CENTER_HEIGHT * height])
    radii = np.array(RADII) * height
    normals = (co - center) / radii ** 2
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    normals += np.array([0.0, -FORWARD_BIAS, 0.0])     # lean toward the face's forward (-Y)
    normals /= np.linalg.norm(normals, axis=1)[:, None]

    # Outer edge = open skin boundary at the sides/back (not the eye and mouth openings).
    bm = bmesh.new()
    bm.from_mesh(me)
    in_skin = np.zeros(nv, bool)
    in_skin[skin_verts] = True
    edge = [v.index for v in bm.verts
            if in_skin[v.index] and co[v.index, 1] > front + OUTER_EDGE_BEHIND_FRONT * height
            and any(e.is_boundary for e in v.link_edges)]
    bm.free()
    weight = np.ones(nv)
    if edge:
        tree = KDTree(len(edge))
        for i, v in enumerate(edge):
            tree.insert(co[v], i)
        tree.balance()
        dist = np.array([tree.find(c)[2] for c in co])
        t = np.clip((dist - FADE[0] * height) / ((FADE[1] - FADE[0]) * height), 0.0, 1.0)
        weight = t * t * (3 - 2 * t)
    return normals[loop_vert], weight[loop_vert] * skin_loop, orig


def _head_frame(face, arm):
    """Empty that follows the head bone and has identity rotation (face space) at rest."""
    from mathutils import Matrix
    from .character import CHARACTER_COLLECTION
    bone = arm.data.bones[HEAD_BONE]
    frame = bpy.data.objects.get(FRAME)
    if frame is None:
        frame = bpy.data.objects.new(FRAME, None)
        frame.empty_display_size = 0.05
        coll = bpy.data.collections.get(CHARACTER_COLLECTION) or bpy.context.scene.collection
        coll.objects.link(frame)
    frame.hide_viewport = frame.hide_render = True
    frame.parent = arm
    frame.parent_type = "BONE"
    frame.parent_bone = HEAD_BONE
    # Bone parenting attaches at the bone's tail; use the rest matrix, so the current pose
    # doesn't matter.
    rest = arm.matrix_world @ bone.matrix_local @ Matrix.Translation((0.0, bone.length, 0.0))
    frame.matrix_parent_inverse = rest.inverted()
    frame.matrix_basis = face.matrix_world.copy()
    return frame


def _build_group(frame) -> bpy.types.NodeTree:
    ng = bpy.data.node_groups.get(GROUP)
    if ng is None:
        ng = bpy.data.node_groups.new(GROUP, "GeometryNodeTree")
        ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links
    nodes.clear()
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")
    rest_n = nodes.new("GeometryNodeInputNamedAttribute")
    rest_n.data_type = "FLOAT_VECTOR"
    rest_n.inputs["Name"].default_value = NORMAL_ATTR
    w = nodes.new("GeometryNodeInputNamedAttribute")
    w.data_type = "FLOAT"
    w.inputs["Name"].default_value = WEIGHT_ATTR
    info = nodes.new("GeometryNodeObjectInfo")
    info.transform_space = "RELATIVE"
    info.inputs["Object"].default_value = frame
    rotate = nodes.new("FunctionNodeRotateVector")
    links.new(rest_n.outputs["Attribute"], rotate.inputs["Vector"])
    links.new(info.outputs["Rotation"], rotate.inputs["Rotation"])
    current = nodes.new("GeometryNodeInputNormal")      # deformed surface normal (fallback)
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "VECTOR"
    links.new(w.outputs["Attribute"], mix.inputs["Factor"])
    links.new(current.outputs["Normal"], mix.inputs["A"])
    links.new(rotate.outputs[0], mix.inputs["B"])
    norm = nodes.new("ShaderNodeVectorMath")
    norm.operation = "NORMALIZE"
    links.new(mix.outputs["Result"], norm.inputs[0])
    setn = nodes.new("GeometryNodeSetMeshNormal")
    setn.mode = "FREE"
    setn.domain = "CORNER"
    links.new(gin.outputs[0], setn.inputs["Mesh"])
    links.new(norm.outputs[0], setn.inputs["Custom Normal"])
    links.new(setn.outputs[0], gout.inputs[0])
    for i, n in enumerate((gin, rest_n, w, info, rotate, current, mix, norm, setn, gout)):
        n.location = (i * 200 - 1000, 0)
    return ng


def setup_face_normals(face=None, armature=None) -> str:
    """Bake ellipsoid normals into the face skin and add the head-space render modifier."""
    from .character import character_armature
    if face is None:
        from .face import face_mesh
        face = face_mesh()
    arm = armature or character_armature()
    me = face.data
    result = _compute(face)
    if result is None:
        return "face normals: no skin material on the Face mesh"
    normals, weight, orig = result
    if not me.get(BAKED_KEY):
        out = orig * (1 - weight[:, None]) + normals * weight[:, None]
        out /= np.linalg.norm(out, axis=1)[:, None]
        me.normals_split_custom_set(out.tolist())
        me[BAKED_KEY] = True
    for name, dtype in ((NORMAL_ATTR, "FLOAT_VECTOR"), (WEIGHT_ATTR, "FLOAT")):
        if name in me.attributes:
            me.attributes.remove(me.attributes[name])
        me.attributes.new(name, dtype, "CORNER")
    me.attributes[NORMAL_ATTR].data.foreach_set("vector", normals.astype(np.float32).ravel())
    me.attributes[WEIGHT_ATTR].data.foreach_set("value", weight.astype(np.float32))
    me.update()
    if arm is None or HEAD_BONE not in arm.data.bones:
        return "face normals: baked (no head bone; render modifier skipped)"
    group = _build_group(_head_frame(face, arm))
    md = face.modifiers.get(MODIFIER) or face.modifiers.new(MODIFIER, "NODES")
    md.node_group = group
    after_armature = next((i + 1 for i, m in enumerate(face.modifiers) if m.type == "ARMATURE"), 0)
    face.modifiers.move(face.modifiers.find(MODIFIER), after_armature)
    return f"face normals: {int((weight > 0).sum())} skin corners"


def strip(face) -> None:
    """Remove the render-time parts (export keeps only the baked custom normals)."""
    md = face.modifiers.get(MODIFIER)
    if md is not None:
        face.modifiers.remove(md)
    for name in (NORMAL_ATTR, WEIGHT_ATTR):
        if name in face.data.attributes:
            face.data.attributes.remove(face.data.attributes[name])
    frame = bpy.data.objects.get(FRAME)
    if frame is not None:
        bpy.data.objects.remove(frame, do_unlink=True)
