import pytest

from wogen import poses as P


def test_mirror_swaps_sides_and_flips_y_z():
    m = P.mirror({"left_upper_arm": (10, 20, 30), "head": (1, 2, 3)})
    assert m == {"right_upper_arm": (10, -20, -30), "head": (1, -2, -3)}


def test_mirror_is_an_involution_including_ik():
    pose = P.merge({"left_hand": (1, 2, 3)},
                   P.ik("left", "left_upper_leg", (0.1, 0.0, 0.1), (1.0, 0.5, 0.0)))
    assert P.mirror(P.mirror(pose)) == pose


def test_mirror_ik_flips_target_offset_and_pole():
    m = P.mirror(P.ik("left", "left_upper_leg", (0.1, 0.02, 0.1), (1.0, 0.5, 0.0)))
    assert m == {"ik:right_hand": {"target": "right_upper_leg", "offset": (-0.1, 0.02, 0.1),
                                   "pole": (-1.0, 0.5, 0.0)}}


def test_plant_mirrors_rest_anchor_and_orient():
    left = P.plant("left", (0.02, -0.2, 0.03), (0.3, -1.0, 0.0), (28, 4, 6))
    right = P.mirror(left)["ik:right_foot"]
    assert right == {"target": "rest:right_foot", "offset": (-0.02, -0.2, 0.03),
                     "pole": (-0.3, -1.0, 0.0), "orient": (28, -4, -6)}


def test_all_library_ik_entries_are_valid_chains():
    for name, pose in P.POSES.items():
        for key, entry in pose.items():
            if key.startswith(P.IK_PREFIX):
                assert key[len(P.IK_PREFIX):] in P.IK_CHAINS, (name, key)
                assert {"target", "offset", "pole"} <= entry.keys(), (name, key)


def test_dump_load_keeps_orient(tmp_path):
    pose = P.POSES["stride"]
    path = tmp_path / "s.toml"
    path.write_text(P.dump_pose(pose), encoding="utf-8")
    loaded = P.load_pose(path)
    assert loaded["ik:right_foot"]["orient"] == pytest.approx(pose["ik:right_foot"]["orient"])
    assert loaded["hips_location"] == pytest.approx(pose["hips_location"])


def test_both_adds_mirrored_right_side():
    p = P.both({"left_upper_arm": (0, 70, 0), "spine": (2, 0, 0)})
    assert p["right_upper_arm"] == (0, -70, 0) and p["spine"] == (2, 0, 0)


def test_hand_shapes_cover_all_finger_segments():
    for shape in P.HANDS:
        pose = P.hand_shape(shape, "right")
        assert len(pose) == 15
        assert all(k.startswith("right_") for k in pose)


def test_resolve_list_merges_in_order():
    p = P.resolve_pose(["a_pose", {"left_upper_arm": (0, 10, 0)}])
    assert p["left_upper_arm"] == (0, 10, 0) and p["right_upper_arm"] == (0, -68, 0)


def test_resolve_hand_and_mirror_prefixes():
    assert P.resolve_pose("hand:fist:left") == P.hand_shape("fist", "left")
    assert P.resolve_pose("mirror:peace") == P.mirror(P.POSES["peace"])


def test_unknown_pose_lists_names():
    with pytest.raises(KeyError, match="idle"):
        P.resolve_pose("nope")


def test_dump_load_roundtrip(tmp_path):
    pose = P.POSES["thinking"]
    path = tmp_path / "t.toml"
    path.write_text(P.dump_pose(pose, "test pose"), encoding="utf-8")
    loaded = P.load_pose(path)
    assert loaded.keys() == pose.keys()
    for k, v in pose.items():
        if k.startswith(P.IK_PREFIX):
            assert loaded[k]["target"] == v["target"]
            assert loaded[k]["offset"] == pytest.approx(v["offset"])
        else:
            assert loaded[k] == pytest.approx(v)


def test_saved_poses_resolve_by_name(tmp_path):
    (tmp_path / "mine.toml").write_text(P.dump_pose({"head": (5, 0, 0)}), encoding="utf-8")
    assert "mine" in P.list_poses(tmp_path)
    assert P.resolve_pose("mine", tmp_path) == {"head": (5.0, 0.0, 0.0)}
