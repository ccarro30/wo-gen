# Implementation options

The original option analysis from project start. Each section ends with the
**recommendation** made then and the **outcome**, meaning what was actually built. For how
things work now, see [architecture.md](architecture.md).

## 1. Character generation

| Option | How it works | Pros | Cons |
|---|---|---|---|
| **A. Parametric base mesh** | One anime base mesh with clean topology. Many shape keys (face/body sliders), modular hair, outfits and accessories. The generator samples parameters. | Best quality and control. Rigs and deforms reliably. Deterministic. | Large up-front asset work. Variety is limited by the library. |
| **B. VRoid Studio → VRM import** | Design characters in VRoid (free) and import them with the VRM add-on. | Very fast start. Anime look out of the box. Rig and spring bones included. | VRoid has no API, so it's manual. The look is generic. Limited mesh detail. |
| **C. AI image/text-to-3D** | Hunyuan3D, TRELLIS, Rodin, Meshy, Tripo, etc. | Unlimited variety, fast. | Messy topology, no rig, poor anime faces, bad deformation. Needs retopology. |
| **D. Fully procedural** | Geometry nodes or bmesh build the body from scratch. | No external assets needed. | Very hard to reach good quality. |

**Recommendation: A, bootstrapped with B.** Use a VRoid export (or a licensed base mesh) as a
starting topology and rig, then grow our own shape-key and module library on top. Keep C as an
optional path for props and accessories only.

**Outcome:** B as the base, plus A-style variation. Instead of shape keys we retarget the rest
pose (VroidStudio exports have no body shape keys), which also fits garments automatically.
Garments are a library harvested from VroidStudio exports. C isn't used.

## 2. Hair

- **Hair cards / mesh strands**: modeled clumps with toon shading and anisotropic highlight
  textures. The standard anime look, cheap to render, and works well with spring bones.
- **Curves hair (geometry nodes)**: finer detail and procedural styling, but it reads as less
  "anime" and costs more to simulate.

**Recommendation:** mesh hair modules, with optional curve-based flyaway strands for close-ups.

**Outcome:** VroidStudio mesh hair as a library of 8 swappable hairstyles (harvested from
exports, with their spring chains), recolored by colorize. No curve strands.

## 3. Shading and look

- **EEVEE toon pipeline**: Shader to RGB → color ramp (cel bands), plus rim and specular masks.
  Fast. It's the main renderer for stills and video.
- **Outlines**: inverted hull (Solidify, flipped normals) for the character, and Line Art /
  Grease Pencil for interior lines. Freestyle is an alternative under Cycles.
- **Face shadows**: custom normals (transferred from a sphere proxy) or an SDF face-shadow
  texture for clean anime face lighting.
- **MToon (VRM)**: keeps the look compatible if we export VRM.
- **Cycles**: for "semi-realistic anime" renders with soft GI. Slower.

**Recommendation:** EEVEE plus our own toon node group, with inverted-hull outline and face
normal editing. MToon-compatible parameters where that's cheap.

**Outcome:** As recommended. Face shadows use ellipsoid normals (computed, not transferred
from a proxy), set in head space by geometry nodes so shape keys can't tilt them.
MToon stays as the source material, and export restores it.

## 4. Rigging and face

- **Skeleton**: Rigify (bundled, free, good controls) or a custom armature with **VRM humanoid
  bone names**, which keeps VRM/Unity/VTuber export and mocap retargeting easy. Auto-Rig Pro
  is a paid alternative.
- **Face**: shape keys for expressions. Aim for the VRM preset expressions plus a subset of the
  ARKit 52 blendshapes to make face-capture input possible. Eye-bone tracking for gaze.

**Recommendation:** a VRM-compatible deform skeleton with a Rigify-style control layer for
posing. Shape-key-driven face.

**Outcome:** VroidStudio's VRM skeleton with no control rig. Poses are data
(`wogen/poses.py`) applied with our own FK plus analytic IK. The face uses VroidStudio's 58
expression keys plus 4 procedural `wg_*` keys.

## 5. Physics (secondary motion)

| Option | Use for | Notes |
|---|---|---|
| **Spring bones** (Wiggle 2 add-on, VRM spring bones, or our own driver/handler) | Hair, ribbons, skirts, soft tissue | Real-time, stable, anime-standard. Our own implementation keeps it scriptable and headless-friendly. |
| **Cloth sim** | Skirts, loose clothing, capes | Best realism. Slow, needs baking, collision tuning. |
| **Soft body / shape-key jiggle** | Soft tissue | Subtle results usually need hand tuning. |
| **Rigid-body chains** | Accessories | Niche. |

**Recommendation:** spring bones by default for everything, with an optional cloth-sim bake for
hero shots. ⚠ Check that the Wiggle 2 add-on is maintained on Blender 5.x. If it isn't, write
our own (a small verlet solver on a frame-change handler, baked to keyframes).

**Outcome:** our own solver implementing VRM SpringBone 1.0 from VroidStudio's data, stepped
per frame and baked to keys. Garment chains are carried with the garments; legs, forearms
and hands collide with every chain. No cloth sim yet. Soft tissue (bust) is still a stiff spring
chain; a dedicated damped-spring solver is planned (roadmap: body physics).

## 6. Poses and expressions

- **Pose assets** in Blender's Asset Browser: a curated library (idle, shy, peace sign, sitting, …).
- **Procedural variation**: per-bone noise and offsets, head tilt, gaze target, weight shift.
- **IK helpers**: foot planting, hand-to-target (face, hip, prop).
- **Natural-language posing via MCP**: Claude maps a request to a library pose plus tweaks.

**Outcome:** a data library (19 poses) instead of Asset Browser poses, with IK to body
landmarks and floor anchors. Custom poses are saved as TOML. Procedural noise isn't done.

## 7. Animation

- **Action library**: hand-keyed loops (idle, walk, wave, turn, dance snippets), combined
  with the NLA editor.
- **Mocap retargeting**: BVH/FBX (CMU, Mixamo, Rokoko) onto the VRM skeleton, using the Rokoko
  retarget add-on or our own bone-map script.
- **Video-to-motion AI** (⚠ evaluate later): monocular-video pose estimators that output BVH.
  This is the fastest way to get custom motion.

**Outcome so far:** keyed sequences of library poses and generators (13 presets including
walk, run and spin), per-frame foot planting, chains with transitions and seamless loops. No
NLA yet. Mocap: our own BVH retargeter (no Rokoko add-on), with pinned CMU clips.

## 8. Rendering and output

- Camera and lighting presets (portrait, full body, turntable, dramatic rim).
- EEVEE for iteration and most final output. Cycles is optional.
- Stills: PNG/EXR. Video: image sequence → MP4 (H.264/H.265) through Blender's built-in FFmpeg
  output, or external ffmpeg for encoding control.
- A turntable render is the standard QA output for every generated character.

**Outcome:** as recommended. EEVEE only, PNG plus H.264 MP4 written by Blender directly, and
contact sheets as the main QA tool. Turntables and clips work for any generated character.

## 9. AI assistance (optional layer)

- **Text → spec**: Claude turns "cheerful pink-haired girl in a summer dress" into a valid
  `CharacterSpec`. This is cheap and high-value.
- **Visual critique loop**: render → Claude reviews the image → adjusts parameters (through MCP).
- **AI texture/detail**: eye and pattern textures from an image model. Generated textures are
  stored as assets so builds stay reproducible.

**Outcome so far:** the chat-driven visual review loop is in daily use (MCP `look` plus contact
sheets). Text → spec works in chat (catalog + strict check + vocabulary guide); an
unattended API-based command is deferred.

## 10. Languages

| Layer | Language | Why |
|---|---|---|
| Generator core | **Python (`bpy`)** inside Blender | The only first-class Blender API |
| CLI / orchestration | Python 3 via **uv** | Same language. Launches Blender as a subprocess |
| Specs / presets | ~~YAML~~ **TOML**, plus dataclasses (`wogen/body.py`) | `tomllib` is stdlib in both Pythons; no dependencies |
| Shaders | Blender node groups (built from Python or stored in an asset `.blend`) | Native |
| Optional UI | Blender N-panel add-on first. Web UI (FastAPI + simple frontend) later if needed | Least new tech first. **Outcome:** chat through MCP is the UI; no panel yet |

Note: Blender ships its **own bundled Python**. The `wogen` package that runs inside Blender
can only use the standard library and whatever we vendor or install into Blender's Python.
Keep that package dependency-light, and put heavier dependencies in the outer CLI.
