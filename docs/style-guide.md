# Style guide

Target look: **modern stylized 3D anime, close to Zenless Zone Zero (HoYoverse).** It was derived
from the images in `references/`.

> The references are third-party copyrighted screenshots. Keep `references/` out of version
> control. wo-gen is a personal project that is never distributed, so resemblance to existing
> characters is fine, and third-party models you've obtained may be imported for personal use
> (record them in `assets/LICENSES.md` as third-party).

## The balance: stylized, but with weight

Zenless Zone Zero reads as a drawing that obeys physics. The shapes and timing are
exaggerated; mass, balance and follow-through are believable. Use this table to decide any
"how far should this go" question. When a change makes something more real but less
appealing, or more stylized but weightless, it's the wrong change.

| Area | Take from the style | Keep from reality |
|---|---|---|
| Proportions | Long legs, small waist, fuller hips and thighs than life, slim arms, slightly large head | Adult build; joints where a skeleton puts them; left/right symmetry of the body, never of the pose |
| Posing | Clear silhouette, contrapposto, tilted shoulders against tilted hips, expressive hands | Weight over the supporting foot; nothing floats or balances impossibly |
| Timing | Snappy moves into held poses; anticipation before, overshoot and settle after | Feet stay planted; speed changes ease in and out; heavy parts start and stop later than light ones |
| Secondary motion | Visible, a little larger than life, readable at clip size | Driven by the body's acceleration, damped, settles in 2 to 3 swings, scales with mass |
| Soft tissue | Present everywhere it would be (bust, butt, thighs, belly), deliberately | Subtle below the bust; slim bodies barely move; never rubbery, never constant jiggle at idle |
| Shading | Two tones, clean faces, colored lines | Light direction is consistent; shadows sit where the form turns |

Rules of thumb that follow from it:

- **Exaggerate amplitude before duration.** A bigger, quicker bounce that settles fast looks
  like ZZZ. A small bounce that rings for a second looks like jelly.
- **A walk should only just show; an impact should be an event.** Tune each soft region so
  everyday motion sits well under its clamp and jumps reach it (numbers under
  [Secondary-motion targets](#secondary-motion-targets)).
- **Idle is never still, and never busy.** Breathing, blinks, a slow weight shift and a hint
  of hair drift. Physics adds nothing at idle; it only answers motion.
- **Bigger means more movement, not longer ringing.** Size raises amplitude and lowers
  frequency, and damping rises with it so settle time stays about the same.

## Shading

- **Cel shading with soft edges.** Two main tones (lit and shadow) with a narrow, slightly
  blurred boundary, not a hard binary cut.
- **Warm, saturated shadows.** Skin shadows are pink or peach, not grey. Each material gets its
  own shadow color (a ramp per material, not one global multiply).
- **Clean face shadows.** There's almost no shadow noise on the face. Use an SDF face-shadow map
  or normals transferred from a sphere/ellipsoid proxy. The nose is a small highlight or shadow
  wedge.
- **Rim light.** A thin bright fresnel band on the silhouette, tinted by the environment light.
- **Specular.** Sharp, painted-looking highlights on hair, leather, plastic and metal. Fabric is
  mostly matte.

## Outlines

- Inverted-hull silhouette outline. It's **colored per material** (a dark, saturated version of
  the base color, never pure black). Thickness varies with vertex color and with camera distance.
- Thin interior lines at creases, clothing seams and the lower eyelid. These are texture or Line
  Art lines, used sparingly.

## Eyes and face

- Large eyes with a layered iris: a dark top gradient, a bright lower-iris glow, a shaped pupil,
  and 2–3 highlights (one large and soft, smaller sharp ones).
- Thick upper lash line with a flick at the outer corner. Thin lower lash.
- **Eyebrows (and optionally eyes) render through the bangs.** This is a standard anime trick,
  done with a depth/stencil-style material setup or a separate render layer.
- Small nose and mouth. The mouth is a shape-key-driven line with an optional inner-mouth mesh.
- Optional blush (a texture overlay driven by an expression parameter) and a mole/beauty mark slot.

## Hair

- Chunky mesh clumps with tapered, pointed strand tips. Layered bangs that partly cover the eyes.
- Ahoge and stray strands as separate small pieces.
- **Two-tone and streak color**: an underlayer color, colored tips, and a gradient from the roots.
- An "angel ring" style highlight band, drawn with a UV- or tangent-driven mask, not physical
  anisotropy.
- Hair ties, clips and hard-surface accessories (headphones, mechanical ears, goggles) as modules.

## Outfits (urban techwear and streetwear)

- Layered garments: crop tops, jackets worn off-shoulder, shorts and skirts, thigh-highs, gloves,
  chokers.
- **Lots of hardware**: straps, belts, buckles, O-rings, zippers, harnesses, clips. These make good
  procedural detail modules.
- A mix of soft cloth (which gets physics) and hard-surface parts (rigid, parented to bones).
- Graphic prints and decals (text, logos, patches) on fabric. These are **our own** designs,
  applied as decal textures.

## Proportions

- Stylized adult proportions, about 6.5–7.5 heads tall. Long legs, slim waist, a head slightly
  larger than realistic.
- The generator enforces adult proportion ranges regardless of how "cute" the face preset is.
- **Body types, not independent sliders.** ZZZ's cast reads as a few clear builds (slender,
  athletic, curvy), each consistent from shoulders to calves. Sampling every slider on its
  own gives averaged, samey bodies and the odd mismatch (wide hips on thin thighs). Sliders
  that belong together should move together (see the roadmap's proportions items).
- **Shape matters more than size.** Size sliders scale a region about its bone, which
  changes how big it is but not its profile. The style's signature shapes need shape
  controls. Hips, seat and thighs have them (`seat`, `seat_round`, `seat_fold`,
  `hip_curve`, `thigh_upper`, `thigh_back`, `thigh_gap`), tuned by eye on a curvy body: a
  slightly wider pelvis, a round, projecting seat with a defined crease underneath, fuller
  upper and back thighs, and a small gap between the inner thighs. They scale with
  `hip_width` and `thigh`, so slim bodies stay slim. Bust projection and calves still need
  theirs.
- Qualitative targets, to check on a full-body front and side render (estimates from
  reference images, not measurements from the game): legs about half of total height or a
  little more; waist clearly narrower than both ribcage and hips; thighs fullest in their
  upper third; calves slim; shoulders no wider than the hips for curvy builds.

## Motion and secondary physics

Zenless Zone Zero is the model here too: secondary motion is lively but controlled, and it
sells weight. (Qualitative targets from watching the game; judge them on our clips with
side-view frame strips.)

- **Hair follows with a slight lag and reacts to impacts.** Footfalls, landings and quick
  turns send a visible bounce through the hair, from loose tips to stiffer roots. It settles
  in about half a second and never streams back unrealistically while she walks.
- **Breasts have soft, damped secondary motion.** They lag the chest a little and bounce on
  impacts (footfalls, landings, quick turns). The motion is mostly vertical with a smaller
  sideways sway, settles within 2–3 oscillations, is subtle at idle and scales with size. It
  never looks rubbery or exaggerated.
- **Butt, thighs and belly move too, much less.** A firm, quick wobble on landings and hard
  footfalls; on a walk it only just shows. It scales with the hip, thigh and waist sliders,
  and slim bodies barely move. In a walk, most of what the eye reads in the hips is the
  pelvis itself tilting and swaying, so that comes from the animation, not from jiggle.
- **Skirts and loose cloth swing and settle**; limbs push them aside rather than passing
  through.

### Animation feel

Secondary physics can only answer the motion it's given, so the keyed motion carries most of
the feel.

- **Pose to pose, with holds.** Strong key poses, fast transitions (4 to 8 frames at 24 fps),
  then a hold that keeps breathing (a "moving hold"), not a freeze.
- **Anticipation and overshoot.** A dip before a jump, a small wind-up before a wave; go a
  little past the pose and come back.
- **Overlap.** Hips lead, then chest, head, arms and hands, each a frame or two later. Both
  arms or both legs arriving on the same frame looks robotic.
- **Arcs and weight.** Hands and head travel on curves. In a walk the pelvis drops toward
  the swinging leg, shifts over the supporting foot and counter-rotates against the chest.
- **Face is animated too.** Blinks every few seconds and on head turns, eyes that lead the
  head, expression changes that overlap the body move.

### Secondary-motion targets

Numbers to tune toward, for the base body at 24 fps. Measure them with
`scripts/tissue_measure.py` ([workflows.md](workflows.md#tune-physics-and-review-motion)).
"Skin" is the visible movement at the centre of the region.

| Part | Walk | Hop / landing | Bounce | Settles in | Notes |
|---|---|---|---|---|---|
| Hair tips | sway, a few cm | clear bounce, about 10 cm | per chain | about 0.5 s | Roots stiffer than tips; no streaming back while walking. At idle a drift of about 1 cm (2 cm on long hair); skirt hems about 4 mm |
| Bust (tip of the chain) | about 1 cm | about 5 cm, under the 6 cm clamp | 2.3 Hz | 2 to 3 swings | Approved by eye. Mostly vertical, drops scaled to 70 %. Runs and jogs: no more than about 4 to 5 cm between frames (they used to whip 5 to 7 cm) |
| Butt (skin) | about 3 mm | about 9 mm | 3.2 Hz | 2 swings | Approved by eye |
| Thighs (skin) | about 3 mm | about 5 mm | 3.8 Hz | 1 to 2 swings | Approved by eye |
| Belly (skin) | under 2 mm | about 3 mm | 2.8 Hz | 1 to 2 swings | Approved by eye |

Scaling with size: slim settings land at roughly 60 % of these, curvy at 150 to 170 %.

## Lighting and post

- Strong key light plus a colored environment fill (warm/cool contrast). Bloom on highlights.
- Shallow depth of field for portraits. Light color grading. Optional slight chromatic aberration
  or grain.
- Background: stylized urban environments, or a simple gradient/graphic backdrop (like ref 1)
  for character cards.

## Engine implications

- **EEVEE is required for the toon look.** The `Shader to RGB` node (the basis of cel ramps) only
  works in EEVEE. Cycles is limited to non-toon or experimental renders.
- Post effects (bloom, grading, chromatic aberration) go in the Compositor.

## Implementation status

| Element | Status | Where |
|---|---|---|
| Two-tone cel with a soft boundary, per-material shadow colors | ✅ | `toon.PROFILES` |
| Warm skin / cool hair and cloth shadows | ✅ | `toon.PROFILES` |
| Clean face shadows | ✅ Head-space ellipsoid normals on the face skin (no cast shadows) | `face_shading` |
| Rim light tinted by the environment | 🟡 Directional; tinted from the surface color, not the environment | `toon._rim_factor` |
| Painted specular on hair | ✅ From VroidStudio textures | — |
| Colored per-material outlines | ✅ Inverted hull | `toon._add_outline` |
| Smooth silhouettes and curves | 🟡 Body: weld + one subdivision level in renders (approved by eye); garments, hair and exports still low-poly | `toon.add_smoothing` |
| Outline thickness by vertex color or distance | ⬜ Uniform per mesh | — |
| Interior lines | ⬜ Texture lines only | — |
| Layered eyes, lashes | ✅ From VroidStudio textures; iris recolor | `generate.set_palette` |
| Brows through the bangs | ✅ (eyeline optional) | `overlay` |
| Blush driven by expressions | ⬜ | — |
| Two-tone/streak hair, angel ring | 🟡 Colorize keeps painted highlights; no streak controls | `toon._recolor` |
| Hairstyles as modules | ✅ 8 VroidStudio styles, swappable, with physics | `hair` |
| Hair accessories as modules | 🟡 Possible as garments (slot `accessory`) | `outfit` |
| Urban techwear outfits | ⬜ Current library is VroidStudio items (casual, dresses, school) | `assets/garments` |
| Adult proportions | ✅ Enforced (≥ 6.6 heads) | `body.validate` |
| Body types (sliders that move together) | ⬜ Every slider is sampled on its own | `spec`, `body` |
| Shape controls (hip curve, seat, thigh taper, bust projection) | 🟡 Hips, seat and thighs tuned by eye and following size; bust projection, calves, waist profile to do | `bl/shape.py` |
| Hair follow-through | ✅ Lags, swings, bounces on footfalls and landings; stiffer roots, looser tips; hangs with the head in stills | `physics` |
| Breast secondary motion | ✅ Damped soft-tissue bounce, mostly vertical, scales with size; approved by eye. Seeded left/right variation; approved by eye. Imported models use the same solver (`mmd_import.release_bust`; awaiting review) | `softtissue`, `physics` |
| Butt, thigh and belly secondary motion | ✅ Helper bones + the same solver; approved by eye (not in exported VRMs yet) | `softtissue.REGIONS`, `tissue_rig` |
| Squash and stretch, contact (arms on bust, seat on chair, thigh on thigh) | ⬜ Tissue only shifts; nothing presses it | — |
| Skirt swing, limbs push cloth | ✅ Spring chains with limb colliders; no cloth sim between bones | `physics` |
| Wind / idle drift on hair and cloth | ✅ Slow seeded drift on all chains; approved by eye | `drift`, `physics` |
| Anticipation, overshoot, overlap in presets | 🟡 Hop and jump dip first; no overshoot or per-part offsets | `motions` |
| Pelvis drop and weight shift in the walk | 🟡 Walk approved by eye on the base (upright upper body awaiting review on imports); run: shift, drop, upright upper body (awaiting review) | `motions._gait`, `_run_step` |
| Idle life (breathing, blinks, eye darts) | ⬜ Clips hold a static pose between keys | `motions`, `anim` |
| Ground contact shadow | ⬜ Lights cast no shadows, so feet don't visibly touch the floor | `render.setup_lights` |
| Bloom, grade, chromatic aberration, vignette | ✅ | `post` |
| Depth of field, grain | ⬜ | — |
| Urban backgrounds | ⬜ Flat backdrop only | `render.setup_world` |
