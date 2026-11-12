"""Soft-tissue numbers per motion preset, without rendering (run inside headless Blender).

For every tissue bone (bust and lower-body helpers; left side only) and preset it prints:

    acc    peak acceleration of the anchor, m/s^2
    free   peak offset with the clamp off, mm (how hard the motion drives the tissue)
    peak   peak offset as baked, mm (z = its vertical part)
    step   biggest change between two frames, mm (large = it snaps or pops)

Lower-body offsets are the helper bone's shift; the skin moves by about half of that (its
helper weight). Bust offsets are at the chain's tip. Read ``free / limit``: about 1.5 means
"reaches the clamp softly", above 3 means it slams between its limits.

Usage (from the repo root)::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --background `
      --factory-startup --python scripts\\tissue_measure.py -- [SPEC] [PRESETS] [SEED]

SPEC defaults to specs/default.toml, PRESETS to walk,run,hop (comma-separated; mocap tokens
such as mocap:jog@0-3 work), SEED to 7. Lines start with RESULT, so filter on that.
"""
import math
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender" / "modules"))

import bpy  # noqa: E402
from wogen import softtissue  # noqa: E402
from wogen.bl import anim, generate, physics  # noqa: E402
from wogen.bl.character import character_armature  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
spec = args[0] if args else "specs/default.toml"
presets = (args[1] if len(args) > 1 else "walk,run,hop").split(",")
seed = int(args[2]) if len(args) > 2 else 7

generate.generate(spec, seed)
arm = character_armature()
scene = bpy.context.scene


def length(v):
    return math.sqrt(sum(c * c for c in v))


for name in presets:
    anim.clear()
    anim.preset(name)
    physics.clear(arm)
    tissue = physics._Tissue(arm, physics.PhysicsSettings().tissue)
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        tissue.sample()
    fps = scene.render.fps / scene.render.fps_base
    for side in tissue.sides:
        if ".R." in side["bone"] or "_R_" in side["bone"]:
            continue
        acc = max(length(a) for a in softtissue.accelerations(side["pos"], fps))
        free = max(length(o) for o in tissue.offsets(
            {**side, "params": replace(side["params"], limit=10.0)}, fps))
        offsets = tissue.offsets(side, fps)
        peak = max(length(o) for o in offsets)
        peak_z = max(abs(o[2]) for o in offsets)
        step = max(math.dist(a, b) for a, b in zip(offsets, offsets[1:]))
        print(f"RESULT {name:<14} {side['bone'][-34:]:<34} acc {acc:6.1f}  "
              f"free {free * 1000:6.1f}  peak {peak * 1000:5.1f} (z {peak_z * 1000:5.1f})  "
              f"step {step * 1000:5.1f}  limit {side['params'].limit * 1000:4.1f} mm")
