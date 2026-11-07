import pytest

from wogen import garments as G


@pytest.mark.parametrize("name, expected", [
    ("N00_010_01_Onepiece_00_CLOTH_02", "N00_010_01_Onepiece_00"),
    ("N00_008_01_Shoes_01_CLOTH_01", "N00_008_01_Shoes_01"),
    ("wg_N00_008_01_Shoes_01_CLOTH_01.001", "N00_008_01_Shoes_01"),   # toon twin + dup suffix
    ("wgo_N00_010_01_Onepiece_00_CLOTH_04", "N00_010_01_Onepiece_00"),
    ("N00_000_00_Body_00_SKIN", None),
    ("N00_000_00_FaceBrow_00_FACE", None),
    ("N00_000_Hair_00_HAIR_01", None),                                # hair doesn't match
    ("Material", None),
])
def test_garment_key(name, expected):
    assert G.garment_key(name) == expected


def test_strip_suffix():
    assert G.strip_suffix("wgx_N00_000_00_FaceBrow_00_FACE.012") == "N00_000_00_FaceBrow_00_FACE"


def test_slots_and_display_names():
    assert G.slot_for("N00_010_01_Onepiece_00") == "full"
    assert G.slot_for("N00_008_01_Shoes_01") == "shoes"
    assert G.slot_for("N00_099_01_Mystery_00") == "accessory"
    assert G.display_name("N00_010_01_Onepiece_00") == "onepiece_010_01"


REF = {"J_Bip_C_Hips": (0.0, 0.0, 0.90), "J_Bip_C_Head": (0.0, 0.01, 1.36),
       "J_Bip_L_Foot": (0.08, 0.0, 0.10)}


def test_skeleton_vertical_shift_is_accepted():
    lifted = {n: (x, y, z + 0.0139) for n, (x, y, z) in REF.items()}   # heels
    dz, reason = G.skeleton_mismatch(REF, lifted)
    assert reason is None and dz == pytest.approx(0.0139)


def test_skeleton_proportion_change_is_rejected():
    taller = dict(REF, J_Bip_C_Head=(0.0, 0.01, 1.40))
    dz, reason = G.skeleton_mismatch(REF, taller)
    assert dz == pytest.approx(0.0) and "J_Bip_C_Head" in reason


def test_skeleton_bone_set_difference_is_rejected():
    _, reason = G.skeleton_mismatch(REF, {**REF, "J_Bip_C_Neck": (0, 0, 1.3)})
    assert "bone sets differ" in reason


@pytest.mark.parametrize("name, ok", [("skirt_plaid", True), ("dress2", True),
                                      ("Skirt", False), ("a b", False), ("_x", False), ("", False)])
def test_validate_name(name, ok):
    if ok:
        assert G.validate_name(name) == name
    else:
        with pytest.raises(ValueError):
            G.validate_name(name)


def test_outer_slot_layers_over_top():
    assert G.CONFLICTS["outer"] == {"outer"} and "outer" not in G.CONFLICTS["top"]


def test_only_same_slot_conflicts():
    for slot, conflicts in G.CONFLICTS.items():
        assert conflicts <= {slot}, slot
    assert G.CONFLICTS["accessory"] == set()
