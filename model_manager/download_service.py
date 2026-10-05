"""
Download service for Civitai Browser.
Handles downloading models from Civitai with progress tracking and parallel downloads.

The queue is the service's own. Downloads are listed in one order - the one
they were added in, which ↑/↓ change - and a state never moves one: up to
`max_concurrent` run, and when a place frees up, the first waiting one from
the top starts. A waiting download can be started at once (over the limit),
moved up or down, or cancelled before it starts. A running one can be
paused: it keeps its .partial, gives up its place, and resumes with an HTTP
Range request from where it stopped. What is running or paused is kept in the
database (schema_info, under a key for this install), so after a restart -
or a crash - it is there again, paused, to be resumed.
"""
import hashlib
import os
import re
import shutil
import json
import threading
import time
import requests
from collections import deque
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

from .civitai import api_key_from_settings, paid_access_info
from .civitai.ownership import owned_versions
from .forge_host import setting
from .hashing import HashResult
from .install import INSTALL_KEY
from .model_dirs import download_dir, filed_as, proper_place
from .storage import download_payload, get_metadata_paths, write_civitai_info
from .console import say


# What a download is written as until it is whole and verified: never a
# model file extension, so no scan takes it for a model.
PARTIAL = ".partial"

# The speed is the bytes of the last RATE_WINDOW seconds, so a slow chunk or
# a burst does not make it jump; nothing is said of it before a second's worth,
# and nothing arriving for the whole window is "stalled", not 0 B/s.
RATE_WINDOW = 5.0
RATE_SAMPLE_EVERY = 0.5
RATE_FIRST = 1.0
# How many times a resume asks for the rest before it takes the whole file.
RANGE_TRIES = 3

# Bound once: what the speed is measured by, whatever later replaces `time`.
_clock = time.monotonic

# Where this install keeps its downloads that can be resumed: under its own
# key (install.py), so a WebUI sharing the database never takes up another's.
RESUMABLE_KEY = "downloads:" + INSTALL_KEY


#: A download asked for and not yet over: asked for again, it is not started again.
ON_ITS_WAY = ("pending", "downloading", "finishing", "paused")


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
    # A resume the server answered with the whole file, not the rest of it:
    # the download started over.
    started_over: bool = False
    # The version's page on Civitai: where to go when Civitai refuses it.
    page_url: Optional[str] = None
    # Where the file went, when not where Civitai's type would put it: the
    # file, read once it arrived, is another type (see _file_by_what_it_is).
    filed: Optional[str] = None
    # (_clock(), downloaded_bytes) now and then, for the speed; and
    # when the bytes last grew. Measured here, where every chunk is seen: the
    # page sees only its polls, a second or more apart.
    _samples: deque = field(default_factory=deque, repr=False)
    _last_growth: Optional[float] = field(default=None, repr=False)

    def record(self, now: Optional[float] = None) -> None:
        """Note the bytes so far, for the speed: after every chunk, cheaply."""
        now = _clock() if now is None else now
        samples = self._samples
        if samples and self.downloaded_bytes > samples[-1][1]:
            self._last_growth = now
        elif not samples:
            self._last_growth = now
        if not samples or now - samples[-1][0] >= RATE_SAMPLE_EVERY:
            samples.append((now, self.downloaded_bytes))
        # One sample at or before the window's start is kept, as its baseline.
        while len(samples) > 1 and samples[1][0] <= now - RATE_WINDOW:
            samples.popleft()

    def restart_rate(self) -> None:
        """A new attempt starts from nothing: the speed is measured afresh."""
        self._samples.clear()
        self._last_growth = None

    def rate(self, now: Optional[float] = None) -> Tuple[Optional[float], Optional[float], bool]:
        """
        (bytes a second, seconds left, stalled) while downloading; the first
        two None when there is not yet a second's worth to go on, or no total.
        """
        if self.status != "downloading" or not self._samples:
            return None, None, False
        now = _clock() if now is None else now
        if self._last_growth is not None and now - self._last_growth >= RATE_WINDOW:
            return None, None, True
        base_time, base_bytes = self._samples[0]
        for sample in self._samples:
            if sample[0] <= now - RATE_WINDOW:
                base_time, base_bytes = sample
            else:
                break
        elapsed = now - base_time
        if elapsed < RATE_FIRST:
            return None, None, False
        speed = (self.downloaded_bytes - base_bytes) / elapsed
        if speed <= 0:
            return None, None, False
        left = (self.total_bytes - self.downloaded_bytes) / speed if self.total_bytes else None
        return speed, (max(0.0, left) if left is not None else None), False

    @property
    def percent(self) -> float:
        if self.total_bytes == 0:
            return 0
        return (self.downloaded_bytes / self.total_bytes) * 100

    @property
    def is_complete(self) -> bool:
        # paused is not: it is waiting to be resumed.
        return self.status in ("complete", "error", "cancelled")

    def to_dict(self) -> Dict[str, Any]:
        speed, left, stalled = self.rate()
        return {
            "speed_bps": round(speed) if speed else None,
            "eta_seconds": round(left) if left is not None else None,
            "stalled": stalled,
            "started_over": self.started_over,
            "page_url": self.page_url,
            "filed": self.filed,
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


def apply_folder_template(
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


class DownloadService:
    """
    Service for downloading models from Civitai.

    Features:
    - Streaming HTTP downloads with retries and terminal progress bars
    - Parallel download queue
    - Folder template processing
    - Automatic metadata file creation
    """

    # (get, set) for what can be resumed, instead of the database's.
    store = None

    def __init__(self, max_concurrent: int = 2):
        """
        Initialize download service.

        Args:
            max_concurrent: Maximum concurrent downloads.
        """
        self.max_concurrent = max_concurrent
        # Every download, in the list's order: the order they were added in,
        # which move() changes. The page shows them so, whatever their state.
        self._active_downloads: Dict[int, DownloadProgress] = {}
        # What each download needs to run: model_data, version_data (None
        # after a restart, until fetched again), file_index, file_id,
        # model_id, and partial_path once it has one.
        self._jobs: Dict[int, Dict[str, Any]] = {}
        self._running: set = set()
        self._threads: List[threading.Thread] = []
        self._cancel_flags: Dict[int, bool] = {}
        self._pause_flags: Dict[int, bool] = {}
        # (get, set) of the stored value: the database's, unless one is set
        # on the class - as the tests do, so none of them opens a database.
        self._store = DownloadService.store
        self._stored_any = False
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
        """
        Cancel a download: a running one stops at its next chunk; a waiting
        one never starts; a paused one is dropped, its .partial with it.
        """
        partial = None
        with self._lock:
            self._cancel_flags[version_id] = True
            progress = self._active_downloads.get(version_id)
            if progress and progress.status in ("pending", "paused") and version_id not in self._running:
                partial = (self._jobs.get(version_id) or {}).pop("partial_path", None)
                progress.status = "cancelled"
                progress.error = "Download cancelled"
        if partial and os.path.exists(partial):
            os.remove(partial)
        if partial:
            self._save()

    def cancel_all(self):
        """Cancel all active downloads."""
        with self._lock:
            ids = list(self._active_downloads)
        for version_id in ids:
            self.cancel(version_id)

    def _is_cancelled(self, version_id: int) -> bool:
        with self._lock:
            return self._cancel_flags.get(version_id, False)

    def _is_paused(self, version_id: int) -> bool:
        with self._lock:
            return self._pause_flags.get(version_id, False)

    # ------------------------------------------------------------ the queue
    def _waiting(self) -> List[int]:
        """The waiting downloads, top first: pending, and not yet started. Under the lock."""
        return [v for v, p in self._active_downloads.items() if p.status == "pending" and v not in self._running]

    def _pump(self) -> None:
        """Start waiting downloads, from the top, while fewer than the limit run."""
        starting = []
        with self._lock:
            for version_id in self._waiting():
                if len(self._running) >= self.max_concurrent:
                    break
                self._running.add(version_id)
                starting.append(version_id)
        for version_id in starting:
            self._start_thread(version_id)

    def _start_thread(self, version_id: int) -> None:
        thread = threading.Thread(target=self._run, args=(version_id,), daemon=True,
                                  name=f"model-manager-download-{version_id}")
        self._threads.append(thread)
        thread.start()

    def _run(self, version_id: int) -> None:
        """One download, on its own thread; then the next in the queue."""
        try:
            job = self._jobs.get(version_id) or {}
            if job.get("version_data") is None:
                self._fetch_job(version_id, job)
            if job.get("version_data") is None:
                return
            self.download_version(version_id, job["model_data"], job["version_data"],
                                  job.get("file_index"), job.get("file_id"),
                                  resume=job.pop("resume", False))
        except Exception as e:
            progress = self._active_downloads.get(version_id)
            if progress:
                progress.status = "error"
                progress.error = f"Download error: {e}"
            say(f"Download of version {version_id} failed: {e}")
        finally:
            with self._lock:
                self._running.discard(version_id)
            self._pump()

    def _fetch_job(self, version_id: int, job: Dict[str, Any]) -> None:
        """A download remembered across a restart knows its ids only: ask Civitai again."""
        progress = self._active_downloads.get(version_id)
        try:
            from .civitai import CivitaiClient
            client = CivitaiClient.from_settings()
            try:
                model_data = client.get_model(job.get("model_id")) if job.get("model_id") else None
            finally:
                client.close()
            version_data = next((v for v in (model_data or {}).get("modelVersions", [])
                                 if v.get("id") == version_id), None)
            if not version_data:
                raise ValueError("Civitai no longer lists this version")
            job.update(model_data=model_data, version_data=version_data)
        except Exception as e:
            if progress:
                progress.status = "error"
                progress.error = f"Could not resume: {e}"

    def start_now(self, version_id: int) -> bool:
        """A waiting download, started at once - over the limit, which only paces the queue."""
        with self._lock:
            if version_id not in self._waiting():
                return False
            self._running.add(version_id)
        self._start_thread(version_id)
        return True

    def move(self, version_id: int, by: int) -> bool:
        """
        A waiting download, up (-1) or down (+1) the queue: it changes places
        in the list with the nearest waiting one that way, so its place in
        the queue always changes by one, whatever runs between them.
        """
        with self._lock:
            waiting = self._waiting()
            if version_id not in waiting:
                return False
            at = waiting.index(version_id) + by
            if not 0 <= at < len(waiting):
                return False
            other = waiting[at]
            order = list(self._active_downloads)
            i, j = order.index(version_id), order.index(other)
            order[i], order[j] = order[j], order[i]
            self._active_downloads = {v: self._active_downloads[v] for v in order}
            return True

    def pause(self, version_id: int) -> bool:
        """
        Pause a download. A running one stops at its next chunk, keeps its
        .partial and gives up its place; a waiting one leaves the queue.
        """
        with self._lock:
            progress = self._active_downloads.get(version_id)
            if not progress:
                return False
            if progress.status == "downloading":
                self._pause_flags[version_id] = True
                return True
            if progress.status == "pending" and version_id not in self._running:
                progress.status = "paused"
                return True
            return False

    def resume(self, version_id: int) -> bool:
        """
        A paused download, waiting again where it is in the list: running at
        once if there is room - a free place means nothing else is waiting.
        """
        with self._lock:
            resumed = self._requeue([version_id])
        self._pump()
        return bool(resumed)

    def _requeue(self, version_ids: List[int]) -> List[int]:
        """These paused downloads, pending again, where they are in the list. Under the lock."""
        resumed = []
        for version_id in version_ids:
            progress = self._active_downloads.get(version_id)
            if not progress or progress.status != "paused":
                continue
            progress.status = "pending"
            progress.error = None
            self._pause_flags[version_id] = False
            self._jobs.setdefault(version_id, {})["resume"] = True
            resumed.append(version_id)
        return resumed

    def pause_all(self) -> None:
        """Every running download paused, and every waiting one held, so none starts in their place."""
        with self._lock:
            waiting = [v for v, p in self._active_downloads.items() if p.status == "pending"]
            running = [v for v, p in self._active_downloads.items() if p.status == "downloading"]
        for version_id in waiting + running:
            self.pause(version_id)

    def resume_all(self) -> None:
        """
        Every paused download, the top ones running first - all made waiting,
        then started: resumed one by one, each started as it came, and the
        last listed ran first.
        """
        with self._lock:
            self._requeue([v for v, p in self._active_downloads.items() if p.status == "paused"])
        self._pump()

    def wait(self, timeout: float = 10.0) -> None:
        """Until every download thread has ended: for tests."""
        deadline = _clock() + timeout
        while _clock() < deadline:
            alive = [t for t in list(self._threads) if t.is_alive()]
            if not alive:
                return
            alive[0].join(timeout=max(0.0, deadline - _clock()))

    # ------------------------------------------------------ across restarts
    def _stored(self):
        if self._store is None:
            from .db import get_models_db
            db = get_models_db()
            self._store = (lambda: db.get_info(RESUMABLE_KEY), lambda value: db.set_info(RESUMABLE_KEY, value))
        return self._store

    def _save(self) -> None:
        """What can be resumed after a restart: every download with a .partial, running or paused."""
        with self._lock:
            entries = []
            for version_id, progress in self._active_downloads.items():
                job = self._jobs.get(version_id) or {}
                if job.get("partial_path") and progress.status in ("downloading", "paused", "pending"):
                    entries.append({"version_id": version_id, "model_id": job.get("model_id"),
                                    "file_id": job.get("file_id"), "file_index": job.get("file_index"),
                                    "file_name": progress.file_name, "partial_path": job["partial_path"],
                                    "total_bytes": progress.total_bytes})
        # Nothing to keep, and nothing kept before: the database is not touched.
        if not entries and not self._stored_any:
            return
        try:
            self._stored()[1](json.dumps(entries) if entries else None)
            self._stored_any = bool(entries)
        except Exception as e:
            say(f"Could not keep the downloads to resume: {e}")

    def restore(self) -> None:
        """
        After a restart, the downloads that were running or paused, paused -
        a running one included: its thread died with the WebUI, its .partial
        did not. One whose .partial is gone is forgotten.
        """
        try:
            entries = json.loads(self._stored()[0]() or "[]")
        except Exception as e:
            say(f"Could not read the downloads to resume: {e}")
            return
        self._stored_any = bool(entries)
        with self._lock:
            for entry in entries:
                partial = entry.get("partial_path")
                version_id = entry.get("version_id")
                if not partial or version_id is None or not os.path.exists(partial):
                    continue
                self._active_downloads[version_id] = DownloadProgress(
                    version_id=version_id, file_name=entry.get("file_name") or "",
                    total_bytes=entry.get("total_bytes") or 0,
                    downloaded_bytes=os.path.getsize(partial), status="paused")
                self._jobs[version_id] = {"model_id": entry.get("model_id"), "file_id": entry.get("file_id"),
                                          "file_index": entry.get("file_index"), "model_data": None,
                                          "version_data": None, "partial_path": partial}
        self._save()

    def get_progress(self, version_id: int) -> Optional[DownloadProgress]:
        """Get progress for a specific download."""
        with self._lock:
            return self._active_downloads.get(version_id)

    def get_all_progress(self) -> List[Dict[str, Any]]:
        """
        Every download, in the list's order: a waiting one with its place in
        the queue, from 1.
        """
        with self._lock:
            waiting = self._waiting()
            out = []
            for version_id, progress in self._active_downloads.items():
                entry = progress.to_dict()
                if version_id in waiting:
                    entry["queue_position"] = waiting.index(version_id) + 1
                out.append(entry)
            return out

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

    @staticmethod
    def _file_by_what_it_is(path: str, progress: DownloadProgress) -> str:
        """
        Where a finished download belongs, by what the file is.

        The folder was chosen before the file existed, from Civitai's type,
        which is the uploader's: a VAE or a text encoder shared as a
        "Checkpoint" landed in Stable-diffusion, where Forge offers it as a
        checkpoint. Its header says what it is; a file of another type goes
        to that type's folder, keeping its subfolders. Never over a file:
        the same file already there is kept and this copy - made moments
        ago - removed; a different one leaves this where it landed.

        Returns where the file is now.
        """
        try:
            from .file_identity import identify
            found = identify(path)
            file_type = found.file_type
        except Exception as e:
            say(f"Could not read what {os.path.basename(path)} is: {e}")
            return path
        to = proper_place(path, filed_as(file_type, found.model_class))
        if not to:
            return path
        if os.path.exists(to):
            from .hashing import file_sha256
            mine = progress.sha256 or file_sha256(path) or ""
            if mine and (file_sha256(to) or "").upper() == mine.upper():
                os.remove(path)
                progress.filed = f"Already in {os.path.dirname(to)}, where a {file_type} goes"
                return to
            progress.filed = (f"Left in {os.path.dirname(path)}: it is a {file_type}, and "
                              f"{os.path.dirname(to)} has a different file named {os.path.basename(to)}")
            return path
        os.makedirs(os.path.dirname(to), exist_ok=True)
        shutil.move(path, to)
        progress.filed = f"Filed in {os.path.dirname(to)}: the file is a {file_type}"
        say(f"{progress.filed}")
        return to

    def get_base_path(self, model_type: str) -> str:
        """The folder a download of this Civitai type is filed under - see model_dirs."""
        return download_dir(model_type)

    def _download_file(
        self,
        url: str,
        target_path: str,
        headers: Dict[str, str],
        progress: DownloadProgress,
        resume_from: int = 0
    ) -> bool:
        """
        Download file using requests with tqdm progress bar - from
        `resume_from` bytes in, when resuming: the rest is asked for with a
        Range request and added to the file. A server that sends the whole
        file instead is taken from the start. A pause stops at the next chunk
        and keeps the file (status "paused"); False is returned, as for any
        download that did not finish.
        """
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
                    # Only the first attempt resumes: a retry starts over, as before.
                    offset = resume_from if attempt == 0 and os.path.exists(target_path) else 0
                    asked = dict(headers)
                    if offset:
                        asked["Range"] = f"bytes={offset}-"
                    session = requests.Session()
                    # Civitai's storage now and then sends the whole file
                    # for a range - with an API key, 1 of 8 resumes in one
                    # measurement - and a fresh request, through a fresh
                    # redirect, is answered: asked again before starting over.
                    tries = RANGE_TRIES if offset else 1
                    for tried in range(1, tries + 1):
                        response = session.get(url, headers=asked, stream=True, timeout=60)
                        response.raise_for_status()
                        if not offset or getattr(response, "status_code", 200) == 206 or tried == tries:
                            break
                        say(f"The server sent the whole of {file_name}, not the rest: asking again")
                        if hasattr(response, "close"):
                            response.close()
                    if offset and getattr(response, "status_code", 200) != 206:
                        say(f"The server sent the whole file, not the rest: starting {file_name} over")
                        offset = 0
                        progress.started_over = True

                    length = int(response.headers.get('content-length', 0))
                    total_size = length + offset if length else 0
                    progress.total_bytes = total_size

                    # Use 1MB chunks for better performance
                    chunk_size = 1024 * 1024

                    downloaded = offset
                    # A retry starts from nothing: its bytes, and its speed,
                    # measured from now - so no data at all is stalled too.
                    progress.downloaded_bytes = offset
                    progress.restart_rate()
                    progress.record()
                    # Hashed as it arrives, where the network is the limit:
                    # afterwards, reading a 7 GB file again to hash it took
                    # 10 s, all of it spent waiting for the download to finish.
                    # Resumed, what is already there is read once to begin with.
                    hasher = hashlib.sha256()
                    if offset:
                        with open(target_path, 'rb') as done_part:
                            for block in iter(lambda: done_part.read(4 * 1024 * 1024), b''):
                                hasher.update(block)

                    # Create tqdm progress bar for terminal (stacked)
                    if tqdm and total_size > 0:
                        pbar = tqdm(
                            total=total_size,
                            initial=offset,
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
                        with open(target_path, 'ab' if offset else 'wb') as f:
                            for chunk in response.iter_content(chunk_size=chunk_size):
                                if self._is_paused(progress.version_id):
                                    # Kept, to be resumed from: nothing removed.
                                    if pbar:
                                        pbar.close()
                                    progress.status = "paused"
                                    return False
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
                                    progress.record()
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

                    say(f"HTTP error {status_code}: {e}")
                    if response_body:
                        say(f"Response body: {response_body}")

                    if os.path.exists(target_path):
                        os.remove(target_path)

                    if status_code == 401:
                        progress.status = "error"
                        progress.error = ("Civitai asks for an API key for this download. Add one in the settings "
                                          "(\u2699 at the top right of the Model Manager or Civitai Browser tab), "
                                          "under Civitai connection.")
                        return False
                    elif status_code == 403:
                        # Civitai says why, in JSON - "Early Access", say.
                        reason = ""
                        try:
                            reason = (json.loads(response_body) or {}).get("message") or ""
                        except (ValueError, AttributeError):
                            pass
                        progress.status = "error"
                        progress.error = (f"Civitai refused the download: {reason}" if reason else
                                          "Access denied. This model may require special permissions or a valid API key.")
                        return False
                    else:
                        if attempt < max_retries - 1:
                            say(f"Retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                        else:
                            progress.status = "error"
                            progress.error = f"Download failed (HTTP {status_code}): {e}"
                            return False

                except requests.exceptions.RequestException as e:
                    say(f"Download attempt {attempt + 1} failed: {e}")
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    if attempt < max_retries - 1:
                        say(f"Retrying in {retry_delay}s...")
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

    def download_version(
        self,
        version_id: int,
        model_data: Dict[str, Any],
        version_data: Dict[str, Any],
        file_index: Optional[int] = None,
        file_id: Optional[int] = None,
        resume: bool = False
    ) -> DownloadProgress:
        """
        Download a model version from Civitai - with `resume`, carrying on
        from its .partial where there is one.
        """
        partial_path = None
        with self._lock:
            # The progress the queue made, or a paused one being resumed, is
            # the one the page follows; anything else starts afresh.
            progress = self._active_downloads.get(version_id)
            if progress is None or progress.status not in ("pending", "paused"):
                progress = DownloadProgress(version_id=version_id)
                self._active_downloads[version_id] = progress
            progress.status = "downloading"
            progress.error = None
            self._cancel_flags[version_id] = False
            self._pause_flags[version_id] = False
            job = self._jobs.setdefault(version_id, {})
            job.setdefault("model_id", (model_data or {}).get("id"))
            job.setdefault("file_index", file_index)
            job.setdefault("file_id", file_id)

        try:
            model_id = (model_data or {}).get("id")
            if model_id:
                progress.page_url = f"https://civitai.com/models/{model_id}?modelVersionId={version_id}"
            # A paid version downloads when the API key's account bought it.
            # One it did not is refused before anything is created: its
            # download answers 403, and _download_file would burn three
            # retries on it. Unknown - Civitai not asked - it is tried.
            paid = paid_access_info(version_data)
            if paid:
                if not api_key_from_settings():
                    progress.status = "error"
                    progress.error = ("This version is paid on Civitai. With an API key set (the settings, "
                                      "Civitai connection), a version you have bought downloads here.")
                    return progress
                bought = (owned_versions([version_id]) or {}).get(version_id)
                if bought is False:
                    progress.status = "error"
                    progress.error = (
                        ("This version is paid on Civitai" if paid["permanent"] else
                         f"This version is in early access until {paid['ends_at']}")
                        + ", and Civitai says your account has not bought it. Just bought it? Civitai's API "
                        "takes some minutes to know: try again shortly. Otherwise, buy it on its page.")
                    return progress

            model_type = model_data.get("type", "Other")
            base_path = self.get_base_path(model_type)

            template = setting('model_manager_civitai_folder_template')
            subfolder = apply_folder_template(template, model_data, version_data)
            # Absolute, with no "..": the path a scan finds the file by, which
            # is how the library knows it is the same file.
            target_dir = os.path.abspath(os.path.join(base_path, subfolder) if subfolder else base_path)

            os.makedirs(target_dir, exist_ok=True)

            files = version_data.get("files", [])
            if not files:
                progress.status = "error"
                progress.error = "No files available for download"
                return progress

            file_info = files[pick_file_index(files, file_index, file_id)]
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
                    say(f"Already on disk, adding to the library: {target_path}")
                    if not os.path.exists(get_metadata_paths(target_path)[0]):
                        write_civitai_info(target_path, download_payload(model_data, version_data, model_type))
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

            api_key = api_key_from_settings()

            headers = {"User-Agent": "SD-WebUI-Forge-Model-Manager/1.0"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            say(f"Downloading: {file_name}")
            say(f"Target: {target_dir}")

            # Written under another name until it is whole and verified, so a
            # download that fails never leaves a file under the model's own
            # name - one a scan would take for the model - and whatever the
            # download deletes is only ever its own .partial.
            partial_path = target_path + PARTIAL
            resume_from = os.path.getsize(partial_path) if resume and os.path.exists(partial_path) else 0
            # Kept in the database while it runs, so a restart - or a crash -
            # leaves it paused, to be resumed, rather than a stray .partial.
            job["partial_path"] = partial_path
            self._save()
            success = self._download_file(download_url, partial_path, headers, progress, resume_from)

            if not success:
                if progress.status == "paused":
                    partial_path = None          # kept, to resume from
                    self._save()
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
            target_path = self._file_by_what_it_is(target_path, progress)

            write_civitai_info(target_path, download_payload(model_data, version_data, model_type))

            say(f"Downloaded: {target_path}")

            progress.file_path = target_path
            progress.status = "finishing"
            self._sync_downloaded_file(target_path, progress, known)
            progress.synced = True
            progress.status = "complete"
            say(f"Download complete: {target_path}")

            return progress

        except Exception as e:
            import traceback
            say(f"Download error: {e}")
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
                self._pause_flags.pop(version_id, None)
                ended = progress.status in ("complete", "error", "cancelled")
                if ended:
                    self._jobs.get(version_id, {}).pop("partial_path", None)
            if ended:
                self._save()
            # Every way a download fails sets the reason on its progress, for
            # the page; most never said it here too.
            if progress.status == "error":
                say(f"Download of {progress.file_name or 'version %s' % version_id} "
                      f"failed: {progress.error}")

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
            files[pick_file_index(files, file_index, file_id)].get("name", "Unknown")
            if files else "Unknown"
        )

        with self._lock:
            # One on its way is answered as it is: dropping its row and
            # queuing it afresh started a running download over - asked for
            # again by the Resources dialog for one the Civitai Browser
            # started, say, or for a gone version whose newest was coming
            # already (#119). A finished one is queued afresh, at the end of
            # the list: its file may be gone since.
            current = self._active_downloads.get(version_id)
            if current is not None and current.status in ON_ITS_WAY:
                return current
            self._active_downloads.pop(version_id, None)
            self._active_downloads[version_id] = progress
            self._cancel_flags[version_id] = False
            self._jobs[version_id] = {"model_data": model_data, "version_data": version_data,
                                      "file_index": file_index, "file_id": file_id,
                                      "model_id": (model_data or {}).get("id")}
        self._pump()
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
                say(f"Synced to database: {file_path}")
                try:
                    get_models_db().set_downloaded_at(file_path)
                except Exception as e:
                    say(f"Failed to set downloaded_at: {e}")
            else:
                if progress is not None:
                    progress.sync_error = result.error
                say(f"Sync warning: {result.error}")
        except Exception as e:
            if progress is not None:
                progress.sync_error = str(e)
            say(f"Failed to sync downloaded file: {e}")


# Global download service instance
_download_service: Optional[DownloadService] = None
_download_service_lock = threading.Lock()


def get_download_service() -> DownloadService:
    """
    The one download service, made at the first ask. Made under a lock: the
    page's first poll and a Download, on two threads at once, each made one,
    and the queue that was not kept went unwatched. Handed out only once it
    has restored what was running or paused when the WebUI last stopped.
    """
    global _download_service
    with _download_service_lock:
        if _download_service is None:
            service = DownloadService(max_concurrent=2)
            service.restore()
            _download_service = service
    return _download_service
