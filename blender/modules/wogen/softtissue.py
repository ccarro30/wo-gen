"""Soft-tissue secondary motion (breasts, butt, thighs, belly): damped springs driven by the
body's acceleration.

Pure Python (no bpy), so it's unit-tested. ``wogen.bl.physics`` samples each anchor per frame
and turns the offsets into bone motion: the bust bones, or the helper bones of ``REGIONS``
(butt, thighs, belly), where "chest" below reads as the helper's parent bone.

Each axis of the tissue's offset from where the chest carries it is a damped oscillator in
the chest's frame::

    x'' = -w^2 x - 2 zeta w x' + gain * (gravity_weight * (g - g_rest) - a)

where ``a`` is the anchor's acceleration and ``g - g_rest`` is how far gravity has turned
away from upright (bowing lets the bust hang forward a little). The tissue lags the chest,
then bounces back. A damping ratio of about 0.2 settles in 2 to 3 oscillations. The offset
is soft-clamped (tanh) so hard landings never look rubbery.

Axes are the character's rest frame: x lateral, y depth (-y is forward), z vertical.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

Vec = tuple[float, float, float]
GRAVITY: Vec = (0.0, 0.0, -9.81)


@dataclass(frozen=True)
class TissueParams:
    frequency: Vec = (2.07, 2.58, 2.27)  # Hz per axis (lateral, depth, vertical); lower = looser
    damping: float = 0.23                # damping ratio (0 = rings forever, 1 = no overshoot)
    # Response per axis: mostly vertical, some sway. The offset is measured at the tip of the
    # bust chain (~15 cm from its base, which sits inside the chest), so it reads larger than
    # the visible motion (``wogen.bl.physics`` turns part of it into a shift of the whole
    # breast, the rest into a swing). Tuned so a walk moves about 1 cm there (slight but
    # visible) while hops and jumps reach the clamp (a real shock).
    gain: Vec = (0.4, 0.26, 0.9)
    gravity_weight: float = 0.4        # how much posture changes the rest sag
    limit: float = 0.062               # m, soft clamp of the offset at the tip
    substeps: int = 8                  # integration steps per frame
    # m/s^2, soft clamp of the driving acceleration (0 = off). Keyframed runs spike to
    # 5 g for a frame; without this, small firm regions slam between their limits.
    drive_limit: float = 22.0
    # s, the time span the anchor's acceleration is measured over (a second difference at
    # +-drive_window). One frame at 24 fps, where everything was tuned; a fixed time keeps
    # the response the same at other frame rates. Longer smooths one-frame spikes from keys.
    drive_window: float = 1.0 / 24.0
    # Extra damping ratio deep in the clamp (0 = off): tissue pressed into its limit loses
    # energy instead of storing it. It rises with the square of how far the offset is past
    # ``LIMIT_KNEE`` of the limit, so motion well inside the limit is untouched. Without it a
    # run stepping near the bust's own frequency winds the swing up to twice the limit, and
    # the clamped tip whips through the middle of each swing.
    limit_damping: float = 1.5
    # s, how late this part feels the anchor's motion (``vary`` sets a little per side, so a
    # pair doesn't peak on the same frame; differences in timing survive the clamp, where
    # differences in size are flattened).
    drive_delay: float = 0.0


LIMIT_KNEE = 0.5      # fraction of the limit where ``limit_damping`` starts


def for_size(params: TissueParams, bust: float) -> TissueParams:
    """Scale for the ``bust`` body slider (1.0 = base): bigger moves more with a slower
    bounce; smaller is firmer (moves less, quicker). Bigger also gets more damping, so it
    still settles promptly instead of ringing (tuned by eye on hop/walk/run clips)."""
    s = max(0.5, bust)
    return replace(params,
                   frequency=tuple(f * s ** -0.3 for f in params.frequency),
                   damping=min(0.9, params.damping * s ** 0.3),
                   gain=tuple(g * s ** 1.8 for g in params.gain),
                   limit=params.limit * s ** 0.25)


# Per-part variation (``vary``): real tissue is never perfectly symmetric, so the two sides
# of a pair get slightly different responses, seeded per character. The sides differ by
# half to all of this fraction of each value (each side moves half of it, opposite ways).
VARIATION = {"frequency": 0.06, "damping": 0.12, "gain": 0.08, "limit": 0.06}
MAX_DELAY = 0.04      # s: one side of a pair feels the motion 20 to 40 ms (about a frame) late
_SIDE_TAGS = (("_L_", "_R_"), (".L.", ".R."))


def _pair(key: str) -> tuple[str, int]:
    """(name shared by both sides, +1 left / -1 right / 0 midline) for a bone name."""
    for left, right in _SIDE_TAGS:
        if left in key:
            return key.replace(left, "_S_"), 1
        if right in key:
            return key.replace(right, "_S_"), -1
    return key, 0


def vary(params: TissueParams, seed: int, key: str, scale: float = 1.0) -> TissueParams:
    """``params`` nudged by a seeded amount for one part (``key``: its bone name), so left
    and right differ a little in timing and size instead of moving as mirror images. The
    two sides of a pair draw the same numbers and move in opposite directions, so every
    character gets a clear but small difference; a midline part (belly) gets a one-sided
    nudge. ``scale`` 0 returns ``params`` unchanged."""
    if scale <= 0:
        return params
    pair, side = _pair(key)
    rng = random.Random(f"{seed}:{pair}")
    sign = side or 1

    def nudge(value: float, frac: float) -> float:
        u = rng.uniform(0.5, 1.0) * rng.choice((-1.0, 1.0))
        return value * (1.0 + scale * frac * u * sign / (2 if side else 1))
    late = rng.choice((-1, 1)) == sign if side else rng.random() < 0.5
    delay = rng.uniform(0.5, 1.0) * MAX_DELAY
    return replace(params,
                   frequency=tuple(nudge(f, VARIATION["frequency"]) for f in params.frequency),
                   damping=nudge(params.damping, VARIATION["damping"]),
                   gain=tuple(nudge(g, VARIATION["gain"]) for g in params.gain),
                   limit=nudge(params.limit, VARIATION["limit"]),
                   drive_delay=params.drive_delay + (scale * delay if late else 0.0))


def accelerations(positions: list[Vec], fps: float, window: float | None = None) -> list[Vec]:
    """Per-frame acceleration of a sampled point: the second difference at +-``window``
    seconds (default one frame), between samples linearly interpolated. A window of ``n``
    frames is the one-frame value averaged with weights 1, 2, .., n, .., 2, 1. Frames
    closer than ``window`` to either end repeat the nearest value."""
    n = len(positions)
    span = 1.0 if window is None else max(1.0, window * fps)    # in frames
    if n < 3 or 2 * span > n - 1:
        return [(0.0, 0.0, 0.0)] * n

    def at(f: float) -> Vec:
        i = min(int(f), n - 2)
        t = f - i
        return tuple(a + (b - a) * t for a, b in zip(positions[i], positions[i + 1]))

    first, last = math.ceil(span - 1e-9), math.floor(n - 1 - span + 1e-9)
    scale = (fps / span) ** 2
    out = []
    for i in range(first, last + 1):
        lo, hi = at(i - span), at(i + span)
        out.append(tuple((hi[k] - 2 * positions[i][k] + lo[k]) * scale for k in range(3)))
    return [out[0]] * first + out + [out[-1]] * (n - 1 - last)


def _soft_clamp(x: Vec, limit: float) -> Vec:
    length = math.sqrt(sum(c * c for c in x))
    if length < 1e-12 or limit <= 0:
        return x
    k = limit * math.tanh(length / limit) / length
    return tuple(c * k for c in x)


def _delayed(seq: list[Vec], frames: float) -> list[Vec]:
    """``seq`` shifted later by ``frames`` (fractional, linear in between; the start holds)."""
    out = []
    for i in range(len(seq)):
        f = max(0.0, i - frames)
        j = min(int(f), len(seq) - 2)
        t = f - j
        out.append(tuple(a + (b - a) * t for a, b in zip(seq[j], seq[j + 1])))
    return out


def simulate(accels: list[Vec], fps: float, params: TissueParams = TissueParams(),
             gravity: list[Vec] | None = None) -> list[Vec]:
    """Tissue offsets per frame, given the anchor's acceleration per frame in the chest frame.

    ``gravity`` is gravity in the chest frame per frame (defaults to upright). The offset
    starts at the equilibrium of the first frame's inputs, at rest.
    """
    n = len(accels)
    if gravity is None:
        gravity = [GRAVITY] * n
    w = [2 * math.pi * f for f in params.frequency]
    if params.drive_limit > 0:
        accels = [_soft_clamp(a, params.drive_limit) for a in accels]
    if params.drive_delay > 0 and n > 1:
        accels, gravity = (_delayed(seq, params.drive_delay * fps) for seq in (accels, gravity))

    def force(i: int, k: int) -> float:
        g = params.gravity_weight * (gravity[i][k] - GRAVITY[k])
        return params.gain[k] * (g - accels[i][k])

    if n == 0:
        return []
    x = [force(0, k) / (w[k] * w[k]) for k in range(3)]
    v = [0.0, 0.0, 0.0]
    out = [_soft_clamp(tuple(x), params.limit)]
    h = 1.0 / fps / params.substeps
    knee = LIMIT_KNEE * params.limit
    for i in range(1, n):
        for s in range(params.substeps):
            t = (s + 1) / params.substeps
            zeta = params.damping
            if params.limit_damping > 0:
                past = math.sqrt(sum(c * c for c in x)) - knee
                if past > 0:
                    zeta = min(4.0, zeta + params.limit_damping * (past / (params.limit - knee)) ** 2)
            for k in range(3):
                f = force(i - 1, k) * (1 - t) + force(i, k) * t   # inputs vary linearly
                v[k] += h * (f - w[k] * w[k] * x[k] - 2 * zeta * w[k] * v[k])
                x[k] += h * v[k]                                  # semi-implicit Euler
        out.append(_soft_clamp(tuple(x), params.limit))
    return out


# ---------------------------------------------------------------- lower-body regions

@dataclass(frozen=True)
class Region:
    """A soft area without bones of its own (butt, thigh, belly).

    ``wogen.bl.tissue_rig`` adds one helper bone per source bone and moves a share of that
    bone's skin weights onto it, by a smooth ellipsoid falloff. A helper only ever takes
    weight from its own parent, so the mesh deforms exactly as before until the solver moves
    the helper. Names are VRM humanoid bones; ``{side}`` makes one region per side.
    """
    name: str
    anchor: str                    # the centre is an offset from this bone's head
    sources: tuple[str, ...]       # bones that give up weight (each gets a helper)
    center: Vec                    # m, base rest space, left side (x is mirrored on the right)
    radii: Vec                     # m, ellipsoid where the falloff reaches zero
    params: TissueParams           # response of the helper's offset
    size: tuple[tuple[str, float], ...] = ()   # body slider -> exponent of the size factor
    share: float = 0.7             # of the source weight, at the centre
    core: float = 0.3              # inner fraction of the radii that gets the full share


# Firmer and much smaller than the bust: the offset is the helper bone's shift, and the skin
# moves by that times its helper weight (at most ``share``). Tuned by eye on walk, run and hop
# clips, so a walk only just shows and a landing gives a short, quick wobble (approved by eye
# 2026-11-10, with ``limit_damping`` off).
REGIONS: tuple[Region, ...] = (
    Region("butt", "{side}_upper_leg", ("hips", "{side}_upper_leg"),
           center=(0.012, 0.050, 0.010), radii=(0.095, 0.075, 0.105),
           params=TissueParams(frequency=(3.0, 3.4, 3.2), damping=0.3, gain=(0.4, 0.35, 0.6),
                               gravity_weight=0.1, limit=0.018, drive_limit=25.0,
                               limit_damping=0.0),
           size=(("hip_width", 1.5), ("thigh", 1.0))),
    Region("thigh", "{side}_upper_leg", ("{side}_upper_leg",),
           center=(0.0, 0.004, -0.150), radii=(0.100, 0.100, 0.150),
           params=TissueParams(frequency=(3.6, 3.6, 3.8), damping=0.35, gain=(0.35, 0.35, 0.5),
                               gravity_weight=0.05, limit=0.010, drive_limit=25.0,
                               limit_damping=0.0),
           size=(("thigh", 2.5),), share=0.6),
    Region("belly", "hips", ("hips", "spine"),
           center=(0.0, -0.085, 0.050), radii=(0.085, 0.060, 0.075),
           params=TissueParams(frequency=(2.8, 3.0, 2.8), damping=0.35, gain=(0.15, 0.25, 0.35),
                               gravity_weight=0.1, limit=0.008, drive_limit=25.0,
                               limit_damping=0.0),
           size=(("waist", 3.0),), share=0.6),
)
SHARE_CAP = 0.8      # most of a bone's weight that overlapping regions may take together


def sides(region: Region) -> tuple[str, ...]:
    """Sides a region exists on: ("left", "right"), or ("",) for one on the midline."""
    sided = "{side}" in region.anchor or any("{side}" in s for s in region.sources)
    return ("left", "right") if sided else ("",)


def falloff(point: Vec, region: Region, side: str = "left") -> float:
    """Share of a source bone's weight that ``region`` takes at ``point`` (an offset from the
    anchor bone's head, base rest space): ``share`` in the core, easing to 0 at the radii."""
    mirror = -1.0 if side == "right" else 1.0
    c = (region.center[0] * mirror, region.center[1], region.center[2])
    r = math.sqrt(sum(((p - q) / e) ** 2 for p, q, e in zip(point, c, region.radii)))
    t = min(1.0, max(0.0, (r - region.core) / (1.0 - region.core)))
    return region.share * (1.0 - t * t * (3.0 - 2.0 * t))


def region_size(region: Region, body: dict) -> float:
    """Size factor of a region from the body sliders (1.0 = base)."""
    size = 1.0
    for name, power in region.size:
        size *= float(body.get(name, 1.0)) ** power
    return size


def region_params(region: Region, body: dict) -> TissueParams:
    """The region's response for a body: slim moves less and quicker, curvy more."""
    return for_size(region.params, region_size(region, body))
