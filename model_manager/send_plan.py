"""
Which model Send to txt2img should set Forge up for.

Forge's UI preset and the text encoders and VAE to load (forge_modules.py)
depend on the model the image will generate with. That is not always the
model whose gallery the image is in: a LoRA's or a VAE's gallery holds images
made with some checkpoint, and "Qwen-Image - GGUF" on Civitai is a VAE and a
text encoder filed as a Checkpoint. So the answer is the first of these that
gives one:

    file           the gallery's own file, when it is a checkpoint - the
                   send selects it, so it is what Forge loads
    image          the checkpoint the image names, when it is installed -
                   the paste loads it
    gallery        the gallery's file's own model: an Anima LoRA's images
                   were made with an Anima checkpoint
    image_civitai  the checkpoint the image names, when it is not installed:
                   its baseModel, asked of Civitai once and remembered.
                   Forge's preset then brings back the checkpoint last used
                   with it
    civitai        the gallery version's own baseModel on Civitai

Everything read from a file goes through file_identity.py, and is stored.
"""
import os
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .architecture import preset_for_base_model, record_architecture

# At most this many Civitai lookups for one send: an image can name a dozen
# "checkpoints", most of them VAEs and encoders filed as one.
MAX_LOOKUPS = 4


@dataclass
class SendModel:
    """The model a send is for, and how that was decided."""
    preset: Optional[str] = None
    model_class: Optional[str] = None
    bundled_text_encoder: bool = False
    bundled_vae: bool = False
    source: Optional[str] = None


# Civitai's answer for a checkpoint an image names but this library does not
# have: ("v", version id) or ("h", hash) -> (baseModel, file names), or None
# for not found. Only answers are kept, not failures, so a network error is
# asked about again next time.
_remembered: Dict[Tuple[str, str], Optional[Tuple[str, List[str]]]] = {}
_lock = threading.Lock()


def plan_model(db, file_path: str = "", base_model: str = "",
               version_ids: List[int] = (), hashes: List[str] = (),
               model_name: str = "",
               lookup: Callable[[str, str], Optional[dict]] = None) -> SendModel:
    """
    The model a send is for - see the module docstring for the order.

    Args:
        db: The models database.
        file_path: The gallery's file - the version shown.
        base_model: The gallery version's baseModel on Civitai.
        version_ids: The Civitai version ids the image names as checkpoints.
        hashes: The hashes the image names its checkpoint by.
        model_name: The checkpoint's name in the image's generation data.
        lookup: Asks Civitai about ("v", id) or ("h", hash); stands in for
            the network in tests.
    """
    version_ids = [int(i) for i in version_ids if str(i).strip().isdigit()]
    hashes = [h.strip() for h in hashes if h and h.strip()]
    gallery = _read(db, file_path) if file_path else {}
    if gallery.get("file_type") == "Checkpoint" and gallery.get("architecture"):
        return _from_row(gallery, "file")

    for row in db.versions_named_by(list(version_ids), list(hashes)):
        if row.get("file_path") == file_path:
            continue
        row = _read(db, row["file_path"])
        if row.get("file_type") == "Checkpoint" and row.get("architecture"):
            return _from_row(row, "image")

    if gallery.get("architecture"):
        return SendModel(preset=gallery["architecture"], source="gallery")

    preset = _image_checkpoint_on_civitai(db, version_ids, hashes, model_name,
                                          lookup or _ask_civitai)
    if preset:
        return SendModel(preset=preset, source="image_civitai")

    preset = preset_for_base_model(base_model or gallery.get("base_model"))
    return SendModel(preset=preset, source="civitai" if preset else None)


def _read(db, path: str) -> dict:
    """A version row, its file read first if no scan has read it."""
    try:
        record_architecture(db, path)
    except Exception as e:
        print(f"[ModelManager] Could not read {os.path.basename(path)}: {e}")
    return db.get_version(path) or {}


def _from_row(row: dict, source: str) -> SendModel:
    return SendModel(preset=row["architecture"], model_class=row.get("architecture_class"),
                     bundled_text_encoder=bool(row.get("bundled_text_encoder")),
                     bundled_vae=bool(row.get("bundled_vae")), source=source)


def _image_checkpoint_on_civitai(db, version_ids, hashes, model_name, lookup) -> Optional[str]:
    """
    The preset of a checkpoint the image names that this library lacks.

    Several can answer: an image's "checkpoints" include VAEs and encoders
    uploaded as one, whose baseModel is usually "Other" and maps to nothing.
    Of those that map to a preset, the one whose file is named as the image's
    model wins; else the first.
    """
    local_ids = {row.get("id") for row in db.versions_named_by(list(version_ids), [])}
    keys = [("h", h.lower()) for h in hashes if h and not db.versions_named_by([], [h])] + \
           [("v", str(i)) for i in version_ids if i not in local_ids]
    stem = os.path.splitext(os.path.basename(model_name or ""))[0].lower()

    first = None
    for key in keys[:MAX_LOOKUPS]:
        answer = _remember(key, lookup)
        if not answer:
            continue
        preset = preset_for_base_model(answer[0])
        if not preset:
            continue
        if stem and any(os.path.splitext(name)[0].lower() == stem for name in answer[1]):
            return preset
        first = first or preset
    return first


def _remember(key, lookup) -> Optional[Tuple[str, List[str]]]:
    with _lock:
        if key in _remembered:
            return _remembered[key]
    try:
        version = lookup(*key)
    except Exception as e:
        print(f"[ModelManager] Could not ask Civitai about {key[1]}: {e}")
        return None
    answer = None
    if version:
        answer = (version.get("baseModel") or "",
                  [f.get("name") or "" for f in version.get("files") or []])
    with _lock:
        _remembered[key] = answer
    return answer


def _ask_civitai(kind: str, value: str) -> Optional[dict]:
    from .civitai import CivitaiClient
    client = CivitaiClient.from_settings()
    try:
        if kind == "h":
            return client.get_model_by_hash(value)
        return client.get_model_version(int(value))
    finally:
        client.close()
