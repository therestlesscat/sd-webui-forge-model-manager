"""
Where models live: the folders a sync walks and a download files into.

One table, because it used to be two. Scan Disk knew the command-line options
and walked Stable-diffusion, Lora and VAE; the downloader filed upscalers,
ControlNets, poses and the rest into folders the scan never walked, so a full
scan forgot each one as a file gone from disk.

Every folder a download can write to is one the library walks.
"""
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from . import folder_walk
from .forge_host import forge_setting, is_neo, model_folders, webui_root
from .hashing import read_hashes
from .console import say


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

    `replaced_by` is the option that, given, replaces `default` in the
    WebUI's own loader instead of adding to it - --lora-dir, where --lora-dirs
    adds - in both WebUIs, or in Neo alone when `replaced_in` says "neo"
    (#195). The walk still covers the default: its files are the library's.

    `settings` are the WebUI's own settings that name more folders of the
    kind - ControlNet's control_net_models_path (#197) - and
    `original_only`, (folder under models, option or None) pairs the
    original Forge alone loads beside the kind's own - its other upscalers
    (#198). Both are walked and loaded, and never filed into: a download
    goes where it went.
    """

    def __init__(self, default: Optional[str], options=(), download: bool = True,
                 replaced_by: Optional[str] = None, replaced_in: str = "both",
                 settings=(), original_only=()):
        self.default = default
        self.options = tuple(options)
        self.download = download
        self.replaced_by = replaced_by
        self.replaced_in = replaced_in
        self.settings = tuple(settings)
        self.original_only = tuple(original_only)


# Which options replace a default folder, read from each WebUI's loader:
# networks.py (LoRA), lib_controlnet/global_state.py, shared_items.py
# (hypernetworks, the original Forge's alone) and modelloader.load_upscalers -
# Neo reads --esrgan-models-path alone, the original Forge it and ESRGAN.
# Both ControlNets also read the folder their setting names; the original
# Forge loads every Upscaler subclass, each from its option and its own
# folder under models (cmd_name = <name>_models_path) - HAT has no option.
FOLDERS = {
    "Checkpoint": Folder("Stable-diffusion", ("ckpt_dir", "ckpt_dirs")),
    "LORA": Folder("Lora", ("lora_dir", "lora_dirs"), replaced_by="lora_dir"),
    "VAE": Folder("VAE", ("vae_dir", "vae_dirs")),
    # No Civitai type is a text encoder: a download lands here when the file,
    # read once it has arrived, says it is one (see proper_place).
    "TextEncoder": Folder("text_encoder", ("text_encoder_dir", "text_encoder_dirs")),
    "TextualInversion": Folder(None, ("embeddings_dir",)),
    "Hypernetwork": Folder("hypernetworks", ("hypernetwork_dir",), replaced_by="hypernetwork_dir"),
    "Controlnet": Folder("ControlNet", ("controlnet_dir", "controlnet_dirs"), replaced_by="controlnet_dir",
                         settings=("control_net_models_path",)),
    "Upscaler": Folder("ESRGAN", ("esrgan_models_path",), replaced_by="esrgan_models_path", replaced_in="neo",
                       original_only=(("RealESRGAN", "realesrgan_models_path"), ("DAT", "dat_models_path"),
                                      ("HAT", None), ("SwinIR", "swinir_models_path"),
                                      ("ScuNET", "scunet_models_path"))),
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
    "TextualInversion": "TextualInversion", "Hypernetwork": "Hypernetwork", "Controlnet": "Controlnet",
    "Upscaler": "Upscaler",
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


def lora_folders(cmd_opts=None) -> Optional[List[str]]:
    """
    The folders the running WebUI loads <lora:name> from, as its own walk
    takes them (networks.process_network_files): --lora-dir, then Neo's
    --lora-dirs. Not the library's Lora folders: a library two WebUIs share
    holds the other's too, which this one never walks. None outside a WebUI,
    or one without its LoRA extension, where they are not known.
    """
    if cmd_opts is None:
        cmd_opts, _ = model_folders()
    folders = option_dirs(cmd_opts, *FOLDERS["LORA"].options)
    return [os.path.abspath(f) for f in folders] or None


def embedding_folders(cmd_opts=None) -> Optional[List[str]]:
    """
    The folder the running WebUI loads embeddings from, and walks whole:
    --embeddings-dir, which defaults to its own embeddings folder (both
    WebUIs' ui_extra_networks_textual_inversion.py). An embedding anywhere
    else - the LoRA folder, the other WebUI's - it never loads (#179). None
    outside a WebUI, where it is not known.
    """
    if cmd_opts is None:
        cmd_opts, _ = model_folders()
    folders = option_dirs(cmd_opts, *FOLDERS["TextualInversion"].options)
    return [os.path.abspath(f) for f in folders] or None


def _named_dirs(cmd_opts, models_path: Optional[str]) -> List[str]:
    """
    Every folder the library names, there or not, as absolute paths: each
    one an option or a setting names, and each kind's folder under the
    models path. Duplicates (case-insensitively on Windows) are left out.
    """
    directories = []
    neo = is_neo()
    for folder in FOLDERS.values():
        directories.extend(option_dirs(cmd_opts, *folder.options))
        directories.extend(_more_folders(folder, cmd_opts, models_path, neo))
    if models_path:
        directories.extend(os.path.join(models_path, folder.default)
                           for folder in FOLDERS.values() if folder.default)

    seen = set()
    result = []
    for directory in directories:
        path = os.path.abspath(str(directory))
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def library_dirs(cmd_opts=None, models_path: Optional[str] = None) -> List[str]:
    """
    Every folder the library walks, as absolute paths: each one an option
    names, and each kind's folder under the models path. Missing folders and
    duplicates (case-insensitively on Windows) are left out.
    """
    if cmd_opts is None and models_path is None:
        cmd_opts, models_path = model_folders()
    return [path for path in _named_dirs(cmd_opts, models_path) if os.path.isdir(path)]


def missing_library_dirs(cmd_opts=None, models_path: Optional[str] = None) -> List[str]:
    """
    The folders the library names that are not there - a drive unplugged, a
    share asleep, a kind's folder never made - for the sync to say which
    of them held files it kept (#389).
    """
    if cmd_opts is None and models_path is None:
        cmd_opts, models_path = model_folders()
    return [path for path in _named_dirs(cmd_opts, models_path) if not os.path.isdir(path)]


# .gguf: quantized models Forge loads directly (Flux, Wan, Z-Image...),
# which were never indexed. .sft: safetensors under a short name.
MODEL_EXTENSIONS = {".safetensors", ".sft", ".gguf", ".ckpt", ".pt", ".pth", ".bin"}


def find_model_files(directories: List[str]) -> List[str]:
    """
    Every model file under these folders, as Forge finds them: through
    symbolic links, and each folder once, by the first route to it
    (folder_walk). A folder that is not there gives none.
    """
    model_files = []
    for root, _, files in folder_walk.walk(directories):
        for file in files:
            if os.path.splitext(file)[1].lower() in MODEL_EXTENSIONS:
                model_files.append(os.path.join(root, file))
    return model_files


def _replacing(folder: Folder, cmd_opts, neo: bool) -> Optional[str]:
    """The option that replaces this kind's default folder in this WebUI, when it holds one."""
    if not folder.replaced_by or (folder.replaced_in == "neo" and not neo):
        return None
    return folder.replaced_by if option_dirs(cmd_opts, folder.replaced_by) else None


def _more_folders(folder: Folder, cmd_opts, models_path: Optional[str], neo: bool) -> List[str]:
    """
    A kind's folders beyond its own and its options': those its settings
    name (#197), and in the original Forge those it alone loads (#198).
    """
    found = []
    for key in folder.settings:
        value = forge_setting(key)
        if value and str(value).strip():
            found.append(str(value).strip())
    if not neo:
        for name, option in folder.original_only:
            if option:
                found.extend(option_dirs(cmd_opts, option))
            if models_path:
                found.append(os.path.join(models_path, name))
    return found


def _roots(cmd_opts, models_path, loaded_in_neo: Optional[bool] = None):
    """
    Every folder of each kind, as (kind, absolute path), longest first. With
    `loaded_in_neo` given - whether this is Neo - only those the WebUI's own
    loaders read: less each default an option replaced (#195). A singular
    option holds its default when not given - --lora-dir is models\\Lora -
    so that folder stays, by the option.
    """
    roots = []
    for kind, folder in FOLDERS.items():
        named = option_dirs(cmd_opts, *folder.options)
        replaced = loaded_in_neo is not None and _replacing(folder, cmd_opts, loaded_in_neo)
        if folder.default is not None and models_path and not replaced:
            named.append(os.path.join(models_path, folder.default))
        named.extend(_more_folders(folder, cmd_opts, models_path,
                                   is_neo() if loaded_in_neo is None else loaded_in_neo))
        roots.extend((kind, os.path.abspath(d)) for d in named if d)
    return sorted(roots, key=lambda r: -len(r[1]))


def shown_roots(cmd_opts=None, root: Optional[str] = None) -> List[Tuple[str, str]]:
    """
    What a path the pages show is read from (shownPath, ui_options.mjs), as
    (label, folder), the longest folder first so the innermost names a path:
    each folder the WebUI was given on the command line, by its option -
    --lora-dir\\x.safetensors - then the WebUI's own folder, unnamed -
    models\\text_encoder\\y.safetensors. A path under neither - the other
    WebUI's, sharing the database, in a folder this one was not given - is
    shown whole. An option's folder inside the WebUI's own - the embeddings'
    default, set whether or not it was given - goes by the WebUI's folder.
    """
    if cmd_opts is None and root is None:
        cmd_opts, _ = model_folders()
        root = webui_root()
    root = os.path.abspath(root) if root else ""
    inside = os.path.normcase(root).rstrip("\\/") + os.sep if root else None
    roots = {}
    for folder in FOLDERS.values():
        for name in folder.options:
            for path in option_dirs(cmd_opts, name):
                path = os.path.abspath(path)
                if inside and (os.path.normcase(path) + os.sep).startswith(inside):
                    continue
                roots.setdefault(os.path.normcase(path), ("--" + name.replace("_", "-"), path))
    found = sorted(roots.values(), key=lambda r: -len(r[1]))
    return found + ([("", root)] if root else [])


def _innermost(path: str, roots):
    """The (kind, folder) of these that holds the path, the innermost; (None, None) for none."""
    where = os.path.normcase(os.path.abspath(path))
    for kind, root in roots:
        if where.startswith(os.path.normcase(root).rstrip("\\/") + os.sep):
            return kind, root
    return None, None


def folder_of(path: str, cmd_opts=None, models_path: Optional[str] = None):
    """
    The kind of folder a file is in, and that folder: ("VAE", "...\\VAE"), or
    (None, None) for a file outside them all. The innermost wins, so a
    command-line folder inside models/ is its own kind. Every folder the
    walk covers, loaded or not: whether the WebUI loads it is loads_here's.
    """
    if cmd_opts is None and models_path is None:
        cmd_opts, models_path = model_folders()
    return _innermost(path, _roots(cmd_opts, models_path or ""))


def loads_here(path: str, cmd_opts=None, models_path: Optional[str] = None) -> bool:
    """
    Whether the path is in a folder this WebUI's loaders read (#195): not a
    kind's default folder an option replaced - Neo given --esrgan-models-path
    reads no upscaler from its own models\\ESRGAN - nor the other WebUI's.
    Not whether the file is there.
    """
    if cmd_opts is None and models_path is None:
        cmd_opts, models_path = model_folders()
    return _innermost(path, _roots(cmd_opts, models_path or "", is_neo()))[0] is not None


def ignored_because(path: str, cmd_opts=None, models_path: Optional[str] = None) -> Optional[str]:
    """
    Why this WebUI does not load a file the library walks: the option that
    replaced its folder - "--esrgan-models-path" - for the pages' "Ignored by
    Neo" (#195). None for a file it loads, one gone from disk, and the other
    WebUI's, in a folder this one was not given: not ignored, only not held.
    """
    if cmd_opts is None and models_path is None:
        cmd_opts, models_path = model_folders()
    kind, _ = folder_of(path, cmd_opts, models_path)
    if kind is None or loads_here(path, cmd_opts, models_path):
        return None
    option = _replacing(FOLDERS[kind], cmd_opts, is_neo())
    if not option or not os.path.isfile(path):
        return None
    return "--" + option.replace("_", "-")



def held_here(path: str, cmd_opts=None, models_path: Optional[str] = None) -> bool:
    """
    Whether a library file is held here: on disk, in a folder this WebUI
    loads from - the one meaning of "held" (#188). A row whose file is gone,
    deleted by hand and not yet forgotten by a walk, is not; nor is the other
    WebUI's file, sharing the database, which this one cannot load. What is
    held is Owned in the Civitai Browser, left out of a draw, and not
    downloaded again.
    """
    return bool(path) and os.path.isfile(path) and loads_here(path, cmd_opts, models_path)

def filed_as(file_type: Optional[str], model_class: Optional[str]) -> Optional[str]:
    """
    The type a file is filed by, when it is not where that type goes: its
    own - but a Checkpoint only when Forge's detector took it (`model_class`).
    One known by its layer names alone is something UNet-shaped Forge did not
    take - a ControlNet was, until #118 - and in Stable-diffusion Forge could
    not load it as a checkpoint either.
    """
    if file_type == "Checkpoint" and not model_class:
        return None
    return file_type


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


class SideFiles(NamedTuple):
    """The side files beside a model file under its name: its own, and those it leaves, each with why."""
    own: List[str]
    # (path, "shared" | "embedding"): another model file in the folder has
    # the same name, so they are its too; or a .png that is an embedding.
    kept: List[Tuple[str, str]]


def shares_stem(path: str) -> bool:
    """
    Whether another model file in the folder has this one's name, its
    extension aside: `demo.pt` beside `demo.safetensors`, whose side files
    are found by that name too (#388). The folder is listed once; names are
    compared as the system compares them (on Windows `DEMO.PT` counts), the
    extension in lower case. The file itself is left out by name. A folder
    that cannot be listed raises: nothing tells its side files are this
    file's alone, and a delete keeps them rather than guess.
    """
    folder, name = os.path.split(path)
    own = os.path.normcase(name)
    stem = os.path.normcase(os.path.splitext(name)[0])
    for other in os.listdir(folder or "."):
        if os.path.normcase(other) == own:
            continue
        other_stem, extension = os.path.splitext(other)
        if extension.lower() in MODEL_EXTENSIONS and os.path.normcase(other_stem) == stem:
            return True
    return False


def is_embedding_image(path: str) -> bool:
    """
    Whether a .png is a textual inversion, as the original Forge reads one
    (its `textual_inversion.load_from_file`: the `sd-ti-embedding` text) -
    not a preview. Neo loads none from a picture. One that cannot be read
    is no embedding, and a side file as before.
    """
    try:
        # Here, not at the top: every module asks model_dirs about folders,
        # and only a delete or a move asks this.
        from PIL import Image
        with Image.open(path) as image:      # closed: Windows would not delete it open
            return "sd-ti-embedding" in (getattr(image, "text", None) or {})
    except Exception:
        return False


def companions(path: str) -> SideFiles:
    """
    The files beside this one, under its name, that are there - its own,
    which a delete removes and a move takes, and those it leaves (#388): all
    of them while another model file shares its name, and its `.png` when
    that is an embedding. The file itself may be gone by then: a delete asks
    once the model file is removed.
    """
    stem = os.path.splitext(path)[0]
    present = [stem + suffix for suffix in COMPANIONS if os.path.exists(stem + suffix)]
    if present and shares_stem(path):
        return SideFiles([], [(side, "shared") for side in present])
    own, kept = [], []
    for side in present:
        if side == stem + ".png" and is_embedding_image(side):
            kept.append((side, "embedding"))
        else:
            own.append(side)
    return SideFiles(own, kept)


class MoveFailed(Exception):
    """A move that failed partway and could not take back all it had moved: what was left, and where."""


def _move_one(source: str, destination: str) -> None:
    """
    One file moved, or left where it was - never in both places. Where the
    rename is refused - a file another program holds - shutil.move copies
    it and then removes the original; a refused removal left the copy
    beside it, which every later move found in its way (#388). One that
    cannot be removed either is named in the error.
    """
    # Checked again at the move itself: a file put there since the check
    # of every destination would be written over by the copy, then removed.
    if os.path.exists(destination):
        raise FileExistsError(f"{destination} is already there")
    try:
        shutil.move(source, destination)   # a rename, or a copy across drives
    except Exception as error:
        if os.path.exists(source) and os.path.exists(destination):
            try:
                os.remove(destination)
            except OSError as e:
                say(f"Could not remove the copy {destination}: {e}")
                raise MoveFailed(f"{error}; a copy is left at {destination}") from error
        raise


def _move_all(moves: List[Tuple[str, str]]) -> Tuple[Optional[List[Tuple[str, str]]], Optional[str]]:
    """
    These moves, all or none: none when any would land on something
    already there - nothing is ever written over - answering what is in
    the way. Else the moves made. One that fails partway takes back those
    made before it, last first, and the folders it made, and raises: the
    model file never sits where its row does not name it, half its side
    files left behind (#388). One it cannot take back is named in the error.
    """
    for _, destination in moves:
        if os.path.exists(destination):
            return None, destination
    folder = os.path.dirname(moves[0][1])
    created = []                            # the folders this makes, deepest first
    probe = folder
    while probe and not os.path.exists(probe):
        created.append(probe)
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    os.makedirs(folder, exist_ok=True)
    made = []
    try:
        for source, destination in moves:
            _move_one(source, destination)
            made.append((source, destination))
    except Exception as error:
        left = []
        for source, destination in reversed(made):
            try:
                _move_one(destination, source)
            except Exception as back:
                say(f"Could not move {destination} back to {source}: {back}")
                left.append(destination)
        if left:
            raise MoveFailed(f"{error}; left at {', '.join(left)}") from error
        for empty in created:
            try:
                os.rmdir(empty)
            except OSError:
                break
        raise
    return moves, None


def relocate(path: str, to: str) -> Tuple[Optional[List[Tuple[str, str]]], Optional[str]]:
    """
    Move a file, and its own side files (`companions`), to `to`: the moves
    made, for a put-back to undo exactly. Nothing is moved - None, and the
    path in the way - when the file or a side file would land on something
    already there. Side files another model file shares stay with it, and
    an embedding stays where it is loaded from.
    """
    stem, new_stem = os.path.splitext(path)[0], os.path.splitext(to)[0]
    moves = [(path, to)] + [(c, new_stem + c[len(stem):]) for c in companions(path).own]
    return _move_all(moves)


def put_back(moves: List[Tuple[str, str]]) -> List[str]:
    """
    Moves undone, exactly as `relocate` made them - worked out again, a
    file moved beside another of its name would leave its side files there
    - the model file first, and each on its own: one that cannot go back,
    or whose old place is taken meanwhile, is left where it is and named,
    rather than take the model file back to where its row does not name it.
    A model file that stays keeps its side files with it: sent back alone,
    they would read as whatever now holds its old name. Answers where each
    file left behind is.
    """
    left = []
    for index, (source, destination) in enumerate(moves):
        if index > 0 and moves[0][1] in left:
            left.append(destination)
            continue
        if os.path.exists(source):
            left.append(destination)
            continue
        try:
            _move_one(destination, source)
        except Exception as e:
            say(f"Could not move {destination} back to {source}: {e}")
            left.append(destination)
    return left


def misplaced_files(db) -> List[Dict[str, Any]]:
    """
    Every file in the library sitting in a folder for another type - a VAE
    in Stable-diffusion, where Forge offers it as a checkpoint - with where
    it belongs, what its header says and what said so, and whether a file
    of its name is already there: "same" (the library holds both, with one
    SHA-256), "different" (two SHA-256s), or "exists" (a file it cannot
    compare). Files whose type is Unknown are never among them, nor files
    not on disk: a sync keeps the row of one whose drive is away (#389),
    and its move would fail at every sync.
    """
    found = []
    for row in db.files_with_types():
        to = proper_place(row["file_path"], filed_as(row["file_type"], row["architecture_class"]))
        if not to or not os.path.exists(row["file_path"]):
            continue
        clash = None
        if os.path.exists(to):
            mine = read_hashes(row["file_hashes"]).get("sha256", "")
            theirs = read_hashes((db.get_version(to) or {}).get("file_hashes")).get("sha256", "")
            clash = ("same" if mine == theirs else "different") if mine and theirs else "exists"
        found.append({"path": row["file_path"], "to": to, "file_type": row["file_type"],
                      "identified_by": row["identified_by"], "clash": clash})
    return found


class Moves(NamedTuple):
    """What move_misplaced_files() did."""
    moved: int
    # Left where they are, though another type's: something of that name is
    # already in their own folder.
    not_moved: List[str]
    errors: List[str]


def move_misplaced_files(db) -> Moves:
    """
    Move each of misplaced_files() into its own folder, with its row, pin
    and generations: never over a file. Only ever asked for by its own box.
    """
    moved, not_moved, errors = 0, [], []
    for item in misplaced_files(db):
        path, to = item["path"], item["to"]
        relocated = None
        try:
            in_the_way = to if item["clash"] else None
            if in_the_way is None:
                relocated, in_the_way = relocate(path, to)
            if relocated is None:
                not_moved.append(path)
                # Which file: one of its side files' names can be the one taken.
                say(f"Not moved: {path} - {in_the_way} is already there")
                continue
            db.move_version(path, to)
            moved += 1
            say(f"Moved, as a {item['file_type']}: {path} -> {to}")
        except Exception as e:
            problem = str(e)
            # The file moved first, and its row could not follow - the
            # database locked by the other WebUI sharing it. Where no row
            # names it, the next walk would forget its row, pin and
            # generations, and take it for a new file. So it goes back.
            if relocated:
                left = put_back(relocated)
                if left:
                    problem += f"; left at {', '.join(left)}"
            errors.append(f"{os.path.basename(path)}: could not move it: {problem}")
            say(f"Could not move {path}: {problem}")
    return Moves(moved, not_moved, errors)


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


class Sight:
    """
    Whether a sync can see the place a file not on disk was in (#389): only
    then is its absence evidence that it was deleted.

    A file is not there when it was deleted - and when its drive is
    unplugged, its share asleep, or the junction it was reached through
    leads to a drive that is away. A sync forgot every file on such a drive,
    and the first sync after it came back read each one again from scratch.
    So, going up from the file's folder to the first folder that is there,
    its absence counts only when that folder is its own, or inside a library
    folder the walk read, or holds one - the drive is up, and a folder on it
    was deleted. A link on the way that leads nowhere (there as a link, not a
    folder: junctions and symbolic links alike, in Python 3.10 as in 3.13)
    says the drive behind it is away. Each folder is asked once, and each
    file's folder judged once: on a share asleep every question is a wait.
    """

    def __init__(self, walked: List[str], everywhere: bool = False):
        self.walked = [_as_prefix(p) for p in walked]
        # Asked to forget what it cannot see (the Sync dialog's box): every
        # place counts as seen, and a missing file as deleted, as before #389.
        self.everywhere = everywhere
        self._folders: Dict[str, bool] = {}
        self._verdicts: Dict[str, bool] = {}

    def _there(self, folder: str) -> bool:
        key = os.path.normcase(folder)
        if key not in self._folders:
            self._folders[key] = os.path.isdir(folder)
        return self._folders[key]

    def can_see(self, path: str) -> bool:
        """Whether the place this file was in can be seen: its absence is a deletion."""
        if self.everywhere:
            return True
        folder = os.path.dirname(os.path.abspath(path))
        key = os.path.normcase(folder)
        if key not in self._verdicts:
            self._verdicts[key] = self._judge(folder)
        return self._verdicts[key]

    def _judge(self, folder: str) -> bool:
        if self._there(folder):
            return True
        while True:
            if os.path.lexists(folder):
                return False            # a link that leads nowhere
            above = os.path.dirname(folder)
            if above == folder:
                return False            # nothing there, up to the drive or share
            folder = above
            if self._there(folder):
                break
        where = _as_prefix(folder)
        return any(where.startswith(walked) or walked.startswith(where) for walked in self.walked)


def _as_prefix(folder: str) -> str:
    """A folder as the start of every path inside it, as Windows compares paths: X:\\ once, not X:\\\\."""
    return os.path.normcase(os.path.abspath(folder)).rstrip("\\/") + os.sep


def _missed(stored_paths, found_paths, sight: Sight) -> Tuple[List[str], List[str]]:
    """
    Of the stored paths a walk did not find: those gone - not on disk where
    the sync can see, or found by another route - and those kept, not on
    disk where it cannot.
    """
    found = set(found_paths)
    missed = [p for p in stored_paths if p and p not in found]
    on_disk = {p for p in missed if os.path.exists(p)}
    twice = folder_walk.found_elsewhere(on_disk, found) if on_disk else {}
    gone, kept = [], []
    for p in missed:
        if p in on_disk:
            if p in twice:
                gone.append(p)
        elif sight.can_see(p):
            gone.append(p)
        else:
            kept.append(p)
    return gone, kept


def _sight(walked) -> Sight:
    """The folders walked as a Sight - a sync's own, kept for its length - or the library's, by default."""
    if isinstance(walked, Sight):
        return walked
    return Sight(library_dirs() if walked is None else walked)


def gone_from_disk(stored_paths, found_paths, walked=None) -> List[str]:
    """
    The stored paths a walk did not find and that are not on disk, where the
    sync can see (Sight) - or whose file the walk found by another route.
    `walked`: the folders the walk read, or a Sight of them; the library's
    by default.

    A path the walk missed is not evidence on its own: the walk only looks
    for model files, in the library's folders, and a download can land
    elsewhere - a wildcard's .zip, a folder template pointing outside. Only
    a file that is really not there is gone. Or one stored twice: a loop, or
    a folder reached through a link and directly, gave one file a row by each
    path, and the walk now finds it by one (#348).
    """
    return _missed(stored_paths, found_paths, _sight(walked))[0]


def kept_unseen(stored_paths, found_paths, walked=None) -> List[str]:
    """The stored paths a walk did not find, not on disk where the sync cannot see (Sight): kept."""
    return _missed(stored_paths, found_paths, _sight(walked))[1]


def forget_gone(db, found_paths, walked=None, kept: Optional[List[str]] = None) -> List[str]:
    """
    After a walk of the whole library that found `found_paths`, forget the
    rows of files that are gone - and only those (gone_from_disk). A walk
    that found nothing forgets nothing: that is a drive not mounted or a
    folder setting wrong, not a library emptied. Scan Disk and a full sync
    each did this in their own code, the rule written two ways. `kept`, a
    list, takes the paths kept (kept_unseen), from the same look.

    Returns the paths forgotten.
    """
    if not found_paths:
        say("Walk found no model files; leaving the database alone")
        return []
    gone, unseen = _missed(db.get_all_version_paths(), found_paths, _sight(walked))
    if kept is not None:
        kept.extend(unseen)
    for path in gone:
        db.delete_version(path)
    return gone
