# Roadmap

Status as of 2026-11-08. 140 tests pass.

| Phase | Goal | Status |
|---|---|---|
| **0. Setup** | Blender, MCP, repo, version control, headless render | ✅ Done |
| **1. One good character** | Toon look, outlines, expressions, turntable | ✅ Done (anime face shadows) |
| **2. Parameterization** | Spec + seed → body/face/palette variants, adult rule | ✅ Done (11 body + 8 face params) |
| **3. Modules** | Garments and hairstyles, fitted to any body | ✅ Done (17 garments, 8 hairstyles) |
| **4. Physics** | Hair, skirt and soft-tissue secondary motion | ✅ Spring bones done; no cloth sim |
| **5. Poses and stills** | Pose/expression library, presets, one-command portrait | ✅ Done (19 poses, 22 expressions) |
| **6. Animation and video** | Motion library, mocap retarget, MP4 | 🟡 13 presets incl. walk/run, seamless loops, chains with transitions, foot planting, follow camera; BVH mocap (11 CMU clips) |
| **7. AI layer** | Text → spec, render-critique loop, batch | 🟡 Text → spec in chat (catalog, strict check, guide); review loop is manual in chat; no unattended command |
| **Export** | Reusable models | ✅ VRM 1.0 + FBX, round-trip verified |

## Done, by phase

**0. Setup.**
- Git with binaries in Git LFS (`.gitattributes`), pushed to GitHub.
- Blender 5.2.3 LTS, the VRM add-on and MCP for Blender 2.2.7 (pinned, with an update
  script).
- `uv` project with pytest and fake-bpy-module.
- A headless job launcher.

**1. Look.**
- Cel materials per material class (warm skin shadows, cool hair/cloth shadows, unlit
  eyes/face lines), hue-preserving hair back faces.
- Directional rim tinted from the surface color.
- Per-material colored inverted-hull outlines.
- Brows through the bangs (view-ray geometry-nodes copy).
- Compositor bloom, grade and vignette.
- Anime face shadows: head-space ellipsoid normals on the face skin (no blotches on nose or
  lips; expressions and sliders can't tilt them), no cast shadows.

**2. Generation.**
- Rest-pose retargeting: lengths, widths, thickness, head and bust.
- Procedural face keys: eyes (size, height), face width, chin, brows (height, tilt), nose
  size, mouth width. Expressions rescale with eye size, so blinks close on big eyes.
- Palette colorize (hair, irises, brows) and skin tint.
- Adult rule: ≥ 6.6 heads, with `head_scale` clamped in closed form; tested across 40 seeds.
- `generate`/`variants` commands; about 14 s per character, flat across long batches (each
  regeneration frees the previous character's data).

**3. Garments.**
- Split VroidStudio's merged body into garments (alpha-pruned shells) with an exact
  hidden-skin mask.
- Harvesting from multiple exports: heel-shift re-seating, duplicate signatures.
- Garment rigs (skirt bones, springs, colliders).
- Fitting to generated bodies.
- Outfit sets, mix-and-match, per-layer recolor, descriptive names and slots.
- Hairstyle library (8 styles): hair meshes, HairBack cap and hair spring chains as swappable
  modules that replace the base hair; spec `[hair] style`, `--hair`, `hair-sheet`.

**4. Physics.**
- Our own VRM SpringBone 1.0 solver, baked to keys.
- Rest slack against T-pose colliders.
- Calmer bust default.
- Garment chains simulated alongside the character's.

**5. Poses.**
- FK + analytic two-bone IK (arms and legs), `rest:` floor anchors, foot orientation, shoe
  lift.
- Hand shapes (solved thumbs for relaxed/peace/fist/point), automatic mirroring.
- Skirt settle for stills: the move into the pose is replayed with skirt springs and
  full-length leg colliders, so skirts drape instead of keeping their standing shape.
- Garment clearance: arms and IK hands are moved out of skirts/dresses after every pose.
- Full framing fits the posed body, hair and garments (sitting/crouching stay in frame).
- Save/load round trip (< 0.1 mm).
- Props (outlined seat), camera yaw.

**6. Motion.**
- 13 motion presets: `walk`, `run`, `spin`, `jump_for_joy`, `hop`, `wave_hello`,
  `blow_kiss`, `heart`, `bow`, `sway`, `look_around`, plus seamless `walk_loop` / `run_loop`
  (pure data in `motions.py`, tested). The run has a flight phase and tucked heel.
- Chains (`--preset a,b,c`) with transitions; position carries over after travel; quaternion
  keys kept in one hemisphere, so turns never unwind the long way.
- Loops: warm-up cycles plus spring-key closure, so the last cycle repeats without a seam.
- Per-frame foot planting (planted feet drift < 2 mm; steps follow lifted arcs).
- Follow camera for travel; spring "carry" so walking doesn't stream the hair back.
- Mocap: BVH retargeting (rotation deltas from the T-pose frame), floor pass, arms kept out
  of skirts per frame; 11 pinned CMU clips (`scripts/update-mocap.ps1`, `wogen mocap`,
  `clip --mocap NAME`).
- Baked physics; legs, forearms and hands collide with hair and skirt chains.
- MP4 clips and turntables of the base or any generated character (`--spec/--seed`).

**7. AI layer.**
- Text → spec in chat: `wogen catalog` (what exists), `wogen check` (strict validation),
  `catalog.save_spec` (TOML writer), and a vocabulary guide ([text-to-spec.md](text-to-spec.md)).
  Example: `specs/example_elegant.toml`.

**Export.**
- Done on a copy of the scene; `wogen export` exports any saved `.blend`.
- Bakes in the face keys and recolors (into textures), removes hidden skin, adds garment
  springs to the VRM.
- VRM: MToon, 25 spring chains and 28 colliders on re-import, and the skirt swings.
- FBX: skinned, with 60 embedded textures.

## Known issues

| Issue | Impact | Fix direction |
|---|---|---|
| `hair_bob` (the base hair) has no HairBack cap | Scalp shows from side/back with that style (and with no `--hair`) | Re-export the bob with a base-hair cap in VroidStudio and re-harvest |
| Elbow crease at sharp bends; shorts clip in deep sits | Visible in some poses | VroidStudio weights; corrective shape keys or weight smoothing |
| No cloth sim | Kneeling / sitting on the floor: the cloth *between* skirt bones is pierced by the thighs (skirt bones themselves are kept out by `physics.settle`; arms by clearance) | Optional Blender cloth bake for stills (skirt pinned at the waist, body as collider) |
| Only light skin tones (skin is a tint over the light base texture) | Darker skin looks muddy; `check` warns | Colorize skin like hair, or VroidStudio skin texture variants |

## Decisions

| Topic | Decision |
|---|---|
| Base mesh | VroidStudio base (`base_f01`), varied by our own retargeting and face keys |
| Hardware | AMD RX 9070 XT 16 GB (HIP). EEVEE for all toon output |
| Style | ZZZ-like stylized cel shading ([style-guide.md](style-guide.md)) |
| Outputs | PNG, MP4, `.blend`, VRM 1.0, FBX |
| Budget | Free tools only; paid ones case by case |
| Interaction | Chat through MCP first; headless CLI mirrors the same functions |
| Specs | TOML (stdlib in both Pythons), not YAML |
| Physics | Own spring-bone solver baked to keys (no Wiggle 2) |

AMD caveat: many AI tools (video-to-mocap, image-to-3D) assume NVIDIA CUDA. Check ROCm,
DirectML or CPU support before adopting one.

## Next steps (recommended order)

1. **Motion realism.** Foot locking for mocap (feet slide a little where her proportions differ
   from the actor's), finger poses during mocap, blending mocap into presets/chains, and
   video-to-motion (CPU-only tools, given AMD).
2. **Skin tones.** Support darker skin (colorize or texture variants instead of a tint).
3. **Face, further.** A nose shadow wedge and lip highlight (style guide); expression-specific
   blush.

Optional, deferred: a `wogen describe "..."` command that does text → spec unattended via the
Claude API (needs an API key and the `anthropic` package). Chat covers it for now; see
[text-to-spec.md](text-to-spec.md).
