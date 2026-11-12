import pytest

from wogen import mmd


def _skeleton(extra_torso=("上半身2",)):
    """A small MMD semi-standard skeleton, as {bone: parent}."""
    bones = {"全ての親": None, "センター": "全ての親", "グルーブ": "センター", "腰": "グルーブ",
             "下半身": "腰", "上半身": "腰"}
    parent = "上半身"
    for b in extra_torso:
        bones[b] = parent
        parent = b
    bones.update({"首": parent, "頭": "首"})
    for s in ("L", "R"):
        bones.update({f"肩.{s}": parent, f"腕.{s}": f"肩.{s}", f"ひじ.{s}": f"腕.{s}",
                      f"手首.{s}": f"ひじ.{s}", f"足.{s}": "下半身", f"ひざ.{s}": f"足.{s}",
                      f"足首.{s}": f"ひざ.{s}", f"足D.{s}": "下半身", f"目.{s}": "頭",
                      f"人指１.{s}": f"手首.{s}"})
    return bones


def test_maps_the_semi_standard_skeleton():
    hmap = mmd.humanoid_map(_skeleton())
    assert hmap["hips"] == "腰" and hmap["head"] == "頭" and hmap["neck"] == "首"
    assert hmap["spine"] == "上半身" and hmap["chest"] == "上半身2" and "upper_chest" not in hmap
    assert hmap["left_upper_leg"] == "足.L"            # the FK controller, not the D-bone
    assert hmap["right_hand"] == "手首.R" and hmap["left_eye"] == "目.L"
    assert hmap["left_index_proximal"] == "人指１.L"
    assert mmd.is_character(_skeleton())


def test_torso_chain_length_varies():
    hmap = mmd.humanoid_map(_skeleton(("上半身1", "上半身2")))
    assert (hmap["spine"], hmap["chest"], hmap["upper_chest"]) == ("上半身", "上半身1", "上半身2")
    hmap = mmd.humanoid_map(_skeleton(()))
    assert hmap["spine"] == "上半身" and "chest" not in hmap


def test_hips_fall_back_when_there_is_no_waist_bone():
    bones = _skeleton()
    bones["下半身"] = bones["上半身"] = "グルーブ"
    del bones["腰"]
    assert mmd.humanoid_map(bones)["hips"] == "グルーブ"


def test_props_are_not_characters(tmp_path):
    assert not mmd.is_character({"全ての親": None, "武器": "全ての親"})
    for rel in ("a/角色.pmx", "a/武器.pmx", "b/武器2.pmx", "b/other.pmx"):
        (tmp_path / rel).parent.mkdir(exist_ok=True)
        (tmp_path / rel).write_bytes(b"")
    assert [p.name for p in mmd.list_models(tmp_path)] == ["角色.pmx", "other.pmx"]


def test_every_preset_key_has_morphs():
    from wogen.expressions import PRESETS
    used = {k for p in PRESETS.values() for k in p} - {"Fcl_MTH_Close"}
    assert used <= set(mmd.FCL_MORPHS)


def test_morph_weights_pick_available_candidates():
    have = {"まばたき", "あ１", "口角上げ", "にこり", "笑い", "下眼上"}
    w = mmd.morph_weights({"Fcl_MTH_A": 0.5, "Fcl_EYE_Close": 1.0}, have)
    assert w == {"あ１": 0.5, "まばたき": 1.0}
    # Full-face keys expand into parts; missing parts (びっくり etc.) are dropped; sums clamp.
    w = mmd.morph_weights({"Fcl_ALL_Joy": 1.0, "Fcl_EYE_Fun": 2.0}, have)
    assert w["にこり"] == 1.0 and w["笑い"] == 1.0 and w["下眼上"] == 1.0
    assert w["口角上げ"] == 0.8 and "ワ" not in w
    assert mmd.morph_weights({"Fcl_MTH_Close": 1.0}, have) == {}


def test_follow_map_links_d_bones_to_their_fk_bones():
    bones = {"足.L": None, "足D.L": None, "ひざ.L": None, "ひざD.L": None, "足首.R": None,
             "足首D.R": None, "足首D.L": None}
    assert mmd.follow_map(bones) == {"足D.L": "足.L", "ひざD.L": "ひざ.L", "足首D.R": "足首.R"}


def test_find_model_by_name_or_folder(tmp_path):
    for rel in ("111/角色.pmx", "111/角色_白.pmx", "222/角色.pmx", "333/其他.pmx"):
        (tmp_path / rel).parent.mkdir(exist_ok=True)
        (tmp_path / rel).write_bytes(b"")
    assert mmd.find_model("其他", tmp_path).name == "其他.pmx"
    assert mmd.find_model("角色_白", tmp_path).name == "角色_白.pmx"
    assert mmd.model_label(mmd.find_model("222/角色", tmp_path), tmp_path) == "222/角色"
    with pytest.raises(ValueError, match="several"):
        mmd.find_model("角色", tmp_path)            # exact name in two folders
    with pytest.raises(ValueError, match="No imported"):
        mmd.find_model("nobody", tmp_path)


def test_find_model_by_english_name(tmp_path):
    for rel in ("a/伊德海莉.pmx", "b/蕾米埃尔·黑.pmx", "b/蕾米埃尔·黑带大翅膀.pmx"):
        (tmp_path / rel).parent.mkdir(exist_ok=True)
        (tmp_path / rel).write_bytes(b"")
    assert mmd.find_model("yidhari", tmp_path).stem == "伊德海莉"
    assert mmd.find_model("Remielle_black", tmp_path).stem == "蕾米埃尔·黑"      # exact wins
    assert mmd.english_label(mmd.find_model("big_wings", tmp_path), tmp_path) == \
        "b/Remielle_black_with_big_wings"


def test_bust_bones_picks_the_skinned_driven_bone_per_side():
    bones = {"上半身2": None, "おっぱい調整": "上半身2", "胸上.L": "おっぱい調整",
             "胸上2.L": "上半身2", "胸先.L": "胸上2.L", "胸上2.R": "上半身2",
             "胸リボン": "上半身2"}
    driven = {"胸上.L", "胸上2.L", "胸上2.R", "胸リボン"}
    weights = {"胸上2.L": 400.0, "胸上2.R": 380.0, "胸リボン": 50.0}
    assert mmd.bust_bones(bones, {}, driven, weights) == ["胸上2.L", "胸上2.R"]


def test_bust_bones_counts_children_and_prefers_the_root_on_ties():
    bones = {"上半身2": None, "胸上.L": "上半身2", "胸.L": "胸上.L", "胸補助1.L": "胸.L"}
    driven = {"胸上.L", "胸.L"}
    assert mmd.bust_bones(bones, {}, driven, {"胸補助1.L": 300.0}) == ["胸上.L"]
    # translated names: the original decides
    english = {"bust_upper.L": "胸上.L", "bust.L": "胸.L", "assist.L": "胸補助1.L", "ub2": "上半身2"}
    tb = {"ub2": None, "bust_upper.L": "ub2", "bust.L": "bust_upper.L", "assist.L": "bust.L"}
    assert mmd.bust_bones(tb, english, {"bust_upper.L"}, {"assist.L": 1.0}) == ["bust_upper.L"]
