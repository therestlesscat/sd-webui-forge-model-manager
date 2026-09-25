"""
How explicit is this? - asked and answered in one place.

Civitai reports maturity three different ways, and they do not always agree.
This module decides which to believe, so the scan, the sync, the image store
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
from typing import Any, Dict, Iterable, List, Optional, Tuple

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

def image_level(image: Dict[str, Any]) -> int:
    """
    How explicit one image is.

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
    return any(image_level(img) != PG for img in images)


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
