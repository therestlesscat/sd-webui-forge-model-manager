"""
Sync service for fetching model data from Civitai.
"""
import os
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Callable

from .civitai_api import CivitaiClient, CivitaiAPIError, CivitaiNotFoundError
from .storage import read_civitai_info, write_civitai_info
from .images_cache import get_images_cache


@dataclass
class SyncResult:
    """Result of syncing a single model."""
    success: bool = False
    skipped: bool = False
    not_found: bool = False
    error: Optional[str] = None
    model_id: Optional[int] = None
    version_id: Optional[int] = None
    image_count: int = 0


@dataclass
class SyncProgress:
    """Progress tracking for sync operation."""
    total: int = 0
    processed: int = 0
    synced: int = 0
    skipped: int = 0
    errors: int = 0
    not_found: int = 0
    current_model: str = ""
    error_messages: List[str] = field(default_factory=list)
    is_complete: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class SyncService:
    """
    Service for syncing local models with Civitai.

    Fetches model metadata, descriptions, and images from Civitai API
    and saves them to .civitai.info and .images.json files.
    """

    def __init__(self, client: Optional[CivitaiClient] = None):
        """
        Initialize the sync service.

        Args:
            client: CivitaiClient instance. If None, creates from settings.
        """
        self.client = client or CivitaiClient.from_settings()
        self._cancel_requested = False
        self._progress = SyncProgress()

    def calculate_hash(self, file_path: str) -> Optional[str]:
        """
        Calculate SHA256 hash for a model file.

        Uses WebUI's hash cache if available for performance.

        Args:
            file_path: Path to the model file.

        Returns:
            SHA256 hash string (uppercase), or None on error.
        """
        try:
            # Try using WebUI's hash module (has caching)
            try:
                from modules import hashes
                title = os.path.basename(file_path)

                # Check cache first
                cached = hashes.sha256_from_cache(file_path, title)
                if cached:
                    return cached.upper()

                # Calculate and cache
                result = hashes.sha256(file_path, title)
                if result:
                    return result.upper()
            except ImportError:
                pass

            # Fallback: calculate directly
            print(f"[ModelManager] Calculating hash for {os.path.basename(file_path)}...")
            sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                # Read in 64KB chunks
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256.update(chunk)

            return sha256.hexdigest().upper()

        except Exception as e:
            print(f"[ModelManager] Error calculating hash: {e}")
            return None

    def sync_model(self, model_path: str, force: bool = False) -> SyncResult:
        """
        Sync a single model with Civitai.

        Steps:
        1. Check if .civitai.info exists (skip if not force)
        2. Calculate SHA256 hash
        3. Call by-hash endpoint to get version info
        4. Fetch all images for the version
        5. Save to .civitai.info and .images.json

        Args:
            model_path: Path to the model file.
            force: Re-sync even if civitai data exists.

        Returns:
            SyncResult with status and details.
        """
        result = SyncResult()
        model_name = os.path.basename(model_path)

        # Check if already has civitai data
        if not force:
            existing_data = read_civitai_info(model_path)
            if existing_data:
                print(f"[ModelManager] Skipping {model_name} (already has civitai data, use Shift+click to force)")
                result.skipped = True
                return result

        print(f"[ModelManager] Processing {model_name}...")

        # Calculate file hash
        file_hash = self.calculate_hash(model_path)
        if not file_hash:
            result.error = "Failed to calculate hash"
            return result

        try:
            # Get version info by hash
            version_data = self.client.get_model_by_hash(file_hash)

            if not version_data:
                result.not_found = True
                return result

            version_id = version_data.get("id")
            model_id = version_data.get("modelId")

            result.version_id = version_id
            result.model_id = model_id

            # Save civitai.info (raw by-hash response, don't modify)
            if not write_civitai_info(model_path, version_data):
                result.error = "Failed to write civitai.info"
                return result

            # Fetch first page of images (max 200) and store in DB
            if version_id:
                print(f"[ModelManager] Fetching images for {model_name}...")
                images_result = self.client.get_model_images(version_id, limit=200, page=1)
                images = images_result.get("images", [])
                total_count = images_result.get("total_count", len(images))
                total_pages = images_result.get("total_pages", 1)
                result.image_count = len(images)

                # Store images in SQLite cache
                if images:
                    cache = get_images_cache()
                    # Clear any existing images for this version
                    cache.clear_version(version_id)
                    # Store page 1 images
                    cache.store_images(version_id, page=1, images=images)
                    # Store pagination state
                    cache.update_pagination_state(
                        version_id=version_id,
                        total_count=total_count,
                        total_pages=total_pages,
                        fetched_pages=1
                    )

            result.success = True
            print(f"[ModelManager] Synced {model_name}: {result.image_count} of {total_count} images")

            return result

        except CivitaiNotFoundError:
            result.not_found = True
            return result

        except CivitaiAPIError as e:
            result.error = str(e)
            return result

        except Exception as e:
            result.error = f"Unexpected error: {e}"
            return result

    def sync_all(
        self,
        model_paths: Optional[List[str]] = None,
        force: bool = False,
        callback: Optional[Callable[[SyncProgress], None]] = None,
        max_workers: int = 4
    ) -> SyncProgress:
        """
        Sync multiple models with Civitai using multiple threads.

        Args:
            model_paths: Specific paths to sync, or None for all models.
            force: Re-sync even if civitai data exists.
            callback: Called after each model with progress update.
            max_workers: Number of parallel threads (default 4).

        Returns:
            Final SyncProgress with summary.
        """
        self._cancel_requested = False
        self._progress_lock = threading.Lock()

        # Get all models if not specified
        if model_paths is None:
            from .scanner import scan_models
            models = scan_models()
            model_paths = [m.file_path for m in models]

        self._progress = SyncProgress(total=len(model_paths))

        print(f"[ModelManager] Starting sync with {max_workers} threads for {len(model_paths)} models")

        def process_model(path: str) -> tuple:
            """Process a single model and return (path, result)."""
            if self._cancel_requested:
                return path, None
            return path, self.sync_model(path, force=force)

        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            futures = {executor.submit(process_model, path): path for path in model_paths}

            # Process results as they complete
            for future in as_completed(futures):
                if self._cancel_requested:
                    print("[ModelManager] Sync cancelled by user")
                    break

                path, result = future.result()
                if result is None:
                    continue

                model_name = os.path.basename(path)

                # Thread-safe progress update
                with self._progress_lock:
                    self._progress.current_model = model_name
                    self._progress.processed += 1

                    if result.success:
                        self._progress.synced += 1
                    elif result.skipped:
                        self._progress.skipped += 1
                    elif result.not_found:
                        self._progress.not_found += 1
                    else:
                        self._progress.errors += 1
                        if result.error:
                            error_msg = f"{model_name}: {result.error}"
                            self._progress.error_messages.append(error_msg)
                            # Keep only last 10 errors
                            if len(self._progress.error_messages) > 10:
                                self._progress.error_messages = self._progress.error_messages[-10:]

        self._progress.current_model = ""
        self._progress.is_complete = True

        print(f"[ModelManager] Sync complete: {self._progress.synced} synced, "
              f"{self._progress.not_found} not found, {self._progress.skipped} skipped, "
              f"{self._progress.errors} errors")

        return self._progress

    def cancel(self):
        """Request cancellation of the sync operation."""
        self._cancel_requested = True
        print("[ModelManager] Sync cancellation requested")

    @property
    def progress(self) -> SyncProgress:
        """Get current sync progress."""
        return self._progress
