"""Command-line entry point: ``uv run wogen <command>``.

Rendering commands launch headless Blender (``wogen.launcher``) and run the matching job in
``wogen.bl.jobs``. Options after the command are forwarded to the job unchanged, so the CLI
and the in-Blender job share one definition of each option (``wogen <job> --help``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import spec as spec_mod
from .launcher import run_job
from .paths import OUT_DIR

# CLI command -> (job name in wogen.bl.jobs, default output file under out/).
BLENDER_JOBS = {
    "render-test": ("render_test", "render-test.png"),
    "portrait": ("portrait", "portrait.png"),
    "turntable": ("turntable", "turntable.mp4"),
    "clip": ("clip", "clip.mp4"),
    "outfit-sheet": ("outfit_sheet", "outfits.png"),
    "hair-sheet": ("hair_sheet", "hair.png"),
    "generate": ("generate", "generated.png"),
    "variants": ("variants", "variants.png"),
}


def run_blender_job(command: str, rest: list[str]) -> int:
    job, default_name = BLENDER_JOBS[command]
    if any(a in ("-h", "--help") for a in rest):
        return run_job(job, "--help")
    rest = list(rest)
    if "--mmd" in rest[:-1]:                 # pick the model now: fail before Blender starts
        from . import mmd
        from .paths import REPO_ROOT
        i = rest.index("--mmd")
        try:
            rest[i + 1] = str(mmd.find_model(rest[i + 1], REPO_ROOT / "imports").resolve())
        except ValueError as e:
            print(f"{command}: {e}", file=sys.stderr)
            return 2
    if "--out" in rest:
        i = rest.index("--out")
        out = Path(rest[i + 1]).resolve()
        rest[i + 1] = str(out)
    else:
        out = (OUT_DIR / default_name).resolve()
        rest += ["--out", str(out)]
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    code = run_job(job, *rest)
    if code != 0 or not out.is_file():
        print(f"{command} FAILED (blender exit code {code})", file=sys.stderr)
        return code or 1
    print(f"{command} OK: {out}")
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    resolved = spec_mod.resolve(spec_mod.load_spec(args.spec), args.seed)
    print(spec_mod.to_json(resolved))
    return 0


def _cmd_catalog(args: argparse.Namespace) -> int:
    from .catalog import catalog
    print(json.dumps(catalog(), indent=2))
    return 0


def _cmd_mocap(args: argparse.Namespace) -> int:
    from .bvh import catalog
    clips = catalog()
    missing = 0
    for name, entry in clips.items():
        mark = "  " if entry["available"] else "! "
        missing += not entry["available"]
        print(f"{mark}{name:14s} {entry['description']}")
    if missing:
        print(f"{missing} clip(s) not downloaded (!): run scripts\\update-mocap.ps1")
    print("Use: wogen clip --mocap NAME [--start S] [--end S] [--in-place]")
    return 0


def _cmd_mmd(args: argparse.Namespace) -> int:
    from . import mmd
    from .paths import REPO_ROOT
    imports = REPO_ROOT / "imports"
    models = mmd.list_models(imports) if imports.is_dir() else []
    for path in models:
        print(f"  {mmd.english_label(path, imports):60s} ({mmd.model_label(path, imports)})")
    if not models:
        print("No models: put PMX packages in imports/<folder>/ (see CLAUDE.md, imported characters)")
    print("Use: wogen portrait|clip|turntable --mmd NAME  (a name, folder/name or .pmx path)")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    from .catalog import check
    errors, warnings = check(spec_mod.load_spec(args.spec))
    for e in errors:
        print("ERROR  ", e)
    for w in warnings:
        print("warning", w)
    print("OK" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


def _cmd_export(args: argparse.Namespace) -> int:
    blend = Path(args.blend).resolve()
    if not blend.is_file():
        print(f"export: no such file {blend}", file=sys.stderr)
        return 1
    code = 0
    for target in args.out:      # one process per format: export prepares the scene destructively
        out = Path(target).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        extra = ["--name", args.name] if args.name else []
        code = run_job("export", "--out", str(out), *extra, blend_file=blend) or code
        print(f"export {'OK' if out.is_file() else 'FAILED'}: {out}")
    return code


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):    # model names may not fit the console's code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in BLENDER_JOBS:
        return run_blender_job(argv[0], argv[1:])

    parser = argparse.ArgumentParser(
        prog="wogen",
        epilog="Blender jobs (options are forwarded; see 'wogen <job> --help'): "
               + ", ".join(BLENDER_JOBS),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("harvest", help="Extract garments and hairstyles from assets/base/*.vrm into the library")
    p.add_argument("names", nargs="*")
    p.add_argument("--reference", default="base_f01")
    p.add_argument("--fresh", action="store_true", help="ignore the index; overwrite by name")
    p.add_argument("--only", choices=["garments", "hair"], default=None)
    p.set_defaults(func=lambda a: run_job("harvest", *a.names, "--reference", a.reference,
                                          *(["--fresh"] if a.fresh else []),
                                          *(["--only", a.only] if a.only else [])))

    p = sub.add_parser("catalog", help="Print what a spec can contain (ranges, hairstyles, "
                                       "outfit sets, garments) as JSON")
    p.set_defaults(func=_cmd_catalog)

    p = sub.add_parser("mocap", help="List the motion-capture clips (assets/mocap/manifest.json)")
    p.set_defaults(func=_cmd_mocap)

    p = sub.add_parser("mmd", help="List the imported MMD character models (imports/)")
    p.set_defaults(func=_cmd_mmd)

    p = sub.add_parser("check", help="Strictly check a spec (unknown keys, ranges, asset names)")
    p.add_argument("spec")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("resolve", help="Resolve a TOML spec with a seed and print JSON")
    p.add_argument("spec")
    p.add_argument("--seed", type=int, default=None)
    p.set_defaults(func=_cmd_resolve)

    p = sub.add_parser("export", help="Export the character in a saved .blend to VRM/FBX "
                                      "(the .blend is not modified)")
    p.add_argument("blend", help="e.g. a scene saved with 'generate --save-blend'")
    p.add_argument("--out", action="append", required=True, metavar="PATH",
                   help=".vrm or .fbx (repeatable)")
    p.add_argument("--name", default=None, help="model name (default: from the scene)")
    p.set_defaults(func=_cmd_export)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
