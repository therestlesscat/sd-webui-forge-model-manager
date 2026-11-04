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


# ---------------------------------------------- a settings row (#378)
# What each stored image and generation was made with, read from its record
# or its text when that is written, the record and the text staying the
# source. The sampler and schedule type are kept as written: their split is
# by the asking WebUI's lists of samplers, which two WebUIs sharing a
# database differ in.

TEXT, WHOLE, NUMBER = "text", "whole", "number"
# Every column of `image_params`, with what it holds; `generation_params`
# has them all but `scheduler`, which only ComfyUI's data gives, and `seed`,
# which is per image there (`generation_images.seed`).
IMAGE_COLUMNS = {
    "sampler": TEXT, "schedule_type": TEXT, "scheduler": TEXT, "steps": WHOLE, "cfg": NUMBER,
    "distilled_cfg": NUMBER, "shift": NUMBER, "seed": WHOLE, "width": WHOLE, "height": WHOLE,
    "clip_skip": WHOLE, "hires_upscale": NUMBER, "hires_steps": WHOLE, "hires_upscaler": TEXT, "denoise": NUMBER,
}
GENERATION_COLUMNS = {k: v for k, v in IMAGE_COLUMNS.items() if k not in ("scheduler", "seed")}
# Not recorded when 0: Send's paste writes no steps or CFG of 0 (`truthy`).
_ZERO_IS_NONE = ("steps", "cfg")
_NUMBER_TEXT = re.compile(r"\s*-?\d+(?:\.\d+)?\s*")
# What an SQLite INTEGER holds; a larger int raises OverflowError when bound.
_SQLITE_INTEGER = (-2 ** 63, 2 ** 63 - 1)


def _typed(kind: str, value: Any) -> Any:
    """A value as its column holds it: text as written; a number, or text
    that reads as one, as a number; anything else - a list, an object, a
    yes or no, nothing, or a whole number past SQLite's 64 bits, as 25 of
    one library's stored seeds are - None, so no value can fail a write."""
    if kind == TEXT:
        return value if isinstance(value, str) and value.strip() else None
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and _NUMBER_TEXT.fullmatch(value):
        value = float(value)
    if not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        return None
    # A whole count written `20.0` is 20; a REAL column keeps 7 and 7.0 as one.
    if kind == WHOLE and isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and not _SQLITE_INTEGER[0] <= value <= _SQLITE_INTEGER[1]:
        return None
    return value


def _row(columns: Dict[str, str], given: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    row = {k: _typed(kind, given.get(k)) for k, kind in columns.items()}
    for k in _ZERO_IS_NONE:
        if row.get(k) == 0:
            row[k] = None
    return row if any(v is not None for v in row.values()) else None


def _size(given: Dict[str, Any], size_key: str, width_key: str, height_key: str) -> Dict[str, Any]:
    """The settings' size: its `Size`, else its width and height - never the picture's."""
    size = size_of(given.get(size_key))
    if size:
        return {"width": size[0], "height": size[1]}
    return {"width": given.get(width_key), "height": given.get(height_key)}


# A checkpoint's settings, grouped (checkpoint_image_settings,
# checkpoint_generation_settings): the columns counted, then how many uses
# give them and the newest use's id.
GROUP_KEYS = ("sampler", "schedule_type", "scheduler", "steps", "cfg", "distilled_cfg", "shift", "uses", "newest")


def settings_group(row: Any) -> Dict[str, Any]:
    """One group of a checkpoint's settings, by GROUP_KEYS."""
    return dict(zip(GROUP_KEYS, tuple(row)))


def image_params_row(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    A Civitai image's settings row, read from its record as Send reads it
    (`record_meta`): one value per column of IMAGE_COLUMNS, or None when the
    record gives none.
    """
    # A record's meta that is not an object - text, a list - gives no setting.
    meta = record_meta(record) if isinstance(record, dict) and isinstance(record.get("meta") or {}, dict) else {}
    shift = meta.get("Shift")
    return _row(IMAGE_COLUMNS, {
        "sampler": meta.get("sampler"), "schedule_type": meta.get("Schedule type"), "scheduler": meta.get("scheduler"),
        "steps": meta.get("steps"), "cfg": meta.get("cfgScale"), "distilled_cfg": meta.get("Distilled CFG Scale"),
        "shift": shift if truthy(shift) else meta.get("shift"), "seed": meta.get("seed"),
        **_size(meta, "Size", "width", "height"),
        "clip_skip": image_clip_skip(meta), "hires_upscale": meta.get("Hires upscale"),
        "hires_steps": meta.get("Hires steps"), "hires_upscaler": meta.get("Hires upscaler"),
        "denoise": meta.get("Denoising strength"),
    })


def generation_params_row(infotext: Any, name_fields: Any = None) -> Optional[Dict[str, Any]]:
    """
    A generation's settings row: its text's settings line, read with the
    original Forge's pattern in either WebUI (`fixed_line_pattern`), else
    what Sync images read from its first image's file name (`name_fields`,
    kept under the line's own names). One value per column of
    GENERATION_COLUMNS, or None when neither gives one.
    """
    from ..forge_host import fixed_line_pattern
    from ..image_text import line_params
    fields = line_params(infotext if isinstance(infotext, str) else None, fixed_line_pattern())
    if not fields and isinstance(name_fields, dict):
        fields = name_fields
    return _row(GENERATION_COLUMNS, {
        "sampler": fields.get("Sampler"), "schedule_type": fields.get("Schedule type"),
        "steps": fields.get("Steps"), "cfg": fields.get("CFG scale"),
        "distilled_cfg": fields.get("Distilled CFG Scale"), "shift": fields.get("Shift"),
        **_size(fields, "Size", "Size-1", "Size-2"),
        "clip_skip": fields.get("Clip skip"), "hires_upscale": fields.get("Hires upscale"),
        "hires_steps": fields.get("Hires steps"), "hires_upscaler": fields.get("Hires upscaler"),
        "denoise": fields.get("Denoising strength"),
    })
