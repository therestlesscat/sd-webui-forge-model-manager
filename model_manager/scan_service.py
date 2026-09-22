"""
Scan service for populating the models database.

Scans model directories, reads metadata files, and stores
computed metadata in SQLite for fast querying.
"""
import os
import json
import threading
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from .db import get_models_db
from .nsfw import UNKNOWN, level_name, max_image_level, model_level
from .storage import read_civitai_info


# NSFW level bitmask values (from Civitai API)
# NSFW severity order for comparison (higher index = more severe)
NSFW_SEVERITY = ["PG", "PG-13", "R", "X", "XXX", "Unknown"]


# Command-line options that point at model directories, per model type.
#
# Forge uses singular options holding one path (--ckpt-dir). Forge Neo renamed
# them to repeatable plural options holding a list (--ckpt-dirs), and added
# --text-encoder-dirs. Both names are checked so the extension works on either.
MODEL_DIR_OPTIONS = {
    "Checkpoint": ("ckpt_dir", "ckpt_dirs"),
    "LORA": ("lora_dir", "lora_dirs"),
    "VAE": ("vae_dir", "vae_dirs", "text_encoder_dirs"),
    "Hypernetwork": ("hypernetwork_dir",),
    "Controlnet": ("controlnet_dir",),
}


def collect_cmd_dirs(cmd_opts, *option_names) -> List[str]:
    """
    Read directory paths from command-line options.

    Handles both a single path (Forge) and a list of paths (Neo), and skips
    options the running WebUI does not define.

    Args:
        cmd_opts: The WebUI's parsed command-line options.
        option_names: Attribute names to read, in priority order.

    Returns:
        List of directory paths (may be empty; not checked for existence).
    """
    found = []

    for name in option_names:
        value = getattr(cmd_opts, name, None)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            found.extend(str(v) for v in value if v)
        else:
            found.append(str(value))

    return found


@dataclass
class ScanProgress:
    """Progress tracking for scan operation."""
    total: int = 0
    processed: int = 0
    current_file: str = ""
    is_complete: bool = False
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "processed": self.processed,
            "current_file": self.current_file,
            "is_complete": self.is_complete,
            "error_count": len(self.errors),
        }


class ScanService:
    """
    Service for scanning models and populating the database.
    """

    # Model file extensions
    MODEL_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}

    def __init__(self):
        self._cancel_requested = False
        self._progress = ScanProgress()
        self._progress_lock = threading.Lock()

    def find_model_files(self, directories: List[str]) -> List[str]:
        """Find all model files in the given directories."""
        model_files = []

        for directory in directories:
            if not os.path.isdir(directory):
                continue

            for root, _, files in os.walk(directory):
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in self.MODEL_EXTENSIONS:
                        model_files.append(os.path.join(root, file))

        return model_files

    def extract_metadata(self, model_path: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """
        Extract all metadata for a model file.

        Returns:
            Tuple of (civitai_model_data or None, version_data)
        """
        file_name = os.path.basename(model_path)
        file_ext = os.path.splitext(model_path)[1].lower()

        # Version data (always present)
        version_data = {
            "file_path": model_path,
            "file_name": file_name,
            "file_extension": file_ext,
            "has_civitai_data": False,
            "nsfw_level": 1,  # Default to PG
        }

        # File stats
        try:
            stat = os.stat(model_path)
            version_data["file_size"] = stat.st_size
            version_data["file_modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        except OSError:
            version_data["file_size"] = 0
            version_data["file_modified"] = None

        # Read .civitai.info
        civitai_data = read_civitai_info(model_path)
        civitai_model = None

        if civitai_data:
            version_data["has_civitai_data"] = True
            civitai_model = self._extract_civitai_metadata(civitai_data, version_data, model_path)
        else:
            # Infer model type from path when no civitai data
            version_data["base_model"] = None

        return civitai_model, version_data

    def _infer_model_type(self, path: str) -> str:
        """Infer model type from directory path."""
        path_lower = path.lower()
        if "lora" in path_lower:
            return "LORA"
        elif "embedding" in path_lower or "textual" in path_lower:
            return "TextualInversion"
        elif "vae" in path_lower:
            return "VAE"
        elif "controlnet" in path_lower:
            return "Controlnet"
        elif "upscal" in path_lower:
            return "Upscaler"
        elif "checkpoint" in path_lower or "stable-diffusion" in path_lower:
            return "Checkpoint"
        return "Unknown"

    def _extract_civitai_metadata(
        self,
        data: Dict,
        version_data: Dict,
        model_path: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract metadata from civitai.info data.

        Returns civitai_model dict if model-level data is available.
        Updates version_data with version-level fields.
        """
        civitai_model = None

        # The civitai.info has the full model response format
        # Root level = model data, modelVersions[0] = the version we downloaded
        model_id = data.get("id")

        if model_id:
            # Extract model-level data
            stats = data.get("stats", {})
            creator = data.get("creator", {})

            # Calculate rating from thumbs
            thumbs_up = stats.get("thumbsUpCount", 0)
            thumbs_down = stats.get("thumbsDownCount", 0)
            rating = 0
            if thumbs_up + thumbs_down > 0:
                rating = round((thumbs_up / (thumbs_up + thumbs_down)) * 5, 2)

            civitai_model = {
                "id": model_id,
                "name": data.get("name", ""),
                "description": data.get("description"),
                "type": data.get("type", self._infer_model_type(model_path)),
                "nsfw": data.get("nsfw", False),
                "nsfw_level": data.get("nsfwLevel", UNKNOWN),
                "tags": data.get("tags", []),
                "creator_username": creator.get("username") if creator else None,
                "creator_image_url": creator.get("image") if creator else None,
                "stats_download_count": stats.get("downloadCount", 0),
                "stats_thumbs_up": stats.get("thumbsUpCount", 0),
                "stats_thumbs_down": stats.get("thumbsDownCount", 0),
                "stats_rating": rating,
                "allow_no_credit": data.get("allowNoCredit"),
                "allow_commercial_use": data.get("allowCommercialUse"),
                "allow_derivatives": data.get("allowDerivatives"),
                "allow_different_license": data.get("allowDifferentLicense"),
                "supports_generation": data.get("supportsGeneration"),
            }

            version_data["model_id"] = model_id

        # Find the matching version in modelVersions
        versions = data.get("modelVersions", [])
        matched_version = None

        if versions:
            # First version is typically the one we downloaded (sync reorders it)
            # But also try to match by filename
            file_name = version_data["file_name"]

            for v in versions:
                files = v.get("files", [])
                for f in files:
                    if f.get("name") == file_name:
                        matched_version = v
                        break
                if matched_version:
                    break

            # Fallback to first version
            if not matched_version and versions:
                matched_version = versions[0]

        if matched_version:
            version_stats = matched_version.get("stats", {})

            version_data["id"] = matched_version.get("id")
            version_data["version_name"] = matched_version.get("name")
            version_data["base_model"] = matched_version.get("baseModel")
            version_data["published_at"] = matched_version.get("publishedAt")
            version_data["created_at"] = matched_version.get("createdAt")
            version_data["nsfw_level"] = matched_version.get("nsfwLevel", UNKNOWN)
            version_data["trained_words"] = matched_version.get("trainedWords", [])
            version_data["description"] = matched_version.get("description")
            version_data["stats_download_count"] = version_stats.get("downloadCount", 0)
            version_data["stats_thumbs_up"] = version_stats.get("thumbsUpCount", 0)

            # Get file hashes if available (from Civitai data)
            files = matched_version.get("files", [])
            for f in files:
                if f.get("name") == version_data["file_name"]:
                    civitai_hashes = f.get("hashes", {})
                    if civitai_hashes:
                        # Convert to our lowercase format
                        version_data["file_hashes"] = {
                            k.lower(): v for k, v in civitai_hashes.items()
                        }
                    break

        # Calculate effective NSFW level considering images
        self._calculate_nsfw_level(data, version_data)

        return civitai_model

    def _calculate_nsfw_level(self, civitai_data: Dict, version_data: Dict):
        """
        Settle a version's NSFW level from everything we know about it.

        Its own rating, plus the worst picture in its gallery - preferring the
        images already stored, and falling back to the ones the payload came
        with. See model_manager.nsfw for how a single image is judged.
        """
        images = []
        version_id = version_data.get("id")
        if version_id:
            try:
                from .db import get_models_db
                images = get_models_db().get_all_images_for_version(version_id)
            except Exception:
                pass

        if not images:
            versions = civitai_data.get("modelVersions", [])
            if versions:
                images = versions[0].get("images", []) or []

        version_data["nsfw_level"] = model_level(
            None,
            version_data.get("nsfw_level"),
            max_image_level(images) if images else None,
        )

    def scan_models(
        self,
        directories: Optional[List[str]] = None,
        max_workers: int = 4,
        callback: Optional[Callable[[ScanProgress], None]] = None
    ) -> ScanProgress:
        """
        Scan model directories and populate the database.

        Args:
            directories: List of directories to scan. If None, uses WebUI model dirs.
            max_workers: Number of parallel workers.
            callback: Called with progress updates.

        Returns:
            Final ScanProgress.
        """
        self._cancel_requested = False

        # Get model directories if not specified
        if directories is None:
            directories = self._get_model_directories()

        # Find all model files
        print(f"[ModelManager] Scanning directories: {directories}")
        model_files = self.find_model_files(directories)

        self._progress = ScanProgress(total=len(model_files))
        print(f"[ModelManager] Found {len(model_files)} model files")

        if not model_files:
            self._progress.is_complete = True
            return self._progress

        # Get database
        db = get_models_db()

        # Track which files we've seen (to remove deleted ones)
        seen_paths = set()

        def process_model(path: str) -> Optional[Tuple[Optional[Dict], Dict]]:
            if self._cancel_requested:
                return None
            try:
                return self.extract_metadata(path)
            except Exception as e:
                with self._progress_lock:
                    self._progress.errors.append(f"{os.path.basename(path)}: {e}")
                return None

        # Process models in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_model, path): path for path in model_files}

            for future in as_completed(futures):
                if self._cancel_requested:
                    break

                path = futures[future]
                result = future.result()

                with self._progress_lock:
                    self._progress.processed += 1
                    self._progress.current_file = os.path.basename(path)

                if result:
                    civitai_model, version_data = result
                    seen_paths.add(path)

                    # Insert/update civitai model if we have one
                    if civitai_model:
                        db.upsert_civitai_model(civitai_model)

                    # Insert/update version
                    db.upsert_version(version_data)

                if callback:
                    callback(self._progress)

        # Remove models that no longer exist
        existing_paths = set(db.get_all_version_paths())
        removed_paths = existing_paths - seen_paths
        for path in removed_paths:
            db.delete_version(path)

        if removed_paths:
            print(f"[ModelManager] Removed {len(removed_paths)} deleted models from database")

        # Update scan timestamp
        db.set_metadata("last_scan", datetime.now().isoformat())

        self._progress.current_file = ""
        self._progress.is_complete = True

        stats = db.get_stats()
        print(f"[ModelManager] Scan complete: {stats['total_versions']} versions "
              f"({stats['with_civitai_data']} with Civitai data, "
              f"{stats['total_civitai_models']} unique models)")

        return self._progress

    def _get_model_directories(self) -> List[str]:
        """Get model directories from WebUI settings."""
        directories = []

        try:
            from modules import shared

            if hasattr(shared, 'cmd_opts'):
                cmd = shared.cmd_opts
                for names in MODEL_DIR_OPTIONS.values():
                    directories.extend(collect_cmd_dirs(cmd, *names))

            # Default paths
            if hasattr(shared, 'models_path'):
                models_path = shared.models_path
                directories.extend([
                    os.path.join(models_path, "Stable-diffusion"),
                    os.path.join(models_path, "Lora"),
                    os.path.join(models_path, "VAE"),
                ])

        except ImportError:
            pass

        # Drop duplicates (case-insensitively on Windows) and missing dirs
        seen = set()
        result = []
        for directory in directories:
            if not directory:
                continue
            path = os.path.abspath(str(directory))
            key = os.path.normcase(path)
            if key in seen or not os.path.isdir(path):
                continue
            seen.add(key)
            result.append(path)

        return result

    def cancel(self):
        """Cancel the scan operation."""
        self._cancel_requested = True

    @property
    def progress(self) -> ScanProgress:
        """Get current scan progress."""
        return self._progress
