# Tooling

Installs need explicit approval (global rule 1). Everything below marked ✅ is installed.

## Required

| Tool | Version / location | Purpose | Notes |
|---|---|---|---|
| **Blender** | ✅ 5.2.3 LTS, `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` | Everything | Not on PATH. The CLI finds it at that path, or set `WOGEN_BLENDER`. Bundled Python 3.13. |
| **VRM Add-on for Blender** | ✅ Blender Extensions (`bl_ext.blender_org.vrm`) | VRM import/export, MToon, spring-bone data, humanoid map | Headless jobs enable it themselves under `--factory-startup`. |
| **Python + uv** | ✅ Python 3.14, uv | CLI, tests | `requires-python >=3.13`. `.venv` via `uv sync`. Dev group: `pytest`, `fake-bpy-module`. |
| **MCP for Blender** | ✅ 2.2.9, pinned | Claude ↔ live Blender | See below. |
| **MMD Tools** | ✅ Blender Extensions (`bl_ext.blender_org.mmd_tools`), installed 2026-11-10 | Import PMX/PMD reference models (`imports/`) | Interactive Blender only; headless jobs don't enable it. Imported scenes are saved as `.blend` next to the source so scripts can load them without it. |
| **VroidStudio** | ✅ (winget) | Base body, garments, hairstyles | Source project in `vroid/model.vroid`. |
| **Git + Git LFS** | ✅ installed; repo on GitHub | Version control | `.gitattributes` puts `*.vrm *.vroid *.blend *.fbx *.png *.jpg *.mp4 *.bvh` in LFS. Set up LFS once per machine before cloning. |
| **GPU** | ✅ AMD RX 9070 XT (HIP) | EEVEE rendering | Keep Adrenalin drivers current. Cycles works on HIP but isn't used for the toon look. |

Not needed: standalone ffmpeg (Blender writes H.264 MP4 itself), Wiggle 2 (own solver), Rigify
(poses use our own FK/IK on the VRM skeleton).

## Getting more from the tools we have

Nothing here needs an install. Ids refer to the backlog in [roadmap.md](roadmap.md).

| Tool | Unused capability | What it would give us |
|---|---|---|
| Blender | Corrective Smooth modifier (after the armature) | Softer elbow and hip creases without new weights (B4). Render only; VRM can't carry it |
| Blender | Cloth simulation, baked | Cloth between skirt bones for stills (P4) |
| Blender | Video Sequencer | Tile two clips side by side for before/after review (E4); also frame grabs from an MP4. No ffmpeg needed |
| Blender | EEVEE depth of field and motion blur | Portrait depth and smoother fast motion (L6). Check motion blur against the outlines first |
| Blender | Line Art (Grease Pencil) modifier | Interior lines at creases and seams (style guide). Costly per frame; try on stills |
| Blender | A shadow-catcher plane, or light linking | A ground contact shadow while the face stays shadow-free (L1) |
| Blender | NLA strips and F-curve Noise modifiers | One way to layer idle motion over a preset (M3). Generating the extra keys ourselves keeps it seeded and testable; compare both |
| Blender | Shape-key drivers | Bone-driven corrective shapes (B4, T5) |
| VRM add-on | Spring-bone capsule colliders and the spring "center" | Better limb collision than sphere rows; our `carry` is a hand-made center. Read the add-on's data model before relying on either |
| VRM add-on | VRM Animation (`.vrma`) export | Share a baked motion with VRM apps, not just the model. Unverified: check that this add-on version writes it |
| VroidStudio | Items we haven't harvested: shorts, leggings, swimsuits, thigh-highs, more hair | C1, C3. Texture editing inside VroidStudio is the cheapest path to techwear (C2) |
| MCP for Blender | `look` on a posed frame of the live scene | Fast visual checks while tuning, without a headless render. Headless stays the source of truth |
| pytest | The `blender` marker | More integration tests (E1, E2). They cost about 15 s each, so group assertions per Blender launch |
| Our own scripts | `scripts/tissue_measure.py`, `scripts/frame_strip.py` | Numbers and frame strips for any physics change. See [workflows.md](workflows.md#tune-physics-and-review-motion) |

## Candidate tools

Not installed. Each needs approval (global rule 1) and a check that it's free, runs on this
machine (AMD GPU: assume CUDA-only until proven otherwise) and has terms that suit personal
use. Versions and licenses below are from memory, so verify them before proposing an install.

| Tool | For | Notes |
|---|---|---|
| **ruff** | Linting and formatting (E5) | One dev dependency. `.gitignore` already lists its cache |
| **ffmpeg** (standalone) | Frame extraction, GIFs, side-by-side clips | Optional: Blender's sequencer covers the same needs with more code |
| **Mixamo** (Adobe, web) | Stylized, game-like motions (idles, dances, reactions) as FBX | Free with an account. Needs an FBX → our-retarget path (the retargeter reads BVH; Blender can convert). Check the terms |
| **Bandai Namco Research Motion Dataset** | Styled locomotion and gestures (the same action in several characters' styles) | BVH. Closer to anime acting than CMU. License is non-commercial; fine for personal use, record it in `assets/LICENSES.md` |
| **100STYLE** | 100 walking and running styles | BVH. Good source for M1 references and gait variety. Check the license |
| **Video-to-motion** (GVHMR, WHAM, 4D-Humans; FreeMoCap; MediaPipe) | Custom motion from a phone video (M5) | The research models assume CUDA; MediaPipe and FreeMoCap run on CPU with lower quality. Output needs conversion to BVH and our foot locking |
| **A VRM viewer/runtime** (e.g. a three-vrm web viewer run locally, or a desktop VRM app) | Seeing exported spring physics as an app plays it (T2, T7) | Blender re-import only proves the data round-trips, not how it moves |
| **Krita / Inkscape** | Decals, prints, techwear texture edits (C2) | Free, no GPU needs |

Evaluated and not needed: Wiggle 2 (own solver), Rigify (own FK/IK), the Rokoko retarget
add-on (own BVH retargeter), image/text-to-3D generators (topology and rigging don't meet the
bar; see [implementation-options.md](implementation-options.md)).

## MCP for Blender (pinned)

The PyPI package is `mcp-for-blender`; its wheel bundles the add-on, so one version pins both
halves.

| Half | Location | Pinned by |
|---|---|---|
| MCP server | `.mcp.json`: `uvx mcp-for-blender@2.2.9`, telemetry opt-outs set | Version in `args` |
| Blender add-on | `blender/addons/blender_mcp.py`, extracted from the same wheel | `blender/addons/blender_mcp.VERSION` (version + SHA-256s) |

- **Update:** run `.\scripts\update-blender-mcp.ps1`. It pins the newest release and does
  nothing if that's already pinned; `-Version X.Y.Z` pins a specific version and `-Force`
  re-extracts. It downloads the wheel, checks the SHA-256 against PyPI, extracts the add-on
  and rewrites the pin. Then restart Blender and Claude Code.
- **Blender setup (one time):** Preferences → File Paths → Script Directories → add `<repo>\blender`,
  then enable "MCP for Blender". This also puts `wogen` on Blender's `sys.path`. Start the
  server from the sidebar (N) → MCP tab.
- **Don't use the add-on's own Update button.** It pulls `main` from GitHub, bypassing the pin.
- **Telemetry** is off in both halves. **Network:** the socket listens on `localhost:9876`.
  Asset/generator integrations (Poly Haven, Sketchfab, Hyper3D, …) are off.
- The add-on runs arbitrary Python in Blender: use it with trusted prompts only.

## Motion capture clips (pinned)

BVH clips from the CMU Graphics Lab Motion Capture Database (Bruce Hahne's 2010 BVH
conversion), via the GitHub mirror `una-dinosauria/cmu-mocap` at a pinned commit. Data only:
nothing is installed.

| What | Location |
|---|---|
| Clip list + pinned source commit | `assets/mocap/manifest.json` (`name -> file`) |
| Downloaded clips | `assets/mocap/cmu/*.bvh` (Git LFS) |
| Lock (commit + SHA-256 of each file) | `assets/mocap/cmu/LOCK` |

- **Get / repair:** `.\scripts\update-mocap.ps1`. It downloads missing clips, re-downloads
  any whose hash no longer matches the lock, removes clips the manifest no longer lists, and
  rewrites the lock. A no-op when everything is present.
- **Add a clip:** find it in the source's index (`cmu-mocap-index-text.txt` in the repo, about
  2,500 motions with descriptions), add `"name": {"file": "data/NNN/NN_MM.bvh", "description":
  "..."}` to the manifest, rerun the script. `uv run wogen mocap` lists what's available.
- **Move to a newer source commit:** change `source.commit` in the manifest and rerun; a
  changed commit re-downloads everything.
- **Terms:** CMU: "free for use in research and commercial projects worldwide"; credit
  mocap.cs.cmu.edu (also recorded in `assets/LICENSES.md`).

## Dev workflow

- `uv run wogen <command>` launches Blender as
  `--background --factory-startup --python-exit-code 1 --python-expr <bootstrap> -- <job> <args>`.
  Jobs live in `wogen/bl/jobs.py`; options after the command are forwarded unchanged.
- **Tests:** run `uv run pytest`. Pure modules take about 1 s; the `blender`-marked
  integration tests run headless renders, a portrait job and a clip job (about 50 s total).
- **Tuning scripts:** `scripts/tissue_measure.py` (soft-tissue numbers per preset) and
  `scripts/frame_strip.py` (frames of a clip in one PNG) run inside headless Blender; see
  [workflows.md](workflows.md#tune-physics-and-review-motion).
- **Scratch and output:** temp files go to `.cache/tmp/` (deleted after use), and outputs go
  to `out/`. Both are gitignored, as are `references/` and the `.cache/` wheel cache.
- **Live session:** in chat, Claude calls `wogen.bl.*` through MCP. Reload edited modules with
  `importlib.reload`.

## Licensing

- Everything in `assets/` except the mocap clips was made by you in VroidStudio. Your own
  VroidStudio creations are generally yours to use (⚠ check VroidStudio's terms for
  preset/sample items before redistributing). The CMU mocap clips are third-party, free for
  research and commercial use, with a credit line (see `assets/LICENSES.md`).
- `references/` holds third-party copyrighted screenshots, used as a style reference only and
  never committed.
- `imports/` holds third-party character models (gitignored), used as references and for use as
  characters is this project.
- Provenance is recorded in [assets/LICENSES.md](../assets/LICENSES.md); add a row for every new
  asset.
- Avoid marketplace assets that forbid AI use or redistribution, and MMD/game-ripped models.
