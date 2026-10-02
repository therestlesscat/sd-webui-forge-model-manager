"""
What a sync would cost and cover, before anyone starts one - for the sync
dialog: the requests a metadata sync would make, and how many models each
staleness window holds. Queries and arithmetic over the library; the sync
itself is sync_service.py's.
"""
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .civitai import CivitaiClient
from .db import get_models_db
from .sync_service import SyncService


# ---------------------------------------------------------------- estimating

# The staleness windows the sync dialog offers, shortest first. They are here
# rather than in the UI so the counts beside them and the filter behind them
# cannot drift apart.
SYNC_WINDOWS: List[Tuple[str, int]] = [
    ("1 day", 1),
    ("2 days", 2),
    ("7 days", 7),
    ("1 month", 30),
    ("3 months", 90),
    ("6 months", 180),
]


def window_cutoff(days: int) -> str:
    """The timestamp `days` ago, in the form the database stores."""
    return (datetime.now() - timedelta(days=days)).isoformat()




def estimate_metadata_sync(model_paths: Optional[List[str]] = None,
                           synced_before: Optional[str] = None,
                           downloaded_after: Optional[str] = None,
                           include_images: bool = False,
                           include_prompts: bool = True) -> Dict[str, Any]:
    """
    What a metadata sync would cost, before anyone commits to it.

    Counted the way sync_metadata() actually batches, so the number shown in
    the dialog is the number of requests that will be made: models a hundred
    per request, two more per hundred checkpoints to learn trained from merged,
    one gallery page per version, and generation data thirty ids per request
    pooled across a chunk of versions.

    Requests, deliberately, and not minutes. How long those requests take
    depends on the rate limit in force, the round trip to Civitai, and whether
    any of them are retried after a 429 - none of which this knows, and two of
    which differ per machine. A count that is right everywhere is worth more
    than a duration that is only right here.

    The image figures rest on the galleries already cached, which is the only
    guide there is before fetching them. A version whose gallery has never
    been cached is costed at the library's average.

    Args:
        model_paths: Restrict to these files, or None for everything.
        synced_before: Only models last refreshed before this ISO timestamp.
        downloaded_after: Only versions downloaded since this ISO timestamp.
        include_images: Whether galleries would be refetched.
        include_prompts: Whether generation data would be looked up.

    Returns:
        How much is in scope, and how many requests each part would take.
    """
    db = get_models_db()
    versions = db.get_linked_versions(synced_before=synced_before,
                                      downloaded_after=downloaded_after)

    if model_paths is not None:
        wanted = set(model_paths)
        versions = [v for v in versions if v["file_path"] in wanted]

    models = len({v["model_id"] for v in versions})

    metadata_requests = math.ceil(models / 100) if models else 0

    # Checkpoints cost two more requests per hundred, because checkpointType
    # is a filter Civitai accepts but not a field it returns: the answer comes
    # from which of two queries a model appears in. See get_checkpoint_types().
    checkpoint_ids = {v["model_id"] for v in versions if v.get("model_id")} \
        & set(db.checkpoint_model_ids())
    checkpoint_requests = (2 * math.ceil(len(checkpoint_ids) / 100)) if checkpoint_ids else 0
    image_requests = sum(1 for v in versions if v.get("id")) if include_images else 0

    prompt_requests = 0
    images_total = 0
    if include_images and include_prompts:
        counts = db.count_images_by_version()
        average = round(sum(counts.values()) / len(counts)) if counts else 0
        per_version = [counts.get(v["id"]) or average
                       for v in versions if v.get("id")]
        images_total = sum(per_version)
        # Pooled per chunk, exactly as _refresh_galleries does it.
        for start in range(0, len(per_version), SyncService.GALLERY_CHUNK):
            chunk = per_version[start:start + SyncService.GALLERY_CHUNK]
            prompt_requests += math.ceil(sum(chunk) / CivitaiClient.GENERATION_DATA_BATCH)

    total = metadata_requests + checkpoint_requests + image_requests + prompt_requests
    return {
        "versions": len(versions),
        # What "All models" would come to, so the dialog can show it beside
        # that option whichever scope is currently selected.
        "all_versions": len(db.get_linked_versions()),
        "models": models,
        "images": images_total,
        "requests": {
            "metadata": metadata_requests,
            "checkpoints": checkpoint_requests,
            "images": image_requests,
            "prompts": prompt_requests,
            "total": total,
        },
    }


def sync_window_counts(model_paths: Optional[List[str]] = None,
                       basis: str = "synced") -> List[Dict[str, Any]]:
    """
    How many versions each window would select.

    The dialog shows these beside the windows, so "not synced in 7 days" is
    never a guess about what it will do.

    Args:
        model_paths: Restrict to these files, or None for everything.
        basis: "synced" counts models not refreshed within the window;
            "downloaded" counts versions that arrived inside it. The two run
            in opposite directions - one is looking for the neglected, the
            other for the new - which is why they are separate scopes rather
            than one control with a sign.
    """
    db = get_models_db()
    out = []
    for label, days in SYNC_WINDOWS:
        if basis == "downloaded":
            versions = db.get_linked_versions(downloaded_after=window_cutoff(days))
        else:
            versions = db.get_linked_versions(synced_before=window_cutoff(days))
        if model_paths is not None:
            wanted = set(model_paths)
            versions = [v for v in versions if v["file_path"] in wanted]
        out.append({"label": label, "days": days, "versions": len(versions)})
    return out
