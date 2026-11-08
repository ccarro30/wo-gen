import pytest

from wogen import spec as s

SPEC = {
    "version": 1,
    "seed": 7,
    "body": {"height_cm": [158, 168], "waist": [0.4, 0.6], "build": "slim"},
    "hair": {"style": {"choice": ["twin_tails", "bob", "long_straight"]}},
    "outfit": ["crop_top", "shorts"],
}


def test_resolve_is_deterministic():
    assert s.resolve(SPEC, 42) == s.resolve(SPEC, 42)


def test_different_seeds_differ():
    results = {s.to_json(s.resolve(SPEC, seed)) for seed in range(10)}
    assert len(results) > 1


def test_ranges_and_choices_resolve_within_bounds():
    for seed in range(50):
        r = s.resolve(SPEC, seed)
        assert isinstance(r["body"]["height_cm"], int)
        assert 158 <= r["body"]["height_cm"] <= 168
        assert 0.4 <= r["body"]["waist"] <= 0.6
        assert r["hair"]["style"] in {"twin_tails", "bob", "long_straight"}
        assert r["body"]["build"] == "slim"
        assert r["outfit"] == ["crop_top", "shorts"]


def test_seed_defaults_to_spec_seed():
    assert s.resolve(SPEC) == s.resolve(SPEC, 7)


def test_invalid_range_rejected():
    with pytest.raises(ValueError):
        s.resolve({"x": [5, 1]}, 0)


def test_load_spec_roundtrip(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('version = 1\nseed = 3\n[body]\nheight_cm = [158, 168]\n', encoding="utf-8")
    r = s.resolve(s.load_spec(p))
    assert r["seed"] == 3 and 158 <= r["body"]["height_cm"] <= 168


def test_adding_keys_keeps_other_values():
    base = {"face": {"eye_size": [-1.0, 1.0]}, "colors": {"hair": {"choice": ["a", "b", "c", "d"]}}}
    more = {"face": {"brow_tilt": [-1.0, 1.0], "eye_size": [-1.0, 1.0]},
            "body": {"bust": [0.8, 1.3]}, "colors": {"hair": {"choice": ["a", "b", "c", "d"]}}}
    for seed in range(20):
        a, b = s.resolve(base, seed), s.resolve(more, seed)
        assert a["face"]["eye_size"] == b["face"]["eye_size"]
        assert a["colors"]["hair"] == b["colors"]["hair"]
