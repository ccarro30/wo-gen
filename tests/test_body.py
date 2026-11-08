import pytest

from wogen import body as B
from wogen import spec as S


def test_base_proportions_are_seven_heads():
    assert B.heads_tall(B.BodyParams()) == pytest.approx(7.0)


def test_longer_legs_add_heads_bigger_head_removes():
    assert B.heads_tall(B.BodyParams(leg_length=1.08)) > 7.0
    assert B.heads_tall(B.BodyParams(head_scale=1.05)) < 7.0


def test_values_are_clamped_to_ranges():
    p = B.validate(B.CharacterParams(body=B.BodyParams(bust=3.0, waist=0.1)))
    assert p.body.bust == B.BODY_RANGES["bust"][1]
    assert p.body.waist == B.BODY_RANGES["waist"][0]
    assert any("bust" in n for n in p.notes)


def test_adult_rule_shrinks_head_when_needed():
    childlike = B.BodyParams(head_scale=1.06, leg_length=0.94, torso_length=0.94, neck_length=0.90)
    assert B.heads_tall(childlike) < B.MIN_HEADS_TALL
    p = B.validate(B.CharacterParams(body=childlike))
    assert B.heads_tall(p.body) >= B.MIN_HEADS_TALL - 1e-6
    assert p.body.head_scale < 1.06
    assert any("adult proportions" in n for n in p.notes)


@pytest.mark.parametrize("seed", range(40))
def test_every_default_spec_seed_is_adult(seed):
    from wogen.paths import REPO_ROOT
    raw = S.load_spec(REPO_ROOT / "specs" / "default.toml")
    p = B.from_spec(S.resolve(raw, seed))
    assert B.heads_tall(p.body) >= B.MIN_HEADS_TALL - 1e-6
    for name, (lo, hi) in B.BODY_RANGES.items():
        assert lo <= getattr(p.body, name) <= hi


def test_from_spec_maps_sections_and_flags_unknown_keys():
    p = B.from_spec({"body": {"bust": 1.1, "wingspan": 2}, "face": {"eye_size": 0.5},
                     "colors": {"hair": "#ffffff"},
                     "outfit": {"set": "school", "add": ["bow_pink"],
                                "tint": {"skirt_plaid": "#223344", "blouse_white:CLOTH_01": "#c03050"}}})
    assert p.body.bust == 1.1 and p.face.eye_size == 0.5 and p.palette.hair == "#ffffff"
    assert p.outfit == "school" and p.garment_add == ["bow_pink"]
    assert p.garment_tints == {"skirt_plaid": "#223344", "blouse_white:CLOTH_01": "#c03050"}
    assert any("wingspan" in n for n in p.notes)


def test_from_spec_hair_style_table_or_string():
    assert B.from_spec({"hair": {"style": "hair_twintails"}}).hair == "hair_twintails"
    assert B.from_spec({"hair": "hair_bob"}).hair == "hair_bob"
    assert B.from_spec({}).hair is None


@pytest.mark.parametrize("seed", range(10))
def test_default_spec_picks_a_hairstyle(seed):
    from wogen.paths import REPO_ROOT
    p = B.from_spec(S.resolve(S.load_spec(REPO_ROOT / "specs" / "default.toml"), seed))
    assert p.hair and p.hair.startswith("hair_")
