"""Toon (cel) materials and outlines. EEVEE only: Shader-to-RGB has no effect in Cycles.

``apply_toon()`` converts an imported VRoid/VRM character: every MToon material gets a
``wg_`` cel twin (originals are kept for VRM export / ``remove_toon()``), and each mesh gets
an inverted-hull outline whose color is derived per material (style guide: never pure black).
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass

import bpy

Color = tuple[float, float, float]

OUTLINE_MOD = "wg_outline"
# Render-time smoothing (``add_smoothing``): the body is VroidStudio's low-poly triangle mesh
# (about 11k triangles), which shows angles along the hips, seat and thighs. A Weld re-joins
# the vertices that the VRM export splits along UV seams (2,094 open edges on the body), so
# one level of subdivision rounds the surface without opening cracks along those seams.
# Render only: export strips every modifier but the armature.
WELD_MOD, SUBSURF_MOD = "wg_weld", "wg_subsurf"
SMOOTH_MESHES = ("Body",)
SOURCE_KEY = "wg_source"


# ---------------------------------------------------------------- color helpers

def srgb_to_linear(c: Color) -> Color:
    """Palette colors (hex, color pickers) are sRGB; Blender node colors are linear."""
    def ch(v: float) -> float:
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (ch(c[0]), ch(c[1]), ch(c[2]))


def hex_to_srgb(value: str) -> Color:
    h = value.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Expected #RRGGBB, got {value!r}")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def outline_color_for(base_srgb: Color, value: float = 0.32, sat_boost: float = 1.25) -> Color:
    """Dark, saturated version of a base color (sRGB in, sRGB out)."""
    h, s, v = colorsys.rgb_to_hsv(*base_srgb)
    return colorsys.hsv_to_rgb(h, min(1.0, s * sat_boost + 0.1), v * value)


_mean_cache: dict[int, Color] = {}   # by ID.session_uid; cleared by remove_character()


def image_mean_srgb(image: bpy.types.Image | None, step: int = 16) -> Color:
    """Alpha-weighted mean color of an image (stored values, i.e. sRGB for 8-bit images)."""
    if image is None or image.size[0] == 0:
        return (0.5, 0.5, 0.5)
    if image.session_uid in _mean_cache:
        return _mean_cache[image.session_uid]
    import numpy as np
    w, h = image.size
    px = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(px)
    px = px.reshape(-1, 4)[::step]
    mask = px[:, 3] > 0.5
    rgb = px[mask, :3] if mask.any() else px[:, :3]
    mean = tuple(float(x) for x in rgb.mean(axis=0))
    _mean_cache[image.session_uid] = mean
    return mean


# ---------------------------------------------------------------- profiles

@dataclass(frozen=True)
class ToonProfile:
    shadow_tint: Color      # sRGB multiplier applied to the lit color in shadow
    threshold: float = 0.5  # light/shadow boundary (0..1 of diffuse intensity)
    softness: float = 0.03  # half-width of the boundary blur
    rim: float = 0.0        # rim-light strength on the lit side
    lit: bool = True        # False -> flat/unlit (eyes, brows, lashes, mouth)
    outline: bool = True
    outline_width: float = 0.0012   # metres
    backface_tint: Color | None = None   # sRGB multiplier for back faces (inner hair); unlit
    rim_color: Color = (1.0, 0.95, 0.90)  # sRGB, screened over the base


# Rim light comes from this direction in camera space (+X right, +Y up): upper left.
RIM_DIRECTION = (-0.65, 0.55, 0.0)


PROFILES: dict[str, ToonProfile] = {
    "SKIN": ToonProfile(shadow_tint=(0.98, 0.84, 0.82), threshold=0.42, softness=0.05, rim=0.45),
    "HAIR": ToonProfile(shadow_tint=(0.70, 0.64, 0.80), threshold=0.50, softness=0.03, rim=0.55,
                        outline_width=0.0010, backface_tint=(0.58, 0.50, 0.56)),
    "CLOTH": ToonProfile(shadow_tint=(0.84, 0.83, 0.92), threshold=0.45, softness=0.03, rim=0.35),
    "EYE": ToonProfile(shadow_tint=(1, 1, 1), lit=False, outline=False),
    "FACE": ToonProfile(shadow_tint=(1, 1, 1), lit=False, outline=False),
}
MESH_OUTLINE_SCALE = {"Face": 0.6}   # thinner silhouette line on the face mesh

# Per-mesh overrides. Face skin shades with baked ellipsoid normals (bl/face_shading.py), so
# it takes a crisp band; the slightly lower threshold keeps the face lit up to ~70 degrees of
# key-light azimuth before the shadow reaches the nose.
PROFILE_OVERRIDES: dict[tuple[str, str], ToonProfile] = {
    ("Face", "SKIN"): ToonProfile(shadow_tint=(0.98, 0.84, 0.82), threshold=0.36, softness=0.02,
                                  rim=0.30),
}


def profile_for(mesh_name: str, material_name: str) -> ToonProfile:
    cls = classify(material_name)
    return PROFILE_OVERRIDES.get((mesh_name, cls), PROFILES[cls])


def classify(material_name: str) -> str:
    """VRoid material names end in _SKIN/_HAIR/_CLOTH/_EYE/_FACE (optionally + _NN)."""
    from ..garments import strip_suffix
    tokens = [t for t in strip_suffix(material_name).upper().split("_") if not t.isdigit()]
    for token in reversed(tokens):   # class is the last word: "..._Face_00_SKIN" -> SKIN
        if token in PROFILES:
            return token
    return "CLOTH"


# ---------------------------------------------------------------- node helpers

def _mix(nodes, links, blend: str, fac, a, b, loc):
    node = nodes.new("ShaderNodeMix")
    node.data_type = "RGBA"
    node.blend_type = blend
    node.clamp_result = True
    node.location = loc
    sock = {s.identifier: s for s in node.inputs}
    _link_or_set(links, sock["Factor_Float"], fac)
    _link_or_set(links, sock["A_Color"], a)
    _link_or_set(links, sock["B_Color"], b)
    return next(s for s in node.outputs if s.identifier == "Result_Color")


def _link_or_set(links, socket, value):
    if isinstance(value, bpy.types.NodeSocket):
        links.new(value, socket)
    elif isinstance(value, (int, float)):
        socket.default_value = value
    else:
        socket.default_value = (*value, 1.0) if len(value) == 3 else value


def _mtoon_inputs(src: bpy.types.Material):
    """(image, base_factor_rgba, alpha_mode, alpha_cutoff) from the VRM add-on's MToon data."""
    try:
        ext = src.vrm_addon_extension.mtoon1
        pbr = ext.pbr_metallic_roughness
        return (pbr.base_color_texture.index.source, tuple(pbr.base_color_factor),
                ext.alpha_mode, float(ext.alpha_cutoff))
    except AttributeError:
        return (None, (1.0, 1.0, 1.0, 1.0), "OPAQUE", 0.5)


def _alpha_socket(nodes, links, tex, factor_a, mode, cutoff, loc):
    if mode == "OPAQUE" or tex is None:
        return None
    alpha = tex.outputs["Alpha"]
    if factor_a < 1.0:
        mul = nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.location = (loc[0] - 200, loc[1])
        links.new(alpha, mul.inputs[0])
        mul.inputs[1].default_value = factor_a
        alpha = mul.outputs[0]
    if mode == "MASK":
        gt = nodes.new("ShaderNodeMath")
        gt.operation = "GREATER_THAN"
        gt.location = loc
        links.new(alpha, gt.inputs[0])
        gt.inputs[1].default_value = cutoff
        alpha = gt.outputs[0]
    return alpha


def _finish(mat, nodes, links, surface, alpha, mode, loc):
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (loc[0] + 400, loc[1])
    if alpha is None:
        links.new(surface, out.inputs["Surface"])
        mat.surface_render_method = "DITHERED"
        return
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (loc[0], loc[1] - 150)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (loc[0] + 200, loc[1])
    links.new(alpha, mix.inputs["Fac"])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(surface, mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    mat.surface_render_method = "BLENDED" if mode == "BLEND" else "DITHERED"


# ---------------------------------------------------------------- materials

def make_cel_material(
    name: str,
    base: Color,
    shadow: Color,
    threshold: float = 0.5,
    softness: float = 0.03,
) -> bpy.types.Material:
    """Flat-color two-tone cel material (sRGB colors). Used by the render test."""
    base_l, shadow_l = srgb_to_linear(base), srgb_to_linear(shadow)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    fac = _light_factor(nodes, links, threshold, softness, (-800, 0))
    col = _mix(nodes, links, "MIX", fac, shadow_l, base_l, (-200, 0))
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (0, 0)
    links.new(col, emission.inputs["Color"])
    _finish(mat, nodes, links, emission.outputs[0], None, "OPAQUE", (200, 0))
    return mat


def _light_factor(nodes, links, threshold, softness, loc):
    """0 in shadow, 1 in light, with a soft band of +-softness around threshold."""
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.location = loc
    to_rgb = nodes.new("ShaderNodeShaderToRGB")
    to_rgb.location = (loc[0] + 200, loc[1])
    bw = nodes.new("ShaderNodeRGBToBW")
    bw.location = (loc[0] + 400, loc[1])
    rng = nodes.new("ShaderNodeMapRange")
    rng.location = (loc[0] + 600, loc[1])
    rng.clamp = True
    rng.inputs["From Min"].default_value = max(0.0, threshold - softness)
    rng.inputs["From Max"].default_value = min(1.0, threshold + softness)
    links.new(diffuse.outputs[0], to_rgb.inputs[0])
    links.new(to_rgb.outputs["Color"], bw.inputs[0])
    links.new(bw.outputs[0], rng.inputs["Value"])
    return rng.outputs["Result"]


def _rim_factor(nodes, links, strength: float, loc):
    """Directional rim: silhouette band (facing) x normal pointing toward RIM_DIRECTION."""
    weight = nodes.new("ShaderNodeLayerWeight")
    weight.location = loc
    weight.inputs["Blend"].default_value = 0.5
    band = nodes.new("ShaderNodeMapRange")
    band.location = (loc[0] + 200, loc[1])
    band.clamp = True
    band.inputs["From Min"].default_value = 0.62
    band.inputs["From Max"].default_value = 0.72
    links.new(weight.outputs["Facing"], band.inputs["Value"])

    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = (loc[0], loc[1] - 250)
    to_cam = nodes.new("ShaderNodeVectorTransform")
    to_cam.vector_type = "NORMAL"
    to_cam.convert_from = "WORLD"
    to_cam.convert_to = "CAMERA"
    to_cam.location = (loc[0] + 200, loc[1] - 250)
    links.new(geometry.outputs["Normal"], to_cam.inputs["Vector"])
    dot = nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.location = (loc[0] + 400, loc[1] - 250)
    links.new(to_cam.outputs["Vector"], dot.inputs[0])
    length = sum(c * c for c in RIM_DIRECTION) ** 0.5
    dot.inputs[1].default_value = tuple(c / length for c in RIM_DIRECTION)
    side = nodes.new("ShaderNodeMapRange")
    side.location = (loc[0] + 600, loc[1] - 250)
    side.clamp = True
    side.inputs["From Min"].default_value = -0.05
    side.inputs["From Max"].default_value = 0.45
    links.new(dot.outputs["Value"], side.inputs["Value"])

    mul = nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.location = (loc[0] + 800, loc[1] - 100)
    links.new(band.outputs["Result"], mul.inputs[0])
    links.new(side.outputs["Result"], mul.inputs[1])
    scale = nodes.new("ShaderNodeMath")
    scale.operation = "MULTIPLY"
    scale.location = (loc[0] + 1000, loc[1] - 100)
    links.new(mul.outputs[0], scale.inputs[0])
    scale.inputs[1].default_value = strength
    return scale.outputs[0]


def _luminance(c_linear) -> float:
    return 0.2126 * c_linear[0] + 0.7152 * c_linear[1] + 0.0722 * c_linear[2]


def _recolor(nodes, links, color, tint, hsv, loc, colorize=None, mean_lum: float = 0.5):
    """Optional recolor: ``colorize`` (sRGB target: texture luminance / mean luminance x target,
    keeping painted shading), then HSV adjust (hue 0.5 = unchanged), then sRGB tint multiply."""
    if colorize is not None:
        bw = nodes.new("ShaderNodeRGBToBW")
        bw.location = (loc[0] - 400, loc[1] + 200)
        _link_or_set(links, bw.inputs[0], color)
        ratio = nodes.new("ShaderNodeMath")
        ratio.operation = "DIVIDE"
        ratio.location = (loc[0] - 200, loc[1] + 200)
        links.new(bw.outputs[0], ratio.inputs[0])
        ratio.inputs[1].default_value = max(mean_lum, 1e-3)
        target = srgb_to_linear(tuple(colorize))
        color = _mix(nodes, links, "MULTIPLY", 1.0, (1.0, 1.0, 1.0), target, (loc[0], loc[1] + 200))
        scaled = nodes.new("ShaderNodeVectorMath")
        scaled.operation = "SCALE"
        scaled.location = (loc[0] + 200, loc[1] + 200)
        links.new(color, scaled.inputs[0])
        links.new(ratio.outputs[0], scaled.inputs["Scale"])
        color = scaled.outputs["Vector"]
    if hsv is not None:
        hs = nodes.new("ShaderNodeHueSaturation")
        hs.location = loc
        hs.inputs["Hue"].default_value = hsv[0]
        hs.inputs["Saturation"].default_value = hsv[1]
        hs.inputs["Value"].default_value = hsv[2]
        _link_or_set(links, hs.inputs["Color"], color)
        color = hs.outputs["Color"]
    if tint is not None:
        color = _mix(nodes, links, "MULTIPLY", 1.0, color, srgb_to_linear(tuple(tint)),
                     (loc[0] + 200, loc[1]))
    return color


def recolor_srgb(c: Color, tint=None, hsv=None, colorize=None) -> Color:
    """Python equivalent of ``_recolor`` for flat colors (outline colors)."""
    if colorize is not None:
        c = tuple(colorize)
    if hsv is not None:
        h, s, v = colorsys.rgb_to_hsv(*c)
        c = colorsys.hsv_to_rgb((h + hsv[0] - 0.5) % 1.0, min(1.0, s * hsv[1]), min(1.0, v * hsv[2]))
    if tint is not None:
        c = tuple(a * b for a, b in zip(c, tint))
    return c


def build_toon_material(src: bpy.types.Material, profile: ToonProfile, name: str | None = None,
                        alpha_scale: float = 1.0, tint=None, hsv=None,
                        colorize=None) -> bpy.types.Material:
    """Create/rebuild ``wg_<src>``: texture-driven cel shading from an MToon source.

    ``alpha_scale`` < 1 makes a see-through variant (used for features drawn over hair).
    ``tint``/``hsv`` recolor the base (see ``wogen.bl.outfit.recolor``).
    """
    name = name or f"wg_{src.name}"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat[SOURCE_KEY] = src.name
    mat.use_nodes = True
    mat.use_backface_culling = False
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()

    image, factor, mode, cutoff = _mtoon_inputs(src)
    tex = None
    lit: object = factor[:3]
    if image is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.location = (-1400, 200)
        lit = tex.outputs["Color"]
        if factor[:3] != (1.0, 1.0, 1.0):
            lit = _mix(nodes, links, "MULTIPLY", 1.0, lit, factor[:3], (-1100, 200))
    if tint is not None or hsv is not None or colorize is not None:
        mean_lum = _luminance(srgb_to_linear(image_mean_srgb(image))) if image else 0.5
        lit = _recolor(nodes, links, lit, tint, hsv, (-1100, 500), colorize, mean_lum)

    if profile.lit:
        shadow = _mix(nodes, links, "MULTIPLY", 1.0, lit, srgb_to_linear(profile.shadow_tint),
                      (-800, 350))
        fac = _light_factor(nodes, links, profile.threshold, profile.softness, (-1400, -200))
        col = _mix(nodes, links, "MIX", fac, shadow, lit, (-500, 200))
        if profile.rim > 0:
            rim = _rim_factor(nodes, links, profile.rim, (-1000, -500))
            # Rim = a lighter version of the surface's own color (keeps hue on dark hair).
            lighter = nodes.new("ShaderNodeGamma")
            lighter.location = (-600, 600)
            _link_or_set(links, lighter.inputs["Color"], lit)
            lighter.inputs["Gamma"].default_value = 0.4
            rim_col = _mix(nodes, links, "MULTIPLY", 1.0, lighter.outputs["Color"],
                           srgb_to_linear(profile.rim_color), (-400, 600))
            col = _mix(nodes, links, "SCREEN", rim, col, rim_col, (-250, 200))
    else:
        col = lit

    if profile.backface_tint is not None:
        geometry = nodes.new("ShaderNodeNewGeometry")
        geometry.location = (-400, 500)
        inner = _mix(nodes, links, "MULTIPLY", 1.0, lit, srgb_to_linear(profile.backface_tint),
                     (-250, 450))
        col = _mix(nodes, links, "MIX", geometry.outputs["Backfacing"], col, inner, (-100, 350))

    emission = nodes.new("ShaderNodeEmission")
    emission.location = (0, 200)
    _link_or_set(links, emission.inputs["Color"], col)
    alpha = _alpha_socket(nodes, links, tex, factor[3], mode, cutoff, (-200, -100))
    if alpha_scale < 1.0:
        scale = nodes.new("ShaderNodeMath")
        scale.operation = "MULTIPLY"
        scale.location = (0, -100)
        _link_or_set(links, scale.inputs[0], alpha if alpha is not None else 1.0)
        scale.inputs[1].default_value = alpha_scale
        alpha, mode = scale.outputs[0], "BLEND"
    _finish(mat, nodes, links, emission.outputs[0], alpha, mode, (200, 200))
    return mat


def build_outline_material(src: bpy.types.Material, profile: ToonProfile, tint=None,
                           hsv=None, colorize=None) -> bpy.types.Material:
    """Create/rebuild ``wgo_<src>``: back-face hull colored from the source texture."""
    name = f"wgo_{src.name}"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat[SOURCE_KEY] = src.name
    mat.use_nodes = True
    mat.use_backface_culling = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()

    image, factor, mode, cutoff = _mtoon_inputs(src)
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (0, 0)
    if not profile.outline:
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        _finish(mat, nodes, links, transparent.outputs[0], None, "OPAQUE", (0, 0))
        mat.surface_render_method = "DITHERED"
        return mat

    mean = image_mean_srgb(image)
    base = recolor_srgb(tuple(m * f for m, f in zip(mean, factor[:3])), tint, hsv, colorize)
    emission.inputs["Color"].default_value = (*srgb_to_linear(outline_color_for(base)), 1.0)
    tex = None
    if image is not None and mode != "OPAQUE":
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.location = (-600, -100)
    alpha = _alpha_socket(nodes, links, tex, factor[3], mode, cutoff, (-200, -100))
    _finish(mat, nodes, links, emission.outputs[0], alpha, mode, (200, 0))
    return mat


def add_flat_outline(obj: bpy.types.Object, color: Color, width: float = 0.0025) -> None:
    """Inverted-hull outline in one flat sRGB color, for non-character meshes (props).

    Width is in the mesh's local units, so keep object scale at 1 (bake sizes into the mesh).
    """
    _strip_outlines(obj)
    name = f"wgo_flat_{obj.name}"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.use_backface_culling = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*srgb_to_linear(outline_color_for(color)), 1.0)
    _finish(mat, nodes, links, emission.outputs[0], None, "OPAQUE", (200, 0))
    n = len(obj.data.materials)
    obj.data.materials.append(mat)
    md = obj.modifiers.new(OUTLINE_MOD, "SOLIDIFY")
    md.thickness = width
    md.offset = 1.0
    md.use_flip_normals = True
    md.use_rim = False
    md.use_even_offset = False
    md.material_offset = n


# ---------------------------------------------------------------- apply / remove

def apply_toon(meshes: list[bpy.types.Object] | None = None, outline: bool = True) -> str:
    """Convert character meshes to wogen cel materials (+ outlines). Idempotent."""
    from . import overlay
    if meshes is None:
        from .character import character_meshes
        meshes = character_meshes()
    converted: dict[str, str] = {}
    restore_overlay = []
    for obj in meshes:
        params = overlay.saved_params(obj)
        if params is not None:
            overlay.remove(obj, forget=False)
            restore_overlay.append(params)
        _strip_outlines(obj)
        sources = [_source_of(m) for m in obj.data.materials]
        recolors = [material_recolor(obj, src.name) if src else {} for src in sources]
        for i, src in enumerate(sources):
            if src is None:
                continue
            # Keep the unassigned MToon source alive (orphan purge / .blend save would drop
            # it, breaking remove_toon(), VRM export and recoloring).
            src.use_fake_user = True
            obj.data.materials[i] = build_toon_material(src, profile_for(obj.name, src.name),
                                                        **recolors[i])
            converted[src.name] = classify(src.name)
        if outline:
            _add_outline(obj, sources, recolors)
        if obj.name in SMOOTH_MESHES:
            add_smoothing(obj)
    for params in restore_overlay:
        overlay.features_through_hair(**params)
    counts: dict[str, int] = {}
    for cls in converted.values():
        counts[cls] = counts.get(cls, 0) + 1
    return f"toon applied to {len(meshes)} meshes, {len(converted)} materials {counts}"


def remove_toon(meshes: list[bpy.types.Object] | None = None) -> None:
    """Restore the original (MToon) materials and the VRM add-on's look (outlines not restored)."""
    from . import overlay
    if meshes is None:
        from .character import character_meshes
        meshes = character_meshes()
    for obj in meshes:
        if overlay.saved_params(obj) is not None or obj.modifiers.get(overlay.MODIFIER):
            overlay.remove(obj)
        _strip_outlines(obj)
        for i, m in enumerate(obj.data.materials):
            src = _source_of(m)
            if src is not None:
                obj.data.materials[i] = src


def _source_of(mat: bpy.types.Material | None) -> bpy.types.Material | None:
    if mat is None:
        return None
    src_name = mat.get(SOURCE_KEY)
    return bpy.data.materials.get(src_name) if src_name else mat


def add_smoothing(obj: bpy.types.Object, levels: int = 1) -> None:
    """Weld + one level of subdivision right after the armature (idempotent), so the posed
    surface is smoothed and the outline hull follows the smooth surface."""
    weld = obj.modifiers.get(WELD_MOD) or obj.modifiers.new(WELD_MOD, "WELD")
    weld.merge_threshold = 1e-5
    sub = obj.modifiers.get(SUBSURF_MOD) or obj.modifiers.new(SUBSURF_MOD, "SUBSURF")
    sub.render_levels = levels
    # Headless, nothing shows the viewport, but every frame change (bakes, foot locking)
    # evaluates it: smoothing there doubled clip times. Final renders use render_levels.
    sub.levels = 0 if bpy.app.background else levels
    weld.show_viewport = not bpy.app.background
    arm_mods = [i for i, md in enumerate(obj.modifiers) if md.type == "ARMATURE"]
    after = arm_mods[0] + 1 if arm_mods else 0
    obj.modifiers.move(obj.modifiers.find(WELD_MOD), after)
    obj.modifiers.move(obj.modifiers.find(SUBSURF_MOD), after + 1)


def _strip_outlines(obj: bpy.types.Object) -> None:
    """Remove our hull + outline slots, and the VRM add-on's MToon outline modifiers."""
    for md in list(obj.modifiers):
        is_vrm_outline = (md.type == "NODES" and md.node_group is not None
                          and md.node_group.name.startswith("VRM Add-on MToon"))
        if md.name == OUTLINE_MOD or is_vrm_outline:
            obj.modifiers.remove(md)
    mats = obj.data.materials
    for i in range(len(mats) - 1, -1, -1):
        if mats[i] is not None and mats[i].name.startswith("wgo_"):
            mats.pop(index=i)


RECOLOR_KEY = "wg_recolor"


def material_recolor(obj: bpy.types.Object, material_name: str) -> dict:
    """Recolor kwargs for one material: object-wide ``wg_tint``/``wg_hsv`` (garments) plus the
    first ``wg_recolor`` rule whose key is a substring of the material name, e.g.
    ``{"EyeIris": {"colorize": [..]}, "SKIN": {"tint": [..]}}`` (JSON string property)."""
    import json

    from ..garments import strip_suffix
    out = {}
    if obj.get("wg_tint") is not None:
        out["tint"] = tuple(obj["wg_tint"])
    if obj.get("wg_hsv") is not None:
        out["hsv"] = tuple(obj["wg_hsv"])
    rules = json.loads(obj[RECOLOR_KEY]) if obj.get(RECOLOR_KEY) else {}
    name = strip_suffix(material_name)
    # Most specific (longest) matching key wins, e.g. "CLOTH_03" (one layer) over "CLOTH".
    for key in sorted(rules, key=len, reverse=True):
        if key in name:
            out.update({k: tuple(v) for k, v in rules[key].items() if v is not None})
            break
    return out


def _add_outline(obj: bpy.types.Object, sources: list[bpy.types.Material | None],
                 recolors: list[dict] | None = None) -> None:
    profiles = [profile_for(obj.name, s.name) if s else None for s in sources]
    widths = [p.outline_width for p in profiles if p and p.outline]
    if not widths:
        return
    n = len(sources)
    recolors = recolors or [{} for _ in sources]
    for src, prof, rc in zip(sources, profiles, recolors):
        if src is None:
            obj.data.materials.append(None)
        else:
            obj.data.materials.append(build_outline_material(src, prof, **rc))
    md = obj.modifiers.new(OUTLINE_MOD, "SOLIDIFY")
    md.thickness = max(widths) * MESH_OUTLINE_SCALE.get(obj.name, 1.0)
    md.offset = 1.0
    md.use_flip_normals = True
    md.use_rim = False
    md.use_even_offset = False
    md.material_offset = n
