# Architecture

## Overview

```
 ┌──────────────────┐  spec.toml + seed   ┌──────────────────────────────────────────────┐
 │ CLI (uv run      │ ──────────────────▶ │ Blender 5.2 (headless job or live GUI)        │
 │ wogen …)         │  launches Blender   │                                               │
 └──────────────────┘                     │  wogen.bl                                     │
 ┌──────────────────┐  Python via MCP     │   import VRM ─▶ body retarget ─▶ toon/overlay │
 │ Claude + Blender │ ──────────────────▶ │   ─▶ face keys ─▶ outfit split/equip ─▶ palette│
 │ MCP (live scene) │  + screenshots      │   ─▶ pose / expression / anim ─▶ physics bake │
 └──────────────────┘                     │   ─▶ render (EEVEE + compositor) / export     │
                                          └──────────────────────┬────────────────────────┘
        assets/base/*.vrm  assets/garments/*.blend                │
        specs/*.toml       assets/poses/*.toml          PNG · MP4 · .blend · VRM · FBX
```

## Principles

1. **Base model + library + parameters.** Quality comes from a VroidStudio base (topology,
   rig, face shape keys, spring bones). Variety comes from rest-pose retargeting, procedural
   face keys, recoloring, and a harvested garment library.
2. **Deterministic.** A character is fully described by spec + seed + asset library. All
   randomness happens while resolving the spec (`wogen.spec`), never inside Blender operations.
3. **Headless is the source of truth.** Every feature is a plain function in `wogen.bl`,
   reachable from a headless job (`wogen.bl.jobs`) and from MCP. MCP never runs logic that
   isn't in the package.
4. **Non-destructive where it matters.** Toon materials are twins of the MToon sources (which
   are kept, fake-user protected). Export works on a saved copy. Garments are separate objects.

## Code layout

`blender/modules/wogen/` is on `sys.path` for all three entry points: the CLI (installed into
`.venv`), headless jobs (the launcher inserts it; jobs run with `--factory-startup`), and the
live GUI (Blender adds `<script dir>/modules`, with `<repo>/blender` set as script directory).

Pure modules (no `bpy`, unit-tested):

| Module | Responsibility |
|---|---|
| `spec` | TOML specs; seeded resolution of `[min, max]` ranges and `{choice = [...]}` |
| `body` | Body/face/palette parameters, ranges, adult-proportion rule, spec → params |
| `poses` | Pose format, mirroring, hand shapes, IK entries, library, TOML save/load |
| `expressions` | Expression presets over VroidStudio `Fcl_*` face keys |
| `garments` | VroidStudio material-name parsing, slots/conflicts, skeleton comparison, naming |
| `paths`, `launcher`, `cli` | Paths/Blender discovery, headless job launcher, command line |

Blender modules (`wogen.bl`):

| Module | Responsibility |
|---|---|
| `character` | VRM import into the `wogen_character` collection, cleanup, `prepare()` |
| `toon` | Cel materials (per class: skin/hair/cloth/eye/face), outlines, rim, recolor rules |
| `overlay` | Brows (and optional lash lines) drawn through the bangs |
| `body` | Rest-pose retargeting for body params; garment/rig fitting; procedural face keys |
| `outfit` | Split Body into garments, hidden-skin mask, recolor/layers, library save/equip, harvest, sets, names |
| `garment_rig` | Secondary bones + spring chains + colliders carried by garments |
| `face` | Expressions and gaze |
| `pose` | Applying poses (FK + analytic two-bone IK), saving poses, grounding (with shoe lift) |
| `anim` | Keyed sequences and presets (layered-action F-curve helpers) |
| `physics` | VRM SpringBone 1.0 solver, baked to keyframes (character + garment chains) |
| `render` | Portrait camera/lights/world, turntable, clips, contact sheets |
| `post` | Compositor: bloom, chromatic aberration, grade, vignette |
| `props` | Simple props (seat) |
| `generate` | Spec + seed → finished character; palette |
| `export` | VRM/FBX export from a prepared copy |
| `jobs` | Headless job entry points mirroring the CLI |

## Generation pipeline (`generate.generate`)

1. **Resolve** the spec with the seed → `CharacterParams` (clamped; adult rule applied).
2. **Import** `assets/base/<base>.vrm` (VRM add-on) into `wogen_character`.
3. **Body retarget** (`bl/body.py`): per-bone affine transforms, then linear blend skinning
   of every mesh's rest geometry (all shape keys), then the bones are moved.
   - Lengths stretch along the joint segment; widths scale radially. Head and bust scale
     uniformly and are inherited by children, so hair follows the head.
   - The transforms are stored on the armature (`wg_body_transforms`), so garments equipped
     later fit the same body.
4. **Toon** (`bl/toon.py`): every MToon material gets a `wg_` cel twin, with outlines as an
   inverted-hull Solidify using per-material `wgo_` colors.
5. **Overlay**: a geometry-nodes copy of the brows, moved toward the camera along each view
   ray, so it draws over the bangs at the same screen position.
6. **Face keys**: procedural `wg_eye_size`, `wg_eye_height`, `wg_face_width`, `wg_chin_length`.
7. **Outfit split**: VroidStudio merges clothing into `Body` as full-body *shells* in stacked
   alpha-cut texture layers.
   - Faces transparent in their layer are pruned, and each item becomes a `Garment_*`
     object.
   - Skin under opaque cloth is masked (alpha sampled at the exact surface point).
8. **Outfit set / extra garments** from the library. On equip, each garment is fitted to the
   body, its rig bones are installed, MToon is re-enabled, and the hidden skin is
   recomputed.
9. **Palette**: hair/iris *colorize* (texture luminance remapped onto a target color, keeping
   the painted shading), brows follow the hair, and skin gets a tint.

Generated characters carry `wg_generated` (resolved spec + params) on the armature.

## Garment library

- **Harvest** (`outfit.harvest`): each `base_f01*.vrm` export is imported and split, and its
  skeleton is compared with the reference.
  - VroidStudio lifts the whole body by the shoe height, so exports differ by a pure vertical
    shift. Garments are re-seated by −dz, and shoes store `wg_lift`.
  - Duplicates are detected by a geometry+texture signature.
- **Storage**: one standalone `.blend` per garment (packed textures, no rig dependency) plus
  `index.json`, holding signatures, outfit sets, descriptive renames, slot overrides and set
  renames. Renames are re-applied on every harvest.
- **Garment rigs**: skirts/dresses carry bones the base lacks (prefixed `<garment>.`), their
  spring chains and their hip/leg colliders. Equip installs the bones, physics simulates the
  chains, and export writes them into the VRM spring data.
- **Slots**: full, top, bottom, outer, shoes, legwear, inner, accessory. Only same-slot items
  conflict; sets layer freely.

## Posing and motion

- **Pose format**: `{humanoid_bone: (x, y, z)}` degrees, relative to the T-pose, about the
  armature axes (character faces −Y, her left is +X). Converted per bone as
  `rest⁻¹ · delta · rest`, so it's independent of VroidStudio's bone rolls.
  - IK entries place hands/feet at anchors (`<bone>` posed head, or `rest:<bone>` floor spot),
    with a pole and an optional end orientation.
  - Feet are solved before hands, then grounded (plus shoe lift).
- **Animation**: `anim.sequence` keys library poses/expressions at frames (Blender 5 layered
  actions; F-curves reached through `anim_utils.action_get_channelbag_for_slot`).
- **Physics**: the VRM SpringBone 1.0 algorithm (inertia/drag, stiffness toward the
  parent-carried rest direction, gravity, sphere collisions), stepped per frame in armature
  space and baked to keys.
  - `rest_slack` lets each joint keep the collider overlap it starts with, so VroidStudio's
    T-pose colliders don't push the authored hair out when the arms are down.

## Rendering

EEVEE only for the toon look (`Shader to RGB`); Standard view transform; key sun without cast
shadows (clean anime faces) plus a cool rim sun; a world that shows the background only to
camera rays. `render.portrait` frames face/bust/full from the posed head with optional yaw.
Turntables orbit the camera on a frame-driven pivot; clips render the scene's animation to
H.264 MP4. The compositor group (`post.py`) adds bloom, chromatic aberration, grade and vignette.

## Export (`bl/export.py`)

`export_character(path)` saves the scene to `.cache/tmp/…` and runs the `export` job on that
copy. `prepare()` then works destructively on the copy:
- drops animation, overlay and outline/mask modifiers;
- bakes the `wg_*` face keys into every key block;
- deletes hidden skin and unworn garments;
- restores MToon, with recolors baked into new packed textures;
- registers garment spring chains and colliders through the VRM add-on operators.

VRM keeps MToon. FBX swaps in Principled BSDF materials and embeds the textures.

## Where MCP fits

Blender MCP (pinned community server) lets Claude run Python in the live session and take
screenshots. It's used for interactive tuning, review loops (`look`, contact sheets) and
natural-language requests mapped onto `wogen` calls. Batch work and anything that must be
reproducible runs headless. Exploration code worth keeping moves into the package.

## Conventions

- **Custom properties.** Armature: `wg_body_params`, `wg_body_transforms`, `wg_generated`.
  Garment objects: `wg_garment`, `wg_slot`, `wg_item`, `wg_lift`, `wg_rig`, `wg_recolor`.
  Face: `wg_through_hair_params`. Materials: `wg_source` (twin → MToon source).
- **Names.** `wg_*` cel twins, `wgo_*` outlines, `wgx_*` overlay materials. `Garment_<name>`
  objects. Blender's `.NNN` duplicate suffixes are stripped when parsing names.
- **Paths.** Temporary files only go under `.cache/tmp` (never the system temp); outputs go
  under `out/`.
- **Python.** Blender bundles Python 3.13, so the package stays 3.13-compatible and
  stdlib-only inside Blender (numpy is available there). The CLI runs on 3.14 in `.venv`.
