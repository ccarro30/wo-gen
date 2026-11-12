"""Shape sliders: displace the rest mesh to change the profile of hips, seat and thighs.

Size sliders (``wogen.bl.body``) scale a region about its bone, which changes how big it is
but not its shape. These fields push the skin of the fitted rest pose (after the size
transforms, before any posing) in smooth regions placed relative to the fitted hip and thigh
bones, masked by the skin weights so nothing else moves. Amounts come from
``wogen.body.shape_amounts``; at amount 1 each field moves the skin by its reference
distance (see ``offsets``). Prototyped as shape keys on the curvy body and dialed in by eye.

The body gets the fields directly; its offsets are stored as a point attribute
(``OFFSET_ATTR``). Garments copy the offset of the nearest body skin (``fit_garment``), so
cloth moves with the skin under it instead of being pierced. Hair is left alone.

Axes: armature rest space, x left, -y forward, z up.
"""

from __future__ import annotations

import numpy as np

OFFSET_ATTR = "wg_shape_offset"
REACH = (0.04, 0.10)        # m: garments copy the full offset within 4 cm of skin, none past 10


def _ss(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _ell(p: np.ndarray, c: np.ndarray, r: np.ndarray) -> np.ndarray:
    return np.sqrt((((p - c) / r) ** 2).sum(1))


def _weights(obj, arm, wanted: set[str]) -> np.ndarray:
    """Per vertex, the skin weight on ``wanted`` bones, counting bones parented under them
    (garment and tissue helper bones) until another humanoid bone is reached."""
    from .pose import humanoid_map
    humanoid = set(humanoid_map(arm).values())

    def owner(name):
        bone = arm.data.bones.get(name)
        while bone is not None and bone.name not in humanoid:
            bone = bone.parent
        return bone.name if bone is not None else None
    hit = {vg.index for vg in obj.vertex_groups if owner(vg.name) in wanted}
    w = np.zeros(len(obj.data.vertices))
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group in hit:
                w[v.index] += g.weight
    return np.clip(w, 0.0, 1.0)


def offsets(obj, arm, amounts: dict[str, float], co: np.ndarray) -> np.ndarray:
    """Displacement per vertex of ``obj`` (rest coordinates ``co``, armature space)."""
    from .pose import humanoid_map
    hm = humanoid_map(arm)
    out = np.zeros_like(co)

    def a(name: str) -> float:
        return float(amounts.get(name, 0.0))
    if not any(a(n) for n in amounts):
        return out
    for s, side in ((1, "left"), (-1, "right")):
        ul = arm.data.bones[hm[f"{side}_upper_leg"]]
        ll = arm.data.bones[hm[f"{side}_lower_leg"]]
        h, k = np.array(ul.head_local), np.array(ll.head_local)
        own = s * co[:, 0] > 0
        region = _weights(obj, arm, {hm["hips"], ul.name}) * own
        leg = _weights(obj, arm, {ul.name}) * own
        midline = _ss(0.0, 0.025, s * co[:, 0])                 # keeps the cleft
        axis = k - h
        length = np.linalg.norm(axis)
        u = axis / length
        t = ((co - h) @ u) / length                            # 0 at the hip, 1 at the knee
        radial = (co - h) - np.outer((co - h) @ u, u)
        rn = np.linalg.norm(radial, axis=1) + 1e-9

        # Seat (25 mm): out from a point inside the buttock, behind and below the hip joint.
        core = h + np.array([s * 0.010, 0.010, -0.020])
        c, r = h + np.array([s * 0.012, 0.060, -0.030]), np.array([0.095, 0.080, 0.115])
        d = co - core
        d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
        back = _ss(core[1] - 0.01, core[1] + 0.03, co[:, 1])
        seat = d * (0.025 * a("seat") * (1 - _ss(0.25, 1.0, _ell(co, c, r)))
                    * back * midline * region)[:, None]
        out += seat
        # Roundness: fill the projected seat out toward a sphere about the same point, on
        # its back-facing part only (sideways it would bulge the outer hip).
        if a("seat_round"):
            v = co + seat - core
            dist = np.linalg.norm(v, axis=1)
            dirs = v / (dist[:, None] + 1e-9)
            w = ((1 - _ss(0.3, 1.0, _ell(co, c, r))) * _ss(0.15, 0.65, dirs[:, 1])
                 * midline * region)
            if (w > 0.5).any():
                radius = np.percentile(dist[w > 0.5], 90)
                out += dirs * (np.clip(radius - dist, 0.0, None) * w * a("seat_round"))[:, None]
        # Hip curve (15 mm): lateral flare at the level of the top of the thigh bone.
        core = h + np.array([-s * 0.010, 0.0, -0.070])
        c, r = h + np.array([s * 0.060, 0.005, -0.070]), np.array([0.070, 0.110, 0.130])
        d = co - core
        d[:, 1] *= 0.3
        d[:, 2] = 0.0
        d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
        out += d * (0.015 * a("hip_curve") * (1 - _ss(0.2, 1.0, _ell(co, c, r)))
                    * _ss(h[0] * 0.5, h[0], s * co[:, 0]) * region)[:, None]
        # Upper thigh (+12 % radius): fullest in the upper third, easing into the knee.
        prof = _ss(0.0, 0.22, t) * (1 - _ss(0.40, 0.92, t))
        out += radial * (0.12 * a("thigh_upper") * prof * leg)[:, None]
        # Seat fold (8 mm) and back of the thigh (10 mm): a crease under the seat, fuller
        # just below it.
        back_face = _ss(0.25, 0.75, radial[:, 1] / rn)
        lateral = (_ss(0.005, 0.02, s * co[:, 0])
                   * (1 - _ss(h[0] + 0.03, h[0] + 0.075, s * co[:, 0])))
        band = np.exp(-((co[:, 2] - (h[2] - 0.095)) / 0.018) ** 2)
        out[:, 1] -= 0.008 * a("seat_fold") * band * back_face * lateral * region
        prof = _ss(0.18, 0.32, t) * (1 - _ss(0.40, 0.70, t))
        out += (radial / rn[:, None]) * (0.010 * a("thigh_back") * prof * back_face * leg)[:, None]
        # Thigh gap (15 mm): the inner face of the upper thigh toward the midline.
        inner = np.clip(-s * radial[:, 0] / rn, 0.0, 1.0) ** 1.5
        prof = _ss(0.03, 0.22, t) * (1 - _ss(0.45, 0.85, t))
        out[:, 0] -= s * 0.015 * a("thigh_gap") * prof * inner * leg
    return out


def _rest(obj) -> np.ndarray:
    co = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", co)
    return co.reshape(-1, 3).astype(np.float64)


def _to_arm(obj, arm, co: np.ndarray) -> np.ndarray:
    m = arm.matrix_world.inverted() @ obj.matrix_world
    return co @ np.array(m.to_3x3()).T + np.array(m.translation)


def _displace(obj, arm, off: np.ndarray) -> None:
    """Add ``off`` (armature space) to every shape key of ``obj``, or to its vertices."""
    to_mesh = np.array((obj.matrix_world.inverted() @ arm.matrix_world).to_3x3())
    delta = (off @ to_mesh.T).astype(np.float32)
    me = obj.data
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    if me.shape_keys:
        for kb in me.shape_keys.key_blocks:
            kb.data.foreach_get("co", co)
            kb.data.foreach_set("co", (co.reshape(-1, 3) + delta).ravel())
        me.shape_keys.key_blocks[0].data.foreach_get("co", co)
    else:
        me.vertices.foreach_get("co", co)
        co = (co.reshape(-1, 3) + delta).ravel()
    me.vertices.foreach_set("co", co)
    me.update()


def apply_body(body_obj, arm, amounts: dict[str, float]) -> int:
    """Shape the body mesh and record its offsets; returns the number of vertices moved."""
    co = _to_arm(body_obj, arm, _rest(body_obj))
    off = offsets(body_obj, arm, amounts, co)
    moved = int((np.linalg.norm(off, axis=1) > 1e-5).sum())
    if moved:
        _displace(body_obj, arm, off)
    attrs = body_obj.data.attributes
    attr = attrs.get(OFFSET_ATTR) or attrs.new(OFFSET_ATTR, "FLOAT_VECTOR", "POINT")
    attr.data.foreach_set("vector", off.astype(np.float32).ravel())
    return moved


def fit_garment(garment, arm, body_obj) -> int:
    """Give a (size-fitted) garment the offset of the body skin nearest each vertex.

    The body's rest positions already include its offsets, so a garment vertex is matched
    against the body as it was before shaping (current minus offset)."""
    from mathutils import Vector
    from mathutils.kdtree import KDTree
    attr = body_obj.data.attributes.get(OFFSET_ATTR)
    if attr is None:
        return 0
    n = len(body_obj.data.vertices)
    body_off = np.empty(n * 3, dtype=np.float32)
    attr.data.foreach_get("vector", body_off)
    body_off = body_off.reshape(-1, 3).astype(np.float64)
    moving = np.linalg.norm(body_off, axis=1) > 1e-5
    if not moving.any():
        return 0
    body_co = _to_arm(body_obj, arm, _rest(body_obj)) - body_off
    tree = KDTree(n)
    for i, p in enumerate(body_co):
        tree.insert(Vector(p), i)
    tree.balance()
    co = _to_arm(garment, arm, _rest(garment))
    off = np.zeros_like(co)
    pad = REACH[1] + 0.03
    lo, hi = body_co[moving].min(0) - pad, body_co[moving].max(0) + pad
    for i in np.nonzero(np.all((co > lo) & (co < hi), axis=1))[0]:
        found = tree.find_n(Vector(co[i]), 4)
        dist = np.array([d for _, _, d in found])
        w = 1.0 / (dist + 1e-4)
        o = sum(wi * body_off[j] for (_, j, _), wi in zip(found, w)) / w.sum()
        off[i] = o * (1 - _ss(REACH[0], REACH[1], dist.min()))
    moved = int((np.linalg.norm(off, axis=1) > 1e-5).sum())
    if moved:
        _displace(garment, arm, off)
    return moved
