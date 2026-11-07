"""Command-line entry point: ``uv run wogen <command>``.

Rendering commands launch headless Blender (``wogen.launcher``) and run the matching job in
``wogen.bl.jobs``. Options after the command are forwarded to the job unchanged, so the CLI
and the in-Blender job share one definition of each option (``wogen <job> --help``).
"""

from __future__ import annotations

import argparse
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
    "generate": ("generate", "generated.png"),
    "variants": ("variants", "variants.png"),
}


def run_blender_job(command: str, rest: list[str]) -> int:
    job, default_name = BLENDER_JOBS[command]
    if any(a in ("-h", "--help") for a in rest):
        return run_job(job, "--help")
    rest = list(rest)
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


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in BLENDER_JOBS:
        return run_blender_job(argv[0], argv[1:])

    parser = argparse.ArgumentParser(
        prog="wogen",
        epilog="Blender jobs (options are forwarded; see 'wogen <job> --help'): "
               + ", ".join(BLENDER_JOBS),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("harvest", help="Extract garments from assets/base/*.vrm into the library")
    p.add_argument("names", nargs="*")
    p.add_argument("--reference", default="base_f01")
    p.add_argument("--fresh", action="store_true", help="ignore the index; overwrite by name")
    p.set_defaults(func=lambda a: run_job("harvest", *a.names, "--reference", a.reference,
                                          *(["--fresh"] if a.fresh else [])))

    p = sub.add_parser("resolve", help="Resolve a TOML spec with a seed and print JSON")
    p.add_argument("spec")
    p.add_argument("--seed", type=int, default=None)
    p.set_defaults(func=_cmd_resolve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
