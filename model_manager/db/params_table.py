"""
How an image's generation settings are read, once, for every reader (#378):
Send's paste of a Civitai image reads its record's data here.
"""
import re
from typing import Any, Dict

# Forge's pattern for a field of the settings line (`re_param`, Neo's
# infotext_utils.py), and the image data's names for the line's own.
RE_PARAM = re.compile(r'\s*([\w\s\-\/]+):\s*("(?:\\.|[^\\"])+"|[^,]*)(?:,|$)')
_DATA_NAMES = {"Steps": "steps", "Sampler": "sampler", "CFG scale": "cfgScale", "Seed": "seed"}


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
