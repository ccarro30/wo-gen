"""Character specs: authored as TOML, resolved deterministically from a seed (pure Python).

TOML is used because ``tomllib`` is in the standard library both in the CLI and in
Blender's bundled Python, so specs load the same everywhere with no extra dependencies.

Resolution rules for any value in the spec tree:
- ``[min, max]`` with two numbers  -> uniform sample (int if both bounds are ints)
- ``{ choice = [a, b, ...] }``     -> one of the options
- anything else                    -> kept as-is

Every value draws from its own random stream, seeded by (seed, key path), e.g.
``"7:face.eye_size"``. Adding, removing or reordering keys never changes the values drawn for
the other keys, so a seed keeps its look when specs gain new settings.
"""

from __future__ import annotations

import json
import random
import tomllib
from pathlib import Path
from typing import Any

SPEC_VERSION = 1


def load_spec(path: str | Path) -> dict[str, Any]:
    with open(path, "rb") as f:
        spec = tomllib.load(f)
    version = spec.get("version", SPEC_VERSION)
    if version != SPEC_VERSION:
        raise ValueError(f"Unsupported spec version {version} (expected {SPEC_VERSION})")
    return spec


def resolve(spec: dict[str, Any], seed: int | None = None) -> dict[str, Any]:
    """Return a new spec with every range/choice replaced by a concrete value."""
    if seed is None:
        seed = int(spec.get("seed", 0))
    resolved = _resolve(spec, seed, "")
    resolved["seed"] = seed
    resolved["version"] = SPEC_VERSION
    return resolved


def to_json(resolved: dict[str, Any]) -> str:
    return json.dumps(resolved, indent=2, sort_keys=True)


def _is_range(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    )


def _rng(seed: int, path: str) -> random.Random:
    # String seeds hash with SHA-512 (random.seed version 2): stable across runs and platforms.
    return random.Random(f"{seed}:{path}")


def _resolve(value: Any, seed: int, path: str) -> Any:
    if _is_range(value):
        lo, hi = value
        if lo > hi:
            raise ValueError(f"Range has min > max: {value}")
        rng = _rng(seed, path)
        if isinstance(lo, int) and isinstance(hi, int):
            return rng.randint(lo, hi)
        return round(rng.uniform(lo, hi), 4)
    if isinstance(value, dict):
        if set(value) == {"choice"}:
            options = value["choice"]
            if not isinstance(options, list) or not options:
                raise ValueError(f"'choice' needs a non-empty list: {value}")
            return _resolve(_rng(seed, path).choice(options), seed, path + "/choice")
        return {k: _resolve(v, seed, f"{path}.{k}" if path else k) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, seed, f"{path}[{i}]") for i, v in enumerate(value)]
    return value
