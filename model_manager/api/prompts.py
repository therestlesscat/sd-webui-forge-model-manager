"""
Deciding whether a model is worth opening.

The browser can filter to models whose example images carry a usable prompt,
or to models whose example images are all safe for work. Civitai can answer
neither, so each candidate has to be looked at - which is expensive, and why
the answers are cached as they are gathered.
"""
import threading
import time
from typing import Any, Dict, Optional, Tuple

from ..civitai import enrich_images_with_generation_data, image_has_usable_prompt
from ..nsfw import SFW_MAX, image_level


# One /images call plus one generation-data batch, so ~2 requests per model.
PROMPT_SAMPLE_SIZE = 20

# Models checked concurrently. Each check is ~2 requests, so this multiplies
# throughput up to whatever the client's rate limiter allows.
PROMPT_CHECK_WORKERS = 4


def count_usable_prompt_images(client, db, model, sample_size: int = PROMPT_SAMPLE_SIZE,
                               fetched: Optional[Dict[str, Any]] = None) -> int:
    """
    Count how many of a model's first images carry a usable prompt.

    Answers "is this model worth opening" for the browse filter. Results are
    written to the browse cache, so the work also pre-loads the gallery: a
    model that passes the filter opens instantly with its prompts already in
    place. Cached versions cost no requests at all.

    Args:
        client: Civitai client.
        db: Models database (for the browse cache).
        model: Model dict from the search response.
        sample_size: How many images to look at.
        fetched: The /images answer for this version, if the caller already
            asked for it - the SFW check does, and one request serves both.

    Returns:
        Number of sampled images with a usable prompt.
    """
    versions = model.get("modelVersions") or []
    if not versions:
        return 0

    version = versions[0]
    version_id = version.get("id")
    if not version_id:
        return 0

    cached = db.get_cached_browse_images(version_id)
    if cached:
        return sum(1 for img in cached if image_has_usable_prompt(img))

    result = fetched if fetched is not None else client.get_model_images(
        version_id, cursor=None, limit=sample_size)
    images = result.get("images", []) or []
    enrich_images_with_generation_data(client, images)

    if images:
        model_id = model.get("id")
        db.store_browse_images(model_id, version_id, images)
        next_cursor = result.get("next_cursor")
        if next_cursor:
            db.store_browse_cursor(model_id, version_id, next_cursor)

    return sum(1 for img in images if image_has_usable_prompt(img))


# ------------------------------------------------------------ SFW examples
# What the SFW check has decided, per version: (has an NSFW image, when).
# Most models on Civitai have NSFW images, so most checks fail, and a page
# can take dozens of them. Remembering the answer - pass or fail - makes
# paging back, or searching again, cost nothing.
#
# This is kept here rather than in the browse image cache because images
# the SFW check fetches have not had their generation data filled in, and
# the prompt check trusts cached images to have it.
SFW_VERDICT_TTL_SECONDS = 6 * 60 * 60
_sfw_verdicts: Dict[int, Tuple[bool, float]] = {}
_sfw_lock = threading.Lock()


def has_nsfw_image(images) -> bool:
    """
    Whether any of these images is above PG-13 - R and up, Blocked, or not
    rated at all. A strict check: an image nobody has rated is not known to
    be safe.
    """
    return any(image_level(image) > SFW_MAX for image in images)


def _remembered_sfw(version_id: int) -> Optional[bool]:
    with _sfw_lock:
        entry = _sfw_verdicts.get(version_id)
    if entry and time.time() - entry[1] < SFW_VERDICT_TTL_SECONDS:
        return entry[0]
    return None


def _remember_sfw(version_id: int, has_nsfw: bool) -> None:
    with _sfw_lock:
        _sfw_verdicts[version_id] = (has_nsfw, time.time())


def forget_sfw_verdicts() -> None:
    """Clear what the SFW check remembers. For tests."""
    with _sfw_lock:
        _sfw_verdicts.clear()


def inspect_model(client, db, model, *, want_prompts: bool, want_sfw: bool,
                  min_usable: int = 1,
                  sample_size: int = PROMPT_SAMPLE_SIZE) -> Optional[str]:
    """
    Run the costly checks on one model, spending at most one /images request.

    The SFW check goes first: it needs no generation data, so a model it rules
    out never costs the lookup the prompt check makes. When both are on, the
    images it fetched are handed to the prompt check rather than asked for
    again.

    A model with no images fails both: the SFW check, since nothing shows it
    does not generate NSFW, and the prompt check, which needs prompts to reuse.

    Returns:
        None to keep the model, or why it was left out: "nsfw" or "prompt".
        CivitaiRateLimitError is not caught; the filter loop stops on it.
    """
    versions = model.get("modelVersions") or []
    version_id = versions[0].get("id") if versions else None

    fetched = None
    if want_sfw and not version_id:
        return "nsfw"       # no version, no images: nothing shows it is safe
    if want_sfw:
        has_nsfw = _remembered_sfw(version_id)
        if has_nsfw is None:
            cached = db.get_cached_browse_images(version_id)
            if cached:
                images = cached[:sample_size]
            else:
                fetched = client.get_model_images(version_id, cursor=None, limit=sample_size)
                images = (fetched.get("images") or [])[:sample_size]
            # No images is not a pass: nothing shows the model is safe.
            has_nsfw = not images or has_nsfw_image(images)
            _remember_sfw(version_id, has_nsfw)
        if has_nsfw:
            return "nsfw"

    if want_prompts:
        usable = count_usable_prompt_images(client, db, model, sample_size, fetched=fetched)
        if usable < min_usable:
            return "prompt"

    return None
