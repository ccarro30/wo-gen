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


def test_bigger_bust_moves_more_smaller_is_firmer():
    small, base, big = (softtissue.for_size(TissueParams(), s) for s in (0.85, 1.0, 1.3))
    assert small.gain[2] < base.gain[2] < big.gain[2]
    assert small.frequency[2] > base.frequency[2] > big.frequency[2]
    assert big.limit > base.limit

    def peak(p):
        return max(abs(o[2]) for o in softtissue.simulate(_impulse(), FPS, p))
    assert peak(small) < peak(base) < peak(big)


def test_bowing_lets_the_bust_hang_forward():
    # Chest pitched 90 degrees forward: gravity points along -y (forward) in the chest frame.
    out = softtissue.simulate([(0.0, 0.0, 0.0)] * 5, FPS, TissueParams(),
                              gravity=[(0.0, GRAVITY[2], 0.0)] * 5)
    assert out[-1][1] < 0 and out[-1][2] > 0


# ---------------------------------------------------------------- lower-body regions

REGIONS = {r.name: r for r in softtissue.REGIONS}


def test_region_falloff_is_full_at_the_centre_and_zero_outside():
    for region in softtissue.REGIONS:
        c, r = region.center, region.radii
        assert softtissue.falloff(c, region) == region.share
        edge = (c[0], c[1], c[2] + r[2] * 1.01)
        assert softtissue.falloff(edge, region) == 0.0
        half = softtissue.falloff((c[0], c[1], c[2] + r[2] * 0.65), region)
        assert 0.0 < half < region.share


def test_region_falloff_mirrors_for_the_right_side():
    butt = REGIONS["butt"]
    x, y, z = butt.center
    assert softtissue.falloff((-x, y, z), butt, "right") == butt.share
    assert softtissue.sides(butt) == ("left", "right")
    assert softtissue.sides(REGIONS["belly"]) == ("",)


def test_overlapping_regions_leave_weight_on_the_bone():
    assert all(r.share <= softtissue.SHARE_CAP < 1.0 for r in softtissue.REGIONS)


def test_slim_bodies_move_less_and_curvy_more():
    slim = {"hip_width": 0.92, "thigh": 0.90, "waist": 0.88}
    curvy = {"hip_width": 1.10, "thigh": 1.12, "waist": 1.08}

    def peak(p):
        return max(abs(o[2]) for o in softtissue.simulate(_impulse(), FPS, p))
    for region in softtissue.REGIONS:
        assert softtissue.region_size(region, {}) == 1.0
        a, b, c = (softtissue.region_params(region, body) for body in (slim, {}, curvy))
        assert a.gain[2] < b.gain[2] < c.gain[2]
        assert peak(a) < peak(b) < peak(c)


def test_lower_body_is_firmer_and_subtler_than_the_bust():
    bust = TissueParams()
    for region in softtissue.REGIONS:
        p = region.params
        assert p.frequency[2] > bust.frequency[2] and p.damping > bust.damping
        assert p.limit < 0.5 * bust.limit and p.gain[2] < bust.gain[2]


def test_drive_limit_tames_acceleration_spikes():
    p = TissueParams(limit=1.0, drive_limit=25.0)
    free = TissueParams(limit=1.0, drive_limit=0.0)

    def peak(params, accel):
        return max(abs(o[2]) for o in softtissue.simulate(_impulse(accel=accel), FPS, params))
    assert peak(p, 5.0) > 0.95 * peak(free, 5.0)          # gentle motion passes through
    assert peak(p, 500.0) < 0.1 * peak(free, 500.0)       # a spike is held to the limit
    assert peak(p, 500.0) <= 1.01 * peak(free, 25.0)


def test_acceleration_window_is_the_same_at_any_frame_rate():
    def bounce(fps):          # a 3 Hz bounce, 4 cm peak to peak, sampled at ``fps``
        return [(0.0, 0.0, 0.02 * math.sin(2 * math.pi * 3 * i / fps)) for i in range(fps)]
    at24 = softtissue.accelerations(bounce(24), 24, 1 / 24)
    at48 = softtissue.accelerations(bounce(48), 48, 1 / 24)
    assert softtissue.accelerations(bounce(24), 24) == at24      # default: one frame
    for i in range(2, 22):
        assert abs(at48[2 * i][2] - at24[i][2]) < 1e-9


def test_acceleration_window_smooths_a_one_frame_spike():
    pos = [(0.0, 0.0, 0.0)] * 10 + [(0.0, 0.0, 0.01)] + [(0.0, 0.0, 0.0)] * 10
    one = max(abs(a[2]) for a in softtissue.accelerations(pos, FPS))
    two = max(abs(a[2]) for a in softtissue.accelerations(pos, FPS, 2 / FPS))
    assert two < 0.6 * one


def test_limit_damping_only_acts_near_the_limit():
    def resonant(amp):        # steps at the bust's own vertical frequency
        f = TissueParams().frequency[2]
        return [(0.0, 0.0, amp * math.sin(2 * math.pi * f * i / FPS)) for i in range(120)]
    on, off = TissueParams(), TissueParams(limit_damping=0.0)

    def run(params, amp):
        return softtissue.simulate(resonant(amp), FPS, params)
    small_on, small_off = run(on, 1.0), run(off, 1.0)       # a walk: well inside the limit
    assert max(abs(a[2] - b[2]) for a, b in zip(small_on, small_off)) < 1e-12

    def whip(out):            # biggest move between frames: the clamped tip whipping across
        return max(math.dist(a, b) for a, b in zip(out, out[1:]))
    assert whip(run(on, 15.0)) < 0.75 * whip(run(off, 15.0))


def test_variation_is_seeded_small_and_differs_per_side():
    base = TissueParams()
    left, right = (softtissue.vary(base, 7, k) for k in ("J_Sec_L_Bust1", "J_Sec_R_Bust1"))
    assert left == softtissue.vary(base, 7, "J_Sec_L_Bust1")        # deterministic
    assert left != right and left != softtissue.vary(base, 8, "J_Sec_L_Bust1")
    for p in (left, right):
        for a, b in zip(p.frequency, base.frequency):
            assert abs(a / b - 1) <= softtissue.VARIATION["frequency"] + 1e-9
        assert abs(p.damping / base.damping - 1) <= softtissue.VARIATION["damping"] + 1e-9
    assert softtissue.vary(base, 7, "x", scale=0.0) == base
