# wo-gen

A Blender 5.2 generator of stylized 3D anime characters (adult women), in the style of
Zenless Zone Zero. Overview and commands: [README.md](README.md).

## Read before working

1. [docs/style-guide.md](docs/style-guide.md): the balance table at the top says how far
   anything should go (stylized, but with weight). It also holds the proportion, animation
   and secondary-motion targets.
2. [docs/roadmap.md](docs/roadmap.md): "Next steps" and the improvement backlog say what to
   do, where each change starts and how big it is. Known issues are there too.
3. [docs/workflows.md](docs/workflows.md): how-tos. For any physics or motion change, follow
   "Tune physics and review motion".

Also: [docs/architecture.md](docs/architecture.md) (how it works),
[docs/tooling.md](docs/tooling.md) (installed tools, unused capabilities, candidate tools).

## Working rules for this project

- **You can't watch video.** Check motion with `scripts/tissue_measure.py` (numbers) and
  `scripts/frame_strip.py` (frames in one PNG), then give the user clips. Their eye on the
  clip is the only test of feel; don't call tuning done without it.
- **Look at renders before presenting them** (hands, clipping, framing) and fix problems at
  the source.
- **Headless is the source of truth.** Features are plain functions in `wogen.bl`, reachable
  from a job and from MCP. Pure logic goes in `blender/modules/wogen/*.py` with tests.
- **Run headless Blender with the literal path**:
  `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python <script> -- <args>`.
  Give render outputs absolute paths. Call it directly, one command per launch (chained
  with `;` is fine): the permission guard blocks it inside loops or behind variables.
- **Shape and look questions: prototype live, then build in.** With Blender open (MCP),
  try candidates on the live character (shape keys the user can drag, modifiers on a copy)
  and let the user dial values by eye; then move the chosen values into the generator. See
  "Tune body shape with the user" in [docs/workflows.md](docs/workflows.md).
- **Tests:** `uv run pytest` (about a minute); `-m "not blender"` for the pure tests only.
- **Scratch** goes in `.cache/tmp/`, output in `out/` (both gitignored).
- **Imported characters (`imports/`, agreed with the user 2026-11-10, revised 2026-11-11).**
  The user imports officially released MMD models of game characters (miHoYo/HoYoverse,
  Zenless Zone Zero and others) for personal use under their release terms, translated in
  [assets/LICENSES.md](assets/LICENSES.md). The agent renders, views and debugs them like
  original characters (frames, frame strips, renders checked before presenting), within
  these limits:
  - **Nothing leaves the machine.** `imports/` and renders of imported characters
    (`out/`) stay gitignored. They're never committed, published, uploaded or put in
    artifacts or external services (the terms forbid redistribution).
  - **Content within the terms:** nothing sexual or suggestive, no gore, nothing that
    mocks or degrades a character. Poses, motion and expressions like the game's own.
  - **Their bodies stay theirs:** soft tissue on imported characters stays subtle and
    game-like, and their proportions aren't reshaped (the terms allow only moderate outfit
    changes). A character who is canonically under 18 gets no soft-tissue physics; check
    the canon before tuning one.
  - **No parts taken:** their meshes, textures, rigs and hair don't go onto original
    characters (the terms forbid taking parts to modify other models).
  - **Learn from them for original characters.** The project's main goal remains its own,
    completely new characters. The imported models are the reference for what good looks
    like: detail, physics, proportions and design creativity. Study and measure them
    (proportion ratios, how hair and clothing are layered and rigged, physics behaviour,
    shading and toon ramps, expression design) and build what was learned into the
    original generator as new, original work. Ideas and measurements carry over; assets
    don't.
  - The user remains the judge of feel in clips (the agent can't watch video).
- **Keep the docs current** when something changes: move finished backlog items to "Done, by
  phase" in the roadmap and update the style guide's status table and any numbers.
