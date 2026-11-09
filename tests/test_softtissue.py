import math

from wogen import softtissue
from wogen.softtissue import GRAVITY, TissueParams

FPS = 24


def _impulse(frames=72, at=5, accel=20.0):
    """Upward acceleration for one frame (a sharp lift), otherwise still."""
    return [(0.0, 0.0, accel if i == at else 0.0) for i in range(frames)]


def _zero_crossings(values):
    return sum(1 for a, b in zip(values, values[1:]) if a * b < 0)


def test_still_body_stays_at_rest():
    out = softtissue.simulate([(0.0, 0.0, 0.0)] * 30, FPS)
    assert all(abs(c) < 1e-12 for o in out for c in o)


def test_lift_lags_down_then_settles_in_a_few_oscillations():
    p = TissueParams(limit=1.0)          # effectively unclamped
    z = [o[2] for o in softtissue.simulate(_impulse(), FPS, p)]
    first = next(v for v in z if abs(v) > 1e-6)
    assert first < 0                     # the chest goes up, the tissue lags behind
    peak = max(abs(v) for v in z)
    late = max(abs(v) for v in z[5 + FPS * 3 // 2:])   # 1.5 s after the impulse
    assert late < 0.05 * peak
    assert 3 <= _zero_crossings([v for v in z[5:] if abs(v) > 0.02 * peak]) <= 7


def test_mostly_vertical():
    p = TissueParams(limit=1.0)
    up = max(abs(o[2]) for o in softtissue.simulate(_impulse(), FPS, p))
    side = max(abs(o[0]) for o in softtissue.simulate(
        [(a[2], 0.0, 0.0) for a in _impulse()], FPS, p))
    assert side < 0.6 * up


def test_soft_clamp_bounds_hard_landings():
    p = TissueParams()
    out = softtissue.simulate(_impulse(accel=400.0), FPS, p)
    assert max(math.sqrt(sum(c * c for c in o)) for o in out) <= p.limit + 1e-9


def test_accelerations_of_a_parabola():
    pos = [(0.0, 0.0, 0.5 * 9.81 * (i / FPS) ** 2) for i in range(10)]
    acc = softtissue.accelerations(pos, FPS)
    assert all(abs(a[2] - 9.81) < 1e-6 for a in acc)


def test_bigger_bust_is_bouncier_smaller_is_firmer():
    small, base, big = (softtissue.for_size(TissueParams(), s) for s in (0.85, 1.0, 1.3))
    assert small.gain[2] < base.gain[2] < big.gain[2]
    assert small.frequency[2] > base.frequency[2] > big.frequency[2]
    assert small.damping > base.damping > big.damping
    assert big.limit > base.limit


def test_bowing_lets_the_bust_hang_forward():
    # Chest pitched 90 degrees forward: gravity points along -y (forward) in the chest frame.
    out = softtissue.simulate([(0.0, 0.0, 0.0)] * 5, FPS, TissueParams(),
                              gravity=[(0.0, GRAVITY[2], 0.0)] * 5)
    assert out[-1][1] < 0 and out[-1][2] > 0
