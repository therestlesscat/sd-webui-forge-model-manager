"""
Deciding whether a model is worth opening.

The browser can filter to models whose example images carry a usable prompt,
or to models whose example images are all safe for work. Civitai can answer
neither, so each candidate has to be looked at: its first images, and for the
prompt check, the prompts behind them.

Nothing is kept of the images. The SFW check remembers its verdict for a few
hours; the prompt check asks again each time. What makes that affordable is
checking a chunk of models at once and pooling their prompt lookups: 20
images each, up to 30 ids per lookup, so 8 models cost 8 + 6 requests, not 16.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from ..civitai import (
    CivitaiRateLimitError,
    apply_generation_data,
    generation_ids_needing_lookup,
)
from ..civitai.prompt_filter import RATE_LIMITED
from ..prompt_rules import usable
from ..nsfw import SFW_MAX, image_level
from ..remembered import Remembered
from ..console import say


# Images looked at per model: one /images request.
PROMPT_SAMPLE_SIZE = 20

# Models checked at once, and requests in flight. The client's rate limiter
# paces them whatever this says, so past a few it only decides how many
# prompt lookups one chunk can pool. Measured on 40 models at 6 requests/s:
# 4 workers 13.8 s, 16 workers 11.6 s - the rate limit, not this, is the cap.
PROMPT_CHECK_WORKERS = 8


# ------------------------------------------------------------ SFW examples
# What the SFW check has decided, per version: (has an NSFW image, when).
# Most models on Civitai have NSFW images, so most checks fail, and a page
# can take dozens of them. Remembering the answer - pass or fail - makes
# paging back, or searching again, cost nothing: 40 models took 6.0 s to
# check, and 0.6 s again from here. Only the verdict is kept, in memory.
SFW_VERDICT_TTL_SECONDS = 6 * 60 * 60
# The 2,000 most recent: a session's pages of models, and an old one forgotten
# is only checked again.
_sfw_verdicts = Remembered(most=2000)


def has_nsfw_image(images) -> bool:
    """
    Whether any of these images is above PG-13 - R and up, Blocked, or not
    rated at all. A strict check: an image nobody has rated is not known to
    be safe.
    """
    return any(image_level(image) > SFW_MAX for image in images)


def _remembered_sfw(version_id: int) -> Optional[bool]:
    entry = _sfw_verdicts.get(version_id)
    if entry and time.time() - entry[1] < SFW_VERDICT_TTL_SECONDS:
        return entry[0]
    return None


def _remember_sfw(version_id: int, has_nsfw: bool) -> None:
    _sfw_verdicts[version_id] = (has_nsfw, time.time())


def forget_sfw_verdicts() -> None:
    """Clear what the SFW check remembers. For tests."""
    _sfw_verdicts.clear()


def inspect_models(client, models: List[Dict[str, Any]], *, want_prompts: bool,
                   want_sfw: bool, min_usable: int = 1,
                   sample_size: int = PROMPT_SAMPLE_SIZE,
                   workers: int = PROMPT_CHECK_WORKERS) -> List[Any]:
    """
    Run the costly checks on a chunk of models, spending at most one /images
    request on each, and one set of prompt lookups for the whole chunk.

    The SFW check goes first: it needs no generation data, so a model it rules
    out never costs a lookup. The images it fetched serve the prompt check too.

    A model with no images fails both: the SFW check, since nothing shows it
    does not generate NSFW, and the prompt check, which needs prompts to reuse.

    Returns:
        One verdict per model, in order: None to keep it, why it was left out
        ("nsfw" or "prompt"), "failed" when Civitai could not say, or
        RATE_LIMITED when it refused to - which the filter loop stops on, so
        the model is checked again on the next page rather than dropped.
    """
    verdicts: List[Any] = [None] * len(models)
    to_fetch: List[Tuple[int, int]] = []          # (position, version id)

    for position, model in enumerate(models):
        versions = model.get("modelVersions") or []
        version_id = versions[0].get("id") if versions else None
        if not version_id:
            # No version, no images: nothing shows it is safe, or has prompts
            verdicts[position] = "nsfw" if want_sfw else "prompt"
            continue
        if want_sfw:
            has_nsfw = _remembered_sfw(version_id)
            if has_nsfw:
                verdicts[position] = "nsfw"
                continue
            if has_nsfw is False and not want_prompts:
                continue                          # safe, and nothing else to ask
        to_fetch.append((position, version_id))

    def fetch(entry):
        _, version_id = entry
        try:
            result = client.get_model_images(version_id, cursor=None, limit=sample_size)
            return (result.get("images") or [])[:sample_size]
        except CivitaiRateLimitError:
            return RATE_LIMITED
        except Exception as e:
            say(f"Images for version {version_id} failed: {e}")
            return "failed"

    if len(to_fetch) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(to_fetch))) as executor:
            fetched = list(executor.map(fetch, to_fetch))
    else:
        fetched = [fetch(entry) for entry in to_fetch]

    samples: Dict[int, List[Dict[str, Any]]] = {}
    for (position, version_id), images in zip(to_fetch, fetched):
        if not isinstance(images, list):
            verdicts[position] = images
            continue
        if want_sfw and _remembered_sfw(version_id) is None:
            has_nsfw = not images or has_nsfw_image(images)
            _remember_sfw(version_id, has_nsfw)
            if has_nsfw:
                verdicts[position] = "nsfw"
                continue
        if want_prompts:
            samples[position] = images

    if not samples:
        return verdicts

    pooled = [image_id for images in samples.values()
              for image_id in generation_ids_needing_lookup(images)]
    errors: Dict[int, Exception] = {}
    generation_data: Dict[int, Dict[str, Any]] = {}
    if pooled:
        try:
            generation_data = client.get_generation_data(pooled, workers=workers, errors=errors)
        except Exception as e:
            say(f"Generation data lookup failed: {e}")
            errors = {image_id: e for image_id in pooled}

    for position, images in samples.items():
        if generation_data:
            apply_generation_data(images, generation_data)
        if sum(1 for img in images if usable(img)) >= min_usable:
            continue
        # Too few prompts - unless some were never learned. A lookup that
        # failed says nothing about the model; it used to drop it as promptless.
        lost = [errors[img.get("id")] for img in images if img.get("id") in errors]
        if any(isinstance(e, CivitaiRateLimitError) for e in lost):
            verdicts[position] = RATE_LIMITED
        elif lost:
            verdicts[position] = "failed"
        else:
            verdicts[position] = "prompt"

    return verdicts


def inspect_model(client, model: Dict[str, Any], **options) -> Optional[str]:
    """
    inspect_models() for one model.

    Raises:
        CivitaiRateLimitError: if Civitai refused to answer.
    """
    verdict = inspect_models(client, [model], **options)[0]
    if verdict is RATE_LIMITED:
        raise CivitaiRateLimitError()
    return verdict
