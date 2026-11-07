"""Secondary motion: VRM SpringBone 1.0 simulation, baked to keyframes.

Reads the spring chains, joint parameters and sphere colliders that VroidStudio exported
(via the VRM add-on), steps the VRM 1.0 spring-bone algorithm frame by frame over the
current animation, and keys the resulting spring-bone rotations. Baking makes renders
deterministic and headless-safe (no playback-order dependence).

Per joint, per frame (spec)::

    inertia  = (tail - prev_tail) * (1 - drag)
    stiff    = dt * stiffness * rest_direction        # rest direction carried by the parent
    gravity  = dt * gravity_power * gravity_dir
    next     = tail + inertia + stiff + gravity
    next     = head + normalize(next - head) * length # keep bone length
    collide with spheres (radius + hit_radius), re-normalize length

Simulation runs in armature space (all VroidStudio chains use ``Root`` as their center),
so moving the whole armature doesn't cause jiggle.

Chat usage::

    from wogen.bl import anim, physics
    anim.preset("look_around")
    physics.bake()                         # simulate + key spring bones over the scene range
    physics.bake(PhysicsSettings(drag_scale=1.5))
    physics.clear()
"""

from __future__ import annotations

from dataclasses import dataclass, field

import bpy
from mathutils import Matrix, Quaternion, Vector

from .anim import remove_fcurves


@dataclass
class PhysicsSettings:
    stiffness_scale: float = 1.0
    drag_scale: float = 1.0
    gravity_scale: float = 1.0
    # Per-chain overrides by VRM spring name: {"Bust": {"drag_force": 0.3}}.
    # VroidStudio exports bust drag 0.05 (very bouncy); default to a calmer value.
    overrides: dict[str, dict[str, float]] = field(
        default_factory=lambda: {"Bust": {"drag_force": 0.3, "stiffness": 1.0}})
    settle_frames: int = 30     # steps run on the first frame so chains start at rest
    substeps: int = 1           # >1 for fast motion (more stable collisions)
    # Allow each joint/collider pair the overlap it has in the first frame's pose, so the
    # authored hairstyle isn't pushed out at rest (VroidStudio colliders are set up for the
    # T-pose; with arms down, hair tips already sit inside chest/arm spheres).
    rest_slack: bool = True


@dataclass
class _Joint:
    bone: str
    child: str
    stiffness: float
    drag: float
    gravity_power: float
    gravity_dir: Vector
    hit_radius: float
    length: float = 0.0
    v_rest: Vector | None = None      # head -> child head, armature space, rest pose
    rest_rel: Matrix | None = None    # parent rest^-1 @ bone rest
    rest_q: Quaternion | None = None
    tail: Vector | None = None
    prev_tail: Vector | None = None
    allowed: dict[int, float] = field(default_factory=dict)  # collider index -> min distance


@dataclass
class _Spring:
    name: str
    joints: list[_Joint]
    # (collider object, radius) from the VRM add-on, or ((bone, local offset), radius)
    # for garment-rig colliders.
    colliders: list[tuple[object, float]]


def _springs(arm: bpy.types.Object, settings: PhysicsSettings) -> list[_Spring]:
    sb = arm.data.vrm_addon_extension.spring_bone1
    groups = {g.uuid: g for g in sb.collider_groups}
    colliders = {c.uuid: c for c in sb.colliders}
    out = []
    for sp in sb.springs:
        ov = settings.overrides.get(sp.vrm_name, {})
        names = [j.node.bone_name for j in sp.joints]
        joints = []
        for j, child in zip(sp.joints[:-1], names[1:]):
            joints.append(_Joint(
                bone=j.node.bone_name, child=child,
                stiffness=ov.get("stiffness", j.stiffness) * settings.stiffness_scale,
                drag=min(1.0, ov.get("drag_force", j.drag_force) * settings.drag_scale),
                gravity_power=ov.get("gravity_power", j.gravity_power) * settings.gravity_scale,
                gravity_dir=Vector(j.gravity_dir).normalized() if Vector(j.gravity_dir).length
                else Vector((0, 0, -1)),
                hit_radius=ov.get("hit_radius", j.hit_radius),
            ))
        cols = []
        for ref in sp.collider_groups:
            group = groups.get(ref.collider_group_uuid)
            if group is None:
                continue
            for cref in group.colliders:
                c = colliders.get(cref.collider_uuid)
                if c is not None and c.bpy_object is not None and c.shape_type == "Sphere":
                    cols.append((c.bpy_object, float(c.shape.sphere.radius)))
        if joints:
            out.append(_Spring(sp.vrm_name, joints, cols))
    out.extend(_garment_springs(arm, settings))
    return out


def _garment_springs(arm: bpy.types.Object, settings: PhysicsSettings) -> list[_Spring]:
    """Spring chains carried by visible garments (see ``wogen.bl.garment_rig``)."""
    from . import garment_rig
    from .outfit import garments
    out = []
    try:
        worn = [g for g in garments() if not g.hide_render]
    except RuntimeError:
        return out
    for g in worn:
        rig = garment_rig.get(g)
        cols = {cid: ((c["bone"], Vector(c["offset"])), c["radius"])
                for cid, c in rig.get("colliders", {}).items() if c["bone"] in arm.data.bones}
        for sp in rig.get("springs", []):
            ov = settings.overrides.get(sp["name"], {})
            js = [j for j in sp["joints"] if j["bone"] in arm.pose.bones]
            joints = [_Joint(
                bone=j["bone"], child=c["bone"],
                stiffness=ov.get("stiffness", j["stiffness"]) * settings.stiffness_scale,
                drag=min(1.0, ov.get("drag_force", j["drag_force"]) * settings.drag_scale),
                gravity_power=ov.get("gravity_power", j["gravity_power"]) * settings.gravity_scale,
                gravity_dir=(Vector(j["gravity_dir"]).normalized() if Vector(j["gravity_dir"]).length
                             else Vector((0, 0, -1))),
                hit_radius=ov.get("hit_radius", j["hit_radius"]),
            ) for j, c in zip(js[:-1], js[1:])]
            if joints:
                out.append(_Spring(f"{g['wg_garment']}:{sp['name']}", joints,
                                   [cols[cid] for cid in sp["colliders"] if cid in cols]))
    return out


def spring_bone_names(arm: bpy.types.Object | None = None) -> list[str]:
    from .character import character_armature
    arm = arm or character_armature()
    sb = arm.data.vrm_addon_extension.spring_bone1
    names = [j.node.bone_name for sp in sb.springs for j in sp.joints]
    names += [j.bone for sp in _garment_springs(arm, PhysicsSettings()) for j in sp.joints]
    return names


def clear(arm: bpy.types.Object | None = None) -> int:
    """Remove baked spring-bone keys and reset those bones to rest."""
    from .character import character_armature
    arm = arm or character_armature()
    names = set(spring_bone_names(arm))
    removed = remove_fcurves(arm, lambda p: any(f'"{n}"' in p for n in names))
    for n in names:
        pb = arm.pose.bones.get(n)
        if pb is not None:
            pb.matrix_basis = Matrix.Identity(4)
    return removed


def _init_joint(arm, j: _Joint) -> None:
    pb = arm.pose.bones[j.bone]
    bone, child = pb.bone, arm.data.bones[j.child]
    j.v_rest = child.head_local - bone.head_local
    j.length = j.v_rest.length
    j.rest_q = bone.matrix_local.to_quaternion()
    j.rest_rel = (bone.parent.matrix_local.inverted() @ bone.matrix_local
                  if bone.parent else bone.matrix_local.copy())


def _step_spring(arm, spring: _Spring, dt: float, centers: list[tuple[Vector, float]],
                 write: bool) -> None:
    first = arm.pose.bones[spring.joints[0].bone]
    parent_mat = first.parent.matrix.copy() if first.parent else Matrix.Identity(4)
    parent_rest_q = (first.parent.bone.matrix_local.to_quaternion() if first.parent
                     else Quaternion())
    for j in spring.joints:
        unrotated = parent_mat @ j.rest_rel                 # this bone with identity basis
        head = unrotated.translation
        parent_delta = parent_mat.to_quaternion() @ parent_rest_q.inverted()
        rest_dir = (parent_delta @ j.v_rest).normalized()
        if j.tail is None:
            j.tail = head + rest_dir * j.length
            j.prev_tail = j.tail.copy()

        inertia = (j.tail - j.prev_tail) * (1.0 - j.drag)
        nxt = j.tail + inertia + rest_dir * (dt * j.stiffness) + j.gravity_dir * (dt * j.gravity_power)
        nxt = head + (nxt - head).normalized() * j.length
        for ci, (center, radius) in enumerate(centers):
            d = nxt - center
            r = j.allowed.get(ci, radius + j.hit_radius)
            if d.length < r and d.length > 1e-9:
                nxt = center + d.normalized() * r
                nxt = head + (nxt - head).normalized() * j.length
        j.prev_tail, j.tail = j.tail, nxt

        delta = j.v_rest.rotation_difference(parent_delta.inverted() @ (nxt - head))
        basis_q = j.rest_q.inverted() @ delta @ j.rest_q
        if write:
            pb = arm.pose.bones[j.bone]
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = basis_q
        parent_mat = unrotated @ basis_q.to_matrix().to_4x4()
        parent_rest_q = j.rest_q


def _compute_slack(arm, spring: _Spring, centers: list[tuple[Vector, float]]) -> None:
    """Record, per joint, colliders its rest-carried tail already penetrates (current pose)."""
    first = arm.pose.bones[spring.joints[0].bone]
    parent_mat = first.parent.matrix.copy() if first.parent else Matrix.Identity(4)
    parent_rest_q = (first.parent.bone.matrix_local.to_quaternion() if first.parent
                     else Quaternion())
    for j in spring.joints:
        unrotated = parent_mat @ j.rest_rel
        head = unrotated.translation
        parent_delta = parent_mat.to_quaternion() @ parent_rest_q.inverted()
        tail = head + (parent_delta @ j.v_rest)
        j.allowed = {}
        for ci, (center, radius) in enumerate(centers):
            dist = (tail - center).length
            if dist < radius + j.hit_radius:
                j.allowed[ci] = dist
        parent_mat, parent_rest_q = unrotated, j.rest_q   # chain continues in rest shape


def bake(settings: PhysicsSettings | None = None, frame_start: int | None = None,
         frame_end: int | None = None) -> str:
    """Simulate spring bones over the frame range and key them (replacing earlier bakes)."""
    from .character import character_armature
    settings = settings or PhysicsSettings()
    scene = bpy.context.scene
    arm = character_armature()
    start = scene.frame_start if frame_start is None else frame_start
    end = scene.frame_end if frame_end is None else frame_end
    clear(arm)
    springs = _springs(arm, settings)
    for sp in springs:
        for j in sp.joints:
            _init_joint(arm, j)
    to_arm = arm.matrix_world.inverted()
    dt = 1.0 / (scene.render.fps / scene.render.fps_base) / settings.substeps

    def centers(sp: _Spring):
        out = []
        for ref, r in sp.colliders:
            if isinstance(ref, tuple):        # garment collider: (bone, bone-local offset)
                bone, offset = ref
                out.append((arm.pose.bones[bone].matrix @ offset, r))
            else:
                out.append((to_arm @ ref.matrix_world.translation, r))
        return out

    scene.frame_set(start)
    if settings.rest_slack:
        for sp in springs:
            _compute_slack(arm, sp, centers(sp))
    for _ in range(settings.settle_frames):
        for sp in springs:
            _step_spring(arm, sp, dt, centers(sp), write=False)
    keyed = 0
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        for sp in springs:
            cs = centers(sp)
            for s in range(settings.substeps):
                _step_spring(arm, sp, dt, cs, write=(s == settings.substeps - 1))
            for j in sp.joints:
                arm.pose.bones[j.bone].keyframe_insert("rotation_quaternion", frame=frame)
                keyed += 1
    scene.frame_set(start)
    return (f"baked {len(springs)} springs "
            f"({sum(len(s.joints) for s in springs)} joints) over frames {start}-{end}")
