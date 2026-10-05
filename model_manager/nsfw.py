"""
How explicit is this? - asked and answered in one place.

Civitai reports maturity three different ways, and they do not always agree.
This module decides which to believe, so the sync, the image store
and the browser all reach the same verdict about the same picture.

THE LEVELS are bit flags, from Civitai's own scale:

    PG 1 · PG-13 2 · R 4 · X 8 · XXX 16 · Blocked 32 · Unknown 64

A stored value can carry more than one bit: a model at 3 is PG|PG-13, meaning
its gallery spans both. Comparisons are numeric - a higher number is more
explicit - which holds because the bits ascend.

WHICH FIELD WINS
  browsingLevel  an integer on Civitai's current scale. Authoritative.
  nsfwLevel      a legacy string, from before browsingLevel existed.
  nsfw           a bare boolean, older still.

browsingLevel wins whenever it is present. The other two remain because none
of these fields has historically been dependable, and an image that arrives
without the integer still has to be classified rather than waved through.

WHY THE LEGACY MAP LOOKS THE WAY IT DOES
Measured against 67,458 stored images, the legacy string and browsingLevel
correspond exactly:

    None   -> 1  (20,489 images, no exceptions)
    Soft   -> 2  ( 6,020 images, no exceptions)
    Mature -> 4  (12,388 images, no exceptions)
    X      -> 16 or 8 (28,561 images; the only string that splits)

An earlier map read Soft as R and Mature as X - one level harsher than Civitai
means - which pushed 27% of images up a grade and quietly dropped their models
out of a filtered view.
"""
import gzip
import hashlib
import json
import os
import re
import threading
import zlib
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple

from .forge_host import DEFAULTS, setting
from .console import say

# ---------------------------------------------------------------- vocabulary

PG = 1
PG13 = 2
R = 4
X = 8
XXX = 16
BLOCKED = 32
UNKNOWN = 64

#: Everything a "safe for work" view should admit: PG and PG-13.
SFW_MAX = PG | PG13  # 3

#: The levels a person can give one of their own images. Blocked and Unknown
#: are what Civitai or nobody says, not a rating anyone chooses.
USER_LEVELS = (PG, PG13, R, X, XXX)


def user_level(value: Any) -> Optional[int]:
    """
    A rating a person gave, checked: one of USER_LEVELS, or None for none -
    the image goes back to the level its prompt gives it.

    Raises:
        ValueError: for anything else.
    """
    if value is None or value == "":
        return None
    level = int(value)
    if level not in USER_LEVELS:
        raise ValueError(f"not a level one can rate an image: {value!r}")
    return level

LEVEL_TO_NAME = {
    PG: "PG",
    PG13: "PG-13",
    R: "R",
    X: "X",
    XXX: "XXX",
    BLOCKED: "Blocked",
    UNKNOWN: "Unknown",
}

NAME_TO_LEVEL = {
    "PG": PG,
    "PG-13": PG13,
    "R": R,
    "X": X,
    "XXX": XXX,
    "Blocked": BLOCKED,
    "Banned": BLOCKED,   # what older payloads called it
    "Unknown": UNKNOWN,
}

#: The legacy nsfwLevel string, mapped as Civitai's own browsingLevel pairs it.
#: "X" is the one string that spans two levels, so it takes the higher.
LEGACY_NAME_TO_LEVEL = {
    "None": PG,
    "Soft": PG13,
    "Mature": R,
    "X": XXX,
}

#: A bare nsfw=True, with nothing else to go on. Deliberately cautious: it is
#: the last resort, and guessing low would show something unasked for.
NSFW_FLAG_LEVEL = R


def level_name(level: Optional[int]) -> str:
    """Name the most explicit bit set in `level`."""
    if not level or not isinstance(level, int):
        return "Unknown"
    for bit in (BLOCKED, XXX, X, R, PG13, PG):
        if level & bit:
            return LEVEL_TO_NAME[bit]
    return "Unknown"


def parse_level(name: Optional[str]) -> int:
    """Turn a level name back into its bit, Unknown if it is not one."""
    if not name:
        return UNKNOWN
    return NAME_TO_LEVEL.get(name.strip(), UNKNOWN)


# ------------------------------------------------------------------- images

# ------------------------------------------------------------- the prompt
#
# Civitai's raters miss some: an image rated PG whose prompt asks for
# something explicit is not PG. A short list of words that almost never
# appear in a PG prompt catches those. Measured on 100,555 stored images:
# 95% of the images whose prompts use them are rated X or XXX (5% R), and
# they turn up in 256 of 31,745 PG and PG-13 prompts - which are raised.
#
# A flagged image is X: the level Civitai itself gives most such images, one
# step short of XXX, which two of the words fall short of nearly as often.
# Only the positive prompt is read - the same words in a negative prompt
# mean the opposite - and only images rated PG or PG-13 are raised; the rest
# are already hidden wherever PG-13 is the line.

#: The level a PG or PG-13 image is raised to when its prompt is explicit.
PROMPT_LEVEL = X

#: The words shipped with the extension, one per line.
PROMPT_WORDS_FILE = os.path.join(os.path.dirname(__file__), "data", "nsfw_prompt_words.txt")

#: The setting holding a person's own additions.
PROMPT_WORDS_SETTING = "model_manager_nsfw_prompt_words"

_WORD = re.compile(r"[a-z]+")
_words_lock = threading.Lock()
_bundled: Optional[FrozenSet[str]] = None
_extra: Tuple[str, FrozenSet[str]] = ("", frozenset())


def parse_words(text: str) -> FrozenSet[str]:
    """Words from a list: one per line or comma-separated, # starts a comment."""
    words = set()
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0]
        for part in line.split(","):
            words.update(_WORD.findall(part.lower()))
    return frozenset(words)


def prompt_words() -> FrozenSet[str]:
    """The filter words: the bundled list, plus any added in the settings."""
    global _bundled, _extra
    with _words_lock:
        if _bundled is None:
            try:
                with open(PROMPT_WORDS_FILE, encoding="utf-8") as f:
                    _bundled = parse_words(f.read())
            except OSError:
                _bundled = frozenset()
        raw = str(setting(PROMPT_WORDS_SETTING) or "")
        if raw != _extra[0]:
            _extra = (raw, parse_words(raw))
        return _bundled | _extra[1]


# ------------------------------------------------------ the prompt model
#
# The words alone caught 81% of the X and XXX images that have a prompt, and
# picking more of them one at a time stopped paying: a list learned from the
# data caught less, at the same cost in PG images flagged. A model that
# weighs every word, every pair of adjacent words, the negative prompt, the
# ADetailer and hires prompts and the resources used does better. The one
# that ships is trained by tools/train_nsfw_from_civitai.py on 762k prompts
# from the thousand Civitai models with the most images. On a library it
# never saw, it caught 94% of X/XXX at the setting's default, raising 2.2% of
# PG/PG-13; the model it replaced, trained on that library, caught 84% of
# Civitai's own at the same share. The words above still apply as well.
#
# The negative prompt is read as its own words: there they tend to mean the
# opposite, and the model learns that rather than being told.

#: The trained model, shipped with the extension.
PROMPT_MODEL_FILE = os.path.join(os.path.dirname(__file__), "data", "nsfw_prompt_model.json.gz")

#: The setting: what share of PG and PG-13 prompts the model may raise, in
#: percent, as measured on what it was trained on. 0 turns it off.
PROMPT_MODEL_SETTING = "model_manager_nsfw_prompt_model_percent"

#: Which judges a prompt: "model" - the trained model and the words - or
#: "words" alone. A trained model is right more often, and is still wrong
#: sometimes, in ways nobody can point at; the words say exactly what they
#: do. The choice is the user's.
DETECTION_SETTING = "model_manager_nsfw_detection"

_model_lock = threading.Lock()
_model: Optional[Dict[str, Any]] = None
_model_loaded = False


def prompt_features(prompt: str, negative: str = "") -> FrozenSet[str]:
    """
    What the model reads in a prompt: its words, each pair of adjacent words,
    and the negative prompt's words, marked as such. Split as the word list
    is. The trainer uses this same function, so the two cannot drift apart.
    """
    words = _WORD.findall((prompt or "").lower())
    features = set(words)
    features.update(a + "_" + b for a, b in zip(words, words[1:]))
    features.update("neg:" + w for w in _WORD.findall((negative or "").lower()))
    return frozenset(features)


#: More of an image's prompt, in other fields: ADetailer's, often the detail
#: that says what an image is, and the hires pass's.
EXTRA_PROMPTS = ("ADetailer prompt", "ADetailer prompt 2nd", "ADetailer prompt 3rd", "Hires prompt")
EXTRA_NEGATIVES = ("ADetailer negative prompt", "ADetailer negative prompt 2nd",
                   "ADetailer negative prompt 3rd")


def _text(meta: Dict[str, Any], key: str) -> str:
    value = meta.get(key)
    return value if isinstance(value, str) else ""


def positive_prompts(meta: Dict[str, Any]) -> List[str]:
    """Every positive prompt an image has: its own, then ADetailer's and hires'."""
    return [t for t in [_text(meta, "prompt")] + [_text(meta, k) for k in EXTRA_PROMPTS] if t]


def image_features(meta: Dict[str, Any], version: int = 1) -> FrozenSet[str]:
    """
    What a model of feature set `version` reads in an image's generation data.

    1 - the prompt and negative prompt: prompt_features().
    2 - every positive prompt (positive_prompts(); word pairs within each,
        never across two), every negative one, and the resources the image
        names: civitaiResources by version id, resources by hash. A model
        file says which it was trained on.
    """
    if not isinstance(meta, dict):
        return frozenset()
    if version == 1:
        return prompt_features(_text(meta, "prompt"), _text(meta, "negativePrompt"))
    features = set()
    for prompt in positive_prompts(meta):
        features |= prompt_features(prompt)
    for key in ("negativePrompt",) + EXTRA_NEGATIVES:
        features |= prompt_features("", _text(meta, key))
    for resource in meta.get("civitaiResources") or []:
        if isinstance(resource, dict) and resource.get("modelVersionId"):
            features.add("res:v%s" % resource["modelVersionId"])
    for resource in meta.get("resources") or []:
        if isinstance(resource, dict) and resource.get("hash"):
            features.add("res:h%s" % str(resource["hash"]).lower())
    return frozenset(features)


def feature_hash(feature: str, bits: int) -> int:
    """Where a feature's weight is kept: CRC-32 of it, in `bits` bits."""
    return zlib.crc32(feature.encode()) & ((1 << bits) - 1)


def prompt_model() -> Optional[Dict[str, Any]]:
    """The trained model, loaded once; None if it is missing or unreadable."""
    global _model, _model_loaded
    with _model_lock:
        if not _model_loaded:
            _model_loaded = True
            try:
                with gzip.open(PROMPT_MODEL_FILE, "rt", encoding="utf-8") as f:
                    raw = json.load(f)
                raw["weights"] = dict(zip(raw.pop("keys"), raw.pop("values")))
                raw.setdefault("features", 1)
                with open(PROMPT_MODEL_FILE, "rb") as f:
                    raw["digest"] = hashlib.sha1(f.read()).hexdigest()
                _model = raw
            except (OSError, ValueError, KeyError, TypeError) as e:
                say(f"NSFW prompt model not loaded: {e}")
                _model = None
        return _model


def detection() -> str:
    """The setting: "model" or "words"."""
    return "words" if setting(DETECTION_SETTING) == "words" else "model"


def prompt_model_percent() -> float:
    """The setting, as a number; the default where it cannot be read."""
    try:
        return max(0.0, float(setting(PROMPT_MODEL_SETTING)))
    except (TypeError, ValueError):
        return DEFAULTS[PROMPT_MODEL_SETTING]


def prompt_model_threshold() -> Optional[float]:
    """
    The score above which the model calls a prompt explicit, for the setting's
    percentage - read off the calibration the trainer measured, between its
    points in straight lines. None when the model is off or missing - or
    not chosen: the words alone judge then.
    """
    if detection() == "words":
        return None
    model = prompt_model()
    percent = prompt_model_percent()
    if model is None or percent <= 0:
        return None
    points = sorted((float(p), float(t)) for p, t in model.get("calibration", []))
    if not points:
        return None
    if percent <= points[0][0]:
        return points[0][1]
    for (p0, t0), (p1, t1) in zip(points, points[1:]):
        if percent <= p1:
            return t0 + (t1 - t0) * (percent - p0) / (p1 - p0)
    return points[-1][1]


def prompt_score(meta: Dict[str, Any]) -> Optional[float]:
    """How explicit the model reads an image's generation data as; None without a model."""
    model = prompt_model()
    if model is None:
        return None
    bits, weights = model["bits"], model["weights"]
    return model["bias"] + sum(weights.get(feature_hash(f, bits), 0.0)
                               for f in image_features(meta, model["features"]))


def prompt_words_fingerprint() -> str:
    """
    Changes whenever the verdict can - the words, the model or its setting -
    so stored levels know to be redone.
    """
    model = prompt_model()
    # "rule": what is read changed - the words now read every positive prompt.
    parts = sorted(prompt_words()) + ["rule:2",
        "model:" + (model["digest"] if model else "none"),
        "threshold:" + repr(prompt_model_threshold()),
    ]
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()


def prompt_is_explicit(image: Dict[str, Any]) -> bool:
    """
    Whether an image's own prompt is explicit: any of its positive prompts -
    its own, ADetailer's, hires' - uses a filter word - whole words, any case;
    anything not a letter separates them, so tag_words, (weighted:1.2) and
    <lora:names> are read as the words they hold - or the prompt model scores
    it above the setting's threshold. An image with no prompt of its own is
    left to its rating: the model's calibration is measured on those that do.
    """
    meta = image.get("meta")
    if not isinstance(meta, dict) or not _text(meta, "prompt"):
        return False
    words = prompt_words()
    if words and any(not words.isdisjoint(_WORD.findall(p.lower())) for p in positive_prompts(meta)):
        return True
    threshold = prompt_model_threshold()
    return threshold is not None and prompt_score(meta) > threshold


def image_level(image: Dict[str, Any]) -> int:
    """
    How explicit one image is: Civitai's rating, raised to X when an image
    rated PG or PG-13 has an explicit prompt. Every view judges by this.

    Args:
        image: An image payload from Civitai.

    Returns:
        A level from the scale above.
    """
    level = rated_level(image)
    if level <= SFW_MAX and prompt_is_explicit(image):
        return PROMPT_LEVEL
    return level


def generated_level(meta: Optional[Dict[str, Any]]) -> int:
    """
    How explicit one of your own images is: its prompt is all there is to go
    on, as nobody has rated it. PG, unless its prompt is explicit by the rule
    every Civitai image is held to (prompt_is_explicit()), when it is X - as
    a PG image with that prompt would be.

    Args:
        meta: The image's generation data, as a Civitai image's meta: prompt,
            negativePrompt, and "Hires prompt", "ADetailer prompt" and the
            rest under their infotext names.
    """
    return PROMPT_LEVEL if prompt_is_explicit({"meta": meta or {}}) else PG


def stamp_levels(images: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """
    Write each image's level on it, for the browser, in place.

    mm_level is image_level(); mm_level_from_prompt says the prompt rule is
    what set it, for the "X · prompt" badge. The browser used to judge the
    images it was sent itself, with a copy of this rule in common.mjs and the
    words fetched to feed it - two implementations that had to agree. Every
    image it shows passes through this server, so it is judged here, once,
    and the browser reads the answer.
    """
    for image in images or []:
        if isinstance(image, dict):
            level = image_level(image)
            image["mm_level"] = level
            image["mm_level_from_prompt"] = level != rated_level(image)
    return images


def rated_level(image: Dict[str, Any]) -> int:
    """
    How explicit Civitai says one image is, and nothing else.

    Prefers browsingLevel, falls back to the legacy string, then to the bare
    boolean, and finally admits it does not know.

    Args:
        image: An image payload from Civitai.

    Returns:
        A level from the scale above.
    """
    browsing = image.get("browsingLevel")
    if isinstance(browsing, int) and browsing > 0:
        return browsing

    legacy = image.get("nsfwLevel")
    if isinstance(legacy, int) and legacy > 0:
        # Some payloads put the integer in the old field.
        return legacy
    if isinstance(legacy, str):
        level = LEGACY_NAME_TO_LEVEL.get(legacy)
        if level:
            return level

    if image.get("nsfw") is True:
        return NSFW_FLAG_LEVEL
    if image.get("nsfw") is False:
        return PG

    return UNKNOWN


def version_covers(images: Optional[List[Dict[str, Any]]],
                   complete: bool) -> Tuple[Optional[str], Optional[str]]:
    """
    A version's two cover images: one for NSFW allowed, one for NSFW hidden.

    The cover is the first of the images the creator attached to a version
    (its showcase) - what Civitai shows as the version's image. With NSFW
    hidden the card needs a safe image instead, safe meaning what it means
    everywhere else here: PG or PG-13. If the cover is one, it is the safe
    cover too; if not, the first safe image after it. A showcase with no safe
    image has no safe cover, and the card then looks in the gallery - see
    query_models_grouped().

    Only a complete showcase says which image is the cover, and which safe
    one comes first. /models/{id} returns one, and /models?ids= does with
    nsfw=true; /model-versions/by-hash never does, whatever it is asked - it
    keeps PG only - and nor may a .civitai.info that one of those wrote. A
    stripped showcase's first image is still safe, so it stands in as the
    safe cover until a complete one replaces it; it cannot stand in for the
    cover.

    Args:
        images: The version's showcase, or None if the payload had none.
        complete: Whether it is known to be unstripped.

    Returns:
        (cover, safe cover). None means unknown - keep what is stored - and
        '' means known to be absent.
    """
    if images is None:
        return None, None
    urls = [img for img in images if img.get("url")]
    safe = next((img["url"] for img in urls if image_level(img) <= SFW_MAX), "")
    cover = (urls[0]["url"] if urls else "") if complete else None
    if not complete and not safe:
        # A stripped showcase with nothing left says nothing either way.
        safe = None
    return cover, safe


def showcase_is_complete(images: List[Dict[str, Any]]) -> bool:
    """
    Whether a showcase read from somewhere unknown - a .civitai.info written
    by whatever wrote it - provably still has its non-PG images. One that is
    all PG may have been stripped, so the cover cannot be taken from it.
    """
    # Civitai's rating, not ours: the question is whether Civitai stripped
    # the showcase, and it strips by its own rating.
    return any(rated_level(img) != PG for img in images)


def max_image_level(images: Iterable[Dict[str, Any]]) -> int:
    """The most explicit level among `images`, or Unknown if there are none."""
    levels = [image_level(image) for image in images]
    return max(levels) if levels else UNKNOWN


# ------------------------------------------------------------------- models

def max_mode_ceiling(levels: Iterable[int]) -> int:
    """
    The exclusive upper bound for a "nothing above this" filter.

    Levels are bit flags, so a model can sit at 3 - PG|PG-13 - meaning its
    gallery spans both. Asking for "PG-13 and below" therefore cannot be
    `<= 2`, which would exclude that model; it has to be "no bit set at or
    above the next flag up", which is `< 4`.

    Returns the bound to compare with `<`, so callers do not have to know
    that doubling the highest chosen level is what expresses it.
    """
    chosen = [level for level in levels if level]
    return (max(chosen) * 2) if chosen else (UNKNOWN * 2)


def model_level_sql(model_column: str, version_column: str, images_subquery: str) -> str:
    """
    model_level(), written as SQL.

    The grid filters on this in the database rather than in Python, so the
    rule exists twice; keeping the SQL here means it is at least beside the
    Python it has to agree with.

    Unknown is dropped to 0 before the MAX and restored afterwards, because
    it is not a level on the scale - see model_level().
    """
    def known(expr: str) -> str:
        return f"COALESCE(NULLIF({expr}, {UNKNOWN}), 0)"

    highest = (f"MAX({known(model_column)}, "
               f"{known(version_column)}, "
               f"{known('(%s)' % images_subquery)})")
    return f"COALESCE(NULLIF({highest}, 0), {UNKNOWN})"


def model_level(model_level_: Optional[int],
                version_level: Optional[int],
                highest_image_level: Optional[int]) -> int:
    """
    How explicit a model is, as the grid and its filters see it.

    The most explicit of its own rating, the version's, and the worst picture
    in its gallery - because a gallery is what someone actually sees when they
    open it, whatever the model is nominally rated.

    Unknown is the absence of a rating, not a rating above XXX, so it does not
    take part in the comparison. It used to: UNKNOWN is 64, the largest value
    on the scale, so a single missing component carried the whole model past
    every ceiling a filter could set. Civitai leaves nsfwLevel off most version
    payloads, which made 746 of 747 local versions unfilterable.

    A model is Unknown only when nothing about it is known.
    """
    known = [level for level in (model_level_, version_level, highest_image_level)
             if level and level != UNKNOWN]
    return max(known) if known else UNKNOWN
