"""Idle drift: a slowly varying, seeded push for spring chains (hair, ribbons, skirts).

Pure Python (no bpy), so it's unit-tested. ``wogen.bl.physics`` adds ``strength * drift(t)``
to every spring step like extra gravity, so hair and skirts never hang dead still between
moves. Each axis is a sum of a few slow sines with seeded phases and slightly detuned
frequencies: smooth, never repeating within a clip, and the same for the same seed.

Axes are the character's rest frame: x lateral, y depth (-y is forward), z vertical. The
drift is mostly sideways, a little in depth and hardly vertical, like a light breeze.
"""

from __future__ import annotations

import math
import random

Vec = tuple[float, float, float]

AXIS_WEIGHTS: Vec = (1.0, 0.6, 0.2)
# Hz: a slow sway, a medium one and a light flutter, with weights. Below about 0.6 Hz it
# reads as air moving, not as the character shaking.
WAVES: tuple[tuple[float, float], ...] = ((0.13, 0.55), (0.29, 0.3), (0.61, 0.15))


def drift(t: float, seed: int = 0) -> Vec:
    """Drift direction and amount at time ``t`` (seconds): each axis within about +-1 times
    its ``AXIS_WEIGHTS``."""
    rng = random.Random(seed * 7919 + 17)
    out = []
    for weight in AXIS_WEIGHTS:
        value = 0.0
        for freq, amp in WAVES:
            f = freq * rng.uniform(0.85, 1.15)
            value += amp * math.sin(2 * math.pi * f * t + rng.uniform(0.0, 2 * math.pi))
        out.append(weight * value)
    return tuple(out)
