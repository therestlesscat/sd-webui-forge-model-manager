"""
Records other tools keep beside a model file, read for a model Civitai has
deleted (#350).

A sync reads a record in one case only: Civitai knows no file with these
hashes and has no model by the id the record names (SyncService.
_identify_by_sidecar). Its own `.civitai.info` comes first and is read as
before (storage.read_model_payload); this module reads the rest. Some 21
tools write one, in twelve shapes under eleven file names - CivitAI Browser
Neo's `.api_info.json`, Stability Matrix's `.cm-info.json`, Lora Manager's
`.metadata.json`... A file's name does not tell its shape (a `.json` holds
six), so each is read by the keys inside, and turned into the model shape
the fallback takes: the model at the top, its versions under
`modelVersions`, each with its files and their hashes.

What they hold is often wrong for the file beside them: one library's
CivitAI Browser `.json` files held "Model not found" as their ids in 338 of
612, and 10 of 159 `.cm-info.json` named another version than Civitai says
the file is. So each is checked as far as its contents allow, in tiers:

    1  it lists this file's SHA-256
    2  it names this file, at this size, and lists no hash (CivitScraper's own)
    3  ids alone, unchecked - taken only when no record of tiers 1 or 2 sits
       beside the file: one that fails its check says the ids around the
       file are wrong
"""
import json
import os
import re
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from .architecture import PRESET_BY_CLASS
from .storage import as_model_payload

# Beside `<stem>`, in no order that matters: tiers decide.
SUFFIXES = (".civitai.info", ".api_info.json", ".metadata.json", ".cm-info.json", ".cminfo.json",
            ".civitai.json", ".info.json", ".json", ".swarm.json", ".md")
# CiviMeta's: a folder named after the whole file, `<name>.safetensors.civitai/`.
CIVIMETA = (".civitai", "meta.json")

# "sd version" in Forge's notes is Forge's own field: SD1/SD2/SDXL/Other as
# the CivitAI Browsers cut Civitai's label down until 2026-02, Unknown, or a
# Neo preset. Only what is none of those is Civitai's label (Neo from 2026-02).
_NOT_A_BASE_MODEL = ({"", "sd1", "sd2", "sdxl", "other", "unknown", "flux"}
                     | {p.lower() for p in PRESET_BY_CLASS.values()})

_URL_MODEL = re.compile(r"civitai\.[a-z]+/models/(\d+)", re.I)
_URL_VERSION = re.compile(r"modelVersionId=(\d+)", re.I)

# (tier, the model shape) - the shape None when the keys are a record's but no
# ids in it are usable: a checked record that cannot pass, all the same.
Record = Tuple[int, Optional[Dict[str, Any]]]


def _id(value: Any) -> Optional[int]:
    """A Civitai id: a whole number, never the text a tool wrote where one
    was missing ("Model not found", "")."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip()) or None
    return None


def _ids_from_url(text: Any) -> Tuple[Optional[int], Optional[int]]:
    """(model id, version id) from a Civitai page's address in some text."""
    if not isinstance(text, str):
        return None, None
    model, version = _URL_MODEL.search(text), _URL_VERSION.search(text)
    return (int(model.group(1)) if model else None), (int(version.group(1)) if version else None)


def _sd_version(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip().lower() not in _NOT_A_BASE_MODEL:
        return value.strip()
    return None


def _words(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(w) for w in value if w]
    if isinstance(value, str):
        return [w.strip() for w in re.split(r"[,;]", value) if w.strip()]
    return []


def _model(model_id: Optional[int], versions: List[Dict[str, Any]], **fields) -> Optional[Dict[str, Any]]:
    """The model shape, or None without a model id or a version id. A name
    nobody gave stays None, for read() to fill."""
    versions = [v for v in versions if _id(v.get("id"))]
    if not model_id or not versions:
        return None
    for v in versions:
        v["id"] = _id(v["id"])
    return {"id": model_id, "name": None, **{k: v for k, v in fields.items() if v is not None},
            "modelVersions": versions}


def _this_file(model_path: str, sha256: Optional[str]) -> List[Dict[str, Any]]:
    """A version's file list holding only the file beside the record."""
    return [{"name": os.path.basename(model_path), "hashes": {"SHA256": sha256} if sha256 else {}}]


# --------------------------------------------------------------- the shapes
# Each takes a record's JSON (or text) and the model file's path, and gives
# (tier, model shape) or None. Tried in this order; the first that knows the
# keys decides, so the order is the reference doc's: most specific first.

def _civitai_model(data, path) -> Optional[Record]:
    """Civitai's model record (`/models/{id}`): `modelVersions` a list."""
    if not isinstance(data.get("modelVersions"), list):
        return None
    payload = dict(data)
    payload["id"] = _id(data.get("id"))
    payload["modelVersions"] = [dict(v) for v in data["modelVersions"] if isinstance(v, dict)]
    return 1, (payload if payload["id"] else None)


def _civitai_version(data, path) -> Optional[Record]:
    """Civitai's version record (`/model-versions/...`): the model inside."""
    if not isinstance(data.get("model"), dict) or not _id(data.get("modelId")):
        return None
    payload = as_model_payload(data)
    if not payload:
        return 1, None
    payload["id"] = _id(payload.get("id"))
    return 1, (payload if payload["id"] else None)


def _freetool(data, path) -> Optional[Record]:
    """CivitaiFreeTool's `.civitai.info`: `id` is the model's, the version
    in `versionId` and a `version` object, the files at the top."""
    version = data.get("version")
    if not isinstance(version, dict) or "versionId" not in data:
        return None
    creator = data.get("creator")
    return 1, _model(
        _id(data.get("modelId")) or _id(data.get("id")),
        [{"id": data.get("versionId") or version.get("id"), "name": version.get("name"),
          "baseModel": data.get("baseModel") or version.get("baseModel"),
          "trainedWords": _words(data.get("trainedWords")), "description": version.get("description"),
          "publishedAt": version.get("publishedAt") or None,
          "files": [f for f in data.get("files") or [] if isinstance(f, dict)]}],
        name=data.get("name") or None, type=data.get("type") or None, nsfw=data.get("nsfw"),
        tags=data.get("tags") or None, description=data.get("description") or None,
        creator={"username": creator} if isinstance(creator, str) and creator else None)


def _version_alone(data, path) -> Optional[Record]:
    """A version record with no model inside (CivitScraper builds one):
    tier 1 when its files carry hashes, else 2 - by name and size."""
    if ("modelId" not in data or "id" not in data or "versionId" in data
            or "model" in data or "modelVersions" in data):
        return None
    files = [f for f in data.get("files") or [] if isinstance(f, dict)]
    hashed = any(f.get("hashes") for f in files)
    version = {k: v for k, v in data.items() if k != "modelId"}
    version["files"] = files
    return (1 if hashed else 2), _model(_id(data.get("modelId")), [version])


def _pascal(data, path) -> Optional[Record]:
    """Stability Matrix's `.cm-info.json` and Civicomfy's `.cminfo.json`:
    flat, PascalCase. An OpenModelDB upscaler's has no ModelId: nothing."""
    if "ModelId" not in data and "VersionId" not in data:
        return None
    hashes = data.get("Hashes") if isinstance(data.get("Hashes"), dict) else {}
    creator = data.get("AuthorUsername") or data.get("CreatorUsername")
    return 1, _model(
        _id(data.get("ModelId")),
        [{"id": data.get("VersionId"), "name": data.get("VersionName"), "baseModel": data.get("BaseModel"),
          "trainedWords": _words(data.get("TrainedWords")), "description": data.get("VersionDescription"),
          "files": [{"name": data.get("RemoteFileName") or data.get("PrimaryFileName"),
                     "id": _id(data.get("RemoteFileId") or data.get("PrimaryFileId")), "hashes": hashes}]}],
        name=data.get("ModelName") or None, type=data.get("ModelType") if isinstance(data.get("ModelType"), str) else None,
        nsfw=data.get("Nsfw"), tags=data.get("Tags") or None, description=data.get("ModelDescription") or None,
        creator={"username": creator} if creator else None)


def _lora_manager(data, path) -> Optional[Record]:
    """Lora Manager's `.metadata.json`: the file's facts at the top,
    Civitai's version record under `civitai`."""
    inner = data.get("civitai")
    if not isinstance(inner, dict) or "sha256" not in data:
        return None
    found = _civitai_version(inner, path)
    payload = found[1] if found else None
    if not payload:
        return 1, None
    if not payload.get("name") and data.get("model_name"):
        payload["name"] = data["model_name"]
    # Both halves: its own SHA-256 of the file, and Civitai's record listing
    # it - the record is what says which version, and read() holds it to the
    # file's hash. Its own note alone was computed from the file, and would
    # pass whatever version the record names.
    sha = data.get("sha256")
    version = payload["modelVersions"][0]
    if not isinstance(sha, str) or not _lists(version, sha):
        return 1, None
    if not version.get("baseModel") and data.get("base_model"):
        version["baseModel"] = data["base_model"]
    return 1, payload


def _browser_json(data, path) -> Optional[Record]:
    """The CivitAI Browsers' `.json`: ids, the file's own `sha256`, Forge's
    notes beside them. No model name. A tool's 404 left "Model not found"
    as the ids: nothing."""
    if "modelVersionId" not in data or "modelId" not in data:
        return None
    sha = data.get("sha256") if isinstance(data.get("sha256"), str) else None
    return (1 if sha else 3), _model(
        _id(data.get("modelId")),
        [{"id": data.get("modelVersionId"),
          "baseModel": data.get("baseModel") or _sd_version(data.get("sd version")),
          "trainedWords": _words(data.get("activation text")), "files": _this_file(path, sha)}],
        description=data.get("description") or None, tags=data.get("modelTags") or None)


def _snake_ids(data, path) -> Optional[Record]:
    """Flat snake-case ids and no hash (CivitaiManager's `.json`,
    CivitaiFreeTool's): unchecked."""
    if "model_id" not in data or "version_id" not in data:
        return None
    return 3, _model(
        _id(data.get("model_id")),
        [{"id": data.get("version_id"), "name": data.get("version_name") or data.get("version"),
          "baseModel": data.get("base_model"),
          "trainedWords": _words(data.get("trained_words") or data.get("trainedWords")), "files": []}],
        name=data.get("name") or None, type=data.get("type") or None, description=data.get("description") or None)


def _swarm(data, path) -> Optional[Record]:
    """SwarmUI's `.swarm.json`: `modelspec.*` keys, the ids in the page's
    address its description starts with. Unchecked."""
    if not any(str(k).startswith("modelspec.") for k in data):
        return None
    model_id, version_id = _ids_from_url(data.get("modelspec.description"))
    return 3, _model(
        model_id,
        [{"id": version_id, "baseModel": data.get("modelspec.usage_hint") or None,
          "trainedWords": _words(data.get("modelspec.trigger_phrase")), "files": []}],
        name=data.get("modelspec.title") or None,
        creator={"username": data["modelspec.author"]} if data.get("modelspec.author") else None)


def _forge_notes(data, path) -> Optional[Record]:
    """Forge's notes (`sd version`, `activation text`) with a Civitai page's
    address in `notes` (Civitai Shortcut) or `model url` (GustavSO's model
    manager). Without one there are no ids: nothing. Unchecked."""
    if "sd version" not in data and "activation text" not in data:
        return None
    model_id, version_id = _ids_from_url(data.get("model url") or data.get("notes"))
    return 3, _model(
        model_id,
        [{"id": version_id, "baseModel": _sd_version(data.get("sd version")),
          "trainedWords": _words(data.get("activation text")), "files": []}],
        description=data.get("description") or None)


def _civimeta(data, path) -> Optional[Record]:
    """CiviMeta's `meta.json`, its own flattening: `name` the model,
    `versionName`, `hash` the file's SHA-256 - as ComfyUI-Continuity reads
    it; CiviMeta's own source was not found."""
    if "versionId" not in data or "modelId" not in data:
        return None
    creator = data.get("creator")
    return 1, _model(
        _id(data.get("modelId")),
        [{"id": data.get("versionId"), "name": data.get("versionName"), "baseModel": data.get("baseModel"),
          "trainedWords": _words(data.get("trainedWords")), "description": data.get("versionDescription"),
          "files": _this_file(path, data.get("hash") if isinstance(data.get("hash"), str) else None)}],
        name=data.get("name") or None, type=data.get("type") or None, nsfw=data.get("nsfw"),
        tags=data.get("tags") or None, description=data.get("description") or None,
        creator=creator if isinstance(creator, dict) else ({"username": creator} if creator else None))


def _markdown(text: str, path) -> Optional[Record]:
    """ComfyUI-Model-Manager's `.md`: YAML front matter (`modelPage`,
    `baseModel`, `hashes`, `author`), then Markdown."""
    match = re.match(r"\A---\s*\n(.*?)\n---\s*(\n|\Z)", text, re.S)
    if not match:
        return None
    try:
        import yaml
        front = yaml.safe_load(match.group(1))
    except Exception:
        return None
    if not isinstance(front, dict):
        return None
    model_id, version_id = _ids_from_url(front.get("modelPage"))
    hashes = front.get("hashes") if isinstance(front.get("hashes"), dict) else {}
    words = re.search(r"^# Trigger Words\s*\n+(.+)$", text[match.end():], re.M)
    return 1, _model(
        model_id,
        [{"id": version_id, "baseModel": front.get("baseModel"),
          "trainedWords": _words(words.group(1)) if words else [],
          "files": [{"name": os.path.basename(path), "hashes": hashes}]}],
        creator={"username": front["author"]} if front.get("author") else None)


# The order the keys are asked in. Lora Manager's before Civitai's version
# record: its `civitai` object is one. A Browser `.json` (ids + Forge's
# notes) before Forge's notes alone; CiviMeta's last of the camel-case ids.
SHAPES: Tuple[Callable[[Dict[str, Any], str], Optional[Record]], ...] = (
    _civitai_model, _lora_manager, _civitai_version, _freetool, _version_alone, _pascal,
    _browser_json, _snake_ids, _swarm, _forge_notes, _civimeta,
)


def _records(model_path: str) -> Iterator[Tuple[str, Any]]:
    """(the record's name, its parsed JSON or text) for each record there."""
    stem = os.path.splitext(model_path)[0]
    for suffix in SUFFIXES:
        path = stem + suffix
        if path == model_path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        if suffix == ".md":
            yield suffix, text
            continue
        try:
            yield suffix, json.loads(text)
        except ValueError:
            continue
    folder = os.path.join(model_path + CIVIMETA[0], CIVIMETA[1])
    if os.path.isfile(folder):
        try:
            with open(folder, "r", encoding="utf-8") as f:
                yield os.path.basename(model_path) + CIVIMETA[0] + "/" + CIVIMETA[1], json.load(f)
        except (OSError, ValueError):
            pass


def present(model_path: str) -> bool:
    """Whether any record but `.civitai.info` - read at every lookup already
    - sits beside the file. A look at the folder only, nothing opened."""
    stem = os.path.splitext(model_path)[0]
    return (any(os.path.isfile(stem + s) for s in SUFFIXES if s != ".civitai.info")
            or os.path.isfile(os.path.join(model_path + CIVIMETA[0], CIVIMETA[1])))


def _lists(version: Dict[str, Any], sha256: str) -> bool:
    """Whether a version's files list this SHA-256, whatever the case of the
    hash or of its key."""
    want = sha256.upper()
    for f in version.get("files") or []:
        hashes = f.get("hashes") if isinstance(f, dict) else None
        if isinstance(hashes, dict) and any(str(k).lower() == "sha256" and str(h).upper() == want
                                            for k, h in hashes.items()):
            return True
    return False


def _names(version: Dict[str, Any], model_path: str) -> bool:
    """Whether a version's files name this file at its size, to the KB."""
    name = os.path.basename(model_path).lower()
    try:
        size_kb = os.path.getsize(model_path) / 1024
    except OSError:
        return False
    for f in version.get("files") or []:
        if not isinstance(f, dict) or str(f.get("name") or "").lower() != name:
            continue
        listed = f.get("sizeKB", f.get("sizeKb"))
        if isinstance(listed, (int, float)) and abs(listed - size_kb) < 1:
            return True
    return False


def _first(payload: Dict[str, Any], version: Dict[str, Any], model_path: str) -> Dict[str, Any]:
    """The payload with the version that passed first: the one filed. A
    model needs a name (models.name), and many records give none - a
    Browser's `.json`, SwarmUI's: the file's, as its card shows a file with
    no model."""
    payload = dict(payload)
    payload["modelVersions"] = [version] + [v for v in payload["modelVersions"] if v is not version]
    if not payload.get("name"):
        payload["name"] = os.path.splitext(os.path.basename(model_path))[0]
    return payload


def read(model_path: str, sha256: Optional[str]) -> Optional[Tuple[Dict[str, Any], str, bool]]:
    """
    Another tool's record of this file, in the model shape: the version that
    passed its check first in `modelVersions`.

    Returns:
        (payload, the record's name, whether it was checked), or None when no
        record there passes - or, with none of tiers 1 and 2 there, none at all.
    """
    found: List[Tuple[int, str, Dict[str, Any]]] = []
    for name, data in _records(model_path):
        shapes = (_markdown,) if isinstance(data, str) else SHAPES
        if not isinstance(data, (dict, str)):
            continue
        for shape in shapes:
            try:
                record = shape(data, model_path)
            except Exception:
                record = None
            if record is not None:
                tier, payload = record
                if payload:
                    found.append((tier, name, payload))
                elif tier < 3:
                    found.append((tier, name, {"modelVersions": []}))
                break
    checked_there = any(tier < 3 for tier, _, _ in found)
    for wanted in (1, 2):
        for tier, name, payload in found:
            if tier != wanted:
                continue
            if tier == 1:
                version = next((v for v in payload["modelVersions"] if sha256 and _lists(v, sha256)), None)
            else:
                version = next((v for v in payload["modelVersions"] if _names(v, model_path)), None)
            if version is not None:
                return _first(payload, version, model_path), name, True
    if checked_there:
        return None
    for tier, name, payload in found:
        if tier == 3 and payload.get("modelVersions"):
            return _first(payload, payload["modelVersions"][0], model_path), name, False
    return None
