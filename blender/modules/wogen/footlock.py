"""Foot locking for retargeted motion (pure Python; applied by ``wogen.bl.mocap.lock_feet``).

Given each frame's sole points of one foot (heel and toe tip, armature space), work out a
horizontal correction per frame that keeps a planted foot from skating:

- the pivot is the lower of heel and toe tip, so a heel-to-toe roll is kept;
- a pivot touching the floor is planted (a heel stops when it strikes, even if the capture
  still slides it); just above the floor it's planted only when nearly still;
- while planted, the correction holds the pivot where it landed; switching pivot mid-contact
  carries the correction over, so the foot doesn't jump;
- after lift-off the correction eases back to zero over a few frames.
"""

from __future__ import annotations

import math

Vec3 = tuple[float, float, float]

SKATE_HEIGHT = 0.01       # m: a sole point this close to the floor is touching it
CONTACT_HEIGHT = 0.03     # m: a sole point this low may be planted (if nearly still)
CONTACT_SPEED = 0.6       # m/s horizontal: slower than this while low = planted
RELEASE_FRAMES = 4        # ease the lock out over this many frames after lift-off


def contact_offsets(samples: list[dict[str, Vec3]], floor: float, fps: float) -> list[tuple[float, float]]:
    """``samples``: per frame ``{"heel": (x, y, z), "toe": (x, y, z)}``. ``floor``: the sole
    height when standing. Returns the (dx, dy) correction per frame."""
    out: list[tuple[float, float]] = []
    c = (0.0, 0.0)
    locked: tuple[float, float] | None = None
    pivot_prev = None
    since_release = RELEASE_FRAMES
    release_from = (0.0, 0.0)
    n = len(samples)
    for i, s in enumerate(samples):
        heights = {k: s[k][2] - floor for k in ("heel", "toe")}
        pivot = min(heights, key=heights.get)
        p = s[pivot]
        lo, hi = max(i - 1, 0), min(i + 1, n - 1)                  # central difference
        a, b = samples[lo][pivot], samples[hi][pivot]
        speed = math.hypot(b[0] - a[0], b[1] - a[1]) * fps / max(hi - lo, 1)
        h = heights[pivot]
        planted = h < SKATE_HEIGHT or (h < CONTACT_HEIGHT and speed < CONTACT_SPEED)
        if planted:
            if locked is None:                       # touchdown (mid-release: continue from c)
                if since_release >= RELEASE_FRAMES:
                    c = (0.0, 0.0)
                locked = (p[0] + c[0], p[1] + c[1])
            elif pivot != pivot_prev:                # heel -> toe roll: keep the foot put
                locked = (p[0] + c[0], p[1] + c[1])
            c = (locked[0] - p[0], locked[1] - p[1])
            since_release = 0
            release_from = c
        else:
            locked = None
            if since_release < RELEASE_FRAMES:
                since_release += 1
                t = since_release / RELEASE_FRAMES
                k = 1.0 - t * t * (3 - 2 * t)
                c = (release_from[0] * k, release_from[1] * k)
            else:
                c = (0.0, 0.0)
        pivot_prev = pivot
        out.append(c)
    return out
