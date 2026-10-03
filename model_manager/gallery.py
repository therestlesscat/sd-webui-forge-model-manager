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

PAGE_SIZE_SETTING = "model_manager_gallery_page_size"
# A sync fetches a gallery's first page in one request, and Civitai answers at
# most 200 images to one; a larger size, set by hand in config.json, failed
# the fetch instead of paging.
MAX_PAGE_SIZE = 200


def gallery_page_size() -> int:
    """The page size the settings give, kept to something that works."""
    try:
        size = int(setting(PAGE_SIZE_SETTING))
    except (TypeError, ValueError):
        size = DEFAULTS[PAGE_SIZE_SETTING]
    return min(max(size, 1), MAX_PAGE_SIZE)


# The most images Civitai's /images gives to one request: the client asks
# for no more, whatever it is passed.
IMAGES_PER_REQUEST = 100


def refresh_size(stored: int, keep_count: bool) -> int:
    """
    How many images a refresh of a gallery fetches (#103): a page, at the
    size the settings give, or as many as the version has stored - never
    fewer than a page. A refresh replaces the stored gallery whole, so the
    first deletes what was stored past it.
    """
    page = gallery_page_size()
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


def filter_images(images: List[Dict[str, Any]], hide_nsfw: bool,
                  hide_promptless: bool) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Civitai images through the switches: judged by nsfw.py, read by prompt_rules."""
    return switch_counts(
        images,
        [image_level(img) <= SFW_MAX for img in images],
        [image_readable(img) for img in images],
        hide_nsfw, hide_promptless)
