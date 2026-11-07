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
| **Git + Git LFS** | ✅ installed | Version control | **The repo isn't initialized yet.** LFS for `*.vrm *.blend *.vroid`. |
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

## Dev workflow

- `uv run wogen <command>` launches Blender as
  `--background --factory-startup --python-exit-code 1 --python-expr <bootstrap> -- <job> <args>`.
  Jobs live in `wogen/bl/jobs.py`; options after the command are forwarded unchanged.
- **Tests:** run `uv run pytest`. Pure modules take about 1 s; the `blender`-marked
  integration tests run headless renders, a portrait job and a clip job (about 45 s total).
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
- A provenance file, `assets/LICENSES.md`, is recommended but doesn't exist yet.
- Avoid marketplace assets that forbid AI use or redistribution, and MMD/game-ripped models.
