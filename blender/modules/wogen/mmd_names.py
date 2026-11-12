"""English names for imported MMD models (pure Python; applied by ``wogen.bl.mmd_import``).

The packages name bones, morphs, materials and objects in Japanese (the MMD standard
vocabulary) and Chinese (the modelers' additions). ``translate`` turns a name into English
term by term (longest match first), keeping ASCII parts, numbers and the ``.L``/``.R``
side; anything not in the dictionaries stays as it is, so nothing is lost. Morphs use
``translate_morph`` (whole-name meanings, with 左/右 sides). ``unique_names`` makes a
rename map without collisions.

``pmx_header`` reads a model's names and comment (its release terms) straight from the
file, so model listing works without Blender.
"""

from __future__ import annotations

import re
import struct
import unicodedata
from pathlib import Path

# Bone (and general) terms. Japanese: MMD semi-standard skeleton; Chinese: the modelers'.
BONE_TERMS = {
    # skeleton
    "全ての親": "root", "操作中心": "view_center", "センター": "center", "グルーブ": "groove",
    "腰キャンセル": "waist_cancel", "キャンセル": "cancel", "腰": "waist",
    "上半身": "upper_body", "下半身": "lower_body", "首": "neck", "頭": "head",
    "両目": "both_eyes", "目": "eye", "肩": "shoulder", "腕捩": "arm_twist", "腕": "arm",
    "ひじ": "elbow", "手首": "wrist", "手捩": "wrist_twist", "足捩": "leg_twist", "捩": "twist",
    "手先": "hand_tip", "親指": "thumb", "人差指": "index", "人指": "index", "中指": "middle",
    "薬指": "ring", "小指": "little", "足首": "ankle", "足先": "toe", "つま先": "toe_tip",
    "足": "leg", "ひざ": "knee", "先": "tip", "ダミー": "dummy",
    # helpers and physics
    "補助": "assist", "辅助": "assist", "補": "assist", "錘": "weight", "锤": "weight",
    "位置調節": "position_adjust", "調整": "adjust", "おっぱい": "bust", "胸": "bust",
    "尻": "butt", "肉腿": "thigh_flesh", "肉": "flesh", "震": "jiggle", "腿": "thigh",
    "跟": "heel",
    # hair, clothes, accessories
    "前髪": "front_hair", "後髪": "back_hair", "髪球": "hair_bun", "髪": "hair", "髮": "hair",
    "发": "hair", "スカート": "skirt", "裙": "skirt", "袖": "sleeve", "カフ": "cuff",
    "靴": "shoe", "帽挂": "hat_charm", "帽": "hat", "耳": "ear", "角": "horn", "尾": "tail",
    "项链": "necklace", "结": "knot", "饰": "ornament", "挂": "charm",
    # wings and mechanisms (Lemiel's wing rig)
    "はばたき": "flap", "改造後に削除": "remove_after_edit", "翼": "wing", "翅膀": "wings",
    "エンジン受": "engine_mount", "エンジン": "engine", "ピストン受": "piston_mount",
    "ピストン": "piston", "受": "mount", "全親": "all_parent", "親": "parent", "の": "",
    # positions and parts
    "口中": "mouth_inner", "中口": "mid_mouth", "口": "mouth", "歯": "teeth", "齿": "teeth",
    "眉": "brow", "目光": "eye_highlight", "上": "upper", "下": "lower", "前": "front",
    "後": "back", "后": "back", "内": "inner", "元": "base", "中": "mid", "左": "left",
    "右": "right",
}

# Material terms (mostly Chinese).
MATERIAL_TERMS = {
    "贴身衣物": "underwear", "眼睫毛": "eyelashes", "蝴蝶结": "bow", "脚指甲": "toenails",
    "头发高光": "hair_highlight", "高光": "highlight", "金属": "metal", "皮肤": "skin",
    "目影": "eye_shadow", "发饰": "hair_ornament", "头饰": "head_ornament", "耳饰": "earrings",
    "戒指": "ring", "袖子": "sleeve", "墨镜": "sunglasses", "外衣": "coat", "衣服": "clothes",
    "口舌": "tongue", "口线": "mouth_line", "目线": "eye_line", "睫毛": "lashes",
    "眉毛": "brows", "睫眉": "lashes_brows", "二重": "double_eyelid", "目白": "eye_white",
    "白目": "eye_white", "眼白": "eye_white", "眼睛": "eyes", "指甲": "nails", "颈饰": "choker",
    "面纱": "veil", "挂饰": "pendant", "带子": "strap", "前带": "front_strap", "帽子": "hat",
    "头发": "hair", "前发": "front_hair", "内裙": "underskirt", "表情": "expression",
    "体": "body", "衣": "clothes", "服": "clothes", "肌": "skin", "颜": "face", "脸": "face",
    "鞋": "shoes", "袜": "stockings", "睫": "lashes", "齿": "teeth", "舌": "tongue",
    "唇": "lips", "扣": "button", "披": "cape", "带": "strap", "花": "flower", "筒": "tube",
    "线": "line", "光": "light", "手": "hand", "臂": "arm", "头": "head", "颈": "neck", "脚": "foot",
    "眼": "eye", "腿": "leg", "白": "white",
}

# Model, variant and object words (file, folder and object names).
MODEL_TERMS = {
    # characters: English names from the packages' PMX headers, except Remielle (no English
    # name in those packages; the spelling is from their texture files, ⚠ unverified)
    "耀嘉音": "Astra_Yao", "叶瞬光": "Ye_Shunguang", "普罗米娅": "Promeia", "卢西娅": "Lucia",
    "诺姆": "Norma", "希希芙": "Cissia", "伊德海莉": "Yidhari", "蕾米埃尔": "Remielle",
    # variants
    "手和胸部无碰撞版": "no_hand_chest_collision", "手和胸部无碰撞": "no_hand_chest_collision",
    "胸部和手无碰撞": "no_hand_chest_collision", "带大翅膀": "with_big_wings",
    "泳装": "swimsuit", "摘帽": "hat_off", "斗篷": "cloak", "武器": "weapon", "翅膀": "wings",
    "补妆镜": "makeup_mirror", "葡萄": "grapes", "白": "white", "黑": "black", "版": "version",
    "·": "_", "�": "",
}

# Morphs: whole-name meanings (sides come from a 左/右 suffix; no-suffix winks are the
# model's left, checked by where they move vertices).
MORPH_TERMS = {
    # eyes
    "まばたき": "blink", "笑い": "eyes_smile", "ウィンク": "wink_smile_L", "ウィンク2": "wink_L",
    "びっくり": "eyes_wide", "じと目": "eyes_half_closed", "怒り目": "eyes_angry",
    "悲しむ": "eyes_sad", "眼角下": "eye_corners_down", "下眼上": "lower_lids_up",
    "星目": "star_eyes", "はぅ": "eyes_flustered", "キリッ": "eyes_determined",
    "にっこり": "eyes_beaming",
    # mouth
    "あ": "mouth_a", "い": "mouth_i", "う": "mouth_u", "え": "mouth_e", "お": "mouth_o",
    "ワ": "mouth_wa", "□": "mouth_square", "▲": "mouth_triangle", "にやり": "mouth_smirk",
    "口角上げ": "mouth_corners_up", "口角下げ": "mouth_corners_down", "口横広げ": "mouth_wide",
    "口横狭め": "mouth_narrow", "口上": "mouth_up", "口下": "mouth_down", "口": "mouth",
    "笑う": "mouth_laugh", "喜び": "joy", "歯上": "teeth_upper", "歯下": "teeth_lower",
    "齿上": "teeth_upper", "齿下": "teeth_lower", "上歯": "teeth_upper", "下歯": "teeth_lower",
    # brows
    "真面目": "brows_serious", "困る": "brows_troubled", "にこり": "brows_cheerful",
    "怒り": "brows_angry", "悲し": "brows_sad", "上": "brows_up", "下": "brows_down",
    "前": "brows_forward", "八": "brows_worried", "リラックス": "brows_relaxed",
    # other
    "帽": "hat",
}

# Words in bone/material morph names (wing flapping, hiding parts).
MORPH_WORDS = {"はばたき": "flap", "速度": "speed", "隐藏": "hide", "面纱": "veil",
               "表示": "show", "非表示": "hide", "初期": "initial", "角度": "angle",
               "幅": "amplitude", "大": "large", "小": "small", "消": "hide"}

_SIDE = re.compile(r"\.(L|R)$")
_NUM = re.compile(r"^(.*?)(\d+)$")


def _normalize(name: str) -> str:
    """Full-width letters/digits and half-width katakana to their plain forms."""
    return unicodedata.normalize("NFKC", name)


def has_foreign(name: str) -> bool:
    return any(ord(c) > 127 for c in name)


def translate(name: str, terms: dict[str, str] | None = None) -> str:
    """English for a bone/material/object name, term by term; unknown characters stay."""
    terms = BONE_TERMS if terms is None else terms
    name = _normalize(name)
    side = _SIDE.search(name)
    core = name[:side.start()] if side else name
    keys = sorted(terms, key=len, reverse=True)
    parts: list[str] = []
    i = 0
    while i < len(core):
        if ord(core[i]) < 128:
            j = i
            while j < len(core) and ord(core[j]) < 128:
                j += 1
            parts.append(core[i:j])
            i = j
            continue
        key = next((k for k in keys if core.startswith(k, i)), None)
        if key is None:
            parts.append(core[i])
            i += 1
        else:
            if terms[key]:
                parts.append("\x00" + terms[key])         # marker: a translated word
            i += len(key)
    out, prev_word = "", False
    for p in parts:
        word = p.startswith("\x00")
        p = p.lstrip("\x00")
        if out and (word or prev_word) and out[-1].isalnum() and p[:1].isalnum():
            out += "_"
        out += p
        prev_word = word
    lead = len(core) - len(core.lstrip("_"))              # keep _shadow_ / _dummy_ markers
    out = "_" * lead + (re.sub(r"_+", "_", out).strip("_") or core)
    return out + (side.group(0) if side else "")


def translate_morph(name: str) -> str:
    """English for a facial morph: whole-name meaning, 左/右 sides as _L/_R, numbers kept."""
    core = _normalize(name)
    side = ""
    if core.endswith(("左", "右")) and len(core) > 1:
        side, core = ("_L" if core[-1] == "左" else "_R"), core[:-1]
    num = ""
    m = _NUM.match(core)
    if core not in MORPH_TERMS and m and m.group(1) in MORPH_TERMS:
        core, num = m.group(1), "_" + m.group(2)
    if core in MORPH_TERMS:
        base = MORPH_TERMS[core]
        if side and base.endswith(("_L", "_R")):           # ウィンク右: replace the side
            base = base[:-2]
        return base + num + side
    return translate(name, {**BONE_TERMS, **MATERIAL_TERMS, **MORPH_WORDS})


def translate_model(name: str) -> str:
    """English for a model, folder or object name (characters and variants)."""
    return translate(name, {**MATERIAL_TERMS, **MODEL_TERMS})


def unique_names(names, translator) -> dict[str, str]:
    """{original: english} for names that change, never colliding with each other or with
    the names that stay (a clash gets ``_2``, ``_3``, ...)."""
    names = list(names)
    taken = {n for n in names if not has_foreign(n)}
    out = {}
    for n in names:
        if not has_foreign(n):
            continue
        new = translator(n)
        candidate, k = new, 2
        while candidate in taken:
            side = _SIDE.search(new)
            stem, suffix = (new[:side.start()], side.group(0)) if side else (new, "")
            candidate, k = f"{stem}_{k}{suffix}", k + 1
        taken.add(candidate)
        out[n] = candidate
    return out


def pmx_header(path: Path) -> dict[str, str]:
    """A PMX file's model names and comments: {"name", "name_en", "comment", "comment_en"}."""
    data = Path(path).read_bytes()[:65536]
    if data[:4] != b"PMX ":
        raise ValueError(f"{path} isn't a PMX file")
    encoding = "utf-16-le" if data[9] == 0 else "utf-8"
    off = 9 + data[8]
    out = {}
    for key in ("name", "name_en", "comment", "comment_en"):
        n = struct.unpack_from("<i", data, off)[0]
        off += 4
        out[key] = data[off:off + n].decode(encoding, "replace")
        off += n
    return out
