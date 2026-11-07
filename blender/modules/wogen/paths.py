"""Project paths and Blender executable discovery (pure Python)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
MODULES_DIR = PACKAGE_DIR.parent              # blender/modules (on sys.path inside Blender)
REPO_ROOT = MODULES_DIR.parent.parent
ASSETS_DIR = REPO_ROOT / "assets"
OUT_DIR = REPO_ROOT / "out"
CACHE_DIR = REPO_ROOT / ".cache"


def scratch_dir(prefix: str) -> Path:
    """A fresh temp directory inside the project (``.cache/tmp``), never the system temp."""
    import uuid
    path = CACHE_DIR / "tmp" / f"{prefix}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path

_DEFAULT_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")


def find_blender() -> Path:
    """Blender executable: $WOGEN_BLENDER, then the default install path, then PATH."""
    env = os.environ.get("WOGEN_BLENDER")
    if env:
        path = Path(env)
        if not path.is_file():
            raise FileNotFoundError(f"WOGEN_BLENDER points to a missing file: {path}")
        return path
    if _DEFAULT_BLENDER.is_file():
        return _DEFAULT_BLENDER
    on_path = shutil.which("blender")
    if on_path:
        return Path(on_path)
    raise FileNotFoundError("Blender not found. Set WOGEN_BLENDER to the blender executable.")
