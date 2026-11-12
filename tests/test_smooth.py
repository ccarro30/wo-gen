import math

from wogen import smooth


def _about_x(deg):
    h = math.radians(deg) / 2
    return (math.cos(h), math.sin(h), 0.0, 0.0)


def _angle(q):
    return math.degrees(2 * math.acos(min(1.0, abs(q[0]))))


def test_flicker_is_damped_but_a_steady_turn_is_kept():
    noisy = [_about_x(2 * i + (12 if i % 2 else -12)) for i in range(40)]   # +-12 deg flicker
    out = smooth.smooth_quaternions(noisy, 1.5)
    steps = [abs(_angle(out[i + 1]) - _angle(out[i])) for i in range(5, 34)]
    assert max(steps) < 3.5                       # was ~26 deg per frame
    assert abs(_angle(out[20]) - 40) < 1.0        # the underlying 2 deg/frame turn stays


def test_sign_flips_dont_cancel_and_zero_sigma_is_identity():
    track = [_about_x(10)] * 10
    track[5] = tuple(-x for x in track[5])        # same rotation, other hemisphere
    out = smooth.smooth_quaternions(track, 2.0)
    assert all(abs(_angle(q) - 10) < 1e-6 for q in out)
    assert smooth.smooth_quaternions(track, 0) == track
