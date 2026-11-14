# Roadmap

Status as of 2026-11-10. 173 tests pass.

| Phase | Goal | Status |
|---|---|---|
| **0. Setup** | Blender, MCP, repo, version control, headless render | ✅ Done |
| **1. One good character** | Toon look, outlines, expressions, turntable | ✅ Done (anime face shadows) |
| **2. Parameterization** | Spec + seed → body/face/palette variants, adult rule | ✅ Done (11 body size + 7 shape + 8 face params) |
| **3. Modules** | Garments and hairstyles, fitted to any body | ✅ Done (17 garments, 8 hairstyles) |
| **4. Physics** | Hair, skirt and soft-tissue secondary motion | 🟡 Spring bones for hair and skirts with idle drift, soft-tissue solver (bust, butt, thighs, belly) with left/right variation, all approved by eye; no cloth sim, no lower-body motion in exports |
| **5. Poses and stills** | Pose/expression library, presets, one-command portrait | ✅ Done (19 poses, 24 expressions) |
| **6. Animation and video** | Motion library, mocap retarget, MP4 | 🟡 13 presets incl. walk/run, seamless loops, chains with transitions, foot planting, follow camera; BVH mocap (11 CMU clips) |
| **7. AI layer** | Text → spec, render-critique loop, batch | 🟡 Text → spec in chat (catalog, strict check, guide); review loop is manual in chat; no unattended command |
| **Export** | Reusable models | ✅ VRM 1.0 + FBX, round-trip verified |
| **8. Imported characters** | Officially released MMD models posed, animated and simulated by the same pipeline | 🟡 PMX import, humanoid mapping, A-pose → T-pose rest, library poses apply; presets, expressions, framing, physics to do |

## Done, by phase

**0. Setup.**
- Git with binaries in Git LFS (`.gitattributes`), pushed to GitHub.
- Blender 5.2.3 LTS, the VRM add-on and MCP for Blender 2.2.9 (pinned, with an update
  script).
- `uv` project with pytest and fake-bpy-module.
- A headless job launcher.

**1. Look.**
- Cel materials per material class (warm skin shadows, cool hair/cloth shadows, unlit
  eyes/face lines), hue-preserving hair back faces.
- Directional rim tinted from the surface color.
- Per-material colored inverted-hull outlines.
- Smooth body surface: VroidStudio's body is about 11k triangles and showed angles along the
  hips, seat and thighs. Renders weld the UV-seam splits back together and subdivide once
  after the armature (`toon.add_smoothing`); exports keep the original mesh.
- Brows through the bangs (view-ray geometry-nodes copy).
- Compositor bloom, grade and vignette.
- Anime face shadows: head-space ellipsoid normals on the face skin (no blotches on nose or
  lips; expressions and sliders can't tilt them), no cast shadows.

**2. Generation.**
- Rest-pose retargeting: lengths, widths, thickness, head and bust.
- Hip and thigh shape (B2, first part): `seat`, `seat_round`, `seat_fold`, `hip_curve`,
  `thigh_upper`, `thigh_back`, `thigh_gap` displace the fitted rest mesh (`bl/shape.py`).
  Each follows `hip_width` or `thigh` (none at the slider's minimum, the user's tuned amount
  at the curvy end), so shape stays in proportion to size; 1.0 = as tuned. Dialed in by the
  user as live shape keys on the curvy body. Garments copy the nearest skin's offset.
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
- Garment chains simulated alongside the character's.
- Legs, forearms and hands collide with hair and skirt chains (slack measured on the T-pose).
- Spring "carry" for travel (horizontal only, so footfalls and landings bounce the hair: run
  hair-tip motion went from 2 to 10.5 cm), substeps for fast motion, seamless loop closure.
- Bust: a soft-tissue solver (`softtissue`) replaces VroidStudio's bust chain in bakes. Each
  axis is a damped spring (about 2.3 Hz, damping ratio 0.23) driven by the chest's
  acceleration and posture. It is mostly vertical and soft-clamped: a slight bounce on a
  walk, a full one on jumps. Bigger busts move more but still settle promptly; smaller ones
  are firmer.
  Exported VRMs get bust springs tuned to approximate it (drag 0.15; stiffness scaled with
  the bust slider like the bake's frequency).
- Bust on runs and jogs (T3): past half its limit the bust loses energy (`limit_damping`),
  so a run near its own frequency no longer winds it up to twice the limit and whips the
  tip through each swing; `drive_limit` 22 m/s² trims one-frame spikes. The limit rose to
  62 mm so hops keep their approved peak. Frame-to-frame steps: run 73 → 47 mm, jog 52 → 38,
  hop 49 → 39; walk unchanged. Approved by eye (2026-11-10).
- Left/right variation: the two sides of each pair respond a few percent differently and
  one feels the motion 20 to 40 ms late, seeded per character (`softtissue.vary`,
  `PhysicsSettings.tissue_variation`), so they don't move as mirror images. Approved at 1.0.
- Frame-rate independence (P5): acceleration is measured over a fixed time window
  (`drive_window`, one 24 fps frame), so 30 or 60 fps drive the tissue the same.
- Idle drift (P1): a slow, seeded breeze (`wogen.drift`) on every spring chain: hair tips
  sway about 1 cm (2 cm on long hair), skirt hems about 4 mm. `PhysicsSettings.drift`.
  Approved by eye.
- Hair taper (P3): hair stiffness runs from 1.5× at the root to 0.7× at the tip
  (`hair_taper`), so long hair bends along its length.
- Butt, thighs and belly: helper bones added on the first bake (`tissue_rig`) take a smooth
  share of the hip, thigh and spine weights on the body and garments, and the same solver
  shifts them. Firmer and much subtler than the bust, scaled by `hip_width`, `thigh` and
  `waist` (slim bodies barely move). The first tuning pass was approved by eye as is (T1,
  2026-11-10); `limit_damping` stays off on these regions.

**5. Poses.**
- FK + analytic two-bone IK (arms and legs), `rest:` floor anchors, foot orientation, shoe
  lift.
- Hand shapes (solved thumbs for relaxed/peace/fist/point), automatic mirroring.
- Settle for stills: the move into the pose is replayed with skirt and hair springs and
  full-length leg colliders, so skirts drape and hair hangs from a tilted or bowed head
  (P2). The bust takes the solver's rest offset for the posture (it hangs forward in a bow).
- Garment clearance: arms and IK hands are moved out of skirts/dresses after every pose.
- Full framing fits the posed body, hair and garments (sitting/crouching stay in frame).
- Save/load round trip (< 0.1 mm).
- Props (outlined seat), camera yaw.

**6. Motion.**
- Walk rework (2026-11-11, from review: stiff body, small arm swing, little knee bend):
  arms swing about the left-right axis (`poses.swing`; Z on a lowered arm only gave ~7°)
  18° forward / 16° back with the elbow bending 10-26°, symmetric (the right arm's centre
  was off by 12°); pelvis shifts 3.2 cm over the stance foot and drops toward the swing
  leg; hip and chest twist were reversed in walk and run, now the pelvis turns with the
  leading leg and the chest counters it; knee peaks 40° → 51°, back heel peels to 20°.
  Second pass (review: still rigid, stride short, more hip sway): step 0.34 → 0.55 m
  (`WALK_STRIDE`) with a contact drop that scales with it, pelvis shift 6.4 cm and drop 6°,
  feet 3 cm in toward the midline, arms 22°/18°. Hip bob 1.4 → 2.7 cm; the harder
  footfalls doubled the walk's bust bounce (base 7 → 13 mm at the tip, Yidhari 6 → 11).
  Third pass (review: upper body followed the hip angles on Yidhari): the spine cancels
  the pelvis's tilt and turn, the chest only counter-turns ±3°; upper body within ~2° of
  upright while the hips turn ±8°. walk.mp4 approved by eye (2026-11-11).
- Run pelvis (M1, 2026-11-12): shift 1.5 cm over the supporting foot and 4° drop
  (passing: stance foot; contact: landing foot at 60 %; flight centred), turn ±6°, the
  spine cancels both (upper body within ~1-3° of upright), feet 2 cm toward the midline.
  Run tissue unchanged (bust step 36 → 37 mm).
- Upright upper body (2026-11-12, review: Yidhari's torso still slid with the hips): the
  `upright` pose entry leans the spine per rig so the neck follows 30 % of the pelvis's
  sideways shift (`bl.pose._keep_upright`; a fixed lean fit one rig, not the other).
  Neck side travel in the walk: Yidhari 9.5 → 3.3 cm, base 5.7 → 1.9 cm; pelvis 7-8 cm.
- 13 motion presets: `walk`, `run`, `spin`, `jump_for_joy`, `hop`, `wave_hello`,
  `blow_kiss`, `heart`, `bow`, `sway`, `look_around`, plus seamless `walk_loop` / `run_loop`
  (pure data in `motions.py`, tested). The run has a flight phase and tucked heel, and its
  hips travel at an even speed (they used to surge and stall each step, a 5 g jolt).
- Chains (`--preset a,b,c`) with transitions, including mocap clips (`mocap:CLIP@a-b`) with
  stepping transitions; position carries over after travel; quaternion
  keys kept in one hemisphere, so turns never unwind the long way.
- Loops: warm-up cycles plus spring-key closure, so the last cycle repeats without a seam.
- Per-frame foot planting (planted feet drift < 2 mm; steps follow lifted arcs).
- Follow camera for travel; spring "carry" so walking doesn't stream the hair back.
- Mocap: BVH retargeting (rotation deltas from the T-pose frame), floor pass on the sole
  points (follows a sloped capture floor: `mocap:walk` median float 31 → 6 mm),
  anti-aliased downsampling (each output frame averages the 120 fps source frames around
  it, `mocap.ANTIALIAS`: hips rotation shake 3.0° → 1.0°, the "vibrating" body), foot, toe
  and hand rotations smoothed further (`smooth.py`: their 15-30° flicker read as snapping
  feet; toe-point jerk spikes 55 → 11 in the dance), foot locking (skating cut from up to 44 cm to about 1 cm per clip), procedural
  fingers (open for raised/expressive gestures, loose fists when running), arms kept out
  of skirts per frame; travelling clips walk toward the camera; 11 pinned CMU clips
  (`scripts/update-mocap.ps1`, `wogen mocap`, `clip --mocap NAME`).
- FK feet planted between keys (presets no longer drift; the spin steps around).
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

**Reference model.**
- Astra Yao (Zenless Zone Zero, PMX by 观海子) imported with MMD Tools into
  `imports/astra_yao.blend` (gitignored; one
  38.6k-vertex mesh, 37 expression keys, 446 bones, 268 MMD rigid bodies. A reference for
  proportions, look and physics, never a parts donor. First measurement: about 7.6 heads tall
  against our 7.0 base (head smaller relative to the body), with the same leg-to-torso ratio
  (1.69). Clean thigh and hip measurements still need her garters, rings and stocking layers
  masked out by material.

## Known issues

| Issue | Impact | Fix direction |
|---|---|---|
| `hair_bob` (the base hair) has no HairBack cap | Scalp shows from side/back with that style (and with no `--hair`) | Re-export the bob with a base-hair cap in VroidStudio and re-harvest |
| Elbow crease at sharp bends; shorts clip in deep sits | Visible in some poses | VroidStudio weights; corrective shape keys or weight smoothing |
| No cloth sim | Kneeling / sitting on the floor: the cloth *between* skirt bones is pierced by the thighs (skirt bones themselves are kept out by `physics.settle`; arms by clearance) | Optional Blender cloth bake for stills (skirt pinned at the waist, body as collider) |
| Only light skin tones (skin is a tint over the light base texture) | Darker skin looks muddy; `check` warns | Colorize skin like hair, or VroidStudio skin texture variants |
| Walk/run presets rotate the planted foot about the ankle at heel strike | Reads as a small toe slide | Pivot the contact about the heel (backlog M2) |
| Soft-tissue helper bones are static in exported VRM/FBX | Exported models have bust springs but no butt, thigh or belly motion; export after a bake is untested | Backlog T2, E1 |
| Only the body is smoothed, and only in renders | Garments and hair keep their low-poly angles; exported VRM/FBX bodies too | Backlog L7 |
| `tennis_set_white` thigh band shows a skin-coloured rectangle on the thigh (with or without body shaping) | Visible in hips/full framing | Check the garment's layers (`render.layer_sheet`); likely a skin patch in the band's mesh |
| Every outfit but `tennis` hides the hips under a skirt | Lower-body physics is invisible in most renders | Backlog C1 |
| Between keys the body is perfectly still (no breathing or blinks; hair and cloth now drift) | Idles feel lifeless next to the reference | Backlog M3 |

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

Each step names backlog items below by id. The order puts what most changes the ZZZ feel
per hour of work first.

0. **Imported characters (current focus).** Officially released MMD models in `imports/`
   (gitignored), personal use under their release terms. The agent renders and debugs them
   like original characters, locally only (see [CLAUDE.md](../CLAUDE.md), "Imported
   characters"). They serve two goals: animating the imported characters themselves, and,
   above all, learning from their detail, physics, proportions and design to make the
   **original** characters better (ideas and measurements carry over, never assets).
   - Step 1, import (built; awaiting the user's review of renders): PMX import, humanoid map and T-pose rest are done
     (`wogen.mmd`, `bl/mmd_import.py`). The rest conversion poses the arms and bakes the
     evaluated rig (helper and twist bones included) into the new rest: ≤ 0.002 mm rest
     error and the same match to the original rig posed into the T-pose, on all models in
     `imports/`. Also done:
     - **Expressions:** every expression preset maps to the standard MMD morphs
       (`mmd.FCL_MORPHS`; regions and sides checked by where each morph moves vertices).
       Resets touch only face-category morphs, and gaze uses the humanoid map's eyes.
     - **Presets and mocap run:** the leg IK and waist-cancel (`腰キャンセル`) constraints
       are muted so the legs follow the hips. The mocap retarget follows the D-bones'
       FK sources (`mmd.follow_map`; the toes were bent about 100°).
     - **Floor contact:** the import lifts models standing into the floor (up to 46 mm)
       and measures each shoe's heel and toe from its foot-skinned vertices
       (`wg_soles`). Measured on four models: keyframed walk within −7..+6 mm of the floor
       (one model −20 mm); `mocap:dance` median 2–12 mm, lowest −1..−11 mm (base 0 / −5).

     Open:
     - Expression weights are first guesses that need the user's eye.
     - `耀嘉音`'s brows are bone morphs, which aren't applied.
     - The first renders and clips (`--mmd NAME`, `wogen mmd` lists the models) are for
       the user to review: framing, expressions, feet.
     - `wogen mmd` also lists prop packages (a mirror, a cloak, grapes); they only fail
       on import. Reading bone names from the PMX would filter them.

     Also done: framing, physics carry and face shading resolve bones through the
     humanoid map (`pose.humanoid_bone`); `--mmd NAME` on portrait, turntable and clip;
     physics runs without VRM data (no springs). Lower-body soft tissue is off on imported
     rigs until step 2.
     - **English names:** every bone, morph, material, image and object is renamed at import
       (`mmd_names`; 100 % of the names in the current packages). Poses and animation are
       identical to the untranslated import. `wogen mmd` and `--mmd` use English names.
     - The release terms are recorded in `assets/LICENSES.md`.
     - User feedback on the first clips, and what was done:
       - Dance feet snapping: the mocap foot/toe rotations flickered; now smoothed.
       - Body jerky/vibrating before the spin: the 120 → 24 fps sampling let capture
         noise through; now anti-aliased.
       - Walk: the eyes were closed throughout (the `happy` expression); now
         `smile_soft`, eyes open.
       - Hips framing cut at the knees on MMD rigs; it now centres on the hip joints.
       - Still open: rigid tails and hair (step 2); hands resting on wider thighs and a
         small arm swing; the base's dance foot still slides 0.59 m with locking on
         (Yidhari's 0.000 m).
   - Step 2, physics (in progress): the models' own rigid bodies and joints (hair, tails,
     skirts, sleeves, accessories; 250-900 bodies per model) are imported, moved with the
     T-pose conversion, renamed, built with mmd_tools (`mmd_import.build_physics`) and
     baked by `physics.bake`/`settle` (`mmd_import.simulate`). Clips get a 48-frame lead-in
     from the rest pose, so the clip moves 48 frames later (sleeve bows were stretched
     toward their T-pose places without it). Yidhari's walk bakes in about 4 s. User
     review (2026-11-11): tails and hair approved as they are. The packages' bust is a
     closed loop of 0.1-0.2 kg bodies on ~100 N·m/rad springs (about 100 Hz), which turned
     0.3° in a walk; `mmd_import.release_bust` now hands the skinned bust bone per side
     (`mmd.bust_bones`, turned bone-following before `build_rig`) to our soft-tissue solver with the base's approved tuning (walk
     6-9 mm at the bone tip, hop about 3 cm), which also removed the dependency-cycle
     warning (chest colliders sat on bones the simulation drove). Open: the user's review
     of the bust feel; lower-body tissue on imported models; the lead-in's frame shift in
     chains with transitions. Original plan:
     hair and skirt chains (convert MMD rigid bodies, or our spring
     solver), soft tissue on the D-bones that carry the skin weights.
   - Step 3, measurement: proportions of the imported models against the base and curvy
     bodies, to calibrate ranges and a ZZZ-like body type (B1).
   - Step 4, look: study the packages' toon ramps and shading for `toon.PROFILES`.
   - Step 5, design study for original characters: how the imported models build their
     detail (hair layering and card counts, clothing layers, accessories, silhouettes),
     rig it (hair, skirt and accessory chains, helper bones) and move it (MMD rigid-body
     settings as references for our springs). Write up the findings, then turn them into
     new original assets and generator features (hairstyles, outfits, physics presets).
1. **Show and ship the lower body**: C1 (an outfit that shows it), T2 (motion in exported
   VRMs). Tuning (T1, T3) and body shape for hips and thighs are done and approved.
2. **Make the motion carry the feel**: M2 (heel pivot), M3 (idle
   life), M4 (overshoot and overlap). Physics only answers the motion it's given.
3. **Body types and shape**: B1, the rest of B2 (calf, bust projection, waist front/back),
   then B3. Hips, seat and thighs now have shape sliders.
4. **Liveliness in stills and idles**: L1
   (ground shadow).
5. **Look**: L2 (skin tones), L3 (face details), L4 (rim, outline width), C2 (techwear).
6. **Engineering as you go**: E1 to E4 whenever they'd save time on the step in hand.

## Improvement backlog

From a whole-project review on 2026-11-09. Read [style-guide.md](style-guide.md) first: its
balance table says how far each item should go. Size is S (hours), M (a session or two) or L
(several sessions). "Where" is where the change starts. When an item is done, move it to
"Done, by phase" and update the style guide's status table.

### Soft tissue and physics

| Id | Improvement | Why | Where | Size |
|---|---|---|---|---|
| T2 | Spring chains for the helper bones in VRM export | Exported models have no lower-body motion (helpers are static). Helpers shift, and VRM springs only rotate, so each needs a bone whose head sits deep (near the parent joint) and whose tail is the region centre | `export.prepare`, `tissue_rig` | M |
| T4 | Squash and stretch on soft tissue | The style's bounce changes shape: stretch along the motion, squash on the rebound, volume kept. Scale the bone along the offset direction from the solver's velocity (a few percent) | `physics._Tissue.pose` | M |
| T5 | Pose-driven shape for the lower body | Real hips change shape as the leg swings (the seat flattens when the thigh comes forward, fills when it goes back). Inertia can't do that. Drive the helpers (or corrective shape keys) from the upper-leg rotation | `tissue_rig`, new pure module | M |
| T6 | Contact: arms on the bust, thigh on thigh, seat on a chair | Tissue passes through or ignores what touches it. Start with sphere colliders that push the tissue offset (as spring chains have), then a flatten-on-seat for sitting poses | `physics._Tissue`, `poses` | L |
| T8 | A separate side-hip region if review asks for it | The butt region covers the side of the hip by its falloff; a region of its own could be tuned alone | `softtissue.REGIONS` | S |
| P4 | Cloth between skirt bones | Known issue: thighs pierce the cloth between bones in floor sits. Blender's cloth sim baked for stills only, pinned at the waist | new `bl/cloth.py` | L |

### Motion and animation

| Id | Improvement | Why | Where | Size |
|---|---|---|---|---|
| M2 | Heel-pivot contact | Known issue: the planted foot rotates about the ankle at heel strike, which reads as a toe slide | `motions._gait`, `anim._plant_pass` | M |
| M3 | Idle life layered over any clip: breathing, blinks, small eye darts, slow weight shift | Between keys she's a statue. This is the cheapest big gain in feel. Build it as a pure generator of extra keys (seeded), applied after the preset | new pure module + `anim` | M |
| M4 | Overshoot, settle and overlap in presets | Poses are reached by plain interpolation, all bones on the same frame. Add a helper that offsets chest, head and arms by 1 to 3 frames and inserts a small overshoot key | `motions`, `anim.sequence` | M |
| M5 | More varied source motion | 11 CMU clips, all realistic and plain. Stylized sets and video-to-motion are listed in [tooling.md](tooling.md#candidate-tools) | `assets/mocap/manifest.json`, `bvh` | M |
| M6 | Camera moves | Every clip uses a fixed or follow camera. A slow push-in, a small orbit and an eased cut between framings would lift every clip | `render.clip` | S |
| M7 | Render at 30 or 60 fps | 24 fps suits holds but makes fast secondary motion steppy. Soft tissue is ready (P5 done); spring chains still step per frame | `jobs._clip` | S |
| M8 | Expression timing in presets | Expressions switch on body keys. Lead or trail them by a few frames, and blink on head turns (part of M3) | `motions`, `anim.sequence` | S |

### Body and proportions

| Id | Improvement | Why | Where | Size |
|---|---|---|---|---|
| B1 | Body types: a `[body] type` (slender, athletic, curvy, ...) that moves related sliders together, with small per-slider variation on top | Independent sampling gives averaged bodies and mismatches. See the style guide | `spec`, `body.from_spec`, `specs/default.toml` | S |
| B2 | Shape controls, the rest: calf, bust projection separate from width, waist front/back (hips, seat and thighs are done, see `bl/shape.py`) | Radial scaling about a bone changes size, not profile. The ellipsoid falloff in `softtissue.Region` already defines the regions; displacing the rest mesh along it (before the bones move) gives shape sliders that garments can follow the same way | `bl/body.py`, `softtissue.falloff` | M |
| B3 | Wider ranges once B2 exists | `hip_width` tops out at 1.10 and `thigh` at 1.12, which is modest next to the style's curvier builds. Scaling further without shape control looks inflated, so do B2 first | `body.BODY_RANGES` | S |
| B4 | Corrective smoothing at joints | Known issue: elbow crease, shorts clipping in deep sits. Try a Corrective Smooth modifier after the armature (render only), or bone-driven corrective keys | `character`, `toon` (modifier order) | S |
| B5 | A second base body | One VroidStudio body bounds everything. The harvest and fit pipeline is per-base already (`base` in specs) | `assets/base`, `outfit.harvest` | L |

### Look

| Id | Improvement | Why | Where | Size |
|---|---|---|---|---|
| L1 | Ground contact shadow | Lights cast no shadows (kept off for clean faces), so feet never visibly meet a floor. A soft blob or a shadow-catcher plane that only receives from the body would ground her | `render.setup_lights`, `render.setup_world` | S |
| L2 | Skin tones | Known issue: darker skin is a tint over a light texture and goes muddy. Colorize as hair does, with its own shadow ramp | `generate.set_palette`, `toon.PROFILES` | M |
| L3 | Face details: nose shadow wedge, lip highlight, expression blush | Style-guide items still open | `face_shading`, `face` | M |
| L4 | Rim tinted by the environment; outline width by distance and vertex color | Style-guide items still open. Outline width is uniform per mesh, so one that suits a face close-up doesn't suit a full-body shot | `toon._rim_factor`, `toon._add_outline` | M |
| L5 | Hair shadow on the forehead | A stylized offset shadow under the bangs is part of the look, and cast shadows are off | `toon`, `overlay` | M |
| L6 | Depth of field and backgrounds | Flat backdrop only | `render`, `post` | M |
| L7 | Smoothing beyond the body | The body renders with weld + subdivision (`toon.add_smoothing`); garments and hair still show angles, and exports keep the low-poly body. Garments need checks first (layered cloth and hems shrink under subdivision); exports would need the mesh itself subdivided | `toon.SMOOTH_MESHES`, `export.prepare` | M |

### Content

| Id | Improvement | Why | Where | Size |
|---|---|---|---|---|
| C1 | Outfits that show the body: shorts, leggings, a swimsuit, thigh-highs | Only the tennis set shows the hips; every other outfit hides them under a skirt, so lower-body work is invisible in normal renders | VroidStudio, then [workflows.md](workflows.md#add-garments-to-the-library) | S (user) |
| C2 | Urban techwear | The style guide's outfit target isn't in the library at all | VroidStudio textures, accessories as garments | L |
| C3 | Fix the `hair_bob` cap | Known issue | VroidStudio re-export | S (user) |

### Engineering

| Id | Improvement | Why | Where | Size |
|---|---|---|---|---|
| E1 | Blender tests for the tissue rig and for export after a bake | Three Blender tests cover the whole `bl` package. The helper bones are untested there: assert that weights still sum to what they did, that the rest mesh doesn't move, and that a baked character exports | `tests/test_render_test.py` | S |
| E2 | Physics numbers as a regression test | Tuning is by eye and nothing stops a later change from undoing it. Assert `tissue_measure` peaks for walk and hop stay inside a band around the approved values | `scripts/tissue_measure.py`, tests | S |
| E3 | Fold the tuning scripts into the CLI | `scripts/tissue_measure.py` and `scripts/frame_strip.py` run through a long Blender command line. `wogen measure` and `wogen strip` jobs would match the other commands | `bl/jobs.py`, `cli.py` | S |
| E4 | Side-by-side comparison clips | Tuning rounds compare old and new from memory. Blender's sequencer can tile two rendered clips with no extra tool | new job | S |
| E5 | A linter | `.gitignore` expects ruff but it isn't installed; nothing checks style or unused code. Needs an install (ask first) | `pyproject.toml` | S |
| E6 | Cache generated characters | Every clip regenerates the character (about 14 s). Saving the generated `.blend` keyed by spec + seed would make tuning rounds faster | `jobs._prepare` | M |

Optional, deferred: a `wogen describe "..."` command that does text → spec unattended via the
Claude API (needs an API key and the `anthropic` package). Chat covers it for now; see
[text-to-spec.md](text-to-spec.md).
