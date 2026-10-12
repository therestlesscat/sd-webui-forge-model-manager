"""
What an image file says about how it was made, for Sync images (#233).

Two witnesses, read by readers kept apart, so another tool's format is another
reader (#232):

- the generation text Forge writes into the file: PNG's `parameters`, and the
  EXIF comment of a JPEG, WebP, AVIF or JXL - read here with PIL rather than
  by Forge's read_info_from_image, which in the original Forge scans a file's
  pixels for hidden text when there is none, and imports the WebUI to do it;
- the file's own name and folders, read back by Forge's naming settings:
  for an image with no text, what its name says - model, sampler, steps,
  size, time - is all there is.

The text is parsed by Forge's own parser, as the recorder parses it
(generations.infotext_meta). Its last line is also read here, by Forge's own
pattern for it: the parser drops `Model` when it names the checkpoint loaded
now, and Neo's drops every `Module N`, which a match needs.
"""
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .forge_host import infotext_line_pattern

# What a sync reads as an image.
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".avif", ".jxl")

_EXIF_IFD = 0x8769
_USER_COMMENT = 0x9286


def read_text(path: str) -> Tuple[Optional[str], int, int]:
    """
    The generation text written into an image file, and the image's size.

    Raises OSError for a file that cannot be opened as an image.
    """
    from PIL import Image
    with Image.open(path) as image:
        width, height = image.size
        info = image.info or {}
        text = info.get("parameters")
        if not text and "exif" in info:
            text = _user_comment(image)
        if not text and isinstance(info.get("comment"), (bytes, str)):
            comment = info["comment"]
            text = comment.decode("utf-8", "ignore") if isinstance(comment, bytes) else comment
    text = text.strip() if isinstance(text, str) else None
    return (text or None), width, height


def _user_comment(image) -> Optional[str]:
    """The EXIF UserComment Forge writes a JPEG's or WebP's text into: eight
    bytes naming the encoding, then the text."""
    try:
        value = image.getexif().get_ifd(_EXIF_IFD).get(_USER_COMMENT)
    except Exception:
        return None
    if isinstance(value, str):
        return value
    if not isinstance(value, bytes) or len(value) < 8:
        return None
    head, body = value[:8], value[8:]
    if head == b"UNICODE\x00":
        # Forge writes it big-endian (piexif); a little-endian writer starts
        # its text with a zero byte the other way round.
        encoding = "utf-16-le" if body[1:2] == b"\x00" and body[:1] != b"\x00" else "utf-16-be"
        return body.decode(encoding, "ignore")
    return body.decode("utf-8", "ignore")


def line_params(text: Optional[str]) -> Dict[str, str]:
    """
    An infotext's last line, `Key: value, ...`, as Forge's parser reads it:
    only when it has at least three such pairs, each value unquoted. Nothing
    is dropped or renamed - unlike the parser's answer.
    """
    if not text:
        return {}
    last = text.strip().split("\n")[-1]
    pairs = infotext_line_pattern().findall(last)
    if len(pairs) < 3:
        return {}
    params = {}
    for key, value in pairs:
        value = value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            try:
                value = json.loads(value)
            except ValueError:
                pass
        params[key.strip()] = value
    return params


# ------------------------------------------------------------- the file's name

# Forge's naming keys a name is read back by, each with what its value looks
# like, the field it is kept as, and how it is checked. A key not here reads
# as any text, compared but not kept.
_KEYS = {
    "model_name": (r".+", "Model"),
    "sampler": (r".+?", "Sampler"),
    "scheduler": (r".+?", "Schedule type"),
    "sampler_scheduler": (r".+?", None),
    "steps": (r"\d+", "Steps"),
    "cfg": (r"\d+(?:\.\d+)?", "CFG scale"),
    "clip_skip": (r"\d+", "Clip skip"),
    "width": (r"\d+", "Size-1"),
    "height": (r"\d+", "Size-2"),
    "seed": (r"\d+", "Seed"),
    "seed_first": (r"\d+", "Seed"),
    "seed_last": (r"\d+", None),
    "batch_number": (r"\d+", None),
    "generation_number": (r"\d+", None),
    "batch_size": (r"\d+", None),
    "model_hash": (r"[0-9a-fA-F]+", "Model hash"),
}
# Keys whose value changes from image to image of one press, or says when:
# never what two images must share to join.
_PER_IMAGE = {"seed", "seed_first", "seed_last", "batch_number", "generation_number",
              "datetime", "date", "job_timestamp", "image_hash", "elapsed_time"}
# Each time key's format when the pattern names none (Forge's FilenameGenerator).
_TIME_FORMATS = {"datetime": "%Y%m%d%H%M%S", "job_timestamp": "%Y%m%d%H%M%S", "date": "%Y-%m-%d"}
_STRFTIME = {"%Y": r"\d{4}", "%m": r"\d{2}", "%d": r"\d{2}", "%H": r"\d{2}", "%M": r"\d{2}",
             "%S": r"\d{2}", "%y": r"\d{2}", "%f": r"\d+", "%j": r"\d{3}"}
_TOKEN = re.compile(r"\[(\w+)((?:<[^>]*>)*)\]")


class NamePattern(object):
    """
    One of Forge's naming patterns - `[model_name]-[steps]-[datetime]` - as a
    way to read a name back into its fields. A name that does not fit reads
    as nothing.
    """

    def __init__(self, pattern: str, samplers: Optional[List[str]] = None, numbered: bool = False):
        self.pattern = pattern or ""
        self.keys: List[str] = []
        self.formats: Dict[str, str] = {}
        sampler = None
        if samplers:
            # A sampler's name holds spaces and signs, and the names around it
            # dashes: known names, longest first, place it where a lazy match
            # could not. A sampler Forge no longer lists - renamed, or an
            # extension's - is read by the lazy match after.
            sampler = "|".join(re.escape(s) for s in sorted(set(samplers), key=len, reverse=True))
        self.regexes = [r for r in (self._compile(numbered, sampler) if sampler else None,
                                    self._compile(numbered, None)) if r is not None]
        self.regex = self.regexes[0] if self.regexes else None

    def _compile(self, numbered: bool, sampler: Optional[str]):
        self.keys, self.formats = [], {}
        parts = [r"(?:\d{4,}-)?" if numbered else ""]
        at = 0
        for match in _TOKEN.finditer(self.pattern):
            parts.append(re.escape(self.pattern[at:match.start()]))
            key = match.group(1).lower()
            args = re.findall(r"<([^>]*)>", match.group(2) or "")
            group = f"k{len(self.keys)}"
            if key in _TIME_FORMATS:
                fmt = args[0] if args and args[0] else _TIME_FORMATS[key]
                self.formats[group] = fmt
                regex = _strftime_regex(fmt)
            elif key == "sampler" and sampler:
                regex = f"(?:{sampler})"
            else:
                regex = _KEYS.get(key, (r".+?", None))[0]
            parts.append(f"(?P<{group}>{regex})")
            self.keys.append(key)
            at = match.end()
        parts.append(re.escape(self.pattern[at:]))
        return re.compile("^" + "".join(parts) + "$", re.IGNORECASE) if self.keys else None

    def read(self, name: str) -> Optional[Dict[str, Any]]:
        """
        A name's fields: {"fields": {Forge's infotext names: value}, "same":
        what two images must share to join, "time": the time it names, or
        None}. None when the name does not fit, or a value fails its check.
        """
        match = next((m for m in (r.match(name) for r in self.regexes) if m), None)
        if not match:
            return None
        fields: Dict[str, Any] = {}
        same: List[Tuple[str, str]] = []
        time = None
        for index, key in enumerate(self.keys):
            group = f"k{index}"
            value = match.group(group)
            if group in self.formats:
                try:
                    parsed = datetime.strptime(value, self.formats[group])
                except ValueError:
                    return None
                if key != "date":
                    # A date alone says no time of day: the file's is nearer.
                    time = parsed
                continue
            if key not in _PER_IMAGE:
                same.append((key, value.lower()))
            field = _KEYS.get(key, (None, None))[1]
            if field:
                fields[field] = value
        if "Size-1" in fields and "Size-2" in fields:
            fields["Size"] = f"{fields.pop('Size-1')}x{fields.pop('Size-2')}"
        return {"fields": fields, "same": tuple(same), "time": time}


def _strftime_regex(fmt: str) -> str:
    parts, at = [], 0
    for match in re.finditer(r"%.", fmt):
        parts.append(re.escape(fmt[at:match.start()]))
        parts.append(_STRFTIME.get(match.group(0), r".+?"))
        at = match.end()
    parts.append(re.escape(fmt[at:]))
    return "".join(parts)


def read_name(path: str, root: str, file_pattern: Optional[NamePattern],
              folder_pattern: Optional[NamePattern]) -> Optional[Dict[str, Any]]:
    """
    What an image's name, and its folders under the synced one, say: as
    NamePattern.read gives it, the folders' fields added where the name has
    none. A folder pattern is read level by level, as far as the folders go:
    an extension may add a level of its own. None when the name does not fit.
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    read = file_pattern.read(stem) if file_pattern else None
    if read is None:
        return None
    if folder_pattern and folder_pattern.pattern:
        levels = [p for p in re.split(r"[\\/]", folder_pattern.pattern) if p]
        rel = os.path.relpath(os.path.dirname(path), root)
        folders = [p for p in re.split(r"[\\/]", rel) if p and p != "."]
        for level, folder in zip(levels, folders):
            got = NamePattern(level).read(folder)
            if got:
                for key, value in got["fields"].items():
                    read["fields"].setdefault(key, value)
                if read["time"] is None and got["time"] is not None:
                    read["time"] = got["time"]
    return read


# ------------------------------------------------------------- an infotext's LoRAs

_LORA_TAG = re.compile(r"<lora:([^:>]+)(?::([^:>]*))?[^>]*>", re.IGNORECASE)


def prompt_loras(prompt: Optional[str]) -> List[Dict[str, Any]]:
    """The LoRAs a prompt names, `<lora:name:weight>`, in order, each once."""
    found: Dict[str, Dict[str, Any]] = {}
    for name, weight in _LORA_TAG.findall(prompt or ""):
        name = name.strip()
        if not name or name.lower() in found:
            continue
        try:
            value = float(weight) if weight not in (None, "") else None
        except ValueError:
            value = None
        found[name.lower()] = {"name": name, "weight": value}
    return list(found.values())


def lora_hashes(value: Optional[str]) -> Dict[str, str]:
    """`Lora hashes: "name: hash, name: hash"` as {name: hash}, hashes lower case."""
    found: Dict[str, str] = {}
    for part in (value or "").split(","):
        if ":" in part:
            name, digest = part.rsplit(":", 1)
            if name.strip() and digest.strip():
                found[name.strip()] = digest.strip().lower()
    return found
