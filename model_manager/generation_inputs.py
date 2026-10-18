"""
The images an img2img generation started from (#34): the selected mode's
source and the layer painted over it - the mask, or the strokes - kept as
PNG files in a store, so Send can put them back and the viewer can show them.

Only the canvases of the mode Forge was sent are kept: Forge's img2img reads
no others for that press (`img2img_function`, the same in Neo and the
original Forge), and scripts see the run's `p.init_images` and
`p.image_mask`, built from these two. The mode is the number Generate sends,
so what is kept is what Forge used, whatever mode the page showed.

A file in the store is named by a hash of its picture's pixels, size and
colour mode: a picture inpainted twenty times is one file. The store sits
beside the database, as the thumbnails do, so two WebUIs sharing a database
share it; each file under its name's first two letters, as a thumbnail is,
so no folder holds them all. Each generation
naming one has a row in `generation_input_files`; a file goes once no row
names it. Generation ids are never reused (AUTOINCREMENT), so after any
delete the rows of generations that are gone are found and cleared here
(`forget`), whichever delete it was - one lock spans that and the recorder's
save-and-record, so a file is never deleted between a press finding it
already there and its row being written.
"""
import hashlib
import os
import threading
import uuid
from typing import Any, Dict, Iterable, List, Optional

from .console import say
from .forge_host import setting

KEEP_SETTING = "model_manager_generations_keep_inputs"
FOLDER_SETTING = "model_manager_generations_inputs_dir"
FOLDER_NAME = "generation-inputs"

# Each img2img mode's canvases, by Forge's own input names - the source
# first, then its layer. Batch (5) reads folders and uploads: nothing here.
MODE_IMAGES = {
    0: ("init_img",),
    1: ("sketch", "sketch_fg"),
    2: ("init_img_with_mask", "init_img_with_mask_fg"),
    3: ("inpaint_color_sketch", "inpaint_color_sketch_fg"),
    4: ("init_img_inpaint", "init_mask_inpaint"),
}
CANVASES = frozenset(name for names in MODE_IMAGES.values() for name in names)
# What each layer is, for drawing it over its source: strokes in colour -
# Sketch's, and Inpaint sketch's, which are its mask too - a mask painted
# over the picture, or a black and white mask uploaded.
LAYER_KINDS = {"sketch_fg": "strokes", "inpaint_color_sketch_fg": "strokes",
               "init_img_with_mask_fg": "mask", "init_mask_inpaint": "mask-upload"}

# Held by the recorder from finding a file in the store to writing the row
# naming it, and by forget() from finding a file unnamed to deleting it.
LOCK = threading.Lock()

_IMAGE_MARKS = ("__image__", "__array__", "__file__")


def keeping() -> bool:
    """Whether img2img generations keep their source and layer."""
    return bool(setting(KEEP_SETTING))


def default_folder() -> str:
    """The store when none is named: generation-inputs beside the database."""
    from .db.database import database_path
    return os.path.join(os.path.dirname(os.path.abspath(database_path())), FOLDER_NAME)


def folder() -> str:
    """The store: the setting, read as the thumbnails' is, else beside the database."""
    named = str(setting(FOLDER_SETTING) or "").strip().strip('"').strip()
    return os.path.normpath(named) if named else default_folder()


def mode_of(fixed: Dict[str, Any]) -> Optional[int]:
    """img2img's mode as a press's named inputs hold it: Forge's number, 0 to 5."""
    try:
        return int(round(float(fixed.get("mode"))))
    except (TypeError, ValueError):
        return None


def mode_images(tab: str, fixed: Dict[str, Any]) -> tuple:
    """The input names of the canvases this press's mode reads; none for txt2img."""
    if tab != "img2img":
        return ()
    return MODE_IMAGES.get(mode_of(fixed), ())


def _is_image(value) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    return isinstance(value, Image.Image)


def _as_image(value):
    """A canvas's value as a PIL image: Forge's canvas sends one, or an array."""
    if value is None:
        return None
    if _is_image(value):
        return value
    if type(value).__name__ == "ndarray":
        from PIL import Image
        return Image.fromarray(value)
    return None


def held_images(tab: str, names: List[str], values: List[Any]) -> Dict[str, Any]:
    """
    The canvases a press's mode reads, from Generate's values in Forge's
    order: {input name: image}. Empty canvases, and every other mode's, are
    left out.
    """
    fixed = dict(zip(names, values))
    held = {}
    for name in mode_images(tab, fixed):
        image = _as_image(fixed.get(name))
        if image is not None:
            held[name] = image
    return held


def file_name(image) -> str:
    """A picture's name in the store: its pixels, size and mode, hashed."""
    digest = hashlib.sha256(f"{image.mode}:{image.width}x{image.height}:".encode())
    digest.update(image.tobytes())
    return digest.hexdigest()[:32] + ".png"


def save(images: Dict[str, Any]) -> Dict[str, str]:
    """
    Each image into the store, unless a file of the same picture is there:
    {input name: path}. Written under a name of its own and renamed into
    place, so two presses saving one picture cannot leave half a file. Call
    with LOCK held, up to the row that names the file.
    """
    store = folder()
    kept = {}
    for name, image in images.items():
        stored = file_name(image)
        path = os.path.join(store, stored[:2], stored)
        if not os.path.isfile(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            part = f"{path}.{uuid.uuid4().hex[:8]}.part"
            try:
                image.save(part, format="PNG")
                os.replace(part, path)
            finally:
                if os.path.exists(part):
                    os.remove(part)
        kept[name] = os.path.normpath(os.path.abspath(path))
    return kept


def from_files(stored: Dict[str, Any], names: Iterable[str]) -> Dict[str, Any]:
    """The images a queued task kept for these inputs, opened: {name: image}.
    One whose file is gone, or never kept, is left out."""
    from PIL import Image
    opened = {}
    for name in names:
        entry = stored.get(name)
        path = entry.get("__image__") or entry.get("__array__") if isinstance(entry, dict) else None
        if not path or not os.path.isfile(path) or not path.lower().endswith(".png"):
            continue
        with Image.open(path) as image:
            image.load()
            opened[name] = image.copy()
    return opened


def drop_files(value: Any) -> Any:
    """A kept value with every file it names said missing: a queued task's
    inputs copied into its generation keep no file of the task's."""
    if isinstance(value, list):
        return [drop_files(v) for v in value]
    if not isinstance(value, dict):
        return value
    for mark in _IMAGE_MARKS:
        if mark in value:
            return {"__missing__": mark.strip("_")}
    return {k: drop_files(v) for k, v in value.items()}


def with_kept(named: Dict[str, Any], kept: Dict[str, str]) -> Dict[str, Any]:
    """A press's named inputs naming the kept files where they said missing."""
    fixed = dict(named.get("fixed") or {})
    for name, path in kept.items():
        fixed[name] = {"__image__": path}
    return {**named, "fixed": fixed}


def source_back(tab: str, named: Optional[Dict[str, Any]]) -> Optional[bool]:
    """
    Whether Send can put back the source of this press's mode: its file is
    named and there. None where there is no source to speak of - txt2img,
    img2img's Batch.
    """
    fixed = (named or {}).get("fixed") or {}
    names = mode_images(tab, fixed)
    if not names:
        return None
    entry = fixed.get(names[0])
    path = entry.get("__image__") or entry.get("__array__") if isinstance(entry, dict) else None
    return bool(path) and os.path.isfile(path)


def forget(db) -> List[str]:
    """
    Clear the rows of generations that are gone, and delete each kept file
    no row names any more. Run after every delete of generations.

    Returns:
        The files deleted.
    """
    deleted = []
    with LOCK:
        for path in db.drop_orphan_input_files():
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    deleted.append(path)
            except OSError as e:
                say(f"Could not delete a kept source image {path}: {e}")
    return deleted
