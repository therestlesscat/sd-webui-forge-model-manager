"""
What a Civitai payload says about a model and a version, as database rows.

Written three times before - Scan Disk reading a sidecar, a sync storing
Civitai's model answer, a sync storing its by-hash answer - and the copies
had begun to differ: one made up a type the others did not. These hold the
fields Civitai gives; each caller adds what is its own - the file's path,
size and date, which hashes it trusts, how complete the cover is, and, for a
scan, the showcase's images in the version's level (#104).
"""
from typing import Any, Dict, Optional

from .hashing import read_hashes
from .nsfw import UNKNOWN


def model_row(data: Dict[str, Any]) -> Dict[str, Any]:
    """A row of `models` from a model payload (its id, name, stats, licence...)."""
    stats = data.get("stats") or {}
    creator = data.get("creator") or {}
    thumbs_up = stats.get("thumbsUpCount", 0)
    thumbs_down = stats.get("thumbsDownCount", 0)
    rating = round((thumbs_up / (thumbs_up + thumbs_down)) * 5, 2) if thumbs_up + thumbs_down > 0 else 0
    return {
        "id": data.get("id"),
        "name": data.get("name", ""),
        "description": data.get("description"),
        # Civitai's type, as Civitai gave it - None when it gave none. What
        # the file really is comes from the file itself (file_identity.py).
        "type": data.get("type"),
        "nsfw": data.get("nsfw", False),
        "nsfw_level": data.get("nsfwLevel", UNKNOWN),
        "tags": data.get("tags", []),
        "creator_username": creator.get("username") if creator else None,
        "creator_image_url": creator.get("image") if creator else None,
        "stats_download_count": stats.get("downloadCount", 0),
        "stats_thumbs_up": thumbs_up,
        "stats_thumbs_down": thumbs_down,
        "stats_rating": rating,
        "allow_no_credit": data.get("allowNoCredit"),
        "allow_commercial_use": data.get("allowCommercialUse"),
        "allow_derivatives": data.get("allowDerivatives"),
        "allow_different_license": data.get("allowDifferentLicense"),
        "supports_generation": data.get("supportsGeneration"),
        "versions": data.get("modelVersions"),
    }


def version_row(version: Dict[str, Any], model_id: Optional[int]) -> Dict[str, Any]:
    """A row of `versions`, from a version payload."""
    stats = version.get("stats") or {}
    row = {
        "id": version.get("id"),
        "version_name": version.get("name"),
        "base_model": version.get("baseModel"),
        "published_at": version.get("publishedAt"),
        "created_at": version.get("createdAt"),
        "nsfw_level": version.get("nsfwLevel", UNKNOWN),
        "trained_words": version.get("trainedWords", []),
        "description": version.get("description"),
        "stats_download_count": stats.get("downloadCount", 0),
        "stats_thumbs_up": stats.get("thumbsUpCount", 0),
    }
    if model_id is not None:
        row["model_id"] = model_id
    return row


# What Civitai's list says of one file, as columns of `files` (#133).
FILE_FIELDS = ("civitai_file_id", "civitai_file_type", "fp", "size", "format", "civitai_primary")


def file_row(version: Dict[str, Any], file_name: Optional[str],
             hashes: Any = None) -> Dict[str, Any]:
    """
    One file of a version as Civitai lists it - its id, its type there
    (Model, VAE, Pruned Model...), fp / size / format, whether primary - as
    columns of `files`: the file a hash of one kind names in both (a sync's,
    a download's - sure), else the one of its name, its case aside (a sidecar
    beside a file nobody has hashed). Nothing, for a file the list does not
    name: renamed on disk, or replaced on Civitai since.
    """
    files = [f for f in version.get("files") or [] if isinstance(f, dict)]
    ours = read_hashes(hashes)

    def same_hash(listed: Dict[str, Any]) -> bool:
        theirs = read_hashes(listed.get("hashes"))
        return any(ours.get(kind) == value for kind, value in theirs.items())

    found = next((f for f in files if ours and same_hash(f)), None)
    if found is None and file_name:
        found = next((f for f in files if str(f.get("name") or "").lower() == file_name.lower()), None)
    if found is None:
        return {}
    meta = found.get("metadata") or {}
    return {
        "civitai_file_id": found.get("id"),
        "civitai_file_type": found.get("type"),
        "fp": meta.get("fp"),
        "size": meta.get("size"),
        "format": meta.get("format"),
        "civitai_primary": None if found.get("primary") is None else bool(found.get("primary")),
    }
