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
from typing import Optional, List, Dict, Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models_db import get_models_db
from .storage import read_civitai_info


# NSFW level bitmask values (from Civitai API)
NSFW_BITS = {
    1: "PG",
    2: "PG-13",
    4: "R",
    8: "X",
    16: "XXX",
    32: "Blocked",
}

# NSFW severity order for comparison
NSFW_SEVERITY = ["PG", "PG-13", "R", "X", "XXX", "Unknown"]


def get_nsfw_from_bitmask(value: int) -> str:
    """Convert bitmask to highest NSFW level string."""
    if not value or not isinstance(value, int):
        return "Unknown"

    # Find highest set bit
    for bit in [32, 16, 8, 4, 2, 1]:
        if value & bit:
            return NSFW_BITS.get(bit, "Unknown")
    return "Unknown"


def get_nsfw_from_value(value) -> str:
    """Convert various NSFW value formats to level string."""
    if value is None:
        return "Unknown"

    # Integer bitmask
    if isinstance(value, int):
        return get_nsfw_from_bitmask(value)

    # Boolean
    if isinstance(value, bool):
        return "R" if value else "PG-13"

    # String
    if isinstance(value, str):
        normalized = value.upper().replace("-", "").replace(" ", "")
        mapping = {
            "PG": "PG",
            "PG13": "PG-13",
            "R": "R",
            "X": "X",
            "XXX": "XXX",
            "NONE": "Unknown",
            "FALSE": "PG-13",
            "TRUE": "R",
        }
        return mapping.get(normalized, "Unknown")

    return "Unknown"


def compare_nsfw(level1: str, level2: str) -> int:
    """Compare two NSFW levels. Returns >0 if level1 > level2."""
    try:
        idx1 = NSFW_SEVERITY.index(level1) if level1 in NSFW_SEVERITY else 5
        idx2 = NSFW_SEVERITY.index(level2) if level2 in NSFW_SEVERITY else 5
        return idx1 - idx2
    except ValueError:
        return 0


def max_nsfw(levels: List[str]) -> str:
    """Get the maximum NSFW level from a list."""
    if not levels:
        return "Unknown"

    result = levels[0]
    for level in levels[1:]:
        if compare_nsfw(level, result) > 0:
            result = level
    return result


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

    def extract_metadata(self, model_path: str) -> Dict[str, Any]:
        """
        Extract all metadata for a model file.

        Reads the model file stats, .civitai.info, .images.json,
        and checks for preview files.
        """
        result = {
            "file_path": model_path,
            "file_name": os.path.basename(model_path),
            "file_extension": os.path.splitext(model_path)[1].lower(),
        }

        # File stats
        try:
            stat = os.stat(model_path)
            result["file_size"] = stat.st_size
            result["file_modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        except OSError:
            result["file_size"] = 0
            result["file_modified"] = None

        # Default display name from filename
        result["display_name"] = os.path.splitext(result["file_name"])[0]

        # Infer model type from path
        result["model_type"] = self._infer_model_type(model_path)

        # Read .civitai.info
        civitai_data = read_civitai_info(model_path)
        if civitai_data:
            result["has_civitai_data"] = True
            self._extract_civitai_metadata(civitai_data, result)
        else:
            result["has_civitai_data"] = False
            result["nsfw_level"] = "Unknown"

        # Calculate NSFW level from images
        if result["has_civitai_data"]:
            self._calculate_nsfw_level(model_path, civitai_data, result)

        # Check for preview files
        self._find_preview(model_path, result)

        return result

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

    def _extract_civitai_metadata(self, data: Dict, result: Dict):
        """Extract metadata from civitai.info data."""
        # Check if this is a version response (from by-hash API)
        model_data = data.get("model", {})

        if model_data:
            # Version response format
            result["display_name"] = model_data.get("name", result["display_name"])
            result["model_type"] = model_data.get("type", result["model_type"])
            result["civitai_model_id"] = data.get("modelId")
            result["civitai_version_id"] = data.get("id")
            result["base_model"] = data.get("baseModel", "")
            result["trained_words"] = data.get("trainedWords", [])

            # Version-level NSFW (integer bitmask at root of version response)
            version_nsfw_level = data.get("nsfwLevel")
            if version_nsfw_level is not None:
                result["_version_nsfw"] = get_nsfw_from_bitmask(version_nsfw_level)

            # Model-level NSFW (boolean) - fallback
            model_nsfw = model_data.get("nsfw", False)
            result["_model_nsfw"] = "R" if model_nsfw else "PG-13"
        else:
            # Full model response format
            result["display_name"] = data.get("name", result["display_name"])
            result["model_type"] = data.get("type", result["model_type"])
            result["civitai_model_id"] = data.get("id")
            result["tags"] = data.get("tags", [])

            # Model-level NSFW (boolean) - fallback
            model_nsfw = data.get("nsfw", False)
            result["_model_nsfw"] = "R" if model_nsfw else "PG-13"

            # Stats
            stats = data.get("stats", {})
            result["rating"] = stats.get("rating", 0)
            result["download_count"] = stats.get("downloadCount", 0)

            # Creator
            creator = data.get("creator", {})
            result["creator"] = creator.get("username") if creator else None

            # First version
            versions = data.get("modelVersions", [])
            if versions:
                version = versions[0]
                result["civitai_version_id"] = version.get("id")
                result["base_model"] = version.get("baseModel", "")
                result["trained_words"] = version.get("trainedWords", [])

                # Version-level NSFW (integer bitmask)
                version_nsfw_level = version.get("nsfwLevel")
                if version_nsfw_level is not None:
                    result["_version_nsfw"] = get_nsfw_from_bitmask(version_nsfw_level)

                published = version.get("publishedAt")
                if published:
                    result["published_at"] = published

        # Also check stats at version level
        stats = data.get("stats", {})
        if stats:
            if "thumbsUpCount" in stats and "rating" not in result:
                # Approximate rating from thumbs
                result["rating"] = min(5.0, stats.get("thumbsUpCount", 0) / 100)
            if "downloadCount" in stats and not result.get("download_count"):
                result["download_count"] = stats.get("downloadCount", 0)

    def _calculate_nsfw_level(self, model_path: str, civitai_data: Dict, result: Dict):
        """Calculate the effective NSFW level from all sources."""
        levels = []

        # Version-level NSFW (most authoritative)
        version_nsfw = result.get("_version_nsfw", "Unknown")
        if version_nsfw != "Unknown":
            levels.append(version_nsfw)

        # Model-level NSFW (boolean fallback)
        model_nsfw = result.get("_model_nsfw", "Unknown")
        if model_nsfw != "Unknown":
            levels.append(model_nsfw)

        # Get images from SQLite cache if we have a version ID
        images = []
        version_id = result.get("civitai_version_id")
        if version_id:
            try:
                from .images_cache import get_images_cache
                cache = get_images_cache()
                images = cache.get_all_images_for_version(version_id)
            except Exception:
                pass

        # Fall back to images in civitai_data if no cached images
        if not images and "images" in civitai_data:
            images = civitai_data["images"]

        # Extract NSFW from images using browsingLevel (preferred) or nsfwLevel
        for img in images:
            # Prefer browsingLevel (integer)
            browsing_level = img.get("browsingLevel")
            if browsing_level is not None:
                level = get_nsfw_from_bitmask(browsing_level)
                if level != "Unknown":
                    levels.append(level)
                continue

            # Fall back to nsfwLevel
            nsfw_val = img.get("nsfwLevel", img.get("nsfw"))
            level = get_nsfw_from_value(nsfw_val)
            if level != "Unknown":
                levels.append(level)

        # Get max level, filtering out Unknown
        real_levels = [l for l in levels if l != "Unknown"]
        if real_levels:
            result["nsfw_level"] = max_nsfw(real_levels)
        else:
            result["nsfw_level"] = "Unknown"

        # Clean up temp fields
        result.pop("_model_nsfw", None)
        result.pop("_version_nsfw", None)

    def _find_preview(self, model_path: str, result: Dict):
        """Find preview image for the model."""
        base = os.path.splitext(model_path)[0]
        preview_extensions = [".preview.png", ".preview.jpg", ".preview.jpeg", ".png", ".jpg"]

        for ext in preview_extensions:
            preview_path = base + ext
            if os.path.exists(preview_path):
                result["preview_path"] = preview_path
                return

        # No local preview - check for Civitai image URL
        if result.get("has_civitai_data"):
            civitai_data = read_civitai_info(model_path)
            if civitai_data:
                images = civitai_data.get("images", [])
                if images and images[0].get("url"):
                    result["preview_url"] = images[0]["url"]

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

        def process_model(path: str) -> Optional[Dict]:
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
                    seen_paths.add(path)
                    db.upsert_model(result)

                if callback:
                    callback(self._progress)

        # Remove models that no longer exist
        existing_paths = set(db.get_all_model_paths())
        removed_paths = existing_paths - seen_paths
        for path in removed_paths:
            db.delete_model(path)

        if removed_paths:
            print(f"[ModelManager] Removed {len(removed_paths)} deleted models from database")

        # Update scan timestamp
        db.set_metadata("last_scan", datetime.now().isoformat())

        self._progress.current_file = ""
        self._progress.is_complete = True

        stats = db.get_stats()
        print(f"[ModelManager] Scan complete: {stats['total_models']} models "
              f"({stats['with_civitai_data']} with Civitai data)")

        return self._progress

    def _get_model_directories(self) -> List[str]:
        """Get model directories from WebUI settings."""
        directories = []

        try:
            from modules import shared
            # Get model paths from WebUI
            if hasattr(shared, 'cmd_opts'):
                cmd = shared.cmd_opts
                if hasattr(cmd, 'ckpt_dir') and cmd.ckpt_dir:
                    directories.append(cmd.ckpt_dir)
                if hasattr(cmd, 'lora_dir') and cmd.lora_dir:
                    directories.append(cmd.lora_dir)

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

        # Filter to existing directories
        return [d for d in directories if d and os.path.isdir(d)]

    def cancel(self):
        """Cancel the scan operation."""
        self._cancel_requested = True

    @property
    def progress(self) -> ScanProgress:
        """Get current scan progress."""
        return self._progress
