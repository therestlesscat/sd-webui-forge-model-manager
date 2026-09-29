"""
What a gallery page is, for every gallery: both tabs' Civitai images and your
generations.

A page is a slice of what is stored, in gallery order - its size a setting,
100 by default - taken before the NSFW and prompt switches, which only decide
which of its images are drawn. A page the library cannot fill is filled from
Civitai first (api/images.gallery_page). So a page is the same whatever the
switches say, and whatever size the images were fetched in.

Kept apart from api/ and ui/, which both read it, so neither imports the other.
"""

PAGE_SIZE_SETTING = "model_manager_gallery_page_size"
DEFAULT_PAGE_SIZE = 100
# A sync fetches a gallery's first page in one request, and Civitai answers at
# most 200 images to one; a larger size, set by hand in config.json, failed
# the fetch instead of paging.
MAX_PAGE_SIZE = 200


def gallery_page_size() -> int:
    """The page size the settings give, kept to something that works."""
    try:
        from modules import shared
        size = int(getattr(shared.opts, PAGE_SIZE_SETTING, DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError, ImportError):
        size = DEFAULT_PAGE_SIZE
    return min(max(size, 1), MAX_PAGE_SIZE)
