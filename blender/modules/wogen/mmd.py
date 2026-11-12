"""MMD (PMX) models: skeleton mapping to VRM humanoid names, and model discovery.

Pure Python (no bpy), so it's unit-tested. ``wogen.bl.mmd_import`` imports a PMX with the
mmd_tools add-on, stores ``humanoid_map`` on the armature, and turns the A-pose rest into
the T-pose rest the rest of wogen assumes (poses, IK and mocap are relative to a T-pose).

Names are the mmd_tools forms of the MMD semi-standard skeleton: the side moves from a
左/右 prefix to a ``.L``/``.R`` suffix (左腕 -> 腕.L). The controllers that poses rotate are
the FK bones (足.L, not the D-bones that carry the skin weights): mmd_tools drives the
D-bones from them.

The model packages are officially released character models (personal use; see
``assets/LICENSES.md``): no redistribution, no sexual or offensive content.
"""

from __future__ import annotations

from pathlib import Path

# humanoid name -> candidate MMD bone names (first one present wins). Spine, chest and
# upper chest come from the 上半身 chain instead (``humanoid_map``), since models differ in
# how many 上半身 bones they have.
_SIDED = {
    "shoulder": ("肩",), "upper_arm": ("腕",), "lower_arm": ("ひじ",), "hand": ("手首",),
    "upper_leg": ("足",), "lower_leg": ("ひざ",), "foot": ("足首",), "toes": ("足先EX",),
    "eye": ("目",),
    "thumb_metacarpal": ("親指０",), "thumb_proximal": ("親指１",), "thumb_distal": ("親指２",),
    "index_proximal": ("人指１",), "index_intermediate": ("人指２",), "index_distal": ("人指３",),
    "middle_proximal": ("中指１",), "middle_intermediate": ("中指２",), "middle_distal": ("中指３",),
    "ring_proximal": ("薬指１",), "ring_intermediate": ("薬指２",), "ring_distal": ("薬指３",),
    "little_proximal": ("小指１",), "little_intermediate": ("小指２",), "little_distal": ("小指３",),
}
_CENTRAL = {"hips": ("腰", "グルーブ", "センター"), "neck": ("首",), "head": ("頭",)}
SPINE_ROOT = "上半身"
REQUIRED = ("hips", "spine", "neck", "head", "left_upper_arm", "left_lower_arm", "left_hand",
            "right_upper_arm", "right_lower_arm", "right_hand", "left_upper_leg",
            "left_lower_leg", "left_foot", "right_upper_leg", "right_lower_leg", "right_foot")
# T-pose conversion: these chains are posed straight along +-X, then baked into the rest.
ARM_CHAIN = ("upper_arm", "lower_arm", "hand")
# The IK controllers mmd_tools adds; wogen solves legs itself, so their constraints are muted.
IK_BONES = ("足ＩＫ", "つま先ＩＫ")
IK_LIMIT_CONSTRAINT = "mmd_ik_limit_override"   # mmd_tools' knee limit for its leg IK
# Waist-cancel bones (between 下半身 and 足) undo 腰's rotation for the legs, an MMD motion
# convenience; wogen turns the pelvis as a whole, so their constraints are muted.
CANCEL_BONES = ("腰キャンセル",)
PROP_HINTS = ("武器",)      # weapon packages and the like ship as separate PMX files
# Deform (D) bones copy their FK bone's rotation through mmd_tools constraints; children
# of a D-bone (足先EX under 足首D) move with the FK bone, not with the D-bone's parent.
D_BONES = {"足D": "足", "ひざD": "ひざ", "足首D": "足首"}


def follow_map(bones) -> dict[str, str]:
    """D-bone -> the FK bone it copies, for the sided D-bones present in ``bones``."""
    out = {}
    for side in ("left", "right"):
        for d, fk in D_BONES.items():
            if _side(d, side) in bones and _side(fk, side) in bones:
                out[_side(d, side)] = _side(fk, side)
    return out


def _side(name: str, side: str) -> str:
    return f"{name}.{'L' if side == 'left' else 'R'}"


BUST_HINTS = ("胸", "おっぱい", "乳")


def is_bust(original: str) -> bool:
    return any(h in original for h in BUST_HINTS)


def bust_bones(bones: dict[str, str | None], originals: dict[str, str], driven,
               weights: dict[str, float]) -> list[str]:
    """Per side, the physics-``driven`` bust bone carrying the most breast skin (its own
    vertex ``weights`` plus its descendants'); on a tie the one nearer the root. The side
    comes from a ``.L``/``.R`` suffix or 左/右 in the original name. ``originals`` maps
    current (translated) names to the model's own."""
    children: dict[str | None, list[str]] = {}
    for name, parent in bones.items():
        children.setdefault(parent, []).append(name)

    def skin(name: str) -> float:
        return weights.get(name, 0.0) + sum(skin(c) for c in children.get(name, ()))

    def depth(name: str) -> int:
        return 0 if bones.get(name) is None else 1 + depth(bones[name])

    best: dict[str, tuple] = {}
    for name in driven:
        original = originals.get(name, name)
        if name not in bones or not is_bust(original):
            continue
        side = ("L" if name.endswith(".L") or "左" in original else
                "R" if name.endswith(".R") or "右" in original else None)
        weight = skin(name)
        if side is None or weight <= 0.0:
            continue
        key = (weight, -depth(name), name)
        if side not in best or key > best[side]:
            best[side] = key
    return [best[s][2] for s in sorted(best)]


def humanoid_map(bones: dict[str, str | None]) -> dict[str, str]:
    """VRM humanoid name -> bone name, given ``{bone: parent}`` for the armature."""
    out: dict[str, str] = {}
    for human, candidates in _CENTRAL.items():
        found = next((c for c in candidates if c in bones), None)
        if found:
            out[human] = found
    # Spine chain: 上半身 and its descendants down to 首 (spine, chest, upper chest).
    if SPINE_ROOT in bones and "neck" in out:
        chain = [out["neck"]]
        while chain[-1] in bones and bones[chain[-1]] is not None and chain[-1] != SPINE_ROOT:
            chain.append(bones[chain[-1]])
        if chain[-1] == SPINE_ROOT:
            torso = list(reversed(chain[1:]))                  # 上半身 .. last before 首
            torso = [b for b in torso if not b.startswith("_")]
            for human, bone in zip(("spine", "chest", "upper_chest"), torso):
                out[human] = bone
    for side in ("left", "right"):
        for human, candidates in _SIDED.items():
            found = next((_side(c, side) for c in candidates if _side(c, side) in bones), None)
            if found:
                out[f"{side}_{human}"] = found
    return out


def is_character(bones: dict[str, str | None]) -> bool:
    """Whether a skeleton has every bone wogen needs to pose it."""
    hmap = humanoid_map(bones)
    return all(name in hmap for name in REQUIRED)


# ---------------------------------------------------------------- facial morphs
# wogen's expressions are VRoid ``Fcl_*`` key weights (``wogen.expressions``). On an MMD
# model each Fcl key becomes weighted standard morphs; each entry is a tuple of candidate
# names (first one the model has wins). Regions and sides were checked by where each morph
# moves vertices on the imported models: no-suffix winks/brows are the model's left (+X),
# ウィンク２ is a plain close and ウィンク the smiling one. Weights are first guesses for
# the user to dial by eye. Fcl keys with no entry (Fcl_MTH_Close) have no MMD equivalent.
_A, _O, _WA = ("あ", "あ１", "あ2"), ("お", "お２", "う"), ("ワ", "ワ２")
FCL_MORPHS: dict[str, tuple[tuple[tuple[str, ...], float], ...]] = {
    "Fcl_EYE_Close": ((("まばたき",), 1.0),),
    "Fcl_EYE_Close_L": ((("ウィンク２",), 1.0),),
    "Fcl_EYE_Close_R": ((("ウィンク２右",), 1.0),),
    "Fcl_EYE_Joy": ((("笑い",), 1.0),),
    "Fcl_EYE_Fun": ((("笑い",), 0.4), (("下眼上",), 0.6)),
    "Fcl_EYE_Angry": ((("怒り目",), 1.0),),
    "Fcl_EYE_Sorrow": ((("悲しむ",), 1.0),),
    "Fcl_EYE_Surprised": ((("びっくり",), 1.0),),
    "Fcl_BRW_Angry": ((("怒り",), 1.0),),
    "Fcl_BRW_Sorrow": ((("困る", "悲し"), 1.0),),
    "Fcl_BRW_Fun": ((("にこり",), 0.7),),
    "Fcl_BRW_Joy": ((("にこり",), 1.0),),
    "Fcl_BRW_Surprised": ((("上",), 1.0),),
    "Fcl_MTH_A": ((_A, 1.0),),
    "Fcl_MTH_I": ((("い",), 1.0),),
    "Fcl_MTH_U": ((("う",), 1.0),),
    "Fcl_MTH_E": ((("え",), 1.0),),
    "Fcl_MTH_O": ((_O, 1.0),),
    "Fcl_MTH_Fun": ((("口角上げ", "にやり"), 1.0),),
    "Fcl_MTH_Joy": ((("口角上げ", "にやり"), 0.8), (_WA, 0.35)),
    "Fcl_MTH_Angry": ((("口角下げ",), 0.8), (("口横狭め",), 0.3)),
    "Fcl_MTH_Sorrow": ((("口角下げ",), 0.7),),
    "Fcl_MTH_Small": ((("口横狭め",), 1.0),),
    "Fcl_MTH_Large": ((("口横広げ",), 1.0),),
    "Fcl_MTH_Surprised": ((_O, 0.6),),
}
# Full-face Fcl keys expand into their brow, eye and mouth parts.
for _mood in ("Joy", "Fun", "Angry", "Sorrow", "Surprised"):
    FCL_MORPHS[f"Fcl_ALL_{_mood}"] = tuple(
        e for part in ("BRW", "EYE", "MTH") for e in FCL_MORPHS[f"Fcl_{part}_{_mood}"])


MORPH_NAMES = frozenset(n for entries in FCL_MORPHS.values() for cands, _ in entries for n in cands)


def morph_weights(fcl: dict[str, float], available) -> dict[str, float]:
    """Fcl key weights -> MMD morph weights for a model with morphs ``available``
    (summed, clamped to 0..1). Keys the model can't show are dropped."""
    available = set(available)
    out: dict[str, float] = {}
    for key, w in fcl.items():
        for candidates, kw in FCL_MORPHS.get(key, ()):
            name = next((c for c in candidates if c in available), None)
            if name is not None:
                out[name] = out.get(name, 0.0) + kw * w
    return {k: max(0.0, min(1.0, v)) for k, v in out.items()}


def list_models(imports_dir: Path) -> list[Path]:
    """Character PMX files under ``imports_dir`` (props such as weapons left out)."""
    return sorted(p for p in Path(imports_dir).glob("*/*.pmx")
                  if not any(h in p.stem for h in PROP_HINTS))


def model_label(path: Path, imports_dir: Path) -> str:
    """``folder/name`` of a model under ``imports_dir``, as on disk."""
    return Path(path).relative_to(imports_dir).with_suffix("").as_posix()


def english_label(path: Path, imports_dir: Path) -> str:
    """``model_label`` in English (``mmd_names.translate_model``)."""
    from .mmd_names import translate_model
    folder, _, stem = model_label(path, imports_dir).rpartition("/")
    return f"{translate_model(folder)}/{translate_model(stem)}" if folder else translate_model(stem)


def find_model(name: str, imports_dir: Path) -> Path:
    """The model ``name`` picks: a .pmx path, else the one model whose ``folder/name``
    label, on disk or in English (any case), contains it; an exact name or label wins over
    partial matches."""
    path = Path(name)
    if path.suffix.lower() == ".pmx" and path.is_file():
        return path
    models = list_models(imports_dir)
    want = name.casefold()
    labels = {}
    for p in models:
        en = english_label(p, imports_dir)
        labels[p] = {model_label(p, imports_dir).casefold(), en.casefold(),
                     p.stem.casefold(), en.rpartition("/")[2].casefold()}
    hits = [p for p in models if any(want in label for label in labels[p])]
    exact = [p for p in hits if want in labels[p]]
    hits = exact or hits
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(f"No imported model matches {name!r} ('wogen mmd' lists them)")
    raise ValueError(f"{name!r} matches several models; use folder/name: "
                     + ", ".join(english_label(p, imports_dir) for p in hits))
