"""Soft-tissue secondary motion (breasts): damped springs driven by the body's acceleration.

Pure Python (no bpy), so it's unit-tested. ``wogen.bl.physics`` samples the chest each frame
and turns the offsets into bust-bone rotations.

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
from dataclasses import dataclass, replace

Vec = tuple[float, float, float]
GRAVITY: Vec = (0.0, 0.0, -9.81)


@dataclass(frozen=True)
class TissueParams:
    frequency: Vec = (2.0, 2.5, 2.2)   # Hz per axis (lateral, depth, vertical); lower = looser
    damping: float = 0.2               # damping ratio (0 = rings forever, 1 = no overshoot)
    # Response per axis: mostly vertical, some sway. The offset is measured at the tip of the
    # bust chain (~15 cm from its base, which sits inside the chest), so it reads larger than
    # the visible motion (``wogen.bl.physics`` turns part of it into a shift of the whole
    # breast, the rest into a swing). Tuned so a walk moves about 1 cm there (slight but
    # visible) while hops and jumps reach the clamp (a real shock).
    gain: Vec = (0.4, 0.26, 0.9)
    gravity_weight: float = 0.4        # how much posture changes the rest sag
    limit: float = 0.054               # m, soft clamp of the offset at the tip
    substeps: int = 8                  # integration steps per frame


def for_size(params: TissueParams, bust: float) -> TissueParams:
    """Scale for the ``bust`` body slider (1.0 = base): bigger is bouncier (moves more, slower,
    rings longer); smaller is firmer (moves less, quicker, settles sooner)."""
    s = max(0.5, bust)
    return replace(params,
                   frequency=tuple(f * s ** -0.5 for f in params.frequency),
                   damping=min(0.9, params.damping * s ** -0.5),
                   gain=tuple(g * s ** 1.8 for g in params.gain),
                   limit=params.limit * s ** 0.25)


def accelerations(positions: list[Vec], fps: float) -> list[Vec]:
    """Per-frame acceleration of a sampled point (central differences; ends repeat)."""
    n = len(positions)
    if n < 3:
        return [(0.0, 0.0, 0.0)] * n
    out = [tuple((positions[i + 1][k] - 2 * positions[i][k] + positions[i - 1][k]) * fps * fps
                 for k in range(3)) for i in range(1, n - 1)]
    return [out[0]] + out + [out[-1]]


def _soft_clamp(x: Vec, limit: float) -> Vec:
    length = math.sqrt(sum(c * c for c in x))
    if length < 1e-12 or limit <= 0:
        return x
    k = limit * math.tanh(length / limit) / length
    return tuple(c * k for c in x)


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

    def force(i: int, k: int) -> float:
        g = params.gravity_weight * (gravity[i][k] - GRAVITY[k])
        return params.gain[k] * (g - accels[i][k])

    if n == 0:
        return []
    x = [force(0, k) / (w[k] * w[k]) for k in range(3)]
    v = [0.0, 0.0, 0.0]
    out = [_soft_clamp(tuple(x), params.limit)]
    h = 1.0 / fps / params.substeps
    for i in range(1, n):
        for s in range(params.substeps):
            t = (s + 1) / params.substeps
            for k in range(3):
                f = force(i - 1, k) * (1 - t) + force(i, k) * t   # inputs vary linearly
                v[k] += h * (f - w[k] * w[k] * x[k] - 2 * params.damping * w[k] * v[k])
                x[k] += h * v[k]                                  # semi-implicit Euler
        out.append(_soft_clamp(tuple(x), params.limit))
    return out
