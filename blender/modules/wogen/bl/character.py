"""Loading and inspecting characters."""

from __future__ import annotations

from pathlib import Path

import bpy

from ..paths import ASSETS_DIR

BASE_DIR = ASSETS_DIR / "base"
CHARACTER_COLLECTION = "wogen_character"
IMPORTED_ACTIONS_KEY = "wg_imported_actions"
VRM_ADDON = "bl_ext.blender_org.vrm"


def ensure_vrm_addon() -> None:
    """Enable the VRM extension (needed in --factory-startup runs, where prefs aren't loaded)."""
    # Note: hasattr(bpy.ops.import_scene, "vrm") is always True (operators resolve lazily).
    if VRM_ADDON in bpy.context.preferences.addons:
        return
    try:
        bpy.ops.preferences.addon_enable(module=VRM_ADDON)
    except Exception as e:   # noqa: BLE001 - surface a clear message
        raise RuntimeError(f"Could not enable {VRM_ADDON}; is the VRM extension installed? ({e})")
    if VRM_ADDON not in bpy.context.preferences.addons:
        raise RuntimeError(f"{VRM_ADDON} could not be enabled")


def prepare(name: str = "base_f01", through_hair: list[str] | None = ("brow",),
            split_outfit: bool = True) -> bpy.types.Object:
    """One call from empty scene to styled character: import, toon, features through hair,
    and (by default) clothing split into separate garments with covered skin hidden."""
    from . import outfit, overlay, toon
    ensure_vrm_addon()
    clear_default_scene()
    armature = import_base(name)
    from .face_shading import setup_face_normals
    setup_face_normals(armature=armature)
    toon.apply_toon()
    if through_hair:
        overlay.features_through_hair(list(through_hair))
    if split_outfit:
        outfit.split()
    return armature


def clear_default_scene() -> None:
    """Remove Blender's startup cube (only if untouched-looking); leaves everything else."""
    cube = bpy.data.objects.get("Cube")
    if cube is not None and cube.type == "MESH" and len(cube.data.vertices) == 8:
        bpy.data.objects.remove(cube, do_unlink=True)


def import_base(name: str = "base_f01", replace: bool = True) -> bpy.types.Object:
    """Import ``assets/base/<name>.vrm`` (or a path to any .vrm) into its own collection;
    returns the armature. With ``replace``, a previously imported character is removed first.
    """
    path = Path(name) if name.lower().endswith(".vrm") else BASE_DIR / f"{name}.vrm"
    name = path.stem
    if not path.is_file():
        raise FileNotFoundError(path)
    ensure_vrm_addon()

    scene = bpy.context.scene
    if replace:
        remove_character()

    coll = bpy.data.collections.new(CHARACTER_COLLECTION)
    scene.collection.children.link(coll)
    layer_coll = bpy.context.view_layer.layer_collection.children[coll.name]
    prev_active = bpy.context.view_layer.active_layer_collection
    bpy.context.view_layer.active_layer_collection = layer_coll
    colls_before = set(scene.collection.children)
    actions_before = set(bpy.data.actions)
    try:
        result = bpy.ops.import_scene.vrm(filepath=str(path))
    finally:
        bpy.context.view_layer.active_layer_collection = prev_active
    if "FINISHED" not in result:
        raise RuntimeError(f"VRM import failed: {result}")
    # The add-on puts its collider empties in a scene-level "Colliders" collection and adds a
    # fake-user "T-Pose" action: adopt both so remove_character() can free them.
    for extra in set(scene.collection.children) - colls_before - {coll}:
        scene.collection.children.unlink(extra)
        coll.children.link(extra)
    coll[IMPORTED_ACTIONS_KEY] = [a.name for a in set(bpy.data.actions) - actions_before]

    armature = next((o for o in coll.all_objects if o.type == "ARMATURE"), None)
    if armature is None:
        raise RuntimeError("Imported VRM has no armature")
    armature["wogen_base"] = name
    return armature


def remove_character() -> None:
    """Delete the character and free everything it used, so repeated generations in one
    session don't accumulate data (and slow down).

    Ends with a recursive orphan purge: any datablock left with no users is deleted, including
    unrelated orphans in a live session (they would be dropped on save anyway).
    """
    from ..paths import ASSETS_DIR as assets
    coll = bpy.data.collections.get(CHARACTER_COLLECTION)
    if coll is None:
        return
    actions = [bpy.data.actions.get(n) for n in coll.get(IMPORTED_ACTIONS_KEY, [])]
    for obj in coll.all_objects:   # toon.apply_toon() fake-users the MToon sources
        if obj.type == "MESH":
            for mat in obj.data.materials:
                src = bpy.data.materials.get(mat.get("wg_source", "")) if mat else None
                for m in (mat, src):
                    if m is not None:
                        m.use_fake_user = False
    for obj in list(coll.all_objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for child in list(coll.children_recursive):
        bpy.data.collections.remove(child)
    bpy.data.collections.remove(coll)
    for action in actions:
        if action is not None:
            bpy.data.actions.remove(action)
    garments = (assets / "garments").resolve()
    for lib in list(bpy.data.libraries):   # entries left by appending library garments
        if Path(bpy.path.abspath(lib.filepath)).resolve().parent == garments:
            bpy.data.libraries.remove(lib)
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    from . import outfit, toon
    toon._mean_cache.clear()
    outfit._alpha_cache.clear()


def character_meshes() -> list[bpy.types.Object]:
    coll = bpy.data.collections.get(CHARACTER_COLLECTION)
    return [o for o in coll.all_objects if o.type == "MESH"] if coll else []


def character_armature() -> bpy.types.Object | None:
    coll = bpy.data.collections.get(CHARACTER_COLLECTION)
    if coll is None:
        return None
    return next((o for o in coll.all_objects if o.type == "ARMATURE"), None)


def summary() -> str:
    """One-paragraph description of the loaded character (for chat)."""
    arm = character_armature()
    meshes = character_meshes()
    if arm is None:
        return "No character loaded."
    mats = {m.name for o in meshes for m in o.data.materials if m}
    face = next((o for o in meshes if o.name == "Face"), None)
    keys = len(face.data.shape_keys.key_blocks) if face and face.data.shape_keys else 0
    return (
        f"{arm.get('wogen_base', '?')}: {len(meshes)} meshes, {len(arm.data.bones)} bones, "
        f"{len(mats)} materials, {keys} face shape keys"
    )

