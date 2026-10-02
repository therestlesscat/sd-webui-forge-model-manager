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
from typing import Any, Dict, List, Sequence, Tuple

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
