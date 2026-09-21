"""
Marking up a Civitai search result with what we know locally.

A model listed by Civitai says nothing about whether it is already on this
disk, or whether it costs Buzz. These add that, in place, so the browser can
answer both without a second request.
"""
from typing import Any, Dict, List

from ..civitai import paid_access_info


def annotate_paid_access(models: List[Dict[str, Any]]):
    """
    Mark which versions Civitai charges Buzz for, in place.

    Adds `paid_access` to each version: None when it is free, otherwise
    {'permanent': bool, 'ends_at': str|None}. Downloading a paid version
    without buying it fails with 401/403, so the browser needs to say so
    before the user clicks.
    """
    for model in models:
        for version in model.get("modelVersions", []) or []:
            version["paid_access"] = paid_access_info(version)


def annotate_local_ownership(db, models: List[Dict[str, Any]]):
    """
    Mark which of these models and versions already exist locally, in place.

    Args:
        db: Models database.
        models: Models from a Civitai search response.
    """
    if not models:
        return

    model_ids = {m.get("id") for m in models if m.get("id")}
    version_ids = {
        v.get("id")
        for m in models
        for v in (m.get("modelVersions") or [])
        if v.get("id")
    }

    owned_models = set()
    owned_versions = set()

    if model_ids or version_ids:
        with db._cursor() as cursor:
            for column, ids in (("model_id", model_ids), ("id", version_ids)):
                if not ids:
                    continue
                placeholders = ",".join("?" * len(ids))
                cursor.execute(
                    f"SELECT DISTINCT model_id, id FROM model_versions "
                    f"WHERE {column} IN ({placeholders})",
                    list(ids)
                )
                for row in cursor.fetchall():
                    owned_models.add(row["model_id"])
                    owned_versions.add(row["id"])

    for model in models:
        model["owned_locally"] = model.get("id") in owned_models
        model["owned_versions"] = [
            v.get("id") for v in (model.get("modelVersions") or [])
            if v.get("id") in owned_versions
        ]
        for version in (model.get("modelVersions") or []):
            version["owned_locally"] = version.get("id") in owned_versions
