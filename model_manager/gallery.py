"""
What a gallery page is, for every gallery: both tabs' Civitai images and your
generations.

A page is a slice of what is stored, in gallery order - its size a setting,
100 by default - taken before the NSFW and prompt switches, which only decide
which of its images are drawn. A page the library cannot fill is filled from
Civitai first (api/images.gallery_page). So a page is the same whatever the
switches say, and whatever size the images were fetched in.

Every gallery counts what its two switches hide here (switch_counts), so the
number beside a switch and the banner's mean the same in every tab, and hold
when a switch is flipped; only how a gallery tells safe and readable differs.
Where a gallery's images come from is its own business, not this module's.

Kept apart from api/ and ui/, which both read it, so neither imports the other.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .forge_host import DEFAULTS, setting
from .nsfw import SFW_MAX, image_level
from .prompt_rules import image_readable

# What each gallery with pages pages by, and how many images a sync keeps
# (#230): one setting did all of it, so 5 Civitai images a page also meant 5
# of your own and 5 kept by a sync.
MM_IMAGES_SETTING = "model_manager_mm_images_per_page"
CB_IMAGES_SETTING = "model_manager_cb_images_per_page"
GENERATIONS_SETTING = "model_manager_mm_generations_per_page"
SYNC_IMAGES_SETTING = "model_manager_sync_images_per_version"
PAGE_SETTINGS = (MM_IMAGES_SETTING, CB_IMAGES_SETTING, GENERATIONS_SETTING, SYNC_IMAGES_SETTING)
# The one setting they were split from: carried over once (ui/settings.py).
OLD_PAGE_SIZE_SETTING = "model_manager_gallery_page_size"
MIN_PAGE_SIZE = 5
# A sync fetches a gallery's first page in one request, and Civitai answers at
# most 200 images to one; a larger size, set by hand in config.json, failed
# the fetch instead of paging.
MAX_PAGE_SIZE = 200
# What the Generations tab and the Civitai Images tab add as you scroll near
# the end: a part, not a setting - they have no pages to size.
TILE_PART = 100


def _sized(key: str) -> int:
    """A page size the settings give, kept to something that works."""
    try:
        size = int(setting(key))
    except (TypeError, ValueError):
        size = DEFAULTS[key]
    return min(max(size, MIN_PAGE_SIZE), MAX_PAGE_SIZE)


def mm_images_page_size() -> int:
    """How many images Load More adds in a model's Civitai images, in the Model Manager."""
    return _sized(MM_IMAGES_SETTING)


def cb_images_page_size() -> int:
    """How many images Load More adds in a model's images, in the Civitai Browser."""
    return _sized(CB_IMAGES_SETTING)


def generations_page_size() -> int:
    """How many generations Load More adds in a model's Your generations."""
    return _sized(GENERATIONS_SETTING)


def sync_image_count() -> int:
    """How many of each version's Civitai images a sync fetches and keeps."""
    return _sized(SYNC_IMAGES_SETTING)


def gallery_page_size() -> int:
    """
    What a tab that loads as you scroll adds at a time - the Generations
    tab, the Civitai Images tab - and the frozen v36 reads' page
    (tests/v36_generations.py): TILE_PART, read when asked, so a suite can
    shrink it.
    """
    return TILE_PART


# The most images Civitai's /images gives to one request: the client asks
# for no more, whatever it is passed.
IMAGES_PER_REQUEST = 100


def refresh_size(stored: int, keep_count: bool) -> int:
    """
    How many images a refresh of a gallery fetches (#103): what a sync keeps
    (#230), or as many as the version has stored - never fewer than what a
    sync keeps. A refresh replaces the stored gallery whole, so the first
    deletes what was stored past it.
    """
    page = sync_image_count()
    return max(page, stored) if keep_count else page


def fetch_gallery(client, version_id: int, count: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    A version's first `count` images from Civitai, and the cursor to what
    follows them: batches of IMAGES_PER_REQUEST, Civitai's cursor followed
    until there are enough or it has no more - in no more requests than
    that many batches, which is what the sync dialog says it costs. What
    the client raises, it raises: a refresh replaces the gallery only once
    all of it has come.
    """
    images: List[Dict[str, Any]] = []
    cursor = None
    for _ in range(max(1, math.ceil(count / IMAGES_PER_REQUEST))):
        if len(images) >= count:
            break
        result = client.get_model_images(version_id, cursor=cursor,
                                         limit=min(IMAGES_PER_REQUEST, count - len(images)))
        batch = result.get("images") or []
        images.extend(batch)
        cursor = result.get("next_cursor") or None
        if not batch or not cursor:
            break
    return images, cursor


def switch_counts(items: Sequence[Any], safe: Sequence[bool], readable: Sequence[bool],
                  hide_nsfw: bool, hide_promptless: bool) -> Tuple[List[Any], Dict[str, int]]:
    """
    The items the two switches let through, in order, and the counts - as
    ImagesOps.get_image_counts() means each - over all of them: what each
    switch alone hides, what both do, and what each is acting on.

    Args:
        safe: for each item, whether it is no more than PG-13.
        readable: for each item, whether its prompt is worth reading.
    """
    n = len(items)
    nsfw_kept = [i for i in range(n) if safe[i] or not hide_nsfw]
    shown = [i for i in nsfw_kept if readable[i] or not hide_promptless]
    both = sum(1 for i in range(n)
               if hide_nsfw and hide_promptless and not safe[i] and not readable[i])
    return [items[i] for i in shown], {
        "total": n,
        "filtered": len(shown),
        "hidden_nsfw": n - len(nsfw_kept) - both,
        "hidden_both": both,
        "hidden_promptless": len(nsfw_kept) - len(shown),
        "hidden": n - len(shown),
        "nsfw_count": sum(1 for i in range(n)
                          if not safe[i] and (readable[i] or not hide_promptless)),
        "promptless_count": sum(1 for i in nsfw_kept if not readable[i]),
        "promptless_total": sum(1 for r in readable if not r),
    }


def switch_counts_sql(hide_nsfw: bool, hide_promptless: bool,
                      safe: str = "safe", readable: str = "readable") -> str:
    """
    switch_counts()'s counts as SQL aggregates, each named as it names them,
    over rows whose `safe` and `readable` columns are 1 or 0 - for a read
    that counts in SQL, rather than handing every row to Python (#231).
    switch_counts_test holds the two to the same answers.
    """
    kept = f"({safe} OR NOT {int(bool(hide_nsfw))})"
    shown = f"({kept} AND ({readable} OR NOT {int(bool(hide_promptless))}))"
    both = f"({int(bool(hide_nsfw and hide_promptless))} AND NOT {safe} AND NOT {readable})"
    return ", ".join([
        "COUNT(*) AS total",
        f"TOTAL({shown}) AS filtered",
        f"COUNT(*) - TOTAL({kept}) - TOTAL({both}) AS hidden_nsfw",
        f"TOTAL({both}) AS hidden_both",
        f"TOTAL({kept}) - TOTAL({shown}) AS hidden_promptless",
        f"COUNT(*) - TOTAL({shown}) AS hidden",
        f"TOTAL(NOT {safe} AND ({readable} OR NOT {int(bool(hide_promptless))})) AS nsfw_count",
        f"TOTAL({kept} AND NOT {readable}) AS promptless_count",
        f"TOTAL(NOT {readable}) AS promptless_total",
    ])


def filter_images(images: List[Dict[str, Any]], hide_nsfw: bool,
                  hide_promptless: bool) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Civitai images through the switches: judged by nsfw.py, read by prompt_rules."""
    return switch_counts(
        images,
        [image_level(img) <= SFW_MAX for img in images],
        [image_readable(img) for img in images],
        hide_nsfw, hide_promptless)
