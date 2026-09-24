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

from .client import CivitaiClient, CivitaiRateLimitError

FILTER_TOKEN_PREFIX = "mmfilter:"

# check()'s answers in the filter loop, besides a reason string.
KEEP = object()
SKIPPED = object()
RATE_LIMITED = object()

# The shortest prompt worth showing, in characters after trimming. Mirrors
# MIN_PROMPT_LENGTH in javascript/shared/common.mjs - the grid and the server
# have to agree about what counts as a prompt, or one hides what the other
# shows. Below four is "1", ".", "???"; never something someone wrote.
MIN_PROMPT_LENGTH = 4


def image_has_usable_prompt(img: Dict[str, Any]) -> bool:
    """
    True if an image carries a prompt *and* the parameters needed to reproduce it.

    A bare prompt is not much use without steps/sampler/cfg - "Send to txt2img"
    would produce something unrelated. The prompt must also be long enough to
    be one: this used to accept "1" as long as the settings were present.

    Args:
        img: Image dict, already enriched with generation data.

    Returns:
        Whether the image is worth showing when filtering for usable prompts.
    """
    meta = img.get("meta") or {}

    if len((meta.get("prompt") or "").strip()) < MIN_PROMPT_LENGTH:
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
    count_usable_images: Optional[Callable[[Dict[str, Any]], int]],
    page_size: int,
    min_usable: int = 1,
    start_token: Optional[str] = None,
    max_checks: Optional[int] = None,
    batch_size: int = 20,
    workers: int = 4,
    accept: Optional[Callable[[Dict[str, Any]], bool]] = None,
    max_searches: Optional[int] = None,
    inspect: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
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
        batch_size=batch_size, workers=workers, accept=accept, max_searches=max_searches,
        inspect=inspect,
    ):
        if kind == "done":
            summary = payload

    return summary


def iter_models_with_usable_prompts(
    client: CivitaiClient,
    search_params: Dict[str, Any],
    count_usable_images: Optional[Callable[[Dict[str, Any]], int]],
    page_size: int,
    min_usable: int = 1,
    start_token: Optional[str] = None,
    max_checks: Optional[int] = None,
    batch_size: int = 20,
    workers: int = 4,
    accept: Optional[Callable[[Dict[str, Any]], bool]] = None,
    max_searches: Optional[int] = None,
    inspect: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
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

    `accept` is a second filter, for anything decidable from the search
    result alone (the file size filter). It runs first, costs nothing, and a
    model it rejects is never prompt-checked. With no prompt check at all
    (`count_usable_images` None) it is the only filter. Either way a narrow
    one can mean many batches for one page, so `max_searches` bounds the
    search calls the same way `max_checks` bounds the prompt checks.

    `inspect` is the general form of the costly check, for more than one
    question per model: it returns None to keep a model, or why it was left
    out - "prompt" or "nsfw" - and each reason is counted on its own. It
    replaces `count_usable_images`; give one or the other.

    If Civitai rate-limits a search or a check (CivitaiRateLimitError), the
    page stops there with `rate_limited` set, and the token points at the
    model that was not checked, so Next retries it rather than skipping it.

    Args:
        client: Civitai client.
        search_params: Arguments for client.search_models (without limit/cursor).
        count_usable_images: Returns how many usable-prompt images a model
            has, or None for no prompt check.
        page_size: How many models to return.
        min_usable: Minimum usable-prompt images for a model to qualify.
        start_token: Token from a previous call, or a plain cursor, or None.
        max_checks: Maximum models to check before giving up on filling the page.
        batch_size: Models to pull from Civitai per search call.
        accept: Free check run before the prompt check; False drops the model.
        max_searches: Maximum search calls before giving up on filling the page.
        inspect: Costly check returning None to keep, or a reason to drop.

    Yields events as the work happens, so a caller can show results while the
    rest are still being checked:
        ("progress", {"checked", "dropped", "unsafe", "failed", "rejected", "found"})
            after each search and before each chunk of costly checks
        ("model", model) as each qualifying model is found
        ("done", summary) once, last, with nextCursor and final counts

    Yields:
        Tuples of (event kind, payload).
    """
    if inspect is not None and count_usable_images is not None:
        raise ValueError("give count_usable_images or inspect, not both")
    if count_usable_images is not None:
        def inspect(model):
            return None if count_usable_images(model) >= min_usable else "prompt"

    cursor, index = decode_filter_token(start_token)

    models: List[Dict[str, Any]] = []
    batch: Optional[List[Dict[str, Any]]] = None
    batch_next_cursor: Optional[str] = None
    checked = 0       # costly checks made, which is what max_checks bounds
    dropped = 0       # failed the prompt check
    unsafe = 0        # failed the SFW check
    failed = 0        # the check itself failed, so nothing is known
    rejected = 0      # failed accept(), never given a costly check
    searches = 0
    exhausted = False
    budget_reached = False
    rate_limited = False

    def counts():
        return {"checked": checked, "dropped": dropped, "unsafe": unsafe,
                "failed": failed, "rejected": rejected, "found": len(models)}

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

            # The token already points at the start of this batch, so a page
            # cut short here resumes exactly where it stopped.
            if max_searches is not None and searches >= max_searches:
                budget_reached = True
                break

            try:
                result = client.search_models(**search_params, limit=batch_size, cursor=cursor)
            except CivitaiRateLimitError:
                rate_limited = budget_reached = True
                break
            searches += 1
            batch = result.get("items", []) or []
            batch_next_cursor = result.get("nextCursor")

            # Each search is a wait of its own, and with only the size filter
            # there is no per-chunk progress below to say anything is moving.
            yield "progress", counts()

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

        # Pass over what the free check rejects before any prompt check is
        # spent on it. Consumed in order, so the resume token stays exact.
        if accept is not None:
            while index < len(batch) and not accept(batch[index]):
                index += 1
                rejected += 1
            if index >= len(batch):
                continue

        # No costly check: whatever accept() let through qualifies as it is.
        if inspect is None:
            model = batch[index]
            index += 1
            models.append(model)
            yield "model", model
            continue

        # Check several models at once - each check is a couple of network
        # round trips, so this is the difference between a page taking seconds
        # and taking tens of seconds. Results are consumed strictly in order so
        # the resume token stays exact.
        yield "progress", counts()

        remaining_budget = (max_checks - checked) if max_checks is not None else len(batch)
        take = max(1, min(workers, len(batch) - index, remaining_budget))
        chunk = batch[index:index + take]

        # What check() says about a model: KEEP, a reason string, SKIPPED
        # for one accept() rules out (costing no check), or RATE_LIMITED.
        def check(model):
            if accept is not None and not accept(model):
                return SKIPPED
            try:
                return inspect(model) or KEEP
            except CivitaiRateLimitError:
                return RATE_LIMITED
            except Exception as e:
                # Never let one bad model abort the whole page
                print(f"[ModelManager] Check failed for model {model.get('id')}: {e}")
                return "prompt" if count_usable_images is not None else "failed"

        if len(chunk) == 1:
            verdicts = [check(chunk[0])]
        else:
            with ThreadPoolExecutor(max_workers=len(chunk)) as executor:
                verdicts = list(executor.map(check, chunk))

        checked += sum(1 for v in verdicts if v not in (SKIPPED, RATE_LIMITED))

        # Anything checked past the end of the page is left for the next one.
        # Its answer is cached now, so checking it again there costs nothing.
        consumed = 0
        for model, verdict in zip(chunk, verdicts):
            if len(models) >= page_size:
                break
            if verdict is RATE_LIMITED:
                # Not consumed: the token points here, so Next retries it.
                rate_limited = budget_reached = True
                break
            consumed += 1
            if verdict is SKIPPED:
                rejected += 1
            elif verdict is KEEP:
                models.append(model)
                yield "model", model
            elif verdict == "nsfw":
                unsafe += 1
            elif verdict == "failed":
                failed += 1
            else:
                dropped += 1

        index += consumed
        if rate_limited:
            break

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
        "unsafe": unsafe,
        "failed": failed,
        "rejected": rejected,
        "budget_reached": budget_reached,
        "rate_limited": rate_limited,
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


def keep_generation_data(images: List[Dict[str, Any]],
                         previous: Optional[List[Dict[str, Any]]]) -> int:
    """
    Give freshly fetched images the generation data their stored copies had.

    /images returns meta: null. The prompt, the settings and the resources
    come from a separate lookup, which a sync may skip ("Image prompts"
    unticked) and which fails without an API key. A gallery replaced with only
    what /images says therefore lost every prompt it had. So before one is
    replaced, each image whose fresh copy has no prompt takes the meta its
    stored copy had; anything the fresh meta does carry wins. Everything else
    about the image comes from the fresh copy.

    Call it before the lookup: what is carried over is not looked up again.

    Args:
        images: The fresh images, changed in place.
        previous: The same version's images as stored, or None.

    Returns:
        How many images kept their generation data.
    """
    if not images or not previous:
        return 0

    stored = {img.get("id"): img.get("meta") for img in previous
              if img.get("id") and img.get("meta")}
    kept = 0

    for img in images:
        old = stored.get(img.get("id"))
        fresh = img.get("meta") or {}
        if not old or fresh.get("prompt"):
            continue
        merged = dict(old)
        merged.update({key: value for key, value in fresh.items() if value is not None})
        img["meta"] = merged
        kept += 1

    return kept


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
