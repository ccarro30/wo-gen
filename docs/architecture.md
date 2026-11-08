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
   Each value draws from its own stream seeded by (seed, key path), so adding settings to a
   spec never changes the other values a seed produces.
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
| `bvh` | BVH parser, mocap clip catalog (`assets/mocap/manifest.json`), CMU → humanoid bone map |
| `motions` | Motion presets and generators (turn, hop, spin, sway, walk, run, loops), chains, per-preset clip options |
| `expressions` | Expression presets over VroidStudio `Fcl_*` face keys |
| `garments` | VroidStudio material-name parsing, slots/conflicts, skeleton comparison, naming |
| `catalog` | What a spec can contain (from the ranges + garment index), strict `check`, TOML writer, `save_spec` |
| `paths`, `launcher`, `cli` | Paths/Blender discovery, headless job launcher, command line |

Blender modules (`wogen.bl`):

| Module | Responsibility |
|---|---|
| `character` | VRM import into the `wogen_character` collection, cleanup, `prepare()` |
| `toon` | Cel materials (per class: skin/hair/cloth/eye/face), outlines, rim, recolor rules |
| `overlay` | Brows (and optional lash lines) drawn through the bangs |
| `face_shading` | Anime face shadows: ellipsoid normals on the face skin, rotated with the head |
| `body` | Rest-pose retargeting for body params; garment/rig fitting; procedural face keys |
| `outfit` | Split Body into garments, hidden-skin mask, recolor/layers, library save/equip, harvest, sets, names |
| `hair` | Hairstyle modules: build from an export's hair, harvest, strip the base hair, equip |
| `garment_rig` | Secondary bones + spring chains + colliders carried by garments |
| `face` | Expressions and gaze |
| `pose` | Applying poses (FK + analytic two-bone IK), saving poses, grounding (with shoe lift), thumb solver |
| `clearance` | Moves forearms/hands out of skirts and dresses after posing |
| `anim` | Keys sequences (layered-action F-curve helpers), per-frame foot planting |
| `physics` | VRM SpringBone 1.0 solver, baked to keyframes (character + garment chains) |
| `render` | Portrait camera/lights/world, turntable, clips, contact sheets |
| `post` | Compositor: bloom, chromatic aberration, grade, vignette |
| `props` | Simple props (seat) with a flat-color outline (`toon.add_flat_outline`) |
| `generate` | Spec + seed → finished character; palette |
| `export` | VRM/FBX export from a prepared copy |
| `jobs` | Headless job entry points mirroring the CLI |

## Generation pipeline (`generate.generate`)

1. **Resolve** the spec with the seed → `CharacterParams` (clamped; adult rule applied).
2. **Import** `assets/base/<base>.vrm` (VRM add-on) into `wogen_character`; the add-on's
   collider collection and T-pose action are adopted into it. The previous character is
   removed first (`character.remove_character`): its objects, collections and actions are
   deleted, garment library entries dropped, orphans purged recursively, and image caches
   cleared, so long batches don't accumulate data or slow down.
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
6. **Face shading** (`bl/face_shading.py`, right after the body retarget): the face skin
   shades with the normals of an ellipsoid fitted to the face, leaned toward the face's
   forward direction, so the shadow sweeps in cleanly from the side instead of breaking up
   on the nose and lips.
   - Baked into the mesh's custom normals (what export keeps).
   - For rendering, the `wg_face_normals` geometry-nodes modifier (after the armature) sets
     them again from rest-space attributes, rotated by `wg_head_frame` (an empty on the head
     bone). Surface-relative normals would tilt with every shape key and leave patches.
   - The brows-through-hair overlay captures and restores normals around its Join Geometry,
     which would otherwise drop them.
7. **Face keys**: procedural `wg_eye_size`, `wg_eye_height`, `wg_face_width`,
   `wg_chin_length`, `wg_brow_height`, `wg_brow_tilt`, `wg_nose_size`, `wg_mouth_width`.
   Expression keys are rescaled around the eyes to match `eye_size`
   (`body.scale_expressions_to_eyes`), so blinks close fully on big eyes, also in export.
8. **Outfit split**: VroidStudio merges clothing into `Body` as full-body *shells* in stacked
   alpha-cut texture layers.
   - Faces transparent in their layer are pruned, and each item becomes a `Garment_*`
     object.
   - Skin under opaque cloth is masked (alpha sampled at the exact surface point).
9. **Outfit set / extra garments / hairstyle** from the library. On equip, each garment is
   fitted to the body, its rig bones are installed, MToon is re-enabled, and the hidden skin
   is recomputed (hair never hides skin). The first hairstyle equipped removes the base hair
   (`hair.strip_base`: meshes, Body's HairBack faces, hair spring chains, `J_Sec_Hair*`
   bones).
10. **Palette**: hair/iris *colorize* (texture luminance remapped onto a target color, keeping
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
  chains, and export writes them into the VRM spring data. The prefix is the id at harvest
  time (e.g. `hair_4.`), not the later descriptive name; ids are unique, so it doesn't matter.
- **Hairstyles** (`hair.harvest`) are garments with slot `hair`. From `base_f01` and each
  `base_f01_hair*.vrm` (same body, other hair), the `Hair###` meshes and the `HairBack` layer
  VroidStudio merges into Body are joined into one mesh. Its rig takes every `J_Sec_Hair*`
  bone, spring chain and collider. Outfit sets never include or hide hair.
- **Slots**: full, top, bottom, outer, shoes, legwear, inner, accessory. Only same-slot items
  conflict; sets layer freely.

## Posing and motion

- **Pose format**: `{humanoid_bone: (x, y, z)}` degrees, relative to the T-pose, about the
  armature axes (character faces −Y, her left is +X). Converted per bone as
  `rest⁻¹ · delta · rest`, so it's independent of VroidStudio's bone rolls.
  - IK entries place hands/feet at anchors (`<bone>` posed head, or `rest:<bone>` floor spot),
    with a pole and an optional end orientation.
  - Feet are solved before hands, then grounded (plus shoe lift).
  - **Garment clearance** (`clearance.py`, on by default in `apply_pose`): forearm/hand
    samples below the waist are tested against the posed skirts/dresses (a radial ray that
    exits the cloth = inside; or within 2 cm). Free arms rotate out about the shoulder in 2°
    steps (≤ 30°); IK hands move their target outward and re-solve (≤ 12 cm). Cloth weighted
    to the arm bones (cuffs, armholes) is ignored, and passes repeat until nothing moves.
  - **Skirt settle** (`physics.settle`, unkeyed poses only): replays the move from the
    standing rest pose into the pose over ~32 steps while garment spring chains simulate
    against full-length thigh/shin colliders (slack measured standing), so a rising thigh
    lifts the skirt. Runs before clearance, so arms clear the draped skirt. Clips bake instead.
  - **Hand shapes**: finger curls, plus solved thumbs (relaxed, peace, fist, point).
    `pose.solve_thumb(curls, over=[fingers])` searches thumb angles by forward kinematics so
    the tip rests on the curled fingers; use it for new hand shapes instead of guessing.
- **Animation**: `anim.sequence` keys library poses/expressions at frames (Blender 5 layered
  actions; F-curves reached through `anim_utils.action_get_channelbag_for_slot`).
  - **Foot planting**: after keying, foot IK is re-solved on every in-between frame. A foot
    whose target is the same in two keys stays locked (< 2 mm drift in the walk); a foot that
    moves along the floor follows an eased, lifted arc. Leg bones are keyed per frame.
  - **Presets** (`motions.py`, pure): keys built from library poses and generators. A spin
    rotates the hips bone (not the object), keyed every 90° so quaternion interpolation
    takes the intended way round; springs feel the turn. The walk alternates passing and
    contact keys with heel strike/toe-off, arm swing and hip/chest twist; the run adds a
    flight key (`ground: False`) and tucks the swing heel.
  - **Chains** (`motions.chain`, via `motions.build("a,b")`): presets offset in time with a
    gap, a trailing hold dropped; after a `travel` preset, later poses are shifted (hips and
    `rest:` foot targets) to where she stopped. Options merge (any follow, max carry/substeps).
  - **Quaternion continuity**: after keying, keys in the opposite hemisphere from the
    previous key are negated, so 360° → 0° doesn't play a reverse spin.
  - **Clip options** (`PRESET_OPTIONS`): `follow` keys a camera pivot to the hips' travel;
    `carry` moves spring chains with the hips (like a VRM spring center) so walking doesn't
    stream the hair back; `substeps` for fast spins; `loop` = cycle length. Loop presets key
    several identical cycles; after the bake, `anim.loop_range` narrows the scene to the last
    cycle and spreads each spring curve's leftover end/start difference linearly over it.
- **Physics**: the VRM SpringBone 1.0 algorithm (inertia/drag, stiffness toward the
  parent-carried rest direction, gravity, sphere collisions), stepped per frame in armature
  space and baked to keys.
  - `rest_slack` lets each joint keep the collider overlap it starts with, so VroidStudio's
    T-pose colliders don't push the authored hair out when the arms are down.
  - `limb_colliders` (default on) adds spheres along the legs, forearms and hands to every
    chain, with their slack measured on the T-pose, so hands push skirts and hair aside.
- **Mocap** (`bvh.py` pure parser + catalog; `bl/mocap.py`): CMU BVH frame 0 is a T-pose, as
  is our rest. Per mapped joint the motion is the world rotation relative to that frame,
  converted from BVH axes (Y up, facing +Z) to ours and applied over the bone's rest:
  `basis = rest⁻¹ · D_parent⁻¹ · D · rest`. Hips travel is scaled by hip-height ratio, the
  clip is turned to face the camera, a floor pass drops it so contacts land on the floor
  (5th percentile of the lowest foot), and `clearance.clear_arms` runs per frame.

## Rendering

EEVEE only for the toon look (`Shader to RGB`); Standard view transform; key sun without cast
shadows (clean anime faces) plus a cool rim sun; a world that shows the background only to
camera rays. `render.portrait` frames face/bust from the posed head; full fits the posed
bounds of every visible character mesh at the render aspect (sitting/crouching stay in
frame); optional yaw.
Turntables orbit the camera on a frame-driven pivot; clips render the scene's animation to
H.264 MP4. The compositor group (`post.py`) adds bloom, chromatic aberration, grade and vignette.

## Export (`bl/export.py`)

`export_character(path)` saves the scene to `.cache/tmp/…` and runs the `export` job on that
copy. `prepare()` then works destructively on the copy:
- drops animation, overlay, face-normal and outline/mask modifiers (the face keeps its baked
  normals);
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
