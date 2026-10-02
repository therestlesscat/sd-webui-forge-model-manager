"""
Scan service for populating the models database.

Scans model directories, reads metadata files, and stores
computed metadata in SQLite for fast querying.
"""
import os
import threading
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from .db import get_models_db
from .architecture import needs_check, store_architecture
from .file_identity import identify
from .model_dirs import gone_from_disk, library_dirs, proper_place, relocate
from .nsfw import (
    PG, UNKNOWN, max_image_level, model_level, showcase_is_complete,
    version_covers,
)
from .storage import read_civitai_info


def _sha256(hashes) -> str:
    return str((hashes or {}).get("sha256") or "").upper() if isinstance(hashes, dict) else ""


def misplaced_files(db) -> List[Dict[str, Any]]:
    """
    Every file in the library sitting in a folder for another type - a VAE
    in Stable-diffusion, where Forge offers it as a checkpoint - with where
    it belongs, what its header says and what said so, and whether a file
    of its name is already there: "same" (the library holds both, with one
    SHA-256), "different" (two SHA-256s), or "exists" (a file it cannot
    compare). Files whose type is Unknown are never among them.
    """
    found = []
    for row in db.files_with_types():
        to = proper_place(row["file_path"], row["file_type"])
        if not to:
            continue
        clash = None
        if os.path.exists(to):
            mine, theirs = _sha256(row["file_hashes"]), _sha256((db.get_version(to) or {}).get("file_hashes"))
            clash = ("same" if mine == theirs else "different") if mine and theirs else "exists"
        found.append({"path": row["file_path"], "to": to, "file_type": row["file_type"],
                      "identified_by": row["identified_by"], "clash": clash})
    return found


@dataclass
class ScanProgress:
    """Progress tracking for scan operation."""
    total: int = 0
    processed: int = 0
    current_file: str = ""
    is_complete: bool = False
    errors: List[str] = field(default_factory=list)
    moved: int = 0
    # Files left where they are, though another type's: something of that
    # name is already in their own folder.
    not_moved: List[str] = field(default_factory=list)

    def fail(self, message: str):
        """Finished by an error."""
        self.errors.append(message)
        self.is_complete = True

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "processed": self.processed,
            "current_file": self.current_file,
            "is_complete": self.is_complete,
            "error_count": len(self.errors),
            "moved": self.moved,
            "not_moved": len(self.not_moved),
        }


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


class ScanService:
    """
    Service for scanning models and populating the database.
    """

    # Model file extensions
    # .gguf: quantized models Forge loads directly (Flux, Wan, Z-Image...),
    # which were never indexed. .sft: safetensors under a short name.
    MODEL_EXTENSIONS = {".safetensors", ".sft", ".gguf", ".ckpt", ".pt", ".pth", ".bin"}

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
            # Unknown until the sidecar says otherwise, so a sidecar silent
            # on the level does not bring a PG in over the one stored.
            "nsfw_level": UNKNOWN,
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
        civitai_data = as_model_payload(read_civitai_info(model_path))
        civitai_model = None

        if civitai_data:
            version_data["has_civitai_data"] = True
            civitai_model = self._extract_civitai_metadata(civitai_data, version_data, model_path)
        else:
            version_data["base_model"] = None
            # PG keeps a file Civitai does not know visible under a level
            # filter. upsert_version() writes it only into a new row: a row
            # a sync rated keeps its level.
            version_data["nsfw_level"] = PG

        return civitai_model, version_data

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
                # Civitai's type, as Civitai gave it. What the file really
                # is comes from the file itself (file_identity.py).
                "type": data.get("type"),
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
                "versions": data.get("modelVersions"),
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

            # The cover only if this sidecar provably kept its non-PG images;
            # older syncs, and some other tools, wrote stripped ones.
            showcase = matched_version.get("images")
            version_data["cover_url"], version_data["safe_cover_url"] = version_covers(
                showcase, complete=bool(showcase) and showcase_is_complete(showcase))

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
        callback: Optional[Callable[[ScanProgress], None]] = None,
        reread_headers: bool = False,
        move_misplaced: bool = False,
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
        fixed = db.normalize_version_paths()
        if fixed:
            print(f"[ModelManager] Stored {fixed} file paths as a scan finds them")

        # Track which files we've seen (to remove deleted ones)
        seen_paths = set()

        def process_model(path: str):
            if self._cancel_requested:
                return None
            try:
                civitai_model, version_data = self.extract_metadata(path)
            except Exception as e:
                with self._progress_lock:
                    self._progress.errors.append(f"{os.path.basename(path)}: {e}")
                return None
            # What the file's own contents say it is - read here, on the
            # worker, and only for files new or changed since last time,
            # unless every header is to be read again. Never a reason to
            # fail the scan.
            architecture = None
            try:
                modified = needs_check(db, path, force=reread_headers)
                if modified is not None:
                    architecture = (identify(path), modified)
            except Exception as e:
                print(f"[ModelManager] Architecture check failed for {os.path.basename(path)}: {e}")
            return civitai_model, version_data, architecture

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
                    civitai_model, version_data, architecture = result
                    seen_paths.add(path)

                    # One file's bad metadata is that file's error, not the
                    # end of the scan for every file after it.
                    try:
                        # Insert/update civitai model if we have one
                        if civitai_model:
                            db.upsert_civitai_model(civitai_model)

                        # Insert/update version
                        db.upsert_version(version_data)

                        if architecture is not None:
                            store_architecture(db, path, *architecture)
                    except Exception as e:
                        print(f"[ModelManager] Could not store {os.path.basename(path)}: {e}")
                        with self._progress_lock:
                            self._progress.errors.append(f"{os.path.basename(path)}: {e}")

                if callback:
                    callback(self._progress)

        # Files in another type's folder go to their own, when asked: never
        # unasked, never over a file, and with their row, pin and
        # generations. Before the diff, which then finds them where they are.
        if move_misplaced and not self._cancel_requested:
            self._move_misplaced(db)

        # Forget files that are gone from disk - and only those. It used to
        # forget every file this pass had not stored, so a cancelled scan
        # dropped all the files it had not reached yet, and a file whose
        # sidecar failed to read lost its row though it was still there.
        # A cancelled scan forgets nothing: it has not looked everywhere.
        if not self._cancel_requested:
            removed_paths = gone_from_disk(db.get_all_version_paths(), model_files)
            for path in removed_paths:
                db.delete_version(path)

            if removed_paths:
                print(f"[ModelManager] Removed {len(removed_paths)} deleted models from database")

            # What only those files kept: their models, where no other file
            # of the model is left, and their gallery images.
            models_gone, images_gone = db.prune_orphans()
            if models_gone or images_gone:
                print(f"[ModelManager] Forgot {models_gone} models with no files left "
                      f"and {images_gone} of their images")

        # Update scan timestamp
        db.set_info("last_scan", datetime.now().isoformat())

        self._progress.current_file = ""
        self._progress.is_complete = True

        stats = db.get_stats()
        print(f"[ModelManager] Scan complete: {stats['total_versions']} versions "
              f"({stats['with_civitai_data']} with Civitai data, "
              f"{stats['total_civitai_models']} unique models)")

        return self._progress

    def _move_misplaced(self, db) -> None:
        for item in misplaced_files(db):
            path, to = item["path"], item["to"]
            try:
                if item["clash"] or not relocate(path, to):
                    self._progress.not_moved.append(path)
                    print(f"[ModelManager] Not moved: {path} - {to} is already there")
                    continue
                db.move_version(path, to)
                self._progress.moved += 1
                print(f"[ModelManager] Moved, as a {item['file_type']}: {path} -> {to}")
            except Exception as e:
                self._progress.errors.append(f"{os.path.basename(path)}: could not move it: {e}")
                print(f"[ModelManager] Could not move {path}: {e}")

    def _get_model_directories(self) -> List[str]:
        """Every folder the library walks - see model_dirs."""
        return library_dirs()

    def cancel(self):
        """Cancel the scan operation."""
        self._cancel_requested = True

    @property
    def progress(self) -> ScanProgress:
        """Get current scan progress."""
        return self._progress
