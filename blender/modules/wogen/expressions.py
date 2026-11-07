"""Facial expression presets (pure Python; applied by ``wogen.bl.face``).

Each preset is a weighted set of VRoid ``Fcl_*`` face shape keys. Presets can be mixed:
``resolve_weights({"happy": 0.6, "wink_l": 1.0})``.
"""

from __future__ import annotations

PRESETS: dict[str, dict[str, float]] = {
    "neutral": {},
    # full-face emotions (VRM presets)
    "happy": {"Fcl_ALL_Joy": 1.0},
    "fun": {"Fcl_ALL_Fun": 1.0},
    "angry": {"Fcl_ALL_Angry": 1.0},
    "sad": {"Fcl_ALL_Sorrow": 1.0},
    "surprised": {"Fcl_ALL_Surprised": 1.0},
    # composed, subtler expressions
    "smile_soft": {"Fcl_BRW_Fun": 0.4, "Fcl_EYE_Fun": 0.35, "Fcl_MTH_Fun": 0.6},
    "smile_closed_eyes": {"Fcl_BRW_Joy": 0.6, "Fcl_EYE_Joy": 1.0, "Fcl_MTH_Joy": 0.7},
    "grin": {"Fcl_BRW_Fun": 0.5, "Fcl_EYE_Fun": 0.5, "Fcl_MTH_Fun": 0.4, "Fcl_MTH_Large": 0.35,
             "Fcl_MTH_A": 0.3},
    "smug": {"Fcl_BRW_Angry": 0.25, "Fcl_EYE_Fun": 0.45, "Fcl_MTH_Fun": 0.45, "Fcl_MTH_Small": 0.3},
    "shy": {"Fcl_BRW_Sorrow": 0.55, "Fcl_EYE_Fun": 0.25, "Fcl_MTH_Small": 0.6, "Fcl_MTH_Fun": 0.25},
    "pout": {"Fcl_BRW_Angry": 0.35, "Fcl_MTH_Angry": 0.6, "Fcl_MTH_Small": 0.5},
    "worried": {"Fcl_BRW_Sorrow": 0.8, "Fcl_EYE_Sorrow": 0.3, "Fcl_MTH_Sorrow": 0.4},
    "determined": {"Fcl_BRW_Angry": 0.6, "Fcl_EYE_Angry": 0.3, "Fcl_MTH_Close": 0.6},
    "sleepy": {"Fcl_BRW_Sorrow": 0.2, "Fcl_EYE_Close": 0.55, "Fcl_MTH_Small": 0.4},
    "startled": {"Fcl_BRW_Surprised": 1.0, "Fcl_EYE_Surprised": 0.8, "Fcl_MTH_O": 0.5},
    # eyes
    "blink": {"Fcl_EYE_Close": 1.0},
    "wink_l": {"Fcl_EYE_Close_L": 1.0},
    "wink_r": {"Fcl_EYE_Close_R": 1.0},
    # mouth shapes (visemes) for lip-sync
    "aa": {"Fcl_MTH_A": 1.0},
    "ih": {"Fcl_MTH_I": 1.0},
    "ou": {"Fcl_MTH_U": 1.0},
    "ee": {"Fcl_MTH_E": 1.0},
    "oh": {"Fcl_MTH_O": 1.0},
}

VISEMES = frozenset({"aa", "ih", "ou", "ee", "oh"})


def list_expressions() -> list[str]:
    return sorted(PRESETS)


def resolve_weights(spec: str | dict[str, float], weight: float = 1.0) -> dict[str, float]:
    """Preset name or {preset or Fcl_ key: weight} -> {shape key: weight}, clamped to 0..1."""
    items = {spec: weight} if isinstance(spec, str) else {k: v * weight for k, v in spec.items()}
    keys: dict[str, float] = {}
    for name, w in items.items():
        if name in PRESETS:
            for key, kw in PRESETS[name].items():
                keys[key] = keys.get(key, 0.0) + kw * w
        elif name.startswith("Fcl_"):
            keys[name] = keys.get(name, 0.0) + w
        else:
            raise KeyError(f"Unknown expression {name!r}. Presets: {', '.join(list_expressions())}")
    return {k: max(0.0, min(1.0, v)) for k, v in keys.items()}
