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

A Wan model is also text-to-video or image-to-video, and an image-to-video
one cannot run from txt2img: it has no start frame to be given. Forge's
detector does not say which - it tells I2V by img_emb, which only Wan 2.1
has, so every Wan 2.2 file is WAN21_T2V. The file does: its patch embedding
takes the latent's 16 channels, and an I2V model 20 more, the start frame
and its mask. Where no file can be read, Civitai's baseModel names it.
"""
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from .architecture import preset_for_base_model, read_shapes
from .file_identity import LORA_FAMILY
from .hashing import hash_key
from .identity_store import record_architecture
from .model_dirs import folder_of
from .remembered import Remembered
from .console import say

# At most this many Civitai lookups for one send: an image can name a dozen
# "checkpoints", most of them VAEs and encoders filed as one.
MAX_LOOKUPS = 4

# A Wan model's patch embedding input width -> what it generates. Wan 2.2 5B
# (48) is neither: Neo's detector does not know it.
_WAN_INPUT = {16: "t2v", 36: "i2v"}


# What Send uses of a gallery's own file, by what the file is: the checkpoint
# it loads, the LoRA or embedding a chip names, the VAE or text encoder it
# selects (#134). An upscaler, a ControlNet, a hypernetwork, it does not.
SENT_TYPES = frozenset(("Checkpoint", "TextualInversion", "VAE", "Text Encoder") + LORA_FAMILY)


def send_files(files: Iterable[Dict[str, Any]],
               here: Callable[[str], bool] = lambda path: folder_of(path)[0] is not None) -> Set[str]:
    """
    Of a model's local files, the one Send uses for each version, by path: of
    a type it uses, in this WebUI's folders - a version's copy in another
    WebUI's, sharing the database, is not one this Forge lists - the first
    by path. None for a version with no such file (#133).
    """
    chosen: Dict[Any, str] = {}
    for f in sorted(files, key=lambda f: f.get("file_path") or ""):
        path = f.get("file_path")
        key = f.get("id") if f.get("id") is not None else path
        if path and key not in chosen and f.get("file_type") in SENT_TYPES and here(path):
            chosen[key] = path
    return set(chosen.values())


@dataclass
class SendModel:
    """The model a send is for, and how that was decided."""
    preset: Optional[str] = None
    model_class: Optional[str] = None
    bundled_text_encoder: bool = False
    bundled_vae: bool = False
    source: Optional[str] = None
    video: Optional[str] = None     # "t2v" or "i2v" for a Wan model


# Civitai's answer for a checkpoint an image names but this library does not
# have: ("v", version id) or ("h", hash) -> (baseModel, file names), or None
# for not found. Only answers are kept, not failures, so a network error is
# asked about again next time. The 2,000 most recent: a long session sends
# from many galleries, and an answer forgotten is only asked again.
_remembered = Remembered(most=2000)
_NOT_ASKED = object()


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
        return _from_row(gallery, "file", base_model)

    row = _local_checkpoint(db, file_path, version_ids, hashes)
    if row:
        return _from_row(row, "image")

    gallery_base = base_model or gallery.get("base_model")
    if gallery.get("architecture"):
        return SendModel(preset=gallery["architecture"], source="gallery",
                         video=_video(gallery["architecture"], named=gallery_base))

    preset, named, _ = _image_checkpoint_on_civitai(db, version_ids, hashes, model_name,
                                                    lookup or _ask_civitai)
    if preset:
        return SendModel(preset=preset, source="image_civitai", video=_video(preset, named=named))

    preset = preset_for_base_model(gallery_base)
    return SendModel(preset=preset, source="civitai" if preset else None,
                     video=_video(preset, named=gallery_base))


def image_checkpoint(db, file_path: str = "", version_ids: List[int] = (), hashes: List[str] = (),
                     model_name: str = "", lookup: Callable[[str, str], Optional[dict]] = None,
                     here: Callable[[str], bool] = None) -> Dict[str, Any]:
    """
    The checkpoint an image names, for a send from a gallery that is not a
    checkpoint's (#134) - the one thing such a send cannot go without.

    Returns {"path": file} when the library has it; {"missing": name} when it
    names one the library lacks - by the name the image gives it, the name
    Civitai gives its file, or its hash; {"not_checkpoint": True} when what
    it names as checkpoints is something else, here or on Civitai (a VAE or
    a text encoder filed as one); {} when it names none.
    """
    version_ids = [int(i) for i in version_ids if str(i).strip().isdigit()]
    hashes = [h.strip() for h in hashes if h and h.strip()]
    row = _local_checkpoint(db, file_path, version_ids, hashes, here)
    if row:
        return {"path": row["file_path"]}
    if model_name.strip():
        return {"missing": model_name.strip()}
    if not (version_ids or hashes):
        return {}
    preset, _, name = _image_checkpoint_on_civitai(db, version_ids, hashes, "", lookup or _ask_civitai)
    if preset and name:
        return {"missing": name}
    if hashes:
        # A model hash is the checkpoint's, whatever Civitai knows of it.
        return {"missing": hashes[0]}
    return {"not_checkpoint": True}


def _local_checkpoint(db, file_path: str, version_ids, hashes, here: Callable[[str], bool] = None) -> dict:
    """
    The library's checkpoint the image names, read as a scan reads it: one in
    this WebUI's folders before another's - a library shared with the other
    WebUI holds its copies too - else the first. {} for none.
    """
    here = here or (lambda path: folder_of(path)[0] is not None)
    found = []
    for row in db.versions_named_by(list(version_ids), list(hashes)):
        if row.get("file_path") == file_path:
            continue
        row = _read(db, row["file_path"])
        if row.get("file_type") == "Checkpoint" and row.get("architecture"):
            if here(row["file_path"]):
                return row
            found.append(row)
    return found[0] if found else {}


def _read(db, path: str) -> dict:
    """A version row, its file read first if no scan has read it."""
    try:
        record_architecture(db, path)
    except Exception as e:
        say(f"Could not read {os.path.basename(path)}: {e}")
    return db.get_version(path) or {}


def _from_row(row: dict, source: str, base_model: str = "") -> SendModel:
    return SendModel(preset=row["architecture"], model_class=row.get("architecture_class"),
                     bundled_text_encoder=bool(row.get("bundled_text_encoder")),
                     bundled_vae=bool(row.get("bundled_vae")), source=source,
                     video=_video(row["architecture"], row.get("file_path"),
                                  base_model or row.get("base_model")))


def _video(preset: Optional[str], path: str = "", named: str = "") -> Optional[str]:
    """
    "t2v" or "i2v" for a Wan model, else None - by its file where there is
    one to read, else by the baseModel Civitai gives it.
    """
    if preset != "wan":
        return None
    if path:
        shapes = read_shapes(path) or {}
        for name, (shape, _) in shapes.items():
            if name.endswith("patch_embedding.weight") and len(shape) > 1:
                return _WAN_INPUT.get(shape[1])
    words = re.findall(r"[a-z0-9]+", (named or "").lower())
    if "ti2v" in words:
        return None
    if "i2v" in words:
        return "i2v"
    if "t2v" in words:
        return "t2v"
    return None


def _image_checkpoint_on_civitai(db, version_ids, hashes, model_name,
                                 lookup) -> Tuple[Optional[str], str, str]:
    """
    The preset of a checkpoint the image names that this library lacks, the
    baseModel Civitai gave it, and the name of its file there.

    Several can answer: an image's "checkpoints" include VAEs and encoders
    uploaded as one, whose baseModel is usually "Other" and maps to nothing.
    Of those that map to a preset, the one whose file is named as the image's
    model wins; else the first.
    """
    local_ids, local_hashes = db.local_versions_by_key(list(version_ids), list(hashes))
    keys = [("h", h.lower()) for h in hashes if h and hash_key(h) not in local_hashes] + \
           [("v", str(i)) for i in version_ids if i not in local_ids]
    stem = os.path.splitext(os.path.basename(model_name or ""))[0].lower()

    first = (None, "", "")
    for key in keys[:MAX_LOOKUPS]:
        answer = _remember(key, lookup)
        if not answer:
            continue
        preset = preset_for_base_model(answer[0])
        if not preset:
            continue
        named = [name for name in answer[1] if os.path.splitext(name)[0].lower() == stem]
        if stem and named:
            return preset, answer[0], named[0]
        first = first if first[0] else (preset, answer[0], next(iter(answer[1]), ""))
    return first


def _remember(key, lookup) -> Optional[Tuple[str, List[str]]]:
    known = _remembered.get(key, _NOT_ASKED)
    if known is not _NOT_ASKED:
        return known
    try:
        version = lookup(*key)
    except Exception as e:
        say(f"Could not ask Civitai about {key[1]}: {e}")
        return None
    answer = None
    if version:
        answer = (version.get("baseModel") or "",
                  [f.get("name") or "" for f in version.get("files") or []])
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
