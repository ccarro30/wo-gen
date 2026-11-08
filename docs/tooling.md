# Tooling

Installs need explicit approval (global rule 1). Everything below marked ✅ is installed.

## Required

| Tool | Version / location | Purpose | Notes |
|---|---|---|---|
| **Blender** | ✅ 5.2.3 LTS, `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` | Everything | Not on PATH. The CLI finds it at that path, or set `WOGEN_BLENDER`. Bundled Python 3.13. |
| **VRM Add-on for Blender** | ✅ Blender Extensions (`bl_ext.blender_org.vrm`) | VRM import/export, MToon, spring-bone data, humanoid map | Headless jobs enable it themselves under `--factory-startup`. |
| **Python + uv** | ✅ Python 3.14, uv | CLI, tests | `requires-python >=3.13`. `.venv` via `uv sync`. Dev group: `pytest`, `fake-bpy-module`. |
| **MCP for Blender** | ✅ 2.2.7, pinned | Claude ↔ live Blender | See below. |
| **VroidStudio** | ✅ (winget) | Base body, garments, (next) hairstyles | Source project in `vroid/model.vroid`. |
| **Git + Git LFS** | ✅ installed; repo on GitHub | Version control | `.gitattributes` puts `*.vrm *.vroid *.blend *.fbx *.png *.jpg *.mp4` in LFS. Set up LFS once per machine before cloning. |
| **GPU** | ✅ AMD RX 9070 XT (HIP) | EEVEE rendering | Keep Adrenalin drivers current. Cycles works on HIP but isn't used for the toon look. |

Not needed: standalone ffmpeg (Blender writes H.264 MP4 itself), Wiggle 2 (own solver), Rigify
(poses use our own FK/IK on the VRM skeleton).

## MCP for Blender (pinned)

The PyPI package is `mcp-for-blender`; its wheel bundles the add-on, so one version pins both
halves.

| Half | Location | Pinned by |
|---|---|---|
| MCP server | `.mcp.json`: `uvx mcp-for-blender@2.2.7`, telemetry opt-outs set | Version in `args` |
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
  integration tests run headless renders, a portrait job and a clip job (about 47 s total).
- **Scratch and output:** temp files go to `.cache/tmp/` (deleted after use), and outputs go
  to `out/`. Both are gitignored, as are `references/` and the `.cache/` wheel cache.
- **Live session:** in chat, Claude calls `wogen.bl.*` through MCP. Reload edited modules with
  `importlib.reload`.

## Licensing

- Everything in `assets/` was made by you in VroidStudio. Your own VroidStudio creations are
  generally yours to use (⚠ check VroidStudio's terms for preset/sample items before
  redistributing).
- `references/` holds third-party copyrighted screenshots, used as a style reference only and
  never committed.
- Provenance is recorded in [assets/LICENSES.md](../assets/LICENSES.md); add a row for every new
  asset.
- Avoid marketplace assets that forbid AI use or redistribution, and MMD/game-ripped models.
