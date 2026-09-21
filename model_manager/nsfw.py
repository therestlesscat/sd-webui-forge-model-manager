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
from typing import Any, Dict, Iterable, Optional

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


def max_image_level(images: Iterable[Dict[str, Any]]) -> int:
    """The most explicit level among `images`, or Unknown if there are none."""
    levels = [image_level(image) for image in images]
    return max(levels) if levels else UNKNOWN


# ------------------------------------------------------------------- models

def model_level(model_level_: Optional[int],
                version_level: Optional[int],
                highest_image_level: Optional[int]) -> int:
    """
    How explicit a model is, as the grid and its filters see it.

    The most explicit of its own rating, the version's, and the worst picture
    in its gallery - because a gallery is what someone actually sees when they
    open it, whatever the model is nominally rated.

    Absent values count as Unknown rather than as safe: a model nobody has
    rated is not thereby harmless.
    """
    return max(
        model_level_ or UNKNOWN,
        version_level or UNKNOWN,
        highest_image_level or UNKNOWN,
    )
