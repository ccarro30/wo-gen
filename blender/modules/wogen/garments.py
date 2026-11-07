"""Garment naming helpers (pure Python; used by ``wogen.bl.outfit``).

VroidStudio material names look like ``N00_010_01_Onepiece_00_CLOTH_02``:
an item id (``N00_010_01_Onepiece_00``), then the class (``CLOTH``/``SKIN``/...) and a layer
number. VroidStudio exports each garment as several stacked copies of the same geometry, one
per texture layer, so a garment is identified by the item id, not by the material.
"""

from __future__ import annotations

import re

_ITEM_RE = re.compile(r"^(?P<item>N\d+_\d+_\d+_(?P<kind>[A-Za-z]+)_\d+)_(?P<cls>[A-Z]+)(?:_\d+)?$")
_DUP_SUFFIX = re.compile(r"\.\d{3}$")   # Blender's ".001" for duplicate datablock names


def strip_suffix(name: str) -> str:
    """Drop the ``wg_``/``wgo_``/``wgx_`` prefix and Blender's ``.NNN`` duplicate suffix."""
    for prefix in ("wgx_", "wgo_", "wg_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return _DUP_SUFFIX.sub("", name)

# VroidStudio item kind -> outfit slot (what it replaces when equipping).
SLOTS = {
    "Onepiece": "full", "Tops": "top", "Bottoms": "bottom", "Shoes": "shoes",
    "Socks": "legwear", "Accessory": "accessory", "Inner": "inner",
}
# Equipping a garment in one slot removes garments in the conflicting slots. Only the same
# slot conflicts: VroidStudio layers items freely (e.g. a "Onepiece" skirt under a top).
# "outer" layers over a top (cardigans, jackets).
CONFLICTS = {
    "full": {"full"}, "top": {"top"}, "bottom": {"bottom"}, "shoes": {"shoes"},
    "legwear": {"legwear"}, "inner": {"inner"}, "outer": {"outer"}, "accessory": set(),
}
VALID_NAME = re.compile(r"^[a-z0-9][a-z0-9_]*$")


def validate_name(name: str) -> str:
    if not VALID_NAME.match(name):
        raise ValueError(f"Garment/set names must be lowercase letters, digits, underscores: {name!r}")
    return name


def parse_material(name: str) -> dict | None:
    """``{"item", "kind", "cls"}`` for a VroidStudio material name, else ``None``."""
    m = _ITEM_RE.match(strip_suffix(name))
    return m.groupdict() if m else None


def garment_key(material_name: str) -> str | None:
    """Item id for clothing materials; ``None`` for body/face/hair/eye materials."""
    info = parse_material(material_name)
    if info is None or info["cls"] in ("SKIN", "FACE", "EYE", "HAIR"):
        return None
    return info["item"]


def slot_for(item: str) -> str:
    info = parse_material(item + "_CLOTH")
    kind = info["kind"] if info else item
    return SLOTS.get(kind, "accessory")


def skeleton_mismatch(a: dict, b: dict, tolerance: float = 0.001,
                      root: str = "J_Bip_C_Hips") -> tuple[float, str | None]:
    """Compare skeletons ({bone: (x, y, z)}) up to a pure vertical shift. VroidStudio lifts the
    whole body by the shoe sole/heel height, so exports of one body differ only by that.
    Returns ``(dz, None)`` when ``b == a + dz`` within ``tolerance`` metres, else
    ``(dz, reason)``."""
    missing = sorted(set(a) ^ set(b))
    if missing:
        return 0.0, f"bone sets differ: {missing[:4]}"
    dz = b[root][2] - a[root][2]

    def err(n):
        return sum((x - y) ** 2 for x, y in zip(a[n], (b[n][0], b[n][1], b[n][2] - dz))) ** 0.5
    worst = max(a, key=err)
    return dz, (None if err(worst) <= tolerance else f"{worst} off by {err(worst) * 1000:.1f} mm")


def display_name(item: str) -> str:
    """``N00_010_01_Onepiece_00`` -> ``onepiece_010_01``."""
    parts = item.split("_")
    return f"{parts[3].lower()}_{parts[1]}_{parts[2]}" if len(parts) >= 5 else item.lower()
