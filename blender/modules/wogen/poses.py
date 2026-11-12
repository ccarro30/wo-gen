"""Pose library (pure Python; applied by ``wogen.bl.pose``).

Pose format: ``{humanoid_bone: (x, y, z)}`` in degrees. Bone names are VRM humanoid names in
snake_case (``left_upper_arm``, ``head``, ``right_index_proximal``...). Each value rotates the
bone *relative to the T-pose rest*, about the armature axes, applied X then Y then Z.
Children inherit their parents' rotations.

Axes (character faces -Y, character's left is +X, up is +Z). Signs for the LEFT side
(right side is the mirror: ``(x, y, z) -> (x, -y, -z)``):

=====================  =======================================================
spine/chest/neck/head  X+ bend/nod forward, Y+ lean to her left, Z+ turn to her left
left_upper_arm         Y+ lowers the arm, Z- swings it forward, Z+ back, X twists
                       (lowered arms: ``swing()`` for forward/back)
left_lower_arm         Z- bends the elbow forward (forearm toward the front)
left_hand              Y+ flexes the palm down, Z- bends the hand forward
left fingers           Y+ curls toward the palm, Z- spreads toward the front
left_upper_leg         X- lifts the leg forward, Y+ moves it outward (to her left)
left_lower_leg         X+ bends the knee (foot goes back)
=====================  =======================================================

``hips_location`` (metres, armature axes) shifts the whole body, e.g. to sit or crouch.

IK entries place a hand or foot (two-bone limb chain) at a point relative to an anchor::

    "ik:left_hand": {"target": "left_upper_leg", "offset": (0.08, 0.0, 0.07),
                     "pole": (1.0, 0.6, 0.0)}
    "ik:right_foot": {"target": "rest:right_foot", "offset": (0.0, 0.25, 0.05),
                      "pole": (0.0, -1.0, 0.0), "orient": (-50, 0, 0)}

``target`` is a humanoid bone whose *posed* head is the anchor, or ``rest:<bone>`` for that
joint's rest position (a fixed spot on the floor, unaffected by ``hips_location``).
``offset`` is in metres along the armature axes; ``pole`` is the direction the elbow/knee
points. ``orient`` (degrees, armature axes, relative to rest) sets the end bone's absolute
orientation; feet default to ``(0, 0, 0)`` (flat), hands keep their relative rotation.
For feet, X+ tips the toes down (heel up).

IK runs after rotations and ``hips_location``; feet are solved before hands, so hands can
target knees (``left_lower_leg``).
"""

from __future__ import annotations

import math
import tomllib
from pathlib import Path
from typing import Union

Euler = tuple[float, float, float]
Pose = dict[str, Union[Euler, dict]]
PoseSpec = Union[str, Pose, list]

HIPS_LOCATION = "hips_location"
IK_PREFIX = "ik:"
REST_PREFIX = "rest:"
IK_CHAINS = {f"{side}_{end}" for side in ("left", "right") for end in ("hand", "foot")}


def ik(side: str, target: str, offset: Euler, pole: Euler, limb: str = "hand",
       orient: Euler | None = None) -> Pose:
    """IK entry placing ``side`` hand/foot at ``target`` anchor + ``offset``."""
    entry = {"target": target, "offset": tuple(offset), "pole": tuple(pole)}
    if orient is not None:
        entry["orient"] = tuple(orient)
    return {f"{IK_PREFIX}{side}_{limb}": entry}


def plant(side: str, offset: Euler = (0.0, 0.0, 0.0), pole: Euler = (0.0, -1.0, 0.0),
          orient: Euler | None = None) -> Pose:
    """Foot IK anchored to its rest spot on the floor (+ offset). Knee points forward."""
    return ik(side, f"{REST_PREFIX}{side}_foot", offset, pole, "foot", orient)
FINGERS = ("thumb", "index", "middle", "ring", "little")
FINGER_SEGMENTS = {
    "thumb": ("metacarpal", "proximal", "distal"),
    **{f: ("proximal", "intermediate", "distal") for f in FINGERS[1:]},
}


# ---------------------------------------------------------------- helpers

def mirror_name(name: str) -> str:
    if name.startswith(REST_PREFIX):
        return REST_PREFIX + mirror_name(name[len(REST_PREFIX):])
    if name.startswith("left_"):
        return "right_" + name[5:]
    if name.startswith("right_"):
        return "left_" + name[6:]
    return name


def mirror_euler(e: Euler) -> Euler:
    return (e[0], -e[1], -e[2])


def mirror(pose: Pose) -> Pose:
    """Swap left/right (and mirror centre bones)."""
    out: Pose = {}
    for name, e in pose.items():
        if name == HIPS_LOCATION:
            out[name] = (-e[0], e[1], e[2])
        elif name.startswith(IK_PREFIX):
            flip = lambda v: (-v[0], v[1], v[2])  # noqa: E731 - reflect across the YZ plane
            entry = {"target": mirror_name(e["target"]), "offset": flip(e["offset"]),
                     "pole": flip(e["pole"])}
            if "orient" in e:
                entry["orient"] = mirror_euler(e["orient"])
            out[IK_PREFIX + mirror_name(name[len(IK_PREFIX):])] = entry
        else:
            out[mirror_name(name)] = mirror_euler(e)
    return out


def _is_left(key: str) -> bool:
    return key.startswith("left_") or key.startswith(IK_PREFIX + "left_")


def both(left: Pose) -> Pose:
    """A left-side pose plus its mirror on the right."""
    return {**left, **mirror({k: v for k, v in left.items() if _is_left(k)})}


def _matrix(e: Euler) -> list[list[float]]:
    """Rotation matrix of an XYZ euler in degrees (X applied first: Rz @ Ry @ Rx)."""
    cx, cy, cz = (math.cos(math.radians(a)) for a in e)
    sx, sy, sz = (math.sin(math.radians(a)) for a in e)
    return [[cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
            [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
            [-sy, sx * cy, cx * cy]]


def _euler(m: list[list[float]]) -> Euler:
    y = math.asin(max(-1.0, min(1.0, -m[2][0])))
    if abs(math.cos(y)) > 1e-6:
        x, z = math.atan2(m[2][1], m[2][2]), math.atan2(m[1][0], m[0][0])
    else:                                           # gimbal lock: put it all in X
        x, z = math.atan2(-m[1][2], m[1][1]), 0.0
    return (math.degrees(x), math.degrees(y), math.degrees(z))


def swing(e: Euler, pitch: float) -> Euler:
    """``e`` followed by a turn of ``pitch`` degrees about the left-right (X) axis. X- swings
    a lowered arm forward on either side. (A lowered arm hangs nearly along Z, so its own Z
    only twists it a little: 20 degrees of Z move it about 6 degrees forward.)"""
    a, b = _matrix((pitch, 0.0, 0.0)), _matrix(e)
    return _euler([[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)])


def hand(side: str, curls: dict[str, tuple[float, float, float]],
         spread: dict[str, float] | None = None,
         thumb: tuple[Euler, Euler, Euler] | None = None) -> Pose:
    """Hand shape for ``side`` ('left'/'right'): per-finger curl of each segment (degrees).

    ``thumb`` gives explicit eulers (left-side convention) for the metacarpal, proximal and
    distal segments and overrides any thumb curl. A thumb that folds across the palm can't be
    expressed as a single curl angle; solve it with ``wogen.bl.pose.solve_thumb``.
    """
    pose: Pose = {}
    for finger, angles in curls.items():
        for seg, angle in zip(FINGER_SEGMENTS[finger], angles):
            spread_z = (spread or {}).get(finger, 0.0) if seg in ("metacarpal", "proximal") else 0.0
            if finger == "thumb":
                pose[f"left_{finger}_{seg}"] = (0.0, angle * 0.5, -angle)   # small curls only
            else:
                pose[f"left_{finger}_{seg}"] = (0.0, angle, spread_z)
    if thumb is not None:
        for seg, e in zip(FINGER_SEGMENTS["thumb"], thumb):
            pose[f"left_thumb_{seg}"] = tuple(e)
    return pose if side == "left" else mirror(pose)


def merge(*poses: Pose) -> Pose:
    """Later poses override earlier ones bone by bone."""
    out: Pose = {}
    for p in poses:
        out.update(p)
    return out


# ---------------------------------------------------------------- hand shapes

# Folded thumbs were solved with wogen.bl.pose.solve_thumb on base_f01 (thumb tip resting on
# the palm side of the named curled fingers' middle segments); they hold for generated bodies.
HANDS = {
    "relaxed": dict(curls={"index": (10, 18, 10), "middle": (15, 22, 12),
                           "ring": (18, 25, 14), "little": (22, 28, 16)},
                    thumb=((0, 9, 13), (0, 0, 52), (0, 0, 0))),               # along the index
    "fist": dict(curls={"index": (75, 95, 60), "middle": (80, 95, 60),
                        "ring": (80, 95, 60), "little": (80, 95, 60)},
                 thumb=((11, -1, -1), (90, -4, 56), (0, 7, 4))),          # over index + middle
    "peace": dict(curls={"index": (0, 0, 0), "middle": (0, 0, 0),
                         "ring": (80, 95, 60), "little": (80, 95, 60)},
                  spread={"index": -8, "middle": 8},
                  thumb=((-8, -3, 30), (56, -14, 78), (0, 21, 6))),       # over the ring finger
    "point": dict(curls={"index": (0, 0, 0), "middle": (80, 95, 60),
                         "ring": (80, 95, 60), "little": (80, 95, 60)},
                  thumb=((21, 0, -1), (90, -6, 70), (0, 7, 15))),         # over the middle finger
    "open": dict(curls={"thumb": (0, 0, 0), "index": (0, 0, 0), "middle": (0, 0, 0),
                        "ring": (0, 0, 0), "little": (0, 0, 0)},
                 spread={"index": -8, "middle": -2, "ring": 4, "little": 10}),
}


def hand_shape(name: str, side: str) -> Pose:
    return hand(side, **HANDS[name])


# ---------------------------------------------------------------- body poses

ARMS_DOWN = both({"left_upper_arm": (0, 72, -6), "left_lower_arm": (0, 0, -10),
                  "left_hand": (0, 4, 0)})

RELAXED_HANDS = merge(hand_shape("relaxed", "left"), hand_shape("relaxed", "right"))

POSES: dict[str, Pose] = {
    "t_pose": {},
    "a_pose": both({"left_upper_arm": (0, 68, 0)}),
    "idle": merge(
        ARMS_DOWN, RELAXED_HANDS,
        {"spine": (2, -1, 0), "chest": (1, 0, 0), "neck": (2, 0, 0), "head": (2, 3, 2),
         "hips": (0, 2, 0)},
    ),
    "hands_on_hips": merge(
        RELAXED_HANDS,
        both({**ik("left", "left_upper_leg", (0.09, 0.01, 0.10), (1.0, 0.8, 0.0)),
              "left_hand": (0, 0, 0)}),
        {"chest": (-2, 0, 0), "head": (0, -3, 0)},
    ),
    "peace": merge(
        ARMS_DOWN, hand_shape("relaxed", "left"), hand_shape("peace", "right"),
        ik("right", "head", (-0.17, -0.10, -0.01), (-1.0, 0.3, -1.0)),
        {"head": (0, -6, -4), "spine": (0, 2, 0)},
    ),
    "wave": merge(
        ARMS_DOWN, hand_shape("relaxed", "left"), hand_shape("open", "right"),
        ik("right", "head", (-0.27, -0.06, -0.03), (-1.0, 0.3, -1.0)),
        {"head": (0, -4, -3)},
    ),
    "shy": merge(
        RELAXED_HANDS,
        both(ik("left", "hips", (0.02, -0.15, -0.07), (1.0, 0.4, -0.3))),
        {"spine": (4, 0, 0), "neck": (6, 0, 0), "head": (8, 6, 3)},
    ),
    "hand_on_chest": merge(
        ARMS_DOWN, RELAXED_HANDS,
        ik("right", "upper_chest", (-0.05, -0.15, -0.02), (-1.0, 0.2, -1.0)),
        {"head": (3, 4, 0)},
    ),
    "thinking": merge(
        hand_shape("relaxed", "left"), hand_shape("fist", "right"),
        ik("left", "spine", (-0.06, -0.15, 0.04), (1.0, 0.0, -1.0)),
        ik("right", "head", (-0.02, -0.11, -0.08), (-0.6, 0.2, -1.0)),
        {"head": (4, -6, -6)},
    ),
    # ---- expressive upper body (used by the motion presets; fine as stills too)
    "bow": merge(   # polite bow, hands together in front
        RELAXED_HANDS,
        both(ik("left", "hips", (0.03, -0.17, -0.12), (1.0, 0.3, -0.5))),
        {"hips": (16, 0, 0), "spine": (10, 0, 0), "chest": (6, 0, 0), "neck": (4, 0, 0),
         "head": (6, 0, 0), HIPS_LOCATION: (0.0, 0.06, -0.01)},   # hinge at the hips
        plant("left"), plant("right"),
    ),
    "cheer": merge(   # both arms up, open hands
        hand_shape("open", "left"), hand_shape("open", "right"),
        both({"left_upper_arm": (0, -55, -8), "left_lower_arm": (0, 0, -20)}),
        {"chest": (-6, 0, 0), "neck": (-4, 0, 0), "head": (-6, 0, 0)},
    ),
    "heart_arms": merge(   # arms form a heart over the head, fingertips touching
        hand_shape("relaxed", "left"), hand_shape("relaxed", "right"),
        both(ik("left", "head", (0.07, 0.0, 0.23), (1.0, 0.3, 0.6))),
        {"head": (0, 6, 0), "spine": (0, 2, 0)},
    ),
    "kiss_hand": merge(   # fingertips of her right hand at her lips
        ARMS_DOWN, hand_shape("relaxed", "left"), hand_shape("relaxed", "right"),
        ik("right", "head", (-0.02, -0.12, -0.06), (-0.6, 0.3, -1.0)),
        {"head": (2, -4, 0)},
    ),
    "kiss_blow": merge(   # ...then thrown toward the viewer
        ARMS_DOWN, hand_shape("relaxed", "left"), hand_shape("open", "right"),
        ik("right", "upper_chest", (-0.05, -0.44, 0.10), (-1.0, 0.0, -0.4)),
        {"head": (0, -6, -4), "chest": (0, 0, -6)},
    ),
    # ---- lower body (feet planted with IK; hips_location moves the body)
    "contrapposto": merge(   # weight on her right leg, left knee relaxed
        ARMS_DOWN, RELAXED_HANDS,
        {HIPS_LOCATION: (-0.035, 0.0, -0.012), "hips": (0, 6, 3), "spine": (1, -4, -2),
         "chest": (0, -3, 0), "neck": (2, 2, 0), "head": (2, 5, 3)},
        plant("right"), plant("left", (0.015, -0.06, 0.0), (0.3, -1.0, 0.0), (0, 0, 8)),
    ),
    "stride": merge(   # mid-step: left foot forward, right heel up
        both({"left_upper_arm": (0, 72, 0), "left_lower_arm": (0, 0, -15)}), RELAXED_HANDS,
        {"left_upper_arm": (0, 72, 18), "right_upper_arm": (0, -72, 18),   # arm swing
         HIPS_LOCATION: (0.0, 0.0, -0.025), "hips": (0, 0, 5), "chest": (0, 0, -6)},
        plant("left", (0.0, -0.20, 0.0)),
        plant("right", (0.0, 0.20, 0.035), orient=(28, 0, 0)),
    ),
    "crouch": merge(   # knees together, forearms resting on the knees
        RELAXED_HANDS,
        both(ik("left", "left_lower_leg", (-0.03, -0.08, 0.02), (1.0, 0.0, -0.5))),
        {HIPS_LOCATION: (0.0, 0.12, -0.45), "spine": (22, 0, 0), "chest": (12, 0, 0),
         "neck": (-10, 0, 0), "head": (-12, 4, 0)},
        plant("left", (-0.01, -0.02, 0.0), (0.05, -1.0, 0.0), (10, 0, 0)),
        plant("right", (0.01, -0.02, 0.0), (-0.05, -1.0, 0.0), (10, 0, 0)),
    ),
    "kneel": merge(   # right knee down, left foot forward
        RELAXED_HANDS,
        {"left_upper_arm": (0, 70, -10), "right_upper_arm": (0, -72, 0),
         "right_lower_arm": (0, 0, 10)},
        ik("left", "left_lower_leg", (0.0, -0.04, 0.03), (1.0, 0.2, -0.3)),
        {HIPS_LOCATION: (0.0, 0.05, -0.44), "spine": (4, 0, 0), "head": (2, 3, 0)},
        plant("left", (0.0, -0.36, 0.0), (0.2, -1.0, 0.0)),
        plant("right", (0.0, 0.40, 0.06), orient=(70, 0, 0)),
    ),
    "sit_chair": merge(   # pair with props.seat(height=0.45)
        both({"left_upper_arm": (0, 66, -20), "left_lower_arm": (0, 0, -40)}), RELAXED_HANDS,
        both(ik("left", "left_upper_leg", (0.03, -0.24, 0.04), (1.0, 0.2, 0.0))),
        {HIPS_LOCATION: (0.0, 0.0, -0.43), "spine": (-4, 0, 0), "chest": (3, 0, 0),
         "head": (3, 3, 0)},
        plant("left", (0.03, -0.38, 0.0)), plant("right", (-0.03, -0.38, 0.0)),
    ),
    "sit_floor": merge(   # sitting on the floor hugging the knees
        RELAXED_HANDS,
        both(ik("left", "left_lower_leg", (-0.06, -0.10, -0.14), (1.0, 0.3, -1.0))),
        {HIPS_LOCATION: (0.0, 0.10, -0.80), "spine": (12, 0, 0), "chest": (6, 0, 0),
         "head": (-4, 6, 0)},
        plant("left", (-0.01, -0.28, 0.0), (0.15, -0.6, 1.0)),
        plant("right", (0.01, -0.28, 0.0), (-0.15, -0.6, 1.0)),
    ),
}


# ---------------------------------------------------------------- resolution & files

def list_poses(extra_dir: Path | None = None) -> list[str]:
    names = set(POSES)
    if extra_dir and extra_dir.is_dir():
        names |= {p.stem for p in extra_dir.glob("*.toml")}
    return sorted(names)


def resolve_pose(spec: PoseSpec, extra_dir: Path | None = None) -> Pose:
    """Pose name, pose dict, or list of those (merged left to right)."""
    if isinstance(spec, list):
        return merge(*(resolve_pose(s, extra_dir) for s in spec))
    if isinstance(spec, dict):
        return _normalize(spec)
    if spec in POSES:
        return dict(POSES[spec])
    if spec.startswith("hand:"):   # e.g. "hand:peace:left"
        _, shape, side = spec.split(":")
        return hand_shape(shape, side)
    if spec.startswith("mirror:"):
        return mirror(resolve_pose(spec[len("mirror:"):], extra_dir))
    if extra_dir is not None and (extra_dir / f"{spec}.toml").is_file():
        return load_pose(extra_dir / f"{spec}.toml")
    raise KeyError(f"Unknown pose {spec!r}. Poses: {', '.join(list_poses(extra_dir))}")


def _normalize(pose: dict) -> Pose:
    out: Pose = {}
    for k, v in pose.items():
        if k.startswith(IK_PREFIX):
            out[k] = {"target": v["target"],
                      "offset": tuple(float(c) for c in v["offset"]),
                      "pole": tuple(float(c) for c in v.get("pole", (0.0, 0.0, -1.0)))}
            if "orient" in v:
                out[k]["orient"] = tuple(float(c) for c in v["orient"])
        else:
            out[k] = tuple(float(c) for c in v)
    return out


def load_pose(path: Path) -> Pose:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    pose = dict(data.get("bones", {}))
    for hand_name, entry in data.get("ik", {}).items():
        pose[IK_PREFIX + hand_name] = entry
    return _normalize(pose)


def _vec(v) -> str:
    return "[" + ", ".join(str(round(float(c), 4)) for c in v) + "]"


def dump_pose(pose: Pose, description: str = "") -> str:
    """TOML text: [bones] rotations, plus [ik.<hand>] tables for IK entries."""
    lines = []
    if description:
        lines.append("description = " + '"' + description.replace('"', "'") + '"')
        lines.append("")
    lines.append("[bones]")
    for name in sorted(k for k in pose if not k.startswith(IK_PREFIX)):
        lines.append(f"{name} = {_vec(pose[name])}")
    for name in sorted(k for k in pose if k.startswith(IK_PREFIX)):
        e = pose[name]
        lines += ["", f"[ik.{name[len(IK_PREFIX):]}]", f'target = "{e["target"]}"',
                  f"offset = {_vec(e['offset'])}", f"pole = {_vec(e['pole'])}"]
        if "orient" in e:
            lines.append(f"orient = {_vec(e['orient'])}")
    return "\n".join(lines) + "\n"
