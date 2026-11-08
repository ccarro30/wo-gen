# wo-gen

A Blender-based generator for stylized 3D anime characters (adult women). From a spec and a
seed it builds a character with her own proportions, face, colors and outfit, then poses her,
renders stills, turntables and short physics-animated clips, and exports reusable VRM/FBX
models. Driven from chat (Claude via Blender MCP) or headlessly from the command line.

**Status:** working end to end on one VroidStudio base body with a 17-garment library and 8 hairstyles.
See [docs/roadmap.md](docs/roadmap.md) for what's done, known issues and next steps.

| | |
|---|---|
| Generate | 11 body + 8 face parameters (eyes, face shape, brows, nose, mouth), 8 hairstyles, hair/eye/skin palette, outfit sets with mix-and-match and per-layer tints; adult-proportion rule enforced |
| Look | EEVEE cel shading (ZZZ-like), colored outlines, brows through bangs, bloom/grade |
| Pose | 19 poses (arm + leg IK), 22 expressions, gaze, props, saved custom poses; arms kept out of skirts |
| Motion | Keyed motion presets, chains and loops, BVH motion capture (CMU clips), VRM spring-bone physics for hair and skirts, MP4 clips/turntables |
| Output | PNG, MP4, `.blend`, VRM 1.0 (MToon + springs), FBX |

## Quick start

Prerequisites (see [docs/tooling.md](docs/tooling.md)): Blender 5.2 LTS at the default path
(or `WOGEN_BLENDER`), the VRM add-on, `uv sync` done. Assets are stored in Git LFS: set up
Git LFS before cloning (`git lfs install`, once per machine), or run `git lfs pull` after.

```powershell
uv run wogen generate --seed 7                         # out/generated.png from specs/default.toml
uv run wogen variants --seeds 1-8                      # out/variants.png: 8 characters
uv run wogen generate --seed 7 --pose peace --export out\seed7.vrm --export out\seed7.fbx
uv run pytest                                          # tests (includes headless Blender runs)
```

## Command line

All commands render headlessly; outputs default to `out/`. `uv run wogen <command> --help`
lists every option.

| Command | Does |
|---|---|
| `generate --spec S --seed N` | Seeded character → portrait. `--pose`, `--expression`, `--framing face\|bust\|full`, `--view-yaw`, `--save-blend F`, `--export F.vrm\|F.fbx` (repeatable) |
| `variants --seeds 1-8` | Contact sheet of seeds from a spec |
| `portrait` | Portrait of the base or a generated character (`--framing face\|bust\|full`). Character options below |
| `turntable` | 360° MP4 |
| `clip --preset NAME` | Keyed motion + baked physics → MP4 (`--no-physics`). Presets: `walk`, `run`, `spin`, `jump_for_joy`, `hop`, `wave_hello`, `blow_kiss`, `heart`, `bow`, `sway`, `look_around`; seamless loops `walk_loop`, `run_loop`; chain with commas (`wave_hello,walk,bow`) |
| `clip --mocap NAME` | Motion capture retargeted onto the character → MP4 (`--start/--end` seconds, `--in-place`). `mocap` lists the clips; `scripts\update-mocap.ps1` fetches them |
| `outfit-sheet` | Every outfit set on the base character |
| `hair-sheet` | Every hairstyle, front and back (`--outfit SET`, `--framing`) |
| `export F.blend --out F.vrm\|F.fbx` | Export the character in a saved scene (repeatable `--out`; the `.blend` isn't changed) |
| `harvest [--fresh] [--only garments\|hair]` | Extract garments (from `base_f01*.vrm`) and hairstyles (from `base_f01_hair*.vrm` + `base_f01`) into the library |
| `resolve SPEC --seed N` | Print a resolved spec as JSON (no Blender) |
| `catalog` | Print what a spec can contain: slider ranges, hairstyles, outfit sets, garments (no Blender) |
| `check SPEC` | Strictly check a spec: unknown keys, out-of-range values, unknown asset names (no Blender) |
| `render-test` | Smoke test of headless EEVEE |

Character options (`portrait`, `turntable`, `clip`): `--spec S` / `--seed N` (generate the
character; without them it's the plain base), `--base`, `--pose NAME[,NAME]`, `--expression`,
`--hair STYLE`, `--outfit SET`, `--equip G`, `--unequip SLOT|G`, `--tint G=#hex`,
`--seat HEIGHT`, `--view-yaw DEG`, `--through-hair brow[,eyeline]`, `--no-post`. With a seed,
the other options override what the spec chose, e.g.
`uv run wogen clip --seed 5 --preset hop --hair hair_bob`.

## Chat (Blender MCP)

With Blender open and the MCP add-on's server started, Claude calls the same package:

```python
from wogen.bl import anim, character, export, face, generate, hair, outfit, physics, pose, render
generate.generate("specs/default.toml", seed=7)          # or a dict spec
generate.set_palette(hair="#f4b6c2", eyes="#5ab0ff")
outfit.equip_set("school"); outfit.equip("bow_pink", exclusive=False)
hair.list_styles(); hair.equip("hair_twintails")         # replaces the base hair
outfit.recolor("skirt_plaid", tint="#3a4a7a")            # layer="CLOTH_02" for one layer
pose.apply_pose("peace"); face.expression("grin"); face.gaze(yaw=8)
render.portrait("bust", pose=None, out_path=r"...\out\peace.png")   # pose=None keeps it
anim.preset("hop"); physics.bake(); render.clip(r"...\out\hop.mp4")
export.export_character(r"...\out\me.vrm")               # VRM or FBX; live scene untouched
```

Review helpers: `render.expression_sheet()`, `pose_sheet()`, `garment_sheet()`,
`layer_sheet(name)`, `outfit_sheet()`, `contact_sheet(...)`.

## Project layout

```
blender/modules/wogen/   the package (importable by the CLI, headless Blender and MCP)
  *.py                   pure Python: specs, body params, poses, expressions, garment naming
  bl/*.py                Blender code: character, toon, overlay, outfit, garment_rig, body,
                         face, pose, anim, physics, render, post, props, generate, export, jobs
blender/addons/          pinned MCP for Blender add-on (Blender script directory)
assets/base/             VroidStudio VRM exports (base_f01 + outfit variants)
assets/garments/         garment library (.blend) + index.json (signatures, sets, names, slots)
assets/poses/            user-saved poses (.toml), created on first save
assets/LICENSES.md       asset provenance
specs/                   character specs (TOML)
tests/                   pytest (pure + headless Blender)
docs/                    documentation
out/, .cache/            generated output and scratch (gitignored)
vroid/                   VroidStudio source project (.vroid)
references/              style references (copyrighted; gitignored)
```

## Design constraints

- All generated characters are adults: proportions are clamped to ≥ 6.6 heads tall.
- Generation is reproducible: same spec + seed + asset library → same character.
- The headless pipeline is the source of truth; MCP is an interactive layer on top of it.
- Personal project, never distributed: resemblance to existing characters is fine, and
  third-party models may be imported for personal use (recorded in `assets/LICENSES.md`).

## Documentation

| Doc | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | How it works: pipeline, modules, data, key techniques |
| [docs/workflows.md](docs/workflows.md) | How-tos: specs, garments, poses, exporting, MCP updates |
| [docs/text-to-spec.md](docs/text-to-spec.md) | Describe a character in words → spec, in chat (vocabulary, process, rules) |
| [docs/roadmap.md](docs/roadmap.md) | Status by phase, known issues, decisions, next steps |
| [docs/tooling.md](docs/tooling.md) | Installed tools, versions, MCP setup, dev workflow |
| [docs/style-guide.md](docs/style-guide.md) | Target look and how far each element is implemented |
| [docs/implementation-options.md](docs/implementation-options.md) | Original option analysis, with the outcome of each |
