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
import math
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable, Tuple

from .civitai import (
    CivitaiClient,
    CivitaiAPIError,
    CivitaiNotFoundError,
    apply_generation_data,
    enrich_images_with_generation_data,
    generation_ids_needing_lookup,
)
from .hashing import BLAKE3_AVAILABLE, HashResult, ModelHasher
from .storage import write_civitai_info
from .nsfw import UNKNOWN
from .db import get_models_db



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
            # Civitai has already been asked about this file and did not know
            # it. Most LoRAs, VAEs and text encoders never came from Civitai,
            # so without this the next run would re-read the whole file to
            # recompute its hashes and ask again, for nothing. Force ignores
            # this, because a model can appear on Civitai later.
            if existing and existing.get("civitai_lookup_failed_at"):
                print(f"[ModelManager] Skipping {model_name} "
                      f"(not on Civitai as of {existing['civitai_lookup_failed_at'][:10]})")
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
                get_models_db().set_lookup_failed(model_path)
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
                data_to_save = full_model_data
            else:
                # Fallback to version-only data if full model fetch failed
                print(f"[ModelManager] Warning: Could not fetch full model data for {model_name}")
                data_to_save = version_data

            data_to_save = self._payload_with_version_first(data_to_save, version_id)

            if not write_civitai_info(model_path, data_to_save):
                result.error = "Failed to write civitai.info"
                return result

            # Fetch first batch of images (100) using cursor pagination
            if version_id:
                print(f"[ModelManager] Fetching images for {model_name}...")
                images_result = self.client.get_model_images(version_id, cursor=None, limit=100)
                images = images_result.get("images", [])
                # /images returns meta: null - generation data comes from a
                # separate endpoint. Without this, a forced re-sync would
                # replace existing prompts with nulls.
                enrich_images_with_generation_data(self.client, images)
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

            # Update database with model and version data. A failure here
            # means the model will not show up in the UI, so it must not be
            # reported as a successful sync.
            db_error = self._update_database(model_path, data_to_save, hashes)
            if db_error:
                result.error = f"Database update failed: {db_error}"
                return result

            # It was found, so drop any earlier "not on Civitai" note. The
            # accessor rather than `db`, which is only bound on some paths.
            get_models_db().set_lookup_failed(model_path, failed=False)

            result.success = True
            has_more = next_cursor is not None if version_id else False
            print(f"[ModelManager] Synced {model_name}: {result.image_count} images (has_more: {has_more})")

            return result

        except CivitaiNotFoundError:
            get_models_db().set_lookup_failed(model_path)
            result.not_found = True
            return result

        except CivitaiAPIError as e:
            result.error = str(e)
            return result

        except Exception as e:
            result.error = f"Unexpected error: {e}"
            return result

    def _update_database(self, model_path: str, civitai_data: Dict, hashes: HashResult) -> Optional[str]:
        """
        Update the database with model and version data from Civitai response.

        Args:
            model_path: Path to the local model file.
            civitai_data: Full Civitai model response (or version-only if model fetch failed).
            hashes: HashResult with all computed hashes.

        Returns:
            None on success, or an error message describing the failure.
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
                    "nsfw_level": civitai_data.get("nsfwLevel", UNKNOWN),
                    "tags": civitai_data.get("tags", []),
                    "creator_username": creator.get("username") if creator else None,
                    "creator_image_url": creator.get("image") if creator else None,
                    "stats_download_count": stats.get("downloadCount", 0),
                    "stats_thumbs_up": thumbs_up,
                    "stats_thumbs_down": thumbs_down,
                    "stats_rating": rating,
                    "allow_no_credit": civitai_data.get("allowNoCredit", True),
                    "allow_commercial_use": civitai_data.get("allowCommercialUse"),
                    "allow_derivatives": civitai_data.get("allowDerivatives", True),
                    "allow_different_license": civitai_data.get("allowDifferentLicense", True),
                    "supports_generation": civitai_data.get("supportsGeneration", False),
                }
                db.upsert_civitai_model(civitai_model, from_civitai=True)

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
                        "nsfw_level": matched_version.get("nsfwLevel", UNKNOWN),
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
                    "nsfw_level": civitai_data.get("nsfwLevel", UNKNOWN),
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

                db.upsert_version(version_data)

            return None

        except Exception as e:
            import traceback
            print(f"[ModelManager] Error updating database for {os.path.basename(model_path)}: {e}")
            traceback.print_exc()
            return str(e)

    def _hashes_to_dict(self, hashes: HashResult) -> Dict[str, str]:
        """
        Convert HashResult to a dict for storage.

        Only includes non-None hash values.

        Args:
            hashes: HashResult with computed hashes.

        Returns:
            Dict mapping hash type to value.
        """
        return hashes.to_dict()

    def sync_all(
        self,
        model_paths: Optional[List[str]] = None,
        force: bool = False,
        callback: Optional[Callable[[SyncProgress], None]] = None,
        max_workers: Optional[int] = None
    ) -> SyncProgress:
        """
        Sync multiple models with Civitai using multiple threads.

        Args:
            model_paths: Specific paths to sync, or None for all models.
            force: Re-sync even if civitai data exists.
            callback: Called after each model with progress update.
            max_workers: Number of parallel threads, or None to take the
                setting. Hashing is bound by reading and hashing bytes, and
                both scale with threads, so this is the dial that matters for
                a full sync.

        Returns:
            Final SyncProgress with summary.
        """
        self._cancel_requested = False
        self._progress_lock = threading.Lock()

        if max_workers is None:
            max_workers = configured_hash_threads()

        # Get all models if not specified
        if model_paths is None:
            from .scan_service import ScanService
            scan_svc = ScanService()
            directories = scan_svc._get_model_directories()
            model_paths = scan_svc.find_model_files(directories)

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

    @staticmethod
    def _payload_with_version_first(model_data: Dict, version_id: Optional[int]) -> Dict:
        """
        Put the version we hold locally at the front of modelVersions.

        Everything downstream - the sidecar, _update_database, the details
        panel - reads modelVersions[0] as "the one this file is".
        """
        versions = model_data.get("modelVersions")
        if not versions or version_id is None:
            return model_data

        matched = [v for v in versions if v.get("id") == version_id]
        if not matched:
            return model_data

        others = [v for v in versions if v.get("id") != version_id]
        model_data["modelVersions"] = matched + others
        return model_data

    def sync_metadata(
        self,
        model_paths: Optional[List[str]] = None,
        include_images: bool = False,
        include_prompts: bool = True,
        synced_before: Optional[str] = None,
        downloaded_after: Optional[str] = None,
        callback: Optional[Callable[[SyncProgress], None]] = None,
        max_workers: Optional[int] = None
    ) -> SyncProgress:
        """
        Refresh Civitai data for models that already resolve, without hashing.

        sync_all() exists to *identify* a file: it reads every byte to compute
        hashes and asks Civitai which version they belong to. Once that has
        happened the answer is recorded, so refreshing descriptions, tags,
        stats and licences only needs the model ids we already hold. That turns
        an hours-long pass over a large library into a handful of requests,
        since ids are fetched a hundred at a time.

        Versions that have never resolved are counted as skipped - identifying
        them requires the hashing that sync_all() does.

        Args:
            model_paths: Restrict to these files, or None for everything.
            include_images: Also refetch each version's gallery. This is the
                expensive half: images cannot be batched, and the existing
                rows for a version are replaced.
            include_prompts: Look up the generation data behind those images.
                Civitai's public endpoint returns meta: null, so without this
                the galleries arrive without prompts - and with it, they cost
                a request per thirty images, which is most of a full sync.
            synced_before: Only refresh models last refreshed before this ISO
                timestamp, for "everything I have not touched in a week".
            downloaded_after: Only refresh versions downloaded since this ISO
                timestamp, for "whatever I added this week".
            callback: Called after each version with progress.
            max_workers: Threads used for the per-version work. None derives
                it from the configured request rate, which is what actually
                bounds the sync - a thread beyond that only waits for a token.

        Returns:
            Final SyncProgress with summary.
        """
        self._cancel_requested = False
        self._progress_lock = threading.Lock()

        if max_workers is None:
            max_workers = self._workers_for_rate()

        db = get_models_db()
        versions = db.get_linked_versions(synced_before=synced_before,
                                          downloaded_after=downloaded_after)

        if model_paths is not None:
            wanted = set(model_paths)
            versions = [v for v in versions if v["file_path"] in wanted]

        missing = [v for v in versions if not os.path.exists(v["file_path"])]
        versions = [v for v in versions if os.path.exists(v["file_path"])]

        # With images this runs twice over the list - metadata, then galleries
        # - so the bar counts both passes rather than filling up halfway.
        passes = 2 if include_images else 1
        self._progress = SyncProgress(total=len(versions) * passes)
        self._progress.skipped = len(missing)
        for version in missing:
            self._progress.error_messages.append(
                f"File not found: {os.path.basename(version['file_path'])}"
            )

        if not versions:
            self._progress.is_complete = True
            return self._progress

        model_ids = list(dict.fromkeys(v["model_id"] for v in versions))
        print(f"[ModelManager] Metadata sync: {len(versions)} versions across "
              f"{len(model_ids)} models (images={include_images})")

        self._progress.current_model = f"Fetching {len(model_ids)} models from Civitai..."
        if callback:
            callback(self._progress)

        try:
            fetched = self.client.get_models_by_ids(model_ids)
        except Exception as e:
            self._progress.is_complete = True
            self._progress.error_messages.append(f"Could not fetch models: {e}")
            return self._progress

        print(f"[ModelManager] Metadata sync: Civitai returned {len(fetched)} of {len(model_ids)}")

        def process(version: Dict[str, Any]) -> None:
            if self._cancel_requested:
                return

            path = version["file_path"]
            name = os.path.basename(path)
            model_data = fetched.get(version["model_id"])

            with self._progress_lock:
                self._progress.current_model = name

            if not model_data:
                with self._progress_lock:
                    self._progress.processed += 1
                    self._progress.not_found += 1
                return

            try:
                # A fresh copy per version: the reordering below is per file,
                # and several local files can share one model.
                payload = self._payload_with_version_first(
                    json.loads(json.dumps(model_data)), version["id"]
                )

                if not write_civitai_info(path, payload):
                    raise RuntimeError("could not write civitai.info")

                db_error = self._update_database(
                    path, payload, HashResult.from_stored(version["file_hashes"])
                )
                if db_error:
                    raise RuntimeError(db_error)

                with self._progress_lock:
                    self._progress.processed += 1
                    self._progress.synced += 1

            except Exception as e:
                with self._progress_lock:
                    self._progress.processed += 1
                    self._progress.errors += 1
                    self._progress.error_messages.append(f"{name}: {e}")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process, v) for v in versions]
            for future in as_completed(futures):
                future.result()
                if callback:
                    callback(self._progress)
                if self._cancel_requested:
                    break

        if include_images and not self._cancel_requested:
            self._refresh_galleries(versions, callback, max_workers, include_prompts)

        self._progress.is_complete = True
        self._progress.current_model = ""
        print(f"[ModelManager] Metadata sync complete: {self._progress.synced} updated, "
              f"{self._progress.not_found} not on Civitai, {self._progress.errors} errors")
        return self._progress

    # Galleries are refreshed a chunk of versions at a time, not one by one.
    # The generation data behind them is fetched by id, 30 ids per request,
    # and a batch filled from one gallery is mostly half-empty: 90 images
    # means three full requests and one carrying ten. Pooling a chunk's ids
    # fills every batch but the last, which over this library is ~470 fewer
    # requests - and the rate limiter charges one token per request.
    GALLERY_CHUNK = 40

    def _workers_for_rate(self) -> int:
        """
        How many threads the configured request rate can keep busy.

        Every request takes a token from one shared bucket, so throughput is
        the rate, not the thread count; threads only exist to cover the time
        a request spends in flight. One thread per request-per-second covers a
        round trip of up to a second, which is past what Civitai takes.
        """
        rate = getattr(getattr(self.client, "rate_limiter", None),
                       "tokens_per_second", 4.0)
        return max(4, min(int(rate + 0.5), 12))

    def _refresh_galleries(self,
                           versions: List[Dict[str, Any]],
                           callback: Optional[Callable[[SyncProgress], None]],
                           max_workers: int,
                           include_prompts: bool = True) -> None:
        """Replace each version's cached gallery with a fresh first page."""
        db = get_models_db()

        for start in range(0, len(versions), self.GALLERY_CHUNK):
            if self._cancel_requested:
                return

            chunk = versions[start:start + self.GALLERY_CHUNK]
            galleries: List[Tuple[int, List[Dict[str, Any]]]] = []

            def fetch(version: Dict[str, Any]) -> None:
                if self._cancel_requested or not version.get("id"):
                    # Linked to a model but with no version id of its own, so
                    # there is no gallery to ask for.
                    return
                name = os.path.basename(version["file_path"])
                with self._progress_lock:
                    self._progress.current_model = f"Images: {name}"
                try:
                    result = self.client.get_model_images(
                        version["id"], cursor=None, limit=100
                    )
                    images = result.get("images", [])
                except Exception as e:
                    with self._progress_lock:
                        self._progress.errors += 1
                        self._progress.error_messages.append(f"{name}: images: {e}")
                    images = []
                with self._progress_lock:
                    galleries.append((version["id"], images))

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for future in as_completed([executor.submit(fetch, v) for v in chunk]):
                    future.result()

            # One pooled lookup for the whole chunk, then hand each gallery
            # back the rows that belong to it.
            pooled: List[int] = []
            if include_prompts:
                for _, images in galleries:
                    pooled.extend(generation_ids_needing_lookup(images))

            generation_data: Dict[int, Dict[str, Any]] = {}
            if pooled:
                try:
                    generation_data = self.client.get_generation_data(pooled)
                except Exception as e:
                    print(f"[ModelManager] Generation data lookup failed: {e}")

            with self._progress_lock:
                self._progress.processed += len(chunk) - len(galleries)

            for version_id, images in galleries:
                if generation_data:
                    apply_generation_data(images, generation_data)
                try:
                    db.clear_version_images(version_id)
                    if images:
                        db.store_images(version_id, page=1, images=images)
                except Exception as e:
                    with self._progress_lock:
                        self._progress.errors += 1
                        self._progress.error_messages.append(f"images {version_id}: {e}")

                with self._progress_lock:
                    self._progress.processed += 1

            if callback:
                callback(self._progress)

    def cancel(self):
        """Request cancellation of the sync operation."""
        self._cancel_requested = True
        print("[ModelManager] Sync cancellation requested")

    @property
    def progress(self) -> SyncProgress:
        """Get current sync progress."""
        return self._progress


# ---------------------------------------------------------------- estimating

# The staleness windows the sync dialog offers, shortest first. They are here
# rather than in the UI so the counts beside them and the filter behind them
# cannot drift apart.
SYNC_WINDOWS: List[Tuple[str, int]] = [
    ("1 day", 1),
    ("2 days", 2),
    ("7 days", 7),
    ("1 month", 30),
    ("3 months", 90),
    ("6 months", 180),
]


def window_cutoff(days: int) -> str:
    """The timestamp `days` ago, in the form the database stores."""
    return (datetime.now() - timedelta(days=days)).isoformat()


def configured_hash_threads() -> int:
    """
    How many files to hash at once, as the settings have it.

    Unlike the metadata sync, this is not bound by an API rate: it is bound by
    reading and hashing bytes, and both scale nearly linearly with threads. The
    right number depends on the disk the models are on, which is why it is a
    setting rather than a constant.
    """
    try:
        from modules import shared
        configured = getattr(shared.opts, 'model_manager_hash_threads', None)
        if configured:
            return max(1, min(int(configured), 16))
    except Exception:
        pass
    return 4


def configured_rate() -> float:
    """Requests per second the client will be allowed, as the settings have it."""
    try:
        from modules import shared
        configured = getattr(shared.opts, 'model_manager_civitai_requests_per_second', None)
        api_key = getattr(shared.opts, 'model_manager_civitai_api_key', '')
        if not api_key:
            return CivitaiClient.UNAUTH_RATE
        if configured:
            return max(0.5, min(float(configured), 10.0))
        return CivitaiClient.AUTH_RATE
    except Exception:
        return CivitaiClient.AUTH_RATE


def estimate_metadata_sync(model_paths: Optional[List[str]] = None,
                           synced_before: Optional[str] = None,
                           downloaded_after: Optional[str] = None,
                           include_images: bool = False,
                           include_prompts: bool = True,
                           rate: Optional[float] = None) -> Dict[str, Any]:
    """
    What a metadata sync would cost, before anyone commits to it.

    Counted the way sync_metadata() actually batches, so the number shown in
    the dialog is the number of requests that will be made: models a hundred
    per request, one gallery page per version, and generation data thirty ids
    per request pooled across a chunk of versions.

    The image figures rest on the galleries already cached, which is the only
    guide there is before fetching them. A version whose gallery has never
    been cached is costed at the library's average.

    Args:
        model_paths: Restrict to these files, or None for everything.
        synced_before: Only models last refreshed before this ISO timestamp.
        downloaded_after: Only versions downloaded since this ISO timestamp.
        include_images: Whether galleries would be refetched.
        include_prompts: Whether generation data would be looked up.
        rate: Requests per second, or None to read the setting.

    Returns:
        Counts, a request breakdown, and the seconds each part would take.
    """
    db = get_models_db()
    versions = db.get_linked_versions(synced_before=synced_before,
                                      downloaded_after=downloaded_after)

    if model_paths is not None:
        wanted = set(model_paths)
        versions = [v for v in versions if v["file_path"] in wanted]

    models = len({v["model_id"] for v in versions})
    rate = rate or configured_rate()

    metadata_requests = math.ceil(models / 100) if models else 0
    image_requests = sum(1 for v in versions if v.get("id")) if include_images else 0

    prompt_requests = 0
    images_total = 0
    if include_images and include_prompts:
        counts = db.count_images_by_version()
        average = round(sum(counts.values()) / len(counts)) if counts else 0
        per_version = [counts.get(v["id"]) or average
                       for v in versions if v.get("id")]
        images_total = sum(per_version)
        # Pooled per chunk, exactly as _refresh_galleries does it.
        for start in range(0, len(per_version), SyncService.GALLERY_CHUNK):
            chunk = per_version[start:start + SyncService.GALLERY_CHUNK]
            prompt_requests += math.ceil(sum(chunk) / CivitaiClient.GENERATION_DATA_BATCH)

    total = metadata_requests + image_requests + prompt_requests
    return {
        "versions": len(versions),
        # What "All models" would come to, so the dialog can show it beside
        # that option whichever scope is currently selected.
        "all_versions": len(db.get_linked_versions()),
        "models": models,
        "images": images_total,
        "rate": rate,
        "requests": {
            "metadata": metadata_requests,
            "images": image_requests,
            "prompts": prompt_requests,
            "total": total,
        },
        "seconds": {
            "metadata": metadata_requests / rate,
            "images": image_requests / rate,
            "prompts": prompt_requests / rate,
            "total": total / rate,
        },
    }


def sync_window_counts(model_paths: Optional[List[str]] = None,
                       basis: str = "synced") -> List[Dict[str, Any]]:
    """
    How many versions each window would select.

    The dialog shows these beside the windows, so "not synced in 7 days" is
    never a guess about what it will do.

    Args:
        model_paths: Restrict to these files, or None for everything.
        basis: "synced" counts models not refreshed within the window;
            "downloaded" counts versions that arrived inside it. The two run
            in opposite directions - one is looking for the neglected, the
            other for the new - which is why they are separate scopes rather
            than one control with a sign.
    """
    db = get_models_db()
    out = []
    for label, days in SYNC_WINDOWS:
        if basis == "downloaded":
            versions = db.get_linked_versions(downloaded_after=window_cutoff(days))
        else:
            versions = db.get_linked_versions(synced_before=window_cutoff(days))
        if model_paths is not None:
            wanted = set(model_paths)
            versions = [v for v in versions if v["file_path"] in wanted]
        out.append({"label": label, "days": days, "versions": len(versions)})
    return out
