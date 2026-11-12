# Workflows

## Write a character spec

Specs are TOML in `specs/`. Any value can be a fixed value, a `[min, max]` range, or
`{ choice = [...] }`; the seed resolves ranges and choices. Start from
[specs/default.toml](../specs/default.toml) (everything random) or
[specs/school_navy.toml](../specs/school_navy.toml) (fixed look). To start from a description
in words instead, see [text-to-spec.md](text-to-spec.md). `uv run wogen check specs/x.toml`
validates any spec strictly.

```toml
version = 1
seed = 1                 # default seed; --seed overrides
base = "base_f01"        # assets/base/<base>.vrm

[body]                   # multipliers around 1.0 (ranges: wogen/body.py BODY_RANGES)
leg_length = [1.0, 1.06] # head_scale leg_length arm_length torso_length neck_length
bust = [0.9, 1.15]       # shoulder_width hip_width waist thigh arm_thickness bust
seat = 1.2               # shapes (1.0 = suits hip_width/thigh, 0 = none): seat seat_round
                         # seat_fold hip_curve thigh_upper thigh_back thigh_gap

[face]                   # -1 .. 1
eye_size = [0.2, 0.6]    # eye_size eye_height face_width chin_length
brow_tilt = 0.3          # brow_height brow_tilt nose_size mouth_width

[colors]                 # "#RRGGBB"; hair/eyes colorize, skin tints (keep it near white)
hair = { choice = ["#1d1b26", "#f4b6c2"] }
eyes = "#5ab0ff"

[hair]
style = "hair_hime_long"   # library hairstyle (hair-sheet shows them); omit for the base hair

[outfit]
set = "school"                             # tennis | sweets | school | red_dress | pink_capelet
add = ["bow_pink"]                         # extra garments
tint = { skirt_plaid = "#4a5a9a", "tennis_set_white:CLOTH_01" = "#c03050" }  # :LAYER = one layer
```

Values are clamped to their ranges and the adult rule may reduce `head_scale`. The reasons
appear as `[generate]` notes. `uv run wogen resolve specs/x.toml --seed 3` shows the resolved
values without Blender.

## Tune body shape with the user

Shapes are easiest to judge by hand. In live Blender (MCP): generate the body in question,
unequip everything but hair and shoes, then add each candidate field from `bl/shape.py` (or a
new one) as a shape key on `Body` (slider -1..2) and let the user drag them in the Shape Keys
panel. Read the values back, and build them in: a new field goes into `shape.offsets`, its
name into `body.SHAPES` with the size slider it follows and the tuned amount, and the
amounts in `SHAPES` are what the user chose on a body at `SHAPE_TUNED_ON`. Check a bare,
a shorts and a skirt render afterward (cloth follows the skin by nearest-vertex transfer).
The body mesh is coarse (about 120 vertices over each seat), so narrow features such as a
crease can look faceted at large values.

## Add garments to the library

1. In VroidStudio, open the **same body** (don't change body sliders) and dress it in new
   items. Shoes may differ; heel height is handled.
2. Export VRM 1.0 with **no reductions** to `assets/base/base_f01_<anything>.vrm` (not
   `base_f01_hair*`, which is reserved for hairstyles).
3. `uv run wogen harvest`. New garments are saved; duplicates are skipped. An export whose
   skeleton differs beyond a vertical shift is skipped with a reason.
4. `uv run wogen outfit-sheet` and review. The new outfit set is named after the export file.
5. Give garments descriptive names and correct slots from chat:
   ```python
   outfit.rename({"tops_003_01": ("hoodie_grey", "outer")}, {"base_f01_outfit6": "street"})
   ```
   Renames live in `assets/garments/index.json` and are re-applied by every harvest
   (including `--fresh`, which rebuilds the library contents from the exports).
6. Add the new export to [assets/LICENSES.md](../assets/LICENSES.md) and commit; `.vrm` and
   `.blend` files go to Git LFS automatically.

Use `render.garment_sheet()` to see each garment alone, and `outfit.list_layers(name)` with
`render.layer_sheet(name)` to find which texture layer is which part.

## Add hairstyles to the library

1. In VroidStudio, open the same body and change **only the hair** (clothes can stay).
2. Export VRM 1.0 with no reductions to `assets/base/base_f01_hair<anything>.vrm`. The
   `_hair` prefix makes harvest treat it as a hairstyle, not an outfit.
3. `uv run wogen harvest --only hair`, then `uv run wogen hair-sheet` to review.
4. Name it from chat, e.g. `outfit.rename({"hair_9": "hair_braid"})`, add it to the
   `[hair] style` choices in specs, and record the export in the asset license file.

The hairstyle replaces the base model's hair (meshes, HairBack cap, hair springs). It takes the
palette's hair color and keeps its own spring chains, which are also exported to VRM.

## Poses

- Library poses: `wogen/poses.py` (`POSES`). For the axis conventions, see the module
  docstring.
- Make a custom pose in chat or by hand in Blender's pose mode, then `pose.save_pose("name")`.
  It's written to `assets/poses/name.toml` and is usable by name everywhere (`--pose name`).
- Combine: `pose.apply_pose(["idle", "hand:peace:right"])`, or tweak with
  `apply_pose({...}, reset=False)`.

## Clips

`anim.sequence([(frame, pose, expression[, {"ground": False}]), ...])`, then `physics.bake()`
and `render.clip(path)` (`follow=True` for travel). The CLI `clip` command uses
`wogen.motions.PRESETS`: add new presets there (plus `PRESET_OPTIONS` if it travels, spins or
loops). Presets: `walk`, `run`, `spin`, `jump_for_joy`, `hop`, `wave_hello`, `blow_kiss`,
`heart`, `bow`, `sway` (loops), `look_around`, and the seamless loops `walk_loop`, `run_loop`.
Keyed feet are planted automatically between keys.

- **Chains**: `--preset wave_hello,walk,spin,bow` plays presets in order with a 10-frame
  transition; after a walk or run the rest happens where she stopped. Mix in motion capture
  with `mocap:CLIP` (trim with `@START-END` seconds), e.g.
  `--preset wave_hello,mocap:happy_walk,bow` or `mocap:salsa@2-6,bow`: each part starts where
  the previous one ended and her feet step across the 14-frame transitions. From chat:
  `opts = anim.preset("wave_hello,walk,bow")`, then bake with `opts` and render.
- **Loops**: `walk_loop` / `run_loop` simulate several warm-up cycles and render only the last
  one, with the spring keys closed onto the first frame, so the MP4 loops without a seam
  (the follow camera keeps her in place). From chat: `physics.bake(...)`, then
  `anim.loop_range(opts)` before `render.clip`.
`clip`, `turntable` and `portrait` take `--seed N` (and `--spec S`) to use a generated
character, e.g. `uv run wogen clip --seed 5 --preset hop --framing full`. Video sizes are
rounded up to even numbers (H.264).

## Motion capture

`uv run wogen mocap` lists the clips; `uv run wogen clip --mocap dance --expression happy
--framing full --out out\dance.mp4` renders one (`--start/--end` seconds to trim,
`--in-place` to remove travel; `--no-foot-lock` and `--no-clear` skip foot locking and the
arm-vs-skirt pass, each about 0.15 s per frame). Fingers are animated automatically. From chat: `opts = mocap.apply("dance")`, then `physics.bake(...)` and
`render.clip(..., follow=opts["follow"])`. To get more clips, see the motion capture section
of [tooling.md](tooling.md).

## Tune physics and review motion

Soft tissue and springs are tuned in a loop: measure, look at frames, then let the user judge
clips. An agent can't watch an MP4, so the first two steps are its eyes; the user's eye on
the clip is the only real test of feel. Targets are in
[style-guide.md](style-guide.md#secondary-motion-targets).

**Where the knobs are**

| What | Where |
|---|---|
| Bust response | `softtissue.TissueParams` defaults; size scaling in `softtissue.for_size` |
| Butt, thigh, belly response, region shape and size scaling | `softtissue.REGIONS` (one `Region` each) |
| Left/right difference | `PhysicsSettings.tissue_variation` (0 = mirror images); amounts in `softtissue.VARIATION`, `MAX_DELAY` |
| How an offset becomes bone motion (bust: 60 % shift + swing, drops at 70 %) | `physics.TISSUE_TRANSLATE`, `TISSUE_DROP`, `_Tissue.pose` |
| Hair and skirt chains | `PhysicsSettings` (`stiffness_scale`, `drag_scale`, `overrides` per chain name, `hair_taper` root/tip) |
| Idle drift (breeze) | `PhysicsSettings.drift`, `drift_cloth`, `drift_seed`; the signal in `wogen.drift` |
| Per-preset bake options (`carry`, `substeps`) | `motions.PRESET_OPTIONS` |

**What each parameter does, and the feedback it answers**

| The user says | Change | Because |
|---|---|---|
| "Too sensitive" / "moves too much on a walk" | Lower `gain` | Gain scales the response to every motion |
| "Jumps should hit harder" / "trim the peak" | Raise / lower `limit` | The limit is the soft clamp that only big impacts reach |
| "Should settle faster" / "rings too long" | Raise `damping` (and a little `frequency`) | Damping ratio sets how many swings it takes; 0.2 is 3 swings, 0.35 is 1 to 2 |
| "Too stiff" / "too floaty" | Lower / raise `frequency` | Frequency is the speed of the bounce. Lowering it also raises amplitude (offset is about gain x acceleration / (2 pi f)^2), so re-check gain |
| "Only the middle moves" | More shift, less swing (`TISSUE_TRANSLATE`), or a wider region (`radii`, `core`) | A swing moves the tip; a shift moves the whole weighted area |
| "Snaps" or "pops" on a run | `drive_limit`, `drive_window`, or fix the motion key (check its acceleration per frame first) | One-frame acceleration spikes from keyed motion |
| "Whips" or "slams" through runs and jogs | Raise `limit_damping` (bust: 1.5) | Steady steps near the tissue's own frequency wind it past the clamp; this drains energy only near the limit |
| "Hair's dead still" / "too breezy" | Raise / lower `drift` | A slow push on every chain; skirts get `drift_cloth` of it |
| "Hair swings like a board" / "tips too floppy" | Widen / narrow `hair_taper` | Stiffness multiplier from root to tip |
| "Bigger should move more" / "smaller firmer" | Exponents in `for_size`, `Region.size` | Size scales gain up, frequency down, damping up |
| "Both sides move exactly alike" / "they look out of sync" | Raise / lower `tissue_variation` | One side lags 20 to 40 ms and responds a few percent differently |

Change one thing per round, and keep the user's last approved values in mind: say what changed
in the same terms they used.

**1. Measure** (no rendering, about a minute):

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup `
  --python scripts\tissue_measure.py -- specs\default.toml walk,run,hop 7
```

Per tissue bone and preset it prints the anchor's peak acceleration, the offset with the
clamp off (`free`), the baked peak, the biggest frame-to-frame step and the limit. Compare
`free` with `limit`: well under on a walk, about 1.5 times on a hop. Above 3 times it slams
between its limits. Lower-body numbers are the helper's shift; the skin moves about half.
Run it for a slim and a curvy spec as well as the base (fixed `[body]` values in a scratch
spec under `.cache/tmp`).

**2. Look at frames** (about 30 s):

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup `
  --python scripts\frame_strip.py -- specs\default.toml C:\...\wo-gen\.cache\tmp\strip.png `
  hop 18,20,21,22,23,25 hips 160 bare
```

One PNG with the frames side by side. Check for skin through cloth, creases, and shapes that
look pushed rather than soft. `bare` removes the outfit; the base body's painted shorts make
hip motion easy to read. Most outfits hide the hips under a skirt (only `tennis` has shorts),
so also check dressed.

**3. Render clips for the user** (about 30 s each):

```powershell
uv run wogen clip --preset hop --spec S --seed 7 --framing hips --view-yaw 160 `
  --unequip tennis_set_white --width 720 --height 900 --out out\tissue\hop_base.mp4
```

Give them walk, run and hop at slim, base and curvy, from behind (`--view-yaw 160`) and from
the front (`35`), bare and dressed; `--framing bust --view-yaw 50` for the bust. Ask for
feedback per size: amount on a walk, amount on a jump, settle speed. Then run
`uv run pytest tests/test_softtissue.py` and update the numbers in the style guide and
[architecture.md](architecture.md).

**To add a soft region** (say, upper arms): add a `Region` to `softtissue.REGIONS` (anchor
bone, source bones, centre offset and radii in the base rest space, response, size sliders).
The helper bones, weights on body and garments, bake, loop closure and clearing all follow
from the list. Check the falloff with a static render before any motion.

## Export a character

- CLI: `uv run wogen generate --seed 7 --export out\c.vrm --export out\c.fbx`, or from a saved
  scene (e.g. one written with `--save-blend`): `uv run wogen export out\c.blend --out out\c.vrm`.
- Chat: `export.export_character(r"...\out\c.vrm")`. It exports a copy, so the scene is
  untouched.
- VRM (1.0) is for VRM-capable apps and viewers: MToon look, expressions, hair + skirt spring
  bones. ⚠ Some VTubing apps only read VRM 0.x; check the app, or convert. FBX is for
  engines: Principled materials with embedded textures, a T-pose rest, and the VroidStudio
  bone names.
- The baked-in result: face sliders, palette and garment tints, worn garments only, and
  hidden skin removed.

## Update the MCP server/add-on

`.\scripts\update-blender-mcp.ps1` pins the newest `mcp-for-blender` release (no-op if current);
then restart Blender and Claude Code. See [tooling.md](tooling.md).

## Run tests

`uv run pytest` runs everything (173 tests, about 55 s). The 3 `blender`-marked tests launch
headless Blender (render test, portrait job with a hairstyle, clip job).
`uv run pytest -m "not blender"` runs the 170 pure tests in under a second. Test temp files go
to `.cache/pytest`.
