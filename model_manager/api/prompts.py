"""
Deciding whether a model is worth opening.

The browser can filter to models whose example images carry a usable prompt.
Civitai cannot answer that, so each candidate has to be looked at - which is
expensive, and why the answers are cached as they are gathered.
"""
from ..civitai import enrich_images_with_generation_data, image_has_usable_prompt


# One /images call plus one generation-data batch, so ~2 requests per model.
PROMPT_SAMPLE_SIZE = 20

# Models checked concurrently. Each check is ~2 requests, so this multiplies
# throughput up to whatever the client's rate limiter allows.
PROMPT_CHECK_WORKERS = 4


def count_usable_prompt_images(client, db, model, sample_size: int = PROMPT_SAMPLE_SIZE) -> int:
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

    result = client.get_model_images(version_id, cursor=None, limit=sample_size)
    images = result.get("images", []) or []
    enrich_images_with_generation_data(client, images)

    if images:
        model_id = model.get("id")
        db.store_browse_images(model_id, version_id, images)
        next_cursor = result.get("next_cursor")
        if next_cursor:
            db.store_browse_cursor(model_id, version_id, next_cursor)

    return sum(1 for img in images if image_has_usable_prompt(img))
