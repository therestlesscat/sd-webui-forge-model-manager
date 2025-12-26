"""
Model scanner module.
Scans model directories and loads metadata.
"""
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from .models import LocalModel, NSFWLevel, ModelType
from .storage import load_model_metadata


# Model file extensions
MODEL_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".bin", ".pth"}

# Directories to scan (relative to models folder)
MODEL_DIRECTORIES = {
    "Stable-diffusion": ModelType.CHECKPOINT,
    "Lora": ModelType.LORA,
    "LyCORIS": ModelType.LOCON,
    "embeddings": ModelType.TEXTUAL_INVERSION,
    "VAE": ModelType.VAE,
    "ControlNet": ModelType.CONTROLNET,
    "ESRGAN": ModelType.UPSCALER,
    "RealESRGAN": ModelType.UPSCALER,
    "SwinIR": ModelType.UPSCALER,
    "hypernetworks": ModelType.HYPERNETWORK,
}


def get_models_root() -> str:
    """Get the root models directory."""
    try:
        from modules import shared
        return shared.cmd_opts.ckpt_dir or os.path.join(os.getcwd(), "models")
    except Exception:
        return os.path.join(os.getcwd(), "models")


def get_embeddings_dir() -> str:
    """Get the embeddings directory."""
    try:
        from modules import shared
        return shared.cmd_opts.embeddings_dir or os.path.join(os.getcwd(), "embeddings")
    except Exception:
        return os.path.join(os.getcwd(), "embeddings")


def scan_directory(directory: str, default_type: ModelType = ModelType.UNKNOWN) -> List[LocalModel]:
    """
    Scan a directory for model files.

    Args:
        directory: Directory to scan
        default_type: Default model type for this directory

    Returns:
        List of LocalModel objects
    """
    models = []

    if not os.path.exists(directory):
        return models

    for root, dirs, files in os.walk(directory):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext not in MODEL_EXTENSIONS:
                continue

            file_path = os.path.join(root, file)

            try:
                stat = os.stat(file_path)
                file_size = stat.st_size
                file_modified = datetime.fromtimestamp(stat.st_mtime)
                file_created = datetime.fromtimestamp(stat.st_ctime)
            except OSError:
                continue

            # Load metadata
            model_info, version_info, images = load_model_metadata(file_path)

            model = LocalModel(
                file_path=file_path,
                file_name=file,
                file_size=file_size,
                file_modified=file_modified,
                file_created=file_created,
                file_extension=ext,
                civitai_model=model_info,
                civitai_version=version_info,
            )

            models.append(model)

    return models


def scan_models() -> List[LocalModel]:
    """
    Scan all model directories.

    Returns:
        List of all LocalModel objects
    """
    all_models = []
    models_root = get_models_root()

    print(f"[ModelManager] Scanning models in {models_root}")
    civitai_count = 0

    for subdir, default_type in MODEL_DIRECTORIES.items():
        directory = os.path.join(models_root, subdir)
        if os.path.exists(directory):
            models = scan_directory(directory, default_type)
            all_models.extend(models)
            print(f"[ModelManager] Found {len(models)} models in {subdir}")

    # Also scan embeddings directory (often separate)
    embeddings_dir = get_embeddings_dir()
    if os.path.exists(embeddings_dir) and embeddings_dir != os.path.join(models_root, "embeddings"):
        models = scan_directory(embeddings_dir, ModelType.TEXTUAL_INVERSION)
        all_models.extend(models)
        print(f"[ModelManager] Found {len(models)} embeddings in {embeddings_dir}")

    # Count models with civitai data
    civitai_count = sum(1 for m in all_models if m.has_civitai_data)
    print(f"[ModelManager] Total models found: {len(all_models)}, with Civitai data: {civitai_count}")
    return all_models


def filter_models(models: List[LocalModel], filters: Dict[str, Any]) -> List[LocalModel]:
    """
    Filter models based on criteria.

    Args:
        models: List of models to filter
        filters: Dict with filter criteria

    Returns:
        Filtered list
    """
    result = models

    # Search filter (handle None)
    search = (filters.get("search") or "").strip().lower()
    if search:
        result = [
            m for m in result
            if search in m.display_name.lower()
            or search in m.file_name.lower()
            or any(search in tw.lower() for tw in m.trained_words)
            or any(search in tag.lower() for tag in m.tags)
        ]

    # Type filter
    type_filter = filters.get("type")
    if type_filter:
        type_enum = ModelType.from_string(type_filter)
        result = [m for m in result if m.model_type == type_enum]

    # Base model filter
    base_model = filters.get("base_model")
    if base_model:
        base_lower = base_model.lower().replace(" ", "").replace(".", "")
        result = [
            m for m in result
            if base_lower in m.base_model.lower().replace(" ", "").replace(".", "")
        ]

    # NSFW filter - either max level OR specific levels
    nsfw_max = filters.get("nsfw_max")
    nsfw_levels = filters.get("nsfw_levels")

    # Debug: show distribution of NSFW levels
    level_counts = {}
    for m in result:
        lvl = m.nsfw_level.value
        level_counts[lvl] = level_counts.get(lvl, 0) + 1
    print(f"[ModelManager] NSFW level distribution: {level_counts}")

    if nsfw_max:
        # Max level mode: show all levels up to and including max
        max_level = NSFWLevel.from_string(nsfw_max)
        result = [m for m in result if m.nsfw_level <= max_level]
    elif nsfw_levels:
        # Specific levels mode: only show selected levels
        allowed_levels = {NSFWLevel.from_string(l) for l in nsfw_levels}
        before_count = len(result)
        result = [m for m in result if m.nsfw_level in allowed_levels]
        print(f"[ModelManager] NSFW filter: levels={nsfw_levels}, allowed={allowed_levels}, before={before_count}, after={len(result)}")

    # Has Civitai data filter
    has_civitai = filters.get("has_civitai")
    if has_civitai is not None:
        result = [m for m in result if m.has_civitai_data == has_civitai]

    # Folder filter
    folder = filters.get("folder")
    if folder:
        result = [m for m in result if folder.lower() in m.file_path.lower()]

    # Tags filter (multi-select)
    tags = filters.get("tags", [])
    if tags:
        result = [
            m for m in result
            if any(tag.lower() in [t.lower() for t in m.tags] for tag in tags)
        ]

    return result


def sort_models(models: List[LocalModel], sort_config: Dict[str, str]) -> List[LocalModel]:
    """
    Sort models.

    Args:
        models: List of models to sort
        sort_config: Dict with 'field' and 'order'

    Returns:
        Sorted list
    """
    field = sort_config.get("field", "name")
    order = sort_config.get("order", "asc")
    reverse = order == "desc"

    def get_sort_key(model: LocalModel):
        if field == "name":
            return model.display_name.lower()
        elif field == "file_size":
            return model.file_size
        elif field == "file_modified":
            return model.file_modified or datetime.min
        elif field == "published_at":
            return model.published_at or datetime.min
        elif field == "rating":
            return model.rating
        elif field == "download_count":
            return model.download_count
        else:
            return model.display_name.lower()

    return sorted(models, key=get_sort_key, reverse=reverse)


def group_by_civitai_model(models: List[LocalModel]) -> Dict[Optional[int], List[LocalModel]]:
    """
    Group models by Civitai model ID for duplicate detection.

    Args:
        models: List of models

    Returns:
        Dict mapping model ID to list of LocalModel (None key for no Civitai data)
    """
    groups: Dict[Optional[int], List[LocalModel]] = {}

    for model in models:
        model_id = model.civitai_model_id
        if model_id not in groups:
            groups[model_id] = []
        groups[model_id].append(model)

    return groups


def find_duplicates(models: List[LocalModel]) -> List[List[LocalModel]]:
    """
    Find models that are duplicates (same Civitai model ID).

    Returns:
        List of groups where each group has 2+ models
    """
    groups = group_by_civitai_model(models)

    duplicates = []
    for model_id, group in groups.items():
        if model_id is not None and len(group) > 1:
            duplicates.append(group)

    return duplicates
