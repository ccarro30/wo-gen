"""Motion presets (pure Python; keyed by ``wogen.bl.anim``).

A preset is a function returning keys ``(frame, pose_spec[, expression[, options]])``;
pose specs use the format in ``wogen.poses``. Generators build poses procedurally (turns,
hops, spins, sways, a walk). ``PRESET_OPTIONS`` holds the clip settings a preset needs.
"""

from __future__ import annotations

from .paths import ASSETS_DIR
from .poses import (HIPS_LOCATION, IK_PREFIX, REST_PREFIX, UPRIGHT, both, merge, plant,
                    resolve_pose, swing)

POSES_DIR = ASSETS_DIR / "poses"


def _turn(pose: str, yaw: float, tilt: float = 0.0) -> dict:
    """``pose`` with the head/neck/chest turned by ``yaw`` degrees (+ = to her left)."""
    base = resolve_pose(pose, POSES_DIR)

    def add(bone, dz, dy=0.0):
        x, y, z = base.get(bone, (0.0, 0.0, 0.0))
        return {bone: (x, y + dy, z + dz)}

    return merge(base, add("head", yaw * 0.5, tilt), add("neck", yaw * 0.3), add("chest", yaw * 0.2))


def _hop(pose: str, height: float, arms: bool = True) -> dict:
    """``pose`` with the body raised/lowered by ``height``. Below 0 the feet stay planted
    (knees bend); above 0 the feet travel with the body (use ``ground: False``).
    ``arms`` swings the arms up with the lift (off for poses that set their own arms)."""

    base = resolve_pose(pose, POSES_DIR)
    lift = max(height, 0.0)
    feet = merge(plant("left", (0.0, 0.0, lift), (0.1, -1.0, 0.0)),
                 plant("right", (0.0, 0.0, lift), (-0.1, -1.0, 0.0)))
    swing = {"left_upper_arm": (0, 72 - 300 * lift, -6), "right_upper_arm": (0, -72 + 300 * lift, -6)}
    return merge(base, feet, swing if (lift and arms) else {}, {"hips_location": (0.0, 0.0, height)})


def _add(base: dict, bone: str, d) -> dict:
    x, y, z = base.get(bone, (0.0, 0.0, 0.0))
    return {bone: (x + d[0], y + d[1], z + d[2])}


def _spin(pose: str, yaw: float) -> dict:
    """``pose`` turned ``yaw`` degrees about the vertical (hips; + = to her left). Rotating
    a bone, not the object, so hair and skirt springs feel the turn."""
    base = resolve_pose(pose, POSES_DIR)
    return merge(base, _add(base, "hips", (0.0, 0.0, yaw)))


def _sway(side: float) -> dict:
    """Idle with the weight and head tilted to one side (``side`` -1..1, + = her left)."""

    base = resolve_pose("idle", POSES_DIR)
    return merge(base, _add(base, "hips", (0, -5 * side, 0)), _add(base, "spine", (0, 7 * side, 0)),
                 _add(base, "chest", (0, 3 * side, 0)), _add(base, "head", (0, 10 * side, 3 * side)),
                 {"hips_location": (0.045 * side, 0.0, -0.012)}, plant("left"), plant("right"))


WALK_STEP, RUN_STEP = 14, 8      # frames per step
# Upper-arm swing at contact (degrees forward, back) and extra elbow bend (forward arm, back
# arm). A relaxed walk swings the arms about 15 to 20 degrees each way, elbows a little bent.
WALK_ARMS = ((22.0, 18.0), (18.0, 0.0))
# Walk shape: step length (m; a relaxed adult step is 0.55 to 0.7), pelvis shift over the
# stance foot (m) and drop toward the swing leg (deg), feet placed this far in toward the
# midline (m; a narrower track makes the hips sway more, a slightly feminine walk).
WALK_STRIDE, WALK_SHIFT, WALK_DROP, WALK_NARROW = 0.55, 0.032, 6.0, 0.03
# How far the shoulders follow the pelvis sideways (``upright``): the hips sway under a
# steadier upper body.
UPRIGHT_SHARE = 0.3
# Run: runners sway less (the body is in flight half the time) and land nearer the midline.
RUN_SHIFT, RUN_DROP, RUN_NARROW = 0.015, 4.0, 0.02
RUN_ARMS = ((26.0, 20.0), (10.0, -10.0))


def _arm_swing(base: dict, sign: float, arms) -> dict:
    """Opposite arm swing: ``sign`` +1 puts the left arm forward (right foot leading)."""
    (forward, back), (bend_fwd, bend_back) = arms
    out = {}
    for side, s, m in (("left", sign, 1.0), ("right", -sign, -1.0)):
        upper, lower = f"{side}_upper_arm", f"{side}_lower_arm"
        out[upper] = swing(base[upper], -forward if s > 0 else back)
        x, y, z = base[lower]
        out[lower] = (x, y, z - m * (bend_fwd if s > 0 else bend_back))   # left Z- bends
    return out


def _gait(steps: int, stride: float, frames_per_step: int, start: int, expression: str,
          run: bool = False, stop: bool = True) -> list[tuple]:
    """Steps forward (toward -Y, her front). Per step: a passing key (swing foot lifted beside
    the stance foot with the knee bent, body high and shifted over the stance foot, the pelvis
    dropping toward the swinging leg) and a contact key (swing foot lands heel first while the
    back heel peels up, body low), with opposite arm swing and the hips and chest twisting
    against each other; the per-frame foot pass smooths it.
    ``run`` leans forward, bends the elbows, lifts the swing foot higher and adds bounce.
    ``stop`` ends standing; otherwise the keys end on a contact (for loops)."""

    base = resolve_pose("idle", POSES_DIR)
    if run:
        base = merge(base, both({"left_lower_arm": (0, 0, -80)}),
                     {"spine": (9, 0, 0), "head": (-5, 0, 0)})
    # The body drops at contact by about what the spread legs lose in height (leg ~0.8 m).
    high, low = 0.004, -0.008 - stride ** 2 / 8.0
    lift = 0.05 if run else 0.075
    n = RUN_NARROW if run else WALK_NARROW
    narrow = {"left": -n, "right": n}
    feet = {"left": 0.0, "right": 0.0}            # forward distance of each foot (metres)
    keys = [(start, merge(base, plant("left"), plant("right")), expression)]
    frame = start + 6 + frames_per_step // 2
    for i in range(steps):
        swing = "right" if i % 2 == 0 else "left"
        stance = "left" if swing == "right" else "right"
        sign = 1.0 if swing == "right" else -1.0      # right foot forward -> left arm forward
        target = feet[stance] + (stride if i else stride / 2)
        mid = (feet[swing] + target) / 2
        if run:
            keys += _run_step(base, feet, stance, swing, target, sign, frame, frames_per_step,
                              narrow)
            feet[swing] = target
            frame += frames_per_step
            continue
        # sign +1: weight on the left foot; the pelvis shifts over it (+X) and drops on the
        # right (hips Y-, as in _sway). The pelvis turns with the leading leg (hips Z+ brings
        # the right hip forward). The spine cancels the pelvis's tilt and turn, so only the
        # hips and seat sway while the upper body stays upright (on MMD rigs the waist and
        # belly hang from the spine bone); the chest adds a slight counter-turn, so the
        # shoulders go with the forward arm.
        passing = merge(base, {
            "hips_location": (WALK_SHIFT * sign, -(feet[stance] + mid) / 2, high),
            "hips": (0, 2 - WALK_DROP * sign, 3 * sign),
            "spine": (2, -1 + WALK_DROP * sign, -3 * sign), "chest": (1, 0, -2 * sign),
            UPRIGHT: (UPRIGHT_SHARE, 0, 0)},
            plant(stance, (narrow[stance], -feet[stance], 0.0)),
            plant(swing, (narrow[swing] / 2, -mid, lift), orient=(5, 0, 0)))
        feet[swing] = target
        contact = merge(base, _arm_swing(base, sign, WALK_ARMS), {
            "hips_location": (0.0, -(feet["left"] + feet["right"]) / 2, low),
            "hips": (0, 2, 8 * sign), "spine": (2, -1, -8 * sign), "chest": (1, 0, -3 * sign),
            UPRIGHT: (UPRIGHT_SHARE, 0, 0)},
            plant(stance, (narrow[stance], -feet[stance], 0.0), orient=(25, 0, 0)),  # heel up
            plant(swing, (narrow[swing], -feet[swing], 0.0), orient=(-15, 0, 0)))   # heel strike
        keys.append((frame - frames_per_step // 2, passing, None))
        keys.append((frame, contact, None))
        frame += frames_per_step
    if not stop:
        return keys
    end = max(feet.values())
    stand = merge(resolve_pose("idle", POSES_DIR), {"hips_location": (0.0, -end, 0.0)},
                  plant("left", (0.0, -end, 0.0)), plant("right", (0.0, -end, 0.0)))
    keys.append((frame - frames_per_step // 2, stand, "smile_soft"))
    keys.append((frame + 10, stand, "smile_soft"))
    return keys


def _run_step(base, feet, stance, swing, target, sign, frame, frames_per_step, narrow):
    """One running step: passing (the swing heel tucks up under the body), flight (both feet
    off the ground, body high) and contact (lands under the body; the back foot is already
    lifting). Feet are tracked forward distances (metres, before this step's landing).
    The hips move forward at an even speed (passing, flight and contact a quarter stride
    apart): an uneven spacing surges and stalls the body every step, a 5 g jolt to the bust.
    As in the walk, the pelvis shifts over the supporting foot and drops on the free side
    (passing: the stance foot; contact: the landing foot, a little less; flight: centred)
    and turns with the leading leg, while the spine cancels both so the upper body stays
    upright and the chest only counter-turns a little."""
    t = feet[stance]
    lead = (target - t) / 4               # the foot lands this far ahead of the hips
    arms = _arm_swing(base, sign, RUN_ARMS)
    sx, sy, _ = base["spine"]

    def pelvis(side: float, turn: float) -> dict:
        """side: +1 = weight on her left foot (shift +X, drop the right hip), 0 = centred."""
        roll = -RUN_DROP * side
        return {"hips": (0, 2 + roll, turn), "spine": (sx, sy - roll, -turn),
                "chest": (1, 0, -0.4 * turn), UPRIGHT: (UPRIGHT_SHARE, 0, 0)}

    passing = merge(base, pelvis(sign, 3 * sign),
                    {"hips_location": (RUN_SHIFT * sign, -(t + lead), 0.0)},
                    plant(stance, (narrow[stance], -t, 0.0)),
                    plant(swing, (narrow[swing] / 2, -(t - 0.10), 0.24), orient=(40, 0, 0)))
    flight = merge(base, arms, pelvis(0.0, 6 * sign),
                   {"hips_location": (0.0, -(t + target) / 2, 0.05)},
                   plant(stance, (narrow[stance], -t, 0.07), orient=(40, 0, 0)),  # toes push off
                   plant(swing, (narrow[swing], -(target - 0.05), 0.06), orient=(-10, 0, 0)))
    contact = merge(base, arms, pelvis(-0.6 * sign, 6 * sign),
                    {"hips_location": (-0.6 * RUN_SHIFT * sign, -(target - lead), -0.05)},
                    plant(swing, (narrow[swing], -target, 0.0), orient=(-5, 0, 0)),
                    plant(stance, (narrow[stance], -t, 0.12), orient=(45, 0, 0)))  # back foot up
    return [(frame - frames_per_step // 2, passing, None),
            (frame - frames_per_step // 4, flight, None, {"ground": False}),
            (frame, contact, None)]


def walk_keys(steps: int = 4, stride: float = WALK_STRIDE, frames_per_step: int = WALK_STEP,
              start: int = 1, expression: str = "smile_soft") -> list[tuple]:
    """A forward walk that starts and ends standing (eyes open: ``happy`` closes them)."""
    return _gait(steps, stride, frames_per_step, start, expression)


def run_keys(steps: int = 6, stride: float = 0.62, frames_per_step: int = RUN_STEP,
             start: int = 1, expression: str = "fun") -> list[tuple]:
    """A forward run that starts and ends standing."""
    return _gait(steps, stride, frames_per_step, start, expression, run=True)


def cycle_keys(run: bool = False, cycles: int = 5) -> list[tuple]:
    """A steady gait ending on a contact, for seamless loops. Every two steps repeat exactly
    (relative to the hips), so the last ``loop`` frames (``PRESET_OPTIONS``) play as a loop;
    the earlier cycles warm up the hair and skirt springs."""
    if run:
        return _gait(1 + 2 * cycles, 0.62, RUN_STEP, 1, "fun", run=True, stop=False)
    return _gait(1 + 2 * cycles, WALK_STRIDE, WALK_STEP, 1, "smile_soft", stop=False)


def _waves(frames: list[int], expr: str) -> list[tuple]:
    tilted = merge(resolve_pose("wave"), {"right_hand": (0, 0, -25)})
    return [(f, tilted if i % 2 else "wave", expr) for i, f in enumerate(frames)]


PRESETS = {
    # Quick head turns: good for testing hair follow-through.
    "look_around": lambda: [
        (1, "idle", "neutral"), (10, _turn("idle", 50, 4), "neutral"),
        (22, _turn("idle", 50, 4), "smile_soft"), (32, _turn("idle", -50, -4), "smile_soft"),
        (44, _turn("idle", -50, -4), "neutral"), (54, "idle", "happy"), (72, "idle", "happy"),
    ],
    # Small bouncy hop in place (crouch -> up -> land).
    "hop": lambda: [
        (1, "idle", "neutral"), (8, _hop("idle", -0.07), "neutral"),
        (14, _hop("idle", 0.12), "happy", {"ground": False}),
        (20, _hop("idle", -0.06), "happy"),
        (28, "idle", "smile_soft"), (48, "idle", "smile_soft"),
    ],
    "wave_hello": lambda: [
        (1, "idle", "neutral"), *_waves([14, 22, 30, 38, 46], "happy"),
        (62, "idle", "smile_soft"), (80, "idle", "smile_soft"),
    ],
    # Crouch, jump with both arms up, land.
    "jump_for_joy": lambda: [
        (1, "idle", "neutral"), (9, _hop("idle", -0.09), "determined"),
        (16, _hop("cheer", 0.16, arms=False), "fun", {"ground": False}),
        (23, _hop("cheer", -0.07, arms=False), "happy"),
        (32, "cheer", "happy"), (44, "cheer", "happy"), (58, "idle", "smile_soft"),
        (70, "idle", "smile_soft"),
    ],
    # A full twirl on the spot; the skirt and hair swing out.
    "spin": lambda: [
        (1, "idle", "smile_soft"), (8, _spin("a_pose", 0), "happy"),
        (13, _spin("a_pose", 90), "happy"), (18, _spin("a_pose", 180), "happy"),
        (23, _spin("a_pose", 270), "happy"), (28, _spin("a_pose", 360), "happy"),
        (40, _spin("peace", 360), "wink_r"), (64, _spin("peace", 360), "wink_r"),
    ],
    # Polite bow.
    "bow": lambda: [
        (1, "idle", "smile_soft"), (18, "bow", "smile_closed_eyes"),
        (34, "bow", "smile_closed_eyes"), (50, "idle", "happy"), (66, "idle", "happy"),
    ],
    # Fingertips to the lips, then the kiss is thrown to the viewer.
    "blow_kiss": lambda: [
        (1, "idle", "smile_soft"), (14, "kiss_hand", "ou"), (24, "kiss_hand", "ou"),
        (32, "kiss_blow", "wink_r"), (48, "kiss_blow", "wink_r"), (64, "idle", "happy"),
        (76, "idle", "happy"),
    ],
    # A heart over the head with a little sway.
    "heart": lambda: [
        (1, "idle", "smile_soft"), (16, "heart_arms", "happy"),
        (28, merge(_sway(0.6), _arms_of("heart_arms")), "happy"),
        (40, merge(_sway(-0.6), _arms_of("heart_arms")), "happy"),
        (52, "heart_arms", "smile_closed_eyes"), (68, "idle", "smile_soft"),
        (80, "idle", "smile_soft"),
    ],
    # Gentle side-to-side idle sway (loops: first and last keys match).
    "sway": lambda: [
        (1, _sway(0), "smile_soft"), (25, _sway(1), "smile_soft"), (49, _sway(0), "smile_soft"),
        (73, _sway(-1), "smile_soft"), (97, _sway(0), "smile_soft"),
    ],
    # Four steps forward (the clip camera follows).
    "walk": lambda: walk_keys(),
    # Six running steps forward.
    "run": lambda: run_keys(),
    # Seamless loops of a steady walk / run (only the last cycle is rendered).
    "walk_loop": lambda: cycle_keys(),
    "run_loop": lambda: cycle_keys(run=True),
}

# Clip settings a preset needs: camera follow and spring carry for travel, physics substeps
# for fast motion. ``travel`` carries her end position into the next preset of a chain;
# ``loop`` renders only the last N frames (one seamless cycle).
PRESET_OPTIONS = {
    "walk": {"follow": True, "carry": 0.85, "travel": True},
    "run": {"follow": True, "carry": 0.9, "substeps": 2, "travel": True},
    "walk_loop": {"follow": True, "carry": 0.85, "loop": 2 * WALK_STEP},
    "run_loop": {"follow": True, "carry": 0.9, "substeps": 2, "loop": 2 * RUN_STEP},
    "spin": {"substeps": 3},
}

CHAIN_GAP = 10      # frames between one preset's last pose and the next preset's first


def shift(spec, dx: float, dy: float) -> dict:
    """A pose moved along the floor: hips and floor-anchored (``rest:``) IK targets."""
    pose = resolve_pose(spec, POSES_DIR)
    out = dict(pose)
    hx, hy, hz = pose.get(HIPS_LOCATION, (0.0, 0.0, 0.0))
    out[HIPS_LOCATION] = (hx + dx, hy + dy, hz)
    for name, entry in pose.items():
        if name.startswith(IK_PREFIX) and entry["target"].startswith(REST_PREFIX):
            ox, oy, oz = entry["offset"]
            out[name] = {**entry, "offset": (ox + dx, oy + dy, oz)}
    return out


def chain(names: list[str], gap: int = CHAIN_GAP) -> tuple[list[tuple], dict]:
    """Presets one after another, with ``gap`` frames of transition between them.

    A trailing hold (last two keys identical) is dropped so the next preset starts moving
    right away; after a travelling preset (walk, run) the rest happens where she stopped.
    Returns (keys, clip options merged from all presets). Loops can't be chained.
    """
    keys: list[tuple] = []
    root = (0.0, 0.0)
    options: dict = {}
    for name in names:
        opts = PRESET_OPTIONS.get(name, {})
        if "loop" in opts:
            raise ValueError(f"{name} is a loop and can't be part of a chain")
        if len(keys) > 1:
            drop_trailing_hold(keys)
        part = placed(PRESETS[name](), keys[-1][0] + gap if keys else part_start(name), root)
        keys += part
        if opts.get("travel"):
            root = end_root(part)
        options = merge_options(options, opts)
    return keys, options


def part_start(name: str) -> int:
    return PRESETS[name]()[0][0]


def placed(part: list[tuple], start: int, root: tuple[float, float]) -> list[tuple]:
    """A preset's keys moved in time (first key at ``start``) and along the floor (``root``)."""
    offset = start - part[0][0]
    return [(k[0] + offset, shift(k[1], *root) if root != (0.0, 0.0) else k[1], *k[2:])
            for k in part]


def drop_trailing_hold(keys: list[tuple]) -> None:
    """Drop the last key if it only holds the one before (so the next part starts moving)."""
    if len(keys) > 1 and keys[-1][1:] == keys[-2][1:]:
        keys.pop()


def end_root(keys: list[tuple]) -> tuple[float, float]:
    """Where the last key leaves her on the floor (the hips' horizontal offset)."""
    hips = resolve_pose(keys[-1][1], POSES_DIR).get(HIPS_LOCATION, (0.0, 0.0, 0.0))
    return (hips[0], hips[1])


def merge_options(options: dict, opts: dict) -> dict:
    """Clip options of a chain: follow/travel if any part needs it; the larger carry/substeps."""
    out = dict(options)
    for k, v in opts.items():
        if k in ("follow", "travel"):
            out[k] = out.get(k, False) or v
        elif k != "loop":
            out[k] = max(out.get(k, 0), v)
    return out


MOCAP_PREFIX = "mocap:"
MOCAP_OPTIONS = {"follow": True, "carry": 0.85, "substeps": 2, "travel": True}


def parse_chain(name: str) -> list[tuple]:
    """Chain tokens -> segments: ``("preset", name)`` or ``("mocap", clip, start_s, end_s)``.

    Mocap tokens are ``mocap:CLIP`` or ``mocap:CLIP@START-END`` (seconds; either side may be
    empty), e.g. ``"wave_hello,mocap:happy_walk,bow"`` or ``"mocap:salsa@2-6"``.
    """
    segments = []
    tokens = [t.strip() for t in name.split(",") if t.strip()]
    if not tokens:
        raise KeyError(f"No preset given; choose from {sorted(PRESETS)}")
    for token in tokens:
        if token.startswith(MOCAP_PREFIX):
            clip, _, span = token[len(MOCAP_PREFIX):].partition("@")
            start_s, end_s = 0.0, None
            if span:
                a, sep, b = span.partition("-")
                if not sep:
                    raise ValueError(f"{token}: trim with @START-END seconds, e.g. @2-6")
                start_s, end_s = float(a or 0.0), (float(b) if b else None)
            if not clip:
                raise ValueError(f"{token}: missing clip name")
            segments.append(("mocap", clip, start_s, end_s))
        elif token in PRESETS:
            if "loop" in PRESET_OPTIONS.get(token, {}) and len(tokens) > 1:
                raise ValueError(f"{token} is a loop and can't be part of a chain")
            segments.append(("preset", token))
        else:
            raise KeyError(f"Unknown preset {token!r}; choose from {sorted(PRESETS)} "
                           f"or {MOCAP_PREFIX}CLIP ('wogen mocap' lists the clips)")
    return segments


def build(name: str) -> tuple[list[tuple], dict]:
    """Keys and clip options for a preset name, or several joined by commas (a chain).
    Chains with mocap segments are built in Blender (``wogen.bl.anim.preset``)."""
    segments = parse_chain(name)
    if any(s[0] == "mocap" for s in segments):
        raise ValueError(f"{name!r} contains mocap segments: build it with wogen.bl.anim.preset")
    names = [s[1] for s in segments]
    if len(names) == 1:
        return PRESETS[names[0]](), dict(PRESET_OPTIONS.get(names[0], {}))
    return chain(names)


def _arms_of(pose: str) -> dict:
    """Only the arm/hand entries (bones and IK) of a library pose."""
    keep = ("shoulder", "upper_arm", "lower_arm", "hand", "thumb", "index", "middle", "ring", "little")
    return {k: v for k, v in resolve_pose(pose, POSES_DIR).items()
            if any(part in k for part in keep) and "foot" not in k}
