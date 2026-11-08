"""Seeded character generation: spec (TOML/dict) + seed -> styled, dressed character.

Chat usage::

    from wogen.bl import generate
    params = generate.generate("specs/default.toml", seed=7)
    params.notes                      # any clamping applied (e.g. adult-proportion rule)
    generate.set_palette(hair="#f4b6c2", eyes="#5ab0ff")
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from .. import body as body_params
from .. import spec as spec_mod
from ..paths import REPO_ROOT

GENERATED_KEY = "wg_generated"


def _hex(value):
    from .toon import hex_to_srgb
    return list(hex_to_srgb(value)) if value else None


def set_palette(hair: str | None = None, eyes: str | None = None, skin: str | None = None) -> str:
    """Recolor hair (colorize), brows (darker hair colour), irises (colorize), skin (tint)."""
    from . import toon
    from .character import character_meshes
    hair_rgb, eye_rgb, skin_rgb = _hex(hair), _hex(eyes), _hex(skin)
    changed = []
    for obj in character_meshes():
        names = [toon._source_of(m).name for m in obj.data.materials if m and toon._source_of(m)]
        rules = json.loads(obj["wg_recolor"]) if obj.get("wg_recolor") else {}
        if hair_rgb and any("_HAIR" in n for n in names):
            rules["_HAIR"] = {"colorize": hair_rgb}
        if obj.name == "Face":
            if hair_rgb:
                rules["FaceBrow"] = {"colorize": [c * 0.75 for c in hair_rgb]}
            if eye_rgb:
                rules["EyeIris"] = {"colorize": eye_rgb}
        if skin_rgb and any(n.endswith("_SKIN") or "_SKIN." in n for n in names):
            rules["_SKIN"] = {"tint": skin_rgb}
        if rules:
            obj["wg_recolor"] = json.dumps(rules)   # longest matching key wins (toon.material_recolor)
            changed.append(obj)
    if changed:
        toon.apply_toon(changed)
    return f"palette hair={hair} eyes={eyes} skin={skin} ({len(changed)} meshes)"


def load(spec) -> dict:
    if isinstance(spec, dict):
        return spec
    path = Path(spec)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return spec_mod.load_spec(path)


def generate(spec="specs/default.toml", seed: int | None = None, base: str | None = None,
             through_hair=("brow",)) -> body_params.CharacterParams:
    """Build a character from ``spec`` + ``seed`` into the scene (replacing any previous one)."""
    from . import body, character, outfit, overlay, toon
    raw = load(spec)
    resolved = spec_mod.resolve(raw, seed)
    params = body_params.from_spec(resolved)
    base = base or resolved.get("base", "base_f01")
    character.ensure_vrm_addon()
    character.clear_default_scene()
    with contextlib.redirect_stdout(io.StringIO()):
        character.import_base(base)
    params.notes.append(body.apply_body(params.body))
    toon.apply_toon()
    if through_hair:
        overlay.features_through_hair(list(through_hair))
    params.notes.append(body.apply_face(params.face))
    outfit.split()
    if params.outfit:
        outfit.equip_set(params.outfit)
    for garment in params.garment_add:
        try:
            outfit.equip(garment, exclusive=False)
        except FileNotFoundError:
            params.notes.append(f"add skipped: no garment {garment}")
    for target, color in params.garment_tints.items():
        garment, _, layer = target.partition(":")
        try:
            outfit.recolor(garment, tint=color, layer=layer or None)
        except KeyError as e:
            params.notes.append(f"tint skipped: {e}")
    if params.hair:
        from . import hair
        try:
            hair.equip(params.hair)
        except KeyError as e:
            params.notes.append(f"hair skipped: {e}")
    p = params.palette
    if p.hair or p.eyes or p.skin:
        set_palette(p.hair, p.eyes, p.skin)
    arm = character.character_armature()
    arm[GENERATED_KEY] = json.dumps({"seed": resolved["seed"], "resolved": resolved,
                                     "params": params.to_dict()}, default=str)
    return params


def describe() -> dict:
    """The resolved spec / parameters of the character currently in the scene."""
    from .character import character_armature
    arm = character_armature()
    return json.loads(arm[GENERATED_KEY]) if arm and arm.get(GENERATED_KEY) else {}
