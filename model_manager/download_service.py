"""
Download service for Civitai Browser.
Handles downloading models from Civitai with progress tracking and parallel downloads.

The queue is the service's own. Downloads are listed in one order - the one
they were added in, which ↑/↓ change - and a state never moves one: up to
`max_concurrent` run, and when a place frees up, the first waiting one from
the top starts. A waiting download can be started at once (over the limit),
moved up or down, or cancelled before it starts. A running one can be
paused: it keeps its .partial, gives up its place, and resumes with an HTTP
Range request from where it stopped. What is not over - running, paused or
waiting - is kept in the database (the downloads table, under this install's
key), so after a restart - or a crash - it is there again, paused, to be
resumed; one whose file the library has by then is not (#187).

A download is one file, and is found by its Civitai file id (#374): two
files of one version are two downloads, and one file listed under several
versions - Civitai's shared VAEs - is one. A download whose file is not
named yet - kept by an older version before the file was known - goes by a
stand-in, its version id negated, until its turn names the file (`stand_in`).
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
from .forge_host import DEFAULTS, setting
from .hashing import HashResult
from .install import INSTALL_KEY
from .model_dirs import download_dir, filed_as, held_here, loads_here, proper_place
from .storage import download_payload, get_metadata_paths, write_civitai_info
from .console import say, say_failure


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
# A part of a file fetched over a connection of its own (#282) is at least
# this big: a 40 MB LoRA keeps one connection, a 100 MB one gets three.
# Civitai's storage holds each connection to about 60 MB/s, so a part this
# size takes half a second, and a new connection's setup is a small share.
PART_MIN = 32 * 1024 * 1024
# How many times a part asks again - from its own size - before the download
# pauses, saying why.
PART_TRIES = 3

# Bound once: what the speed is measured by, whatever later replaces `time`.
_clock = time.monotonic
# The waits between tries of a finished download's rename (#390), 7.5 s in
# all: an antivirus scan or the search indexer holding the new file lets go
# within seconds, and the download then finishes by itself. A module name,
# as _clock is, so the suite runs the tries without waiting.
RENAME_WAITS = (0.5, 1, 2, 4)
_wait = time.sleep

#: A download asked for and not yet over: asked for again, it is not started again.
ON_ITS_WAY = ("pending", "downloading", "finishing", "paused")

_ADD_A_KEY = ("Add one in the settings (⚙ at the top right of the Model Manager or Civitai Browser tab), "
              "under Civitai account.")


def _civitai_message(body: str) -> str:
    """Why Civitai refused a download: the "message" of its JSON answer, or ''."""
    try:
        return (json.loads(body) or {}).get("message") or ""
    except (ValueError, AttributeError):
        return ""


def _refused_401(reason: str, key_set: bool) -> str:
    """
    What a 401 from Civitai's download says (#224). It sends one for a login
    the creator asks for - only to a request without a session, so a key is
    what helps - and for a version whose creator turned downloads off, which
    no key changes. Both said a key was missing until Civitai's words were read.
    """
    if not reason:
        return ("Civitai asks for an API key for this download. " + _ADD_A_KEY if not key_set else
                "Civitai refused the download (HTTP 401) without saying why.")
    said = f"Civitai refused the download: {reason}"
    if key_set or "logged in" not in reason.lower():
        return said
    return f"{said}{'' if said.endswith(('.', '!', '?')) else '.'} An API key logs you in. {_ADD_A_KEY}"


def _refused_403(reason: str) -> str:
    """What a 403 from Civitai's download says: its words - "Early Access", say - when it gives them."""
    return (f"Civitai refused the download: {reason}" if reason else
            "Access denied. This model may require special permissions or a valid API key.")


def _part_path(partial_path: str, index: int) -> str:
    """Where part `index` (from 0) of a download in parts is written: the first is the .partial itself."""
    return partial_path if index == 0 else f"{partial_path}.{index + 1}"


def _part_numbers(partial_path: str) -> List[int]:
    """The numbers of the part files beside a .partial (2, 3, ...), in order."""
    folder, name = os.path.split(partial_path)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    pattern = re.compile(re.escape(name) + r"\.(\d+)")
    return sorted(int(m.group(1)) for m in (pattern.fullmatch(n) for n in names) if m)


def _part_count(partial_path: str) -> int:
    """
    How many parts a kept download was split into, read from its files: 0
    with no .partial, 1 for one connection, N for a .partial with parts 2 to
    N beside it. -1 when the numbers have a gap: a join cut short by a
    restart, its parts no longer adding up.
    """
    if not os.path.exists(partial_path):
        return 0
    numbers = _part_numbers(partial_path)
    if not numbers:
        return 1
    return numbers[-1] if numbers == list(range(2, numbers[-1] + 1)) else -1


def _partial_bytes(partial_path: str) -> int:
    """How far a kept download got: its .partial and every part beside it."""
    paths = [partial_path] + [f"{partial_path}.{n}" for n in _part_numbers(partial_path)]
    return sum(os.path.getsize(p) for p in paths if os.path.exists(p))


def _remove_partial(partial_path: str) -> None:
    """A download's unfinished files - its .partial and the parts beside it (#282): only ever its own."""
    for path in [partial_path] + [f"{partial_path}.{n}" for n in _part_numbers(partial_path)]:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            say(f"Could not remove {path}: {e}")


def _same_path(path: str) -> str:
    """A path as Windows tells two apart: case ignored, ".." resolved. Short names and junctions are not."""
    return os.path.normcase(os.path.abspath(path))


def _remove_parts(partial_path: str) -> None:
    """
    The part files beside a .partial, not the .partial itself: strays a join
    could not remove (#390), which a later resume would read as its split.
    """
    for path in [f"{partial_path}.{n}" for n in _part_numbers(partial_path)]:
        try:
            os.remove(path)
        except OSError as e:
            say(f"Could not remove {path}: {e}")


def _range_total(content_range: str) -> int:
    """The file's whole size from a 206's Content-Range ("bytes 0-99/1000"); 0 when it does not say."""
    try:
        return int(content_range.rsplit("/", 1)[1])
    except (IndexError, ValueError):
        return 0


def _split(total: int, parts: int) -> List[Tuple[int, int]]:
    """The first and last byte of each part: equal, from the file's exact size alone, so a resume finds the same."""
    return [(i * total // parts, (i + 1) * total // parts - 1) for i in range(parts)]


@dataclass
class DownloadProgress:
    """Track download progress."""
    version_id: int
    # What the download is found by: the Civitai file's id, or a stand-in
    # until its turn names it (stand_in).
    file_id: Optional[int] = None
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
    # A file in parts records from every part's thread (#282), and the page's
    # poll reads the samples meanwhile.
    _lock: Any = field(default_factory=threading.RLock, repr=False, compare=False)

    def record(self, now: Optional[float] = None) -> None:
        """Note the bytes so far, for the speed: after every chunk, cheaply."""
        with self._lock:
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

    def add(self, count: int) -> None:
        """Bytes one part brought (#282): added and recorded as one step."""
        with self._lock:
            self.downloaded_bytes += count
            self.record()

    def restart_rate(self) -> None:
        """A new attempt starts from nothing: the speed is measured afresh."""
        with self._lock:
            self._samples.clear()
            self._last_growth = None

    def rate(self, now: Optional[float] = None) -> Tuple[Optional[float], Optional[float], bool]:
        """
        (bytes a second, seconds left, stalled) while downloading; the first
        two None when there is not yet a second's worth to go on, or no total.
        """
        with self._lock:
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
            downloaded = self.downloaded_bytes
        if elapsed < RATE_FIRST:
            return None, None, False
        speed = (downloaded - base_bytes) / elapsed
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
            "file_id": self.file_id,
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


def template_folders(
    path: str,
    root: Optional[str],
    model: Optional[Dict[str, Any]],
    version: Optional[Dict[str, Any]],
    template: str
) -> List[str]:
    """
    The folders a download of this file made under its type's folder `root`,
    by the folder template as it is now, deepest first: what a delete may
    remove once they are empty (#196). The model and version are the stored
    rows, filled in as a download fills them from Civitai's. None when the
    template is empty, the file has no model, or the file is not where the
    template puts it - the template or the model's name changed since, or the
    folders are someone else's: then they are not known to be ours.
    """
    if not (template and root and model):
        return []
    model_data: Dict[str, Any] = {"id": model.get("id") or 0}
    if model.get("name"):
        model_data["name"] = model["name"]
    if model.get("creator_username"):
        model_data["creator"] = {"username": model["creator_username"]}
    base_model = (version or {}).get("base_model")
    subfolder = apply_folder_template(template, model_data, {"baseModel": base_model} if base_model else {})
    levels = subfolder.split(os.sep) if subfolder else []
    if not levels or any(level in ("", ".", "..") for level in levels):
        return []
    folder = os.path.dirname(os.path.abspath(path))
    if os.path.normcase(folder) != os.path.normcase(os.path.join(os.path.abspath(root), subfolder)):
        return []
    made = []
    for _ in levels:
        made.append(folder)
        folder = os.path.dirname(folder)
    return made


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


def stand_in(version_id: int) -> int:
    """
    What a download whose file is not named yet is found by: its version id,
    negated - never a Civitai file id. Only a download kept before #374 with
    no file id, whose version's files the library had no list of, has one.
    """
    return -abs(int(version_id))


def download_key(version_id: int, version_data: Optional[Dict[str, Any]],
                 file_index: Optional[int] = None, file_id: Optional[int] = None) -> int:
    """
    What a download of this version is found by: the file asked for, else the
    one pick_file_index takes from the version's files, else a stand-in.
    """
    if file_id is not None:
        return file_id
    files = (version_data or {}).get("files") or []
    if files:
        chosen = files[pick_file_index(files, file_index, file_id)].get("id")
        if chosen is not None:
            return chosen
    return stand_in(version_id)


class DownloadService:
    """
    Service for downloading models from Civitai.

    Features:
    - Streaming HTTP downloads with retries and terminal progress bars
    - Parallel download queue
    - Folder template processing
    - Automatic metadata file creation
    """

    # (read, write) of the downloads kept across a restart, and the
    # library's files of a download, instead of the database's.
    store = None
    library = None

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
        # (read, write) of the kept rows, and the library's files of a
        # download: the database's, unless set on the class - as the tests
        # do, so none of them opens a database.
        self._store = DownloadService.store
        self._library = DownloadService.library
        self._stored_any = False
        # A save's snapshot and its write, as one step: two threads saving
        # could otherwise write theirs out of order. Never taken under _lock.
        self._save_lock = threading.Lock()
        self._tqdm_positions: Dict[int, int] = {}  # version_id -> tqdm position
        self._lock = threading.Lock()

    def _allocate_tqdm_position(self, key: int) -> int:
        """Allocate a tqdm position for stacked progress bars."""
        with self._lock:
            used_positions = set(self._tqdm_positions.values())
            # Find first available position
            pos = 0
            while pos in used_positions:
                pos += 1
            self._tqdm_positions[key] = pos
            return pos

    def _release_tqdm_position(self, key: int):
        """Release a tqdm position."""
        with self._lock:
            self._tqdm_positions.pop(key, None)

    def cancel(self, key: int):
        """
        Cancel a download: a running one stops at its next chunk; a waiting
        one never starts; a paused one is dropped, its .partial with it.
        """
        partial = None
        dropped = False
        with self._lock:
            self._cancel_flags[key] = True
            progress = self._active_downloads.get(key)
            if progress and progress.status in ("pending", "paused") and key not in self._running:
                partial = (self._jobs.get(key) or {}).pop("partial_path", None)
                progress.status = "cancelled"
                progress.error = "Download cancelled"
                dropped = True
        if partial:
            _remove_partial(partial)
        if dropped:
            self._save()

    def cancel_all(self):
        """Cancel all active downloads."""
        with self._lock:
            keys = list(self._active_downloads)
        for key in keys:
            self.cancel(key)

    def _is_cancelled(self, key: int) -> bool:
        with self._lock:
            return self._cancel_flags.get(key, False)

    def _is_paused(self, key: int) -> bool:
        with self._lock:
            return self._pause_flags.get(key, False)

    # ------------------------------------------------------------ the queue
    def _waiting(self) -> List[int]:
        """The waiting downloads, top first: pending, and not yet started. Under the lock."""
        return [k for k, p in self._active_downloads.items() if p.status == "pending" and k not in self._running]

    def _pump(self) -> None:
        """Start waiting downloads, from the top, while fewer than the limit run."""
        starting = []
        with self._lock:
            for key in self._waiting():
                if len(self._running) >= self.max_concurrent:
                    break
                self._running.add(key)
                starting.append(key)
        for key in starting:
            self._start_thread(key)

    def _start_thread(self, key: int) -> None:
        thread = threading.Thread(target=self._run, args=(key,), daemon=True,
                                  name=f"model-manager-download-{key}")
        self._threads.append(thread)
        thread.start()

    def _run(self, key: int) -> None:
        """One download, on its own thread; then the next in the queue."""
        try:
            job = self._jobs.get(key) or {}
            # Resumed, it may have arrived meanwhile - since a restart, by
            # hand, in the other WebUI: then nothing is fetched (#187).
            if job.get("resume") and self._already_here(key, job):
                return
            if job.get("version_data") is None:
                key = self._fetch_job(key, job)
                if job.get("version_data") is not None and self._is_cancelled(key):
                    # Cancelled while Civitai was asked: download_version
                    # starts by clearing the flag, and would fetch it all.
                    self._cancel_kept(key, job)
                    return
            if job.get("version_data") is None:
                return
            self.download_version(job["version_id"], job["model_data"], job["version_data"],
                                  job.get("file_index"), key if key >= 0 else None,
                                  resume=job.pop("resume", False))
        except Exception as e:
            progress = self._active_downloads.get(key)
            if progress:
                progress.status = "error"
                progress.error = f"Download error: {e}"
            say(f"Download of file {key} failed: {e}")
        finally:
            with self._lock:
                self._running.discard(key)
            # One that ended here and not in download_version - already here,
            # or its fetch from Civitai failed - is kept no longer.
            self._save()
            self._pump()

    def _already_here(self, key: int, job: Dict[str, Any]) -> bool:
        """
        A resumed download whose file the library has now: complete, that
        file, nothing fetched - and its own .partial, of no more use, gone.
        """
        found = self._held(job.get("file_id"))
        if not found:
            return False
        job.pop("resume", None)
        partial = job.pop("partial_path", None)
        if partial:
            _remove_partial(partial)
        progress = self._active_downloads.get(key)
        if progress:
            progress.file_path = found[0]
            progress.filed = "Already in your library"
            # In the library already: the page waits for `synced` to say so.
            progress.synced = True
            progress.status = "complete"
        say(f"Already in your library, not downloaded again: {found[0]}")
        return True

    @staticmethod
    def _kept_partial(job: Dict[str, Any]) -> Optional[str]:
        """The .partial a download kept, while it is still on disk."""
        kept = job.get("partial_path")
        return kept if kept and kept.endswith(PARTIAL) and os.path.exists(kept) else None

    def _writing(self, partial: str, key: int) -> Optional[int]:
        """
        Another download on its way that writes this .partial (#395) - queued
        to resume, downloading or paused - by its key; None if none. One
        being added to the library is not counted: its file is already under
        its name, which the check for a file already there answers. Under
        the lock; `partial` as `_same_path` gives it.
        """
        for other, progress in self._active_downloads.items():
            if other == key or progress.status not in ("pending", "downloading", "paused"):
                continue
            job = self._jobs.get(other) or {}
            named = job.get("partial_path")
            if job.get("claim") == partial or (named and _same_path(named) == partial):
                return other
        return None

    def _cancel_kept(self, key: int, job: Dict[str, Any]) -> None:
        """A download cancelled before it began fetching: cancelled, the .partial it kept removed."""
        partial = job.pop("partial_path", None)
        if partial:
            _remove_partial(partial)
        progress = self._active_downloads.get(key)
        if progress:
            progress.status = "cancelled"
            progress.error = "Download cancelled"

    def _stop_keeping(self, key: int, job: Dict[str, Any], progress: "DownloadProgress",
                      why: str, again: str, kept: str = "What was downloaded is kept") -> None:
        """
        A download that cannot go on now (#390): Civitai could not be asked,
        refused a resumed download, or its file is already in another row.
        Cancelled meanwhile, it is cancelled, the .partial it kept removed.
        Holding a .partial, it pauses, saying why, and keeps it - an Error row
        is not kept across a restart, and the file was left with nothing
        naming it. With none, it is an error, as before.
        """
        if self._is_cancelled(key):
            self._cancel_kept(key, job)
        elif self._kept_partial(job):
            self._pause_saying(progress, f"{why}{'' if why.endswith('.') else '.'} {kept}; {again}")
        else:
            progress.status = "error"
            progress.error = why
        self._save()

    def _held(self, file_id: Optional[int]) -> List[str]:
        """
        The library's files that are this download's Civitai file, on disk
        and in this WebUI's folders: what "already downloaded" means. A row
        whose file is gone does not count, nor the other WebUI's file, which
        this one cannot load. With no file id - a download 0.51.8 kept from
        the Resources dialog - nothing does: another file of the version is
        not this one, and taking it for this one dropped a download and its
        .partial.
        """
        if file_id is None:
            return []
        try:
            if self._library is None:
                from .db import get_models_db
                db = get_models_db()
                self._library = lambda fid: [row["file_path"] for row in db.library_files(file_ids=[fid])]
            paths = self._library(file_id)
        except Exception as e:
            say(f"Could not ask the library about file {file_id}: {e}")
            return []
        return [path for path in paths if held_here(path)]

    def library_place(self, file_id: Optional[int]) -> Tuple[Optional[str], Optional[str]]:
        """
        Where the library has this Civitai file (#276): ("held", path) when
        any of its files is held here - nothing to fetch; else ("gone", path)
        for one the library still lists, gone from disk, in a folder this
        WebUI loads - fetched back there, so its row, pin and generations
        stay; else (None, None) - fetched to the template's folder. Only the
        file id counts: a version's other file is not this one (#189), and
        the other WebUI's copy, in a folder this one does not load, is not
        held here (#188).
        """
        held = self._held(file_id)
        if held:
            return "held", held[0]
        if file_id is None or self._library is None:
            return None, None
        try:
            paths = self._library(file_id)
        except Exception as e:
            say(f"Could not ask the library about file {file_id}: {e}")
            return None, None
        gone = [path for path in paths if path and not os.path.exists(path) and loads_here(path)]
        return ("gone", gone[0]) if gone else (None, None)

    def paid_refusal(self, version_id: int, version_data: Dict[str, Any]) -> Optional[str]:
        """
        Why a paid version is not downloaded here, or None: no API key, or
        Civitai says the key's account has not bought it. Unknown - Civitai
        not asked - it is tried. Asked by the route before queuing (#223),
        and at the download's turn, which a restored download still passes.
        """
        paid = paid_access_info(version_data)
        if not paid:
            return None
        if not api_key_from_settings():
            return ("This version is paid on Civitai. With an API key set (the settings, "
                    "Civitai account), a version you have bought downloads here.")
        bought = (owned_versions([version_id]) or {}).get(version_id)
        if bought is False:
            return (("This version is paid on Civitai" if paid["permanent"] else
                     f"This version is in early access until {paid['ends_at']}")
                    + ", and Civitai says your account has not bought it. Just bought it? Civitai's API "
                    "takes some minutes to know: try again shortly. Otherwise, buy it on its page.")
        return None

    def _fetch_job(self, key: int, job: Dict[str, Any]) -> int:
        """
        A download that knows its ids only - remembered across a restart,
        queued at once (#223), or retried: ask Civitai at its turn. One with
        a stand-in is filed under the file the answer names (_rekey). Returns
        what the download is found by from here on.
        """
        progress = self._active_downloads.get(key)
        version_id = job.get("version_id")
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
                self._stop_keeping(key, job, progress, f"Could not ask Civitai about this version: {e}",
                                   "Resume to try again.")
            return key
        if key < 0:
            named = download_key(version_id, version_data, job.get("file_index"))
            if named >= 0:
                return self._rekey(key, named, job)
        return key

    def _rekey(self, key: int, named: int, job: Dict[str, Any]) -> int:
        """
        A download that went by a stand-in, found by its file from here on, in
        its place in the list. Its file already in another row is not fetched
        twice: this row says so, and ends - keeping what it had downloaded
        where the other row has begun at another place, or is over (#390). A
        row not begun, or writing the very same .partial, would be named by
        this one's Cancel too, which would delete the other download's file.
        """
        apart = False
        with self._lock:
            progress = self._active_downloads.get(key)
            if named in self._active_downloads:
                job["version_data"] = None
                mine, theirs = job.get("partial_path"), (self._jobs.get(named) or {}).get("partial_path")
                over = self._active_downloads[named].status in ("complete", "error", "cancelled")
                apart = bool(mine and (over or (theirs and _same_path(mine) != _same_path(theirs))))
                if progress and not apart:
                    progress.status = "error"
                    progress.error = "This file is already in the list"
                if not apart:
                    return key
            else:
                self._active_downloads = {(named if k == key else k): p
                                          for k, p in self._active_downloads.items()}
                self._jobs[named] = self._jobs.pop(key, job)
                self._jobs[named]["file_id"] = named
                for flags in (self._cancel_flags, self._pause_flags, self._tqdm_positions):
                    if key in flags:
                        flags[named] = flags.pop(key)
                if key in self._running:
                    self._running.discard(key)
                    self._running.add(named)
                if progress:
                    progress.file_id = named
        if apart:
            if progress:
                self._stop_keeping(key, job, progress, "This file is already in the list, in another row",
                                   "Resume once that row has finished and been dismissed, or Cancel to remove it.",
                                   kept="What this download kept is kept")
            return key
        self._save()
        return named

    def start_now(self, key: int) -> bool:
        """A waiting download, started at once - over the limit, which only paces the queue."""
        with self._lock:
            if key not in self._waiting():
                return False
            self._running.add(key)
        self._start_thread(key)
        return True

    def move(self, key: int, by: int) -> bool:
        """
        A waiting download, up (-1) or down (+1) the queue: it changes places
        in the list with the nearest waiting one that way, so its place in
        the queue always changes by one, whatever runs between them.
        """
        with self._lock:
            waiting = self._waiting()
            if key not in waiting:
                return False
            at = waiting.index(key) + by
            if not 0 <= at < len(waiting):
                return False
            other = waiting[at]
            order = list(self._active_downloads)
            i, j = order.index(key), order.index(other)
            order[i], order[j] = order[j], order[i]
            self._active_downloads = {k: self._active_downloads[k] for k in order}
        self._save()
        return True

    def pause(self, key: int) -> bool:
        """
        Pause a download. A running one stops at its next chunk, keeps its
        .partial and gives up its place; a waiting one leaves the queue.
        """
        with self._lock:
            progress = self._active_downloads.get(key)
            if not progress:
                return False
            if progress.status == "downloading":
                self._pause_flags[key] = True
                return True
            if progress.status == "pending" and key not in self._running:
                progress.status = "paused"
                return True
            return False

    def resume(self, key: int) -> bool:
        """
        A paused download, waiting again where it is in the list: running at
        once if there is room - a free place means nothing else is waiting.
        """
        with self._lock:
            resumed = self._requeue([key])
        self._pump()
        return bool(resumed)

    def set_limit(self, limit: int) -> None:
        """
        A new number to run at once (#279). A higher one starts waiting
        downloads now; a lower one stops nothing - the running ones finish,
        and none starts until fewer than it run.
        """
        with self._lock:
            self.max_concurrent = limit
        self._pump()

    def retry(self, key: int) -> bool:
        """
        A failed download, waiting again at the end of the queue, as a new
        press would (#223). Its turn asks Civitai afresh, not the answer of
        the first try: a version bought since, or given a file since, then
        downloads. Only one in error.
        """
        with self._lock:
            failed = self._active_downloads.get(key)
            if not failed or failed.status != "error":
                return False
            job = self._jobs.get(key) or {}
            self._jobs[key] = {"version_id": job.get("version_id", failed.version_id),
                               "model_id": job.get("model_id"), "file_id": job.get("file_id"),
                               "file_index": job.get("file_index"),
                               "model_data": None, "version_data": None}
            del self._active_downloads[key]
            self._active_downloads[key] = DownloadProgress(
                version_id=failed.version_id, file_id=key, file_name=failed.file_name,
                total_bytes=failed.total_bytes)
            self._cancel_flags[key] = False
            self._pause_flags[key] = False
        self._save()
        self._pump()
        return True

    def _requeue(self, keys: List[int]) -> List[int]:
        """These paused downloads, pending again, where they are in the list. Under the lock."""
        resumed = []
        for key in keys:
            progress = self._active_downloads.get(key)
            if not progress or progress.status != "paused":
                continue
            progress.status = "pending"
            progress.error = None
            self._pause_flags[key] = False
            self._jobs.setdefault(key, {})["resume"] = True
            resumed.append(key)
        return resumed

    def pause_all(self) -> None:
        """Every running download paused, and every waiting one held, so none starts in their place."""
        with self._lock:
            waiting = [k for k, p in self._active_downloads.items() if p.status == "pending"]
            running = [k for k, p in self._active_downloads.items() if p.status == "downloading"]
        for key in waiting + running:
            self.pause(key)

    def resume_all(self) -> None:
        """
        Every paused download, the top ones running first - all made waiting,
        then started: resumed one by one, each started as it came, and the
        last listed ran first.
        """
        with self._lock:
            self._requeue([k for k, p in self._active_downloads.items() if p.status == "paused"])
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
            self._store = (lambda: db.kept_downloads(INSTALL_KEY), lambda rows: db.keep_downloads(INSTALL_KEY, rows))
        return self._store

    def _save(self) -> None:
        """
        What a restart brings back: every download not over - running, paused
        or waiting - in the list's order, one row per file. One still waiting
        has no .partial: only one begun was kept, and a restart forgot the
        rest of the queue (#187).
        """
        with self._save_lock:
            with self._lock:
                rows = []
                for key, progress in self._active_downloads.items():
                    if progress.status not in ("downloading", "paused", "pending"):
                        continue
                    job = self._jobs.get(key) or {}
                    rows.append({"version_id": job.get("version_id", progress.version_id),
                                 "model_id": job.get("model_id"),
                                 "file_id": key, "file_index": job.get("file_index"),
                                 "file_name": progress.file_name, "partial_path": job.get("partial_path"),
                                 "total_bytes": progress.total_bytes})
            # Nothing to keep, and nothing kept before: the database is not touched.
            if not rows and not self._stored_any:
                return
            try:
                self._stored()[1](rows)
                self._stored_any = bool(rows)
            except Exception as e:
                say(f"Could not keep the downloads to resume: {e}")

    def restore(self) -> None:
        """
        After a restart, the downloads not over, paused, in their order - a
        running one included: its thread died with the WebUI, its .partial
        did not. A waiting one comes back paused too, so a restart starts
        nothing by itself. Not brought back: one begun whose .partial is
        gone, and one whose file the library has by now - downloaded since,
        by hand or in the other WebUI - whose .partial, of no more use, goes.
        A row with no file id - kept before #374 - comes back under a stand-in.
        """
        try:
            rows = self._stored()[0]() or []
        except Exception as e:
            say(f"Could not read the downloads to resume: {e}")
            return
        self._stored_any = bool(rows)
        back = []
        for row in rows:
            version_id = row.get("version_id")
            partial = row.get("partial_path")
            if version_id is None or (partial and not os.path.exists(partial)):
                continue
            file_id = row.get("file_id")
            found = self._held(file_id if file_id is not None and file_id >= 0 else None)
            if found:
                if partial:
                    _remove_partial(partial)
                say(f"Already in your library, not brought back: {row.get('file_name') or version_id} "
                    f"({found[0]})")
                continue
            back.append(row)
        with self._lock:
            for row in back:
                version_id, partial = row["version_id"], row.get("partial_path")
                key = row["file_id"] if row.get("file_id") is not None else stand_in(version_id)
                if key in self._active_downloads:
                    continue
                self._active_downloads[key] = DownloadProgress(
                    version_id=version_id, file_id=key, file_name=row.get("file_name") or "",
                    total_bytes=row.get("total_bytes") or 0,
                    downloaded_bytes=_partial_bytes(partial) if partial else 0, status="paused")
                job = {"version_id": version_id, "model_id": row.get("model_id"),
                       "file_id": key if key >= 0 else None,
                       "file_index": row.get("file_index"), "model_data": None, "version_data": None}
                if partial:
                    job["partial_path"] = partial
                self._jobs[key] = job
        self._save()

    def get_progress(self, key: int) -> Optional[DownloadProgress]:
        """Get progress for a specific download, by its file."""
        with self._lock:
            return self._active_downloads.get(key)

    def get_all_progress(self) -> List[Dict[str, Any]]:
        """
        Every download, in the list's order: a waiting one with its place in
        the queue, from 1.
        """
        with self._lock:
            waiting = self._waiting()
            out = []
            for key, progress in self._active_downloads.items():
                entry = progress.to_dict()
                if key in waiting:
                    entry["queue_position"] = waiting.index(key) + 1
                out.append(entry)
            return out

    def dismiss(self, key: Optional[int] = None) -> List[int]:
        """
        Forget finished downloads - one, or every one - so they are not
        handed to the page again. Every download was kept until the WebUI
        restarted, so one dismissed in the page came back with the next poll.
        One still running is kept, whatever is asked.

        Returns:
            The file ids forgotten.
        """
        with self._lock:
            gone = [k for k, progress in self._active_downloads.items()
                    if progress.is_complete and (key is None or k == key)]
            for k in gone:
                del self._active_downloads[k]
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
        ago - removed; a different one leaves this where it landed. A move
        Windows refuses - another program holding the file - leaves it where
        it landed too, saying why (#422).

        Returns where the file is now.
        """
        try:
            from .file_identity import identify
            found = identify(path)
            file_type = found.file_type
        except Exception as e:
            say(f"Could not read what {os.path.basename(path)} is: {e}")
            return path
        # A file another program holds - an antivirus scan, the search
        # indexer - cannot be moved: shutil.move's rename is refused, it
        # copies the file, then cannot remove the original, and raised, the
        # download in Error with the file in both folders (#422). So a move
        # that fails leaves the file where it landed, the copy it made gone,
        # and the download goes on to its library row.
        to = None
        made = False
        try:
            to = proper_place(path, filed_as(file_type, found.model_class))
            if not to:
                return path
            if os.path.exists(to):
                from .hashing import file_sha256
                mine = progress.sha256 or file_sha256(path) or ""
                if mine and (file_sha256(to) or "").upper() == mine.upper():
                    try:
                        os.remove(path)
                    except OSError as e:
                        progress.filed = (f"Already in {os.path.dirname(to)}, where a {file_type} goes; this "
                                          f"copy, in {os.path.dirname(path)}, could not be removed: {e}")
                        say(progress.filed)
                        return to
                    progress.filed = f"Already in {os.path.dirname(to)}, where a {file_type} goes"
                    return to
                progress.filed = (f"Left in {os.path.dirname(path)}: it is a {file_type}, and "
                                  f"{os.path.dirname(to)} has a different file named {os.path.basename(to)}")
                return path
            os.makedirs(os.path.dirname(to), exist_ok=True)
            made = not os.path.exists(to)        # what the clean-up below may remove: only a copy of ours
            shutil.move(path, to)
        except OSError as e:
            where = os.path.dirname(to) if to else "its type's folder"
            progress.filed = (f"Left in {os.path.dirname(path)}: it is a {file_type}, and it could not be "
                              f"moved to {where}: {e}")
            if made and os.path.exists(path) and os.path.exists(to):
                try:
                    os.remove(to)
                except OSError as gone:
                    progress.filed += f". A copy is in {where} too, and could not be removed: {gone}"
            say(progress.filed)
            return path
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
        download that did not finish. A try that fails - a dropped connection,
        a short file, a 5xx - keeps what it has, and the next asks for the
        rest the same way (#291); after the last, a download with bytes kept
        pauses, saying why, so Resume carries on.
        """
        try:
            from tqdm import tqdm
        except ImportError:
            tqdm = None

        file_name = os.path.basename(target_path)
        max_retries = 3
        retry_delay = 3

        # Allocate tqdm position for stacked progress bars
        tqdm_pos = self._allocate_tqdm_position(progress.file_id)

        try:
            for attempt in range(max_retries):
                try:
                    # The first attempt starts where it was asked to - a fresh
                    # download never takes up a stale .partial - and each retry
                    # from what the attempts before it kept (#291).
                    offset = ((resume_from if attempt == 0 else os.path.getsize(target_path))
                              if os.path.exists(target_path) else 0)
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
                                if self._is_paused(progress.file_id):
                                    # Kept, to be resumed from: nothing removed.
                                    if pbar:
                                        pbar.close()
                                    progress.status = "paused"
                                    return False
                                if self._is_cancelled(progress.file_id):
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

                        # Short, with no error: a dropped connection seen
                        # late, retried like one (#291). Both WebUIs' urllib3
                        # raise on a short body themselves.
                        if total_size > 0 and downloaded != total_size:
                            raise requests.exceptions.ChunkedEncodingError(
                                f"Incomplete download: {downloaded}/{total_size} bytes")

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

                    if status_code in (401, 403):
                        if os.path.exists(target_path):
                            os.remove(target_path)
                        progress.status = "error"
                        # Civitai says why, in JSON - "Early Access", say.
                        progress.error = (_refused_401(_civitai_message(response_body), bool(api_key_from_settings()))
                                          if status_code == 401 else _refused_403(_civitai_message(response_body)))
                        return False
                    if status_code == 416:
                        # The rest cannot be sent: the .partial as long as the
                        # file, or the file smaller since. Kept, every try and
                        # every Resume would be refused alike: started over.
                        say(f"The server cannot send the rest of {file_name}: starting it over")
                        if os.path.exists(target_path):
                            os.remove(target_path)
                        progress.started_over = True
                    failure = f"Download failed (HTTP {status_code}): {e}"

                except requests.exceptions.RequestException as e:
                    say(f"Download attempt {attempt + 1} failed: {e}")
                    failure = f"Download failed after {max_retries} attempts: {e}"

                except Exception as e:
                    progress.status = "error"
                    progress.error = f"Download error: {e}"
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    return False

                # What the attempt got is kept for the next, which asks for
                # the rest (#291): a drop no longer costs the whole file.
                kept = os.path.getsize(target_path) if os.path.exists(target_path) else 0
                if attempt < max_retries - 1:
                    say(f"Retrying in {retry_delay}s" + (f", from {kept / (1024 * 1024):.1f} MB" if kept else "") + "...")
                    time.sleep(retry_delay)
                elif kept:
                    # A stop needs a way back: Resume carries on from here.
                    return self._pause_saying(progress, f"{failure}. Resume to try again.")
                else:
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    progress.status = "error"
                    progress.error = failure
                    return False

            return False

        finally:
            # Always release tqdm position
            self._release_tqdm_position(progress.file_id)

    # ------------------------------------------------------- a file in parts
    def _parts_for(self, size: int) -> int:
        """
        How many parts a new download is split into (#282): 1 with the switch
        off or no size from Civitai, else the connections setting, with no
        part under PART_MIN - so a file under two of them keeps one connection.
        """
        if size <= 0 or not parts_enabled():
            return 1
        return max(1, min(configured_connections_per_file(), size // PART_MIN))

    def _part_request(self, url: str, headers: Dict[str, str], start: int, end: Optional[int] = None):
        """One request for the bytes from `start` - to `end`, or to the file's end."""
        asked = dict(headers)
        asked["Range"] = f"bytes={start}-{'' if end is None else end}"
        response = requests.Session().get(url, headers=asked, stream=True, timeout=60)
        response.raise_for_status()
        return response

    def _download_parts(self, url: str, partial_path: str, headers: Dict[str, str],
                        progress: DownloadProgress, parts: int, resumed: bool = False) -> bool:
        """
        A file fetched in parts (#282), each over a connection of its own into
        a file of its own - part 1 the .partial itself, part N `.partial.N` -
        and joined in order once all are whole. Each part file's size is how
        far that part got, so pause, resume and a restart work part by part,
        as the .partial's size does for one connection. The split is this
        download's for good: a resume finds it in its part files. How many
        parts fetch at once is read now, at each start or resume.

        The first request, at Civitai's address, asks from part 1's own size
        to the end of the file: its answer gives the file's exact size, which
        the split is made from, and part 1 is read from it. A storage that
        sends the whole file instead is read as one connection on a first
        start; on a resume it is asked again, and then the download pauses,
        saying so. Returns as _download_file does.
        """
        key = progress.file_id
        if not resumed:
            _remove_partial(partial_path)
        have = os.path.getsize(partial_path) if resumed and os.path.exists(partial_path) else 0

        first = None
        failure = ""
        for attempt in range(PART_TRIES):
            try:
                first = self._part_request(url, headers, have)
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                body = ""
                try:
                    body = e.response.text if e.response is not None else ""
                except Exception:
                    pass
                if status in (401, 403):
                    _remove_partial(partial_path)
                    progress.status = "error"
                    progress.error = (_refused_401(_civitai_message(body), bool(api_key_from_settings()))
                                      if status == 401 else _refused_403(_civitai_message(body)))
                    return False
                say(f"HTTP error {status}: {e}")
                failure = f"Download failed (HTTP {status}): {e}"
            except requests.exceptions.RequestException as e:
                say(f"Download attempt {attempt + 1} failed: {e}")
                failure = f"Download failed after {PART_TRIES} attempts: {e}"
            if first is not None:
                if getattr(first, "status_code", 200) == 206 or not resumed:
                    break
                # Civitai's storage now and then ignores a range; a fresh
                # redirect is answered (RANGE_TRIES).
                say(f"The server sent the whole of {progress.file_name}, not the rest: asking again")
                failure = f"Civitai's storage would not send part 1 of {parts}"
                first.close()
                first = None
                continue
            if attempt < PART_TRIES - 1:
                time.sleep(3)
        if first is None:
            if resumed:
                # What it has is kept: a stop needs a way back.
                return self._pause_saying(progress, f"{failure}. Resume to try again.")
            progress.status = "error"
            progress.error = failure
            return False

        if getattr(first, "status_code", 200) == 206:
            total = _range_total(first.headers.get("content-range", "") or first.headers.get("Content-Range", ""))
        else:
            # The whole file for a first request: read as one connection.
            total, parts = int(first.headers.get("content-length", 0) or 0), 1
        if total <= 0:
            # A size the answer does not give cannot be split: one part, to its end.
            total, parts = 0, 1
        bounds = _split(total, parts) if total else [(0, None)]
        paths = [_part_path(partial_path, i) for i in range(parts)]
        for path in paths:
            if not os.path.exists(path):
                open(path, "wb").close()             # the split, kept on disk from the start

        def left(i: int) -> Optional[int]:
            start, end = bounds[i]
            return None if end is None else end - start + 1 - os.path.getsize(paths[i])

        hasher = hashlib.sha256()
        try:
            with open(paths[0], "rb") as done_part:     # part 1, resumed: read once to begin with
                for block in iter(lambda: done_part.read(4 * 1024 * 1024), b""):
                    hasher.update(block)
        except OSError as e:
            # Another program holds it: raised, every other part was deleted (#390).
            first.close()
            return self._pause_saying(progress, f"Another program has part 1 of {progress.file_name} open, "
                                                f"so it could not be read: {e}. Every part is kept; "
                                                "Resume tries again.")
        progress.total_bytes = total
        progress.downloaded_bytes = sum(os.path.getsize(p) for p in paths)
        progress.restart_rate()
        progress.record()
        # Where the redirect went: the storage address the other parts ask.
        storage = {"url": getattr(first, "url", None) or url}
        if left(0) == 0:
            first.close()
            first = None

        todo = deque(i for i in range(parts) if left(i) != 0)
        connections = configured_connections_per_file() if parts_enabled() else 1
        stopped: Dict[str, Any] = {}
        lock = threading.Lock()
        pbar = None
        try:
            from tqdm import tqdm
            pbar = tqdm(total=total, initial=progress.downloaded_bytes, unit='B', unit_scale=True,
                        unit_divisor=1024, desc=progress.file_name[:30], ncols=80,
                        position=self._allocate_tqdm_position(key), leave=True) if total else None
        except ImportError:
            pass

        def work() -> None:
            nonlocal first
            while True:
                with lock:
                    if not todo or stopped:
                        return
                    i = todo.popleft()
                    response, first = (first, None) if i == 0 else (None, first)
                try:
                    outcome = self._fetch_part(i, parts, bounds[i], paths[i], url, headers, storage,
                                               progress, hasher if i == 0 else None, response, stopped, pbar)
                except Exception as e:                 # a full disk, say: the download fails, as today
                    outcome = ("error", f"Download error: {e}")
                if outcome is not None:
                    with lock:
                        stopped.setdefault("why", outcome)

        try:
            threads = [threading.Thread(target=work, daemon=True, name=f"model-manager-part-{key}-{n}")
                       for n in range(max(1, min(connections, len(todo))))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            if first is not None:
                first.close()
            if pbar is not None:
                pbar.close()
            self._release_tqdm_position(key)

        why = stopped.get("why")
        if self._is_cancelled(key) or why == "cancelled":
            _remove_partial(partial_path)
            progress.status = "cancelled"
            progress.error = "Download cancelled"
            return False
        if self._is_paused(key) or why == "paused":
            progress.status = "paused"           # every part kept, to resume from
            return False
        if why is not None:
            kind, message = why
            if kind == "pause":
                return self._pause_saying(progress, message)
            _remove_partial(partial_path)
            progress.status = "error"
            progress.error = message
            return False

        refused = self._join_parts(paths, hasher)
        if refused:
            number, error = refused
            return self._pause_saying(progress, f"Another program has part {number} of {progress.file_name} "
                                                f"open, so the parts could not be joined: {error}. Every part "
                                                "is kept; Resume joins them.")
        size = os.path.getsize(partial_path)
        if total and size != total:
            _remove_partial(partial_path)
            progress.status = "error"
            progress.error = f"Download error: Incomplete download: {size}/{total} bytes"
            return False
        progress.sha256 = hasher.hexdigest().upper()
        return True

    def _fetch_part(self, index: int, parts: int, bounds: Tuple[int, Optional[int]], path: str,
                    url: str, headers: Dict[str, str], storage: Dict[str, str], progress: DownloadProgress,
                    hasher, response, stopped: Dict[str, Any], pbar) -> Any:
        """
        One part, from its file's size to its end: None once whole, or why it
        stopped - "paused", "cancelled", ("pause", why) once it has asked
        PART_TRIES times, ("error", why) for a refusal. It asks the storage
        address first; each time again, Civitai's, for a fresh one - a signed
        link expires, and a storage that ignored a range answers a fresh
        redirect. A connection that drops loses nothing: the part asks again
        from its own size.
        """
        start, end = bounds
        key = progress.file_id
        name = f"part {index + 1} of {parts}"
        failure = ""
        for attempt in range(PART_TRIES):
            have = os.path.getsize(path)
            need = None if end is None else end - start + 1 - have
            if need is not None and need <= 0:
                return None
            fresh = attempt > 0 or storage["url"] == url
            try:
                if response is None:
                    if fresh:
                        response = self._part_request(url, headers, start + have, end)
                        storage["url"] = getattr(response, "url", None) or storage["url"]
                    else:
                        response = self._part_request(storage["url"], {"User-Agent": headers.get("User-Agent", "")},
                                                      start + have, end)
                    if getattr(response, "status_code", 200) != 206:
                        failure = f"Civitai's storage would not send {name}"
                        response.close()
                        response = None
                        continue
                with open(path, "ab") as f:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if self._is_cancelled(key):
                            return "cancelled"
                        if self._is_paused(key):
                            return "paused"
                        if stopped:
                            return None
                        if not chunk:
                            continue
                        if need is not None:
                            chunk = chunk[:need]
                        f.write(chunk)
                        if hasher is not None:
                            hasher.update(chunk)
                        progress.add(len(chunk))
                        if pbar is not None:
                            pbar.update(len(chunk))
                        if need is not None:
                            need -= len(chunk)
                            if need == 0:
                                break
                if need is None or need == 0:
                    return None
                failure = f"{name} ended early"
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                body = ""
                try:
                    body = e.response.text if e.response is not None else ""
                except Exception:
                    pass
                if fresh and status == 401:
                    return ("error", _refused_401(_civitai_message(body), bool(api_key_from_settings())))
                if fresh and status == 403:
                    return ("error", _refused_403(_civitai_message(body)))
                # From the storage, a 403 is most likely its signed link expired.
                failure = f"{name}: HTTP {status}"
            except requests.exceptions.RequestException as e:
                failure = f"{name}: {e}"
            finally:
                if response is not None:
                    response.close()
                    response = None
            say(f"Download of {progress.file_name}, {failure}: asking again")
        if failure.startswith("Civitai's storage"):
            return ("pause", f"{failure}. Resume to try again.")
        return ("pause", f"{failure[0].upper()}{failure[1:]}. Resume to try again.")

    @staticmethod
    def _join_parts(paths: List[str], hasher) -> Optional[Tuple[int, OSError]]:
        """
        Parts 2 to N appended to the .partial in order, each hashed on the way
        and gone once added. Every part is opened before any is added: one
        another program holds stops the join before anything is touched,
        returned as (its number from 1, the error) for the download to pause,
        every part kept - opened as it came, a refusal partway lost the joined
        file (#390). Each part is closed before it is removed, so the join's
        own handle never refuses that; a part Windows still will not remove
        is left, and removed once the file is in place.
        """
        handles = []
        try:
            for index, path in enumerate(paths):
                handles.append(open(path, "ab" if index == 0 else "rb"))
        except OSError as e:
            for handle in handles:
                handle.close()
            return len(handles) + 1, e
        out = handles[0]
        try:
            for path, part in zip(paths[1:], handles[1:]):
                with part:
                    for block in iter(lambda: part.read(4 * 1024 * 1024), b""):
                        hasher.update(block)
                        out.write(block)
                try:
                    os.remove(path)
                except OSError as e:
                    say(f"Could not remove {path} once joined ({e}): it is removed once the file is in place")
        finally:
            for handle in handles:
                handle.close()
        return None

    def _pause_saying(self, progress: DownloadProgress, why: str) -> bool:
        """A download that cannot go on for now - in parts (#282), or one connection out of tries (#291): paused, what it has kept, saying why."""
        say(f"Download of {progress.file_name} paused: {why}")
        progress.status = "paused"
        progress.error = why
        return False

    def _refused(self, key: int, job: Dict[str, Any], progress: DownloadProgress, why: str,
                 kept: Optional[str]) -> DownloadProgress:
        """
        Civitai's answer refuses a download before it fetches: paid and not
        bought, no files, no address. A resumed one holding its .partial is
        paused, the answer dropped as Retry drops it, so Resume asks again - a
        version bought since downloads the rest (#390). Any other: an error.
        """
        if kept:
            job["model_data"] = job["version_data"] = None
            self._stop_keeping(key, job, progress, why if why.endswith(".") else f"{why}.",
                               "Resume to ask Civitai again, or Cancel to remove it.")
        else:
            progress.status = "error"
            progress.error = why
        return progress

    def _pause_whole(self, job: Dict[str, Any], progress: DownloadProgress, partial_path: str,
                     expected: str, why: str) -> None:
        """
        A whole, checked file that could not be put in place, paused with it
        kept (#390): its size recorded as the file's - which Resume compares -
        and its SHA-256 kept with the size and time it had, so Resume need
        not read it again while it is unchanged.
        """
        stat = os.stat(partial_path)
        progress.total_bytes = progress.downloaded_bytes = stat.st_size
        job["checked"] = (progress.sha256, stat.st_size, stat.st_mtime_ns)
        matches = "matches Civitai's SHA-256" if expected else "came to its full length"
        self._pause_saying(progress, f"{why}. It is whole and {matches}, kept as "
                                     f"{os.path.basename(partial_path)}. Resume puts it in place "
                                     "without downloading it again.")
        self._save()

    def _kept_whole(self, job: Dict[str, Any], progress: DownloadProgress, partial_path: str,
                    expected: str) -> Optional[str]:
        """
        A resumed download's .partial that is already the whole file (#390) -
        a rename Windows refused, a connection dropped after the last byte.
        "whole" when its own size, part files not counted, is the size the
        download recorded and its SHA-256 is Civitai's (with none listed, the
        size alone); "wrong" when only the size is; "unread" when it cannot be
        read to tell - paused, kept: another program holds it; else None. The
        SHA-256 worked out when it arrived serves while the file is as it was;
        after a restart it is read again.
        """
        if not progress.total_bytes or not os.path.exists(partial_path):
            return None
        stat = os.stat(partial_path)
        if stat.st_size != progress.total_bytes:
            return None
        if expected:
            checked = job.get("checked")
            if checked and checked[0] and checked[1:] == (stat.st_size, stat.st_mtime_ns):
                sha = checked[0]
            else:
                from .hashing import file_sha256
                sha = file_sha256(partial_path)
                if sha is None:
                    self._pause_saying(progress, f"{os.path.basename(partial_path)} could not be read to check "
                                                 "it: another program may have it open. Everything downloaded "
                                                 "is kept; Resume tries again.")
                    self._save()
                    return "unread"
            if sha.upper() != expected:
                return "wrong"
            progress.sha256 = sha.upper()
        progress.downloaded_bytes = stat.st_size
        return "whole"

    def _into_place(self, key: int, job: Dict[str, Any], progress: DownloadProgress, partial_path: str,
                    target_path: str, expected: str) -> bool:
        """
        A whole, checked download renamed to its own name. Another program
        holding the new file - an antivirus scan, the search indexer, a backup
        tool - makes Windows refuse, and the file was deleted (#390): it is
        tried again over RENAME_WAITS, then paused with the file kept, which
        Resume puts in place without fetching it again. Pause and Cancel
        pressed meanwhile are read between tries. True once renamed; else
        the progress says what became of it.
        """
        folder, name = os.path.split(target_path)

        def appeared() -> bool:
            # Never over a file: one may have arrived under this name meanwhile.
            _remove_partial(partial_path)
            progress.status = "error"
            progress.error = (f"A file named {name} appeared in {folder} while "
                              "downloading, so the download was not put in its place")
            progress.file_path = target_path
            return False

        # Pressed while the transfer ended, or while Resume read the file
        # again (a few seconds a GB): heard now, before the file is placed.
        if self._is_cancelled(key):
            _remove_partial(partial_path)
            progress.status = "cancelled"
            progress.error = "Download cancelled"
            return False
        if self._is_paused(key):
            self._pause_whole(job, progress, partial_path, expected, "Paused")
            return False
        refused = None
        for wait in RENAME_WAITS + (None,):
            if os.path.exists(target_path):
                return appeared()
            try:
                os.rename(partial_path, target_path)
                return True
            except FileExistsError:
                return appeared()
            except OSError as e:
                refused = e
            if wait is None:
                break
            say(f"Windows would not let {name} be renamed into place ({refused}): trying again in {wait} s")
            _wait(wait)
            if self._is_cancelled(key):
                _remove_partial(partial_path)
                progress.status = "cancelled"
                progress.error = "Download cancelled"
                return False
            if self._is_paused(key):
                break
        self._pause_whole(job, progress, partial_path, expected,
                          f"Windows would not let the finished file be renamed into place: {refused}")
        return False

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
        from its .partial where there is one. Found by the file it takes
        (download_key).
        """
        partial_path = None
        checked = False                     # whole and checked, not yet in place (#390)
        expected = ""
        key = download_key(version_id, version_data, file_index, file_id)
        with self._lock:
            # The progress the queue made, or a paused one being resumed, is
            # the one the page follows; anything else starts afresh.
            progress = self._active_downloads.get(key)
            if progress is None or progress.status not in ("pending", "paused"):
                progress = DownloadProgress(version_id=version_id, file_id=key)
                self._active_downloads[key] = progress
            progress.status = "downloading"
            progress.error = None
            self._cancel_flags[key] = False
            self._pause_flags[key] = False
            job = self._jobs.setdefault(key, {})
            job.setdefault("version_id", version_id)
            job.setdefault("model_id", (model_data or {}).get("id"))
            job.setdefault("file_index", file_index)
            if key >= 0:
                job["file_id"] = key

        try:
            model_id = (model_data or {}).get("id")
            if model_id:
                progress.page_url = f"https://civitai.com/models/{model_id}?modelVersionId={version_id}"
            # A resume carries on where its .partial is: the folder template
            # changed, or a sync forgot the row it was fetched back to, while
            # it was paused, and it started over elsewhere, its .partial left.
            # Looked up first, so a refusal below keeps it (#390).
            kept = self._kept_partial(job) if resume else None
            # A paid version downloads when the API key's account bought it.
            # One it did not is refused before anything is created: its
            # download answers 403, and _download_file would burn three
            # retries on it. Unknown - Civitai not asked - it is tried.
            refused = self.paid_refusal(version_id, version_data)
            if refused:
                return self._refused(key, job, progress, refused, kept)

            model_type = model_data.get("type", "Other")

            files = version_data.get("files", [])
            if not files:
                return self._refused(key, job, progress, "No files available for download", kept)

            file_info = files[pick_file_index(files, file_index, file_id)]
            file_name = file_info.get("name", f"model_{version_id}.safetensors")
            download_url = file_info.get("downloadUrl") or version_data.get("downloadUrl")

            if not download_url:
                return self._refused(key, job, progress, "No download URL available", kept)

            # The library first (#276): only the path below was ever looked
            # at, so a copy moved into a subfolder of one's own, or filed by
            # an older template, was fetched again beside it.
            place, library_path = self.library_place(file_info.get("id"))
            if place == "held":
                if kept:
                    _remove_partial(kept)    # only ever this download's own
                progress.file_name = os.path.basename(library_path)
                progress.file_path = library_path
                progress.total_bytes = progress.downloaded_bytes = os.path.getsize(library_path)
                progress.filed = "Already in your library"
                # In the library already: the page waits for `synced` to say so.
                progress.synced = True
                progress.status = "complete"
                say(f"Already in your library, not downloaded again: {library_path}")
                return progress

            if kept:
                target_dir, file_name = os.path.split(kept[:-len(PARTIAL)])
            elif place == "gone":
                # Back where the library had it, under the name it had there:
                # the same row, with its pin and generations, not a second.
                target_dir, file_name = os.path.split(library_path)
            else:
                base_path = self.get_base_path(model_type)
                template = setting('model_manager_civitai_folder_template')
                subfolder = apply_folder_template(template, model_data, version_data)
                # Absolute, with no "..": the path a scan finds the file by, which
                # is how the library knows it is the same file.
                target_dir = os.path.abspath(os.path.join(base_path, subfolder) if subfolder else base_path)

            os.makedirs(target_dir, exist_ok=True)

            progress.file_name = file_name
            target_path = os.path.join(target_dir, file_name)

            # One .partial, one download (#395): two different files of one
            # name in one folder - two versions shipping one file name, say -
            # wrote one .partial at once, and one could end checked and
            # complete holding both downloads' bytes. Taken in the same step
            # as the look, so a download starting a moment later sees it.
            with self._lock:
                holder = self._writing(_same_path(target_path + PARTIAL), key)
                if holder is None:
                    job["claim"] = _same_path(target_path + PARTIAL)
            if holder is not None and holder < 0:
                # A stand-in, kept from before 0.73.0: its file not yet named,
                # most likely this very file, pressed again while it sat paused.
                progress.status = "error"
                progress.error = (f"Not started: an earlier download of {file_name} is paused in the list. "
                                  "Resume it, or Cancel it and press Retry.")
                return progress
            if holder is not None:
                progress.status = "error"
                progress.error = (f"Not started: {file_name}, another download in the list, is being saved "
                                  f"under the same name in {target_dir}. Two different files cannot have one "
                                  "name in one folder. Press Retry once that download has finished: the file "
                                  "there is then compared with this one, and added to your library if it is "
                                  "the same, or you are told it is a different file.")
                return progress

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
            # Resumed whole - a rename Windows refused, a connection dropped
            # after the last byte (#390): put in place, nothing fetched.
            whole = self._kept_whole(job, progress, partial_path, expected) if resume else None
            if whole == "unread":
                partial_path = None              # kept: another program holds it
                return progress
            if whole == "wrong":
                say(f"{file_name}'s kept file is its full size but not Civitai's file: starting it again")
                _remove_partial(partial_path)
            if whole != "whole":
                if not resume:
                    # Strays a join could not remove (#390): a later resume
                    # would read them as its split.
                    _remove_parts(partial_path)
                # In parts (#282), its split is in its part files: a resume keeps
                # it, and a paused one-connection download stays on one.
                kept_parts = _part_count(partial_path) if resume else 0
                if kept_parts < 0:
                    say(f"A join of {file_name}'s parts was cut short: starting it again")
                    _remove_partial(partial_path)
                    kept_parts = 0
                resume_from = os.path.getsize(partial_path) if kept_parts == 1 else 0
                parts = kept_parts or self._parts_for(int((file_info.get("sizeKB") or 0) * 1024))
                # Kept in the database while it runs, so a restart - or a crash -
                # leaves it paused, to be resumed, rather than a stray .partial.
                job["partial_path"] = partial_path
                self._save()
                if parts > 1:
                    success = self._download_parts(download_url, partial_path, headers, progress, parts,
                                                   resumed=kept_parts > 1)
                else:
                    success = self._download_file(download_url, partial_path, headers, progress, resume_from)

                if not success:
                    if progress.status == "paused":
                        partial_path = None          # kept, to resume from
                        self._save()
                    return progress

                if expected and progress.sha256 != expected:
                    _remove_partial(partial_path)
                    progress.status = "error"
                    progress.error = ("The downloaded file does not match Civitai's SHA-256, "
                                      "so it was removed. Try downloading it again.")
                    return progress

            # Whole and checked - or, with no SHA-256 listed, whole: from here
            # until it is in place, a failure keeps it (#390).
            checked = True
            if not self._into_place(key, job, progress, partial_path, target_path, expected):
                partial_path = None              # kept and paused, or gone as the progress says
                return progress
            partial_path = None
            # Under its name now: being added, which a download of the same
            # name meanwhile finds there and is answered by (#395).
            progress.status = "finishing"
            _remove_parts(target_path + PARTIAL)
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
            say_failure(f"Download error: {e}")
            if partial_path and checked and os.path.exists(partial_path):
                # Whole and checked, not yet in place: kept, never deleted (#390).
                self._pause_whole(job, progress, partial_path, expected, f"Download error: {e}")
                return progress
            progress.status = "error"
            progress.error = str(e)
            # Only ever this download's own unfinished files.
            if partial_path:
                _remove_partial(partial_path)
            return progress
        finally:
            with self._lock:
                self._cancel_flags.pop(key, None)
                self._pause_flags.pop(key, None)
                # The claim is the moments before the .partial is recorded;
                # a paused download keeps the name by its .partial.
                self._jobs.get(key, {}).pop("claim", None)
                ended = progress.status in ("complete", "error", "cancelled")
                if ended:
                    self._jobs.get(key, {}).pop("partial_path", None)
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
        model_data: Optional[Dict[str, Any]],
        version_data: Optional[Dict[str, Any]],
        file_index: Optional[int] = None,
        file_id: Optional[int] = None,
        model_id: Optional[int] = None,
        file_name: Optional[str] = None,
        size_kb: Optional[float] = None
    ) -> DownloadProgress:
        """
        Queue a download for parallel processing. Without the version's data,
        it is queued by its ids alone, as a restart brings one back: Civitai
        is asked at its turn (#223), and the row shows the name and size the
        page sent until then. Found by its file: the one asked for, else the
        one chosen from the version's files (download_key) - the route names
        it whenever the version's data is not handed in.
        """
        progress = DownloadProgress(version_id=version_id)
        if version_data is None:
            progress.file_name = file_name or "Unknown"
            progress.total_bytes = int((size_kb or 0) * 1024)
        else:
            files = version_data.get("files", [])
            chosen = files[pick_file_index(files, file_index, file_id)] if files else {}
            progress.file_name = chosen.get("name", "Unknown")
            # Civitai's size (in KiB), shown before it begins - and after a restart.
            progress.total_bytes = int((chosen.get("sizeKB") or 0) * 1024)
            # The file chosen, by Civitai's id: after a restart the version is
            # fetched again, and its list may come in another order (#187).
            file_id = chosen.get("id", file_id)
        key = download_key(version_id, version_data, file_index, file_id)
        progress.file_id = key

        with self._lock:
            # One on its way is answered as it is: dropping its row and
            # queuing it afresh started a running download over - asked for
            # again by the Resources dialog for one the Civitai Browser
            # started, say, or for a gone version whose newest was coming
            # already (#119). A finished one is queued afresh, at the end of
            # the list: its file may be gone since. Another file of the same
            # version is a download of its own (#374).
            current = self._active_downloads.get(key)
            if current is not None and current.status in ON_ITS_WAY:
                return current
            self._active_downloads.pop(key, None)
            self._active_downloads[key] = progress
            self._cancel_flags[key] = False
            self._jobs[key] = {"version_id": version_id, "model_data": model_data, "version_data": version_data,
                               "file_index": file_index, "file_id": key if key >= 0 else None,
                               "model_id": (model_data or {}).get("id") or model_id}
        self._save()
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
            from .sync_service import SyncService, forget_orphans
            from .db import get_models_db
            result = SyncService().sync_model(file_path, force=True, known=known)
            # A file landing where another was identifies it afresh (#200).
            forget_orphans(get_models_db())
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
            service = DownloadService(max_concurrent=configured_downloads_at_once())
            service.restore()
            _download_service = service
    return _download_service


def current_download_service() -> Optional[DownloadService]:
    """The download service if it has been made, else None - never made here."""
    return _download_service


def configured_downloads_at_once() -> int:
    """
    How many downloads run at once, as the settings have it (#279): 1 to 10,
    the same top as Civitai's requests per second. The default when it cannot
    be read.
    """
    try:
        configured = setting('model_manager_downloads_at_once')
        if configured is not None:
            return max(1, min(int(configured), 10))
    except (TypeError, ValueError):
        pass
    return DEFAULTS['model_manager_downloads_at_once']


def parts_enabled() -> bool:
    """Whether a large file is fetched in parts (#282): the switch, on unless turned off."""
    try:
        return bool(setting('model_manager_download_in_parts'))
    except (TypeError, ValueError):
        return DEFAULTS['model_manager_download_in_parts']


def configured_connections_per_file() -> int:
    """
    How many connections a file in parts is fetched over (#282): 2 to 16 - the
    switch is the only off. The default when it cannot be read.
    """
    try:
        configured = setting('model_manager_connections_per_file')
        if configured is not None:
            return max(2, min(int(configured), 16))
    except (TypeError, ValueError):
        pass
    return DEFAULTS['model_manager_connections_per_file']
