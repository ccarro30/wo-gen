# Style guide

Target look: **modern stylized 3D anime, close to Zenless Zone Zero (HoYoverse).** It was derived
from the images in `references/`.

> The references are third-party copyrighted screenshots. Keep `references/` out of version
> control. wo-gen is a personal project that is never distributed, so resemblance to existing
> characters is fine, and third-party models you've obtained may be imported for personal use
> (record them in `assets/LICENSES.md` as third-party).

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
| Bloom, grade, chromatic aberration, vignette | ✅ | `post` |
| Depth of field, grain | ⬜ | — |
| Urban backgrounds | ⬜ Flat backdrop only | `render.setup_world` |
