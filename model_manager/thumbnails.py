"""
Thumbnails of your generations (#5): a small copy of each image for its
tile, so the Generations tab and a model's "Your generations" stop loading
the full file Forge saved - a 1.3 MB PNG, 4 MB once decoded, to draw a tile
300 pixels tall. The viewer still shows the full file.

Off until asked for: Sync images makes them when its "Make thumbnails" box
is ticked - for every image the library holds without one - and, with the
setting on, the recorder makes one for each image it records. An image
without one shows its full file, as before.

Each is kept where the person chose - in a folder (beside the database by
default) or in a `.thumbnails` folder beside each image - and recorded in
`image_thumbnails`, keyed by the image's path: Force sync and the recorder
give an image a new id, never a new path. The record holds the image's
size and modified time when it was made, so a changed image shows its full
file until a sync makes it again.
"""
import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, List, Optional, Tuple

from . import forge_host
from .console import say

# A thumbnail's height: the tile draws 300 px, and 450 serves a screen
# scaled up to 1.5 as well - one size for every screen. 41 ms and 21 KB
# each, median, from 40 real images.
HEIGHT = 450
QUALITY = 80

ENABLED_SETTING = "model_manager_thumbnails"
PLACE_SETTING = "model_manager_thumbnails_place"
FOLDER_SETTING = "model_manager_thumbnails_folder"
THREADS_SETTING = "model_manager_thumbnail_threads"
# Where they are kept, as the settings and the dialog name it.
IN_FOLDER, BESIDE = "In a folder", "Beside each image"
PLACES = (IN_FOLDER, BESIDE)

# The folder beside the database, when the person names none; and the one
# beside each image, which Sync images' walk skips - a `.webp` there would
# otherwise be synced as an image of its own.
FOLDER_NAME = "thumbnails"
BESIDE_NAME = ".thumbnails"

# Thumbnails made between two writes of their records, and two looks at Cancel.
CHUNK = 256

# What making one came to. One that fails raises instead, and gets no
# record: a drive that dropped for a moment heals at the next sync.
MADE, NOT_NEEDED = "made", "not needed"


def enabled() -> bool:
    """Whether Sync images' dialog starts ticked, and the recorder makes them."""
    return bool(forge_host.setting(ENABLED_SETTING))


def place() -> str:
    """Where new thumbnails go: IN_FOLDER or BESIDE each image."""
    chosen = str(forge_host.setting(PLACE_SETTING) or "").strip()
    return chosen if chosen in PLACES else IN_FOLDER


def default_folder() -> str:
    """The folder used when none is named: `thumbnails` beside the database."""
    from .db.database import database_path
    return os.path.join(os.path.dirname(os.path.abspath(database_path())), FOLDER_NAME)


def folder() -> str:
    """The folder thumbnails go into when kept in one."""
    named = str(forge_host.setting(FOLDER_SETTING) or "").strip().strip('"').strip()
    return os.path.normpath(named) if named else default_folder()


def threads() -> int:
    """How many are made at once: the setting, or every processor for 0."""
    try:
        chosen = int(forge_host.setting(THREADS_SETTING) or 0)
    except (TypeError, ValueError):
        chosen = 0
    return chosen if chosen > 0 else max(1, os.cpu_count() or 1)


def target(image_path: str, where: str, root: str) -> str:
    """
    Where an image's thumbnail is written. In a folder: under its first two
    letters, named by a hash of the image's path, so images of one name in
    many folders stay apart. Beside the image: in `.thumbnails`, by its file
    name. The height is in both names: a later size never overwrites.
    """
    if where == BESIDE:
        return os.path.join(os.path.dirname(image_path), BESIDE_NAME,
                            f"{os.path.basename(image_path)}_{HEIGHT}.webp")
    key = hashlib.sha1(os.path.normcase(os.path.normpath(image_path)).lower().encode("utf-8")).hexdigest()
    return os.path.join(root, key[:2], f"{key}_{HEIGHT}.webp")


def is_thumbnail_folder(path: str, root: Optional[str] = None) -> bool:
    """Whether a folder holds thumbnails - a `.thumbnails`, or the folder the
    settings keep them in - so a walk for images leaves it out."""
    if os.path.basename(os.path.normpath(path)).lower() == BESIDE_NAME:
        return True
    root = root if root is not None else folder()
    return os.path.normcase(os.path.normpath(path)) == os.path.normcase(os.path.normpath(root))


def make(image_path: str, destination: str) -> str:
    """
    Make one thumbnail, HEIGHT pixels tall, as WebP - written under a
    temporary name and then renamed, so a half-written file is never
    served. An image no taller needs none.

    Returns:
        MADE or NOT_NEEDED.

    Raises:
        Exception: when the image cannot be read - not an image, cut short,
            or a drive that dropped - or the thumbnail cannot be written.
            Nothing tells a passing failure from a lasting one, so none is
            recorded: the next sync tries again, and says so again.
    """
    from PIL import Image, ImageOps
    with Image.open(image_path) as image:
        if image.height <= HEIGHT:
            return NOT_NEEDED
        image.draft("RGB", (image.width * HEIGHT // image.height, HEIGHT))
        image = ImageOps.exif_transpose(image)
        alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
        image = image.convert("RGBA" if alpha else "RGB")
        image.thumbnail((image.width, HEIGHT), getattr(Image, "Resampling", Image).LANCZOS,
                        reducing_gap=2.0)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    partial = f"{destination}.{os.getpid()}.{threading.get_ident()}.partial"
    try:
        image.save(partial, "WEBP", quality=QUALITY)
        os.replace(partial, destination)
    finally:
        if os.path.exists(partial):
            try:
                os.remove(partial)
            except OSError:
                pass
    return MADE


def _one(entry: Tuple[str, int, int], where: str, root: str) -> Tuple[str, Optional[str], int, int, str]:
    """One image's thumbnail made: (path, thumbnail or None, size, mtime, outcome)."""
    path, size, mtime = entry
    destination = target(path, where, root)
    outcome = make(path, destination)
    return path, destination if outcome == MADE else None, size, mtime, outcome


def current(row: Optional[dict], size: int, mtime_ns: int) -> bool:
    """Whether a thumbnail row still serves an image this size and age: made
    from it as it is, and - if a thumbnail was written - still there."""
    if not row or row.get("size") != size or row.get("mtime_ns") != mtime_ns:
        return False
    return row.get("thumbnail") is None or os.path.isfile(row["thumbnail"])


def pending(db) -> List[Tuple[str, int, int]]:
    """
    Every image the library holds that needs its thumbnail made - none yet,
    or made from the image as it was before: (path, size, modified time in
    ns). One gone from disk is left out.
    """
    todo = []
    for path, thumbnail, size, mtime in db.thumbnail_candidates():
        try:
            stat = os.stat(path)
        except OSError:
            continue
        row = {"thumbnail": thumbnail, "size": size, "mtime_ns": mtime} if size is not None else None
        if not current(row, stat.st_size, stat.st_mtime_ns):
            todo.append((path, stat.st_size, stat.st_mtime_ns))
    return todo


def missing_count(db) -> int:
    """How many of the library's images have no thumbnail row yet - for the
    dialog's estimate: no disk is read, so a changed image is not counted."""
    return sum(1 for _, _, size, _ in db.thumbnail_candidates() if size is None)


def make_many(db, todo: List[Tuple[str, int, int]], stop: Callable[[], bool],
              done: Callable[[str], None], failed: Callable[[str, Exception], None]) -> None:
    """
    Make these thumbnails, threads() at once, recording each chunk as it
    ends. `stop()` is asked between chunks: those made are kept. `done` is
    told each outcome; `failed` each image whose thumbnail could not be
    made - unreadable, or not written - which gets no record and is tried
    again by the next sync.
    """
    where, root = place(), folder()
    with ThreadPoolExecutor(max_workers=threads(), thread_name_prefix="mm-thumbnail") as pool:
        for start in range(0, len(todo), CHUNK):
            if stop():
                return
            futures = [(entry, pool.submit(_one, entry, where, root)) for entry in todo[start:start + CHUNK]]
            made = []
            for entry, future in futures:
                try:
                    path, thumbnail, size, mtime, outcome = future.result()
                except Exception as e:
                    failed(entry[0], e)
                    continue
                made.append((path, thumbnail, size, mtime))
                done(outcome)
            db.record_thumbnails(made)


def for_recorded(db, paths: Iterable[str]) -> None:
    """With the setting on, a thumbnail for each image the recorder just
    wrote, here and now: about 41 ms an image, after Forge has saved it."""
    if not enabled():
        return
    where, root = place(), folder()
    made = []
    for path in dict.fromkeys(p for p in paths if p):
        try:
            stat = os.stat(path)
            path, thumbnail, size, mtime, _ = _one((path, stat.st_size, stat.st_mtime_ns), where, root)
            made.append((path, thumbnail, size, mtime))
        except Exception as e:
            say(f"Could not make a thumbnail of {path}: {e}")
    if made:
        db.record_thumbnails(made)


def forget(db, paths: Iterable[str]) -> int:
    """
    Remove these images' thumbnails - their records and their files - once
    no image's row names them: a delete, Remove folder.

    Returns:
        How many thumbnail files were deleted.
    """
    deleted = 0
    for thumbnail in db.forget_thumbnails(list(paths)):
        try:
            os.remove(thumbnail)
            deleted += 1
        except FileNotFoundError:
            pass
        except OSError as e:
            say(f"Could not delete the thumbnail {thumbnail}: {e}")
            continue
        _tidy(thumbnail)
    return deleted


def _tidy(thumbnail: str) -> None:
    """
    Remove the folders a thumbnail was made into, once they are empty: a
    .thumbnails beside images, a folder's two-letter shard, and the default
    folder itself. A named folder may be the user's own, and stays.
    """
    shard = os.path.dirname(thumbnail)
    name = os.path.basename(shard)
    folders = []
    if name == BESIDE_NAME:
        folders = [shard]
    elif len(name) == 2 and os.path.basename(thumbnail).startswith(name):
        folders = [shard]
        root = os.path.dirname(shard)
        if os.path.normcase(root) == os.path.normcase(default_folder()):
            folders.append(root)
    for each in folders:
        # rmdir removes an empty folder only. A thumbnail being made into it
        # meanwhile fails to save, and is made at the next sync.
        try:
            os.rmdir(each)
        except FileNotFoundError:
            continue
        except OSError:
            return
