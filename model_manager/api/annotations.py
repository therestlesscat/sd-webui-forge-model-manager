"""
Marking up a Civitai search result with what we know locally.

A model listed by Civitai says nothing about whether it is already on this
disk, or whether it costs Buzz. These add that, in place, so the browser can
answer both without a second request.
"""
from typing import Any, Dict, List, Set

from ..civitai import paid_access_info
from ..model_dirs import held_here
from ..nsfw import stamp_levels


def annotate_paid_access(models: List[Dict[str, Any]]):
    """
    Mark which versions Civitai charges Buzz for, in place.

    Adds `paid_access` to each version: None when it is free, otherwise
    {'permanent': bool, 'ends_at': str|None, 'owned': bool|None} - owned
    when the API key's account bought it (civitai/ownership.py). Downloading a paid version
    without buying it fails with 401/403, so the browser needs to say so
    before the user clicks.
    """
    from ..civitai.ownership import mark_owned
    for model in models:
        for version in model.get("modelVersions", []) or []:
            version["paid_access"] = paid_access_info(version)
    # Which of them the key's account bought, asked once for them all.
    mark_owned(v for model in models for v in model.get("modelVersions", []) or [])


def annotate_image_levels(models: List[Dict[str, Any]]):
    """Stamp every showcase image of these models with its level - see nsfw.stamp_levels()."""
    for model in models:
        for version in model.get("modelVersions", []) or []:
            stamp_levels(version.get("images"))


def ownership(db, model_ids, version_ids) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """
    What the library holds of these models and versions, by the one meaning
    of held (model_dirs.held_here, #188): {"models": {id: {"owned", "listed"}},
    "versions": {id: {"owned", "files"}}}. Owned is a held file; listed, any
    row - what the Model Manager lists, so what "Show in MM" can open.
    A version's files are the Civitai ids of its held files (#189).
    """
    models = {i: {"owned": False, "listed": False} for i in model_ids if i}
    versions = {i: {"owned": False, "files": []} for i in version_ids if i}
    for row in db.library_files(list(models), list(versions)):
        held = held_here(row["file_path"])
        model = models.get(row["model_id"])
        if model is not None:
            model["listed"] = True
            model["owned"] = model["owned"] or held
        version = versions.get(row["version_id"])
        if version is not None and held:
            version["owned"] = True
            if row["civitai_file_id"] is not None and row["civitai_file_id"] not in version["files"]:
                version["files"].append(row["civitai_file_id"])
    for version in versions.values():
        version["files"].sort()
    return {"models": models, "versions": versions}


def held_model_ids(db) -> Set[int]:
    """Every Civitai model the library holds a file of: what a draw leaves out (#191)."""
    return {row["model_id"] for row in db.library_files()
            if row["model_id"] is not None and held_here(row["file_path"])}


def annotate_local_ownership(db, models: List[Dict[str, Any]]):
    """
    Mark which of these models, versions and files the library holds, in
    place - and which models it lists, for "Show in MM". See ownership().

    Args:
        db: Models database.
        models: Models from a Civitai search response.
    """
    if not models:
        return
    model_ids = {m.get("id") for m in models if m.get("id")}
    version_ids = {v.get("id") for m in models for v in (m.get("modelVersions") or []) if v.get("id")}
    held = ownership(db, model_ids, version_ids)
    for model in models:
        mine = held["models"].get(model.get("id"), {})
        model["owned_locally"] = bool(mine.get("owned"))
        model["listed_locally"] = bool(mine.get("listed"))
        model["owned_versions"] = []
        for version in (model.get("modelVersions") or []):
            theirs = held["versions"].get(version.get("id"), {})
            version["owned_locally"] = bool(theirs.get("owned"))
            version["owned_files"] = list(theirs.get("files") or [])
            if version["owned_locally"]:
                model["owned_versions"].append(version.get("id"))
