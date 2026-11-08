"""Body / face / color parameters (pure Python; applied by ``wogen.bl.body``).

All body values are multipliers around 1.0 relative to the base model; face values are
shape-key weights in -1..1. Every value is clamped to its range, and the combination is
checked against the adult-proportion rule (``MIN_HEADS_TALL``): if the estimate falls short,
``head_scale`` is reduced until it complies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

MIN_HEADS_TALL = 6.6        # base_f01 is 7.0 heads tall
BASE_HEADS_TALL = 7.0

# name -> (min, max). Ranges are deliberately moderate: stylized but plausible adults.
BODY_RANGES: dict[str, tuple[float, float]] = {
    "head_scale": (0.92, 1.06),
    "leg_length": (0.94, 1.10),
    "arm_length": (0.95, 1.05),
    "torso_length": (0.94, 1.06),
    "neck_length": (0.90, 1.15),
    "shoulder_width": (0.94, 1.08),
    "hip_width": (0.92, 1.10),
    "waist": (0.88, 1.08),
    "thigh": (0.90, 1.12),
    "arm_thickness": (0.90, 1.10),
    "bust": (0.80, 1.30),
}
FACE_KEYS = ("eye_size", "eye_height", "face_width", "chin_length")

# Height fractions of the base model (used by the heads-tall estimate).
_FRACTIONS = {"leg_length": 0.48, "torso_length": 0.30, "neck_length": 0.05, "head_scale": 0.14}
_OTHER = 1.0 - sum(_FRACTIONS.values())     # feet, pelvis


@dataclass
class BodyParams:
    head_scale: float = 1.0
    leg_length: float = 1.0
    arm_length: float = 1.0
    torso_length: float = 1.0
    neck_length: float = 1.0
    shoulder_width: float = 1.0
    hip_width: float = 1.0
    waist: float = 1.0
    thigh: float = 1.0
    arm_thickness: float = 1.0
    bust: float = 1.0

    def is_identity(self) -> bool:
        return all(abs(getattr(self, f.name) - 1.0) < 1e-6 for f in fields(self))


@dataclass
class FaceParams:
    eye_size: float = 0.0
    eye_height: float = 0.0
    face_width: float = 0.0
    chin_length: float = 0.0


@dataclass
class Palette:
    hair: str | None = None      # "#RRGGBB" target (colorize: keeps the painted shading)
    eyes: str | None = None
    skin: str | None = None      # gentle tint multiply


@dataclass
class CharacterParams:
    body: BodyParams = field(default_factory=BodyParams)
    face: FaceParams = field(default_factory=FaceParams)
    palette: Palette = field(default_factory=Palette)
    outfit: str | None = None                       # outfit set name
    hair: str | None = None                         # hairstyle (library, slot "hair")
    garment_add: list[str] = field(default_factory=list)       # extra garments
    garment_tints: dict[str, str] = field(default_factory=dict)  # "name" or "name:LAYER" -> hex
    notes: list[str] = field(default_factory=list)  # adjustments made while validating

    def to_dict(self) -> dict:
        return asdict(self)


def _height_ratio(body: BodyParams) -> float:
    """Height relative to the base model (each body segment scales its share of height)."""
    return _OTHER + sum(frac * getattr(body, name) for name, frac in _FRACTIONS.items())


def heads_tall(body: BodyParams) -> float:
    """Estimated height in head-heights: base heads x height ratio / head scale."""
    return BASE_HEADS_TALL * _height_ratio(body) / body.head_scale


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def validate(params: CharacterParams) -> CharacterParams:
    """Clamp every value to its range and enforce ``MIN_HEADS_TALL`` (mutates and returns)."""
    b = params.body
    for name, (lo, hi) in BODY_RANGES.items():
        v = getattr(b, name)
        c = _clamp(v, lo, hi)
        if c != v:
            params.notes.append(f"{name} {v:.3f} clamped to {c:.3f}")
        setattr(b, name, c)
    for name in FACE_KEYS:
        setattr(params.face, name, _clamp(getattr(params.face, name), -1.0, 1.0))
    ht = heads_tall(b)
    if ht < MIN_HEADS_TALL:
        # heads = BASE * (H0 + f_head * hs) / hs  >=  MIN   <=>   hs <= BASE * H0 / (MIN - BASE * f_head)
        old = b.head_scale
        f_head = _FRACTIONS["head_scale"]
        h0 = _height_ratio(b) - f_head * b.head_scale
        limit = BASE_HEADS_TALL * h0 / (MIN_HEADS_TALL - BASE_HEADS_TALL * f_head)
        b.head_scale = max(BODY_RANGES["head_scale"][0], int(limit * 10000) / 10000)
        params.notes.append(f"head_scale {old:.3f} -> {b.head_scale:.4f} "
                            f"(adult proportions: {ht:.2f} < {MIN_HEADS_TALL} heads)")
    return params


def from_spec(resolved: dict) -> CharacterParams:
    """Map a resolved spec (see ``wogen.spec``) to validated parameters."""
    body = BodyParams(**{k: float(v) for k, v in resolved.get("body", {}).items()
                         if k in BODY_RANGES})
    face = FaceParams(**{k: float(v) for k, v in resolved.get("face", {}).items()
                         if k in FACE_KEYS})
    colors = resolved.get("colors", {})
    palette = Palette(**{k: colors.get(k) for k in ("hair", "eyes", "skin")})
    out = resolved.get("outfit", {})
    if isinstance(out, str):
        out = {"set": out}
    hair = resolved.get("hair", {})
    if isinstance(hair, str):
        hair = {"style": hair}
    params = CharacterParams(body=body, face=face, palette=palette, outfit=out.get("set"),
                             hair=hair.get("style"),
                             garment_add=list(out.get("add", [])),
                             garment_tints=dict(out.get("tint", {})))
    unknown = (set(resolved.get("body", {})) - set(BODY_RANGES)) | \
              (set(resolved.get("face", {})) - set(FACE_KEYS))
    if unknown:
        params.notes.append(f"ignored unknown keys: {sorted(unknown)}")
    return validate(params)
