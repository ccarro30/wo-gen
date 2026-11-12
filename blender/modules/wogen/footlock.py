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


FLOOR_WINDOW = 1.0        # s: one contact sample (the window's low) per window of this length
FLOOR_LOW = 0.05          # share of frames whose lowest sole may dip below the fitted floor
FLOOR_AIRBORNE = 0.02     # m: windows this far above the trend (jumps) are left out of the fit
FLOOR_GAIN = 0.005        # m: a slope must cut the contacts' scatter this much (and by half)
FLOOR_MAX_DRIFT = 0.05    # m/s: the steepest floor drift accepted


def _low(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))]


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values))


def _fit_line(lows: list[float], size: int) -> tuple[float, float, float]:
    """(offset, slope per frame, scatter gain) of a line through each window's low, airborne
    windows dropped; the gain is how much it cuts the lows' scatter against a level floor."""
    n = len(lows)
    points = [(s + (size - 1) / 2, _low(lows[s:s + size], FLOOR_LOW))
              for s in list(range(0, n - size + 1, size)) + ([n - size] if n % size else [])]
    slope = offset = 0.0
    for _ in range(3):
        mx = sum(t for t, _ in points) / len(points)
        my = sum(z for _, z in points) / len(points)
        var = sum((t - mx) ** 2 for t, _ in points)
        slope = sum((t - mx) * (z - my) for t, z in points) / var if var > 0 else 0.0
        offset = my - slope * mx
        kept = [(t, z) for t, z in points if z - (offset + slope * t) < FLOOR_AIRBORNE]
        if len(kept) == len(points) or len(kept) < 2:
            break
        points = kept
    my = sum(z for _, z in points) / len(points)
    level = _rms([z - my for _, z in points])
    sloped = _rms([z - (offset + slope * t) for t, z in points])
    gain = level - sloped if sloped <= 0.5 * level else 0.0
    return offset, slope, gain


def floor_trend(lows: list[float], fps: float) -> list[float]:
    """Per frame, the height of the floor the clip was captured on, from each frame's lowest
    sole point. Capture floors aren't always level (a CMU walk climbs ~6 cm in 2.6 s), so a
    line in time is fitted through the low of each ``FLOOR_WINDOW``, leaving out windows
    well above it (airborne); a second fit on what's left after removing it takes out the
    bias of a window's low sitting at its lower end. The slope is kept only if it clearly
    explains the contacts (``FLOOR_GAIN``); the height is then the low ``FLOOR_LOW`` share
    of all frames with the slope removed, as for a level floor. Clips shorter than two
    windows are level."""
    n = len(lows)
    size = max(1, round(FLOOR_WINDOW * fps))
    slope = 0.0
    if n >= 2 * size:
        offset, slope, gain = _fit_line(lows, size)
        if gain < FLOOR_GAIN:
            slope = 0.0
        else:
            slope += _fit_line([z - (offset + slope * i) for i, z in enumerate(lows)], size)[1]
            limit = FLOOR_MAX_DRIFT / fps
            slope = max(-limit, min(limit, slope))
    offset = _low([z - slope * i for i, z in enumerate(lows)], FLOOR_LOW)
    return [offset + slope * i for i in range(n)]
