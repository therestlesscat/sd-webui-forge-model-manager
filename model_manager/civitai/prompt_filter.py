"""
Finding models you could actually reproduce an image from.

The browser can hide models whose example images carry no usable prompt.
Civitai cannot filter on that, so candidates are fetched and examined, which
makes paging awkward: a page of ten may need eighty models looked at, and the
page boundary no longer lines up with Civitai's cursors. The token functions
below carry both the cursor and how far into a batch we had read.

The public /images endpoint returns meta: null, so generation data comes from
a separate call, batched.
"""
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .client import CivitaiClient

FILTER_TOKEN_PREFIX = "mmfilter:"


def image_has_usable_prompt(img: Dict[str, Any]) -> bool:
    """
    True if an image carries a prompt *and* the parameters needed to reproduce it.

    A bare prompt is not much use without steps/sampler/cfg - "Send to txt2img"
    would produce something unrelated.

    Args:
        img: Image dict, already enriched with generation data.

    Returns:
        Whether the image is worth showing when filtering for usable prompts.
    """
    meta = img.get("meta") or {}

    if not (meta.get("prompt") or "").strip():
        return False
    if not meta.get("steps"):
        return False
    if not (meta.get("sampler") or meta.get("Sampler")):
        return False
    if not (meta.get("cfgScale") or meta.get("CFG scale")):
        return False

    return True


def encode_filter_token(cursor: Optional[str], index: int) -> Optional[str]:
    """
    Pack a search cursor plus a within-batch offset into one opaque token.

    When models are filtered out, page boundaries stop lining up with Civitai's
    cursors: a page can end midway through a batch. Recording which batch we
    were in and how far we got makes the next page resume exactly there, and
    keeps the frontend's existing cursor array working unchanged.
    """
    if cursor is None and index <= 0:
        return None

    payload = json.dumps({"c": cursor or "", "i": index}, separators=(",", ":"))
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    return FILTER_TOKEN_PREFIX + encoded


def decode_filter_token(token: Optional[str]) -> Tuple[Optional[str], int]:
    """
    Unpack a token from encode_filter_token().

    A plain Civitai cursor (or nothing) yields an offset of 0, so unfiltered
    and filtered browsing can share the same cursor plumbing.

    Returns:
        Tuple of (cursor, index within that batch).
    """
    if not token:
        return None, 0

    if not token.startswith(FILTER_TOKEN_PREFIX):
        return token, 0

    try:
        raw = base64.urlsafe_b64decode(token[len(FILTER_TOKEN_PREFIX):].encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        return (data.get("c") or None), int(data.get("i", 0))
    except Exception:
        # A malformed token should restart the listing, not break it
        print("[ModelManager] Ignoring malformed browse token")
        return None, 0


def search_models_with_usable_prompts(
    client: CivitaiClient,
    search_params: Dict[str, Any],
    count_usable_images: Callable[[Dict[str, Any]], int],
    page_size: int,
    min_usable: int = 1,
    start_token: Optional[str] = None,
    max_checks: Optional[int] = None,
    batch_size: int = 20,
    workers: int = 4,
) -> Dict[str, Any]:
    """
    Collect a full page of models with usable prompts.

    Thin wrapper over iter_models_with_usable_prompts() for callers that want
    the whole page at once rather than results as they are found.
    """
    summary: Dict[str, Any] = {}

    for kind, payload in iter_models_with_usable_prompts(
        client, search_params, count_usable_images, page_size,
        min_usable=min_usable, start_token=start_token, max_checks=max_checks,
        batch_size=batch_size, workers=workers,
    ):
        if kind == "done":
            summary = payload

    return summary


def iter_models_with_usable_prompts(
    client: CivitaiClient,
    search_params: Dict[str, Any],
    count_usable_images: Callable[[Dict[str, Any]], int],
    page_size: int,
    min_usable: int = 1,
    start_token: Optional[str] = None,
    max_checks: Optional[int] = None,
    batch_size: int = 20,
    workers: int = 4,
):
    """
    Search models, keeping only those with enough usable-prompt images.

    Civitai cannot filter on this, so models are pulled in batches and checked
    one at a time until the page is full. Models that fail the check are
    skipped; the returned token records exactly where to resume, so the ones
    that were never reached show up on the next page rather than being lost.

    Checking costs API calls, so `max_checks` bounds the work per page. Hitting
    that bound returns a short page rather than stalling - the token still
    points at the next unchecked model.

    Args:
        client: Civitai client.
        search_params: Arguments for client.search_models (without limit/cursor).
        count_usable_images: Returns how many usable-prompt images a model has.
        page_size: How many models to return.
        min_usable: Minimum usable-prompt images for a model to qualify.
        start_token: Token from a previous call, or a plain cursor, or None.
        max_checks: Maximum models to check before giving up on filling the page.
        batch_size: Models to pull from Civitai per search call.

    Yields events as the work happens, so a caller can show results while the
    rest are still being checked:
        ("progress", {"checked", "dropped", "found"}) before each chunk
        ("model", model) as each qualifying model is found
        ("done", summary) once, last, with nextCursor and final counts

    Yields:
        Tuples of (event kind, payload).
    """
    cursor, index = decode_filter_token(start_token)

    models: List[Dict[str, Any]] = []
    batch: Optional[List[Dict[str, Any]]] = None
    batch_next_cursor: Optional[str] = None
    checked = 0
    dropped = 0
    exhausted = False
    budget_reached = False

    while len(models) < page_size:
        if max_checks is not None and checked >= max_checks:
            budget_reached = True
            break

        # Need another batch? (first pass, or current one fully consumed)
        if batch is None or index >= len(batch):
            if batch is not None:
                if not batch_next_cursor:
                    exhausted = True
                    break
                cursor = batch_next_cursor
                index = 0

            result = client.search_models(**search_params, limit=batch_size, cursor=cursor)
            batch = result.get("items", []) or []
            batch_next_cursor = result.get("nextCursor")

            if not batch:
                exhausted = True
                break

            # A token can point past the end if the batch shrank; treat as consumed
            if index >= len(batch):
                if not batch_next_cursor:
                    exhausted = True
                    break
                cursor = batch_next_cursor
                index = 0
                continue

        # Check several models at once - each check is a couple of network
        # round trips, so this is the difference between a page taking seconds
        # and taking tens of seconds. Results are consumed strictly in order so
        # the resume token stays exact.
        yield "progress", {"checked": checked, "dropped": dropped, "found": len(models)}

        remaining_budget = (max_checks - checked) if max_checks is not None else len(batch)
        take = max(1, min(workers, len(batch) - index, remaining_budget))
        chunk = batch[index:index + take]

        def check(model):
            try:
                return count_usable_images(model)
            except Exception as e:
                # Never let one bad model abort the whole page
                print(f"[ModelManager] Prompt check failed for model {model.get('id')}: {e}")
                return 0

        if len(chunk) == 1:
            counts = [check(chunk[0])]
        else:
            with ThreadPoolExecutor(max_workers=len(chunk)) as executor:
                counts = list(executor.map(check, chunk))

        checked += len(chunk)

        # Anything checked past the end of the page is left for the next one.
        # Its images are cached now, so re-checking it there costs nothing.
        consumed = 0
        for model, usable in zip(chunk, counts):
            if len(models) >= page_size:
                break
            consumed += 1
            if usable >= min_usable:
                models.append(model)
                yield "model", model
            else:
                dropped += 1

        index += consumed

    if exhausted:
        next_token = None
    elif batch is not None and index >= len(batch):
        # Batch fully consumed - resume at the start of the next one
        next_token = encode_filter_token(batch_next_cursor, 0) if batch_next_cursor else None
    else:
        next_token = encode_filter_token(cursor, index)

    yield "done", {
        "models": models,
        "nextCursor": next_token,
        "checked": checked,
        "dropped": dropped,
        "budget_reached": budget_reached,
        "exhausted": exhausted,
    }


def _map_civitai_resources(resources: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Convert generation-data resources into the `civitaiResources` shape the UI
    expects (type / name / modelVersionId, used for View + Download links).
    """
    mapped = []

    for resource in resources or []:
        if not isinstance(resource, dict):
            continue

        version_id = resource.get("versionId") or resource.get("modelVersionId")
        entry = {
            "type": resource.get("modelType") or "Unknown",
            "name": resource.get("modelName") or resource.get("versionName") or "Unknown",
            "modelId": resource.get("modelId"),
            "modelVersionId": version_id,
            "modelVersionName": resource.get("versionName"),
        }

        if resource.get("strength") is not None:
            entry["weight"] = resource.get("strength")

        mapped.append(entry)

    return mapped


def enrich_images_with_generation_data(
    client: CivitaiClient,
    images: List[Dict[str, Any]]
) -> int:
    """
    Fill in missing generation metadata on images, in place.

    Only images that lack a usable prompt are looked up. Failures are logged
    and swallowed - images are left as-is rather than breaking the caller.

    Args:
        client: Civitai client to use for the lookup.
        images: Image dicts from the /images endpoint (modified in place).

    Returns:
        Number of images that were enriched.
    """
    needs_lookup = generation_ids_needing_lookup(images)
    if not needs_lookup:
        return 0

    try:
        generation_data = client.get_generation_data(needs_lookup)
    except Exception as e:
        print(f"[ModelManager] Generation data lookup failed: {e}")
        return 0

    return apply_generation_data(images, generation_data)


def generation_ids_needing_lookup(images: List[Dict[str, Any]]) -> List[int]:
    """
    The image ids whose generation data still has to be fetched.

    Split out from enrich_images_with_generation_data() so a caller holding
    several galleries can pool their ids into one set of batches. The lookup
    costs one request per 30 ids however they are grouped, so a batch filled
    from a single gallery is mostly half-empty - see SyncService.
    """
    if not images:
        return []
    return [
        img.get("id") for img in images
        if img.get("id") and not (img.get("meta") or {}).get("prompt")
    ]


def apply_generation_data(images: List[Dict[str, Any]],
                          generation_data: Dict[int, Dict[str, Any]]) -> int:
    """
    Write looked-up generation data onto `images`, in place.

    The other half of enrich_images_with_generation_data(): it takes what the
    lookup returned rather than performing it, so one pooled lookup can be
    spread back over the galleries its ids came from.
    """
    if not generation_data:
        return 0

    enriched = 0

    for img in images:
        data = generation_data.get(img.get("id"))
        if not data:
            continue

        meta = data.get("meta") or {}
        if not meta:
            continue

        # Keep anything the existing meta had that the new one lacks
        merged = dict(meta)
        for key, value in (img.get("meta") or {}).items():
            merged.setdefault(key, value)

        civitai_resources = _map_civitai_resources(data.get("resources"))
        if civitai_resources:
            merged["civitaiResources"] = civitai_resources

        img["meta"] = merged
        enriched += 1

    return enriched
