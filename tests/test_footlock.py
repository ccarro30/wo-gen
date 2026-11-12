import math

import pytest

from wogen import footlock as F

FPS = 24.0


def _foot(heel, toe):
    return {"heel": heel, "toe": toe}


def _held(samples, offsets, key):
    return [(s[key][0] + dx, s[key][1] + dy) for s, (dx, dy) in zip(samples, offsets)]


def test_skidding_heel_strike_is_held_where_it_lands():
    # The heel touches down at y=0 but the capture slides it 2 cm/frame for 6 frames.
    samples = [_foot((0.0, -0.02 * i, 0.0), (0.0, -0.02 * i - 0.2, 0.05)) for i in range(6)]
    held = _held(samples, F.contact_offsets(samples, 0.0, FPS), "heel")
    assert all(p == pytest.approx((0.0, 0.0)) for p in held)


def test_heel_to_toe_roll_keeps_the_foot_put():
    # Heel planted (sliding 1 cm/frame), then the toe becomes the lower point: no jump, and
    # the toe is then held too.
    samples = [_foot((0.0, -0.01 * i, 0.0), (0.0, -0.01 * i - 0.2, 0.004)) for i in range(4)]
    samples += [_foot((0.0, -0.01 * i, 0.02), (0.0, -0.01 * i - 0.2, 0.0)) for i in range(4, 8)]
    off = F.contact_offsets(samples, 0.0, FPS)
    toe = _held(samples, off, "toe")
    assert all(p == pytest.approx(toe[4]) for p in toe[4:])
    heel = _held(samples, off, "heel")
    assert heel[3] == pytest.approx(heel[0])
    assert abs(heel[4][1] - heel[3][1]) < 0.011          # no jump at the switch


def test_lock_eases_out_after_lift_off():
    planted = [_foot((0.0, -0.01 * i, 0.0), (0.0, -0.2, 0.0)) for i in range(5)]
    swing = [_foot((0.0, -0.05 - 0.05 * i, 0.10), (0.0, -0.25 - 0.05 * i, 0.10)) for i in range(8)]
    off = F.contact_offsets(planted + swing, 0.0, FPS)
    mags = [abs(dy) for _, dy in off[4:]]
    assert mags[0] > 0
    assert all(b <= a + 1e-12 for a, b in zip(mags, mags[1:]))   # decays monotonically
    assert off[4 + F.RELEASE_FRAMES] == (0.0, 0.0)


def test_swing_foot_and_slow_hover_are_not_locked():
    fast_low = [_foot((0.0, -0.1 * i, 0.02), (0.0, -0.1 * i - 0.2, 0.02)) for i in range(5)]
    assert all(o == (0.0, 0.0) for o in F.contact_offsets(fast_low, 0.0, FPS))
    high = [_foot((0.0, 0.0, 0.08), (0.0, -0.2, 0.08)) for _ in range(5)]
    assert all(o == (0.0, 0.0) for o in F.contact_offsets(high, 0.0, FPS))


def test_floor_height_is_respected():
    # With shoes lifting the soles 3 cm, a sole at 3 cm is on the floor.
    samples = [_foot((0.0, -0.02 * i, 0.03), (0.0, -0.2, 0.06)) for i in range(4)]
    held = _held(samples, F.contact_offsets(samples, 0.03, FPS), "heel")
    assert all(p == pytest.approx((0.0, 0.0)) for p in held)


def test_floor_trend_follows_a_sloped_capture_floor():
    # A walk on a floor rising 6 cm over 3 s; each step's swing lifts the lowest sole a bit.
    lows = [0.06 * i / 72 + (0.004 if i % 12 < 3 else 0.0) for i in range(72)]
    trend = F.floor_trend(lows, FPS)
    assert abs(trend[0]) < 0.002 and abs(trend[-1] - 0.06 * 71 / 72) < 0.002


def test_floor_trend_keeps_a_noisy_level_floor_level():
    lows = [0.004 * ((i * 7) % 5) / 4 for i in range(192)]       # contact jitter, no drift
    trend = F.floor_trend(lows, FPS)
    assert len(set(trend)) == 1


def test_floor_trend_ignores_jumps_and_short_clips_are_level():
    lows = [0.0] * 96
    lows[30:54] = [0.3] * 24                       # a one-second jump
    assert max(abs(z) for z in F.floor_trend(lows, FPS)) < 1e-9
    assert F.floor_trend([0.02, 0.01, 0.03], FPS) == [0.01] * 3
