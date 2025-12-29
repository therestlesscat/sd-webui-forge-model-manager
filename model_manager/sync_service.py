"""
Sync service for fetching model data from Civitai.
"""
import os
import hashlib
import zlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Callable, Tuple

from .civitai_api import CivitaiClient, CivitaiAPIError, CivitaiNotFoundError
from .storage import write_civitai_info
from .models_db import get_models_db

# Try to import blake3, fall back gracefully if not available
try:
    import blake3
    BLAKE3_AVAILABLE = True
except ImportError:
    BLAKE3_AVAILABLE = False
    print("[ModelManager] Warning: blake3 not installed, BLAKE3 hash fallback disabled")


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


@dataclass
class HashResult:
    """Result of hash calculation with all computed hashes."""
    sha256: Optional[str] = None          # Full file SHA256 (64 chars)
    autov2: Optional[str] = None          # First 10 chars of SHA256
    autov3: Optional[str] = None          # First 12 chars of tensor-only SHA256 (safetensors)
    autov1: Optional[str] = None          # SHA256 of 64KB at 1MB offset, first 8 chars
    crc32: Optional[str] = None           # Full file CRC32 (8 chars)
    blake3: Optional[str] = None          # Full file BLAKE3 (64 chars)
    tensor_sha256: Optional[str] = None   # Full tensor-only SHA256 (safetensors)


class ModelHasher:
    """
    Calculate multiple hash types for model files.

    Supports:
    - SHA256: Full file hash
    - AutoV2: First 10 chars of full SHA256
    - AutoV3: First 12 chars of tensor-only SHA256 (safetensors only)
    - AutoV1: SHA256 of 64KB at 1MB offset, first 8 chars
    - CRC32: Full file CRC32
    - BLAKE3: Full file BLAKE3 hash
    """

    CHUNK_SIZE = 1024 * 1024  # 1MB chunks for reading

    @classmethod
    def calculate_all(cls, file_path: str) -> HashResult:
        """
        Calculate all hash types for a file.

        For safetensors files, also calculates tensor-only hashes.

        Args:
            file_path: Path to the model file.

        Returns:
            HashResult with all computed hashes.
        """
        result = HashResult()
        is_safetensors = file_path.lower().endswith('.safetensors')

        try:
            # Calculate full file hashes in a single pass
            sha256_hasher = hashlib.sha256()
            blake3_hasher = blake3.blake3() if BLAKE3_AVAILABLE else None
            crc = 0

            # For AutoV1: need to capture 64KB at 1MB offset
            autov1_data = b""
            autov1_offset = 1048576  # 1MB
            autov1_size = 65536      # 64KB
            bytes_read = 0

            with open(file_path, "rb") as f:
                # For safetensors, read header size first
                header_size = 0
                if is_safetensors:
                    header_bytes = f.read(8)
                    if len(header_bytes) == 8:
                        header_size = int.from_bytes(header_bytes, "little")
                        # Update hashes with header size bytes
                        sha256_hasher.update(header_bytes)
                        if blake3_hasher:
                            blake3_hasher.update(header_bytes)
                        crc = zlib.crc32(header_bytes, crc)
                        bytes_read = 8

                        # Check if 1MB offset falls within header
                        if autov1_offset < bytes_read:
                            autov1_data = header_bytes[autov1_offset:autov1_offset + autov1_size]

                # Read rest of file
                for chunk in iter(lambda: f.read(cls.CHUNK_SIZE), b""):
                    sha256_hasher.update(chunk)
                    if blake3_hasher:
                        blake3_hasher.update(chunk)
                    crc = zlib.crc32(chunk, crc)

                    # Capture AutoV1 data if we're in the right range
                    chunk_start = bytes_read
                    chunk_end = bytes_read + len(chunk)

                    if chunk_start < autov1_offset + autov1_size and chunk_end > autov1_offset:
                        # Calculate overlap with AutoV1 range
                        start_in_chunk = max(0, autov1_offset - chunk_start)
                        end_in_chunk = min(len(chunk), autov1_offset + autov1_size - chunk_start)
                        autov1_data += chunk[start_in_chunk:end_in_chunk]

                    bytes_read += len(chunk)

            # Store full file hashes
            result.sha256 = sha256_hasher.hexdigest().upper()
            result.autov2 = result.sha256[:10]
            result.crc32 = format(crc & 0xFFFFFFFF, '08X')

            if blake3_hasher:
                result.blake3 = blake3_hasher.hexdigest().upper()

            # Calculate AutoV1 if we have enough data
            if len(autov1_data) >= autov1_size:
                autov1_hash = hashlib.sha256(autov1_data[:autov1_size]).hexdigest().upper()
                result.autov1 = autov1_hash[:8]

            # For safetensors, calculate tensor-only hash (AutoV3)
            if is_safetensors and header_size > 0:
                result.tensor_sha256, result.autov3 = cls._calculate_tensor_hash(file_path, header_size)

        except Exception as e:
            print(f"[ModelManager] Error calculating hashes for {os.path.basename(file_path)}: {e}")

        return result

    @classmethod
    def _calculate_tensor_hash(cls, file_path: str, header_size: int) -> Tuple[Optional[str], Optional[str]]:
        """
        Calculate tensor-only SHA256 for safetensors files.

        Args:
            file_path: Path to safetensors file.
            header_size: Size of the header (from first 8 bytes).

        Returns:
            Tuple of (full tensor SHA256, AutoV3 - first 12 chars).
        """
        try:
            sha256_hasher = hashlib.sha256()
            offset = 8 + header_size  # Skip header size bytes + header

            with open(file_path, "rb") as f:
                f.seek(offset)
                for chunk in iter(lambda: f.read(cls.CHUNK_SIZE), b""):
                    sha256_hasher.update(chunk)

            tensor_sha256 = sha256_hasher.hexdigest().upper()
            autov3 = tensor_sha256[:12]
            return tensor_sha256, autov3

        except Exception as e:
            print(f"[ModelManager] Error calculating tensor hash: {e}")
            return None, None

    @classmethod
    def get_fallback_order(cls, file_path: str) -> List[str]:
        """
        Get the order of hash types to try for lookup.

        Args:
            file_path: Path to model file (to check if safetensors).

        Returns:
            List of hash type names in fallback order.
        """
        is_safetensors = file_path.lower().endswith('.safetensors')

        # Base order: SHA256 -> CRC32 -> BLAKE3 -> AutoV1 -> AutoV2
        order = ["sha256", "crc32", "blake3", "autov1", "autov2"]

        # For safetensors, add AutoV3 after SHA256 (most likely to work for modified files)
        if is_safetensors:
            order.insert(1, "autov3")

        return order

    @classmethod
    def load_cm_info_hashes(cls, file_path: str) -> Optional[Dict[str, str]]:
        """
        Load hashes from .cm-info.json file if it exists.

        Args:
            file_path: Path to model file.

        Returns:
            Dict of hash type -> hash value, or None if not found.
        """
        base = os.path.splitext(file_path)[0]
        cm_info_path = base + ".cm-info.json"

        if not os.path.exists(cm_info_path):
            return None

        try:
            with open(cm_info_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            hashes = data.get("Hashes", {})
            if hashes:
                # Normalize to our format (uppercase)
                return {k.lower(): v.upper() for k, v in hashes.items()}
        except Exception as e:
            print(f"[ModelManager] Error reading .cm-info.json: {e}")

        return None


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

    def calculate_hashes(self, file_path: str) -> HashResult:
        """
        Calculate all hash types for a model file.

        Args:
            file_path: Path to the model file.

        Returns:
            HashResult with all computed hashes.
        """
        model_name = os.path.basename(file_path)
        print(f"[ModelManager] Calculating hashes for {model_name}...")
        return ModelHasher.calculate_all(file_path)

    def _lookup_by_hash_with_fallback(
        self,
        file_path: str,
        hashes: HashResult
    ) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
        """
        Try to find model on Civitai using multiple hash types with fallback.

        Tries hashes in order: SHA256 -> AutoV3 (safetensors) -> CRC32 -> BLAKE3 -> AutoV1 -> AutoV2

        Args:
            file_path: Path to model file.
            hashes: Pre-calculated hash values.

        Returns:
            Tuple of (version_data, matched_hash_type, matched_hash_value) or (None, None, None).
        """
        model_name = os.path.basename(file_path)
        fallback_order = ModelHasher.get_fallback_order(file_path)

        # Also check .cm-info.json for stored hashes
        cm_info_hashes = ModelHasher.load_cm_info_hashes(file_path)

        for hash_type in fallback_order:
            # Get hash value from our calculations
            hash_value = getattr(hashes, hash_type, None)

            # Skip if we don't have this hash
            if not hash_value:
                # Check if .cm-info.json has it
                if cm_info_hashes and hash_type in cm_info_hashes:
                    hash_value = cm_info_hashes[hash_type]
                else:
                    continue

            try:
                version_data = self.client.get_model_by_hash(hash_value)
                if version_data:
                    print(f"[ModelManager] Found {model_name} via {hash_type.upper()}: {hash_value[:16]}...")
                    return version_data, hash_type, hash_value
            except CivitaiNotFoundError:
                # This hash didn't match, try next
                continue
            except CivitaiAPIError as e:
                # API error, log but continue trying other hashes
                print(f"[ModelManager] API error with {hash_type}: {e}")
                continue

        # If we have .cm-info.json hashes that we didn't calculate, try those too
        if cm_info_hashes:
            for hash_type, hash_value in cm_info_hashes.items():
                # Skip if already tried
                if hash_type in fallback_order:
                    continue

                try:
                    version_data = self.client.get_model_by_hash(hash_value)
                    if version_data:
                        print(f"[ModelManager] Found {model_name} via .cm-info.json {hash_type.upper()}: {hash_value[:16]}...")
                        return version_data, hash_type, hash_value
                except (CivitaiNotFoundError, CivitaiAPIError):
                    continue

        return None, None, None

    def sync_model(self, model_path: str, force: bool = False) -> SyncResult:
        """
        Sync a single model with Civitai.

        Steps:
        1. Check if .civitai.info exists and has full data (skip if complete, unless force)
        2. Calculate multiple hash types (SHA256, AutoV3, CRC32, BLAKE3, AutoV1, AutoV2)
        3. Try by-hash endpoint with fallback through hash types
        4. Call model endpoint to get full model data (description, tags, stats)
        5. Fetch images for the version
        6. Save full model data to .civitai.info

        Args:
            model_path: Path to the model file.
            force: Re-sync even if civitai data exists.

        Returns:
            SyncResult with status and details.
        """
        result = SyncResult()
        model_name = os.path.basename(model_path)

        # Check if already synced (using database as source of truth)
        if not force:
            db = get_models_db()
            existing = db.get_version(model_path)
            if existing and existing.get("has_civitai_data"):
                print(f"[ModelManager] Skipping {model_name} (already synced)")
                result.skipped = True
                return result

        print(f"[ModelManager] Processing {model_name}...")

        # Calculate all hash types
        hashes = self.calculate_hashes(model_path)
        if not hashes.sha256:
            result.error = "Failed to calculate hashes"
            return result

        try:
            # Try to find model using fallback hash lookup
            version_data, matched_hash_type, matched_hash = self._lookup_by_hash_with_fallback(
                model_path, hashes
            )

            if not version_data:
                print(f"[ModelManager] {model_name} not found on Civitai (tried all hash types)")
                result.not_found = True
                return result

            version_id = version_data.get("id")
            model_id = version_data.get("modelId")

            result.version_id = version_id
            result.model_id = model_id

            # Fetch full model data (includes description, tags, stats)
            full_model_data = None
            if model_id:
                print(f"[ModelManager] Fetching full model data for {model_name}...")
                full_model_data = self.client.get_model(model_id)

            # Prepare data to save
            if full_model_data:
                # We have full model data - reorder versions to put matched version first
                model_versions = full_model_data.get("modelVersions", [])

                # Find the matched version and move it to front
                matched_version = None
                other_versions = []
                for v in model_versions:
                    if v.get("id") == version_id:
                        matched_version = v
                    else:
                        other_versions.append(v)

                # Rebuild versions list with matched version first
                if matched_version:
                    full_model_data["modelVersions"] = [matched_version] + other_versions

                # Save full model data
                data_to_save = full_model_data
            else:
                # Fallback to version-only data if full model fetch failed
                print(f"[ModelManager] Warning: Could not fetch full model data for {model_name}")
                data_to_save = version_data

            if not write_civitai_info(model_path, data_to_save):
                result.error = "Failed to write civitai.info"
                return result

            # Fetch first batch of images (100) using cursor pagination
            if version_id:
                print(f"[ModelManager] Fetching images for {model_name}...")
                images_result = self.client.get_model_images(version_id, cursor=None, limit=100)
                images = images_result.get("images", [])
                next_cursor = images_result.get("next_cursor")
                result.image_count = len(images)

                # Store images in database
                db = get_models_db()
                # Clear any existing images for this version
                db.clear_version_images(version_id)
                # Store images
                if images:
                    db.store_images(version_id, page=1, images=images)
                # Update cursor and sync date
                db.update_version_images_state(version_id, next_cursor)

            # Update database with model and version data
            self._update_database(model_path, data_to_save, hashes)

            result.success = True
            has_more = next_cursor is not None if version_id else False
            print(f"[ModelManager] Synced {model_name}: {result.image_count} images (has_more: {has_more})")

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

    def _update_database(self, model_path: str, civitai_data: Dict, hashes: HashResult):
        """
        Update the database with model and version data from Civitai response.

        Args:
            model_path: Path to the local model file.
            civitai_data: Full Civitai model response (or version-only if model fetch failed).
            hashes: HashResult with all computed hashes.
        """
        try:
            db = get_models_db()
            file_name = os.path.basename(model_path)
            file_ext = os.path.splitext(model_path)[1].lower()

            # Get file stats
            file_size = 0
            file_modified = None
            try:
                stat = os.stat(model_path)
                file_size = stat.st_size
                from datetime import datetime
                file_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except OSError:
                pass

            model_id = civitai_data.get("id")
            versions = civitai_data.get("modelVersions", [])

            if model_id and versions:
                # Full model response - extract and save model-level data
                stats = civitai_data.get("stats", {})
                creator = civitai_data.get("creator", {})

                # Calculate rating from thumbs
                thumbs_up = stats.get("thumbsUpCount", 0)
                thumbs_down = stats.get("thumbsDownCount", 0)
                rating = 0
                if thumbs_up + thumbs_down > 0:
                    rating = round((thumbs_up / (thumbs_up + thumbs_down)) * 5, 2)

                civitai_model = {
                    "id": model_id,
                    "name": civitai_data.get("name", ""),
                    "description": civitai_data.get("description"),
                    "type": civitai_data.get("type", "Checkpoint"),
                    "nsfw": civitai_data.get("nsfw", False),
                    "nsfw_level": civitai_data.get("nsfwLevel", 64),  # Default to Unknown
                    "tags": civitai_data.get("tags", []),
                    "creator_username": creator.get("username") if creator else None,
                    "creator_image_url": creator.get("image") if creator else None,
                    "stats_download_count": stats.get("downloadCount", 0),
                    "stats_thumbs_up": thumbs_up,
                    "stats_rating": rating,
                    "allow_no_credit": civitai_data.get("allowNoCredit", True),
                    "allow_commercial_use": civitai_data.get("allowCommercialUse"),
                    "allow_derivatives": civitai_data.get("allowDerivatives", True),
                    "allow_different_license": civitai_data.get("allowDifferentLicense", True),
                    "supports_generation": civitai_data.get("supportsGeneration", False),
                }
                db.upsert_civitai_model(civitai_model)

                # Find the matched version (first in list since we reordered it)
                matched_version = versions[0] if versions else None

                if matched_version:
                    version_stats = matched_version.get("stats", {})
                    version_data = {
                        "id": matched_version.get("id"),
                        "model_id": model_id,
                        "version_name": matched_version.get("name"),
                        "base_model": matched_version.get("baseModel"),
                        "published_at": matched_version.get("publishedAt"),
                        "created_at": matched_version.get("createdAt"),
                        "nsfw_level": matched_version.get("nsfwLevel", 64),  # Default to Unknown
                        "trained_words": matched_version.get("trainedWords", []),
                        "description": matched_version.get("description"),
                        "stats_download_count": version_stats.get("downloadCount", 0),
                        "stats_thumbs_up": version_stats.get("thumbsUpCount", 0),
                        "file_path": model_path,
                        "file_name": file_name,
                        "file_size": file_size,
                        "file_hashes": self._hashes_to_dict(hashes),
                        "file_modified": file_modified,
                        "file_extension": file_ext,
                        "has_civitai_data": True,
                    }

                    # Find preview
                    self._find_preview(model_path, version_data, matched_version.get("images", []))
                    db.upsert_version(version_data)

            else:
                # Version-only response (model fetch failed)
                version_id = civitai_data.get("id")
                version_model_id = civitai_data.get("modelId")
                version_stats = civitai_data.get("stats", {})

                version_data = {
                    "id": version_id,
                    "model_id": version_model_id,
                    "version_name": civitai_data.get("name"),
                    "base_model": civitai_data.get("baseModel"),
                    "published_at": civitai_data.get("publishedAt"),
                    "created_at": civitai_data.get("createdAt"),
                    "nsfw_level": civitai_data.get("nsfwLevel", 64),  # Default to Unknown
                    "trained_words": civitai_data.get("trainedWords", []),
                    "description": civitai_data.get("description"),
                    "stats_download_count": version_stats.get("downloadCount", 0),
                    "stats_thumbs_up": version_stats.get("thumbsUpCount", 0),
                    "file_path": model_path,
                    "file_name": file_name,
                    "file_size": file_size,
                    "file_hashes": self._hashes_to_dict(hashes),
                    "file_modified": file_modified,
                    "file_extension": file_ext,
                    "has_civitai_data": True,
                }

                # Find preview
                self._find_preview(model_path, version_data, civitai_data.get("images", []))
                db.upsert_version(version_data)

        except Exception as e:
            print(f"[ModelManager] Error updating database for {os.path.basename(model_path)}: {e}")

    def _hashes_to_dict(self, hashes: HashResult) -> Dict[str, str]:
        """
        Convert HashResult to a dict for storage.

        Only includes non-None hash values.

        Args:
            hashes: HashResult with computed hashes.

        Returns:
            Dict mapping hash type to value.
        """
        result = {}
        if hashes.sha256:
            result["sha256"] = hashes.sha256
        if hashes.autov2:
            result["autov2"] = hashes.autov2
        if hashes.autov3:
            result["autov3"] = hashes.autov3
        if hashes.autov1:
            result["autov1"] = hashes.autov1
        if hashes.crc32:
            result["crc32"] = hashes.crc32
        if hashes.blake3:
            result["blake3"] = hashes.blake3
        if hashes.tensor_sha256:
            result["tensor_sha256"] = hashes.tensor_sha256
        return result

    def _find_preview(self, model_path: str, version_data: Dict, images: List):
        """Find preview image for the model."""
        base = os.path.splitext(model_path)[0]
        preview_extensions = [".preview.png", ".preview.jpg", ".preview.jpeg", ".png", ".jpg"]

        for ext in preview_extensions:
            preview_path = base + ext
            if os.path.exists(preview_path):
                version_data["preview_path"] = preview_path
                return

        # No local preview - check for Civitai image URL
        if images and images[0].get("url"):
            version_data["preview_url"] = images[0]["url"]

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
