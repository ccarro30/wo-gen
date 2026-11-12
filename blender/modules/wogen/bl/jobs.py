"""Entry point inside headless Blender: dispatches ``-- <job> <args...>``.

Jobs mirror the chat (MCP) functions so batch output matches what was tuned interactively.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


def _job_args() -> list[str]:
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def _character_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--spec", default=None,
                   help="generate the character from this spec (TOML) instead of the plain base")
    p.add_argument("--seed", type=int, default=None,
                   help="generate with this seed (implies --spec specs/default.toml)")
    p.add_argument("--base", default=None, help="base export (default: the spec's, or base_f01)")
    p.add_argument("--mmd", default=None, metavar="MODEL",
                   help="an imported MMD model instead of the base ('wogen mmd' lists them; "
                        "a name, folder/name or .pmx path). Outfit, hair and spec options "
                        "don't apply")
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
    p.add_argument("--hair", default=None, metavar="STYLE",
                   help="wear a library hairstyle, e.g. hair_twintails (default: base hair)")
    p.add_argument("--through-hair", default="brow",
                   help="comma-separated features drawn over the bangs ('' to disable)")
    p.add_argument("--no-post", action="store_true")


def _pose_spec(args: argparse.Namespace):
    names = [n for n in args.pose.split(",") if n]
    return names if len(names) > 1 else names[0]


def _prepare(args: argparse.Namespace) -> None:
    """Build the character: the plain base, or a generated one (--spec/--seed). The other
    character options (outfit, hair, tints, ...) then apply on top as overrides."""
    from . import character, face
    features = [f for f in args.through_hair.split(",") if f]
    if args.mmd:
        vroid_only = [flag for flag, used in (
            ("--spec", args.spec), ("--seed", args.seed is not None), ("--base", args.base),
            ("--outfit", args.outfit), ("--equip", args.equip), ("--unequip", args.unequip),
            ("--tint", args.tint), ("--hair", args.hair)) if used]
        if vroid_only:
            raise SystemExit(f"--mmd: {', '.join(vroid_only)} only apply to the VRoid base")
        from . import mmd_import
        try:
            arm = mmd_import.prepare(args.mmd)
        except ValueError as e:              # unknown or ambiguous model name
            raise SystemExit(f"--mmd: {e}") from None
        from .. import mmd
        source = Path(arm.get(mmd_import.SOURCE_KEY))
        print(f"[mmd] {mmd.english_label(source, mmd_import.IMPORTS_DIR)} ({source})")
        face.expression(args.expression)
        if args.seat:
            from . import props
            props.seat(args.seat)
        return
    if args.spec or args.seed is not None:
        from . import generate
        params = generate.generate(args.spec or "specs/default.toml", args.seed, base=args.base,
                                   through_hair=tuple(features))
        for note in params.notes:
            print("[generate]", note)
        print(f"[generate] seed {generate.describe().get('seed')}: outfit={params.outfit}, "
              f"hair={params.hair or 'base'}")
    else:
        character.prepare(args.base or "base_f01", through_hair=features or None)
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
    if args.hair:
        from . import hair
        hair.equip(args.hair)
    if args.seat:
        from . import props
        props.seat(args.seat)


def _portrait(argv: list[str]) -> None:
    from . import render
    p = argparse.ArgumentParser(prog="portrait")
    _character_args(p)
    p.add_argument("--framing", choices=["face", "bust", "hips", "full"], default="bust")
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
    p.add_argument("--framing", choices=["face", "bust", "hips", "full"], default="full")
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
    p.add_argument("--preset", default="look_around",
                   help=f"one of {', '.join(sorted(anim.PRESETS))}, or several joined by "
                        "commas (played in order with transitions)")
    p.add_argument("--framing", choices=["face", "bust", "hips", "full"], default="bust")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1350)
    p.add_argument("--no-physics", action="store_true")
    p.add_argument("--mocap", default=None, help="motion-capture clip instead of a preset "
                   "('wogen mocap' lists them), or a .bvh path")
    p.add_argument("--start", type=float, default=0.0, help="mocap: start time (seconds)")
    p.add_argument("--end", type=float, default=None, help="mocap: end time (seconds)")
    p.add_argument("--in-place", action="store_true", help="mocap: remove horizontal travel")
    p.add_argument("--no-clear", action="store_true",
                   help="mocap: don't keep arms out of skirts (faster)")
    p.add_argument("--no-foot-lock", action="store_true",
                   help="mocap: let feet slide as retargeted (faster)")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    if args.mocap:
        from .. import bvh
        from . import mocap
        bvh.clip_path(args.mocap)      # fail on unknown/missing clips before the slow setup
        _prepare(args)
        opts = mocap.apply(args.mocap, args.start, args.end, args.fps, in_place=args.in_place,
                           expression=args.expression, clear=not args.no_clear,
                           lock=not args.no_foot_lock)
    else:
        from .. import bvh                # fail on unknown presets/clips before the slow setup
        from ..motions import parse_chain
        for seg in parse_chain(args.preset):
            if seg[0] == "mocap":
                bvh.clip_path(seg[1])
        _prepare(args)
        opts = anim.preset(args.preset, args.fps)
    if not args.no_physics:
        print(physics.bake(physics.PhysicsSettings(substeps=opts.get("substeps", 1),
                                                   carry=opts.get("carry", 0.0))))
    elif bpy.context.scene.rigidbody_world is not None:     # an MMD model's own physics
        bpy.context.scene.rigidbody_world.enabled = False
    anim.loop_range(opts)
    render.clip(args.out, args.framing, (args.width, args.height), post=not args.no_post,
                view_yaw=args.view_yaw, fps=args.fps, follow=opts.get("follow", False))


def _harvest(argv: list[str]) -> None:
    from . import character, outfit
    p = argparse.ArgumentParser(prog="harvest")
    p.add_argument("names", nargs="*", help="assets/base/<name>.vrm exports (default: all base_f01*; *_hair* exports are "
                        "harvested as hairstyles)")
    p.add_argument("--reference", default="base_f01")
    p.add_argument("--fresh", action="store_true", help="ignore the index; overwrite by name")
    p.add_argument("--only", choices=["garments", "hair"], default=None)
    args = p.parse_args(argv)
    character.ensure_vrm_addon()
    character.clear_default_scene()
    from . import hair
    hair_prefix = f"{args.reference}_hair"
    garment_names = [n for n in args.names if not n.startswith(hair_prefix)]
    hair_names = [n for n in args.names if n.startswith(hair_prefix)]
    do_garments = args.only != "hair" and (garment_names or not args.names)
    do_hair = args.only != "garments" and (hair_names or not args.names)
    if do_garments:
        for line in outfit.harvest(garment_names or None, args.reference, restore=False,
                                   fresh=args.fresh):
            print("[harvest]", line)
    if do_hair:
        for line in hair.harvest(hair_names or None, args.reference, fresh=args.fresh):
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


def _hair_sheet(argv: list[str]) -> None:
    from . import character, render
    p = argparse.ArgumentParser(prog="hair-sheet")
    p.add_argument("--base", default="base_f01")
    p.add_argument("--outfit", default=None, metavar="SET")
    p.add_argument("--framing", choices=["face", "bust", "hips", "full"], default="bust")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    character.prepare(args.base)
    if args.outfit:
        from . import outfit
        outfit.equip_set(args.outfit)
    print(render.hair_sheet(out_path=args.out, framing=args.framing))


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
    p.add_argument("--framing", choices=["face", "bust", "hips", "full"], default="full")
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
    p.add_argument("--framing", choices=["face", "bust", "hips", "full"], default="full")
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
            print(f"[variants] seed {seed}: " + "; ".join(params.notes + [
                f"outfit={params.outfit}", f"hair={params.hair or 'base'} {params.palette.hair}"]))
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
        "hair_sheet": _hair_sheet,
        "generate": _generate, "variants": _variants, "export": _export}


def main() -> None:
    args = _job_args()
    if not args or args[0] not in JOBS:
        raise SystemExit(f"wogen.bl.jobs: expected one of {sorted(JOBS)}, got {args[:1]}")
    JOBS[args[0]](args[1:])
