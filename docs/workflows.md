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

`uv run pytest` runs everything (159 tests, about 55 s). The 3 `blender`-marked tests launch
headless Blender (render test, portrait job with a hairstyle, clip job).
`uv run pytest -m "not blender"` runs the 156 pure tests in under a second. Test temp files go
to `.cache/pytest`.
