"""
Send's one place (#302): how Forge is set up before a source's settings go
into its tab - a Civitai image, a generation of your own, a queued task.

One plan for every source (`plan`), asked of one route
(`/model-manager/send/plan`). Each source had a route and a function of its
own - `/forge-modules` for a Civitai image, `/generations/{id}/send-plan`,
`/queue/tasks/{id}/send-plan` - which call the same functions here until the
page asks this one alone.

What the page still reads of a Civitai image itself, it sends with the
source: the checkpoint the image names (`imageCheckpoint` in send.mjs), which
also decides whether its Send button is drawn at all. The VAEs it names are
read here (`named_modules`), from the image's stored record.
"""
import os
import re
from typing import Any, Callable, Dict, List, Optional

from .console import say


# ------------------------------------------------------------- the plan

def plan(db, source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    How to set Forge up for a source, by its `kind`:

        civitai     `image` (its id), the gallery's `file_path` and
                    `base_model`, the checkpoint the page read of it -
                    `version_ids`, `hashes`, `model_name` - and `use_version`
        generation  `generation`, and `use_version`
        task        `task`

    Returns:
        The kind's plan with `kind` added, or None for no such source.
    """
    kind = source.get("kind")
    if kind == "civitai":
        record = next(iter(db.stored_records([int(source.get("image") or 0)])), None)
        if record is None:
            return None
        answer = civitai_plan(db, source.get("file_path") or "", source.get("base_model") or "",
                              source.get("version_ids") or "", source.get("hashes") or "",
                              source.get("model_name") or "", "", named_modules(record.get("meta")),
                              int(source.get("use_version") or 0))
    elif kind == "generation":
        answer = generation_plan(db, int(source.get("generation") or 0), source.get("use_version") or None)
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
                      instead: bool = False, local: Optional[Callable[[], dict]] = None) -> dict:
    """
    The image's checkpoint for a send from a gallery that is not a
    checkpoint's: {checkpoint: Forge's name for it} or {checkpoint_problem}.
    `instead`: the version asked for is not the image's own (#278) - the
    answer names the file sent with, for the page to say. `local`: the
    library's checkpoint the image names, looked up once for the whole plan.
    See civitai_plan().
    """
    from .forge_host import checkpoint_name
    from .model_dirs import loads_here
    from .send_plan import image_checkpoint
    try:
        found = image_checkpoint(db, file_path, version_ids.split(","), hashes.split(","), model_name, local=local)
    except Exception as e:
        say(f"Could not work out the image's checkpoint: {e}")
        return {}
    path = found.get("path")
    if path:
        name = checkpoint_name(path)
        if name:
            return {"checkpoint": name, "instead": os.path.basename(path)} if instead else {"checkpoint": name}
        reason = "not_listed" if loads_here(path) else "elsewhere"
        return {"checkpoint_problem": {"reason": reason, "name": os.path.basename(path), "path": path}}
    if found.get("missing"):
        return {"checkpoint_problem": {"reason": "missing", "name": found["missing"]}}
    if found.get("not_checkpoint"):
        return {"checkpoint_problem": {"reason": "not_checkpoint"}}
    return {}


def _listed_label(path: str, installed: dict):
    """The label Forge lists a module file under, by its path; None if it does not list it."""
    wanted = os.path.normcase(os.path.abspath(path))
    return next((label for label, listed in installed.items()
                 if listed and os.path.normcase(os.path.abspath(listed)) == wanted), None)


def civitai_plan(db, file_path: str = "", base_model: str = "", version_ids: str = "", hashes: str = "",
                 model_name: str = "", vae: str = "", module: List[str] = (), use_version: int = 0) -> Dict[str, Any]:
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
        use_version: Send with the library's file of this version, not the
            checkpoint the image names - another file of its version, or
            another version of its model, picked in the Resources dialog
            (#278). The answer's `instead` names the file.

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
        yet, {reason: not_checkpoint} - and the page sends nothing. From a
        VAE's or a text encoder's, that file is in `target` in its kind's
        place; own_not_listed, its name when Forge does not list it. From an
        upscaler's, upscaler: the name Forge lists it under, for Hires fix's;
        upscaler_not_listed, its file's when Forge does not.
    """
    from .file_identity import classify_file
    from .forge_host import embedding_kind, installed_modules, saved_modules
    from .forge_modules import CLASS_FOR_PRESET, NEEDS, match_module, pick, preferred_modules
    from .send_plan import SendModel, local_checkpoint, named_ids, plan_model

    if use_version:
        # The version picked stands for the image's checkpoint, whatever
        # the image names: its preset, its modules, the file loaded.
        version_ids, hashes, model_name = str(use_version), "", ""
    # The library's checkpoint the image names: the model to set up for and
    # the checkpoint to load both start from it, looked up once (#302).
    looked_up: Dict[str, dict] = {}

    def local() -> dict:
        if "row" not in looked_up:
            looked_up["row"] = local_checkpoint(db, file_path, *named_ids(version_ids.split(","), hashes.split(",")))
        return looked_up["row"]

    try:
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
              "target": [], "modules_not_found": [], "bundled": [],
              "checkpoint": None, "checkpoint_problem": None, "own_not_listed": None,
              "upscaler": None, "upscaler_not_listed": None}
    gallery_type = ((db.get_version(file_path) or {}).get("file_type") if file_path else None)
    if gallery_type != "Checkpoint":
        answer.update(_image_checkpoint(db, file_path, version_ids, hashes, model_name, bool(use_version), local))
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
    # and each `Module N` - Forge's own record of what was selected.
    named, unlisted = [], []
    for name in dict.fromkeys(n.strip() for n in [vae, *module] if n and n.strip()):
        label = match_module(name, installed)
        if label is None:
            unlisted.append(name)
        elif label not in named:
            named.append(label)

    if not answer["manage_modules"]:
        # SD and SDXL bring their own: what the image names, if anything;
        # a VAE's gallery takes the VAE's place.
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


def _truthy(value: Any) -> bool:
    """Truth as the page's JavaScript read it, which the readers below were
    ported from: an empty list or object is true there."""
    if value is None or value is False or value == "":
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == value and value != 0
    return True


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


def generation_plan(db, generation_id: int, use_version: Optional[int] = None) -> Optional[Dict[str, Any]]:
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

    Returns:
        plan_for()'s answer, or None for no such generation.
    """
    generation = db.get_generation(generation_id)
    if not generation:
        return None
    path = generation.get("checkpoint_path") or ""
    modules = generation.get("modules") or []
    if use_version:
        # The person chose, in the Resources dialog Send opened, to send with
        # the file of the image's version the library holds - not the file the
        # image was made with (#233): the first of them Forge lists.
        from .forge_host import checkpoint_name
        held = next((r["file_path"] for r in db.library_files(version_ids=[int(use_version)])
                     if checkpoint_name(r["file_path"])), None)
        if held:
            plan = plan_for(db, held, modules)
            plan["instead"] = os.path.basename(held)
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
