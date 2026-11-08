"""What a spec can contain, a strict checker, and a TOML writer (pure Python).

Used for text -> spec in chat: Claude reads ``catalog()``, writes a spec dict from a
description, runs ``check()`` until it's clean, previews it (``wogen variants``) and saves
it with ``save_spec()``. See docs/text-to-spec.md.

``body.from_spec`` is lenient (it clamps and ignores); ``check`` is strict and explains
problems instead, so mistakes surface while the spec is being written.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import body as body_mod
from . import spec as spec_mod
from .garments import CONFLICTS, validate_name
from .paths import ASSETS_DIR, REPO_ROOT

GARMENTS_DIR = ASSETS_DIR / "garments"
SPECS_DIR = REPO_ROOT / "specs"
BASE_DIR = ASSETS_DIR / "base"

TOP_KEYS = {"version", "seed", "base", "description", "body", "face", "colors", "hair", "outfit"}
COLOR_KEYS = ("hair", "eyes", "skin")
OUTFIT_KEYS = {"set", "add", "tint"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

BODY_HELP = {
    "head_scale": "head size (smaller = taller-looking, more mature)",
    "leg_length": "leg length (main height control)",
    "arm_length": "arm length",
    "torso_length": "torso length",
    "neck_length": "neck length",
    "shoulder_width": "shoulder width",
    "hip_width": "hip width",
    "waist": "waist width (lower = slimmer)",
    "thigh": "thigh thickness",
    "arm_thickness": "arm thickness",
    "bust": "bust size",
}
FACE_HELP = {
    "eye_size": "-1 small/mature .. +1 large/cute",
    "eye_height": "-1 lower .. +1 higher on the face",
    "face_width": "-1 narrow .. +1 wide/round",
    "chin_length": "-1 short/cute .. +1 long/mature",
    "brow_height": "-1 low/intense .. +1 high/open",
    "brow_tilt": "-1 soft/droopy (inner ends up) .. +1 sharp/angled (outer ends up)",
    "nose_size": "-1 tiny/button .. +1 larger",
    "mouth_width": "-1 small .. +1 wide",
}


def _index() -> dict:
    path = GARMENTS_DIR / "index.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {k: data.get(k, {}) for k in ("sets", "slots")}


def _library() -> set[str]:
    return {p.stem for p in GARMENTS_DIR.glob("*.blend")} if GARMENTS_DIR.is_dir() else set()


def catalog() -> dict[str, Any]:
    """Everything a spec can use, with ranges and the current asset library."""
    index, library = _index(), _library()
    slots = index["slots"]
    garments: dict[str, list[str]] = {}
    for name in sorted(library):
        slot = slots.get(name, "accessory")
        if slot != "hair":
            garments.setdefault(slot, []).append(name)
    return {
        "value_forms": {"fixed": 1.02, "range": [0.98, 1.06],
                        "choice": {"choice": ["a", "b"]}},
        "body": {k: {"range": list(v), "default": 1.0, "help": BODY_HELP.get(k, "")}
                 for k, v in body_mod.BODY_RANGES.items()},
        "face": {k: {"range": [-1.0, 1.0], "default": 0.0, "help": FACE_HELP.get(k, "")}
                 for k in body_mod.FACE_KEYS},
        "colors": {k: '"#RRGGBB"' for k in COLOR_KEYS}
        | {"note": "hair/eyes recolor the painted textures; keep skin near white (#f6e2d6..#ffffff)"},
        "hair_styles": sorted(n for n in library if slots.get(n) == "hair"),
        "outfit_sets": index["sets"],
        "garments_by_slot": garments,
        "slots": {s: sorted(c) for s, c in CONFLICTS.items()},
        "bases": sorted(p.stem for p in BASE_DIR.glob("*.vrm")
                        if "_" not in p.stem.removeprefix("base_")) if BASE_DIR.is_dir() else [],
        "adult_rule": f">= {body_mod.MIN_HEADS_TALL} heads tall; head_scale is reduced if needed",
    }


# ---------------------------------------------------------------- checking

def _values(value: Any) -> list[Any]:
    """Every concrete value a spec value can resolve to (ranges -> both bounds)."""
    if spec_mod._is_range(value):
        return list(value)
    if isinstance(value, dict) and set(value) == {"choice"}:
        out = []
        for v in value["choice"] if isinstance(value["choice"], list) else []:
            out += _values(v)
        return out
    return [value]


def _check_number(path: str, value: Any, lo: float, hi: float, errors: list[str]) -> None:
    if spec_mod._is_range(value) and value[0] > value[1]:
        errors.append(f"{path}: range min > max {value}")
    for v in _values(value):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            errors.append(f"{path}: expected a number, range or choice, got {v!r}")
        elif not lo <= v <= hi:
            errors.append(f"{path}: {v} is outside {lo}..{hi}")


def _check_names(path: str, value: Any, allowed: set[str], what: str, errors: list[str]) -> None:
    for v in _values(value):
        if not isinstance(v, str) or v not in allowed:
            errors.append(f"{path}: unknown {what} {v!r} (have: {', '.join(sorted(allowed))})")


def check(spec: dict[str, Any], seeds: range = range(20)) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a spec dict. No errors = safe to generate."""
    errors: list[str] = []
    warnings: list[str] = []
    cat = catalog()
    library, slots = _library(), _index()["slots"]
    for key in sorted(set(spec) - TOP_KEYS):
        errors.append(f"unknown key {key!r} (allowed: {', '.join(sorted(TOP_KEYS))})")
    if spec.get("version", spec_mod.SPEC_VERSION) != spec_mod.SPEC_VERSION:
        errors.append(f"version must be {spec_mod.SPEC_VERSION}")
    if "base" in spec and cat["bases"]:
        _check_names("base", spec["base"], set(cat["bases"]), "base", errors)

    for section, allowed in (("body", body_mod.BODY_RANGES), ("face", None)):
        table = spec.get(section, {})
        if not isinstance(table, dict):
            errors.append(f"[{section}] must be a table")
            continue
        for k, v in table.items():
            if section == "body" and k in allowed:
                _check_number(f"body.{k}", v, *allowed[k], errors)
            elif section == "face" and k in body_mod.FACE_KEYS:
                _check_number(f"face.{k}", v, -1.0, 1.0, errors)
            else:
                names = body_mod.BODY_RANGES if section == "body" else body_mod.FACE_KEYS
                errors.append(f"{section}.{k}: unknown (allowed: {', '.join(names)})")

    for k, v in spec.get("colors", {}).items():
        if k not in COLOR_KEYS:
            errors.append(f"colors.{k}: unknown (allowed: {', '.join(COLOR_KEYS)})")
            continue
        for c in _values(v):
            if not isinstance(c, str) or not HEX.match(c):
                errors.append(f"colors.{k}: {c!r} is not \"#RRGGBB\"")
            elif k == "skin" and min(int(c[i:i + 2], 16) for i in (1, 3, 5)) < 0xC8:
                warnings.append(f"colors.skin {c}: dark tints look muddy; keep each channel >= c8")

    hair = spec.get("hair")
    if hair is not None:
        style = hair if isinstance(hair, str) else hair.get("style") if isinstance(hair, dict) else None
        if isinstance(hair, dict) and set(hair) - {"style"}:
            errors.append(f"[hair]: unknown keys {sorted(set(hair) - {'style'})} (allowed: style)")
        if style is not None:
            _check_names("hair.style", style, set(cat["hair_styles"]), "hairstyle", errors)

    outfit = spec.get("outfit")
    if isinstance(outfit, str):
        outfit = {"set": outfit}
    if outfit is not None:
        for k in sorted(set(outfit) - OUTFIT_KEYS):
            errors.append(f"outfit.{k}: unknown (allowed: {', '.join(sorted(OUTFIT_KEYS))})")
        if "set" in outfit:
            _check_names("outfit.set", outfit["set"], set(cat["outfit_sets"]), "outfit set", errors)
        garments = library - {n for n in library if slots.get(n) == "hair"}
        add = outfit.get("add", [])
        for g in add if isinstance(add, list) else [add]:
            _check_names("outfit.add", g, garments, "garment", errors)
        for target, color in outfit.get("tint", {}).items():
            name, _, layer = target.partition(":")
            if name not in library:
                errors.append(f"outfit.tint: unknown garment {name!r}")
            for c in _values(color):
                if not isinstance(c, str) or not HEX.match(c):
                    errors.append(f"outfit.tint.{target}: {c!r} is not \"#RRGGBB\"")
            if layer:
                warnings.append(f"outfit.tint.{target}: layer names aren't checked here; "
                                "use outfit.list_layers() in Blender if unsure")
        worn = _values(outfit.get("set")) if "set" in outfit else []
        sets = cat["outfit_sets"]
        for g in add if isinstance(add, list) else [add]:
            if isinstance(g, str) and slots.get(g) not in (None, "accessory"):
                for s in worn:
                    clash = [m for m in sets.get(s, []) if slots.get(m) in CONFLICTS[slots[g]]]
                    if clash:
                        warnings.append(f"outfit.add {g!r} ({slots[g]}) layers with {clash} from "
                                        f"set {s!r}; both are worn")

    if not errors:
        adjusted = 0
        for seed in seeds:
            try:
                params = body_mod.from_spec(spec_mod.resolve(spec, seed))
            except (ValueError, TypeError) as e:
                errors.append(f"resolve failed: {e}")
                break
            adjusted += any("adult proportions" in n for n in params.notes)
        if adjusted:
            warnings.append(f"adult rule reduces head_scale for {adjusted}/{len(seeds)} seeds "
                            "(fine; lower head_scale or raise leg_length to avoid it)")
    return errors, warnings


# ---------------------------------------------------------------- TOML writing

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(k: str) -> str:
    return k if _BARE_KEY.match(k) else json.dumps(k)


def _value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(x)}" for k, x in v.items()) + " }"
    raise TypeError(f"Can't write {type(v).__name__} to TOML: {v!r}")


SECTION_ORDER = ("body", "face", "colors", "hair", "outfit")


def to_toml(spec: dict[str, Any]) -> str:
    """Serialize a spec dict (scalars first, then one table per section)."""
    lines = []
    tables = [k for k in SECTION_ORDER if isinstance(spec.get(k), dict)]
    tables += [k for k, v in spec.items() if isinstance(v, dict) and k not in tables]
    scalars = {"version": spec.get("version", spec_mod.SPEC_VERSION)}
    scalars |= {k: v for k, v in spec.items() if k not in tables and k != "version"}
    lines += [f"{_key(k)} = {_value(v)}" for k, v in scalars.items()]
    for t in tables:
        lines += ["", f"[{t}]"] + [f"{_key(k)} = {_value(v)}" for k, v in spec[t].items()]
    return "\n".join(lines) + "\n"


def save_spec(spec: dict[str, Any], name: str, overwrite: bool = False) -> Path:
    """Check, then write ``specs/<name>.toml``. Raises on errors or an existing file."""
    validate_name(name)
    errors, _ = check(spec)
    if errors:
        raise ValueError("spec has errors:\n  " + "\n  ".join(errors))
    path = SPECS_DIR / f"{name}.toml"
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} exists (pass overwrite=True)")
    path.write_text(to_toml(spec), encoding="utf-8")
    return path
