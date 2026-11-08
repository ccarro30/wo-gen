"""Keep hands and forearms out of skirts and dresses after posing.

There's no cloth simulation, so a pose that puts a hand where a wide skirt is (arms down
beside a flared dress, hands behind the back) sinks it into the cloth. ``clear_arms`` tests
sample points on each forearm and hand against the posed garments and, where they're
inside (or closer than the hand's thickness), rotates the upper arm about the shoulder so the
hand moves outward, in small steps, until every point is clear or the angle cap is reached.

Inside test: a ray from the point, pointing away from the body's vertical axis, that exits a
garment surface (hits it from the back) means the point is under that cloth. Layered skirts
(outer skirt over a petticoat) work, because the first exit hit decides.

Called by ``pose.apply_pose`` (``clear=True``), so stills, clips and sheets all get it.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

SLOTS = ("full", "bottom")          # garments whose skirts can swallow a hand
MARGIN = 0.02                       # metres: hand/forearm half-thickness around the bone line
STEP_DEG = 2.0
MAX_DEG = 30.0
WAIST_ABOVE_HIPS = 0.08             # only points below hips + this (skirts, not the bodice)
IK_STEP = 0.01                      # metres per step when moving an IK hand target
IK_MAX = 0.12
PASSES = 3                          # cloth weighted to the arms moves with them: re-check


def _arm_carried(g: bpy.types.Object, arm_bones: set[str]) -> list[bool]:
    """Per vertex: is it mostly carried by arm/hand bones (cuffs, sleeves, armholes)? Those
    parts move with the arm, so they're never something the arm should avoid."""
    names = {vg.index: vg.name for vg in g.vertex_groups}
    out = []
    for v in g.data.vertices:
        arm_w = sum(e.weight for e in v.groups if names.get(e.group) in arm_bones)
        total = sum(e.weight for e in v.groups)
        out.append(total > 0 and arm_w / total > 0.3)
    return out


def _garment_trees(arm: bpy.types.Object, hmap: dict) -> list[BVHTree]:
    """Posed garment surfaces in armature space (outline hulls and arm-carried parts excluded)."""
    from .outfit import garments
    from .toon import OUTLINE_MOD
    objs = [g for g in garments() if not g.hide_render and g.get("wg_slot") in SLOTS]
    if not objs:
        return []
    muted = []
    for g in objs:
        md = g.modifiers.get(OUTLINE_MOD)
        if md is not None and md.show_viewport:
            md.show_viewport = False
            muted.append(md)
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        to_arm = arm.matrix_world.inverted()
        arm_bones = {b for n, b in hmap.items()
                     if n.startswith(("left_", "right_")) and not n.split("_", 1)[1].startswith(
                         ("upper_leg", "lower_leg", "foot", "toes", "eye"))}
        trees = []
        for g in objs:
            carried = _arm_carried(g, arm_bones)
            ev = g.evaluated_get(depsgraph)
            me = ev.to_mesh()
            try:
                mat = to_arm @ g.matrix_world
                verts = [mat @ v.co for v in me.vertices]
                me.calc_loop_triangles()
                same = len(me.vertices) == len(carried)
                tris = [tuple(t.vertices) for t in me.loop_triangles
                        if not (same and any(carried[i] for i in t.vertices))]
                if tris:
                    trees.append(BVHTree.FromPolygons(verts, tris))
            finally:
                ev.to_mesh_clear()
        return trees
    finally:
        for md in muted:
            md.show_viewport = True


def _points(arm: bpy.types.Object, hmap: dict, side: str) -> list[Vector]:
    """Armature-space samples along the forearm and hand, plus fingertips."""
    pb = arm.pose.bones
    pts = []
    lower = pb.get(hmap.get(f"{side}_lower_arm", ""))
    if lower is not None:
        pts += [lower.head.lerp(lower.tail, t) for t in (0.5, 0.8, 1.0)]
    hand = pb.get(hmap.get(f"{side}_hand", ""))
    if hand is not None:
        pts.append(hand.tail)
    for finger in ("index_distal", "middle_distal", "little_distal", "thumb_distal"):
        b = pb.get(hmap.get(f"{side}_{finger}", ""))
        if b is not None:
            pts.append(b.tail)
    return pts


def _violation(trees: list[BVHTree], axis: Vector, p: Vector) -> Vector | None:
    """Outward push direction if ``p`` is inside/too close to a garment, else None."""
    if p.z > axis.z + WAIST_ABOVE_HIPS:
        return None
    radial = Vector((p.x - axis.x, p.y - axis.y, 0.0))
    if radial.length < 1e-6:
        return None
    radial.normalize()
    for tree in trees:
        hit = tree.ray_cast(p, radial, 1.0)
        if hit[0] is not None and hit[1].dot(radial) > 0.0:
            return radial                                  # exits the cloth: we're inside
        loc, normal, _i, dist = tree.find_nearest(p, MARGIN)
        if loc is not None and dist < MARGIN:
            return radial
    return None


def clear_arms(arm: bpy.types.Object | None = None, hmap: dict | None = None,
               ik: dict | None = None) -> dict[str, float]:
    """Bring each forearm and hand out of skirts.

    Free arms: rotate the upper arm about the shoulder (result in degrees, key ``side``).
    IK-placed hands (``ik``: ``{side: (target, pole, orient)}`` from ``apply_pose``): move the
    target outward and re-solve, so a hand on the hip stays on the hip, resting on the cloth
    (result in metres, key ``side_ik``).
    """
    from .pose import _armature, humanoid_map
    arm = _armature(arm)
    hmap = hmap or humanoid_map(arm)
    done: dict[str, float] = {}
    ik = {side: [Vector(t), pole, orient] for side, (t, pole, orient) in (ik or {}).items()}
    for _ in range(PASSES):
        step = _clear_pass(arm, hmap, ik)
        if not step:
            break
        for side, deg in step.items():
            done[side] = done.get(side, 0.0) + deg
    return done


def _clear_pass(arm: bpy.types.Object, hmap: dict, ik: dict) -> dict[str, float]:
    trees = _garment_trees(arm, hmap)
    if not trees:
        return {}
    hips = arm.pose.bones.get(hmap.get("hips", ""))
    axis = hips.head.copy() if hips is not None else Vector()
    done = {}
    for side in ("left", "right"):
        if side in ik:
            moved = _clear_ik(arm, hmap, side, ik[side], trees, axis)
            if moved:
                done[f"{side}_ik"] = moved
            continue
        upper = arm.pose.bones.get(hmap.get(f"{side}_upper_arm", ""))
        if upper is None:
            continue
        total = 0.0
        while total < MAX_DEG:
            pushes = [d for d in (_violation(trees, axis, p) for p in _points(arm, hmap, side)) if d]
            if not pushes:
                break
            push = sum(pushes, Vector()).normalized()
            hand = _points(arm, hmap, side)[-1]
            rot_axis = (hand - upper.head).cross(push)
            if rot_axis.length < 1e-6:
                break
            pivot = upper.head.copy()
            rot = Matrix.Rotation(math.radians(STEP_DEG), 4, rot_axis.normalized())
            upper.matrix = Matrix.Translation(pivot) @ rot @ Matrix.Translation(-pivot) @ upper.matrix
            bpy.context.view_layer.update()
            total += STEP_DEG
        if total:
            done[side] = total
    return done


def _clear_ik(arm, hmap, side, entry, trees, axis) -> float:
    from .pose import reach
    moved = 0.0
    while moved < IK_MAX:
        pushes = [d for d in (_violation(trees, axis, p) for p in _points(arm, hmap, side)) if d]
        if not pushes:
            break
        entry[0] = entry[0] + sum(pushes, Vector()).normalized() * IK_STEP
        reach(f"{side}_hand", entry[0], entry[1], arm, hmap, entry[2])
        bpy.context.view_layer.update()
        moved += IK_STEP
    return round(moved, 3)
