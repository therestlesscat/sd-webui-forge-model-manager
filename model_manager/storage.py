"""
Storage module for reading/writing model metadata files.
Handles .civitai.info and .images.json files.
"""
import json
import os
from typing import Optional, Dict, Any, Tuple

from .models import (
    CivitaiModelInfo, ModelVersion, ModelImage, LocalModel
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


# Fields that only come from the full model endpoint (/models/{id})
# These are missing when data comes from by-hash endpoint only
FULL_MODEL_REQUIRED_FIELDS = ["description", "tags", "stats"]


def is_partial_civitai_data(data: Dict[str, Any]) -> bool:
    """
    Check if civitai data is partial (missing full model info).

    By-hash endpoint returns version data with limited embedded model info.
    Full model endpoint returns description, tags, stats that are missing
    from by-hash response.

    Args:
        data: Civitai data from .civitai.info file

    Returns:
        True if data is missing fields that require full model fetch
    """
    if not data:
        return True

    # Check if this is version-only response (has "model" key but no "modelVersions")
    # This format comes from by-hash endpoint
    if "model" in data and "modelVersions" not in data:
        # Check if embedded model has full data
        model_data = data.get("model", {})
        # By-hash response's embedded model never has description
        if not model_data.get("description"):
            return True
        if not model_data.get("tags"):
            return True
        if not model_data.get("stats"):
            return True
        return False

    # Full model response format - check directly
    if "modelVersions" in data:
        # This is full model response, should have everything
        if not data.get("description"):
            return True
        # tags and stats might be empty but should exist
        return False

    # Unknown format - assume partial
    return True


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


def write_images_json(model_path: str, images_data) -> bool:
    """
    Write .images.json file for a model.

    Args:
        model_path: Path to the model file
        images_data: Dict with 'images', 'total_count', etc. OR list of images

    Returns:
        True if successful
    """
    _, images_path = get_metadata_paths(model_path)

    try:
        # Handle both dict format (new) and list format (legacy)
        if isinstance(images_data, dict):
            # New format with total_count, next_cursor, etc.
            data = images_data
            # Ensure images are dicts
            if "images" in data:
                image_list = []
                for img in data["images"]:
                    if isinstance(img, ModelImage):
                        image_list.append(img.to_dict())
                    elif isinstance(img, dict):
                        image_list.append(img)
                data["images"] = image_list
        else:
            # Legacy list format
            image_list = []
            for img in images_data:
                if isinstance(img, ModelImage):
                    image_list.append(img.to_dict())
                elif isinstance(img, dict):
                    image_list.append(img)
            data = {"images": image_list}

        with open(images_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except IOError as e:
        print(f"[ModelManager] Error writing {images_path}: {e}")
        return False


_debug_nsfw_logged = False

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
    global _debug_nsfw_logged
    if not data:
        return None, None

    # Debug: log first civitai data to see nsfw field format
    if not _debug_nsfw_logged:
        nsfw_val = data.get("nsfw", data.get("nsfwLevel", "NOT_FOUND"))
        print(f"[ModelManager] DEBUG first civitai data nsfw field: {nsfw_val}, type: {type(nsfw_val)}")
        print(f"[ModelManager] DEBUG keys in data: {list(data.keys())[:10]}")
        _debug_nsfw_logged = True

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


def save_model_metadata(
    model_path: str,
    civitai_response: Dict[str, Any],
    save_images_separately: bool = True
) -> bool:
    """
    Save metadata for a model from Civitai API response.

    Args:
        model_path: Path to the model file
        civitai_response: Raw Civitai API response
        save_images_separately: If True, also save .images.json

    Returns:
        True if successful
    """
    # Save civitai.info
    if not write_civitai_info(model_path, civitai_response):
        return False

    # Optionally save images separately with full metadata
    if save_images_separately:
        images = civitai_response.get("images", [])
        if images:
            write_images_json(model_path, images)

    return True
