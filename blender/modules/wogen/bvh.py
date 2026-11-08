"""BVH motion files: parsing and a small motion catalog (pure Python).

The catalog is ``assets/mocap/manifest.json`` (clip name -> BVH file from the pinned source);
``scripts/update-mocap.ps1`` downloads the files into ``assets/mocap/cmu/``. Retargeting onto
the character lives in ``wogen.bl.mocap``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .paths import ASSETS_DIR

MOCAP_DIR = ASSETS_DIR / "mocap"
MANIFEST = MOCAP_DIR / "manifest.json"
CLIP_DIR = MOCAP_DIR / "cmu"

# CMU (cgspeed MotionBuilder-friendly names) joint -> VRM humanoid bone. Unmapped joints in
# between (LHipJoint, Neck1, LeftFingerBase, ...) are absorbed: retargeting works on world
# rotations, so only the mapped joints' orientations matter.
CMU_TO_HUMANOID = {
    "Hips": "hips",
    "LowerBack": "spine", "Spine": "chest", "Spine1": "upper_chest",
    "Neck": "neck", "Head": "head",
    **{f"{s}Shoulder": f"{side}_shoulder" for s, side in (("Left", "left"), ("Right", "right"))},
    **{f"{s}Arm": f"{side}_upper_arm" for s, side in (("Left", "left"), ("Right", "right"))},
    **{f"{s}ForeArm": f"{side}_lower_arm" for s, side in (("Left", "left"), ("Right", "right"))},
    **{f"{s}Hand": f"{side}_hand" for s, side in (("Left", "left"), ("Right", "right"))},
    **{f"{s}UpLeg": f"{side}_upper_leg" for s, side in (("Left", "left"), ("Right", "right"))},
    **{f"{s}Leg": f"{side}_lower_leg" for s, side in (("Left", "left"), ("Right", "right"))},
    **{f"{s}Foot": f"{side}_foot" for s, side in (("Left", "left"), ("Right", "right"))},
    **{f"{s}ToeBase": f"{side}_toes" for s, side in (("Left", "left"), ("Right", "right"))},
}


@dataclass
class Joint:
    name: str
    parent: int | None
    offset: tuple[float, float, float]
    channels: list[str] = field(default_factory=list)
    first_channel: int = 0          # index of this joint's first value in a frame row


@dataclass
class Motion:
    joints: list[Joint]
    frames: list[list[float]]
    frame_time: float               # seconds

    @property
    def fps(self) -> float:
        return 1.0 / self.frame_time

    def index(self, name: str) -> int:
        return next(i for i, j in enumerate(self.joints) if j.name == name)

    def channels(self, joint: int, frame: int) -> dict[str, float]:
        """``{"Xposition": .., "Zrotation": .., ...}`` for one joint at one frame."""
        j = self.joints[joint]
        row = self.frames[frame]
        return {c: row[j.first_channel + k] for k, c in enumerate(j.channels)}


def parse(text: str) -> Motion:
    tokens = text.split()
    pos = 0

    def take() -> str:
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    if take() != "HIERARCHY":
        raise ValueError("Not a BVH file (no HIERARCHY)")
    joints: list[Joint] = []
    stack: list[int | None] = []
    channel_count = 0
    current: int | None = None
    while True:
        tok = take()
        if tok in ("ROOT", "JOINT"):
            joints.append(Joint(take(), stack[-1] if stack else None, (0.0, 0.0, 0.0)))
            current = len(joints) - 1
        elif tok == "End":
            take()                  # "Site"
            current = None          # end sites carry no channels
        elif tok == "{":
            stack.append(current)
        elif tok == "}":
            stack.pop()
        elif tok == "OFFSET":
            offset = (float(take()), float(take()), float(take()))
            if current is not None:
                joints[current].offset = offset
        elif tok == "CHANNELS":
            n = int(take())
            joints[current].channels = [take() for _ in range(n)]
            joints[current].first_channel = channel_count
            channel_count += n
        elif tok == "MOTION":
            break
        else:
            raise ValueError(f"Unexpected BVH token {tok!r}")
    if take() != "Frames:":
        raise ValueError("BVH: expected 'Frames:'")
    count = int(take())
    if (take(), take()) != ("Frame", "Time:"):
        raise ValueError("BVH: expected 'Frame Time:'")
    frame_time = float(take())
    values = [float(v) for v in tokens[pos:pos + count * channel_count]]
    if len(values) != count * channel_count:
        raise ValueError(f"BVH: expected {count} frames x {channel_count} channels")
    frames = [values[i * channel_count:(i + 1) * channel_count] for i in range(count)]
    return Motion(joints, frames, frame_time)


def load(path: str | Path) -> Motion:
    return parse(Path(path).read_text(encoding="utf-8", errors="replace"))


def catalog() -> dict[str, dict]:
    """Clip name -> manifest entry plus ``path`` and ``available`` (downloaded)."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = {}
    for name, entry in data["clips"].items():
        path = CLIP_DIR / Path(entry["file"]).name
        out[name] = {**entry, "path": path, "available": path.is_file()}
    return out


def clip_path(name: str) -> Path:
    """Path of a catalog clip (or any existing .bvh path)."""
    if name.lower().endswith(".bvh") and Path(name).is_file():
        return Path(name)
    clips = catalog()
    if name not in clips:
        raise KeyError(f"Unknown mocap clip {name!r}; choose from {sorted(clips)}")
    if not clips[name]["available"]:
        raise FileNotFoundError(f"{clips[name]['path']} is missing: run scripts\\update-mocap.ps1")
    return clips[name]["path"]


def sample_frames(motion: Motion, fps: float, start: float = 0.0, end: float | None = None,
                  skip_first: bool = True) -> list[int]:
    """Source frame indices for output at ``fps`` between ``start``/``end`` seconds of the
    motion (nearest frame). ``skip_first`` drops frame 0 (the T-pose in cgspeed files)."""
    first = 1 if skip_first else 0
    duration = (len(motion.frames) - 1 - first) * motion.frame_time
    end = duration if end is None else min(end, duration)
    out, t = [], start
    while t <= end + 1e-9:
        out.append(first + round(t / motion.frame_time))
        t += 1.0 / fps
    return out
