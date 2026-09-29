"""
Download service for Civitai Browser.
Handles downloading models from Civitai with progress tracking and parallel downloads.
"""
import hashlib
import os
import re
import json
import threading
import time
import requests
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from .civitai import paid_access_info
from .hashing import HashResult


# What a download is written as until it is whole and verified: never a
# model file extension, so no scan takes it for a model.
PARTIAL = ".partial"


@dataclass
class DownloadProgress:
    """Track download progress."""
    version_id: int
    file_name: str = ""
    total_bytes: int = 0
    downloaded_bytes: int = 0
    # pending, downloading, finishing, complete, error, cancelled. finishing:
    # the file is on disk and is being added to the library - the download is
    # not complete until it is, so that complete means ready to use.
    status: str = "pending"
    error: Optional[str] = None
    file_path: Optional[str] = None
    # Set with complete, once the library has the model; kept because callers
    # read it. sync_error says what went wrong if adding it failed.
    synced: bool = False
    sync_error: Optional[str] = None
    # The file's SHA-256, computed as it was written.
    sha256: Optional[str] = None

    @property
    def percent(self) -> float:
        if self.total_bytes == 0:
            return 0
        return (self.downloaded_bytes / self.total_bytes) * 100

    @property
    def is_complete(self) -> bool:
        return self.status in ("complete", "error", "cancelled")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "file_name": self.file_name,
            "total_bytes": self.total_bytes,
            "downloaded_bytes": self.downloaded_bytes,
            "percent": round(self.percent, 1),
            "status": self.status,
            "error": self.error,
            "file_path": self.file_path,
            "synced": self.synced,
            "sync_error": self.sync_error,
        }


class DownloadService:
    """
    Service for downloading models from Civitai.

    Features:
    - Streaming HTTP downloads with retries and terminal progress bars
    - Parallel download queue
    - Folder template processing
    - Automatic metadata file creation
    """

    # Map Civitai model types to WebUI folder names
    MODEL_TYPE_FOLDERS = {
        "Checkpoint": "Stable-diffusion",
        "LORA": "Lora",
        "LoCon": "Lora",
        "DoRA": "Lora",
        "TextualInversion": None,  # Special case: embeddings folder
        "Hypernetwork": "hypernetworks",
        "VAE": "VAE",
        "Controlnet": "ControlNet",
        "Upscaler": "ESRGAN",
        "MotionModule": "MotionModule",
        "Poses": "Poses",
        "Wildcards": "Wildcards",
        "Other": "Other",
    }

    def __init__(self, max_concurrent: int = 2):
        """
        Initialize download service.

        Args:
            max_concurrent: Maximum concurrent downloads.
        """
        self.max_concurrent = max_concurrent
        self._active_downloads: Dict[int, DownloadProgress] = {}
        self._executor: Optional[ThreadPoolExecutor] = None
        self._cancel_flags: Dict[int, bool] = {}
        self._tqdm_positions: Dict[int, int] = {}  # version_id -> tqdm position
        self._lock = threading.Lock()

    def _allocate_tqdm_position(self, version_id: int) -> int:
        """Allocate a tqdm position for stacked progress bars."""
        with self._lock:
            used_positions = set(self._tqdm_positions.values())
            # Find first available position
            pos = 0
            while pos in used_positions:
                pos += 1
            self._tqdm_positions[version_id] = pos
            return pos

    def _release_tqdm_position(self, version_id: int):
        """Release a tqdm position."""
        with self._lock:
            self._tqdm_positions.pop(version_id, None)

    def cancel(self, version_id: int):
        """Request cancellation of a download."""
        with self._lock:
            self._cancel_flags[version_id] = True

    def cancel_all(self):
        """Cancel all active downloads."""
        with self._lock:
            for version_id in self._active_downloads:
                self._cancel_flags[version_id] = True

    def _is_cancelled(self, version_id: int) -> bool:
        with self._lock:
            return self._cancel_flags.get(version_id, False)

    def get_progress(self, version_id: int) -> Optional[DownloadProgress]:
        """Get progress for a specific download."""
        with self._lock:
            return self._active_downloads.get(version_id)

    def get_all_progress(self) -> List[Dict[str, Any]]:
        """Get progress for all active downloads."""
        with self._lock:
            return [p.to_dict() for p in self._active_downloads.values()]

    def dismiss(self, version_id: Optional[int] = None) -> List[int]:
        """
        Forget finished downloads - one, or every one - so they are not
        handed to the page again. Every download was kept until the WebUI
        restarted, so one dismissed in the page came back with the next poll.
        One still running is kept, whatever is asked.

        Returns:
            The version ids forgotten.
        """
        with self._lock:
            gone = [vid for vid, progress in self._active_downloads.items()
                    if progress.is_complete and (version_id is None or vid == version_id)]
            for vid in gone:
                del self._active_downloads[vid]
        return gone

    def get_model_type_folder(self, model_type: str) -> Optional[str]:
        """Get WebUI folder name for a model type."""
        return self.MODEL_TYPE_FOLDERS.get(model_type, "Other")

    def get_base_path(self, model_type: str) -> str:
        """Get full base path for a model type."""
        from modules import shared, paths

        cmd_opts = shared.cmd_opts
        folder_name = self.get_model_type_folder(model_type)

        # Special case: TextualInversion goes to embeddings folder
        if model_type == "TextualInversion" or folder_name is None:
            return getattr(cmd_opts, 'embeddings_dir', os.path.join(paths.models_path, 'embeddings'))

        # Check for command-line overrides. Forge and Neo name these options
        # differently, so look up both - see MODEL_DIR_OPTIONS.
        from .scan_service import MODEL_DIR_OPTIONS, collect_cmd_dirs

        lookup_type = "LORA" if model_type in ("LORA", "LoCon", "DoRA") else model_type
        option_names = MODEL_DIR_OPTIONS.get(lookup_type)

        if option_names:
            # text encoders are scanned alongside VAEs but are not a download
            # target, so never resolve a download path to that directory
            option_names = tuple(n for n in option_names if n != "text_encoder_dirs")
            for directory in collect_cmd_dirs(cmd_opts, *option_names):
                if os.path.isdir(directory):
                    return directory

        # Default: models/<folder_name>
        return os.path.join(paths.models_path, folder_name)

    def apply_folder_template(
        self,
        template: str,
        model_data: Dict[str, Any],
        version_data: Dict[str, Any]
    ) -> str:
        """Apply folder template with placeholders."""
        if not template:
            return ""

        base_model = version_data.get("baseModel", "Unknown")
        model_name = model_data.get("name", "Unknown")
        creator = model_data.get("creator", {}).get("username", "Unknown") if model_data.get("creator") else "Unknown"
        model_id = str(model_data.get("id", 0))

        def sanitize(name: str) -> str:
            # Replace special characters and whitespace with underscore
            name = re.sub(r'[<>:"/\\|?*\s]+', '_', name)
            name = name.strip('._')
            return name[:100] if len(name) > 100 else name

        result = template
        result = result.replace("{baseModel}", sanitize(base_model))
        result = result.replace("{modelName}", sanitize(model_name))
        result = result.replace("{creator}", sanitize(creator))
        result = result.replace("{modelId}", model_id)

        # Normalize separators: convert all to forward slash, collapse multiples, strip edges
        result = result.replace("\\", "/")
        result = re.sub(r'/+', '/', result)
        result = result.strip('/')
        # Convert to OS-native path separators
        result = result.replace("/", os.sep)

        return result

    def _download_file(
        self,
        url: str,
        target_path: str,
        headers: Dict[str, str],
        progress: DownloadProgress
    ) -> bool:
        """Download file using requests with tqdm progress bar."""
        try:
            from tqdm import tqdm
        except ImportError:
            tqdm = None

        file_name = os.path.basename(target_path)
        max_retries = 3
        retry_delay = 3

        # Allocate tqdm position for stacked progress bars
        tqdm_pos = self._allocate_tqdm_position(progress.version_id)

        try:
            for attempt in range(max_retries):
                try:
                    session = requests.Session()
                    response = session.get(url, headers=headers, stream=True, timeout=60)
                    response.raise_for_status()

                    total_size = int(response.headers.get('content-length', 0))
                    progress.total_bytes = total_size

                    # Use 1MB chunks for better performance
                    chunk_size = 1024 * 1024

                    downloaded = 0
                    # Hashed as it arrives, where the network is the limit:
                    # afterwards, reading a 7 GB file again to hash it took
                    # 10 s, all of it spent waiting for the download to finish.
                    hasher = hashlib.sha256()

                    # Create tqdm progress bar for terminal (stacked)
                    if tqdm and total_size > 0:
                        pbar = tqdm(
                            total=total_size,
                            unit='B',
                            unit_scale=True,
                            unit_divisor=1024,
                            desc=file_name[:30],
                            ncols=80,
                            position=tqdm_pos,
                            leave=True
                        )
                    else:
                        pbar = None

                    try:
                        with open(target_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=chunk_size):
                                if self._is_cancelled(progress.version_id):
                                    if pbar:
                                        pbar.close()
                                    f.close()
                                    if os.path.exists(target_path):
                                        os.remove(target_path)
                                    progress.status = "cancelled"
                                    progress.error = "Download cancelled"
                                    return False

                                if chunk:
                                    f.write(chunk)
                                    hasher.update(chunk)
                                    downloaded += len(chunk)
                                    progress.downloaded_bytes = downloaded
                                    if pbar:
                                        pbar.update(len(chunk))

                        if pbar:
                            pbar.close()

                        # Verify file size
                        if total_size > 0 and downloaded != total_size:
                            raise Exception(f"Incomplete download: {downloaded}/{total_size} bytes")

                        progress.sha256 = hasher.hexdigest().upper()
                        return True

                    except Exception as e:
                        if pbar:
                            pbar.close()
                        raise e

                except requests.exceptions.HTTPError as e:
                    # Handle HTTP errors - don't retry on auth errors
                    status_code = e.response.status_code if e.response is not None else None
                    response_body = ""
                    try:
                        response_body = e.response.text if e.response is not None else ""
                    except Exception:
                        pass

                    print(f"[ModelManager] HTTP error {status_code}: {e}")
                    if response_body:
                        print(f"[ModelManager] Response body: {response_body}")

                    if os.path.exists(target_path):
                        os.remove(target_path)

                    if status_code == 401:
                        progress.status = "error"
                        progress.error = "Authentication required. Please add your Civitai API key in Settings > Model Manager."
                        return False
                    elif status_code == 403:
                        progress.status = "error"
                        progress.error = "Access denied. This model may require special permissions or a valid API key."
                        return False
                    else:
                        if attempt < max_retries - 1:
                            print(f"[ModelManager] Retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                        else:
                            progress.status = "error"
                            progress.error = f"Download failed (HTTP {status_code}): {e}"
                            return False

                except requests.exceptions.RequestException as e:
                    print(f"[ModelManager] Download attempt {attempt + 1} failed: {e}")
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    if attempt < max_retries - 1:
                        print(f"[ModelManager] Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                    else:
                        progress.status = "error"
                        progress.error = f"Download failed after {max_retries} attempts: {e}"
                        return False

                except Exception as e:
                    progress.status = "error"
                    progress.error = f"Download error: {e}"
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    return False

            return False

        finally:
            # Always release tqdm position
            self._release_tqdm_position(progress.version_id)

    @staticmethod
    def pick_file_index(
        files: List[Dict[str, Any]],
        file_index: Optional[int] = None,
        file_id: Optional[int] = None
    ) -> int:
        """
        Choose which of a version's files to download.

        files[0] is not the primary file for roughly one version in eleven -
        it is often the full fp32 weights, about twice the size of the pruned
        fp16 file most people want. So, in order of preference:

          - `file_id`, which the file picker sends. It survives the list being
            ordered differently between the search that drew the picker and the
            fetch that serves the download, which an index would not.
          - `file_index`, a position in this list.
          - whichever file Civitai marks primary.
        """
        if file_id is not None:
            for index, file_info in enumerate(files):
                if file_info.get("id") == file_id:
                    return index

        if file_index is not None and 0 <= file_index < len(files):
            return file_index

        for index, file_info in enumerate(files):
            if file_info.get("primary"):
                return index

        return 0

    def download_version(
        self,
        version_id: int,
        model_data: Dict[str, Any],
        version_data: Dict[str, Any],
        file_index: Optional[int] = None,
        file_id: Optional[int] = None
    ) -> DownloadProgress:
        """Download a model version from Civitai."""
        from modules import shared

        progress = DownloadProgress(version_id=version_id)
        progress.status = "downloading"
        partial_path = None

        with self._lock:
            self._active_downloads[version_id] = progress
            self._cancel_flags[version_id] = False

        try:
            # Refuse a version that has to be bought before creating anything:
            # its download URL answers 401/403 without a purchase, and
            # _download_file would burn three retries on a bare HTTP error.
            paid = paid_access_info(version_data)
            if paid:
                progress.status = "error"
                progress.error = (
                    "This version is permanently paid on Civitai - buy it there first"
                    if paid["permanent"] else
                    f"This version is in early access until {paid['ends_at']} - "
                    "buy it on Civitai or wait for it to go free"
                )
                return progress

            model_type = model_data.get("type", "Other")
            base_path = self.get_base_path(model_type)

            template = getattr(shared.opts, 'model_manager_civitai_folder_template', '_{baseModel}/{modelName}')
            subfolder = self.apply_folder_template(template, model_data, version_data)
            # Absolute, with no "..": the path a scan finds the file by, which
            # is how the library knows it is the same file.
            target_dir = os.path.abspath(os.path.join(base_path, subfolder) if subfolder else base_path)

            os.makedirs(target_dir, exist_ok=True)

            files = version_data.get("files", [])
            if not files:
                progress.status = "error"
                progress.error = "No files available for download"
                return progress

            file_info = files[self.pick_file_index(files, file_index, file_id)]
            file_name = file_info.get("name", f"model_{version_id}.safetensors")
            download_url = file_info.get("downloadUrl") or version_data.get("downloadUrl")

            if not download_url:
                progress.status = "error"
                progress.error = "No download URL available"
                return progress

            progress.file_name = file_name
            target_path = os.path.join(target_dir, file_name)

            # Civitai lists every hash the library keeps for a file. When the
            # bytes are the ones it hashed, its list is used rather than
            # reading the file again; when they are not, the file is corrupt.
            civitai_hashes = {k.lower(): v for k, v in (file_info.get("hashes") or {}).items() if v}
            expected = str(civitai_hashes.get("sha256") or "").upper()
            known = None
            if expected:
                known = {"hashes": HashResult.from_stored(civitai_hashes),
                         "version": version_data, "model": model_data}

            if os.path.exists(target_path):
                # Already there - downloaded before, and forgotten by a scan
                # that did not look in its folder, say. If it is the file
                # Civitai lists, it is added to the library, not fetched again.
                from .hashing import file_sha256
                progress.file_path = target_path
                if expected and (file_sha256(target_path) or "").upper() == expected:
                    print(f"[ModelManager] Already on disk, adding to the library: {target_path}")
                    info_path = os.path.splitext(target_path)[0] + ".civitai.info"
                    if not os.path.exists(info_path):
                        self._write_civitai_info(info_path, model_data, version_data, model_type)
                    progress.total_bytes = progress.downloaded_bytes = os.path.getsize(target_path)
                    progress.status = "finishing"
                    self._sync_downloaded_file(target_path, progress, known)
                    progress.synced = True
                    progress.status = "complete"
                    return progress
                progress.status = "error"
                progress.error = (
                    f"A different file named {file_name} is already in {target_dir}" if expected
                    else f"File already exists: {file_name}, and Civitai lists no SHA-256 to compare it with")
                return progress

            api_key = getattr(shared.opts, 'model_manager_civitai_api_key', '')

            headers = {"User-Agent": "SD-WebUI-Forge-Model-Manager/1.0"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            print(f"[ModelManager] Downloading: {file_name}")
            print(f"[ModelManager] Target: {target_dir}")

            # Written under another name until it is whole and verified, so a
            # download that fails never leaves a file under the model's own
            # name - one a scan would take for the model - and whatever the
            # download deletes is only ever its own .partial.
            partial_path = target_path + PARTIAL
            success = self._download_file(download_url, partial_path, headers, progress)

            if not success:
                return progress

            if expected and progress.sha256 != expected:
                os.remove(partial_path)
                progress.status = "error"
                progress.error = ("The downloaded file does not match Civitai's SHA-256, "
                                  "so it was removed. Try downloading it again.")
                return progress

            # Never over a file: one may have arrived under this name while
            # the download ran. (Windows' rename refuses one anyway.)
            if os.path.exists(target_path):
                os.remove(partial_path)
                progress.status = "error"
                progress.error = (f"A file named {file_name} appeared in {target_dir} while "
                                  "downloading, so the download was not put in its place")
                progress.file_path = target_path
                return progress
            os.rename(partial_path, target_path)
            partial_path = None

            # Create .civitai.info file
            info_path = os.path.splitext(target_path)[0] + ".civitai.info"
            self._write_civitai_info(info_path, model_data, version_data, model_type)

            print(f"[ModelManager] Downloaded: {target_path}")

            progress.file_path = target_path
            progress.status = "finishing"
            self._sync_downloaded_file(target_path, progress, known)
            progress.synced = True
            progress.status = "complete"
            print(f"[ModelManager] Download complete: {target_path}")

            return progress

        except Exception as e:
            import traceback
            print(f"[ModelManager] Download error: {e}")
            traceback.print_exc()
            progress.status = "error"
            progress.error = str(e)
            # Only ever this download's own unfinished file.
            if partial_path and os.path.exists(partial_path):
                os.remove(partial_path)
            return progress
        finally:
            with self._lock:
                self._cancel_flags.pop(version_id, None)
            # Every way a download fails sets the reason on its progress, for
            # the page; most never said it here too.
            if progress.status == "error":
                print(f"[ModelManager] Download of {progress.file_name or 'version %s' % version_id} "
                      f"failed: {progress.error}")

    @staticmethod
    def _write_civitai_info(info_path: str, model_data: Dict[str, Any], version_data: Dict[str, Any],
                            model_type: str) -> None:
        """The sidecar a scan reads: the model's payload, with this version."""
        civitai_info = {
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
        with open(info_path, 'w', encoding='utf-8') as f:
            json.dump(civitai_info, f, indent=2)

    def queue_download(
        self,
        version_id: int,
        model_data: Dict[str, Any],
        version_data: Dict[str, Any],
        file_index: Optional[int] = None,
        file_id: Optional[int] = None
    ) -> DownloadProgress:
        """Queue a download for parallel processing."""
        progress = DownloadProgress(version_id=version_id)
        files = version_data.get("files", [])
        progress.file_name = (
            files[self.pick_file_index(files, file_index, file_id)].get("name", "Unknown")
            if files else "Unknown"
        )

        with self._lock:
            self._active_downloads[version_id] = progress

        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.max_concurrent)

        self._executor.submit(
            self.download_version,
            version_id,
            model_data,
            version_data,
            file_index,
            file_id
        )

        return progress

    def _sync_downloaded_file(self, file_path: str, progress: Optional[DownloadProgress] = None,
                              known: Optional[Dict[str, Any]] = None):
        """
        Add a downloaded file to the library, before the download is complete.

        It ran in a background thread after the download said complete, and
        hashed the whole file again: the Civitai Browser showed a finished
        download without its "Show in MM" for as long as that took - 10 s for
        a 7 GB checkpoint. With what the download already knows (`known`: the
        file's hashes, its version and model), it is a second or so, and the
        download waits for it. A failure is recorded on the progress, never
        raised: the file is on disk either way.
        """
        try:
            from .sync_service import SyncService
            from .db import get_models_db
            result = SyncService().sync_model(file_path, force=True, known=known)
            if result.success:
                print(f"[ModelManager] Synced to database: {file_path}")
                try:
                    get_models_db().set_downloaded_at(file_path)
                except Exception as e:
                    print(f"[ModelManager] Failed to set downloaded_at: {e}")
            else:
                if progress is not None:
                    progress.sync_error = result.error
                print(f"[ModelManager] Sync warning: {result.error}")
        except Exception as e:
            if progress is not None:
                progress.sync_error = str(e)
            print(f"[ModelManager] Failed to sync downloaded file: {e}")

    def shutdown(self):
        """Shutdown the executor and cancel pending downloads."""
        self.cancel_all()
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None


# Global download service instance
_download_service: Optional[DownloadService] = None


def get_download_service() -> DownloadService:
    """Get or create download service instance."""
    global _download_service
    if _download_service is None:
        _download_service = DownloadService(max_concurrent=2)
    return _download_service
