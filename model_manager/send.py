"""
Send's one place (#302): how Forge is set up before a source's settings go
into its tab - a Civitai image, a generation of your own, a queued task.

One plan for every source (`plan`), asked of one route
(`/model-manager/send/plan`); each source had a route of its own -
`/forge-modules` for a Civitai image, `/generations/{id}/send-plan`,
`/queue/tasks/{id}/send-plan` - until #302. What the tab's loader then sets
is decided here too (`settings`): a Civitai image's infotext, built from its
stored record; a generation's own, the chips' renames applied, or its kept
press replayed; and the schedule type and Hires fix, in the paste's event.
And an image card's sampler and schedule type (`stamp_readings`).

What the page still reads of a Civitai image itself, it sends with the
source: the checkpoint the image names (`imageCheckpoint` in send.mjs), which
also decides whether its Send button is drawn at all; and the chips'
renames. The VAEs it names are read here (`named_modules`), from the
image's stored record.
"""
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

from .console import say
from .db.params_table import (RE_PARAM, image_clip_skip, read_settings_line, record_meta, size_of as _size_of,
                              truthy as _truthy)


# ------------------------------------------------------------- the plan

def plan(db, source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    How to set Forge up for a source, by its `kind`:

        civitai     `image` (its id), the gallery's `file_path` and
                    `base_model`, the checkpoint the page read of it -
                    `version_ids`, `hashes`, `model_name` - and a pick:
                    `use_checkpoint`, with `image_model`
        generation  `generation`, and a pick: `use_checkpoint`, `image_model`
        task        `task`

    A pick (#377) is a checkpoint chosen in the Resources dialog, by the name
    Forge lists it under; `image_model` the Civitai model the page learnt the
    image's checkpoint is of, which tells a pick of the image's own model
    from another's (pick_kind).

    Returns:
        The kind's plan with `kind` added, or None for no such source.
    """
    kind = source.get("kind")
    image_model = int(source.get("image_model") or 0) or None
    if kind == "civitai":
        record = next(iter(db.stored_records([int(source.get("image") or 0)])), None)
        if record is None:
            return None
        answer = civitai_plan(db, source.get("file_path") or "", source.get("base_model") or "",
                              source.get("version_ids") or "", source.get("hashes") or "",
                              source.get("model_name") or "", "", named_modules(record.get("meta")),
                              source.get("use_checkpoint") or "", vae_keys(record.get("meta")),
                              image_model, checkpoint_names(record.get("meta")))
        # The VAE the image names, for a WebUI without Forge's VAE / Text
        # Encoder control: the page selects it by name, as it always did -
        # none with a pick of another model, of whose family it is not (#377).
        answer["named_vae"] = None if answer.get("other_model") else named_vae(record.get("meta"))
    elif kind == "generation":
        answer = generation_plan(db, int(source.get("generation") or 0), source.get("use_checkpoint") or None,
                                 image_model)
    elif kind == "task":
        answer = task_plan(db, int(source.get("task") or 0))
    else:
        raise ValueError(f"No source of kind {kind!r}")
    return None if answer is None else {"kind": kind, **answer}


# ------------------------------------------------- a Civitai image's plan

def _listed_upscaler(db, file_path: str):
    """
    The name Forge lists an upscaler's gallery's file under - or, where it
    does not list that copy, another copy of it the library holds: by its
    Civitai file, then its version. Forge reads the folder it was given
    alone (--esrgan-models-path, else its own), and the same upscaler can
    be in both: the gallery's card showed the copy in the other, and Send
    said "not listed" though Forge offered it (#138).
    """
    from .forge_host import upscaler_name
    name = upscaler_name(file_path)
    if name:
        return name
    row = db.get_version(file_path) or {}
    file_id, version_id = row.get("civitai_file_id"), row.get("id")
    copies = (db.library_files(file_ids=[file_id]) if file_id is not None else []) \
        + (db.library_files(version_ids=[version_id]) if version_id is not None else [])
    tried = {file_path}
    for copy in copies:
        if copy["file_path"] in tried:
            continue
        tried.add(copy["file_path"])
        name = upscaler_name(copy["file_path"])
        if name:
            return name
    return None


def _image_checkpoint(db, file_path: str, version_ids: str, hashes: str, model_name: str,
                      local: Optional[Callable[[], dict]] = None,
                      names: Optional[Dict[int, str]] = None) -> dict:
    """
    The image's checkpoint for a send from a gallery that is not a
    checkpoint's: {checkpoint: Forge's name for it} or {checkpoint_problem}.
    `local`: the library's checkpoint the image names, looked up once for
    the whole plan. `names`: version id -> the name the image's own
    resource entry gives it (checkpoint_names). See civitai_plan().
    """
    from .forge_host import checkpoint_name
    from .model_dirs import loads_here
    from .send_plan import image_checkpoint
    try:
        found = image_checkpoint(db, file_path, version_ids.split(","), hashes.split(","), model_name, local=local,
                                 names=names)
    except Exception as e:
        say(f"Could not work out the image's checkpoint: {e}")
        return {}
    path = found.get("path")
    if path:
        name = checkpoint_name(path)
        if name:
            return {"checkpoint": name}
        reason = "not_listed" if loads_here(path) else "elsewhere"
        return {"checkpoint_problem": {"reason": reason, "name": os.path.basename(path), "path": path}}
    if found.get("missing"):
        return {"checkpoint_problem": {"reason": "missing", "name": found["missing"]}}
    if found.get("unsupported"):
        return {"checkpoint_problem": {"reason": "unsupported", "name": found.get("name") or "",
                                       "base_model": found["unsupported"]}}
    if found.get("not_checkpoint"):
        return {"checkpoint_problem": {"reason": "not_checkpoint"}}
    return {}


def checkpoint_names(meta: Any) -> Dict[int, str]:
    """
    The name the image's own resource list gives each checkpoint version it
    names (`civitaiResources`): "Model - Version", for a stop to name one
    Civitai no longer answers for (#377).
    """
    names: Dict[int, str] = {}
    entries = (meta.get("civitaiResources") if isinstance(meta, dict) else None) or []
    for entry in entries:
        if not isinstance(entry, dict) or str(entry.get("type") or "").lower() != "checkpoint":
            continue
        version_id = entry.get("modelVersionId")
        name = " - ".join(str(part) for part in (entry.get("name"), entry.get("modelVersionName")) if part)
        if str(version_id or "").isdigit() and name:
            names.setdefault(int(version_id), name)
    return names


def _same_path(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def pick_kind(db, path: str, version_ids: List[Any], hashes: List[str],
              model_id: Optional[int] = None, own_path: str = "") -> str:
    """
    What a checkpoint picked in the Resources dialog is to the image (#377),
    for the notice after and for what goes with it:

        own      the image's own file - its path, its hash, or a file of its
                 version where the image names none by hash
        same     the image's file - by its hash, or by Civitai's for its
                 version - held under another Civitai model (#304): the same
                 bytes
        file     another file of the image's version: fp16 for fp32
        version  another version of the image's model (#278)
        model    anything else, or where the image's model is not known

    The image's VAE and text encoders go with all but `model`; Hires fix's
    checkpoint and module and the refiner too. `model_id`: the model the page
    learnt the image's checkpoint is of; else the library's, of its version.
    """
    from .hashing import hash_key
    from .send_plan import named_ids
    version_ids, hashes = named_ids(version_ids, hashes)
    if _same_path(path, own_path):
        return "own"
    if not version_ids and hashes:
        # Named by a hash alone - a generation kept by name: its version and
        # model as Civitai answered for the hash, once asked (#233).
        known = db.resolved_hashes([hash_key(h) for h in hashes])
        version_ids = [int(v["version_id"]) for v in known.values() if v and v.get("version_id")]
        model_id = model_id or next((v.get("model_id") for v in known.values() if v and v.get("model_id")), None)
    row = db.get_version(path) or {}
    by_hash = [r["file_path"] for r in (db.versions_named_by([], hashes) if hashes else []) if r.get("file_path")]
    if any(_same_path(path, p) for p in by_hash):
        return "own" if not version_ids or row.get("id") in version_ids else "same"
    if version_ids and row.get("id") in version_ids:
        return "file" if hashes else "own"
    if version_ids and not hashes:
        # Named by its version alone, the library holding that very file under
        # another Civitai model (#304): matched by the hash Civitai gave for the
        # version's file, which the dialog's lookup asked.
        from .resources import version_file_hashes
        civitai_hashes = version_file_hashes(version_ids)
        if civitai_hashes and any(_same_path(path, r.get("file_path"))
                                  for r in db.versions_named_by([], civitai_hashes)):
            return "same"
    model = model_id
    if not model and version_ids:
        model = next((r.get("model_id") for r in db.library_files(version_ids=version_ids) if r.get("model_id")), None)
    if model and row.get("model_id") and int(row["model_id"]) == int(model):
        return "version"
    return "model"


def _picked(db, use_checkpoint: str) -> Optional[str]:
    """The file Forge lists a pick under, by exactly that name; None for none: gone since the list was drawn."""
    from .forge_host import checkpoint_file
    try:
        return checkpoint_file(use_checkpoint)
    except Exception as e:
        say(f"Could not ask Forge for the checkpoint picked: {e}")
        return None


def family_modules(db, path: str) -> List[str]:
    """
    The VAE / text encoder labels a checkpoint's family needs, picked from
    what Forge offers as a Civitai image's Send picks them with nothing
    named (forge_modules.pick): for a pick of another model (#377), the
    image's own being of the other family. None for SD and SDXL, which bring
    their own.
    """
    from .file_identity import classify_file
    from .forge_host import installed_modules, saved_modules
    from .forge_modules import pick, preferred_modules
    from .send_plan import picked_model
    found = picked_model(db, path)
    if found.preset in (None, "sd", "xl"):
        return []
    installed = installed_modules()
    modules = {label: classify_file(p) for label, p in installed.items()}
    return list(pick(found.model_class, found.preset, found.bundled_text_encoder, found.bundled_vae,
                     modules, saved_modules(found.preset), preferred_modules(found.preset))["select"])


def _gallery_checkpoint(path: str) -> dict:
    """
    A checkpoint's gallery's own file, by the name Forge lists it under:
    {checkpoint} or {checkpoint_problem}, the problem marked `own` for the
    page to name it as the gallery's. The page once guessed the name from a
    folder named Stable-diffusion in the path, and a checkpoint in any other
    folder Forge was given was never selected (#323).
    """
    from .forge_host import checkpoint_name
    from .model_dirs import loads_here
    name = checkpoint_name(path)
    if name:
        return {"checkpoint": name}
    if not os.path.isfile(path):
        reason = "gone"
    else:
        reason = "not_listed" if loads_here(path) else "elsewhere"
    return {"checkpoint_problem": {"reason": reason, "name": os.path.basename(path), "path": path, "own": True}}


def _family_takes(own: Optional[str], own_vae: bool, installed: Dict[str, str], found, answer: dict) -> Optional[str]:
    """
    A VAE's or text encoder's gallery file, sent with a pick of another model
    (#377): kept where the pick's family takes that kind of module, else left
    out and said in `modules_unfit`, as Send leaves out a VAE of another
    family today. One whose kind cannot be read stays.
    """
    from .file_identity import classify_file
    from .forge_modules import CLASS_FOR_PRESET, NEEDS
    if not own:
        return own
    kind = classify_file(installed[own])[0] if own in installed else None
    if kind is None:
        return own
    if found.preset is None:
        fits = True
    elif found.preset in ("sd", "xl"):
        # SD and SDXL bring their text encoders: of a gallery's modules, an SD VAE alone.
        fits = own_vae and kind == "vae_sd"
    else:
        encoders, vae_kind = NEEDS.get(found.model_class or CLASS_FOR_PRESET.get(found.preset) or "", ((), None))
        fits = kind == vae_kind if own_vae else kind in encoders
    if fits:
        return own
    answer["modules_unfit"].append({"name": own, "kind": kind})
    return None


def _listed_label(path: str, installed: dict):
    """The label Forge lists a module file under, by its path; None if it does not list it."""
    wanted = os.path.normcase(os.path.abspath(path))
    return next((label for label, listed in installed.items()
                 if listed and os.path.normcase(os.path.abspath(listed)) == wanted), None)


# A Civitai AIR id: `urn:air:<ecosystem>:<type>:civitai:<model>@<version>`.
_AIR_CIVITAI = re.compile(r"urn:air:[^:]+:[^:]+:civitai:\d+@(\d+)", re.IGNORECASE)


def _held_label(db, installed: dict, hashes: List[str] = (), versions: List[int] = ()) -> Optional[str]:
    """
    The library's module file Forge lists, by a hash an image gives for it,
    else by its Civitai version (#326); of several, preferred_label()'s. A
    file Forge does not list - another of its name shadows it - is none.
    """
    from .forge_modules import preferred_label
    if not hashes and not versions:
        return None
    rows = db.versions_named_by(list(versions), list(hashes))
    return preferred_label({label for label in (_listed_label(row["file_path"], installed)
                                                for row in rows if row.get("file_path")) if label})


def civitai_plan(db, file_path: str = "", base_model: str = "", version_ids: str = "", hashes: str = "",
                 model_name: str = "", vae: str = "", module: List[str] = (), use_checkpoint: str = "",
                 vae_keys: Optional[Dict[str, Any]] = None, image_model: Optional[int] = None,
                 names: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    """
    What Send to txt2img should set up in Forge before sending a Civitai image.

    The UI preset for the model the image will generate with, and the text
    encoders and VAE it needs that its file does not bring, picked from what
    Forge offers. Which model that is: see send_plan.py. It reads file
    headers, and may ask Civitai once.

    Args:
        file_path: The gallery's file - the version shown.
        base_model: The gallery version's baseModel on Civitai.
        version_ids: Comma-separated Civitai version ids the image names as
            checkpoints.
        hashes: Comma-separated hashes the image names its checkpoint by.
        model_name: The checkpoint's name in the image's generation data.
        vae: The VAE the image's generation data names, if any.
        module: Every module it names - its VAE, then each `Module N` Forge
            wrote (#204) - once per name.
        vae_keys: What else says which VAE it used (vae_keys()): its VAE's
            name among `module`, the hashes it gives for it, the Civitai
            versions civitaiResources lists as one - for a VAE no name finds
            (#326).
        use_checkpoint: Send with this checkpoint, by the name Forge lists
            it under, not the one the image names: picked in the Resources
            dialog (#377; until then a version id, #278). It stands for the
            image's checkpoint - its preset, the file loaded - and in a
            checkpoint's gallery for the gallery's own file. The answer's
            `instead` names its file and `pick` what it is to the image
            (pick_kind); `other_model` is true for another model's, which
            takes none of the image's VAE and text encoders - its family's
            instead - and leaves out a VAE's or text encoder's gallery file
            its family does not take. A name Forge does not list (any more)
            is the stop, `missing`.
        image_model: The Civitai model the page learnt the image's
            checkpoint is of (pick_kind).
        names: Version id -> the name the image's resource list gives it,
            for a stop to name one Civitai does not answer for.

    Returns:
        preset: Forge's UI preset, or null if unknown. source: how it was
        decided (send_plan.py). embeddings: the kind of embedding the model
        loads (forge_host.embedding_kind), for the chips to say which Forge
        skips (#179). manage_modules: whether modules are this call's
        business at all - SD and SDXL checkpoints bring their own, and keep
        the image's VAE as before. select: labels to select; missing: kinds
        nothing installed is; not_found: file names the settings give that
        are not installed. target: exactly what the VAE / Text Encoder
        control should hold once the image is sent - `select` for a model
        whose modules are managed, else the image's modules as Forge lists
        them, or nothing - of a managed model, the image's own file of each
        kind before the plan's pick; modules_not_found: the names the image
        gives that this install does not have. bundled: the kinds the model
        needs that the checkpoint carries itself, and so are not selected -
        for the page to say so, as an empty control otherwise reads as a
        send that failed.

        From a gallery that is not a checkpoint's (#134): checkpoint, the
        name Forge lists the image's checkpoint under, to select; or
        checkpoint_problem, why it cannot be - {reason: missing, name},
        {reason: elsewhere | not_listed, name, path} for one the library has
        in a folder this WebUI does not load, or that Forge has not listed
        yet, {reason: unsupported, name, base_model} for one of a family no
        UI preset runs, {reason: not_checkpoint} - and the page sends
        nothing. From a
        checkpoint's, the same two for its own file (#323), the problem
        marked `own` - {reason: gone} for a file no longer on disk. From a
        VAE's or a text encoder's, that file is in `target` in its kind's
        place; own_not_listed, its name when Forge does not list it. From an
        upscaler's, upscaler: the name Forge lists it under, for Hires fix's;
        upscaler_not_listed, its file's when Forge does not.
    """
    from .file_identity import classify_file
    from .forge_host import embedding_kind, installed_modules, saved_modules
    from .forge_modules import CLASS_FOR_PRESET, NEEDS, match_module, pick, preferred_modules
    from .send_plan import SendModel, local_checkpoint, named_ids, picked_model, plan_model

    # The library's checkpoint the image names: the model to set up for and
    # the checkpoint to load both start from it, looked up once (#302).
    looked_up: Dict[str, dict] = {}

    def local() -> dict:
        if "row" not in looked_up:
            looked_up["row"] = local_checkpoint(db, file_path, *named_ids(version_ids.split(","), hashes.split(",")))
        return looked_up["row"]

    # A pick (#377) stands for the image's checkpoint, whatever the image
    # names: its preset, its modules, the file loaded.
    picked = _picked(db, use_checkpoint) if use_checkpoint else None
    kind = None
    if picked:
        kind = pick_kind(db, picked, version_ids.split(","), hashes.split(","), image_model,
                         (local() or {}).get("file_path") or "")
    try:
        if picked:
            found = picked_model(db, picked)
        else:
            found = plan_model(db, file_path, base_model,
                               version_ids.split(","), hashes.split(","), model_name, local=local)
    except Exception as e:
        say(f"Could not work out the architecture: {e}")
        found = SendModel()
    preset, model_class, source = found.preset, found.model_class, found.source
    bundled_te, bundled_vae = found.bundled_text_encoder, found.bundled_vae

    answer = {"success": True, "preset": preset, "model_class": model_class,
              "source": source, "video": found.video,
              "manage_modules": preset not in (None, "sd", "xl"),
              "embeddings": embedding_kind(model_class, preset),
              "select": [], "missing": [], "needed": [], "not_found": [],
              "target": [], "modules_not_found": [], "modules_unfit": [], "bundled": [],
              "checkpoint": None, "checkpoint_problem": None, "own_not_listed": None,
              "upscaler": None, "upscaler_not_listed": None, "other_model": kind == "model"}
    gallery_type = ((db.get_version(file_path) or {}).get("file_type") if file_path else None)
    if use_checkpoint and not picked:
        # Gone from Forge's list since the dialog drew it: the stop, as for
        # the image's own checkpoint.
        answer["checkpoint_problem"] = {"reason": "missing", "name": use_checkpoint}
    elif picked:
        # In a checkpoint's gallery too: the pick takes the gallery file's place.
        answer["checkpoint"] = use_checkpoint
        if kind != "own":
            answer.update({"instead": os.path.basename(picked), "pick": kind})
    elif gallery_type == "Checkpoint":
        answer.update(_gallery_checkpoint(file_path))
    else:
        answer.update(_image_checkpoint(db, file_path, version_ids, hashes, model_name, local, names))
    if gallery_type == "Upscaler":
        answer["upscaler"] = _listed_upscaler(db, file_path)
        answer["upscaler_not_listed"] = None if answer["upscaler"] else os.path.basename(file_path)

    # The gallery's own VAE or text encoder, as Forge lists it: the
    # primary, which nothing picked for the image takes the place of.
    installed = installed_modules()
    own = None
    if gallery_type in ("VAE", "Text Encoder"):
        own = _listed_label(file_path, installed)
        answer["own_not_listed"] = None if own else os.path.basename(file_path)
    own_vae = gallery_type == "VAE"

    # The modules the image names, as Forge lists them (#204): its VAE,
    # and each `Module N` - Forge's own record of what was selected. By name
    # first; a Civitai AIR id by its version; and a VAE no name finds by a
    # hash the image gives for it, else the version civitaiResources lists
    # (#326). Not the hash first: where a name found a file, A1111's `VAE
    # hash` named a VAE of the other family - SD 1.5 for SDXL, or the
    # reverse - 277 times in 449 on one library, the name 7 in 9,416. A pick
    # of another model takes none of them (#377): they are of the image's.
    keys = (vae_keys or {}) if kind != "model" else {}
    if kind == "model":
        vae, module = "", ()
        own = _family_takes(own, own_vae, installed, found, answer)
    vae_name = keys.get("name")
    by_hash = _held_label(db, installed, hashes=keys.get("hashes") or [])
    names = list(dict.fromkeys(n.strip() for n in [vae, *module] if n and n.strip()))

    def by_name(name: str) -> Optional[str]:
        label = match_module(name, installed)
        air = None if label else _AIR_CIVITAI.fullmatch(name)
        return _held_label(db, installed, versions=[int(air.group(1))]) if air else label

    named, unlisted = [], []
    for name in names:
        if name == vae_name:
            label = by_name(name) or by_hash or _held_label(db, installed, versions=keys.get("versions") or [])
        else:
            label = by_name(name)
        if label is None:
            unlisted.append(name)
        elif label not in named:
            named.append(label)
    if vae_name not in names:
        label = by_hash or _held_label(db, installed, versions=keys.get("versions") or [])
        if label and label not in named:
            named.insert(0, label)

    if not answer["manage_modules"]:
        # SD and SDXL bring their own: what the image names, if anything;
        # a VAE's gallery takes the VAE's place. A VAE of another family, by
        # the file's own tensors, is left out and said (#303): 85 of one
        # library's SDXL images named the Flux VAE (16 latent channels, where
        # SD and SDXL decode 4) or a Wan one. One whose kind cannot be read
        # stays, as named.
        kinds = {label: classify_file(installed[label])[0] for label in named}
        unfit = [label for label in named if str(kinds[label] or "").startswith("vae") and kinds[label] != "vae_sd"]
        answer["modules_unfit"] += [{"name": label, "kind": kinds[label]} for label in unfit]
        named = [label for label in named if label not in unfit]
        if own and own_vae:
            named = [label for label in named
                     if not str(classify_file(installed[label])[0] or "").startswith("vae")]
        answer["target"] = list(dict.fromkeys(label for label in (*named, own) if label))
        answer["modules_not_found"] = unlisted
        return answer

    # What the checkpoint brings itself, of what its model needs: seen to
    # work with nothing selected for Krea 2 (Qwen3-VL 4B) and Flux.1
    # (CLIP-L, T5-XXL, ae) all-in-one checkpoints in Forge Neo 2.29.1.
    encoders, vae_kind = NEEDS.get(model_class or CLASS_FOR_PRESET.get(preset or "") or "", ((), None))
    answer["bundled"] = ((list(encoders) if bundled_te else [])
                         + ([vae_kind] if vae_kind and bundled_vae else []))
    modules = {label: classify_file(path) for label, path in installed.items()}
    answer.update(pick(model_class, preset, bundled_te, bundled_vae,
                       modules, saved_modules(preset), preferred_modules(preset), own, own_vae,
                       named))
    if answer["named_unused"]:
        say(f"Send: the image names {', '.join(answer['named_unused'])}, which a {preset} model "
            "does not use; left out")
    answer["modules_not_found"] = unlisted
    answer["target"] = list(answer["select"])
    return answer


# ------------------------------------------------- the VAEs an image names

# A VAE field that names no file: the checkpoint's own, which an empty
# selection already gives. Seen in one library: "Default (model)" 131,
# "automatic" 30, "Default" 14, "Baked VAE" 5.
_NOT_A_FILE = re.compile(r"(?:automatic|none|null|default.*|baked vae|use same vae)", re.IGNORECASE)
_MODULE_KEY = re.compile(r"Module (\d+)")


def _is_file_name(value: Any) -> bool:
    """Whether a VAE field names a file, or says "the checkpoint's own"."""
    name = str(value if value is not None else "").strip()
    return bool(name) and not _NOT_A_FILE.fullmatch(name)


def named_vae(meta: Any) -> Optional[str]:
    """
    The VAE an image was made with, whatever Civitai called the field.

    Counted over 67,458 stored images, a VAE name turns up under several
    spellings, and they do not overlap: `VAE` 11,304, the usual A1111 field;
    `vaes` 2,392, a list from ComfyUI workflows Civitai normalised, none of
    them with a VAE field; `vae_name` 62, ComfyUI's own node field; `Vae` /
    `vae` 13. "VAE hash" is not read: it names a file we cannot.
    """
    if not isinstance(meta, dict):
        return None
    direct = next((meta.get(k) for k in ("VAE", "Vae", "vae", "vae_name") if _truthy(meta.get(k))), None)
    if isinstance(direct, str) and _is_file_name(direct):
        return direct.strip()
    vaes = meta.get("vaes")
    listed = next((v for v in vaes if isinstance(v, str) and _is_file_name(v)), None) if isinstance(vaes, list) else None
    if listed:
        return listed.strip()
    resources = meta.get("resources") if _truthy(meta.get("resources")) else []
    resource = next((r for r in (resources if isinstance(resources, list) else [])
                     if _truthy(r) and isinstance(r, dict) and r.get("type") == "vae"), None)
    if resource and _truthy(resource.get("name")):
        return resource["name"]
    return None


def vae_keys(meta: Any) -> Dict[str, Any]:
    """
    What besides a name says which VAE an image used (#326): `name`, the
    VAE named_vae() reads; `hashes` its data gives for it - the `resources`
    entry naming it, A1111's `VAE hash` - and `versions`, the Civitai
    versions its `civitaiResources` lists as a VAE. Of one library's
    images, 97 and 287 gave a hash a file here has, and 1,245 their VAE
    only as such a version.
    """
    if not isinstance(meta, dict):
        return {"name": None, "hashes": [], "versions": []}
    name = named_vae(meta)
    name = name.strip() if isinstance(name, str) else name
    resources = meta.get("resources") if isinstance(meta.get("resources"), list) else []
    hashes = [str(r["hash"]).strip() for r in resources
              if isinstance(r, dict) and r.get("type") == "vae" and _truthy(r.get("hash"))
              and (name is None or str(r.get("name") or "").strip() == name)]
    if isinstance(meta.get("VAE hash"), str) and meta["VAE hash"].strip():
        hashes.append(meta["VAE hash"].strip())
    listed = meta.get("civitaiResources") if isinstance(meta.get("civitaiResources"), list) else []
    versions = [int(r["modelVersionId"]) for r in listed
                if isinstance(r, dict) and str(r.get("type") or "").lower() == "vae"
                and str(r.get("modelVersionId") or "").isdigit()]
    return {"name": name, "hashes": list(dict.fromkeys(hashes)), "versions": list(dict.fromkeys(versions))}


def named_modules(meta: Any) -> List[str]:
    """
    Every module an image names (#204): its VAE as named_vae() reads it, then
    each `Module N` - how Forge writes the VAE / Text Encoder selection into
    an image's data, the only place many images name them - in order, each
    once, ignoring case. Read for every kind of model.
    """
    if not isinstance(meta, dict):
        return []
    numbered = sorted(((int(m.group(1)), key) for key in meta for m in [_MODULE_KEY.fullmatch(key)] if m),
                      key=lambda pair: pair[0])
    names = [name.strip() for name in [named_vae(meta), *(meta[key] for _, key in numbered)]
             if isinstance(name, str) and _is_file_name(name)]
    seen = set()
    return [name for name in names if not (name.lower() in seen or seen.add(name.lower()))]


# ------------------------- a Civitai image's settings, as Forge's paste reads them
# Ported from the page (#302): buildInfotext and unquotePrompt in send.mjs,
# the sampler reading in samplers.mjs, videoSize in wan.mjs. The page built
# this text from the same stored record; check 1 holds the two to the same
# text for every stored image (tests/work/r302/).

def _js_text(value: Any) -> str:
    """A value as the page's JavaScript wrote it into a template: 7.0 as "7",
    1e-07 as "1e-7", True as "true"."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _js_number(value)
    return str(value)


def _js_number(x: float) -> str:
    """Number::toString, from Python's shortest round-trip digits."""
    from decimal import Decimal
    if x != x:
        return "NaN"
    if x in (float("inf"), float("-inf")):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    digits_t, exponent = Decimal(repr(abs(x))).normalize().as_tuple()[1:]
    digits = "".join(str(d) for d in digits_t)
    k = len(digits)
    n = exponent + k
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        text = (digits if k == 1 else digits[0] + "." + digits[1:]) + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + text


def _bare(text: Any) -> str:
    """A name as names are compared (#309): lower case, without spaces or
    `_ - + .` - `4xUltrasharp` is `4x-UltraSharp`, `SGMUniform` SGM Uniform.
    No two of Neo's samplers, schedule types or upscalers become one so."""
    return re.sub(r"[\s_\-+.]", "", str(text).lower()) if _truthy(text) else ""


def _label(entry: Any) -> str:
    """A sampler's or schedule type's name as Forge lists it: an entry is the
    name, or the name with its other names (forge_host.sampler_names)."""
    return entry if isinstance(entry, str) else entry[0]


def _found(key: str, entries: List[Any]) -> Optional[str]:
    """The entry one of whose names is `key`, compared bare; the first in
    Forge's order where two share one."""
    for entry in entries:
        names = [entry] if isinstance(entry, str) else [entry[0], *entry[1]]
        if key and any(_bare(n) == key for n in names):
            return _label(entry)
    return None


def _sampler_named(name: Any, samplers: List[Any]) -> Optional[str]:
    """The sampler Forge lists for a name an image gives: by its name, its
    aliases or its k-diffusion function - ComfyUI's name - compared bare, a
    ComfyUI `_gpu` the same sampler (#309). None for none."""
    if not _truthy(name) or not samplers:
        return None
    if name in [_label(s) for s in samplers]:
        return name
    key = _bare(name)
    return _found(key, samplers) or (_found(key[:-3], samplers) if key.endswith("gpu") else None)


def match_sampler(name: Any, samplers: List[Any]) -> Any:
    """The sampler Forge lists for a name an image gives (`_sampler_named`);
    the name with its underscores as spaces when none matches."""
    if not _truthy(name) or not samplers:
        return name
    return _sampler_named(name, samplers) or str(name).replace("_", " ")


def match_scheduler(name: Any, schedulers: List[Any]) -> Optional[str]:
    """The schedule type Forge lists for a name, by its label, name or
    aliases, compared bare (#308, #309). None for none."""
    return _found(_bare(name), schedulers) if _truthy(name) else None


def split_sampler(text: Any, samplers: List[Any], schedulers: List[Any]) -> Dict[str, Any]:
    """
    An image's sampler text read by Forge's samplers and schedulers: "Euler a
    Karras" is the sampler "Euler a" and the schedule type "Karras" (#88).
    `schedulers` as Forge lists them, Automatic left out, in Forge's order.
    As Forge reads one, the schedule type comes off first: any of a schedule
    type's names at its end where what is left is a sampler Forge has (#309)
    - `DPM++ 2M_sgm_uniform` is SGM Uniform, `dpm 2m sgm` being none; else,
    as before, a schedule type's label after a space, the longest first, so
    `heunpp2_sgm_uniform` is heunpp2 and SGM Uniform; else the whole is the
    sampler.
    """
    if not _truthy(text):
        return {"sampler": None, "scheduler": None}
    whole = str(text).replace("_", " ")
    key = _bare(whole)
    ends = [(_bare(n), _label(e)) for e in schedulers for n in ([e] if isinstance(e, str) else [e[0], *e[1]])]
    for end, scheduler in ends:
        if end and key.endswith(end) and len(key) > len(end):
            rest = _sampler_named(key[:-len(end)], samplers)
            if rest:
                return {"sampler": rest, "scheduler": scheduler}
    for scheduler in sorted((_label(e) for e in schedulers), key=len, reverse=True):
        if whole.endswith(" " + scheduler) or whole.lower().endswith(" " + scheduler.lower()):
            return {"sampler": match_sampler(whole[:-(len(scheduler) + 1)], samplers), "scheduler": scheduler}
    return {"sampler": match_sampler(whole, samplers), "scheduler": None}


# A1111's names for its six Real-ESRGAN models, and their files: the original
# Forge lists them by the name, Neo by the file (#309).
_REALESRGAN = {"R-ESRGAN 4x+": "RealESRGAN_x4plus", "R-ESRGAN 4x+ Anime6B": "RealESRGAN_x4plus_anime_6B",
               "R-ESRGAN 2x+": "RealESRGAN_x2plus", "R-ESRGAN General 4xV3": "realesr-general-x4v3",
               "R-ESRGAN General WDN 4xV3": "realesr-general-wdn-x4v3", "R-ESRGAN AnimeVideo": "realesr-animevideov3"}


def _without_extension(name: Any) -> str:
    return re.sub(r"\.(pth|pt|safetensors|ckpt)$", "", str(name), flags=re.IGNORECASE)


def match_upscaler(name: Any, upscalers: List[str]) -> Any:
    """
    The Hires upscaler this WebUI lists for one an image names (#309): by
    case and separators, a file extension aside - `4xUltrasharp` is
    `4x-UltraSharp` - else by A1111's Real-ESRGAN name for its file, or the
    file's for the name; else the name as it is.
    """
    if not _truthy(name) or not upscalers or name in upscalers:
        return name
    listed = {}
    for upscaler in upscalers:
        listed.setdefault(_bare(_without_extension(upscaler)), upscaler)
    key = _bare(_without_extension(name))
    if key in listed:
        return listed[key]
    for a1111, file in _REALESRGAN.items():
        if key in (_bare(a1111), _bare(file)):
            for other in (a1111, file):
                if _bare(other) in listed:
                    return listed[_bare(other)]
    return name


# The two ADetailers' names for the same MediaPipe detector (#328): the
# original Forge's names the detector, ADetailer-Neo the file it downloads.
# Eyes only has none in Neo: its Face Landmarker masks the whole face.
_DETECTORS = (("mediapipe_face_full", "mediapipe_face_full.tflite"),
              ("mediapipe_face_short", "mediapipe_face_short.tflite"),
              ("mediapipe_face_mesh", "face_landmarker.task"))

# `ADetailer model`, `ADetailer model 2nd`, ... as fields of a settings line;
# `ADetailer model classes` is not one.
_DETECTOR_FIELD = re.compile(r"(^|, )(ADetailer model(?: (\d+(?:st|nd|rd|th)))?): ([^,]*)")


def match_detectors(infotext: str, offered: Dict[str, List[str]]) -> str:
    """
    The infotext with each ADetailer tab's detector under this WebUI's name
    for it (#328): where the tab's dropdown does not offer the name given,
    but offers the other ADetailer's name for the same detector. `offered`:
    each tab's choices, by its ordinal - "" for the 1st, "2nd", ... Every
    other field, and a name with no offered pair, as it was: Forge's paste
    sets a dropdown only to a choice it offers, and left the box empty.
    """
    if not infotext or not offered:
        return infotext
    lines = infotext.split("\n")

    def respelled(found: "re.Match") -> str:
        choices = offered.get(found.group(3) or "")
        given = found.group(4).strip()
        if choices is None or given in choices:
            return found.group(0)
        for pair in _DETECTORS:
            if given in pair:
                other = pair[1 - pair.index(given)]
                if other in choices:
                    return f"{found.group(1)}{found.group(2)}: {other}"
        return found.group(0)

    lines[-1] = _DETECTOR_FIELD.sub(respelled, lines[-1])
    return "\n".join(lines)


def _unquoted(text: Any) -> Any:
    """A prompt Civitai stored in quotes, without them; any other as it is."""
    trimmed = ("" if text is None else str(text)).strip()
    inner = trimmed[1:-1]
    if len(trimmed) >= 2 and trimmed.startswith('"') and trimmed.endswith('"') and '"' not in inner:
        return inner.strip()
    return text


# Hires fix's keys, written only when the image had it: Forge's paste turns
# it on from them.
_HANDLED = ("prompt", "negativePrompt", "steps", "sampler", "Schedule type", "cfgScale", "seed",
            "Size", "Model", "Model hash", "VAE", "Denoising strength", "Clip skip", "clipSkip", "CLIP Skip", "Clip Skip",
            "Hires upscale", "Hires upscaler", "Hires steps", "Hires resize-1", "Hires resize-2",
            "resources", "civitaiResources", "Lora hashes")


# Forge's Clip Skip setting and its range (shared_options.py, both WebUIs).
CLIP_SKIP_OPTION = "CLIP_stop_at_last_layers"
CLIP_SKIP_SETTING = "model_manager_send_clip_skip"
CLIP_SKIP_MAX_SETTING = "model_manager_send_clip_skip_max"


def clip_skip_value(value: Any) -> Optional[int]:
    """A clip skip as Forge's setting takes it: a whole 1 to 12; None else."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() and 1 <= number <= 12 else None


def had_hires(meta: Dict[str, Any]) -> bool:
    """Whether an image's data says it was made with Hires fix, as Forge's paste reads it."""
    return _truthy(meta.get("Denoising strength")) and any(
        _truthy(meta.get(k)) for k in ("Hires upscale", "Hires upscaler", "Hires resize-1", "Hires resize-2"))


def sampler_and_scheduler(meta: Dict[str, Any], samplers: List[str], schedulers: List[str]) -> Dict[str, Any]:
    """
    The sampler and schedule type an image names: its `Schedule type`; else
    its `scheduler` - ComfyUI's and Civitai's generator's lowercase field
    (#308) - as Forge lists it (`match_scheduler`); else the one its
    sampler's name ends in. The sampler is split from that name either way:
    "DPM++ 2M Karras" with `scheduler` simple is DPM++ 2M and Simple.
    """
    sampler, scheduler = meta.get("sampler"), meta.get("Schedule type")
    if not _truthy(scheduler):
        scheduler = match_scheduler(meta.get("scheduler"), schedulers) or scheduler
        if _truthy(sampler):
            split = split_sampler(sampler, samplers, schedulers)
            sampler, scheduler = split["sampler"], scheduler or split["scheduler"]
    elif _truthy(sampler):
        # Given beside a Schedule type, a name Forge has is matched too
        # (#309: `Euler A`); one it does not is left as written.
        sampler = _sampler_named(sampler, samplers) or sampler
    return {"sampler": sampler, "scheduler": scheduler}


def image_scheduler(meta: Dict[str, Any], samplers: List[str], schedulers: List[str]) -> Any:
    """The schedule type an image names (`sampler_and_scheduler`)."""
    return sampler_and_scheduler(meta, samplers, schedulers)["scheduler"]


def missing_names(fields: Dict[str, Any], samplers: List[Any], schedulers: List[Any]) -> List[Dict[str, str]]:
    """
    The sampler and schedule type an infotext's fields name that this WebUI
    has none of by Send's matching (#307): `Sampler`, `Schedule type`, and
    the `scheduler` Send passes on from Civitai's data. Automatic is none
    given - the original Forge's parser writes it in where the text has no
    schedule type; `Undefined` is Euler to both. Nothing where Forge's lists
    could not be read.
    """
    if not samplers:
        return []
    given = [v if _truthy(v) and str(v) != "Automatic" else None
             for v in (fields.get("Schedule type"), fields.get("scheduler"))]
    # `Undefined`, Civitai's, both Forges paste as Euler.
    sampler = fields.get("Sampler") if fields.get("Sampler") != "Undefined" else None
    meta = {"sampler": sampler, "Schedule type": given[0], "scheduler": given[1]}
    named = sampler_and_scheduler(meta, samplers, schedulers)
    missing = []
    if _truthy(meta["sampler"]) and named["sampler"] not in [_label(s) for s in samplers]:
        missing.append({"name": str(meta["sampler"]), "kind": "sampler"})
    scheduler = given[0] or given[1]
    if scheduler and match_scheduler(scheduler, schedulers) is None \
            and named["scheduler"] not in [_label(s) for s in schedulers]:
        missing.append({"name": str(scheduler), "kind": "schedule type"})
    return missing


def _text_field(infotext: Any, key: str) -> Any:
    """A field of an infotext's settings line, as Forge's pattern reads it - a
    line of three fields or more; None for none."""
    last = str(infotext or "").strip().split("\n")[-1]
    fields = RE_PARAM.findall(last)
    if len(fields) < 3:
        return None
    return next((v.strip() for k, v in fields if k.strip() == key), None)


# A value Forge's pattern reads as one quoted value (`re_param`), and unquotes.
_QUOTED = re.compile(r'"(?:\\.|[^\\"])+"')


def _field(key: str, value: Any) -> str:
    """A field of the settings line, its value quoted as Forge quotes one
    (`quote`, infotext_utils.py) - with a comma, a colon or a line break -
    which its paste unquotes. Written as it is, a comma cut the value there
    (#316: 1,611 of 107,469 stored images; Hires prompt and ADetailer's
    prompts are pasted into their boxes), and a line break split the line,
    what came before it read as prompt text (#313). A value the data holds
    quoted already is Forge's own, and goes as it is: its paste unquotes it,
    as it would the original file's."""
    text = _js_text(value)
    if _QUOTED.fullmatch(text) or not any(c in text for c in ",:\n"):
        return f"{key}: {text}"
    return f"{key}: {json.dumps(text, ensure_ascii=False)}"


def build_infotext(meta: Any, samplers: List[str], schedulers: List[str],
                   denoising_strength: Any = None, hires_upscaler: Any = None,
                   upscalers: Optional[List[str]] = None) -> str:
    """
    A Civitai image's generation data as an infotext Forge's paste reads:
    the prompt, the negative prompt, then a settings line. What Forge's paste
    sets a control from goes in it (#138): the upscaler, ADetailer's switch,
    a video's frames. `denoising_strength`: img2img always takes one - an
    image-to-video model needs 1 - and txt2img only as part of Hires fix,
    where it would otherwise turn Hires fix on. `hires_upscaler`: an
    upscaler's gallery's own, over the image's (#134). `upscalers`: Hires
    fix's, as this WebUI lists them, the image's matched to one (#309).
    """
    if not _truthy(meta):
        return ""
    meta = meta if isinstance(meta, dict) else {}
    infotext = ""
    prompt = _unquoted(meta.get("prompt"))
    if _truthy(prompt):
        infotext += _js_text(prompt)
    negative = _unquoted(meta.get("negativePrompt"))
    if _truthy(negative):
        infotext += "\nNegative prompt: " + _js_text(negative)

    named = sampler_and_scheduler(meta, samplers, schedulers)
    sampler, scheduler = named["sampler"], named["scheduler"]
    hires = had_hires(meta)

    params = []
    if _truthy(meta.get("steps")):
        params.append(_field("Steps", meta['steps']))
    if _truthy(sampler):
        params.append(_field("Sampler", sampler))
    if _truthy(scheduler):
        params.append(_field("Schedule type", scheduler))
    if _truthy(meta.get("cfgScale")):
        params.append(_field("CFG scale", meta['cfgScale']))
    # Seed 0 is a seed (#310).
    if meta.get("seed") is not None and meta.get("seed") != "":
        params.append(_field("Seed", meta['seed']))
    for key in ("Size", "Model", "Model hash", "VAE"):
        if _truthy(meta.get(key)):
            params.append(_field(key, meta[key]))
    if image_clip_skip(meta) is not None:
        params.append(_field("Clip skip", image_clip_skip(meta)))
    denoise = denoising_strength if denoising_strength is not None else (meta.get("Denoising strength") if hires else None)
    if denoise is not None:
        params.append(_field("Denoising strength", denoise))
    if hires:
        if _truthy(meta.get("Hires upscale")):
            params.append(_field("Hires upscale", meta['Hires upscale']))
        if _truthy(meta.get("Hires upscaler")) and not _truthy(hires_upscaler):
            params.append(_field("Hires upscaler", match_upscaler(meta['Hires upscaler'], upscalers or [])))
        if _truthy(meta.get("Hires steps")):
            params.append(_field("Hires steps", meta['Hires steps']))
    if _truthy(hires_upscaler):
        params.append(_field("Hires upscaler", hires_upscaler))
    # ADetailer's paste turns its tab on or off by this switch, and each of
    # its own tabs by theirs (#311).
    if any(k.startswith("ADetailer ") for k in meta):
        from .forge_host import adetailer_tabs
        params.append("ADetailer enable: True")
        params.extend(adetailer_switches(meta, adetailer_tabs()))
    else:
        params.append("ADetailer enable: False")
    # Every other field as it is (but `_field`), in the page's order: JavaScript's object
    # order puts a key that reads as an array index first, by number.
    keys = sorted((k for k in meta if re.fullmatch(r"0|[1-9]\d*", k) and int(k) < 2 ** 32 - 1), key=int) \
        + [k for k in meta if not (re.fullmatch(r"0|[1-9]\d*", k) and int(k) < 2 ** 32 - 1)]
    for key in keys:
        value = meta[key]
        if key not in _HANDLED and value is not None and value != "" and not isinstance(value, (dict, list)):
            params.append(_field(key, value))
    # Forge's paste reads the last line as settings only with three fields
    # or more (`re_param`, both WebUIs), else as prompt text (#313): a size
    # written as its two halves, which Forge reads as it reads `Size`, makes
    # three of Size and ADetailer's switch.
    if len(params) < 3:
        params = [re.sub(r"^Size: (\d+)x(\d+)$", r"Size-1: \1, Size-2: \2", p) for p in params]
    if params:
        infotext += "\n" + ", ".join(params)
    return infotext


# `ADetailer model`, `ADetailer model 2nd`, ...: the detector of each of
# ADetailer's tabs, an ordinal after the 1st.
_ADETAILER_MODEL = re.compile(r"ADetailer model(?: (\d+)(?:st|nd|rd|th))?")


def _tab_suffix(n: int) -> str:
    """ADetailer's name for its nth tab's fields: nothing for the 1st, else
    its ordinal (`suffix` in both ADetailers' ui.py)."""
    if n == 1:
        return ""
    return f" {n}" + ("th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def adetailer_switches(fields: Dict[str, Any], tabs: int) -> List[str]:
    """
    ADetailer's tab switches for a settings line (#311): `ADetailer tab
    enable`, `ADetailer tab enable 2nd`, ... - True for each tab the fields
    name a detector for, False for every other, from the 1st up to `tabs`
    (how many ADetailer draws) or the highest tab named, whichever is more.

    ADetailer leaves the switch out of what it writes, and Forge's paste
    leaves a field the text lacks as it is on screen: Neo's tabs past the
    1st stayed off, and a tab an earlier Send turned on kept its detector
    for an image that never had it.
    """
    named = set()
    for key, value in fields.items():
        found = _ADETAILER_MODEL.fullmatch(str(key).strip())
        if found and _truthy(value) and str(value).strip() not in ("", "None"):
            named.add(int(found.group(1) or 1))
    last = max([tabs, *named])
    return [f"ADetailer tab enable{_tab_suffix(n)}: {n in named}" for n in range(1, last + 1)]


def with_adetailer_switches(infotext: str) -> str:
    """
    A generation's own infotext with ADetailer's switches on its settings
    line (#311): `ADetailer enable` and each tab's, as a Civitai image's
    text has them. Forge writes neither - 0 of one library's 11,109
    generations that used ADetailer - so a generation sent back left
    ADetailer, and each of its tabs, as the page had them. A text with no
    settings line, or one that already says, is left as it is.
    """
    from .forge_host import adetailer_tabs
    from .image_text import line_params
    params = line_params(infotext)
    if not params or "ADetailer enable" in params:
        return infotext
    if any(key.startswith("ADetailer ") for key in params):
        added = ["ADetailer enable: True", *adetailer_switches(params, adetailer_tabs())]
    else:
        added = ["ADetailer enable: False"]
    return infotext.rstrip() + ", " + ", ".join(added)


def without_lora_hashes(infotext: str) -> str:
    """
    The infotext with no `Lora hashes` field: Forge's LoRA paste renames each
    <lora:> tag by it - to the name its file had on the uploader's disk, or
    an alias - over the file names Send has given them, which the chips name.
    Forge quotes the value, which holds colons; it is a field of the last line.
    """
    lines = str(infotext or "").split("\n")
    lines[-1] = re.sub(r'(^|,\s*)Lora hashes: "(?:[^"\\]|\\.)*"(\s*,\s*)?',
                       lambda m: ", " if m.group(1) and m.group(2) else "", lines[-1], count=1)
    return "\n".join(lines)


# The fields of an infotext's last line that name the image's second models:
# Hires fix's checkpoint and modules, the refiner and where it switches.
_SECOND_MODELS = re.compile(r'(^|,\s*)(?:Hires checkpoint|Hires Module \d+|Refiner|Refiner switch at): '
                            r'(?:"(?:[^"\\]|\\.)*"|[^,\n]*)(\s*,\s*)?')


def without_second_models(infotext: str) -> str:
    """
    The infotext with none of the image's second models (#377): sent with a
    checkpoint of another model, the image's hires checkpoint, Hires Module
    and refiner are of its own family. Left out, Forge's paste sets Hires
    fix's checkpoint to "Use same" and the refiner off; the loader sets Hires
    fix's modules (scheduler/load.corrections).
    """
    lines = str(infotext or "").split("\n")
    previous = None
    while previous != lines[-1]:
        previous = lines[-1]
        lines[-1] = _SECOND_MODELS.sub(lambda m: ", " if m.group(1) and m.group(2) else "", lines[-1], count=1)
    return "\n".join(lines)


def video_size(width: Any, height: Any) -> Dict[str, int]:
    """A video's size as Wan can make it: its 2x2 patches of 8x latents, 16 px."""
    snap = lambda v: max(16, int(_js_round(float(v) / 16)) * 16)  # noqa: E731
    return {"width": snap(width), "height": snap(height)}


def _js_round(x: float) -> float:
    """Math.round: halves up, never to even."""
    import math
    return math.floor(x + 0.5)


# A Civitai image's size is its data's, unless the picture's shape differs
# from it by more than this: then the picture's (#299). One library's 472 of
# 120,104 stored images were sent squashed or stretched at their data's size.
SHAPE_TOLERANCE = 0.03


def civitai_meta(record: Dict[str, Any], frames: Any = None, video: bool = False) -> Dict[str, Any]:
    """
    A Civitai image's data as Send reads it: its own (`record_meta`), with a
    `Size` when it gives none - the picture's, else its width and height - and
    the picture's size where the data's shape differs from it by more than 3%
    (#299). For an image-to-video model, its size as Wan makes it and its
    frames.
    """
    meta = record_meta(record)
    width, height = record.get("width"), record.get("height")
    if not _truthy(meta.get("Size")):
        if _truthy(width) and _truthy(height):
            meta["Size"] = f"{_js_text(width)}x{_js_text(height)}"
        elif _truthy(meta.get("width")) and _truthy(meta.get("height")):
            meta["Size"] = f"{_js_text(meta['width'])}x{_js_text(meta['height'])}"
    # The size Forge's paste ends with: `width` and `height`, which it reads
    # after `Size`, else `Size`.
    passed = lambda v: v is not None and v != "" and not isinstance(v, (dict, list))  # noqa: E731
    if passed(meta.get("width")) and passed(meta.get("height")):
        given = _size_of(f"{_js_text(meta['width'])}x{_js_text(meta['height'])}")
    else:
        given = _size_of(meta.get("Size"))
    try:
        picture = (int(width), int(height)) if _truthy(width) and _truthy(height) else None
    except (TypeError, ValueError):
        picture = None
    if given and picture and all(given) and all(picture) \
            and abs((given[0] / given[1]) / (picture[0] / picture[1]) - 1) > SHAPE_TOLERANCE:
        # Without `width` and `height`, which Forge's paste would read over `Size`.
        meta["Size"] = f"{picture[0]}x{picture[1]}"
        meta.pop("width", None)
        meta.pop("height", None)
    if video:
        size = _size_of(meta.get("Size"))
        w = (size[0] if size and size[0] else None) or width
        h = (size[1] if size and size[1] else None) or height
        if _truthy(w) and _truthy(h):
            snapped = video_size(w, h)
            meta["Size"] = f"{snapped['width']}x{snapped['height']}"
        if _truthy(frames):
            meta["Batch size"] = int(frames)
    return meta


def civitai_infotext(record: Dict[str, Any], samplers: List[str], schedulers: List[str], *,
                     denoising_strength: Any = None, hires_upscaler: Any = None, frames: Any = None,
                     video: bool = False, prompt: Any = None, negative_prompt: Any = None,
                     upscalers: Optional[List[str]] = None, usual: Optional[Dict[str, Any]] = None) -> str:
    """
    The infotext a Send of a Civitai image pastes: civitai_meta(), with the
    page's prompts where it renamed a LoRA tag to the library's file (the
    chips' rule), and the pick's usual settings where the person ticked them
    (`usual`, with_usual_meta), built (build_infotext), its Lora hashes left
    out.
    """
    meta = civitai_meta(record, frames, video)
    if prompt is not None:
        meta["prompt"] = prompt
    if negative_prompt is not None:
        meta["negativePrompt"] = negative_prompt
        # The page's copy, renamed, still holds the line civitai_meta read.
        read_settings_line(meta)
    meta = with_usual_meta(meta, usual, samplers, schedulers)
    return without_lora_hashes(build_infotext(meta, samplers, schedulers, denoising_strength, hires_upscaler, upscalers))


# ------------------------------------------- the pick's usual settings (#378)
# Each setting as the usual settings name it, and as a settings line does.
_USUAL_LINE = {"sampler": "Sampler", "schedule_type": "Schedule type", "steps": "Steps", "cfg": "CFG scale",
               "distilled_cfg": "Distilled CFG Scale", "shift": "Shift"}
# The fields that hold the fifth setting, in a Civitai record and in a line:
# written once, the pick's, never beside the image's - Neo's parser keeps the
# last one written.
_FIFTH_FIELDS = ("Distilled CFG Scale", "Shift", "shift")


def with_usual_meta(meta: Dict[str, Any], usual: Optional[Dict[str, Any]], samplers: List[Any],
                    schedulers: List[Any]) -> Dict[str, Any]:
    """
    A Civitai image's data with the pick's usual settings in place of its
    own (#378). The sampler and schedule type are split first, as the paste
    would read them, and written as two plain fields: a schedule type folded
    into the image's sampler (`DPM++ 2M Karras`) stays when only the sampler
    changes. A fifth setting goes under its own name, every field of either
    fifth the image gives left out. Without `usual`, the data as it is.
    """
    if not usual:
        return meta
    meta = dict(meta)
    if "sampler" in usual or "schedule_type" in usual:
        named = sampler_and_scheduler(meta, samplers, schedulers)
        meta["sampler"] = usual.get("sampler", named["sampler"])
        meta["Schedule type"] = usual.get("schedule_type", named["scheduler"])
        # ComfyUI's own field goes once it is read into the schedule type; one
        # this WebUI lists none of stays, for Send's notice to name (#307).
        if "schedule_type" in usual or match_scheduler(meta.get("scheduler"), schedulers):
            meta.pop("scheduler", None)
    if "steps" in usual:
        meta["steps"] = usual["steps"]
    if "cfg" in usual:
        meta["cfgScale"] = usual["cfg"]
    for key in ("distilled_cfg", "shift"):
        if key in usual:
            for field in _FIFTH_FIELDS:
                meta.pop(field, None)
            meta[_USUAL_LINE[key]] = usual[key]
    return meta


def with_usual_line(infotext: Any, usual: Optional[Dict[str, Any]]) -> Any:
    """
    A generation's infotext with the pick's usual settings (#378): each in
    its settings line replaced where the line has the field, added at its
    end where it has none, quoted as Forge quotes (`_field`); a fifth
    setting in place of the line's own of either kind. Every other byte as
    it was. A text with no settings line - three fields or more, as Forge's
    paste reads one - is left as it is.
    """
    if not usual or not settings_line(infotext):
        return infotext
    # Forge reads the last line of the text stripped; what follows it is kept.
    whole = str(infotext)
    text = whole.rstrip()
    tail = whole[len(text):]
    start = text.rfind("\n") + 1
    last = text[start:]
    found = list(RE_PARAM.finditer(last))
    wanted = {_USUAL_LINE[k]: v for k, v in usual.items() if k in _USUAL_LINE}
    dropped = set(_FIFTH_FIELDS) - set(wanted) if any(k in usual for k in ("distilled_cfg", "shift")) else set()
    out, at, written = [], 0, set()
    for match in found:
        out.append(last[at:match.start()])
        at = match.end()
        key = match.group(1).strip()
        piece = match.group(0)
        if key in dropped:
            continue
        if key in wanted:
            lead = piece[:len(piece) - len(piece.lstrip())]
            piece = lead + _field(key, wanted[key]) + ("," if piece.rstrip().endswith(",") else "")
            written.add(key)
        out.append(piece)
    out.append(last[at:])
    line = "".join(out)
    # A fifth left out goes with another written, so the line always gains
    # a field: after the comma a field left out at its end leaves, or a new one.
    added = [_field(k, v) for k, v in wanted.items() if k not in written]
    if added:
        line = line.rstrip() + (" " if line.rstrip().endswith(",") else ", ") + ", ".join(added)
    return text[:start] + line + tail


def settings_line(infotext: Any) -> bool:
    """Whether a text ends in a settings line, as Forge's paste reads one: the
    last line of the text stripped, three fields or more."""
    last = str(infotext or "").strip().split("\n")[-1]
    return len(RE_PARAM.findall(last)) >= 3


def forge_lists() -> tuple:
    """Forge's samplers, and its schedulers but Automatic, each with the
    other names Forge knows it by (#309)."""
    from .forge_host import sampler_names, scheduler_names
    try:
        return sampler_names(), [s for s in scheduler_names() if s[0] and s[0] != "Automatic"]
    except Exception as e:
        say(f"Send: Forge's samplers could not be read: {e}")
        return [], []


def forge_upscalers() -> List[str]:
    """Hires fix's upscalers as this WebUI lists them; none where they cannot be read."""
    from .forge_host import hires_upscalers
    try:
        return hires_upscalers()
    except Exception:
        return []


def civitai_settings(db, source: Dict[str, Any], usual: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    What the loader sets a tab with for a Civitai image's source (#302): the
    infotext Forge's paste reads, and what the page set after the paste and
    now goes in the same event - the schedule type (the image's, else
    Automatic) and whether Hires fix stays off.

    `source`, as the page sends it: `image` (its id), `upscaler` (an
    upscaler's gallery's own, for Hires fix), `denoise` (img2img's for an
    image-to-video model), `video` and `frames`, and `prompt` /
    `negative_prompt` where the chips renamed a LoRA tag. `usual`: the pick's
    usual settings, ticked (usual_settings.chosen). None for no such image.
    """
    record = next(iter(db.stored_records([int(source.get("image") or 0)])), None)
    if record is None:
        return None
    samplers, schedulers = forge_lists()
    meta = with_usual_meta(civitai_meta(record, source.get("frames"), bool(source.get("video"))), usual,
                           samplers, schedulers)
    return {
        "text": civitai_infotext(record, samplers, schedulers, denoising_strength=source.get("denoise"),
                                 hires_upscaler=source.get("upscaler"), frames=source.get("frames"),
                                 video=bool(source.get("video")), prompt=source.get("prompt"),
                                 negative_prompt=source.get("negative_prompt"), upscalers=forge_upscalers(),
                                 usual=usual),
        "scheduler": image_scheduler(meta, samplers, schedulers) or "Automatic",
        "hires": had_hires(meta),
        # For Forge's Clip Skip setting (#318): none for Flux, which takes
        # only CLIP's final summary and so changes nothing by it.
        "clip_skip": None if "flux" in str(record.get("baseModel") or "").lower()
                     else clip_skip_value(image_clip_skip(meta)),
        # A Civitai image's text always ends in a settings line that took them.
        **({"usual": usual, "usual_text": usual} if usual else {}),
    }


# ------------------------------------------------- the card's reading

def card_reading(meta: Any, samplers: List[str], schedulers: List[str]) -> Dict[str, Any]:
    """
    The sampler and schedule type an image's card shows (#302): its
    `Schedule type`; else its `scheduler` (#308); else its sampler's name
    read for one, as Forge names both ("Euler a Karras" is Euler a and
    Karras), the sampler then the one Forge lists - else the sampler as
    given (`sampler_and_scheduler`). Ported from the card's own
    reading (imageTextHtml in image_card.mjs), and written on each image
    beside its level (`stamp_readings`), as the page reads the level.
    """
    named = sampler_and_scheduler(meta if isinstance(meta, dict) else {}, samplers, schedulers)
    return {"mm_sampler": named["sampler"], "mm_scheduler": named["scheduler"]}


def stamp_readings(images: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """Write each image's card reading on it, in place - where every image
    the page draws a card of is stamped with its level (nsfw.stamp_levels)."""
    if images:
        samplers, schedulers = forge_lists()
        for image in images:
            if isinstance(image, dict):
                image.update(card_reading(image.get("meta"), samplers, schedulers))
    return images


# ------------------------------------------- a generation's settings

def _js_canon(ch: str) -> str:
    """A character as JavaScript's case-blind match without the u flag reads it
    (Canonicalize): its upper case, unless that is not one character, or would
    take a character past ASCII into it - `ſ` does not match `s` there, as it
    does in Python's re."""
    upper = ch.upper()
    if len(upper) != 1 or (ord(ch) >= 128 and ord(upper) < 128):
        return ch
    return upper


def _js_same(text: str, at: int, wanted: str) -> bool:
    if at + len(wanted) > len(text):
        return False
    return all(_js_canon(text[at + n]) == _js_canon(c) for n, c in enumerate(wanted))


def _js_replacement(template: str, text: str, start: int, end: int) -> str:
    """A JavaScript replacement string, its `$` patterns read as String.replace
    reads them for a pattern with no groups: `$$`, `$&`, `` $` ``, `$'`."""
    out, n = [], 0
    while n < len(template):
        pair = template[n:n + 2]
        if pair == "$$":
            out.append("$")
        elif pair == "$&":
            out.append(text[start:end])
        elif pair == "$`":
            out.append(text[:start])
        elif pair == "$'":
            out.append(text[end:])
        else:
            out.append(template[n])
            n += 1
            continue
        n += 2
    return "".join(out)


def rename_lora_tags(prompt: Any, old: Any, new: Any) -> Any:
    """
    The chips' rename (`renameLoraTags`, chips.mjs): every `<lora:old` tag
    followed by `:` or `>`, its name in any case, becomes `<lora:new`. Ported
    for a generation's Send (#302), whose renames the page sends with the
    source; JavaScript's case rule and replacement string kept.
    """
    if not _truthy(prompt) or not _truthy(old) or not _truthy(new) or old == new:
        return prompt
    text, head = str(prompt), "<lora:" + str(old)
    template = "<lora:" + str(new)
    out, n = [], 0
    while n < len(text):
        if _js_same(text, n, head) and n + len(head) < len(text) and text[n + len(head)] in ":>":
            out.append(_js_replacement(template, text, n, n + len(head)))
            n += len(head)
        else:
            out.append(text[n])
            n += 1
    return "".join(out)


def renamed(text: Any, renames: Any) -> Any:
    """Each rename the page sends, `{from, to}`, in its order, as the page applied them."""
    for pair in renames or []:
        if isinstance(pair, dict):
            text = rename_lora_tags(text, pair.get("from"), pair.get("to"))
    return text


RENAME_LORAS_SETTING = "model_manager_send_rename_loras"
# Where the Civitai Images and Generations tabs' "Choose the checkpoint at
# every Send" boxes start, and whether a Resources button's dialog starts its
# box ticked (#377). The boxes are the page's.
CHOOSE_CHECKPOINT_SETTING = "model_manager_send_choose_checkpoint"


def without_renames(source: Dict[str, Any]) -> Dict[str, Any]:
    """
    A source as Send applies it (#205): with the switch off, its LoRA tag
    renames left out - a Civitai image's renamed `prompt` and
    `negative_prompt`, a generation's `renames` - and the image's own text
    pasted. Read at each Send, so a change on either settings page counts at
    the next one.
    """
    from .forge_host import setting
    if setting(RENAME_LORAS_SETTING):
        return source
    return {k: v for k, v in source.items() if k not in ("prompt", "negative_prompt", "renames")}


def replays(generation: Dict[str, Any], into: bool) -> bool:
    """Whether a generation's Send sets its kept press back (#7) rather than
    pasting its infotext: it kept one, and goes back to its own tab - into
    img2img (#299) only an img2img generation's press."""
    return bool(generation.get("inputs")) and (not into or generation.get("mode") == "img2img")


def generation_settings(db, source: Dict[str, Any], into: bool = False,
                        usual: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    What the loader sets a tab with for a generation of your own (#302): the
    image's own infotext, the chips' renames applied and its Lora hashes left
    out, as the page pasted it, with ADetailer's switches (#311); the schedule type and Hires fix the page set
    after the paste, read from the image's data as it read them; and whether
    its kept press is replayed instead (`replays`).

    `source`: `generation`, `image` (its id; else the first image),
    `renames`, the page's `{from, to}`, and `whole` for the Model Manager's
    card, which sends the generation's own infotext - its first image's
    where it has none - as the page did (`card.infotext || first.infotext`:
    2 of one library's 7,174 differ). `usual`: the pick's usual settings,
    ticked (usual_settings.chosen), in its settings line and handed on for the
    replay. None for no such generation.
    """
    generation = db.get_generation(int(source.get("generation") or 0))
    if not generation:
        return None
    images = generation.get("images") or []
    image = next((i for i in images if i.get("id") == source.get("image")), images[0] if images else {})
    meta = image.get("meta") or {}
    infotext = (generation.get("infotext") if source.get("whole") else None) or image.get("infotext") or ""
    samplers, schedulers = forge_lists()
    text = with_usual_line(renamed(infotext, source.get("renames")), usual) if infotext else ""
    # The paste's event sets the schedule type the line was given: none where
    # the text has no settings line to give the usual ones to.
    pasted = (usual or {}).get("schedule_type") if settings_line(text) else None
    return {
        "text": with_adetailer_switches(without_lora_hashes(text)) if infotext else "",
        "scheduler": pasted or image_scheduler(meta, samplers, schedulers) or "Automatic",
        "hires": had_hires(meta),
        # Neo writes `Clip skip` into its own text for SD 1.x alone.
        "clip_skip": clip_skip_value(_text_field(infotext, "Clip skip")),
        "replay": replays(generation, into),
        "mode": generation.get("mode"),
        # For the replay; and what the text took, for the notice of what went
        # - none where it has no settings line to take them.
        **({"usual": usual} if usual else {}),
        **({"usual_text": usual} if usual and settings_line(text) else {}),
    }


def settings(db, source: Dict[str, Any], into: bool = False,
             usual: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    The loader's settings for a source: a Civitai image's or a generation's.
    `usual`: the pick's usual settings, where the person ticked them - its
    callers ask usual_settings.chosen(), which reads Send's own rules.
    """
    source = without_renames(source)
    found = generation_settings(db, source, into, usual) if source.get("kind") == "generation" \
        else civitai_settings(db, source, usual)
    if found is not None:
        found["other_model"] = _other_model(db, source)
    return found


def _source_pick_kind(db, source: Dict[str, Any]) -> Optional[str]:
    """
    What the checkpoint a source is sent with is to its image (pick_kind's
    `own`, `same`, `file`, `version` or `model`), told by the pick as the plan
    told it, from what the page sends with the source: `use_checkpoint`,
    `image_model`, and a Civitai image's `version_ids` and `hashes`. None for
    no pick, a pick Forge no longer lists, or no such generation.
    """
    picked = _picked(db, source.get("use_checkpoint") or "") if source.get("use_checkpoint") else None
    if not picked:
        return None
    image_model = int(source.get("image_model") or 0) or None
    if source.get("kind") == "generation":
        generation = db.get_generation(int(source.get("generation") or 0))
        return generation_pick_kind(db, generation, picked, image_model) if generation else None
    from .send_plan import local_checkpoint, named_ids
    version_ids = str(source.get("version_ids") or "").split(",")
    hashes = str(source.get("hashes") or "").split(",")
    own = local_checkpoint(db, "", *named_ids(version_ids, hashes))
    return pick_kind(db, picked, version_ids, hashes, image_model, (own or {}).get("file_path") or "")


def _other_model(db, source: Dict[str, Any]) -> bool:
    """
    Whether a source is sent with a checkpoint of another model than its
    image's (#377): the loader then sets Hires fix's checkpoint and module to
    "Use same" and leaves the refiner off - the image's own are of its
    family.
    """
    return _source_pick_kind(db, source) == "model"


# --------------------------------------- a generation's, and a task's, plan

def _checkpoints_by_hash(db, generation: Dict[str, Any]) -> List[str]:
    """The library's checkpoint files whose hash is the one the generation
    names - recorded, or its infotext's `Model hash` - in the library's order."""
    from .image_text import line_params
    hashes = [h for h in (generation.get("checkpoint_hash"),
                          line_params(generation.get("infotext")).get("Model hash")) if h]
    if not hashes:
        return []
    return [row["file_path"] for row in db.versions_named_by([], hashes)
            if row.get("file_path") and row.get("file_type") in (None, "Checkpoint")]


def generation_plan(db, generation_id: int, use_checkpoint: Optional[str] = None,
                    image_model: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    What Forge is set up with before a generation of your own is sent back to
    it: the same as it was made with, from what was recorded - its checkpoint's
    UI preset, the checkpoint, and exactly the VAE / text encoder files that
    were loaded, none for a model that loaded none. The same for every kind of
    model.

    Pasting the infotext does not do it: Forge Neo ignores the checkpoint and
    the modules an infotext names unless told otherwise ("Ignore the
    Checkpoint / VAE / Text Encoder when reading infotext", both on by
    default), and a model that loaded no modules names none to clear.

    `use_checkpoint`: a checkpoint picked in the Resources dialog Send opened
    (#377), by the name Forge lists it under, in place of the one the
    generation was made with; `image_model` and the answer's `pick`,
    `instead` and `other_model` as civitai_plan()'s. A pick of another model
    loads its family's modules, not the recorded ones (family_modules).

    Returns:
        plan_for()'s answer, or None for no such generation.
    """
    generation = db.get_generation(generation_id)
    if not generation:
        return None
    path = generation.get("checkpoint_path") or ""
    modules = generation.get("modules") or []
    if use_checkpoint:
        picked = _picked(db, use_checkpoint)
        if not picked:
            # Gone from Forge's list since the dialog drew it: the stop.
            plan = plan_for(db, "", [])
            plan.update({"checkpoint_missing": use_checkpoint,
                         "checkpoint_problem": {"reason": "missing", "name": use_checkpoint},
                         "inputs": bool(generation.get("inputs")), "other_model": False})
            return plan
        kind = generation_pick_kind(db, generation, picked, image_model)
        plan = plan_for(db, picked, modules if kind != "model" else [])
        if kind == "model":
            plan["target"], plan["modules_missing"] = family_modules(db, picked), []
        if kind != "own":
            plan.update({"instead": os.path.basename(picked), "pick": kind})
        plan["other_model"] = kind == "model"
        plan["inputs"] = bool(generation.get("inputs"))
        return plan
    plan = plan_for(db, path, modules)
    if not plan["checkpoint"]:
        # Forge does not list the file it was made with (#233). The library's
        # file with the hash the image names - a download from the Resources
        # dialog Send opened, say - is the one, if Forge lists it. Else Send
        # stops and says why, as a Civitai image's does (civitai_plan): the
        # file is in a folder this WebUI does not load - the other WebUI's -
        # or Forge has not listed it yet, or the library lacks it.
        from .forge_host import checkpoint_name
        from .model_dirs import loads_here
        candidates = [p for p in dict.fromkeys(([path] if path else []) + _checkpoints_by_hash(db, generation))
                      if os.path.isfile(p)]
        listed = next((p for p in candidates if checkpoint_name(p)), None)
        if listed:
            plan = plan_for(db, listed, modules)
        elif candidates:
            found = candidates[0]
            plan["checkpoint_missing"] = os.path.basename(found)
            plan["checkpoint_problem"] = {"reason": "not_listed" if loads_here(found) else "elsewhere",
                                          "name": os.path.basename(found), "path": found}
        else:
            # Synced from a folder, its text may name a checkpoint by name alone.
            name = (None if path else db.unheld_checkpoint(generation_id)) or plan["checkpoint_missing"]
            plan["checkpoint_missing"] = name
            plan["checkpoint_problem"] = {"reason": "missing", "name": name} if name else None
    # Whether its Send sets back what the press was sent (#7); a generation
    # recorded without them has Forge's paste, corrected.
    plan["inputs"] = bool(generation.get("inputs"))
    return plan


def generation_pick_kind(db, generation: Dict[str, Any], picked: str, image_model: Optional[int] = None) -> str:
    """pick_kind() for a generation: its checkpoint's file, version and hash, as recorded."""
    from .image_text import line_params
    path = generation.get("checkpoint_path") or ""
    row = (db.get_version(path) or {}) if path else {}
    hashes = [h for h in (generation.get("checkpoint_hash"),
                          line_params(generation.get("infotext")).get("Model hash")) if h]
    return pick_kind(db, picked, [row["id"]] if row.get("id") else [], hashes,
                     image_model or row.get("model_id"), path)


def plan_for(db, path: str, modules: List[str]) -> Dict[str, Any]:
    """
    How to set Forge up for a checkpoint file and these VAE / text encoder
    files: a generation of your own sent back (generation_plan), or a queued
    task loaded into its tab (task_plan).

    Returns:
        preset (None if unknown), checkpoint (the name Forge lists it under,
        None if it does not), checkpoint_missing (its file name, then),
        target (the module labels to hold), modules_missing (the recorded
        modules Forge does not offer), embeddings (the kind of embedding the
        checkpoint loads: forge_host.embedding_kind).
    """
    from .file_identity import identify
    from .forge_host import checkpoint_name, embedding_kind, installed_modules
    from .identity_store import record_architecture

    preset = None
    model_class = None
    if path:
        # Read as any checkpoint is, once, and stored; a file the library
        # does not hold is read without storing.
        spelled = db.library_spelling([path]).get(path, path)
        try:
            record_architecture(db, spelled)
        except Exception as e:
            say(f"Could not read {os.path.basename(path)}: {e}")
        row = db.get_version(spelled) or {}
        preset, model_class = row.get("architecture"), row.get("architecture_class")
        if not preset and os.path.isfile(path):
            found = identify(path)
            preset, model_class = found.preset, found.model_class

    checkpoint = checkpoint_name(path)
    installed = installed_modules()
    recorded = [os.path.basename(p) for p in modules if p]
    return {
        "preset": preset,
        "checkpoint": checkpoint,
        "checkpoint_missing": os.path.basename(path) if path and not checkpoint else None,
        "target": [m for m in recorded if m in installed],
        "modules_missing": [m for m in recorded if m not in installed],
        "embeddings": embedding_kind(model_class, preset),
    }


def task_plan(db, task_id: int) -> Optional[Dict[str, Any]]:
    """
    How to set Forge up before a task is loaded into its tab (#160): its
    checkpoint's UI preset, the checkpoint, and its VAE / text encoders, as a
    generation's Send does - plan_for(). A checkpoint this WebUI does not
    list is named in checkpoint_missing. It may read the checkpoint's header.

    Returns:
        The plan with the task's `mode`, or None for no task this install
        queued.
    """
    from .forge_host import checkpoint_file
    from .install import INSTALL_KEY
    task = db.get_task(task_id)
    if not task or task.get("install") != INSTALL_KEY:
        return None
    path = checkpoint_file(task.get("checkpoint") or "")
    plan = plan_for(db, path or "", task.get("modules") or [])
    if task.get("checkpoint") and not path:
        plan["checkpoint_missing"] = task["checkpoint"]
    return {"mode": task["mode"], **plan}


# ---------------------------------------- the Resources dialog's checkpoints

# Why a checkpoint is suggested for an image, closest first (#377): the order
# the suggestions come in. Within one, by Forge's name.
SUGGESTED_ORDER = ("this gallery's", "the image's own", "same file", "same version, other file",
                   "same model", "loaded now")
# Suggested and picked before anything is touched: the image comes out as made.
PICKED_FIRST = ("this gallery's", "the image's own", "same file")


def your_checkpoints(db, version_ids: str = "", hashes: str = "", model_id: int = 0, base_model: str = "",
                     same_file: int = 0, gallery_file: str = "", gallery_base_model: str = "",
                     generation: int = 0) -> Dict[str, Any]:
    """
    Every checkpoint Forge lists, for the Resources dialog's list (#377), and
    which of them suit the image - from the library's rows and what the page
    hands, reading no file and asking Civitai nothing.

    Args:
        version_ids, hashes: the image's checkpoint as the page reads it
            (imageCheckpoint in send.mjs); for a generation, its own
            (`generation`) are taken.
        model_id, base_model: what the dialog's missing-resources lookup
            answered for the image's checkpoint version; the library's row
            is taken where it holds the version.
        same_file: the version the library holds the image's very file
            under, as that lookup answered (#304).
        gallery_file, gallery_base_model: the gallery's file and its model's
            base model, in a model's gallery.

    Returns:
        checkpoints: [{name: Forge's, file, family, read, supported, model,
            version, base_model}] in Forge's order; `family` the UI preset a
            sync read, null for none or not read yet (`read` false);
            `supported`, whether this WebUI has that preset.
        suggested: [{name, why}], closest first; picked: the name picked to
            begin with, or null; same_base: {base_model, names} - the
            checkpoints of the image's base model, in Forge's order, shown
            first in their family's tab, not suggested; loaded: Forge's
            checkpoint now; family: the image's, which the list opens on.
    """
    from .architecture import preset_for_base_model
    from .forge_host import available_presets, checkpoint_file, listed_checkpoints, selected_models
    from .image_text import line_params
    from .send_plan import named_ids

    versions, hash_list = named_ids(str(version_ids or "").split(","), str(hashes or "").split(","))
    own_path = ""
    if generation:
        record = db.get_generation(int(generation)) or {}
        own_path = record.get("checkpoint_path") or ""
        hash_list = [h for h in (record.get("checkpoint_hash"),
                                 line_params(record.get("infotext")).get("Model hash")) if h]
        row = (db.get_version(own_path) or {}) if own_path else {}
        versions = [row["id"]] if row.get("id") else []
    if not versions and hash_list:
        # Named by a hash alone - A1111's Model hash, a generation kept by
        # name: its version and model as Civitai answered for the hash.
        known = db.resolved_hashes(hash_list)
        versions = [int(v["version_id"]) for v in known.values() if v and v.get("version_id")]
        model_id = model_id or next((v.get("model_id") for v in known.values() if v and v.get("model_id")), 0)
    listed = listed_checkpoints()
    key = lambda path: os.path.normcase(os.path.abspath(path or ""))
    rows = {key(r["file_path"]): r for r in db.files_described()}
    presets = available_presets()

    checkpoints = []
    by_path: Dict[str, str] = {}
    for name, path in listed:
        row = rows.get(key(path)) or {}
        family = row.get("architecture") or None
        by_path[key(path)] = name
        checkpoints.append({
            "name": name, "file": os.path.basename(path), "family": family, "read": bool(row.get("read")),
            "supported": family is not None and (presets is None or family in presets),
            "model": row.get("model_name") or None, "version": row.get("version_name") or None,
            "base_model": row.get("base_model") or None})

    reasons: Dict[str, List[str]] = {}

    def suggest(paths, why):
        for path in paths:
            name = by_path.get(key(path))
            if name and why not in reasons.setdefault(name, []):
                reasons[name].append(why)

    # The image's own: the first file it names - by a hash, else its version -
    # that Forge lists. From the rows alone: local_checkpoint() reads headers.
    named = [r for r in (db.versions_named_by(versions, hash_list) if (versions or hash_list) else [])
             if r.get("file_path") and r.get("file_type") in (None, "Checkpoint")]
    own = next((r for r in named if key(r["file_path"]) in by_path), named[0] if named else {})
    own_path = own_path or (own or {}).get("file_path") or ""
    if gallery_file and (rows.get(key(gallery_file)) or {}).get("file_type") == "Checkpoint":
        suggest([gallery_file], "this gallery's")
    suggest([own_path] if own_path else [], "the image's own")
    if same_file:
        suggest([r["file_path"] for r in db.library_files(version_ids=[int(same_file)])], "same file")
    if versions:
        suggest([r["file_path"] for r in db.library_files(version_ids=versions)
                 if not _same_path(r["file_path"], own_path)], "same version, other file")
    model = int(model_id or 0) or (own or {}).get("model_id") or next(
        (r.get("model_id") for r in (db.library_files(version_ids=versions) if versions else []) if r.get("model_id")),
        None)
    if model:
        # Its model's other versions the library holds here, as #278 offered them.
        from .resources import other_versions
        held = other_versions(db, versions[0] if versions else 0, int(model))
        suggest([r["file_path"] for v in held for r in db.library_files(version_ids=[v["version_id"]])
                 if r.get("version_id") not in versions], "same model")
    loaded = None
    try:
        loaded_path = checkpoint_file(selected_models().get("checkpoint") or "")
        loaded = by_path.get(key(loaded_path)) if loaded_path else None
    except Exception as e:
        say(f"Could not ask Forge which checkpoint it has: {e}")
    if loaded:
        suggest([checkpoint_file(loaded)], "loaded now")

    def closest(name):
        return min(SUGGESTED_ORDER.index(why) for why in reasons[name]), name.lower()
    suggested = [{"name": name, "why": [w for w in SUGGESTED_ORDER if w in reasons[name]]}
                 for name in sorted(reasons, key=closest)]
    picked = next((s["name"] for s in suggested if s["why"][0] in PICKED_FIRST), None)

    own_row = rows.get(key(own_path)) or {}
    base = own_row.get("base_model") or base_model or gallery_base_model or ""
    same_base = sorted((c["name"] for c in checkpoints if base and c["base_model"] == base
                        and c["name"] not in reasons), key=str.lower)
    family = own_row.get("architecture") or preset_for_base_model(base) \
        or (rows.get(key(gallery_file)) or {}).get("architecture") or preset_for_base_model(gallery_base_model)
    return {"checkpoints": checkpoints, "suggested": suggested, "picked": picked,
            "same_base": {"base_model": base or None, "names": same_base},
            "loaded": loaded, "family": family or None}
