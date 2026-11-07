"""Draw facial features (brows, optionally lash lines) through the bangs.

A geometry-nodes modifier on the Face mesh duplicates the selected feature faces and slides
each vertex toward the active camera along its own view ray. Moving along the view ray keeps
the projected (on-screen) position identical while making the copy nearer than the hair, so
the copy draws over the bangs. It uses a semi-transparent variant of the feature material,
so the hair stays visible underneath. Faces turned away from the camera are dropped so
features never show through the back of the head.

Works for camera renders (uses the scene's active camera). Free viewport angles that
aren't the scene camera will show the copy slightly misplaced.

Chat usage::

    from wogen.bl import overlay
    overlay.features_through_hair()                               # brows, 60% opacity
    overlay.features_through_hair(["brow", "eyeline"], opacity=0.5)
    overlay.remove()
"""

from __future__ import annotations

import bpy

from . import toon

MODIFIER = "wg_through_hair"
GROUP = "wg_through_hair"
PARAMS_KEY = "wg_through_hair_params"

# Feature name -> substring of the VRoid material name.
FEATURES = {
    "brow": "FaceBrow",
    "eyeline": "FaceEyeline",
    "eyelash": "FaceEyelash",
    "iris": "EyeIris",
    "highlight": "EyeHighlight",
}


def _face():
    from .face import face_mesh
    return face_mesh()


def _feature_materials(face: bpy.types.Object, features: list[str]):
    """(current slot material, its MToon source) for each requested feature."""
    unknown = [f for f in features if f not in FEATURES]
    if unknown:
        raise KeyError(f"Unknown features {unknown}; choose from {sorted(FEATURES)}")
    found = []
    for mat in face.data.materials:
        if mat is None or mat.name.startswith("wgo_"):
            continue
        src = toon._source_of(mat)
        if any(FEATURES[f] in src.name for f in features):
            found.append((mat, src))
    return found


def _build_group(selection_mats: list[bpy.types.Material], over_mats: list[bpy.types.Material],
                 offset: float, facing: float) -> bpy.types.NodeTree:
    """Node group: per feature material, separate -> cull back-facing -> pull toward camera."""
    ng = bpy.data.node_groups.get(GROUP)
    if ng is None:
        ng = bpy.data.node_groups.new(GROUP, "GeometryNodeTree")
        ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links
    nodes.clear()

    gin = nodes.new("NodeGroupInput")
    gin.location = (-1400, 0)
    gout = nodes.new("NodeGroupOutput")
    gout.location = (800, 0)
    join = nodes.new("GeometryNodeJoinGeometry")
    join.location = (600, 0)
    links.new(gin.outputs["Geometry"], join.inputs["Geometry"])

    # Camera location in the modified object's space.
    cam = nodes.new("GeometryNodeInputActiveCamera")
    cam.location = (-1400, -400)
    cam_info = nodes.new("GeometryNodeObjectInfo")
    cam_info.transform_space = "RELATIVE"
    cam_info.location = (-1200, -400)
    links.new(cam.outputs[0], cam_info.inputs["Object"])
    position = nodes.new("GeometryNodeInputPosition")
    position.location = (-1200, -600)

    to_cam = nodes.new("ShaderNodeVectorMath")
    to_cam.operation = "SUBTRACT"
    to_cam.location = (-1000, -450)
    links.new(cam_info.outputs["Location"], to_cam.inputs[0])
    links.new(position.outputs[0], to_cam.inputs[1])
    to_cam_n = nodes.new("ShaderNodeVectorMath")
    to_cam_n.operation = "NORMALIZE"
    to_cam_n.location = (-800, -450)
    links.new(to_cam.outputs["Vector"], to_cam_n.inputs[0])

    # Facing test: face normal . direction-to-camera > facing.
    normal = nodes.new("GeometryNodeInputNormal")
    normal.location = (-1000, -250)
    dot = nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.location = (-800, -250)
    links.new(normal.outputs["Normal"], dot.inputs[0])
    links.new(to_cam_n.outputs["Vector"], dot.inputs[1])
    facing_cmp = nodes.new("FunctionNodeCompare")
    facing_cmp.data_type = "FLOAT"
    facing_cmp.operation = "GREATER_THAN"
    facing_cmp.location = (-600, -250)
    links.new(dot.outputs["Value"], facing_cmp.inputs["A"])
    facing_cmp.inputs["B"].default_value = facing

    # Offset along the view ray.
    scaled = nodes.new("ShaderNodeVectorMath")
    scaled.operation = "SCALE"
    scaled.location = (-600, -450)
    links.new(to_cam_n.outputs["Vector"], scaled.inputs[0])
    scaled.inputs["Scale"].default_value = offset

    for i, (sel_mat, over_mat) in enumerate(zip(selection_mats, over_mats)):
        y = 300 + i * 220
        mat_sel = nodes.new("GeometryNodeMaterialSelection")
        mat_sel.location = (-600, y)
        mat_sel.inputs["Material"].default_value = sel_mat
        both = nodes.new("FunctionNodeBooleanMath")
        both.operation = "AND"
        both.location = (-400, y)
        links.new(mat_sel.outputs[0], both.inputs[0])
        links.new(facing_cmp.outputs[0], both.inputs[1])
        sep = nodes.new("GeometryNodeSeparateGeometry")
        sep.domain = "FACE"
        sep.location = (-200, y)
        links.new(gin.outputs["Geometry"], sep.inputs["Geometry"])
        links.new(both.outputs[0], sep.inputs["Selection"])
        move = nodes.new("GeometryNodeSetPosition")
        move.location = (0, y)
        links.new(sep.outputs["Selection"], move.inputs["Geometry"])
        links.new(scaled.outputs["Vector"], move.inputs["Offset"])
        set_mat = nodes.new("GeometryNodeSetMaterial")
        set_mat.location = (200, y)
        links.new(move.outputs["Geometry"], set_mat.inputs["Geometry"])
        set_mat.inputs["Material"].default_value = over_mat
        links.new(set_mat.outputs["Geometry"], join.inputs["Geometry"])

    links.new(join.outputs["Geometry"], gout.inputs["Geometry"])
    return ng


def features_through_hair(features: list[str] | None = None, opacity: float = 0.6,
                          offset: float = 0.04, facing: float = 0.15) -> str:
    """Add/refresh the overlay. Call after ``toon.apply_toon()`` (which resets modifiers)."""
    features = features or ["brow"]
    face = _face()
    pairs = _feature_materials(face, features)
    if not pairs:
        raise RuntimeError(f"No Face materials match {features}")
    sel_mats, over_mats = [], []
    for slot_mat, src in pairs:
        profile = toon.profile_for(face.name, src.name)
        over = toon.build_toon_material(src, profile, name=f"wgx_{src.name}", alpha_scale=opacity,
                                        **toon.material_recolor(face, src.name))
        sel_mats.append(slot_mat)
        over_mats.append(over)
        if over.name not in face.data.materials:
            face.data.materials.append(over)   # GN-assigned materials must be in a slot to render
    group = _build_group(sel_mats, over_mats, offset, facing)
    md = face.modifiers.get(MODIFIER) or face.modifiers.new(MODIFIER, "NODES")
    md.node_group = group
    # Keep it last so it sees armature, shape keys and outline results.
    face.modifiers.move(face.modifiers.find(MODIFIER), len(face.modifiers) - 1)
    # Remembered so toon.apply_toon() can rebuild the overlay after resetting materials.
    face[PARAMS_KEY] = {"features": list(features), "opacity": opacity, "offset": offset,
                        "facing": facing}
    return f"through-hair overlay: {[s.name for _, s in pairs]} at {opacity:.0%}"


def saved_params(face: bpy.types.Object) -> dict | None:
    params = face.get(PARAMS_KEY)
    if params is None:
        return None
    p = params.to_dict() if hasattr(params, "to_dict") else dict(params)
    p["features"] = list(p["features"])
    return p


def remove(face: bpy.types.Object | None = None, forget: bool = True) -> None:
    face = face or _face()
    if forget and PARAMS_KEY in face:
        del face[PARAMS_KEY]
    md = face.modifiers.get(MODIFIER)
    if md is not None:
        face.modifiers.remove(md)
    mats = face.data.materials
    for i in range(len(mats) - 1, -1, -1):
        if mats[i] is not None and mats[i].name.startswith("wgx_"):
            mats.pop(index=i)
