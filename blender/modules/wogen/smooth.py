"""Temporal smoothing of rotation tracks (pure Python; used by ``wogen.bl.mocap``).

Captured foot and toe rotations flicker 15-30 degrees from frame to frame (marker noise);
on screen the foot snaps between positions. ``smooth_quaternions`` low-passes a track with
a Gaussian kernel: neighbours are first put in the same hemisphere (q and -q are the same
rotation), weighted, summed and renormalized, which is accurate for the small angles
between neighbouring frames. Ends use the frames that exist (no padding drift).
"""

from __future__ import annotations

import math

Quat = tuple[float, float, float, float]


def gaussian(sigma: float) -> list[float]:
    """Normalized Gaussian weights for offsets -r..r (r = ceil(3 sigma))."""
    if sigma <= 0:
        return [1.0]
    r = max(1, math.ceil(3 * sigma))
    w = [math.exp(-0.5 * (i / sigma) ** 2) for i in range(-r, r + 1)]
    s = sum(w)
    return [x / s for x in w]


def _dot(a: Quat, b: Quat) -> float:
    return sum(x * y for x, y in zip(a, b))


def average_quaternions(quats: list[Quat], weights: list[float]) -> Quat:
    """Weighted average of nearby rotations (each put in the first one's hemisphere)."""
    ref = quats[0]
    acc = [0.0, 0.0, 0.0, 0.0]
    for q, w in zip(quats, weights):
        s = w if _dot(ref, q) >= 0 else -w
        for c in range(4):
            acc[c] += s * q[c]
    norm = math.sqrt(sum(a * a for a in acc)) or 1.0
    return tuple(a / norm for a in acc)


def smooth_quaternions(track: list[Quat], sigma: float) -> list[Quat]:
    """Gaussian-smoothed copy of ``track`` (one quaternion per frame, w first)."""
    if sigma <= 0 or len(track) < 3:
        return list(track)
    # Hemisphere continuity along the track first.
    q = [tuple(track[0])]
    for t in track[1:]:
        q.append(tuple(t) if _dot(q[-1], t) >= 0 else tuple(-x for x in t))
    weights = gaussian(sigma)
    r = len(weights) // 2
    out = []
    for i in range(len(q)):
        acc = [0.0, 0.0, 0.0, 0.0]
        total = 0.0
        for k, w in enumerate(weights):
            j = i + k - r
            if 0 <= j < len(q):
                for c in range(4):
                    acc[c] += w * q[j][c]
                total += w
        norm = math.sqrt(sum(a * a for a in acc)) or 1.0
        out.append(tuple(a / norm for a in acc))
    return out
