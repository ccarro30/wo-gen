import math

from wogen.drift import AXIS_WEIGHTS, drift


def test_same_seed_same_drift_other_seed_differs():
    assert drift(1.7, 3) == drift(1.7, 3)
    assert drift(1.7, 3) != drift(1.7, 4)


def test_bounded_and_mostly_sideways():
    samples = [drift(i / 24, 1) for i in range(24 * 30)]
    for k, weight in enumerate(AXIS_WEIGHTS):
        assert max(abs(s[k]) for s in samples) <= weight + 1e-9
    rms = [math.sqrt(sum(s[k] ** 2 for s in samples) / len(samples)) for k in range(3)]
    assert rms[0] > rms[1] > rms[2]


def test_slow_and_smooth():
    a = [drift(i / 24, 2)[0] for i in range(24 * 10)]
    assert max(abs(x - y) for x, y in zip(a, a[1:])) < 0.1    # per frame, of a +-1 range
