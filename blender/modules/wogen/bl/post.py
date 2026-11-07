"""Compositor post-processing: bloom, chromatic aberration, grade, vignette.

Blender 5.x: the compositor is a node group assigned to ``scene.compositing_node_group``,
and most node options are menu/value input sockets rather than properties.

Chat usage::

    from wogen.bl import post
    post.setup_post()                              # defaults (style guide look)
    post.setup_post(PostSettings(bloom=0.6, vignette=0.25))
    post.disable_post()
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import bpy

GROUP = "wg_post"


@dataclass
class PostSettings:
    bloom: float = 0.22              # glare strength (0 disables)
    bloom_threshold: float = 0.93    # only near-white highlights bloom (toon colors are <= 1)
    bloom_size: float = 0.5
    dispersion: float = 0.004        # chromatic aberration (0 disables)
    saturation: float = 1.05
    lift: tuple[float, float, float] = (1.0, 1.0, 1.008)     # barely-cool shadows
    gain: tuple[float, float, float] = (1.02, 1.0, 0.985)    # warm highlights
    vignette: float = 0.18           # darkening at the corners (0 disables)


def _input(node, name: str, socket_type: str | None = None):
    for s in node.inputs:
        if s.name == name and (socket_type is None or s.type == socket_type):
            return s
    raise KeyError(f"{node.bl_idname} has no input {name!r} ({socket_type})")


def _set_vector(socket, xy: tuple[float, float]) -> None:
    """Set the first two components of a 2D/3D vector socket."""
    value = list(socket.default_value)
    value[0], value[1] = xy
    socket.default_value = value


def build_post_group(settings: PostSettings) -> bpy.types.NodeTree:
    ng = bpy.data.node_groups.get(GROUP)
    if ng is None:
        ng = bpy.data.node_groups.new(GROUP, "CompositorNodeTree")
        ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    nodes, links = ng.nodes, ng.links
    nodes.clear()
    x = 0

    def place(node):
        nonlocal x
        node.location = (x, 0)
        x += 250
        return node

    layers = place(nodes.new("CompositorNodeRLayers"))
    image = layers.outputs["Image"]

    if settings.bloom > 0:
        glare = place(nodes.new("CompositorNodeGlare"))
        _input(glare, "Type").default_value = "Bloom"
        _input(glare, "Quality").default_value = "High"
        _input(glare, "Threshold").default_value = settings.bloom_threshold
        _input(glare, "Strength").default_value = settings.bloom
        _input(glare, "Size").default_value = settings.bloom_size
        links.new(image, _input(glare, "Image"))
        image = glare.outputs["Image"]

    if settings.dispersion > 0:
        lens = place(nodes.new("CompositorNodeLensdist"))
        _input(lens, "Dispersion").default_value = settings.dispersion
        _input(lens, "Fit").default_value = True
        links.new(image, _input(lens, "Image"))
        image = lens.outputs["Image"]

    balance = place(nodes.new("CompositorNodeColorBalance"))
    _input(balance, "Lift", "RGBA").default_value = (*settings.lift, 1.0)
    _input(balance, "Gain", "RGBA").default_value = (*settings.gain, 1.0)
    links.new(image, _input(balance, "Image"))
    image = balance.outputs["Image"]

    huesat = place(nodes.new("CompositorNodeHueSat"))
    _input(huesat, "Saturation").default_value = settings.saturation
    links.new(image, _input(huesat, "Image"))
    image = huesat.outputs["Image"]

    if settings.vignette > 0:
        ellipse = nodes.new("CompositorNodeEllipseMask")
        ellipse.location = (x - 250, -300)
        _set_vector(_input(ellipse, "Size"), (0.95, 0.95))
        blur = nodes.new("CompositorNodeBlur")
        blur.location = (x, -300)
        _set_vector(_input(blur, "Size"), (300, 300))
        links.new(ellipse.outputs["Mask"], _input(blur, "Image"))
        # v = 1 - strength * (1 - mask)
        inv = nodes.new("ShaderNodeMath")
        inv.operation = "MULTIPLY_ADD"
        inv.location = (x + 250, -300)
        links.new(blur.outputs["Image"], inv.inputs[0])
        inv.inputs[1].default_value = settings.vignette
        inv.inputs[2].default_value = 1.0 - settings.vignette
        mix = place(nodes.new("ShaderNodeMix"))
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        sock = {s.identifier: s for s in mix.inputs}
        sock["Factor_Float"].default_value = 1.0
        links.new(image, sock["A_Color"])
        links.new(inv.outputs[0], sock["B_Color"])
        image = next(s for s in mix.outputs if s.identifier == "Result_Color")

    out = place(nodes.new("NodeGroupOutput"))
    links.new(image, out.inputs[0])
    ng["wg_settings"] = {k: list(v) if isinstance(v, tuple) else v
                         for k, v in asdict(settings).items()}
    return ng


def setup_post(settings: PostSettings | None = None,
               scene: bpy.types.Scene | None = None) -> str:
    scene = scene or bpy.context.scene
    settings = settings or PostSettings()
    scene.compositing_node_group = build_post_group(settings)
    scene.render.use_compositing = True
    return f"post: {asdict(settings)}"


def disable_post(scene: bpy.types.Scene | None = None) -> None:
    scene = scene or bpy.context.scene
    scene.compositing_node_group = None
