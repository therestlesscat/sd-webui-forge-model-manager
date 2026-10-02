"""
Where models live: the folders a scan walks and a download files into.

One table, because it used to be two. The scan knew the command-line options
and walked Stable-diffusion, Lora and VAE; the downloader filed upscalers,
ControlNets, poses and the rest into folders the scan never walked, so a full
scan forgot each one as a file gone from disk.

Every folder a download can write to is one the library walks.
"""
import os
import shutil
from datetime import datetime
from typing import List, Optional

from .forge_host import model_folders


class Folder:
    """
    One kind of model's place on disk.

    `default` is the folder under the WebUI's models path, or None when the
    option itself carries the default (embeddings: both WebUIs give
    --embeddings-dir one, and the original Forge's is not under models).
    `options` are the command-line options naming it - Forge's singular,
    holding one path (--ckpt-dir), and Forge Neo's repeatable plural, holding
    a list (--ckpt-dirs). `download` is False for a folder walked but never
    filed into.
    """

    def __init__(self, default: Optional[str], options=(), download: bool = True):
        self.default = default
        self.options = tuple(options)
        self.download = download


FOLDERS = {
    "Checkpoint": Folder("Stable-diffusion", ("ckpt_dir", "ckpt_dirs")),
    "LORA": Folder("Lora", ("lora_dir", "lora_dirs")),
    "VAE": Folder("VAE", ("vae_dir", "vae_dirs")),
    # No Civitai type is a text encoder: a download lands here when the file,
    # read once it has arrived, says it is one (see proper_place).
    "TextEncoder": Folder("text_encoder", ("text_encoder_dir", "text_encoder_dirs")),
    "TextualInversion": Folder(None, ("embeddings_dir",)),
    "Hypernetwork": Folder("hypernetworks", ("hypernetwork_dir",)),
    "Controlnet": Folder("ControlNet", ("controlnet_dir", "controlnet_dirs")),
    "Upscaler": Folder("ESRGAN", ("esrgan_models_path",)),
    "MotionModule": Folder("MotionModule"),
    "Poses": Folder("Poses"),
    "Wildcards": Folder("Wildcards"),
    "Other": Folder("Other"),
}

#: Civitai types filed with another's files.
SAME_FOLDER_AS = {"LoCon": "LORA", "DoRA": "LORA"}

#: What a file is, as file_identity reads it, to the folder it belongs in.
#: Unknown, and anything not here, belongs nowhere in particular.
FOLDER_FOR_FILE_TYPE = {
    "Checkpoint": "Checkpoint", "LORA": "LORA", "LoCon": "LORA", "LoHa": "LORA", "LoKr": "LORA",
    "DoRA": "LORA", "LyCORIS Full": "LORA", "VAE": "VAE", "Text Encoder": "TextEncoder",
    "TextualInversion": "TextualInversion", "Hypernetwork": "Hypernetwork", "Upscaler": "Upscaler",
}

#: What lies beside a model file under its name, and goes where it goes.
COMPANIONS = (".civitai.info", ".cm-info.json", ".preview.png", ".preview.jpg", ".preview.jpeg",
              ".png", ".jpg", ".images.json")


def option_dirs(cmd_opts, *option_names) -> List[str]:
    """
    The paths these command-line options hold, in order: a single path
    (Forge) or a list (Neo), skipping options the running WebUI does not
    define. Not checked for existence.
    """
    found = []
    for name in option_names:
        value = getattr(cmd_opts, name, None)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            found.extend(str(v) for v in value if v)
        else:
            found.append(str(value))
    return found


def download_dir(model_type: str, cmd_opts=None, models_path: Optional[str] = None) -> str:
    """
    The folder a download of this Civitai type is filed under: the first
    directory an option names that exists, else the type's folder under the
    models path. An unknown type goes to Other.
    """
    if cmd_opts is None and models_path is None:
        cmd_opts, models_path = model_folders()
    models_path = models_path or ""
    model_type = SAME_FOLDER_AS.get(model_type, model_type)
    folder = FOLDERS.get(model_type)
    if folder is None or not folder.download:
        folder = FOLDERS["Other"]

    named = option_dirs(cmd_opts, *folder.options)
    for directory in named:
        if os.path.isdir(directory):
            return directory
    if folder.default is not None:
        return os.path.join(models_path, folder.default)
    # The option carries the default; it may not have been created yet.
    return named[0] if named else os.path.join(models_path, "embeddings")


def library_dirs(cmd_opts=None, models_path: Optional[str] = None) -> List[str]:
    """
    Every folder the library walks, as absolute paths: each one an option
    names, and each kind's folder under the models path. Missing folders and
    duplicates (case-insensitively on Windows) are left out.
    """
    if cmd_opts is None and models_path is None:
        cmd_opts, models_path = model_folders()

    directories = []
    for folder in FOLDERS.values():
        directories.extend(option_dirs(cmd_opts, *folder.options))
    if models_path:
        directories.extend(os.path.join(models_path, folder.default)
                           for folder in FOLDERS.values() if folder.default)

    seen = set()
    result = []
    for directory in directories:
        path = os.path.abspath(str(directory))
        key = os.path.normcase(path)
        if key in seen or not os.path.isdir(path):
            continue
        seen.add(key)
        result.append(path)
    return result


def _roots(cmd_opts, models_path):
    """Every folder of each kind, as (kind, absolute path), longest first."""
    roots = []
    for kind, folder in FOLDERS.items():
        named = option_dirs(cmd_opts, *folder.options)
        if folder.default is not None and models_path:
            named.append(os.path.join(models_path, folder.default))
        roots.extend((kind, os.path.abspath(d)) for d in named if d)
    return sorted(roots, key=lambda r: -len(r[1]))


def folder_of(path: str, cmd_opts=None, models_path: Optional[str] = None):
    """
    The kind of folder a file is in, and that folder: ("VAE", "...\\VAE"), or
    (None, None) for a file outside them all. The innermost wins, so a
    command-line folder inside models/ is its own kind.
    """
    if cmd_opts is None and models_path is None:
        cmd_opts, models_path = model_folders()
    where = os.path.normcase(os.path.abspath(path))
    for kind, root in _roots(cmd_opts, models_path or ""):
        base = os.path.normcase(root)
        if where.startswith(base.rstrip("\\/") + os.sep):
            return kind, root
    return None, None


def proper_place(path: str, file_type: Optional[str], cmd_opts=None,
                 models_path: Optional[str] = None) -> Optional[str]:
    """
    Where a file that is `file_type` belongs, when that is not where it is:
    its type's folder - the one a download of that type goes to - with the
    same subfolders. None when it is in its place, or its type is unknown,
    or it is outside the library's folders.
    """
    if cmd_opts is None and models_path is None:
        cmd_opts, models_path = model_folders()
    belongs = FOLDER_FOR_FILE_TYPE.get(file_type or "")
    kind, root = folder_of(path, cmd_opts, models_path)
    if not belongs or kind is None or kind == belongs:
        return None
    return os.path.join(download_dir(belongs, cmd_opts, models_path), os.path.relpath(path, root))


def companions(path: str) -> List[str]:
    """The files beside this one, under its name, that are there."""
    stem = os.path.splitext(path)[0]
    return [stem + suffix for suffix in COMPANIONS if os.path.exists(stem + suffix)]


def relocate(path: str, to: str) -> bool:
    """
    Move a file, and the companions beside it, to `to`. Nothing is moved -
    and False returned - when the file or any companion would land on
    something already there: nothing is ever written over.
    """
    stem, new_stem = os.path.splitext(path)[0], os.path.splitext(to)[0]
    moves = [(path, to)] + [(c, new_stem + c[len(stem):]) for c in companions(path)]
    if any(os.path.exists(destination) for _, destination in moves):
        return False
    os.makedirs(os.path.dirname(to), exist_ok=True)
    for source, destination in moves:
        shutil.move(source, destination)   # a rename, or a copy across drives
    return True


def file_modified(path: str) -> Optional[str]:
    """
    A file's modified time, as the database stores it: local time, ISO text.
    The one way it is written - needs_check() compares a stored one with a
    fresh one to decide whether a header is read again.
    """
    try:
        return datetime.fromtimestamp(os.stat(path).st_mtime).isoformat()
    except OSError:
        return None


def gone_from_disk(stored_paths, found_paths) -> List[str]:
    """
    The stored paths a walk did not find and that are not on disk.

    A path the walk missed is not evidence on its own: the walk only looks
    for model files, in the library's folders, and a download can land
    elsewhere - a wildcard's .zip, a folder template pointing outside. Only
    a file that is really not there is gone.
    """
    found = set(found_paths)
    return [p for p in stored_paths if p and p not in found and not os.path.exists(p)]
