"""
Storage module for reading/writing model metadata files.
Handles .civitai.info and .images.json files.
"""
import json
import os
from typing import Optional, Dict, Any, Tuple

from .models import (
    CivitaiModelInfo, ModelVersion, ModelImage
)


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
        print(f"[ModelManager] Error reading {civitai_path}: {e}")
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
        print(f"[ModelManager] Error writing {civitai_path}: {e}")
        return False


def as_model_payload(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    A sidecar in the model format the scan reads, whichever it was written in.

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


def read_images_json(model_path: str) -> Optional[Dict[str, Any]]:
    """
    Read .images.json file for a model.

    Args:
        model_path: Path to the model file

    Returns:
        Images data or None if not found
    """
    _, images_path = get_metadata_paths(model_path)

    if not os.path.exists(images_path):
        return None

    try:
        with open(images_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[ModelManager] Error reading {images_path}: {e}")
        return None


def parse_civitai_info(data: Dict[str, Any], filename: Optional[str] = None) -> Tuple[Optional[CivitaiModelInfo], Optional[ModelVersion]]:
    """
    Parse .civitai.info data into model and version objects.

    The .civitai.info format from existing extensions varies:
    1. Full model response (has 'modelVersions' array)
    2. Version-only response (from by-hash API)
    3. Mixed format

    Args:
        data: Raw civitai.info JSON data
        filename: Optional filename to match version by (e.g., "model_v1.safetensors")

    Returns:
        Tuple of (CivitaiModelInfo, ModelVersion) - either may be None
    """
    if not data:
        return None, None

    # Check if this is a version-only response (from by-hash API)
    if "model" in data and "modelVersions" not in data:
        # This is a version response with embedded model info
        model_data = data.get("model", {})
        model_data["modelVersions"] = []  # Empty, we'll use the version from outer data

        model_info = CivitaiModelInfo.from_civitai(model_data)
        version_info = ModelVersion.from_civitai(data)

        return model_info, version_info

    # Check if this is a full model response
    if "modelVersions" in data:
        model_info = CivitaiModelInfo.from_civitai(data)

        # Find matching version by filename if provided
        version_info = None
        if filename and model_info.versions:
            # Try to match by filename in files array
            for version in model_info.versions:
                # Check if this version has a matching file
                version_data = None
                for v in data.get("modelVersions", []):
                    if v.get("id") == version.id:
                        version_data = v
                        break

                if version_data:
                    for f in version_data.get("files", []):
                        if f.get("name") == filename:
                            version_info = version
                            break
                if version_info:
                    break

        # Fallback to first version if no filename match
        if not version_info and model_info.versions:
            version_info = model_info.versions[0]

        return model_info, version_info

    # Fallback: treat as version-only without model wrapper
    if "id" in data and "name" in data:
        version_info = ModelVersion.from_civitai(data)

        # Create minimal model info
        model_info = CivitaiModelInfo(
            id=data.get("modelId", 0),
            name=data.get("model", {}).get("name", version_info.name),
            type=data.get("model", {}).get("type", "Unknown"),
        )

        return model_info, version_info

    return None, None


def load_model_metadata(model_path: str) -> Tuple[Optional[CivitaiModelInfo], Optional[ModelVersion], list]:
    """
    Load all metadata for a model.

    Args:
        model_path: Path to the model file

    Returns:
        Tuple of (CivitaiModelInfo, ModelVersion, list of ModelImage)
    """
    # Read civitai info
    civitai_data = read_civitai_info(model_path)

    # Get filename for matching the correct version
    filename = os.path.basename(model_path)
    model_info, version_info = parse_civitai_info(civitai_data, filename)

    # Read images (our custom format with full metadata)
    images = []
    images_data = read_images_json(model_path)
    if images_data and "images" in images_data:
        images = [ModelImage.from_dict(img) for img in images_data["images"]]
    elif version_info and version_info.images:
        # Fall back to images from civitai.info
        images = version_info.images

    return model_info, version_info, images
