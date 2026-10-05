"""
Which file in the library, or which version on Civitai, an image's resources
are.

An image names the resources it was made with twice: Civitai's list, by
version id, and the infotext's, by hash and by the name its maker had on
disk. Three questions are asked of them: which local file each is - the
chips under a prompt, from the library alone (image_files); what a hash is
on Civitai - the Resources dialog (resolve_hashes); and what a missing one
will be called once downloaded - the chips again, drawn with that name from
the start (missing_files). They were answered inside api/models.py, the
hash lookup twice; the endpoints there now read the request and answer it.

Civitai is asked through `civitai`, a callable the endpoint hands in that
makes the client on first use (lazy_client), so a question the library
answers asks Civitai nothing.
"""
import contextlib
import os
import re
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from .file_identity import LORA_FAMILY, NAMED_IN_PROMPTS
from .hashing import names_this_file
from .model_dirs import folder_of, lora_folders
from .remembered import Remembered

# What a missing resource's file will be called once downloaded, by version
# id, as Civitai answered: the 2,000 most recent, so sending the same image
# again does not ask again.
_MISSING_FILES = Remembered(most=2000)


# The file types a resource can be found by name among: what a chip is for.
# What a prompt names by file name - and a file not read yet, which may be one.
_NAMED_TYPES = set(NAMED_IN_PROMPTS) | {None}


_NUMBERS = re.compile(r"([0-9]+)")


def _natural(text: str) -> list:
    """Forge's natural_sort_key (modules/util.py): numbers as numbers, the
    rest ignoring case - the file's name and its extension apart, as Neo's does."""
    return [[int(part) if part.isdigit() else part.lower() for part in _NUMBERS.split(piece)]
            for piece in os.path.splitext(text)]


def _forge_walk_order(row) -> tuple:
    """
    Where Forge's walk of its LoRA folders reaches a file: folders in natural
    order, then the files in each. networks.py indexes every file by its name
    as it goes, each overwriting the last with that name, so of several files
    named alike the one reached last is the one <lora:name> loads - a
    .safetensors after a .pt of the same name, a later folder after an
    earlier one.
    """
    path = str(row.get("file_path") or "")
    return (_natural(os.path.dirname(path)), _natural(os.path.basename(path)))


def files_by_name(db, named, by_hash, loadable=None) -> dict:
    """
    The library's file for each resource an image names, by the file's name,
    where the resource's hash - if the image gives one - found nothing.

    A file with that name is taken only if it is a LoRA, an embedding, or not
    yet read by a sync; and, where the image gives a hash, only if that hash
    is the file's - so a file that merely shares a name is not taken for the
    one the image used. With no hash, the name alone decides, as it does for
    Forge's <lora:name>: the whole name, never a part of one, and of several
    files with it, the one Forge would load.

    No file has the name, a LoRA whose alias it is: Forge indexes a LoRA by
    its alias too, and puts it in a prompt so. Exactly, as Forge matches one,
    and only an alias one file has: Forge forbids one two files share, and
    looks the name up by file name alone.

    Args:
        named: [{name, hash}], from the image.
        by_hash: what the hashes already found, lower-case hash -> row.
        loadable: (path, file type) -> whether the running WebUI would load
            the file (_loadable_here); None for every file.
    """
    here = (lambda r: loadable(r.get("file_path"), r.get("file_type"))) if loadable else (lambda r: True)
    wanted = [(str(n.get("name") or "").strip(), str(n.get("hash") or "").strip().lower())
              for n in named if isinstance(n, dict)]
    wanted = [(name, h) for name, h in wanted if name and not (h and h in by_hash)]
    rows = db.local_versions_by_name([name for name, _ in wanted])
    aliased = db.local_versions_by_alias([name for name, _ in wanted])
    found = {}
    for name, image_hash in wanted:
        candidates = [r for r in rows.get(name.lower(), []) if r.get("file_type") in _NAMED_TYPES and here(r)]
        if not candidates:
            by_alias = [r for r in aliased.get(name, []) if r.get("file_type") in LORA_FAMILY and here(r)]
            candidates = by_alias if len(by_alias) == 1 else []
        if image_hash:
            match = next((r for r in candidates
                          if names_this_file(r.get("file_hashes"), r.get("file_path"), image_hash)), None)
        else:
            # Several files can have the name: the same LoRA as .safetensors
            # and .pt, or two models in two folders. Forge loads one of them
            # for <lora:name> - the last its walk of the folders reaches - so
            # that is the one taken. It used to take none, and the chip said
            # the image's LoRA was missing with the file right there.
            match = max(candidates, key=_forge_walk_order) if candidates else None
        if match:
            found[name.lower()] = match
    return found


def _as_file(row: Dict[str, Any]) -> Dict[str, Any]:
    """A local file as a chip knows it: its version, the name Forge knows it by
    in a prompt, and what the file itself is (null before a sync has read it)."""
    name = os.path.basename(row.get("file_path") or "")
    return {"version_id": row.get("id"),
            "file_stem": os.path.splitext(name)[0],
            "file_type": row.get("file_type")}


def _loadable_here(folders: Optional[List[str]]) -> Callable[[str, Optional[str]], bool]:
    """
    Whether the running WebUI would load a file as a LoRA, by its path and
    what it is: a chip says "in library" only for one it would (#11). A LoRA
    - or a file no scan has read, unless it sits with the embeddings - only
    in the folders Forge walks for <lora:name>; anything else, as before.
    With the folders not known, every file.
    """
    roots = [os.path.normcase(f).rstrip("\\/") + os.sep for f in folders or ()]

    def loadable(path: str, file_type: Optional[str] = None) -> bool:
        if not roots or (file_type is not None and file_type not in LORA_FAMILY):
            return True
        where = os.path.normcase(os.path.abspath(path or ""))
        if any(where.startswith(root) for root in roots):
            return True
        return file_type is None and folder_of(path)[0] == "TextualInversion"
    return loadable


def image_files(db, version_ids: List[int], hashes: List[str],
                named: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """
    Which local file each of an image's resources is, from the library alone:
    {versions: version id -> file, hashes: hash (lower case) -> file,
    names: name (lower case) -> file, found by its file name or its alias}.
    Only files the running WebUI would load (_loadable_here).
    """
    loadable = _loadable_here(lora_folders())
    types = {}

    def usable(path: str) -> bool:
        # The key lookup knows paths; what each file is, its row says.
        if path not in types:
            types[path] = (db.get_version(path) or {}).get("file_type")
        return loadable(path, types[path])
    by_id, by_hash = db.local_versions_by_key(version_ids, hashes, usable)
    by_name = files_by_name(db, named, by_hash, loadable)
    return {"versions": {str(k): _as_file(v) for k, v in by_id.items()},
            "hashes": {k: _as_file(v) for k, v in by_hash.items()},
            "names": {k: _as_file(v) for k, v in by_name.items()}}


@contextlib.contextmanager
def lazy_client(make: Callable[[], Any]) -> Iterator[Callable[[], Any]]:
    """A callable giving a Civitai client, made on first use and closed after."""
    made = []

    def civitai():
        if not made:
            made.append(make())
        return made[0]
    try:
        yield civitai
    finally:
        if made:
            made[0].close()


# The most hashes one lookup asks Civitai about. Each is its own request, with
# no batch endpoint behind it, and without an API key the rate limit makes each
# one about two seconds: uncapped, one image's 234 hashes took minutes, and held
# the rate every other Civitai request shares. A caller asks again for the rest.
MAX_HASH_LOOKUPS = 20


def resolve_hashes(db, hashes: List[str], civitai: Callable[[], Any],
                   limit: Optional[int] = MAX_HASH_LOOKUPS) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """
    What each hash is: {hash: {hash, version_id, model_id, name, version_name,
    model_type}}, and the hashes not asked about this time.

    Answered cheapest first: this library's own rows, where a version id and
    an AutoV2 hash already sit together; what an earlier lookup recorded; and
    last Civitai, one request per hash - it has no batch endpoint for them -
    and at most `limit` of them (0: none; None: every one). Everything
    Civitai says is recorded, that it has never heard of a hash included, so
    a dead hash is asked about once. A hash Civitai could not be asked about
    is left out.

    Args:
        hashes: lower-case hashes, each once.
    """
    known = db.hashes_from_local_models(hashes)
    known.update({k: v for k, v in db.resolved_hashes(hashes).items() if k not in known})
    missing = [h for h in hashes if h not in known]
    deferred = [] if limit is None else missing[limit:]
    for value in missing if limit is None else missing[:limit]:
        try:
            version = civitai().get_model_by_hash(value)
        except Exception as e:
            # One hash failing must not lose the rest; leave it
            # unresolved rather than recording a wrong answer.
            print(f"[ModelManager] Resolve {value} failed: {e}")
            continue
        db.remember_hash(value, version)
        model = (version or {}).get("model") or {}
        known[value] = {
            "hash": value,
            "version_id": (version or {}).get("id"),
            "model_id": (version or {}).get("modelId"),
            "name": model.get("name"),
            "version_name": (version or {}).get("name"),
            "model_type": model.get("type"),
        }
    return known, deferred


def missing_files(db, wanted: List[Dict[str, Any]], hash_list: List[str],
                  civitai: Callable[[], Any]) -> Dict[str, Dict[str, Any]]:
    """
    What the resources an image names, and the library lacks, will be called
    once downloaded: {versions: version id -> {file_stem, file_type, model_id,
    name, version_name}, or {gone: true}, or {version_gone: true, ...};
    hashes: hash -> version id, or None when Civitai does not know it}.

    A version's name is its file's, as a download names it: the file
    download_service.pick_file_index() would take, from Civitai's model
    payload - one request per hundred models (/models?ids), where nearly every
    resource of Civitai's list carries its model id. A resource named by hash
    alone is turned into a version first (resolve_hashes), at most
    MAX_HASH_LOOKUPS of them asked of Civitai. What could not be asked, or was
    not this time, is absent.

    Args:
        wanted: [{version_id, model_id}]; model_id may be None.
        hash_list: lower-case hashes of resources known by no version, each once.
    """
    from .download_service import pick_file_index

    known, _ = resolve_hashes(db, hash_list, civitai)
    wanted = list(wanted)
    by_hash = {}
    for value in hash_list:
        row = known.get(value)
        if row is None:
            continue
        by_hash[value] = row.get("version_id")
        if row.get("version_id"):
            wanted.append({"version_id": row["version_id"], "model_id": row.get("model_id")})

    model_of = {}
    for item in wanted:
        try:
            version_id = int(item.get("version_id") or 0)
        except (TypeError, ValueError):
            continue
        if version_id:
            model_of[version_id] = model_of.get(version_id) or item.get("model_id") or None

    ask = [v for v in model_of if v not in _MISSING_FILES]
    model_ids = sorted({int(model_of[v]) for v in ask if model_of[v]})
    models = civitai().get_models_by_ids(model_ids) if model_ids else {}
    for version_id in ask:
        model_id = model_of[version_id]
        if model_id:
            model = models.get(int(model_id))
            if model is None:
                _MISSING_FILES[version_id] = {"gone": True}
                continue
            version = next((v for v in model.get("modelVersions") or []
                            if v.get("id") == version_id), None)
            model_type, model_name = model.get("type"), model.get("name")
        else:
            try:
                version = civitai().get_model_version(version_id)
            except Exception as e:
                print(f"[ModelManager] Version {version_id} could not be asked: {e}")
                continue
            if version is None:
                _MISSING_FILES[version_id] = {"gone": True}
                continue
            model_id = version.get("modelId")
            model_type = (version.get("model") or {}).get("type")
            model_name = (version.get("model") or {}).get("name")
        if version is None:
            _MISSING_FILES[version_id] = {"version_gone": True, "model_id": model_id,
                                          "name": model_name, "file_type": model_type}
            continue
        files = version.get("files") or []
        chosen = files[pick_file_index(files)] if files else {}
        _MISSING_FILES[version_id] = {
            "file_stem": os.path.splitext(chosen.get("name") or "")[0] or None,
            "file_type": model_type, "model_id": model_id,
            "name": model_name, "version_name": version.get("name"),
        }

    # Read once each: another request may drop one between asking and reading.
    answers = {str(v): _MISSING_FILES.get(v) for v in model_of}
    return {"versions": {v: answer for v, answer in answers.items() if answer is not None},
            "hashes": by_hash}
