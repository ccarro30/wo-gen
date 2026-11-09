"""Procedural finger animation for motion without finger data (pure Python).

Motion capture (CMU) has no usable finger motion, so straight or frozen hands give the clip away.
Each frame's finger pose is a blend of the library hand shapes (``wogen.poses.HANDS``):

- **open** as the hand rises toward chest/head height (waves, cheers, flourishes) or moves
  fast relative to the chest while she isn't travelling (expressive gestures, not arm swing);
- **loose fist** while the body travels fast (running), unless the hand is open;
- **relaxed** otherwise (the solved thumb rests along the index finger);
- plus a small, slow per-finger drift so the hands never look frozen.

``openness`` turns per-frame measurements into smoothed (open, fist) amounts; ``finger_pose``
gives the pose for one hand. Applied by ``wogen.bl.mocap.animate_fingers``.
"""

from __future__ import annotations

import math

from .poses import FINGER_SEGMENTS, FINGERS, HANDS, hand

RAISE = (-0.4, 0.7)        # hand height between chest (0) and head (1) -> 0..1 raised
GESTURE_SPEED = (0.7, 2.2) # m/s, hand speed relative to the chest -> 0..1 gesturing
RUN_SPEED = (1.5, 2.4)     # m/s, body (hips) horizontal speed -> 0..1 running
TRAVEL_SPEED = (0.6, 1.4)  # m/s, body speed at which arm swing stops counting as a gesture
SMOOTHING = 0.15           # s, time constant of the zero-phase smoothing
FIST_SHARE = 0.65          # how far toward the fist shape a running hand curls
DRIFT_DEG = 4.0            # amplitude of the per-finger drift at rest


def _smoothstep(e0: float, e1: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def _smooth(values: list[float], fps: float) -> list[float]:
    """Exponential smoothing run forward then backward (no lag)."""
    if not values:
        return []
    a = 1.0 - math.exp(-1.0 / (SMOOTHING * fps))
    out = list(values)
    for order in (range(1, len(out)), range(len(out) - 2, -1, -1)):
        step = 1 if order.step == 1 else -1
        for i in order:
            out[i] = out[i - step] + a * (out[i] - out[i - step])
    return out


def openness(height: list[float], hand_speed: list[float], body_speed: list[float],
             fps: float) -> list[tuple[float, float]]:
    """Per frame (open, fist) amounts 0..1 for one hand.

    ``height``: hand height as a fraction from chest (0) to head (1); ``hand_speed``: m/s
    relative to the chest; ``body_speed``: hips' horizontal speed, m/s.
    """
    # Walking/running arm swing is fast too, but hands don't open for it: the gesture term
    # fades out as the body travels (a raised hand still opens, e.g. waving while walking).
    opened = [max(0.85 * _smoothstep(*RAISE, h),
                  0.7 * _smoothstep(*GESTURE_SPEED, s) * (1.0 - _smoothstep(*TRAVEL_SPEED, v)))
              for h, s, v in zip(height, hand_speed, body_speed)]
    running = [_smoothstep(*RUN_SPEED, v) for v in body_speed]
    opened, running = _smooth(opened, fps), _smooth(running, fps)
    return [(o, r * (1.0 - o)) for o, r in zip(opened, running)]


def finger_pose(side: str, open_amt: float, fist_amt: float, t: float = 0.0,
                drift: float = DRIFT_DEG) -> dict:
    """Finger rotations for one hand: relaxed blended toward open / loose fist, plus drift
    (``t`` in seconds; 0 drift for a static shape)."""
    relaxed, opened, fist = HANDS["relaxed"], HANDS["open"], HANDS["fist"]
    curls, spread = {}, {}
    side_phase = 0.0 if side == "left" else 1.7
    for k, finger in enumerate(FINGERS[1:]):
        r = relaxed["curls"][finger]
        o = opened["curls"][finger]
        f = fist["curls"][finger]
        wobble = drift * (1.0 - 0.5 * open_amt) * math.sin(
            2 * math.pi * (0.21 + 0.06 * k) * t + 0.7 * k + side_phase)
        curls[finger] = tuple(
            (rs + (os - rs) * open_amt) + (fs - rs) * FIST_SHARE * fist_amt + wobble * w
            for rs, os, fs, w in zip(r, o, f, (1.0, 0.8, 0.6)))
        spread[finger] = opened["spread"].get(finger, 0.0) * open_amt
    thumb = tuple(tuple(c * (1.0 - open_amt) for c in seg) for seg in relaxed["thumb"])
    return hand(side, curls, spread, thumb)


FINGER_BONES = [f"{side}_{finger}_{seg}" for side in ("left", "right")
                for finger in FINGERS for seg in FINGER_SEGMENTS[finger]]
