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

The breasts don't use their VRM chain: ``_Tissue`` drives the bust bones with the
soft-tissue solver (``wogen.softtissue``) from the chest's acceleration, baked in the same
pass.

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

from ..drift import drift
from ..softtissue import TissueParams
from .anim import remove_fcurves

BUST_SPRING = "Bust"            # VroidStudio's spring name for the breast chains
# VRM spring approximation of the soft-tissue bounce, written into exported VRMs (VRM can only
# store spring chains). VroidStudio's own drag 0.05 rings for too long; 0.3 was rigid.
BUST_SPRING_PARAMS = {"drag_force": 0.15, "stiffness": 0.75}


def bust_spring_params(bust: float = 1.0) -> dict[str, float]:
    """``BUST_SPRING_PARAMS`` for the ``bust`` slider, scaled as ``softtissue.for_size``
    scales the bake. A VRM spring's stiffness acts like frequency squared (times dt) and its
    drag like damping ratio times frequency, so frequency * s^-0.3 and damping * s^0.3 give
    stiffness * s^-0.6 and an unchanged drag."""
    s = max(0.5, bust)
    return {**BUST_SPRING_PARAMS, "stiffness": BUST_SPRING_PARAMS["stiffness"] * s ** -0.6}


@dataclass
class PhysicsSettings:
    stiffness_scale: float = 1.0
    drag_scale: float = 1.0
    gravity_scale: float = 1.0
    # Per-chain overrides by VRM spring name: {"Bust": {"drag_force": 0.3}}. The bust chain
    # (only simulated with soft_tissue=False) gets the parameters exported VRMs use.
    overrides: dict[str, dict[str, float]] = field(
        default_factory=lambda: {BUST_SPRING: dict(BUST_SPRING_PARAMS)})
    settle_frames: int = 30     # steps run on the first frame so chains start at rest
    substeps: int = 1           # >1 for fast motion (more stable collisions)
    # Allow each joint/collider pair the overlap it has in the first frame's pose, so the
    # authored hairstyle isn't pushed out at rest (VroidStudio colliders are set up for the
    # T-pose; with arms down, hair tips already sit inside chest/arm spheres).
    rest_slack: bool = True
    # Carry springs along with the hips' horizontal travel (0..1), like a VRM spring
    # "center": at 1, walking forward causes no lag at all; a little below 1 keeps a hint of
    # sway. Vertical motion is never carried, so footfalls and landings still bounce the hair.
    carry: float = 0.0
    # Bakes add spheres along the legs, forearms and hands to every chain (slack measured on
    # the T-pose), so skirts and hair are pushed by the limbs instead of pierced.
    limb_colliders: bool = True
    # Breasts use the soft-tissue solver (``wogen.softtissue``) instead of the VRM "Bust"
    # chain: a tuned damped bounce driven by the chest's acceleration.
    soft_tissue: bool = True
    tissue: TissueParams = field(default_factory=TissueParams)
    # Butt, thighs and belly too: helper bones (``wogen.bl.tissue_rig``, added on the first
    # bake) driven by the same solver with ``softtissue.REGIONS``. Needs ``soft_tissue``.
    lower_body: bool = True
    # Left/right variation of the soft tissue (``softtissue.vary``), seeded by the character's
    # seed, so the two sides don't move as exact mirror images. 0 = symmetric.
    tissue_variation: float = 1.0
    # Idle drift (``wogen.drift``): a slow, seeded push on spring chains, like a light
    # breeze, so hair and skirts are never dead still between moves. In gravity-power units
    # for hair; other chains (skirts, ribbons) get ``drift_cloth`` of it. 0 turns it off.
    drift: float = 0.05           # hair tips sway ~1 cm (long hair ~2 cm), skirt hems ~4 mm
    drift_cloth: float = 0.3
    drift_seed: int = 0
    # Hair stiffness from root to tip, as multipliers of VroidStudio's per-chain value: a
    # firmer root and looser tips, so long hair bends along its length instead of swinging
    # from the scalp like a board. (1.0, 1.0) keeps the exported values.
    hair_taper: tuple[float, float] = (1.5, 0.7)


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


def _vrm_springs(arm: bpy.types.Object):
    """The armature's VRM spring-bone data, or None (imported MMD rigs; VRM add-on off)."""
    ext = getattr(arm.data, "vrm_addon_extension", None)
    return ext.spring_bone1 if ext is not None else None


def _springs(arm: bpy.types.Object, settings: PhysicsSettings) -> list[_Spring]:
    sb = _vrm_springs(arm)
    if sb is None:
        return []
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


def _is_hair(spring: _Spring) -> bool:
    """Hair chain (base hair or a library hairstyle): VroidStudio names its bones
    ``J_Sec_Hair..`` (prefixed ``hair_N.`` on harvested hairstyles)."""
    return any("J_Sec_Hair" in j.bone for j in spring.joints)


def _taper_hair(springs: list[_Spring], taper: tuple[float, float]) -> None:
    """Scale hair joints' stiffness from ``taper[0]`` at the root to ``taper[1]`` at the tip."""
    root, tip = taper
    for sp in springs:
        if not _is_hair(sp):
            continue
        n = len(sp.joints)
        for i, j in enumerate(sp.joints):
            t = i / (n - 1) if n > 1 else 0.0
            j.stiffness *= root + (tip - root) * t


def spring_bone_names(arm: bpy.types.Object | None = None) -> list[str]:
    from .character import character_armature
    arm = arm or character_armature()
    sb = _vrm_springs(arm)
    names = [j.node.bone_name for sp in sb.springs for j in sp.joints] if sb else []
    names += [j.bone for sp in _garment_springs(arm, PhysicsSettings()) for j in sp.joints]
    from . import tissue_rig
    names += [h["bone"] for h in tissue_rig.helpers(arm)]     # soft-tissue helper bones
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
                 write: bool, push: Vector | None = None) -> None:
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
        if push is not None:
            nxt += push * dt
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


def _rest_slack(arm, spring: _Spring, colliders, first: int) -> None:
    """Slack for ``colliders`` (indices from ``first``) measured on the T-pose rest: limbs
    are far from hair and skirts there, so overlaps that only happen in the clip's first
    frame (hands resting inside a skirt) aren't allowed for the whole clip."""
    for j in spring.joints:
        tail = arm.data.bones[j.child].head_local
        for k, ((bone, offset), radius) in enumerate(colliders):
            dist = (tail - arm.data.bones[bone].matrix_local @ offset).length
            if dist < radius + j.hit_radius:
                j.allowed[first + k] = dist
            else:
                j.allowed.pop(first + k, None)


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
    from . import mmd_import
    if mmd_import.has_physics(arm):          # imported model: its own rigid-body physics
        msg = mmd_import.simulate(start, end)
        bones = mmd_import.tissue_bones(arm)
        if settings.soft_tissue and bones:   # the breasts: our solver (release_bust)
            tissue = _Tissue(arm, settings.tissue, False, settings.tissue_variation, bones)
            for frame in range(scene.frame_start, scene.frame_end + 1):
                scene.frame_set(frame)
                tissue.sample()
            tissue.key(scene.frame_start, scene.render.fps / scene.render.fps_base)
            scene.frame_set(scene.frame_start)
            msg += f" + soft tissue ({len(bones)} bones)"
        return msg
    clear(arm)
    springs = _springs(arm, settings)
    if settings.soft_tissue:
        springs = [sp for sp in springs if sp.name != BUST_SPRING]
    _taper_hair(springs, settings.hair_taper)
    # Imported (MMD) rigs carry their skin weights on D-bones the helpers don't split yet
    # (roadmap step 2), so they get no lower-body tissue for now.
    from .mmd_import import SOURCE_KEY
    lower_body = settings.lower_body and SOURCE_KEY not in arm
    tissue = (_Tissue(arm, settings.tissue, lower_body, settings.tissue_variation)
              if settings.soft_tissue else None)
    limbs = _limb_colliders(arm) if settings.limb_colliders else []
    limb_from = {}
    for sp in springs:
        if limbs:
            limb_from[id(sp)] = len(sp.colliders)
            sp.colliders = list(sp.colliders) + limbs
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
            if limbs:
                _rest_slack(arm, sp, limbs, limb_from[id(sp)])
    for _ in range(settings.settle_frames):
        for sp in springs:
            _step_spring(arm, sp, dt, centers(sp), write=False)
    keyed = 0
    fps = scene.render.fps / scene.render.fps_base
    drift_scale = {id(sp): settings.drift * (1.0 if _is_hair(sp) else settings.drift_cloth)
                   for sp in springs}
    from .pose import humanoid_bone
    hips = arm.pose.bones.get(humanoid_bone(arm, "hips", ""))
    last_center = hips.head.copy() if hips is not None else None
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        if tissue is not None:
            tissue.sample()
        if settings.carry and hips is not None:
            shift = (hips.head - last_center) * settings.carry
            shift.z = 0.0
            last_center = hips.head.copy()
            for sp in springs:
                for j in sp.joints:
                    if j.tail is not None:
                        j.tail = j.tail + shift
                        j.prev_tail = j.prev_tail + shift
        wind = (Vector(drift((frame - start) / fps, settings.drift_seed)) if settings.drift
                else None)
        for sp in springs:
            cs = centers(sp)
            push = wind * drift_scale[id(sp)] if wind is not None else None
            for s in range(settings.substeps):
                _step_spring(arm, sp, dt, cs, write=(s == settings.substeps - 1), push=push)
            for j in sp.joints:
                arm.pose.bones[j.bone].keyframe_insert("rotation_quaternion", frame=frame)
                keyed += 1
    scene.frame_set(start)
    extra = ""
    if tissue is not None and tissue.sides:
        tissue.key(start, scene.render.fps / scene.render.fps_base)
        extra = f" + soft tissue ({len(tissue.sides)} bones)"
        scene.frame_set(start)
    return (f"baked {len(springs)} springs "
            f"({sum(len(s.joints) for s in springs)} joints){extra} over frames {start}-{end}")


# Share of the tissue offset applied as a translation of the bust bone (the rest is a swing
# about its base). VroidStudio weights the breast only partly to ``Bust1`` (0.83 at the
# centre, falling off toward the chest) and barely to ``Bust2``; a swing alone moves just
# the centre, while a translation shifts the whole weighted area as one mass.
TISSUE_TRANSLATE = 0.6
# Downward offsets are scaled by this: a full drop folds the underside into the torso and
# draws a hard crease line.
TISSUE_DROP = 0.7


class _Tissue:
    """Soft-tissue secondary motion. Samples each part's anchor (where its parent bone
    carries it) per frame, then simulates and keys the bones: the ``Bust1`` bones (location +
    rotation) and, with ``lower_body``, the helper bones of ``wogen.bl.tissue_rig`` (butt,
    thighs, belly; location only)."""

    def __init__(self, arm, params: TissueParams, lower_body: bool = True,
                 variation: float = 1.0, bust_bones: list[str] | None = None):
        """``bust_bones`` drives those bones (an imported model's, ``mmd_import.release_bust``;
        anchored at the bone's tail) instead of VroidStudio's ``Bust1`` chains."""
        import json
        from .. import softtissue
        from .body import PARAMS_KEY
        from .generate import GENERATED_KEY
        self.arm = arm
        body = json.loads(arm.get(PARAMS_KEY, "{}"))
        seed = int(json.loads(arm.get(GENERATED_KEY, "{}")).get("seed") or 0)
        bust_params = softtissue.for_size(params, body.get("bust", 1.0))
        self.sides = []
        if bust_bones is not None:
            chains = [(arm.data.bones[n], arm.data.bones[n].tail_local, arm.data.bones[n].tail_local)
                      for n in bust_bones]
        else:
            chains = []
            for b in arm.data.bones:
                if b.name.endswith("Bust1") and b.children and b.parent:
                    mid = b.children[0]
                    tip = mid.children[0].head_local if mid.children else mid.tail_local
                    chains.append((b, mid.head_local, tip))
        for b, anchor, tip in chains:
            chest = b.parent
            self.sides.append({
                "bone": b.name, "chest": chest.name,
                "params": softtissue.vary(bust_params, seed, b.name, variation),
                "anchor": chest.matrix_local.inverted() @ anchor,           # chest-local
                "chest_rest_q": chest.matrix_local.to_quaternion(),
                "lever": tip - b.head_local,                                # rest frame
                "rest_q": b.matrix_local.to_quaternion(),
                "pos": [], "rot": []})
        if not lower_body:
            return
        from . import tissue_rig
        tissue_rig.ensure(arm)
        regions = {r.name: r for r in softtissue.REGIONS}
        for h in tissue_rig.helpers(arm):
            b = arm.data.bones[h["bone"]]
            self.sides.append({
                "bone": b.name, "chest": b.parent.name,
                "params": softtissue.vary(softtissue.region_params(regions[h["region"]], body),
                                          seed, b.name, variation),
                "anchor": b.parent.matrix_local.inverted() @ b.head_local,
                "chest_rest_q": b.parent.matrix_local.to_quaternion(),
                "lever": None,                                 # helpers only shift
                "rest_q": b.matrix_local.to_quaternion(),
                "pos": [], "rot": []})

    def sample(self) -> None:
        mw = self.arm.matrix_world
        for s in self.sides:
            chest = self.arm.pose.bones[s["chest"]]
            s["pos"].append(tuple(mw @ (chest.matrix @ s["anchor"])))
            s["rot"].append(mw.to_quaternion() @ chest.matrix.to_quaternion()
                            @ s["chest_rest_q"].inverted())

    def offsets(self, side: dict, fps: float) -> list[tuple[float, float, float]]:
        from .. import softtissue
        acc = softtissue.accelerations(side["pos"], fps, side["params"].drive_window)
        inv = [q.inverted() for q in side["rot"]]
        local = [tuple(q @ Vector(a)) for q, a in zip(inv, acc)]
        grav = [tuple(q @ Vector(softtissue.GRAVITY)) for q in inv]
        return softtissue.simulate(local, fps, side["params"], grav)

    @staticmethod
    def pose(arm, side: dict, offset) -> None:
        """Pose one part's bone for a tissue offset (rest frame): a bust bone (offset at the
        chain's tip), or a helper bone (the offset is its shift)."""
        off = Vector(offset)
        lever, rq = side["lever"], side["rest_q"]
        pb = arm.pose.bones[side["bone"]]
        if lever is None:
            pb.location = rq.inverted() @ off
            return
        if off.z < 0:
            off.z *= TISSUE_DROP
        move = off * TISSUE_TRANSLATE
        q = lever.rotation_difference(lever + off - move)
        pb.rotation_mode = "QUATERNION"
        # Rest-frame motion as bone-local basis values (as in _step_spring).
        pb.rotation_quaternion = rq.inverted() @ q @ rq
        pb.location = rq.inverted() @ move

    def key(self, start: int, fps: float) -> None:
        for s in self.sides:
            pb = self.arm.pose.bones[s["bone"]]
            for i, off in enumerate(self.offsets(s, fps)):
                self.pose(self.arm, s, off)
                if s["lever"] is not None:
                    pb.keyframe_insert("rotation_quaternion", frame=start + i)
                pb.keyframe_insert("location", frame=start + i)


LEG_COLLIDERS = (("upper_leg", 0.075, 6), ("lower_leg", 0.055, 4))   # (bone, radius, spheres)
ARM_COLLIDERS = (("lower_arm", 0.035, 4), ("hand", 0.04, 2))


def _leg_colliders(arm, specs=LEG_COLLIDERS) -> list[tuple[tuple[str, Vector], float]]:
    """Spheres along each whole thigh and shin (bone-local offsets), for draping skirts.
    VroidStudio's skirt colliders stop two-thirds down the thigh and skip the knee."""
    from .pose import humanoid_map
    hmap = humanoid_map(arm)
    out = []
    for side in ("left", "right"):
        for name, radius, count in specs:
            bone = hmap.get(f"{side}_{name}")
            if bone is None:
                continue
            length = arm.data.bones[bone].length
            for i in range(count):
                out.append(((bone, Vector((0.0, length * i / (count - 1), 0.0))), radius))
    return out


def _limb_colliders(arm) -> list[tuple[tuple[str, Vector], float]]:
    """Full-length leg spheres plus forearm and hand spheres, for bakes: hands push skirts
    and hair aside instead of passing through them."""
    return _leg_colliders(arm) + _leg_colliders(arm, ARM_COLLIDERS)


def settle(steps: int = 48, settings: PhysicsSettings | None = None,
           garments_only: bool = False) -> str:
    """Drape skirts and hair around the current static pose, and let the bust hang with it.

    Stills never run a bake, so skirts keep their standing shape while thighs move through
    them, and hair stays upright under a tilted head. This replays the move from the
    standing rest pose into the current pose over the first two thirds of ``steps`` (so a
    rising thigh carries the skirt up and over instead of piercing it), then holds, and
    writes the final spring rotations (no keys). Legs get full-length colliders. Collider
    slack is measured on the standing rest pose. ``garments_only`` skips the base model's
    own chains (its hair). The bust takes the soft-tissue solver's rest offset for the
    posture (a bow lets it hang forward). Called by ``pose.apply_pose`` for unkeyed poses;
    clips use ``bake``.
    """
    from .character import character_armature
    settings = settings or PhysicsSettings()
    scene = bpy.context.scene
    arm = character_armature()
    from . import mmd_import
    if mmd_import.has_physics(arm):          # imported model: settle its rigid bodies
        return mmd_import.simulate(scene.frame_current, scene.frame_current, lead_in=steps)
    springs = (_garment_springs(arm, settings) if garments_only else _springs(arm, settings))
    springs = [sp for sp in springs if sp.name != BUST_SPRING]
    _taper_hair(springs, settings.hair_taper)
    tissue = None
    if settings.soft_tissue and not garments_only:
        tissue = _Tissue(arm, settings.tissue, lower_body=False)
        for side in tissue.sides:
            arm.pose.bones[side["bone"]].matrix_basis = Matrix.Identity(4)
    if not springs and not tissue:
        return "no spring chains to settle"
    legs = _leg_colliders(arm)
    for sp in springs:
        sp.colliders = list(sp.colliders) + legs
        for j in sp.joints:
            _init_joint(arm, j)
    chain_bones = {j.bone for sp in springs for j in sp.joints}
    target = {pb.name: pb.matrix_basis.copy() for pb in arm.pose.bones if pb.name not in chain_bones}
    arm_z = arm.location.z

    def centers(sp: _Spring):
        out = []
        for ref, r in sp.colliders:
            if isinstance(ref, tuple):
                bone, offset = ref
                out.append((arm.pose.bones[bone].matrix @ offset, r))
            else:
                out.append((arm.matrix_world.inverted() @ ref.matrix_world.translation, r))
        return out

    parts = {name: m.decompose() for name, m in target.items()}

    def blend(t: float) -> None:
        for name, (loc, rot, scale) in parts.items():
            if t >= 1.0:
                arm.pose.bones[name].matrix_basis = target[name]
                continue
            q = Quaternion().slerp(rot, t)
            arm.pose.bones[name].matrix_basis = Matrix.LocRotScale(
                loc * t, q, Vector((1.0, 1.0, 1.0)).lerp(scale, t))
        bpy.context.view_layer.update()

    for pb in arm.pose.bones:
        if pb.name in chain_bones:
            pb.matrix_basis = Matrix.Identity(4)
    blend(0.0)
    if settings.rest_slack:
        for sp in springs:
            _compute_slack(arm, sp, centers(sp))
    dt = 1.0 / (scene.render.fps / scene.render.fps_base)
    ramp = max(1, steps * 2 // 3)
    for i in range(steps):
        t = min(1.0, (i + 1) / ramp)
        if i < ramp:
            blend(t * t * (3 - 2 * t))
        for sp in springs:
            _step_spring(arm, sp, dt, centers(sp), write=(i == steps - 1))
    blend(1.0)
    arm.location.z = arm_z
    bpy.context.view_layer.update()
    extra = ""
    if tissue is not None and tissue.sides:
        fps = scene.render.fps / scene.render.fps_base
        tissue.sample()                      # one frame: the rest offset for this posture
        for side in tissue.sides:
            _Tissue.pose(arm, side, tissue.offsets(side, fps)[0])
        bpy.context.view_layer.update()
        extra = f" + bust ({len(tissue.sides)} bones)"
    return f"settled {len(springs)} chains over {steps} steps{extra}"
