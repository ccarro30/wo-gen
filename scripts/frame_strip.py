"""Frames of a motion preset side by side in one PNG (run inside headless Blender).

An agent can't watch an MP4, so this is how it looks at motion: pick the frames around an
impact (a landing, a footfall) and read the strip for clipping, creases and odd shapes.
Physics is baked exactly as in ``wogen clip``.

Usage (from the repo root; OUT must be an absolute path)::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --background `
      --factory-startup --python scripts\\frame_strip.py -- SPEC OUT.png PRESET FRAMES `
      [FRAMING] [YAW] [WEAR] [SEED] [CELL]

SPEC     a spec path, or mmd:NAME for an imported model (wogen mmd lists them; WEAR and
         SEED don't apply)
FRAMES   comma-separated frame numbers, e.g. 18,20,21,22,23,25 (the hop lands at 20)
FRAMING  face | bust | hips | full (default hips)
YAW      camera orbit in degrees (default 160: rear three-quarter; 0 = front)
WEAR     spec (what the spec chose, default) | bare (no garments; the base body's painted
         shorts show hip and butt motion well) | an outfit set name
SEED     default 7
CELL     cell size in pixels (default 400)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender" / "modules"))

import bpy  # noqa: E402
from wogen.bl import anim, generate, mmd_import, outfit, physics, render  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
spec, out, preset, frames = args[:4]
framing = args[4] if len(args) > 4 else "hips"
yaw = float(args[5]) if len(args) > 5 else 160.0
wear = args[6] if len(args) > 6 else "spec"
seed = int(args[7]) if len(args) > 7 else 7
CELL = int(args[8]) if len(args) > 8 else 400

if spec.startswith("mmd:"):
    mmd_import.prepare(spec[4:])
    wear = "spec"
else:
    generate.generate(spec, seed)
if wear == "bare":
    for g in outfit.garments():
        if g["wg_slot"] not in ("hair", "shoes"):
            outfit.unequip(g["wg_garment"])
elif wear != "spec":
    outfit.equip_set(wear)
opts = anim.preset(preset)
print("RESULT", physics.bake(physics.PhysicsSettings(substeps=opts.get("substeps", 1),
                                                     carry=opts.get("carry", 0.0))))
scene = bpy.context.scene
scene.frame_set(scene.frame_start)
render.portrait(framing, resolution=(CELL, CELL), pose=None, view_yaw=yaw, post=False)
if opts.get("follow"):
    render.follow_camera(scene)
numbers = [int(f) for f in frames.split(",")]
cells = [(str(f), (lambda f=f: scene.frame_set(f))) for f in numbers]
print("RESULT frames:", render.contact_sheet(cells, out, None, CELL, len(numbers)))
print("RESULT wrote", out)
