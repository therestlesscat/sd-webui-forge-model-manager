"""
The database file itself (#287): the space inside it no row uses, compacting
it, and the copies migrations leave beside it.

SQLite keeps the pages a delete or a dropped table frees, marked free, and
reuses them; the file never shrinks by itself. v42 left one library's file
1.92 GB with 566 MB of them. A VACUUM rewrites the file without them, and a
TRUNCATE checkpoint after it hands the space back: until then the new pages
sit in the WAL beside the old file, and SQLite's own checkpoints copy them
back but leave the WAL at its full size.

A VACUUM is a write that holds the database for its whole length - about 17
s for 1.8 GB on an NVMe drive, more on a slower disk. Readers go on: in WAL
mode they see the file as it was. A writer gives up after its busy timeout,
so while one runs every call in this WebUI waits for it instead
(`database.compacting`, read by `ModelsDatabase._cursor`). The other WebUI's
writers cannot be told; the page warns before it starts.

A compact is one of the long jobs (model_manager.jobs), as a sync is.

Every migration that reshapes the database backs it up beside itself first
(`migrations._back_up`), and nothing deleted those copies. `backups` lists
them by the names migrations give them, and `delete_backups` deletes only
what it lists.
"""
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..console import say
from ..jobs import jobs
from . import database

KIND = "compact"

# Below this many free bytes the button is off: rewriting the whole file for
# a few pages a sync leaves is a minute of disk for nothing.
MIN_FREE = 10 * 1048576
# The room a compact needs, as a share of what the file keeps: SQLite builds
# the new copy in the temp folder, then writes it through the WAL - 1.77 GB
# of WAL for a file that ended at 1.76 GB.
ROOM_SHARE = 1.1
# The checkpoint after a VACUUM waits for nothing to be reading: tried this
# many times, each waiting up to this many seconds for readers, then as long
# again before the next.
CHECKPOINT_TRIES = 30
CHECKPOINT_WAIT = 1.0

# The long jobs a compact waits for, and how the page names each.
_JOBS = (("sync", "Sync with Civitai"), ("images", "Sync images"),
         ("restamp", "judging stored images again"))

_STAMP = r"(\d{8}_\d{6})"
# images_cache.db's copies, from v4 (migrations._migrate_to_v4).
_CACHE_BACKUP = re.compile(r"images_cache\.db\.backup_" + _STAMP + r"$", re.IGNORECASE)


def size_text(count: int) -> str:
    """Bytes as the page shows them (formatBytes in core.mjs): "1.79 GB"."""
    if count >= 1073741824:
        return f"{count / 1073741824:.2f} GB"
    if count >= 1048576:
        return f"{count / 1048576:.2f} MB"
    if count >= 1024:
        return f"{count / 1024:.2f} KB"
    return f"{count} B"


def _bytes(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _on_disk(path: str) -> int:
    """The database and its WAL, as the disk holds them."""
    return _bytes(path) + _bytes(path + "-wal")


def _pages(path: str) -> Dict[str, int]:
    """
    SQLite's own count of the file, read on a read-only connection: through
    the WAL, so a VACUUM not yet checkpointed already counts as done.
    """
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        free = conn.execute("PRAGMA freelist_count").fetchone()[0]
    finally:
        conn.close()
    return {"page_size": page_size, "pages": pages, "free_bytes": free * page_size,
            "kept_bytes": (pages - free) * page_size}


def _drive(folder: str) -> str:
    """The drive a folder is on, as a person names it: "F:", else the folder."""
    drive = os.path.splitdrive(os.path.abspath(folder))[0]
    return drive or folder


def _same_disk(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return _drive(a).lower() == _drive(b).lower()


def room(path: str, kept: int) -> List[Dict[str, Any]]:
    """
    Each disk a compact writes to, with what it needs there and has free:
    the system's temp folder for SQLite's copy, the database's folder for the
    WAL - both together when they are one disk.
    """
    need = int(kept * ROOM_SHARE)
    folder = os.path.dirname(os.path.abspath(path))
    temp = tempfile.gettempdir()
    places = [(folder, need * 2)] if _same_disk(folder, temp) else [(folder, need), (temp, need)]
    found = []
    for place, needed in places:
        try:
            free = shutil.disk_usage(place).free
        except OSError:
            continue
        found.append({"drive": _drive(place), "database": place == folder, "needed": needed, "free": free})
    return found


def _short(disks: List[Dict[str, Any]], backups_bytes: int) -> Optional[str]:
    """What a compact lacks in room, in the page's words; None when there is enough."""
    for disk in disks:
        if disk["free"] >= disk["needed"]:
            continue
        text = (f"Compacting needs about {size_text(disk['needed'])} free on {disk['drive']} "
                f"and {size_text(disk['free'])} is free.")
        if disk["database"] and backups_bytes and disk["free"] + backups_bytes >= disk["needed"]:
            text += f" Deleting the old backups below would free {size_text(backups_bytes)}."
        return text
    return None


def _jobs_running() -> Optional[str]:
    """The long job a compact waits for, in the page's words; None while none runs."""
    for kind, name in _JOBS:
        if jobs.running(kind):
            return f"Compacting waits for {name} to end."
    # Imported here: the queue's runner reaches the database at import.
    from ..scheduler.runner import working
    if working():
        return "Compacting waits for the queue to end or pause."
    return None


# ------------------------------------------------------------------ compact

@dataclass
class CompactProgress:
    """
    What the page is told: "running", then "done" - `shrunk` once the file
    has given the space back - "cancelled", or "failed" with why; `locked`
    when another program was writing to the database.
    """
    state: str = "running"
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    before: Optional[int] = None
    after: Optional[int] = None
    shrunk: bool = False
    locked: bool = False
    error: Optional[str] = None

    def fail(self, message: str) -> None:
        self.state, self.error, self.finished = "failed", message, time.time()

    def to_dict(self) -> Dict[str, Any]:
        found = {"state": self.state, "started": self.started, "before": self.before,
                 "seconds": (self.finished or time.time()) - self.started}
        if self.state != "running":
            found.update(finished=self.finished, after=self.after, shrunk=self.shrunk,
                         locked=self.locked, error=self.error)
        return found


class Compact(object):
    """A VACUUM of the database in use, and the checkpoint that gives its space back."""

    def __init__(self, path: str):
        self.path = path
        self.progress = CompactProgress()
        self._conn: Optional[sqlite3.Connection] = None
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        """
        Interrupt the VACUUM, SQLite's own way from another thread: it stops,
        and puts everything back. Once the VACUUM is done, only the wait for
        the checkpoint stops.
        """
        self._cancelled.set()
        conn = self._conn
        if conn is not None:
            try:
                conn.interrupt()
            except sqlite3.Error:
                pass

    def run(self) -> None:
        progress = self.progress
        progress.before = _on_disk(self.path)
        conn = self._open()
        self._conn = conn
        database.compacting.set()
        try:
            say(f"Compacting the database ({size_text(progress.before)})...")
            try:
                conn.execute("VACUUM")
            except sqlite3.OperationalError as e:
                if self._cancelled.is_set():
                    progress.state = "cancelled"
                    say("Compacting the database: cancelled, the database is as it was")
                else:
                    progress.locked = "locked" in str(e) or "busy" in str(e)
                    progress.state, progress.error = "failed", str(e)
                    say(f"Could not compact the database: {e}")
                return
            progress.shrunk = self._checkpoint(conn)
            progress.state = "done"
        finally:
            self._conn = None
            database.compacting.clear()
            conn.close()
            progress.after = _on_disk(self.path)
            progress.finished = time.time()
        say(f"Compacted the database: {size_text(progress.before)} to {size_text(progress.after)} "
            f"in {progress.finished - progress.started:.0f} s"
            + ("" if progress.shrunk else "; the file shrinks once nothing is reading it"))

    def _open(self) -> sqlite3.Connection:
        """
        Not the thread's connection: a VACUUM needs one with no transaction
        open, and the interrupt reaches it from the cancel's thread.
        """
        return sqlite3.connect(self.path, timeout=database.BUSY_SECONDS, isolation_level=None,
                               check_same_thread=False)

    def _checkpoint(self, conn: sqlite3.Connection) -> bool:
        """Hand the space back: True once the checkpoint went through."""
        conn.execute(f"PRAGMA busy_timeout = {int(CHECKPOINT_WAIT * 1000)}")
        for _ in range(CHECKPOINT_TRIES):
            if checkpoint(conn):
                return True
            if self._cancelled.wait(CHECKPOINT_WAIT):
                break
        return False


def checkpoint(conn: sqlite3.Connection) -> bool:
    """A TRUNCATE checkpoint: True when nothing was reading, and the WAL is empty."""
    try:
        return conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    except sqlite3.Error:
        return False


def _finish_shrinking(path: str) -> None:
    """
    A compact that found the file being read at its end: its checkpoint once
    more, without waiting, each time the window asks.
    """
    progress = jobs.progress(KIND)
    if progress is None or progress.state != "done" or progress.shrunk:
        return
    conn = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        if checkpoint(conn):
            progress.shrunk = True
            progress.after = _on_disk(path)
            say(f"Compacted the database: it now takes {size_text(progress.after)}")
    finally:
        conn.close()


def in_use() -> str:
    """The database file this WebUI has open."""
    return database.get_models_db().db_path


def blocked(path: str) -> Optional[str]:
    """Why a compact cannot start now, in the page's words; None when it can."""
    if jobs.running(KIND):
        return "Already compacting."
    reason = _jobs_running()
    if reason:
        return reason
    kept = _pages(path)["kept_bytes"]
    return _short(room(path, kept), sum(b["bytes"] for b in backups(path)))


def start(path: str) -> Optional[str]:
    """Start a compact of the database at `path`: None, or why not."""
    reason = blocked(path)
    if reason:
        return reason
    if not jobs.start(KIND, lambda: Compact(path), lambda compact: compact.run()):
        return "Already compacting."
    return None


def cancel() -> bool:
    """Ask a running compact to stop. False when none runs."""
    return jobs.running(KIND) and jobs.cancel(KIND)


def progress() -> Optional[Dict[str, Any]]:
    """The running or last compact's progress; None when none ran in this process."""
    found = jobs.progress(KIND)
    return found.to_dict() if found else None


def space(path: str) -> Dict[str, Any]:
    """
    What the settings window shows of the database file: its size and its
    WAL's, the free pages, the size kept, what would stop a compact, the
    running or last compact, and the backups beside it. Milliseconds: three
    numbers SQLite keeps, the folder, and a backup's version where its name
    does not say it.
    """
    _finish_shrinking(path)
    pages = _pages(path)
    found = backups(path)
    total = sum(b["bytes"] for b in found)
    disks = room(path, pages["kept_bytes"])
    reason = None if jobs.running(KIND) else (_jobs_running() or _short(disks, total))
    return {"path": path, "file_bytes": _bytes(path), "wal_bytes": _bytes(path + "-wal"), **pages,
            "min_free": MIN_FREE, "room": disks, "blocked": reason, "compact": progress(),
            "custom_database": database._custom_path() is not None,
            "backups": found, "backups_bytes": total}


# ------------------------------------------------------------------ backups

def _database_backup(name: str) -> re.Pattern:
    """A migration's copy of the database named `name`: `<name>.backup_<date>_<time>[_v<N>]`."""
    return re.compile(re.escape(name) + r"\.backup_" + _STAMP + r"(?:_v(\d+))?$", re.IGNORECASE)


def backups(path: str) -> List[Dict[str, Any]]:
    """
    The copies migrations left beside the database, newest first: each with
    its name, when it was made, which database version it holds and its
    size. A `_v42` copy was made before v42 ran, so it holds 41; one without
    the number is read, read-only. Only files whose names migrations give,
    in the database's own folder - never the database, its WAL, a folder.
    """
    folder = os.path.dirname(os.path.abspath(path))
    ours = _database_backup(os.path.basename(path))
    found = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    for entry in entries:
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
        except OSError:
            continue
        match = ours.match(entry.name)
        kind = "database"
        if match is None:
            match = _CACHE_BACKUP.match(entry.name)
            kind = "image_cache"
        if match is None:
            continue
        try:
            made = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        holds = None
        if kind == "database":
            numbered = match.group(2)
            holds = int(numbered) - 1 if numbered else database._stored_schema(entry.path)
        found.append({"name": entry.name, "made": made.isoformat(), "kind": kind, "holds": holds,
                      "bytes": _bytes(entry.path)})
    found.sort(key=lambda b: (b["made"], b["name"]), reverse=True)
    return found


def delete_backups(path: str, names: List[str]) -> Dict[str, Any]:
    """
    Delete these backups beside the database, by name: only names on the
    list `backups` reads now. One name not on it refuses them all, and
    nothing is deleted. Not while a migration runs: its newest copy may be
    the one being written, or the only way back. Answers each name's end.
    """
    if any(not isinstance(name, str) for name in names):
        return {"success": False, "error": "Backups are named by their file names."}
    state = database.migration_state()
    if state is not None and not state.get("error"):
        return {"success": False, "error": "The database is being updated: no backup is deleted until it ends."}
    listed = {b["name"].lower(): b for b in backups(path)}
    unknown = [name for name in names if name.lower() not in listed]
    if unknown:
        return {"success": False, "error": f"Not a backup beside the database: {', '.join(unknown)}. "
                                           "Nothing was deleted."}
    folder = os.path.dirname(os.path.abspath(path))
    results = []
    for name in names:
        backup = listed[name.lower()]
        try:
            os.remove(os.path.join(folder, backup["name"]))
        except PermissionError:
            results.append({"name": backup["name"], "deleted": False, "error": "in use by another program"})
        except OSError as e:
            results.append({"name": backup["name"], "deleted": False, "error": e.strerror or str(e)})
        else:
            say(f"Deleted the database backup {backup['name']} ({size_text(backup['bytes'])})")
            results.append({"name": backup["name"], "deleted": True, "error": None})
    return {"success": True, "results": results}
