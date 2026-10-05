"""
Reading and writing the .civitai.info beside a model file.

A sync and a download write one, for other tools; a sync reads one only for a
model Civitai no longer has (SyncService._identify_by_sidecar).
"""
import json
import os
from typing import Optional, Dict, Any, Tuple
from .console import say


def get_metadata_paths(model_path: str) -> Tuple[str, str]:
    """
    Get paths for metadata files based on model path.

    Returns:
        Tuple of (civitai_info_path, images_json_path)
    """
    base = os.path.splitext(model_path)[0]
    civitai_path = base + ".civitai.info"
    images_path = base + ".images.json"
    return civitai_path, images_path


def read_civitai_info(model_path: str) -> Optional[Dict[str, Any]]:
    """
    Read .civitai.info file for a model.

    Args:
        model_path: Path to the model file

    Returns:
        Raw JSON data or None if not found
    """
    civitai_path, _ = get_metadata_paths(model_path)

    if not os.path.exists(civitai_path):
        return None

    try:
        with open(civitai_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        say(f"Error reading {civitai_path}: {e}")
        return None


def write_civitai_info(model_path: str, data: Dict[str, Any]) -> bool:
    """
    Write .civitai.info file for a model.

    Args:
        model_path: Path to the model file
        data: Civitai API response data

    Returns:
        True if successful
    """
    civitai_path, _ = get_metadata_paths(model_path)

    try:
        with open(civitai_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except IOError as e:
        say(f"Error writing {civitai_path}: {e}")
        return False


def as_model_payload(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    A sidecar in the model format a sync reads, whichever it was written in.

    This extension writes Civitai's model payload: the model at the root,
    its versions under modelVersions. Other tools write the version payload
    from the by-hash endpoint: the version at the root - so its id is the
    version's - with modelId beside it and the model under "model". Read as
    the model format, that made the version id a model id, the version's
    name the model's, and left no type. It is turned into the model format:
    the embedded model at the root, under its own id, with the version as
    its one entry in modelVersions.
    """
    if not data or "modelVersions" in data:
        return data
    model = data.get("model")
    if not isinstance(model, dict) or not data.get("modelId"):
        return data
    version = {k: v for k, v in data.items() if k != "model"}
    payload = dict(model)
    payload["id"] = data["modelId"]
    payload.setdefault("creator", data.get("creator"))
    payload["modelVersions"] = [version]
    return payload



def read_model_payload(model_path: str) -> Optional[Dict[str, Any]]:
    """A model's .civitai.info, in the model format, whichever tool wrote it."""
    return as_model_payload(read_civitai_info(model_path))


def names_a_version(payload: Optional[Dict[str, Any]]) -> bool:
    """
    Whether a sidecar, in the model format, names a version by its id. One
    that names none - an error another tool wrote, a stub with a model id
    alone - is no identification (#131).
    """
    versions = (payload or {}).get("modelVersions") or []
    return any(isinstance(v, dict) and v.get("id") for v in versions)


def download_payload(model_data: Dict[str, Any], version_data: Dict[str, Any],
                     model_type: str) -> Dict[str, Any]:
    """
    The sidecar a download writes: the model's payload, with this version.
    The sync that follows a download writes Civitai's full answer over it;
    this is what is beside the file if that sync cannot.
    """
    return {
        "id": model_data.get("id"),
        "modelId": model_data.get("id"),
        "name": model_data.get("name"),
        "description": model_data.get("description"),
        "type": model_type,
        "nsfw": model_data.get("nsfw"),
        "nsfwLevel": model_data.get("nsfwLevel"),
        "tags": model_data.get("tags", []),
        "creator": model_data.get("creator"),
        "stats": model_data.get("stats"),
        "modelVersions": [version_data],
    }
