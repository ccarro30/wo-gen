import pytest

from wogen import hands as H
from wogen import poses as P

FPS = 24.0


def test_raised_or_fast_hands_open_and_running_curls():
    n = 48
    rest = H.openness([-1.0] * n, [0.1] * n, [0.0] * n, FPS)
    raised = H.openness([1.0] * n, [0.1] * n, [0.0] * n, FPS)
    gesture = H.openness([-1.0] * n, [3.0] * n, [0.0] * n, FPS)
    running = H.openness([-1.0] * n, [0.5] * n, [3.5] * n, FPS)
    assert rest[n // 2] == pytest.approx((0.0, 0.0))
    assert raised[n // 2][0] > 0.8 and gesture[n // 2][0] > 0.6
    assert running[n // 2][1] > 0.9 and running[n // 2][0] < 0.05


def test_openness_is_smoothed_without_lag():
    n = 49
    step = [-1.0] * 24 + [1.0] * 25                        # hand raised at frame 24
    o = [a for a, _ in H.openness(step, [0.0] * n, [0.0] * n, FPS)]
    assert all(b >= a - 1e-9 for a, b in zip(o, o[1:]))    # monotonic ramp, no overshoot
    assert 0.2 < o[24] < 0.65                              # centred on the change (zero phase)
    assert o[0] < 0.05 and o[-1] > 0.8


def test_finger_pose_matches_library_shapes():
    relaxed = H.finger_pose("left", 0.0, 0.0, drift=0.0)
    assert relaxed == P.hand_shape("relaxed", "left")
    opened = H.finger_pose("right", 1.0, 0.0, drift=0.0)
    assert opened["right_index_proximal"][1] == pytest.approx(0.0)
    assert all(v == pytest.approx(0.0) for seg in ("metacarpal", "proximal", "distal")
               for v in opened[f"right_thumb_{seg}"])
    fist = H.finger_pose("left", 0.0, 1.0, drift=0.0)
    assert fist["left_middle_proximal"][1] > relaxed["left_middle_proximal"][1] + 20
    P.resolve_pose(H.finger_pose("left", 0.4, 0.3, t=1.3))   # valid pose names


def test_drift_moves_fingers_a_little():
    a = H.finger_pose("left", 0.0, 0.0, t=0.0)
    b = H.finger_pose("left", 0.0, 0.0, t=1.0)
    diffs = [abs(a[k][1] - b[k][1]) for k in a if "thumb" not in k]
    assert 0 < max(diffs) <= 2 * H.DRIFT_DEG + 1e-9


def test_arm_swing_while_travelling_does_not_open_hands():
    n = 48
    walk = H.openness([-1.0] * n, [2.5] * n, [1.5] * n, FPS)        # fast swing, walking pace
    assert walk[n // 2][0] < 0.05
    wave = H.openness([1.0] * n, [2.5] * n, [1.5] * n, FPS)         # raised hand while walking
    assert wave[n // 2][0] > 0.8
