"""
Sync images (#233): the images already on disk, added to the Generations tab
as generations - from the folders Forge saves results into, read from its
settings at each sync, and folders a person added. The files stay where they
are. Nothing runs unless the person starts it.

A sync, in order:

1. walk each ticked folder, skipping what is not a result - grids, the
   "before" copies, masks, PiD copies, Forge's JPEG copies of large PNGs,
   ControlNet's maps - and what is held already or was deleted with its file
   kept (the removed list);
2. read every new image's generation text (image_text.py);
3. rebuild batches: images of one press become one generation again. With
   text: settings alike, the prompts aside, each seed the one before's plus
   1, each running number the one before's plus 1 - in one library it rebuilt
   all 630 generations the recorder had written. With no text, when the
   person asks: file names that say the same settings, and either a folder
   the library's own images show to be one press, or a gap no longer than
   the one learnt from the images with text;
4. match the files each names - checkpoint, LoRAs, VAE and text encoders -
   in the library;
5. write each press through the recorder's own write, a few hundred at a time.

Cancel during the reading writes nothing; during the writing, what was
written stays, and the next sync adds only the rest.
"""
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from . import forge_host
from .console import say
from .generations import infotext_meta
from .image_text import IMAGE_EXTENSIONS, NamePattern, line_params, lora_hashes, prompt_loras, \
    read_name, read_text
from .install import INSTALL_KEY
from .nsfw import NAME_TO_LEVEL, UNKNOWN, generated_level

# The long job's kind (jobs.py).
KIND = "images"

# The settings a sync keeps, per WebUI (forge_host.DEFAULTS).
FOLDERS_SETTING = "model_manager_image_folders"
FOLDERS_OFF_SETTING = "model_manager_image_folders_off"
LEVEL_SETTING = "model_manager_image_sync_level"
GROUP_SETTING = "model_manager_group_no_text"

# Generations written per transaction.
CHUNK = 200

# Names Forge gives what is not a result: grids, before its number or with
# none, and the copies, at the end.
_GRID = re.compile(r"^(?:\d+-)?(?:grid|xyz_grid|prompt_matrix)(?:-|$)", re.IGNORECASE)
_COPY = re.compile(r"-(?:before-highres-fix|before-color-correction|before-face-restoration|"
                   r"mask|mask-composite|pid)$", re.IGNORECASE)
_NUMBER = re.compile(r"^(\d{4,})(?:-|$)")

# The learnt gap: the gap below which this share of the settings changes the
# file names do not show fall, from at least this many of them. In one
# library 20% gave 27.1 s, and the same on a copy where 9 in 10 changes were
# dropped: images that never change cannot water it down (#233).
GAP_SHARE = 0.20
GAP_LEAST = 20
_GAP_KEY = "image_sync_gap:" + INSTALL_KEY
# A folder shape is trusted to be one press each when this many of its
# folders hold images with text, and this share of those hold one press.
SHAPE_LEAST = 20
SHAPE_SHARE = 0.95
# Keys of an infotext's last line that change with the prompt: a wildcard
# changes them image to image within one press.
_PROMPT_KEYS = re.compile(r"prompt|hashes|template", re.IGNORECASE)
# Keys that say a Hires fix ran, which a txt2img image has and img2img's not.
_HIRES_KEYS = ("Hires upscale", "Hires upscaler", "Hires steps", "Hires resize-1")


# ------------------------------------------------------------------ folders

def _lines(key: str) -> List[str]:
    return [line.strip() for line in str(forge_host.setting(key) or "").splitlines() if line.strip()]


def folders() -> List[Dict[str, Any]]:
    """
    The folders a sync can read: Forge's result folders, read from its
    settings now, then the ones the person added - each {path, key (Forge's
    setting, or None), ticked, forge (whether it is Forge's)}.
    """
    # Forge's folders are kept off by their setting's key, as their paths
    # come from Forge's settings each time; an added folder by its path.
    off = {line.lower() for line in _lines(FOLDERS_OFF_SETTING)}
    found, seen = [], set()
    for entry in forge_host.result_folders():
        seen.add(entry["path"].lower())
        found.append({"path": entry["path"], "key": entry["key"], "forge": True,
                      "ticked": entry["key"].lower() not in off})
    for path in _lines(FOLDERS_SETTING):
        path = os.path.normpath(path)
        if path.lower() not in seen:
            seen.add(path.lower())
            found.append({"path": path, "key": None, "forge": False, "ticked": path.lower() not in off})
    return found


def unticked(listed: List[Dict[str, Any]], ticked: Iterable[str]) -> List[str]:
    """What the off setting keeps for the folders not ticked: a Forge
    folder's key, an added folder's path."""
    ticked = {str(p).lower() for p in ticked}
    return [f["key"] if f["forge"] else f["path"] for f in listed if f["path"].lower() not in ticked]


def add_folder(path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Add a folder to the list a sync reads, kept in this WebUI's settings.

    Returns:
        (the folder as kept, None), or (None, why it was not added).
    """
    path = (path or "").strip().strip('"').strip()
    if not path:
        return None, "Give the folder's full path."
    if not os.path.isabs(path):
        return None, "Give the folder's full path, from its drive."
    path = os.path.normpath(path)
    if not os.path.isdir(path):
        return None, "No such folder."
    if any(f["path"].lower() == path.lower() for f in folders()):
        return None, "That folder is in the list already."
    forge_host.store_settings({FOLDERS_SETTING: "\n".join(_lines(FOLDERS_SETTING) + [path])})
    return path, None


def remove_folder(db, path: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Take an added folder off the list, and remove every generation its syncs
    brought. No file is touched. One of Forge's folders cannot be removed:
    it is unticked instead.

    Returns:
        (how many generations were removed, None), or (None, why not).
    """
    target = os.path.normpath((path or "").strip()).lower()
    listed = next((f for f in folders() if f["path"].lower() == target), None)
    if listed is None:
        return None, "That folder is not in the list."
    if listed["forge"]:
        return None, "Forge saves results there: untick it instead."
    removed = db.delete_synced_from(listed["path"])
    forge_host.store_settings({
        FOLDERS_SETTING: "\n".join(p for p in _lines(FOLDERS_SETTING) if os.path.normpath(p).lower() != target),
        FOLDERS_OFF_SETTING: "\n".join(p for p in _lines(FOLDERS_OFF_SETTING)
                                       if os.path.normpath(p).lower() != target),
    })
    return removed, None


def _maps_folder() -> str:
    return str(forge_host.forge_setting("control_net_detectedmap_dir") or "detected_maps")


def walk(folder: str) -> Iterator[Tuple[str, int, int]]:
    """
    Every result image under a folder, with its subfolders: (path, size,
    modified time in ns). What is not a result is left out: grids, the
    "before" copies, masks, PiD copies, a JPEG beside a PNG of the same name
    - Forge's copy of a large image (export_for_4chan) - and ControlNet's
    maps folder.
    """
    maps = _maps_folder().lower()
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d.lower() != maps]
        pngs = {os.path.splitext(n)[0].lower() for n in filenames if n.lower().endswith(".png")}
        for name in filenames:
            stem, ext = os.path.splitext(name)
            ext = ext.lower()
            if ext not in IMAGE_EXTENSIONS or _GRID.match(stem) or _COPY.search(stem):
                continue
            if ext in (".jpg", ".jpeg") and stem.lower() in pngs:
                continue
            path = os.path.join(dirpath, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            yield path, stat.st_size, stat.st_mtime_ns


def is_new(path: str, size: int, mtime_ns: int, held: set,
           removed: Dict[str, Tuple[Optional[int], Optional[int]]]) -> bool:
    """Whether a sync adds this file: not held already, and not deleted with
    its file kept - unless the file at that path is another now."""
    key = path.lower()
    if key in held:
        return False
    gone = removed.get(key)
    return gone is None or gone != (size, mtime_ns)


def counts(db, entries: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """How many new images each folder holds, by path: a walk, nothing read."""
    held, removed = db.held_image_paths(), db.removed_images()
    return {entry["path"]: sum(1 for path, size, mtime in walk(entry["path"])
                               if is_new(path, size, mtime, held, removed))
            for entry in entries}


# ----------------------------------------------------------------- progress

@dataclass
class ImageSyncProgress:
    """
    What the page is told: the stage ("walking", "reading", "writing"), the
    folder, counts, errors, and how it ended - "done", "cancelled" or
    "failed".
    """
    state: str = "running"
    stage: str = "walking"
    folder: Optional[str] = None
    total: int = 0
    read: int = 0
    generations: int = 0
    images: int = 0
    errors: List[str] = field(default_factory=list)
    error_count: int = 0
    gap: Optional[float] = None
    gap_from: Optional[str] = None
    cancelling: bool = False
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    error: Optional[str] = None

    def note_error(self, message: str) -> None:
        self.error_count += 1
        if len(self.errors) < 50:
            self.errors.append(message)
        say(f"Sync images: {message}")

    def end(self, state: str) -> None:
        self.state, self.finished = state, time.time()

    def fail(self, message: str) -> None:
        self.error = message
        self.end("failed")

    @property
    def is_complete(self) -> bool:
        return self.state != "running"

    def to_dict(self) -> Dict[str, Any]:
        return {"state": self.state, "stage": self.stage, "folder": self.folder,
                "total": self.total, "read": self.read, "generations": self.generations,
                "images": self.images, "errors": list(self.errors), "error_count": self.error_count,
                "gap": self.gap, "gap_from": self.gap_from, "cancelling": self.cancelling,
                "started": self.started, "finished": self.finished, "error": self.error,
                "is_complete": self.is_complete}


# ------------------------------------------------------------------- an image

@dataclass
class _Image:
    path: str
    root: str               # the synced folder it was found under
    source: int             # that folder's number
    mode: str               # txt2img or img2img, by Forge's folder
    size: int
    mtime_ns: int
    number: Optional[int]
    text: Optional[str] = None
    width: int = 0
    height: int = 0
    params: Dict[str, str] = field(default_factory=dict)
    settings: Optional[Tuple] = None     # the last line but the seed and the prompts
    seed: Optional[int] = None
    name: Optional[Dict[str, Any]] = None

    @property
    def folder(self) -> str:
        return os.path.dirname(self.path)


def _seed(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _joins_text(a: _Image, b: _Image) -> bool:
    """One press, both with text: settings alike, the prompts aside, the seed
    one on, the running number one on where both have one."""
    if not (a.text and b.text and a.settings == b.settings and a.seed is not None
            and b.seed == a.seed + 1):
        return False
    return a.number is None or b.number is None or b.number == a.number + 1


def _same_name(a: _Image, b: _Image) -> bool:
    return a.name is not None and b.name is not None and a.name["same"] == b.name["same"]


def _next_number(a: _Image, b: _Image) -> bool:
    return a.number is None or b.number is None or b.number == a.number + 1


def _gap(a: _Image, b: _Image) -> float:
    return abs(b.mtime_ns - a.mtime_ns) / 1e9


def _ordered(images: List[_Image]) -> List[_Image]:
    """A folder's images in the order Forge saved them: by running number
    where every image has one, else by the file's time."""
    if all(i.number is not None for i in images):
        return sorted(images, key=lambda i: (i.number, i.path.lower()))
    return sorted(images, key=lambda i: (i.mtime_ns, i.path.lower()))


def learn_gap(by_folder: Dict[str, List[_Image]]) -> Optional[float]:
    """
    The gap below which GAP_SHARE of the settings changes fall, among
    neighbours with text whose file names match - how soon, at the earliest,
    this person changes what the name does not show. None with fewer than
    GAP_LEAST such changes.
    """
    changes = sorted(_gap(a, b) for images in by_folder.values()
                     for a, b in zip(images, images[1:])
                     if a.text and b.text and _same_name(a, b) and _next_number(a, b)
                     and a.settings != b.settings)
    if len(changes) < GAP_LEAST:
        return None
    return changes[int(GAP_SHARE * (len(changes) - 1))]


def _shape(image: _Image) -> Tuple[int, str]:
    rel = os.path.relpath(image.folder, image.root)
    depth = 0 if rel in (".", "") else rel.count(os.sep)
    return depth, re.sub(r"\d", "9", os.path.basename(image.folder).lower())


def trusted_shapes(groups: Dict[str, List[List[_Image]]]) -> set:
    """
    Folder shapes - depth under the synced folder, and the folder's name
    with every digit as 9 - that the images with text show to be one press
    each: at least SHAPE_LEAST such folders, SHAPE_SHARE of them holding one.
    Forge's [job_timestamp], or an extension adding a folder per task, makes
    such folders; the pattern in Forge's settings may not say so.
    """
    seen: Dict[Tuple[int, str], List[bool]] = {}
    for folder_groups in groups.values():
        texts = [g for g in folder_groups if g[0].text]
        if texts:
            seen.setdefault(_shape(texts[0][0]), []).append(len(texts) == 1)
    return {shape for shape, ones in seen.items()
            if len(ones) >= SHAPE_LEAST and sum(ones) / len(ones) >= SHAPE_SHARE}


def group(images: List[_Image], no_text: bool, gap: Optional[float],
          in_trusted: bool = False) -> List[List[_Image]]:
    """
    One folder's images, in order, as generations. With text, by the batch
    rule. With none, when `no_text`: names that say the same settings, and
    a trusted folder or a gap within the learnt one - or, with none learnt,
    the names alone. Text and no text never join.
    """
    out: List[List[_Image]] = []
    for image in images:
        last = out[-1][-1] if out else None
        joins = False
        if last is not None:
            if image.text and last.text:
                joins = _joins_text(last, image)
            elif no_text and not image.text and not last.text and _same_name(last, image) \
                    and _next_number(last, image):
                joins = in_trusted or gap is None or _gap(last, image) <= gap
        if joins:
            out[-1].append(image)
        else:
            out.append([image])
    return out


# ------------------------------------------------------------------ matching

class _Matcher(object):
    """The library's files, read once for the whole sync."""

    def __init__(self, db):
        from .model_dirs import embedding_folders, lora_folders
        from .resources import _loadable_here
        self.db = db
        self.hashes = db.hash_index()
        self.checkpoints = db.checkpoints_by_stem()
        self.loadable = _loadable_here(lora_folders(), embedding_folders())
        self._by_name: Dict[str, Optional[str]] = {}

    def checkpoint(self, params: Dict[str, str], fields: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """(the checkpoint's path, or None; its name, for one the library lacks)."""
        digest = str(params.get("Model hash") or fields.get("Model hash") or "").strip().lower()
        found = self.hashes.get(digest) if digest else None
        if found and found[1] in (None, "Checkpoint"):
            return found[0], None
        name = str(params.get("Model") or fields.get("Model") or "").strip()
        if not params and name:
            # A file name's [model_name]: the checkpoint by its file name.
            paths = self.checkpoints.get(name.lower()) or []
            if paths:
                return paths[0], None
        return None, (name or None)

    def lora(self, name: str, digest: Optional[str]) -> Optional[str]:
        found = self.hashes.get(digest) if digest else None
        if found:
            return found[0]
        key = name.lower()
        if key not in self._by_name:
            from .resources import files_by_name
            rows = files_by_name(self.db, [{"name": name}], {}, self.loadable)
            self._by_name[key] = (rows.get(key) or {}).get("file_path")
        return self._by_name[key]


def _modules(params: Dict[str, str]) -> List[str]:
    """
    The VAE and text encoders an infotext's `Module N` names, as files, by
    Forge's own list of them. Neo writes each by its file name without the
    extension - `Module 1: sdxl_vae` - where the list is keyed with it.
    """
    known = forge_host.installed_modules()
    by_stem = {os.path.splitext(name)[0].lower(): path for name, path in known.items()}
    paths = []
    for key in sorted(params, key=lambda k: (len(k), k)):
        if not re.fullmatch(r"Module \d+", key):
            continue
        value = str(params[key]).strip()
        if value in ("Use same choices", "Built-in", ""):
            continue
        name = os.path.basename(value)
        path = known.get(value) or known.get(name) or by_stem.get(os.path.splitext(name)[0].lower()) \
            or by_stem.get(name.lower())
        if path:
            paths.append(os.path.normpath(os.path.abspath(path)))
    return paths


# ------------------------------------------------------------------- the job

class ImageSync(object):
    """One sync of the given folders. Never two at once (jobs.py)."""

    def __init__(self, entries: List[Dict[str, Any]], level: int = UNKNOWN, group_no_text: bool = True):
        self.entries = [e for e in entries if e.get("path")]
        self.level = level
        self.group_no_text = group_no_text
        self.progress = ImageSyncProgress()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self.progress.cancelling = True
        self._cancel.set()

    def _cancelled(self) -> bool:
        if self._cancel.is_set():
            self.progress.end("cancelled")
            say("Sync images cancelled")
            return True
        return False

    def run(self) -> None:
        from .db import get_models_db
        db = get_models_db()
        progress = self.progress
        say(f"Sync images: {len(self.entries)} folder(s)")

        held, removed = db.held_image_paths(), db.removed_images()
        gone = [path for path in removed if not os.path.exists(path)]
        if gone:
            db.forget_removed_images(gone)
            say(f"Sync images: {len(gone)} file(s) gone from disk, off the removed list")

        images: List[_Image] = []
        for entry in self.entries:
            progress.folder = entry["path"]
            if not os.path.isdir(entry["path"]):
                progress.note_error(f"not a folder: {entry['path']}")
                continue
            source = db.image_source_id(entry["path"])
            mode = "img2img" if entry.get("key") == "outdir_img2img_samples" else "txt2img"
            for path, size, mtime in walk(entry["path"]):
                if self._cancel.is_set():
                    break
                if is_new(path, size, mtime, held, removed):
                    held.add(path.lower())
                    number = _NUMBER.match(os.path.basename(path))
                    images.append(_Image(path, entry["path"], source, mode, size, mtime,
                                         int(number.group(1)) if number else None))
        if self._cancelled():
            return
        progress.total = len(images)
        say(f"Sync images: {len(images)} new image(s) to read")

        progress.stage = "reading"
        naming = forge_host.naming_patterns()
        try:
            samplers = forge_host.samplers()
        except Exception:
            samplers = None
        file_pattern = NamePattern(naming["file"] or ("[seed]" if naming["in_folders"] else "[seed]-[prompt_spaces]"),
                                   samplers, numbered=naming["numbered"])
        folder_pattern = NamePattern(naming["folder"]) if naming["folder"] else None
        readable: List[_Image] = []
        for image in images:
            if self._cancelled():
                return
            progress.folder = image.root
            try:
                image.text, image.width, image.height = read_text(image.path)
            except Exception as e:
                progress.note_error(f"could not read {image.path}: {e}")
                progress.read += 1
                continue
            image.params = line_params(image.text)
            image.settings = tuple(sorted((k, v) for k, v in image.params.items()
                                          if k != "Seed" and not _PROMPT_KEYS.search(k))) if image.params else None
            image.seed = _seed(image.params.get("Seed"))
            image.name = read_name(image.path, image.root, file_pattern, folder_pattern)
            readable.append(image)
            progress.read += 1

        by_folder: Dict[str, List[_Image]] = {}
        for image in readable:
            by_folder.setdefault(image.folder, []).append(image)
        by_folder = {folder: _ordered(found) for folder, found in by_folder.items()}

        gap, gap_from = learn_gap(by_folder), "learnt"
        if gap is not None:
            db.set_info(_GAP_KEY, repr(gap))
        else:
            stored = db.get_info(_GAP_KEY)
            gap, gap_from = (float(stored), "last learnt") if stored else (None, "names alone")
        progress.gap, progress.gap_from = gap, gap_from
        text_groups = {folder: group(found, False, None) for folder, found in by_folder.items()}
        trusted = trusted_shapes(text_groups)
        if self.group_no_text:
            say("Sync images: images with no text joined " + (
                f"within {gap:.1f} s ({gap_from})" if gap is not None else "by their names alone")
                + (f"; {len(trusted)} folder shape(s) trusted as one press each" if trusted else ""))

        generations: List[List[_Image]] = []
        for found in by_folder.values():
            in_trusted = bool(found) and _shape(found[0]) in trusted
            generations += group(found, self.group_no_text, gap, in_trusted)

        progress.stage = "writing"
        matcher = _Matcher(db)
        for start in range(0, len(generations), CHUNK):
            if self._cancelled():
                return
            chunk = [self._generation(matcher, g) for g in generations[start:start + CHUNK]]
            spelled = db.library_spelling({f for _, _, files in chunk for used in files for f in used})
            chunk = [(g, i, [[spelled.get(f, f) for f in used] for used in files]) for g, i, files in chunk]
            db.record_generations(chunk)
            progress.generations += len(chunk)
            progress.images += sum(len(i) for _, i, _ in chunk)
            progress.folder = generations[start][0].root
        progress.end("done")
        say(f"Sync images: added {progress.images} image(s) as {progress.generations} generation(s)"
            + (f", {progress.error_count} could not be read" if progress.error_count else ""))

    def _generation(self, matcher: _Matcher, images: List[_Image]):
        """One press as the recorder's write takes it: (generation, images, files)."""
        first = images[0]
        rows, used = [], []
        checkpoint_path = checkpoint_name = None
        modules: List[str] = []
        for position, image in enumerate(images):
            fields = (image.name or {}).get("fields", {}) if not image.text else {}
            path, name = matcher.checkpoint(image.params, fields)
            if position == 0:
                checkpoint_path, checkpoint_name = path, name
                modules = _modules(image.params)
            if image.text:
                meta = infotext_meta(image.text, image.width, image.height)
                hashes = lora_hashes(image.params.get("Lora hashes"))
                loras = [{"name": lora["name"], "weight": lora["weight"],
                          "path": matcher.lora(lora["name"], hashes.get(lora["name"]))}
                         for lora in prompt_loras(meta.get("prompt"))]
                level = generated_level(meta)
                row: Dict[str, Any] = {"infotext": image.text, "meta": meta, "prompt": meta.get("prompt"),
                       "negative_prompt": meta.get("negativePrompt"),
                       "hr_prompt": meta.get("Hires prompt") or None,
                       "hr_negative_prompt": meta.get("Hires negative prompt") or None,
                       "subseed": _seed(image.params.get("Variation seed")), "loras": loras}
            else:
                meta = dict(fields)
                if image.width and image.height:
                    meta.setdefault("Size", f"{image.width}x{image.height}")
                level = self.level
                loras = []
                row = {"meta": meta or None}
            row.update({"position": position, "path": image.path, "seed": image.seed or _seed(
                (image.name or {}).get("fields", {}).get("Seed")), "width": image.width,
                "height": image.height, "prompt_nsfw_level": level})
            rows.append(row)
            used.append([f for f in [checkpoint_path, *modules, *(lora["path"] for lora in loras)] if f])
        params = first.params
        mode = first.mode
        if params:
            mode = "img2img" if ("Denoising strength" in params
                                 and not any(k in params for k in _HIRES_KEYS)) else "txt2img"
        generation = {
            "created_at": self._when(first),
            "mode": mode,
            "forge": params.get("Version") or None,
            "prompt": rows[0].get("prompt"),
            "negative_prompt": rows[0].get("negative_prompt"),
            "width": first.width or None,
            "height": first.height or None,
            "checkpoint_path": checkpoint_path,
            "checkpoint_name": checkpoint_name,
            "checkpoint_hash": params.get("Model hash") or None,
            "modules": modules or None,
            "infotext": first.text,
            "image_count": len(rows),
            "prompt_nsfw_level": max(r["prompt_nsfw_level"] for r in rows),
            "source_id": first.source,
        }
        return generation, rows, used

    @staticmethod
    def _when(image: _Image) -> str:
        """When: the time the file's name gives, else the file's own."""
        named = (image.name or {}).get("time")
        moment = named if isinstance(named, datetime) else datetime.fromtimestamp(image.mtime_ns / 1e9)
        return moment.isoformat(timespec="seconds")


def level_of(name: Optional[str]) -> int:
    """A level's name, as the dialog and the setting give it, as a level."""
    return NAME_TO_LEVEL.get(str(name or ""), UNKNOWN)
