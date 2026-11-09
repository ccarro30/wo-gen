import pytest

from wogen import motions as anim
from wogen import poses as P  # noqa: E402


def _feet(keys):
    out = []
    for frame, pose, *_ in keys:
        pose = P.resolve_pose(pose)
        out.append((frame, pose["ik:left_foot"]["offset"][1], pose["ik:right_foot"]["offset"][1],
                    pose["hips_location"][1] if "hips_location" in pose else 0.0))
    return out


def test_walk_alternates_feet_and_moves_forward():
    keys = anim.walk_keys(steps=4, stride=0.3)
    frames = [k[0] for k in keys]
    assert frames == sorted(frames) and len(set(frames)) == len(frames)
    feet = _feet(keys)
    # Forward is -Y: offsets only decrease, and both feet end together, 3.5 strides ahead.
    for (_, l0, r0, _), (_, l1, r1, _) in zip(feet, feet[1:]):
        assert l1 <= l0 + 1e-9 and r1 <= r0 + 1e-9
    assert feet[-1][1] == pytest.approx(-1.05) and feet[-1][2] == pytest.approx(-1.05)
    # The body stays between the feet.
    for _, l, r, hips in feet:
        assert min(l, r) - 1e-9 <= hips <= max(l, r) + 1e-9
    # Feet take turns: right moves on step 1, left on step 2.
    contacts = feet[2::2][:2]
    assert contacts[0][2] < 0 and contacts[0][1] == 0
    assert contacts[1][1] < 0


def test_presets_resolve_and_have_options():
    for name, make in anim.PRESETS.items():
        keys = make()
        assert keys and all(isinstance(k[0], int) for k in keys), name
        for k in keys:
            P.resolve_pose(k[1])
    assert anim.PRESET_OPTIONS["walk"]["follow"] and anim.PRESET_OPTIONS["spin"]["substeps"] > 1


def test_spin_ends_a_full_turn_round():
    keys = anim.PRESETS["spin"]()
    yaws = [P.resolve_pose(k[1]).get("hips", (0, 0, 0))[2] for k in keys]
    assert max(yaws) == pytest.approx(360 + yaws[0] if yaws[0] else 360)
    assert all(b - a <= 90 for a, b in zip(yaws, yaws[1:]))   # quaternion keys stay < 180


def _hips_y(pose):
    return P.resolve_pose(pose).get("hips_location", (0, 0, 0))[1]


def test_chain_orders_frames_and_carries_position_after_travel():
    keys, opts = anim.build("wave_hello,walk,bow")
    frames = [k[0] for k in keys]
    assert frames == sorted(frames) and len(set(frames)) == len(frames)
    assert opts["follow"] and opts["carry"] == 0.85
    walk_end = _hips_y(anim.walk_keys()[-1][1])
    bow = anim.PRESETS["bow"]()
    for original, chained in zip(bow, keys[-len(bow):]):   # the bow happens where she stopped
        a, b = P.resolve_pose(original[1]), P.resolve_pose(chained[1])
        assert b["hips_location"][1] == pytest.approx(a.get("hips_location", (0, 0, 0))[1] + walk_end)
        for chain in ("ik:left_foot", "ik:right_foot"):
            if chain in a:
                assert b[chain]["offset"][1] == pytest.approx(a[chain]["offset"][1] + walk_end)


def test_chain_rejects_loops_and_unknown_names():
    with pytest.raises(ValueError):
        anim.build("wave_hello,walk_loop")
    with pytest.raises(KeyError):
        anim.build("wave_hello,moonwalk")


@pytest.mark.parametrize("name", ["walk_loop", "run_loop"])
def test_loop_cycle_repeats(name):
    keys, opts = anim.build(name)
    n = opts["loop"]
    by_frame = {k[0]: P.resolve_pose(k[1]) for k in keys}
    end = keys[-1][0]
    a, b = by_frame[end - n], by_frame[end]
    dy = b["hips_location"][1] - a["hips_location"][1]
    assert dy < 0                                     # she travelled forward
    for name_ in a:
        if name_ == "hips_location":
            assert b[name_][0] == pytest.approx(a[name_][0]) and b[name_][2] == pytest.approx(a[name_][2])
        elif name_.startswith("ik:"):
            assert b[name_]["offset"][1] == pytest.approx(a[name_]["offset"][1] + dy)
        else:
            assert b[name_] == a[name_], name_


def test_run_is_faster_and_longer_than_walk():
    walk, run = anim.walk_keys(), anim.run_keys()
    assert abs(_hips_y(run[-1][1])) > abs(_hips_y(walk[-1][1]))
    assert (run[3][0] - run[1][0]) < (walk[3][0] - walk[1][0])


def test_parse_chain_mixes_presets_and_mocap():
    segs = anim.parse_chain("wave_hello, mocap:happy_walk ,bow,mocap:salsa@2-6,mocap:dance@1.5-")
    assert segs == [("preset", "wave_hello"), ("mocap", "happy_walk", 0.0, None),
                    ("preset", "bow"), ("mocap", "salsa", 2.0, 6.0), ("mocap", "dance", 1.5, None)]
    with pytest.raises(KeyError):
        anim.parse_chain("wave_hello,moonwalk")
    with pytest.raises(ValueError):
        anim.parse_chain("mocap:salsa@2")
    with pytest.raises(ValueError):
        anim.parse_chain("bow,walk_loop")
    with pytest.raises(ValueError):
        anim.build("wave_hello,mocap:walk")          # mocap chains are built in Blender


def test_merge_options_and_placement():
    opts = anim.merge_options({}, anim.PRESET_OPTIONS["spin"])
    opts = anim.merge_options(opts, anim.MOCAP_OPTIONS)
    assert opts == {"substeps": 3, "follow": True, "carry": 0.85, "travel": True}
    part = anim.placed(anim.PRESETS["bow"](), 50, (0.0, -1.0))
    assert part[0][0] == 50
    assert P.resolve_pose(part[0][1])["hips_location"][1] == pytest.approx(-1.0)
    keys = [(1, "idle", "happy"), (9, "idle", "happy")]
    anim.drop_trailing_hold(keys)
    assert keys == [(1, "idle", "happy")]
