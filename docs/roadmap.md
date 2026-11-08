# Roadmap

Status as of 2026-11-07. 106 tests pass.

| Phase | Goal | Status |
|---|---|---|
| **0. Setup** | Blender, MCP, repo, version control, headless render | ✅ Done |
| **1. One good character** | Toon look, outlines, expressions, turntable | ✅ Done, except proper face shadows |
| **2. Parameterization** | Spec + seed → body/face/palette variants, adult rule | ✅ Done (11 body + 4 face params) |
| **3. Modules** | Garments and hairstyles, fitted to any body | ✅ Done (17 garments, 8 hairstyles) |
| **4. Physics** | Hair, skirt and soft-tissue secondary motion | ✅ Spring bones done; no cloth sim |
| **5. Poses and stills** | Pose/expression library, presets, one-command portrait | ✅ Done (14 poses, 22 expressions) |
| **6. Animation and video** | Motion library, mocap retarget, MP4 | 🟡 Keyed presets + MP4; no walk cycle or mocap |
| **7. AI layer** | Text → spec, render-critique loop, batch | ⬜ Not started (chat + MCP covers some of it manually) |
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
- Clean faces via no cast shadows plus a softer face ramp.

**2. Generation.**
- Rest-pose retargeting: lengths, widths, thickness, head and bust.
- Procedural face keys.
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
- Hand shapes, automatic mirroring.
- Save/load round trip (< 0.1 mm).
- Props (outlined seat), camera yaw.

**6. Motion.**
- Keyed sequences (`look_around`, `hop`, `wave_hello`) with expressions.
- Baked physics.
- MP4 clips and turntables.

**Export.**
- Done on a copy of the scene; `wogen export` exports any saved `.blend`.
- Bakes in the face keys and recolors (into textures), removes hidden skin, adds garment
  springs to the VRM.
- VRM: MToon, 25 spring chains and 28 colliders on re-import, and the skirt swings.
- FBX: skinned, with 60 embedded textures.

## Known issues

| Issue | Impact | Fix direction |
|---|---|---|
| Clips/turntables only use the base character | Can't animate a generated seed from the CLI | Add `--spec/--seed` to `clip`/`turntable` (or reuse `generate` setup) |
| Face shadows use a wide-band workaround | Faces read flatter than the references at strong side light | Normal transfer from a sphere proxy, or an SDF face-shadow map |
| `hair_bob` (the base hair) has no HairBack cap | Scalp shows from side/back with that style (and with no `--hair`) | Re-export the bob with a base-hair cap in VroidStudio and re-harvest |
| Big `eye_size` + blink/expression keys | Eyelids may not fully close | Scale expression deltas near the eyes with the eye key |
| Elbow crease at sharp bends; shorts clip in deep sits | Visible in some poses | VroidStudio weights; corrective shape keys or weight smoothing |
| Interpolating between keyed poses can lift a planted foot briefly | Small foot slide in clips | Key IK targets, or re-run foot IK per frame before baking |
| No cloth sim, capsule colliders or chain-to-chain collision | Long skirts can intersect | Optional cloth bake for hero shots |
| VroidStudio terms not checked for redistribution | Matters before sharing models or parts publicly | Read the current terms; record the result in [assets/LICENSES.md](../assets/LICENSES.md) |

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

1. **Generated characters in motion.** `clip`/`turntable --spec --seed`: one generated
   character, one MP4. Small change.
2. **Text → spec (phase 7).** Claude writes a validated spec from a description ("tall,
   pink-haired, school uniform, shy") and renders it. Mostly prompt + schema work on top of
   `body.from_spec`.
3. **Face quality.** SDF/normal-transfer face shadows, more face sliders (brows, nose, mouth),
   and eye-size-aware expressions.
4. **Motion depth.** A walk cycle and more presets, foot-plant stabilization, and optionally
   BVH mocap retargeting (CPU-only tools, given AMD).
