"""Rendering helpers."""

from __future__ import annotations

import math

import bpy

from .toon import make_cel_material


def _clear_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def apply_toon_color_management(scene: bpy.types.Scene) -> None:
    """Show material colors as authored. AgX/Filmic tone mapping desaturates flat cel colors."""
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def _ensure_object(name: str, data, scene: bpy.types.Scene) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
    return obj


def setup_world(scene: bpy.types.Scene, background=(0.16, 0.15, 0.19), ambient=0.25) -> None:
    """Camera sees ``background`` (sRGB); lighting gets a dim neutral ambient.

    The ambient level feeds the cel ramp (via Shader-to-RGB), so keep it low and neutral.
    """
    from .toon import srgb_to_linear
    world = bpy.data.worlds.get("wg_world") or bpy.data.worlds.new("wg_world")
    scene.world = world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    nodes.clear()
    light_path = nodes.new("ShaderNodeLightPath")
    bg_cam = nodes.new("ShaderNodeBackground")
    bg_cam.inputs["Color"].default_value = (*srgb_to_linear(background), 1.0)
    bg_light = nodes.new("ShaderNodeBackground")
    bg_light.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    bg_light.inputs["Strength"].default_value = ambient
    mix = nodes.new("ShaderNodeMixShader")
    out = nodes.new("ShaderNodeOutputWorld")
    links.new(light_path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    links.new(bg_light.outputs[0], mix.inputs[1])
    links.new(bg_cam.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])


def setup_lights(scene: bpy.types.Scene, key_azimuth: float = 35.0, key_elevation: float = 40.0):
    """Key sun (no cast shadows: clean anime faces) + cool rim/back light."""
    key = _ensure_object("wg_key", bpy.data.lights.new("wg_key", "SUN"), scene)
    key.data.energy = 3.0
    key.data.use_shadow = False
    key.data.color = (1.0, 0.97, 0.93)
    # Sun points along its local -Z; tilt it so light arrives from the front (-Y), then yaw.
    key.rotation_euler = (math.radians(90 - key_elevation), 0.0, math.radians(key_azimuth))

    rim = _ensure_object("wg_rim", bpy.data.lights.new("wg_rim", "SUN"), scene)
    rim.data.energy = 1.5
    rim.data.use_shadow = False
    rim.data.color = (0.75, 0.85, 1.0)
    rim.rotation_euler = (math.radians(-60), 0.0, math.radians(-30))

    for name in ("Light",):   # Blender's startup light
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.type == "LIGHT":
            obj.hide_render = obj.hide_viewport = True


def portrait_camera(scene: bpy.types.Scene, armature: bpy.types.Object, framing: str = "bust",
                    focal_mm: float = 85.0, view_yaw: float = 0.0) -> bpy.types.Object:
    """Camera aimed at the character. framing: 'face' | 'bust' | 'full'.

    ``view_yaw`` orbits the camera (degrees; + moves it toward the character's left,
    e.g. 35 for a three-quarter view of her left side). Face/bust follow the posed head;
    full fits the posed bounds of every visible character mesh (hair, skirts, legs) at the
    current render aspect, so sitting/crouching poses stay in frame.
    """
    from mathutils import Matrix, Vector
    head = armature.matrix_world @ armature.pose.bones["J_Bip_C_Head"].head
    height = head.z + 0.15
    frames = {   # (look-at point, vertical extent to fit in metres)
        "face": (head + Vector((0, 0, 0.07)), 0.34),
        "bust": (head + Vector((0, 0, -0.06)), 0.66),
    }
    if framing == "full":
        frames["full"] = _fit_full(scene, armature, view_yaw) or             (Vector((head.x, head.y, height / 2)), height * 1.1)
    target, extent = frames[framing]
    cam_data = bpy.data.cameras.get("wg_cam") or bpy.data.cameras.new("wg_cam")
    cam = _ensure_object("wg_cam", cam_data, scene)
    cam_data.lens = focal_mm
    cam_data.sensor_fit = "VERTICAL"
    distance = extent / 2 / math.tan(math.atan(cam_data.sensor_height / 2 / focal_mm))
    offset = Vector((0.0, -distance, 0.02 * distance))
    cam.location = target + Matrix.Rotation(math.radians(view_yaw), 3, "Z") @ offset
    direction = target - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    return cam


def _fit_full(scene, armature, view_yaw: float, margin: float = 1.08):
    """(look-at point, vertical extent) fitting all visible character meshes as posed."""
    from mathutils import Matrix, Vector
    from .character import character_meshes
    depsgraph = bpy.context.evaluated_depsgraph_get()
    corners = []
    for obj in character_meshes():
        if obj.hide_render:
            continue
        ev = obj.evaluated_get(depsgraph)
        corners += [ev.matrix_world @ Vector(c) for c in ev.bound_box]
    if not corners:
        return None
    side = Matrix.Rotation(math.radians(view_yaw), 3, "Z") @ Vector((1.0, 0.0, 0.0))
    xs = [c.dot(side) for c in corners]
    zs = [c.z for c in corners]
    lo, hi = min(zs), max(zs)
    left, right = min(xs), max(xs)
    aspect = scene.render.resolution_x / max(1, scene.render.resolution_y)
    extent = max(hi - lo, (right - left) / aspect) * margin
    centre = sum(corners, Vector()) / len(corners)
    across = (left + right) / 2 - centre.dot(side)
    target = Vector((centre.x, centre.y, (lo + hi) / 2)) + side * across
    return target, extent


def portrait(framing: str = "bust", resolution: tuple[int, int] = (1600, 2000),
             out_path: str | None = None, post: bool = True, pose="idle",
             view_yaw: float = 0.0) -> str:
    """Portrait of the loaded character. Renders to ``out_path`` if given.

    ``pose``: pose name/dict/list for ``wogen.bl.pose.apply_pose``; ``None`` keeps the
    current pose. ``post`` enables the compositor look (see ``wogen.bl.post``).
    """
    from . import post as post_mod
    from .character import character_armature
    from .pose import apply_pose
    scene = bpy.context.scene
    arm = character_armature()
    if arm is None:
        raise RuntimeError("No character loaded (wogen.bl.character.import_base())")
    remove_turntable()
    if pose is not None:
        apply_pose(pose, armature=arm)
    scene.render.engine = "BLENDER_EEVEE"
    apply_toon_color_management(scene)
    setup_world(scene)
    setup_lights(scene)
    scene.render.resolution_x, scene.render.resolution_y = resolution   # full framing uses aspect
    scene.render.resolution_percentage = 100
    portrait_camera(scene, arm, framing, view_yaw=view_yaw)
    if post:
        post_mod.setup_post(scene=scene)
    else:
        post_mod.disable_post(scene)
    configure_still(scene, out_path or "")
    if out_path:
        bpy.ops.render.render(write_still=True)
        return out_path
    return "portrait set up (camera wg_cam)"


def configure_video(scene: bpy.types.Scene, out_path: str, fps: int = 24) -> None:
    """MP4 / H.264 output (Blender 5.x: media_type VIDEO + FFMPEG)."""
    r = scene.render                       # H.264 needs even frame sizes: round odd ones up
    r.resolution_x += r.resolution_x % 2
    r.resolution_y += r.resolution_y % 2
    settings = scene.render.image_settings
    settings.media_type = "VIDEO"
    settings.file_format = "FFMPEG"
    ff = scene.render.ffmpeg
    ff.format = "MPEG4"
    ff.codec = "H264"
    ff.constant_rate_factor = "HIGH"
    ff.ffmpeg_preset = "GOOD"
    scene.render.fps = fps
    scene.render.fps_base = 1.0
    scene.render.filepath = out_path
    scene.render.use_file_extension = False


def configure_still(scene: bpy.types.Scene, out_path: str) -> None:
    settings = scene.render.image_settings
    settings.media_type = "IMAGE"
    settings.file_format = "PNG"
    scene.render.filepath = out_path


def turntable(frames: int = 96, framing: str = "full", resolution: tuple[int, int] = (1080, 1350),
              out_path: str | None = None, fps: int = 24, post: bool = True,
              pose="idle") -> str:
    """360° orbit of the camera around the character, rendered to MP4 if ``out_path`` is given.

    The camera is parented to a pivot whose Z rotation is driven by the frame number
    (a simple-expression driver: no keyframes, no Python auto-exec needed).
    """
    from mathutils import Vector

    from .character import character_armature
    scene = bpy.context.scene
    portrait(framing, resolution=resolution, post=post, pose=pose)
    arm = character_armature()
    head = arm.matrix_world @ arm.pose.bones["J_Bip_C_Head"].head
    pivot = bpy.data.objects.get("wg_turntable")
    if pivot is None:
        pivot = bpy.data.objects.new("wg_turntable", None)
        scene.collection.objects.link(pivot)
    pivot.driver_remove("rotation_euler", 2)
    pivot.rotation_euler = (0.0, 0.0, 0.0)
    pivot.location = Vector((head.x, head.y, 0.0))
    bpy.context.view_layer.update()

    cam = scene.camera
    world = cam.matrix_world.copy()
    cam.parent = pivot
    cam.matrix_parent_inverse = pivot.matrix_world.inverted()
    cam.matrix_world = world

    driver = pivot.driver_add("rotation_euler", 2).driver
    driver.type = "SCRIPTED"
    driver.expression = f"(frame - 1) * {2 * math.pi / frames!r}"

    scene.frame_start, scene.frame_end = 1, frames
    scene.frame_set(1)
    if out_path:
        configure_video(scene, out_path, fps)
        bpy.ops.render.render(animation=True)
        configure_still(scene, "")
        return out_path
    return f"turntable set up: {frames} frames, camera parented to wg_turntable"


def clip(out_path: str, framing: str = "bust", resolution: tuple[int, int] = (1080, 1350),
         post: bool = True, view_yaw: float = 0.0, fps: int | None = None,
         follow: bool = False) -> str:
    """Render the scene's current animation (frame range) to MP4 from a portrait camera.

    Pair with ``anim.preset(...)`` / ``anim.sequence(...)`` and ``physics.bake()``.
    ``follow`` moves the camera with her hips horizontally (for presets that travel, e.g.
    ``walk``); framing is set on the first frame.
    """
    scene = bpy.context.scene
    start = scene.frame_start
    scene.frame_set(start)
    portrait(framing, resolution=resolution, post=post, pose=None, view_yaw=view_yaw)
    if follow:
        follow_camera(scene)
    try:
        configure_video(scene, out_path, fps or scene.render.fps)
        bpy.ops.render.render(animation=True)
    finally:
        configure_still(scene, "")
        if follow:
            remove_follow()
        scene.frame_set(start)
    return out_path


FOLLOW = "wg_follow"


def follow_camera(scene: bpy.types.Scene) -> None:
    """Parent ``wg_cam`` to a pivot keyed every frame to the hips' horizontal travel."""
    from .character import character_armature
    arm = character_armature()
    cam = scene.camera
    pivot = _ensure_object(FOLLOW, None, scene)
    pivot.location = (0.0, 0.0, 0.0)
    cam.parent = pivot
    cam.matrix_parent_inverse = pivot.matrix_world.inverted()

    def hips_xy():
        h = arm.matrix_world @ arm.pose.bones["J_Bip_C_Hips"].head
        return h.x, h.y
    current = scene.frame_current
    x0, y0 = hips_xy()                     # relative to the frame the camera was framed on
    for f in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(f)
        x, y = hips_xy()
        pivot.location = (x - x0, y - y0, 0.0)
        pivot.keyframe_insert("location", frame=f)
    scene.frame_set(current)


def remove_follow() -> None:
    pivot = bpy.data.objects.get(FOLLOW)
    if pivot is None:
        return
    for child in list(pivot.children):
        world = child.matrix_world.copy()
        child.parent = None
        child.matrix_world = world
    bpy.data.objects.remove(pivot, do_unlink=True)


def remove_turntable() -> None:
    cam = bpy.data.objects.get("wg_cam")
    if cam is not None and cam.parent is not None:
        world = cam.matrix_world.copy()
        cam.parent = None
        cam.matrix_world = world
    pivot = bpy.data.objects.get("wg_turntable")
    if pivot is not None:
        bpy.data.objects.remove(pivot, do_unlink=True)


def contact_sheet(variants: list[tuple[str, "callable"]], out_path: str, framing: str | None = "face",
                  cell: int = 512, cols: int = 4) -> str:
    """Render one cell per (label, apply_fn) and tile them row-major into a single PNG.

    ``apply_fn`` mutates the scene (e.g. sets an expression) before its cell renders.
    ``framing=None`` keeps the current camera/scene (e.g. a turntable). Cells are square.
    Returns the labels in grid order so chat can map cells to names.
    """
    import os
    import shutil

    import numpy as np

    from ..paths import scratch_dir
    scene = bpy.context.scene
    if framing is not None:
        portrait(framing, resolution=(cell, cell))
    else:
        scene.render.resolution_x = scene.render.resolution_y = cell
        scene.render.resolution_percentage = 100
    rows = math.ceil(len(variants) / cols)
    sheet = None
    tmp_dir = str(scratch_dir("sheet"))
    configure_still(scene, "")
    for i, (_, apply_fn) in enumerate(variants):
        apply_fn()
        path = os.path.join(tmp_dir, f"{i:03d}.png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(path)
        px = np.empty(cell * cell * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        bpy.data.images.remove(img)
        px = px.reshape(cell, cell, 4)
        if sheet is None:   # fill empty cells with the background (top-left pixel)
            sheet = np.empty((rows * cell, cols * cell, 4), dtype=np.float32)
            sheet[:] = px[-1, 0]
        r, c = divmod(i, cols)
        # Blender image rows start at the bottom; the sheet's row 0 is the top.
        y0 = (rows - 1 - r) * cell
        sheet[y0:y0 + cell, c * cell:(c + 1) * cell] = px
    out = bpy.data.images.new("wg_sheet", cols * cell, rows * cell, alpha=True)
    out.pixels.foreach_set(sheet.ravel())
    out.filepath_raw = out_path
    out.file_format = "PNG"
    out.save()
    bpy.data.images.remove(out)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    labels = [label for label, _ in variants]
    grid = [labels[i:i + cols] for i in range(0, len(labels), cols)]
    return "\n".join(" | ".join(row) for row in grid)


def expression_sheet(names: list[str] | None = None, out_path: str | None = None,
                     cols: int = 4, cell: int = 512) -> str:
    """Contact sheet of facial expressions (default: all presets except visemes)."""
    from . import face
    from ..paths import OUT_DIR
    if names is None:
        from ..expressions import VISEMES
        names = [n for n in face.list_expressions() if n not in VISEMES]
    out_path = out_path or str(OUT_DIR / "expressions.png")
    variants = [(n, (lambda n=n: face.expression(n))) for n in names]
    try:
        return contact_sheet(variants, out_path, "face", cell, cols)
    finally:
        face.expression("neutral")


def pose_sheet(names: list[str] | None = None, out_path: str | None = None, framing: str = "full",
               cols: int = 4, cell: int = 512) -> str:
    """Contact sheet of body poses (default: every library pose)."""
    from ..paths import OUT_DIR
    from .pose import POSES_DIR, apply_pose, list_poses
    names = names or [n for n in list_poses(POSES_DIR) if n != "t_pose"]
    out_path = out_path or str(OUT_DIR / "poses.png")
    variants = [(n, (lambda n=n: apply_pose(n))) for n in names]
    return contact_sheet(variants, out_path, framing, cell, cols)


def outfit_sheet(sets: list[str] | None = None, out_path: str | None = None, view_yaw: float = 25,
                 cols: int = 5, cell: int = 512) -> str:
    """Contact sheet of harvested outfit sets worn by the loaded character."""
    from ..paths import OUT_DIR
    from . import outfit
    from .character import character_armature
    sets = sets or sorted(outfit.list_sets())
    out_path = out_path or str(OUT_DIR / "outfits.png")
    scene, arm = bpy.context.scene, character_armature()

    def wear(name):
        def fn():
            outfit.equip_set(name)
            portrait_camera(scene, arm, "full", view_yaw=view_yaw)
        return fn
    return contact_sheet([(s, wear(s)) for s in sets], out_path, "full", cell, cols)


def garment_sheet(names: list[str] | None = None, out_path: str | None = None,
                  view_yaw: float = 25, cols: int = 6, cell: int = 384) -> str:
    """One cell per library garment, worn alone (other garments hidden)."""
    from ..paths import OUT_DIR
    from . import outfit
    from .character import character_armature
    names = names or outfit.list_library()
    out_path = out_path or str(OUT_DIR / "garments.png")
    scene, arm = bpy.context.scene, character_armature()

    def wear(name):
        def fn():
            for g in outfit.garments():
                g.hide_render = g.hide_viewport = True
            outfit.equip(name, exclusive=False)
            portrait_camera(scene, arm, "full", view_yaw=view_yaw)
        return fn
    return contact_sheet([(n, wear(n)) for n in names], out_path, "full", cell, cols)


def hair_sheet(names: list[str] | None = None, out_path: str | None = None,
               view_yaws: tuple[float, ...] = (25.0, 150.0), framing: str = "bust",
               cell: int = 448) -> str:
    """Each library hairstyle (columns) from each view angle (rows)."""
    from ..paths import OUT_DIR
    from . import hair
    from .character import character_armature
    names = names or hair.list_styles()
    out_path = out_path or str(OUT_DIR / "hair.png")
    scene, arm = bpy.context.scene, character_armature()

    def show(name, yaw):
        def fn():
            hair.equip(name)
            portrait_camera(scene, arm, framing, view_yaw=yaw)
        return fn
    cells = [(f"{n} @{yaw:g}", show(n, yaw)) for yaw in view_yaws for n in names]
    return contact_sheet(cells, out_path, framing, cell, len(names))


def layer_sheet(name: str, out_path: str | None = None, framing: str = "full",
                view_yaw: float = 25, cell: int = 448) -> str:
    """The garment as-is, then once per texture layer with that layer tinted magenta."""
    from ..paths import OUT_DIR
    from . import outfit
    from .character import character_armature
    out_path = out_path or str(OUT_DIR / f"layers_{name}.png")
    scene, arm = bpy.context.scene, character_armature()
    layers = outfit.list_layers(name)

    def show(key):
        def fn():
            outfit.recolor(name)                      # reset everything
            for entry in layers:
                outfit.recolor(name, layer=entry["key"])
            if key:
                outfit.recolor(name, colorize=(1.0, 0.0, 1.0), layer=key)
            portrait_camera(scene, arm, framing, view_yaw=view_yaw)
        return fn
    variants = [("as is", show(None))] + [(e["key"], show(e["key"])) for e in layers]
    try:
        return contact_sheet(variants, out_path, framing, cell, len(variants))
    finally:
        show(None)()


def render_test(out_path: str, resolution: tuple[int, int] = (640, 360)) -> None:
    """Build a tiny scene (cel-shaded sphere, sun, camera) and render it with EEVEE.

    Proves the headless EEVEE + Shader-to-RGB toon path works on this machine.
    """
    scene = bpy.context.scene
    _clear_scene()

    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=1.0)
    sphere = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    sphere.data.materials.append(
        make_cel_material("test_cel", base=(0.96, 0.71, 0.76), shadow=(0.78, 0.42, 0.52))
    )

    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 3.0
    sun = bpy.data.objects.new("Sun", sun_data)
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(35))
    scene.collection.objects.link(sun)

    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    cam.location = (0.0, -5.0, 0.6)
    cam.rotation_euler = (math.radians(84), 0.0, 0.0)
    scene.collection.objects.link(cam)
    scene.camera = cam

    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.color = (0.05, 0.05, 0.07)

    scene.render.engine = "BLENDER_EEVEE"
    apply_toon_color_management(scene)
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = out_path
    bpy.ops.render.render(write_still=True)
