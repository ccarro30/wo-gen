"""Run wogen jobs inside a headless Blender process (pure Python)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .paths import MODULES_DIR, find_blender


def run_job(job: str, *args: str, blend_file: Path | None = None) -> int:
    """Run ``wogen.bl.jobs`` job ``job`` in background Blender; returns Blender's exit code.

    ``--factory-startup`` keeps runs hermetic (no user prefs or add-ons), so the modules
    directory is put on ``sys.path`` explicitly rather than via the script-directory pref.
    """
    bootstrap = (
        "import sys; "
        f"sys.path.insert(0, {str(MODULES_DIR)!r}); "
        "from wogen.bl.jobs import main; main()"
    )
    cmd = [str(find_blender()), "--background", "--factory-startup"]
    if blend_file is not None:
        cmd.append(str(blend_file))
    cmd += ["--python-exit-code", "1", "--python-expr", bootstrap, "--", job, *args]
    return subprocess.run(cmd, check=False).returncode
