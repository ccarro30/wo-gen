import struct

from wogen import mmd_names as N


def test_bones_translate_term_by_term_keeping_sides_numbers_and_markers():
    assert N.translate("足首D.L") == "ankle_D.L"
    assert N.translate("腕捩１.R") == "arm_twist_1.R"            # full-width digit
    assert N.translate("ひじ補助.L") == "elbow_assist.L"
    assert N.translate("Skn_L_FootRing_02錘") == "Skn_L_FootRing_02_weight"
    assert N.translate("_shadow_腕補助.R") == "_shadow_arm_assist.R"
    assert N.translate("足ＩＫ.L") == "leg_IK.L"
    assert N.translate("J_Bip_C_Hips") == "J_Bip_C_Hips"          # English stays
    assert N.translate("未知") == "未知"                            # unknown stays


def test_morphs_translate_whole_names_with_sides():
    assert N.translate_morph("まばたき") == "blink"
    assert N.translate_morph("ウィンク") == "wink_smile_L"
    assert N.translate_morph("ウィンク右") == "wink_smile_R"
    assert N.translate_morph("ウィンク２右") == "wink_R"
    assert N.translate_morph("口角上げ左") == "mouth_corners_up_L"
    assert N.translate_morph("あ１") == "mouth_a_1"
    assert N.translate_morph("ｷﾘｯ") == "eyes_determined"           # half-width katakana


def test_models_and_materials():
    assert N.translate_model("蕾米埃尔·黑带大翅膀") == "Remielle_black_with_big_wings"
    assert N.translate_model("卢西娅_摘帽") == "Lucia_hat_off"
    assert N.translate("贴身衣物", N.MATERIAL_TERMS) == "underwear"


def test_unique_names_never_collide():
    names = ["錘", "锤", "weight", "髪"]                            # 錘 and 锤 both mean weight
    out = N.unique_names(names, N.translate)
    assert set(out) == {"錘", "锤", "髪"}
    assert len(set(out.values()) | {"weight"}) == 4


def test_pmx_header(tmp_path):
    def text(s):
        b = s.encode("utf-16-le")
        return struct.pack("<i", len(b)) + b
    data = (b"PMX " + struct.pack("<f", 2.0) + bytes([8, 0, 1, 4, 4, 4, 4, 4, 4])
            + text("伊德海莉") + text("Yidhari") + text("说明") + text("terms"))
    (tmp_path / "m.pmx").write_bytes(data)
    assert N.pmx_header(tmp_path / "m.pmx") == {"name": "伊德海莉", "name_en": "Yidhari",
                                                "comment": "说明", "comment_en": "terms"}
