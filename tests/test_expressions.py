import pytest

from wogen.expressions import PRESETS, list_expressions, resolve_weights


def test_preset_resolves_to_its_keys():
    assert resolve_weights("happy") == {"Fcl_ALL_Joy": 1.0}


def test_weight_scales_preset():
    assert resolve_weights("happy", 0.5) == {"Fcl_ALL_Joy": 0.5}


def test_mix_presets_and_raw_keys_sum_and_clamp():
    w = resolve_weights({"blink": 0.7, "Fcl_EYE_Close": 0.7, "aa": 0.4})
    assert w == {"Fcl_EYE_Close": 1.0, "Fcl_MTH_A": 0.4}


def test_neutral_is_empty():
    assert resolve_weights("neutral") == {}


def test_unknown_name_lists_presets():
    with pytest.raises(KeyError, match="happy"):
        resolve_weights("not_a_preset")


def test_all_presets_use_vroid_face_keys_in_range():
    for name in list_expressions():
        for key, value in PRESETS[name].items():
            assert key.startswith("Fcl_"), (name, key)
            assert 0.0 < value <= 1.0, (name, key, value)
