"""Entry point inside headless Blender: dispatches ``-- <job> <args...>``.

Jobs mirror the chat (MCP) functions so batch output matches what was tuned interactively.
"""

from __future__ import annotations

import argparse
import sys

import bpy


def _job_args() -> list[str]:
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def _character_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--base", default="base_f01")
    p.add_argument("--expression", default="neutral")
    p.add_argument("--pose", default="idle",
                   help="library pose name, or comma-separated names merged left to right")
    p.add_argument("--seat", type=float, default=None, metavar="HEIGHT",
                   help="add a seat prop of this height in metres (e.g. 0.45 for sit_chair)")
    p.add_argument("--view-yaw", type=float, default=0.0,
                   help="orbit the camera (degrees, + toward her left; 35 = three-quarter)")
    p.add_argument("--outfit", default=None, metavar="SET",
                   help="wear a harvested outfit set, e.g. base_f01_outfit3")
    p.add_argument("--equip", action="append", default=[], metavar="GARMENT",
                   help="equip a garment from assets/garments (repeatable)")
    p.add_argument("--unequip", action="append", default=[], metavar="SLOT_OR_NAME",
                   help="hide garments by slot (shoes, top, ...) or name (repeatable)")
    p.add_argument("--tint", action="append", default=[], metavar="GARMENT=#RRGGBB",
                   help="tint a garment, e.g. onepiece_010_01=#ffb8cc (repeatable)")
    p.add_argument("--through-hair", default="brow",
                   help="comma-separated features drawn over the bangs ('' to disable)")
    p.add_argument("--no-post", action="store_true")


def _pose_spec(args: argparse.Namespace):
    names = [n for n in args.pose.split(",") if n]
    return names if len(names) > 1 else names[0]


def _prepare(args: argparse.Namespace) -> None:
    from . import character, face
    features = [f for f in args.through_hair.split(",") if f]
    character.prepare(args.base, through_hair=features or None)
    face.expression(args.expression)
    if args.outfit or args.equip or args.unequip or args.tint:
        from . import outfit
        from .toon import hex_to_srgb
        if args.outfit:
            outfit.equip_set(args.outfit)
        for name in args.equip:
            outfit.equip(name)
        for item in args.unequip:
            outfit.unequip(item)
        for spec in args.tint:
            name, _, color = spec.partition("=")
            outfit.recolor(name, tint=hex_to_srgb(color))
    if args.seat:
        from . import props
        props.seat(args.seat)


def _portrait(argv: list[str]) -> None:
    from . import render
    p = argparse.ArgumentParser(prog="portrait")
    _character_args(p)
    p.add_argument("--framing", choices=["face", "bust", "full"], default="bust")
    p.add_argument("--width", type=int, default=1600)
    p.add_argument("--height", type=int, default=2000)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    _prepare(args)
    render.portrait(args.framing, (args.width, args.height), args.out, post=not args.no_post,
                    pose=_pose_spec(args), view_yaw=args.view_yaw)


def _turntable(argv: list[str]) -> None:
    from . import render
    p = argparse.ArgumentParser(prog="turntable")
    _character_args(p)
    p.add_argument("--framing", choices=["face", "bust", "full"], default="full")
    p.add_argument("--frames", type=int, default=96)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1350)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    _prepare(args)
    render.turntable(args.frames, args.framing, (args.width, args.height), args.out, args.fps,
                     post=not args.no_post, pose=_pose_spec(args))


def _clip(argv: list[str]) -> None:
    from . import anim, physics, render
    p = argparse.ArgumentParser(prog="clip")
    _character_args(p)
    p.add_argument("--preset", default="look_around", choices=sorted(anim.PRESETS))
    p.add_argument("--framing", choices=["face", "bust", "full"], default="bust")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1350)
    p.add_argument("--no-physics", action="store_true")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    _prepare(args)
    anim.preset(args.preset, args.fps)
    if not args.no_physics:
        print(physics.bake())
    render.clip(args.out, args.framing, (args.width, args.height), post=not args.no_post,
                view_yaw=args.view_yaw, fps=args.fps)


def _harvest(argv: list[str]) -> None:
    from . import character, outfit
    p = argparse.ArgumentParser(prog="harvest")
    p.add_argument("names", nargs="*", help="assets/base/<name>.vrm exports (default: all base_f01*)")
    p.add_argument("--reference", default="base_f01")
    p.add_argument("--fresh", action="store_true", help="ignore the index; overwrite by name")
    args = p.parse_args(argv)
    character.ensure_vrm_addon()
    character.clear_default_scene()
    for line in outfit.harvest(args.names or None, args.reference, restore=False,
                               fresh=args.fresh):
        print("[harvest]", line)
    print("[harvest] library:", ", ".join(outfit.list_library()))


def _outfit_sheet(argv: list[str]) -> None:
    from . import character, render
    p = argparse.ArgumentParser(prog="outfit-sheet")
    p.add_argument("--base", default="base_f01")
    p.add_argument("--view-yaw", type=float, default=25.0)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    character.prepare(args.base)
    print(render.outfit_sheet(out_path=args.out, view_yaw=args.view_yaw))


def _parse_seeds(text: str) -> list[int]:
    """'1-8' or '3,7,11' or '5'."""
    seeds = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            seeds += list(range(int(a), int(b) + 1))
        elif part:
            seeds.append(int(part))
    return seeds


def _generate(argv: list[str]) -> None:
    from . import face, generate, render
    p = argparse.ArgumentParser(prog="generate")
    p.add_argument("--spec", default="specs/default.toml")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--pose", default="idle")
    p.add_argument("--expression", default="smile_soft")
    p.add_argument("--framing", choices=["face", "bust", "full"], default="full")
    p.add_argument("--view-yaw", type=float, default=25.0)
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1350)
    p.add_argument("--save-blend", default=None, help="also save the generated scene (.blend)")
    p.add_argument("--export", action="append", default=[], metavar="PATH",
                   help="also export the character (.vrm or .fbx; repeatable)")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    params = generate.generate(args.spec, args.seed)
    for note in params.notes:
        print("[generate]", note)
    face.expression(args.expression)
    render.portrait(args.framing, (args.width, args.height), args.out, pose=args.pose,
                    view_yaw=args.view_yaw)
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=args.save_blend, compress=True)
        print("[generate] saved", args.save_blend)
    if args.export:
        from . import export
        name = f"wogen seed {generate.describe().get('seed')}"
        if len(args.export) == 1:
            for line in export.export_prepared(args.export[0], name):   # disposable process
                print("[export]", line)
        else:
            for path in args.export:
                export.export_character(path, name)                     # each from a clean copy
                print("[export] wrote", path)


def _variants(argv: list[str]) -> None:
    from . import face, generate, render
    from .character import character_armature
    p = argparse.ArgumentParser(prog="variants")
    p.add_argument("--spec", default="specs/default.toml")
    p.add_argument("--seeds", default="1-8")
    p.add_argument("--framing", choices=["face", "bust", "full"], default="full")
    p.add_argument("--view-yaw", type=float, default=25.0)
    p.add_argument("--cols", type=int, default=4)
    p.add_argument("--cell", type=int, default=512)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    seeds = _parse_seeds(args.seeds)
    scene = bpy.context.scene

    def make(seed):
        def fn():
            params = generate.generate(args.spec, seed)
            print(f"[variants] seed {seed}: " + "; ".join(params.notes[:1] + [
                f"outfit={params.outfit}", f"hair={params.palette.hair}"]))
            face.expression("smile_soft")
            render.portrait(args.framing, (args.cell, args.cell), pose="idle",
                            view_yaw=args.view_yaw)
            render.portrait_camera(scene, character_armature(), args.framing,
                                   view_yaw=args.view_yaw)
        return fn
    generate.generate(args.spec, seeds[0])          # contact_sheet needs a character up front
    print(render.contact_sheet([(f"seed {s}", make(s)) for s in seeds], args.out, None,
                               args.cell, args.cols))


def _export(argv: list[str]) -> None:
    """Runs on a saved .blend (passed to Blender): prepare + write VRM/FBX."""
    from . import character, export
    p = argparse.ArgumentParser(prog="export")
    p.add_argument("--out", required=True, help=".vrm or .fbx")
    p.add_argument("--name", default=None)
    args = p.parse_args(argv)
    character.ensure_vrm_addon()
    for line in export.export_prepared(args.out, args.name):
        print("[export]", line)


def _render_test(argv: list[str]) -> None:
    from .render import render_test
    p = argparse.ArgumentParser(prog="render-test")
    p.add_argument("--out", required=True)
    render_test(p.parse_args(argv).out)


JOBS = {"render_test": _render_test, "portrait": _portrait, "turntable": _turntable,
        "clip": _clip, "harvest": _harvest, "outfit_sheet": _outfit_sheet,
        "generate": _generate, "variants": _variants, "export": _export}


def main() -> None:
    args = _job_args()
    if not args or args[0] not in JOBS:
        raise SystemExit(f"wogen.bl.jobs: expected one of {sorted(JOBS)}, got {args[:1]}")
    JOBS[args[0]](args[1:])
