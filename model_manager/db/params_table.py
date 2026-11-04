"""
How an image's generation settings are read, once, for every reader (#378):
Send's paste of a Civitai image reads its record's data here.
"""
import re
from typing import Any, Dict, Optional

# Forge's pattern for a field of the settings line (`re_param`, Neo's
# infotext_utils.py), and the image data's names for the line's own.
RE_PARAM = re.compile(r'\s*([\w\s\-\/]+):\s*("(?:\\.|[^\\"])+"|[^,]*)(?:,|$)')
_DATA_NAMES = {"Steps": "steps", "Sampler": "sampler", "CFG scale": "cfgScale", "Seed": "seed"}


def truthy(value: Any) -> bool:
    """Truth as the page's JavaScript read it, which Send's readers were
    ported from: an empty list or object is true there."""
    if value is None or value is False or value == "":
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == value and value != 0
    return True


# An image's clip skip (#318): Forge's own field, else Civitai's `clipSkip`
# (65,773 of one library's 107,469 images) and two spellings of it. Not
# `Clip slip`, an uploader's typo, nor ComfyUI's `clipstopatlayer`, which
# counts the other way.
CLIP_SKIP_KEYS = ("Clip skip", "clipSkip", "CLIP Skip", "Clip Skip")


def image_clip_skip(meta: Dict[str, Any]) -> Any:
    """The clip skip an image's data gives, as it gives it; None for none."""
    return next((meta[k] for k in CLIP_SKIP_KEYS if truthy(meta.get(k))), None)


def size_of(text: Any) -> Optional[tuple]:
    """A `Size` as Forge writes it, `WxH`, as two whole numbers; None for none."""
    match = re.fullmatch(r"\s*(\d+)\s*x\s*(\d+)\s*", str(text or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def read_settings_line(meta: Dict[str, Any]) -> None:
    """
    An image whose tool stored its whole settings line inside its negative
    prompt (#313: 138 images of one library): the line - one that starts
    with `Steps:` and holds three fields - read as the image's data where the
    data gives no such field, in place, and the negative prompt without it.
    Pasted as text, its settings were never set; read so, the schedule type,
    Hires fix and the size rule follow from it as from any image's data.
    """
    lines = str(meta.get("negativePrompt") or "").split("\n")
    at = next((n for n in range(len(lines) - 1, -1, -1)
               if lines[n].lstrip().startswith("Steps:") and len(RE_PARAM.findall(lines[n])) >= 3), None)
    if at is None:
        return
    for key, value in RE_PARAM.findall(lines[at]):
        key = _DATA_NAMES.get(key.strip(), key.strip())
        if meta.get(key) is None or meta.get(key) == "":
            meta[key] = value.strip()
    meta["negativePrompt"] = "\n".join(lines[:at] + lines[at + 1:]).rstrip()


def record_meta(record: Dict[str, Any]) -> Dict[str, Any]:
    """A Civitai image's data as its settings are read: a copy of its record's
    own, with a settings line kept in its negative prompt read in."""
    meta = dict(record.get("meta") or {})
    read_settings_line(meta)
    return meta
