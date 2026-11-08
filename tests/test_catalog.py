import tomllib

import pytest

from wogen import catalog as C
from wogen import spec as S
from wogen.paths import REPO_ROOT

GOOD = {
    "description": "tall, cool, long black hair, red dress",
    "seed": 3,
    "body": {"leg_length": [1.04, 1.08], "head_scale": 0.96, "waist": 0.92},
    "face": {"eye_size": [-0.3, 0.0], "chin_length": 0.3},
    "colors": {"hair": "#1d1b26", "eyes": {"choice": ["#c0392b", "#8a5a3c"]}, "skin": "#fff4ee"},
    "hair": {"style": "hair_long_straight"},
    "outfit": {"set": "red_dress", "tint": {"dress_red": "#7a1f3d"}},
}


def test_catalog_lists_library():
    cat = C.catalog()
    assert "hair_twintails" in cat["hair_styles"] and len(cat["hair_styles"]) >= 8
    assert "school" in cat["outfit_sets"] and "skirt_plaid" in cat["garments_by_slot"]["bottom"]
    assert not any(n.startswith("hair_") for g in cat["garments_by_slot"].values() for n in g)
    assert cat["body"]["bust"]["range"] == [0.8, 1.3] and cat["bases"] == ["base_f01"]


@pytest.mark.parametrize("name", ["default", "school_navy"])
def test_shipped_specs_are_clean(name):
    errors, _ = C.check(S.load_spec(REPO_ROOT / "specs" / f"{name}.toml"))
    assert errors == []


def test_good_spec_is_clean():
    assert C.check(GOOD)[0] == []


@pytest.mark.parametrize("patch, fragment", [
    ({"mood": "shy"}, "unknown key 'mood'"),
    ({"body": {"height": 1.1}}, "body.height: unknown"),
    ({"body": {"bust": 1.6}}, "outside 0.8..1.3"),
    ({"body": {"leg_length": [1.08, 1.0]}}, "min > max"),
    ({"face": {"eye_size": {"choice": [0.2, 2]}}}, "outside -1.0..1.0"),
    ({"colors": {"hair": "pink"}}, "not \"#RRGGBB\""),
    ({"hair": {"style": "hair_mohawk"}}, "unknown hairstyle 'hair_mohawk'"),
    ({"hair": {"style": {"choice": ["hair_bob", "hair_afro"]}}}, "hair_afro"),
    ({"outfit": {"set": "swimsuit"}}, "unknown outfit set 'swimsuit'"),
    ({"outfit": {"add": ["hair_bob"]}}, "unknown garment 'hair_bob'"),
    ({"outfit": {"tint": {"cape_blue": "#123456"}}}, "unknown garment 'cape_blue'"),
])
def test_check_reports_problems(patch, fragment):
    errors, _ = C.check({**GOOD, **patch})
    assert any(fragment in e for e in errors), errors


def test_check_warns_on_same_slot_layering_and_adult_rule():
    _, warnings = C.check({**GOOD, "body": {"head_scale": 1.06, "leg_length": 0.94},
                           "outfit": {"set": "school", "add": ["skirt_pink_floral"]}})
    assert any("adult rule" in w for w in warnings)
    assert any("skirt_pink_floral" in w and "skirt_plaid" in w for w in warnings)


def test_toml_round_trip():
    text = C.to_toml(GOOD)
    assert tomllib.loads(text) == {**GOOD, "version": 1}
    assert S.resolve(tomllib.loads(text), 3) == S.resolve({**GOOD, "version": 1}, 3)


def test_save_spec(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "SPECS_DIR", tmp_path)
    path = C.save_spec(GOOD, "tall_red")
    assert tomllib.loads(path.read_text(encoding="utf-8"))["hair"] == {"style": "hair_long_straight"}
    with pytest.raises(FileExistsError):
        C.save_spec(GOOD, "tall_red")
    with pytest.raises(ValueError, match="unknown hairstyle"):
        C.save_spec({**GOOD, "hair": "hair_mohawk"}, "bad", overwrite=True)
