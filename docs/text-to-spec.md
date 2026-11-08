# Text to spec

Turning a plain description ("tall, cool, long black hair, red dress") into a character spec
happens **in chat**. Claude translates the description using this guide, checks the result,
renders previews, and saves it once you're happy. Nothing here needs an API key.

## Process

1. **Look up what exists.** `uv run wogen catalog` prints the body and face sliders with their
   ranges, the hairstyles, outfit sets and garments (by slot). Only those names are valid.
2. **Translate** the description with the vocabulary below into a spec dict (or TOML).
   - Fixed values for what the description pins down. Ranges or `{ choice = [...] }` for
     what it leaves open, so each seed gives a different take on the same character.
   - Keep the original words in `description = "..."`.
3. **Check** it: `uv run wogen check specs/x.toml`, or `catalog.check(spec)` from Python.
   Fix every error. Warnings explain side effects (e.g. the adult rule shrinking the head,
   or two skirts worn together).
4. **Preview** a few seeds: `uv run wogen variants --spec specs/x.toml --seeds 1-4`.
   Adjust and repeat.
5. **Save**: `catalog.save_spec(spec, "name")` writes `specs/name.toml` (it refuses specs with
   errors and won't overwrite without `overwrite=True`).
6. **Use it** anywhere: `generate --spec specs/name.toml --seed N`, `clip --spec ... --seed N`,
   `--export out\name.vrm`.

Things a spec can't express are render-time options. Pick them to match the description
when rendering: mood → `--expression`, attitude → `--pose`, motion → `clip --preset`.

## Vocabulary

Body values are multipliers around 1.0; face values run from -1 to 1. The ranges below stay
inside the allowed limits (`wogen catalog`). Combine the rows that apply. When two rows
disagree on a key, use the more specific word.

### Height and proportions

| Words | Values |
|---|---|
| petite, small | `leg_length` 0.95–0.98, `torso_length` 0.96–0.99, `arm_length` 0.97 |
| average | leave unset, or `leg_length` 0.99–1.03 |
| tall | `leg_length` 1.05–1.10, `torso_length` 1.01–1.04, `neck_length` 1.03–1.08 |
| long-legged, model-like | `leg_length` 1.07–1.10, `head_scale` 0.94–0.97 |
| mature, elegant (proportions) | `head_scale` 0.93–0.97, `neck_length` 1.04–1.10 |
| cute, youthful styling | `head_scale` 1.00–1.04 (the adult rule still keeps ≥ 6.6 heads) |

### Build

| Words | Values |
|---|---|
| slender, slim, delicate | `waist` 0.90–0.94, `thigh` 0.92–0.96, `arm_thickness` 0.92–0.95, `hip_width` 0.95–0.98 |
| athletic, fit, sporty | `shoulder_width` 1.03–1.06, `waist` 0.93–0.96, `thigh` 1.02–1.06, `arm_thickness` 1.00–1.04 |
| curvy, voluptuous | `bust` 1.15–1.30, `hip_width` 1.05–1.10, `thigh` 1.05–1.10, `waist` 0.90–0.95 |
| soft, plush | `waist` 1.00–1.05, `thigh` 1.06–1.12, `arm_thickness` 1.03–1.08 |
| broad-shouldered | `shoulder_width` 1.05–1.08 |
| narrow-shouldered | `shoulder_width` 0.94–0.97 |
| flat-chested, small bust | `bust` 0.80–0.90 |
| large bust | `bust` 1.15–1.30 |

### Face

| Words | Values |
|---|---|
| cute, doll-like, big-eyed | `eye_size` 0.4–0.8, `chin_length` -0.4–-0.1, `face_width` 0.0–0.3, `nose_size` -0.6–-0.2 |
| mature, elegant, cool | `eye_size` -0.4–0.0, `chin_length` 0.2–0.5, `face_width` -0.4–-0.1, `brow_tilt` 0.1–0.3 |
| sharp, fierce, sly | `face_width` -0.5–-0.2, `chin_length` 0.3–0.5, `eye_height` 0.1–0.3, `brow_tilt` 0.4–0.8, `brow_height` -0.5–-0.2 |
| round, soft, gentle | `face_width` 0.3–0.6, `chin_length` -0.3–0.0, `brow_tilt` -0.6–-0.2 |
| surprised-looking, open, innocent | `brow_height` 0.4–0.8 |
| worried, droopy brows | `brow_tilt` -0.8–-0.4 |
| button nose, tiny nose | `nose_size` -0.8–-0.4 |
| small mouth | `mouth_width` -0.6–-0.2 |
| wide smile, big mouth | `mouth_width` 0.3–0.7 |

### Colors

Hair and eye colors recolor the painted textures, keeping their shading. Skin is a gentle
tint over the base texture.

| Hair / eyes | Hex | | Hair / eyes | Hex |
|---|---|---|---|---|
| black | `#1d1b26` | | pink | `#f4b6c2` |
| dark brown | `#3b2a2a` | | hot pink, magenta | `#ff5fa0` |
| brown | `#6b4a3a` | | red, crimson | `#c0392b` |
| chestnut, auburn | `#8a4b2f` | | ginger, orange | `#ff6a4d` |
| blonde | `#e8c87a` | | purple | `#9b6bd6` |
| honey, dirty blonde | `#c9a46b` | | lavender | `#b9a3e3` |
| platinum | `#e8e4f2` | | navy, blue | `#2f4f9a` |
| silver, grey | `#c8c8d8` | | sky blue | `#6fb3ff` |
| white | `#f2f0f5` | | teal | `#2a9d8f` |
| amber, gold eyes | `#e0a23a` | | green | `#3fbf7f` |

| Skin | Hex |
|---|---|
| fair, porcelain | `#ffffff` |
| light, warm | `#fff4ee` |
| warm, peach | `#f6e2d6` |
| light tan | `#f0d8c8` |

⚠ Darker skin tones aren't supported yet: the tint only multiplies the light base texture,
and dark tints look muddy (`check` warns). See the roadmap known issues.

### Hair

| Words | `hair.style` |
|---|---|
| bob, short and neat | `hair_bob` |
| long, straight, flowing | `hair_long_straight` |
| hime cut, blunt bangs, princess | `hair_hime_long` |
| twin tails, pigtails | `hair_twintails` |
| ponytail, long ponytail | `hair_ponytail_long` |
| side ponytail, casual short | `hair_side_ponytail` |
| buns, odango | `hair_double_buns` |
| short, playful, messy | `hair_short_loops` |

### Outfit

| Words | `outfit` |
|---|---|
| sporty, casual, tennis | `set = "tennis"` |
| school uniform, student look | `set = "school"` (+ `add = ["bow_pink"]` for a ribbon) |
| elegant, party, gothic, dressy | `set = "red_dress"` (tint `dress_red` for other colors) |
| sweet, pastel, lolita, candy | `set = "sweets"` |
| romantic, soft, fairy | `set = "pink_capelet"` |

Recolor garments with `tint = { garment = "#hex" }`, or one texture layer with
`"garment:CLOTH_02" = "#hex"`. Add pieces from other sets with `add = [...]` (same-slot
items layer; `check` warns).

### Mood and motion (render-time)

| Words | Option |
|---|---|
| shy, timid | `--expression shy --pose shy` |
| cheerful, bubbly | `--expression happy --pose peace` or `clip --preset wave_hello` |
| cool, aloof | `--expression neutral --pose contrapposto` |
| confident, sassy | `--expression smug --pose hands_on_hips` |
| gentle, kind | `--expression smile_soft --pose hand_on_chest` |
| thoughtful | `--expression neutral --pose thinking` |
| energetic, excited | `clip --preset jump_for_joy` or `hop` |
| playful, twirly | `clip --preset spin` |
| flirty, affectionate | `clip --preset blow_kiss` or `heart` |
| polite, proper | `clip --preset bow` |
| relaxed, dreamy | `clip --preset sway` |
| on the move | `clip --preset walk` (or `walk_loop` for a looping clip) |
| in a hurry, sporty | `clip --preset run` or `run_loop` |
| a little scene | chain presets: `clip --preset wave_hello,walk,bow` |

Expressions: `neutral smile_soft happy fun grin smug shy pout sad worried angry determined
surprised startled sleepy smile_closed_eyes wink_l wink_r`. Poses: `idle a_pose contrapposto
crouch hand_on_chest hands_on_hips kneel peace shy sit_chair sit_floor stride thinking wave
bow cheer heart_arms kiss_hand kiss_blow`.

## Rules

- **Adults only.** Every character is an adult woman. Descriptions asking for a child, or for
  childlike bodies, are declined. "Cute" means styling (face, colors, outfit), and the adult
  proportion rule is enforced regardless.
- The project is personal and never distributed, so resemblance to existing characters is
  fine and needs no caveat.

## Optional, not built: a `wogen describe` command

A CLI command could do the same translation unattended by calling the Claude API with the
catalog and this guide, then running `check` in a loop. It would need an API key and the
`anthropic` package (an install). It's deferred; chat covers the need for now.
