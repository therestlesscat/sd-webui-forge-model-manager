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
        # The VAE the image names, for a WebUI without Forge's VAE / Text
        # Encoder control: the page selects it by name, as it always did.
        answer["named_vae"] = named_vae(record.get("meta"))
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


def _normalised(text: Any) -> str:
    """A sampler's name as names are compared: lower case, `_ - +` as spaces."""
    if not _truthy(text):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[_\-+]", " ", str(text).lower())).strip()


def match_sampler(name: Any, samplers: List[str]) -> Any:
    """The sampler Forge lists for a name an image gives, by case and `_ - +`;
    the name with its underscores as spaces when none matches."""
    if not _truthy(name) or not samplers:
        return name
    if name in samplers:
        return name
    wanted = _normalised(name)
    for sampler in samplers:
        if _normalised(sampler) == wanted:
            return sampler
    return str(name).replace("_", " ")


def split_sampler(text: Any, samplers: List[str], schedulers: List[str]) -> Dict[str, Any]:
    """
    An image's sampler text read by Forge's samplers and schedulers: "Euler a
    Karras" is the sampler "Euler a" and the schedule type "Karras" (#88).
    `schedulers` as Forge lists them, Automatic left out, in Forge's order.
    """
    if not _truthy(text):
        return {"sampler": None, "scheduler": None}
    whole = str(text).replace("_", " ")
    for scheduler in schedulers:
        if whole.endswith(" " + scheduler) or whole.lower().endswith(" " + scheduler.lower()):
            return {"sampler": match_sampler(whole[:-(len(scheduler) + 1)], samplers), "scheduler": scheduler}
    return {"sampler": match_sampler(whole, samplers), "scheduler": None}


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
            "Size", "Model", "Model hash", "VAE", "Denoising strength", "Clip skip",
            "Hires upscale", "Hires upscaler", "Hires steps", "Hires resize-1", "Hires resize-2",
            "resources", "civitaiResources", "Lora hashes")


def had_hires(meta: Dict[str, Any]) -> bool:
    """Whether an image's data says it was made with Hires fix, as Forge's paste reads it."""
    return _truthy(meta.get("Denoising strength")) and any(
        _truthy(meta.get(k)) for k in ("Hires upscale", "Hires upscaler", "Hires resize-1", "Hires resize-2"))


def image_scheduler(meta: Dict[str, Any], samplers: List[str], schedulers: List[str]) -> Any:
    """The schedule type an image names: its `Schedule type`, else the one its sampler's name ends in."""
    scheduler = meta.get("Schedule type")
    if not _truthy(scheduler) and _truthy(meta.get("sampler")):
        scheduler = split_sampler(meta.get("sampler"), samplers, schedulers)["scheduler"]
    return scheduler


def build_infotext(meta: Any, samplers: List[str], schedulers: List[str],
                   denoising_strength: Any = None, hires_upscaler: Any = None) -> str:
    """
    A Civitai image's generation data as an infotext Forge's paste reads:
    the prompt, the negative prompt, then a settings line. What Forge's paste
    sets a control from goes in it (#138): the upscaler, ADetailer's switch,
    a video's frames. `denoising_strength`: img2img always takes one - an
    image-to-video model needs 1 - and txt2img only as part of Hires fix,
    where it would otherwise turn Hires fix on. `hires_upscaler`: an
    upscaler's gallery's own, over the image's (#134).
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

    sampler = meta.get("sampler")
    scheduler = meta.get("Schedule type")
    if not _truthy(scheduler) and _truthy(sampler):
        split = split_sampler(sampler, samplers, schedulers)
        sampler, scheduler = split["sampler"], split["scheduler"]
    hires = had_hires(meta)

    params = []
    if _truthy(meta.get("steps")):
        params.append(f"Steps: {_js_text(meta['steps'])}")
    if _truthy(sampler):
        params.append(f"Sampler: {_js_text(sampler)}")
    if _truthy(scheduler):
        params.append(f"Schedule type: {_js_text(scheduler)}")
    if _truthy(meta.get("cfgScale")):
        params.append(f"CFG scale: {_js_text(meta['cfgScale'])}")
    # Seed 0 is a seed (#310).
    if meta.get("seed") is not None and meta.get("seed") != "":
        params.append(f"Seed: {_js_text(meta['seed'])}")
    for key in ("Size", "Model", "Model hash", "VAE", "Clip skip"):
        if _truthy(meta.get(key)):
            params.append(f"{key}: {_js_text(meta[key])}")
    denoise = denoising_strength if denoising_strength is not None else (meta.get("Denoising strength") if hires else None)
    if denoise is not None:
        params.append(f"Denoising strength: {_js_text(denoise)}")
    if hires:
        if _truthy(meta.get("Hires upscale")):
            params.append(f"Hires upscale: {_js_text(meta['Hires upscale'])}")
        if _truthy(meta.get("Hires upscaler")) and not _truthy(hires_upscaler):
            params.append(f"Hires upscaler: {_js_text(meta['Hires upscaler'])}")
        if _truthy(meta.get("Hires steps")):
            params.append(f"Hires steps: {_js_text(meta['Hires steps'])}")
    if _truthy(hires_upscaler):
        params.append(f"Hires upscaler: {_js_text(hires_upscaler)}")
    # ADetailer's paste turns its tab on or off by this switch.
    params.append("ADetailer enable: True" if any(k.startswith("ADetailer ") for k in meta) else "ADetailer enable: False")
    # Every other field as it is, in the page's order: JavaScript's object
    # order puts a key that reads as an array index first, by number.
    keys = sorted((k for k in meta if re.fullmatch(r"0|[1-9]\d*", k) and int(k) < 2 ** 32 - 1), key=int) \
        + [k for k in meta if not (re.fullmatch(r"0|[1-9]\d*", k) and int(k) < 2 ** 32 - 1)]
    for key in keys:
        value = meta[key]
        if key not in _HANDLED and value is not None and value != "" and not isinstance(value, (dict, list)):
            params.append(f"{key}: {_js_text(value)}")
    if params:
        infotext += "\n" + ", ".join(params)
    return infotext


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


def _size_of(text: Any) -> Optional[tuple]:
    match = re.fullmatch(r"\s*(\d+)\s*x\s*(\d+)\s*", str(text or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def civitai_meta(record: Dict[str, Any], frames: Any = None, video: bool = False) -> Dict[str, Any]:
    """
    A Civitai image's data as Send reads it: its own, with a `Size` when it
    gives none - the picture's, else its width and height - and the picture's
    size where the data's shape differs from it by more than 3% (#299). For
    an image-to-video model, its size as Wan makes it and its frames.
    """
    meta = dict(record.get("meta") or {})
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
                     video: bool = False, prompt: Any = None, negative_prompt: Any = None) -> str:
    """
    The infotext a Send of a Civitai image pastes: civitai_meta(), with the
    page's prompts where it renamed a LoRA tag to the library's file (the
    chips' rule), built (build_infotext), its Lora hashes left out.
    """
    meta = civitai_meta(record, frames, video)
    if prompt is not None:
        meta["prompt"] = prompt
    if negative_prompt is not None:
        meta["negativePrompt"] = negative_prompt
    return without_lora_hashes(build_infotext(meta, samplers, schedulers, denoising_strength, hires_upscaler))


def forge_lists() -> tuple:
    """Forge's samplers, and its schedulers but Automatic, as the page's sampler reading took them."""
    from .forge_host import samplers, schedulers
    try:
        return list(samplers()), [s for s in schedulers() if s and s != "Automatic"]
    except Exception as e:
        say(f"Send: Forge's samplers could not be read: {e}")
        return [], []


def civitai_settings(db, source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    What the loader sets a tab with for a Civitai image's source (#302): the
    infotext Forge's paste reads, and what the page set after the paste and
    now goes in the same event - the schedule type (the image's, else
    Automatic) and whether Hires fix stays off.

    `source`, as the page sends it: `image` (its id), `upscaler` (an
    upscaler's gallery's own, for Hires fix), `denoise` (img2img's for an
    image-to-video model), `video` and `frames`, and `prompt` /
    `negative_prompt` where the chips renamed a LoRA tag. None for no such
    image.
    """
    record = next(iter(db.stored_records([int(source.get("image") or 0)])), None)
    if record is None:
        return None
    samplers, schedulers = forge_lists()
    meta = civitai_meta(record, source.get("frames"), bool(source.get("video")))
    return {
        "text": civitai_infotext(record, samplers, schedulers, denoising_strength=source.get("denoise"),
                                 hires_upscaler=source.get("upscaler"), frames=source.get("frames"),
                                 video=bool(source.get("video")), prompt=source.get("prompt"),
                                 negative_prompt=source.get("negative_prompt")),
        "scheduler": image_scheduler(meta, samplers, schedulers) or "Automatic",
        "hires": had_hires(meta),
    }


# ------------------------------------------------- the card's reading

def card_reading(meta: Any, samplers: List[str], schedulers: List[str]) -> Dict[str, Any]:
    """
    The sampler and schedule type an image's card shows (#302): its
    `Schedule type`; else its sampler's name read for one, as Forge names
    both ("Euler a Karras" is Euler a and Karras), the sampler then the one
    Forge lists - else the sampler as given. Ported from the card's own
    reading (imageTextHtml in image_card.mjs), and written on each image
    beside its level (`stamp_readings`), as the page reads the level.
    """
    meta = meta if isinstance(meta, dict) else {}
    sampler, scheduler = meta.get("sampler"), meta.get("Schedule type")
    if not _truthy(scheduler) and _truthy(sampler):
        split = split_sampler(sampler, samplers, schedulers)
        sampler, scheduler = split["sampler"], split["scheduler"]
    return {"mm_sampler": sampler, "mm_scheduler": scheduler}


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


def replays(generation: Dict[str, Any], into: bool) -> bool:
    """Whether a generation's Send sets its kept press back (#7) rather than
    pasting its infotext: it kept one, and goes back to its own tab - into
    img2img (#299) only an img2img generation's press."""
    return bool(generation.get("inputs")) and (not into or generation.get("mode") == "img2img")


def generation_settings(db, source: Dict[str, Any], into: bool = False) -> Optional[Dict[str, Any]]:
    """
    What the loader sets a tab with for a generation of your own (#302): the
    image's own infotext, the chips' renames applied and its Lora hashes left
    out, as the page pasted it; the schedule type and Hires fix the page set
    after the paste, read from the image's data as it read them; and whether
    its kept press is replayed instead (`replays`).

    `source`: `generation`, `image` (its id; else the first image),
    `renames`, the page's `{from, to}`, and `whole` for the Model Manager's
    card, which sends the generation's own infotext - its first image's
    where it has none - as the page did (`card.infotext || first.infotext`:
    2 of one library's 7,174 differ). None for no such generation.
    """
    generation = db.get_generation(int(source.get("generation") or 0))
    if not generation:
        return None
    images = generation.get("images") or []
    image = next((i for i in images if i.get("id") == source.get("image")), images[0] if images else {})
    meta = image.get("meta") or {}
    infotext = (generation.get("infotext") if source.get("whole") else None) or image.get("infotext") or ""
    samplers, schedulers = forge_lists()
    return {
        "text": without_lora_hashes(renamed(infotext, source.get("renames"))) if infotext else "",
        "scheduler": image_scheduler(meta, samplers, schedulers) or "Automatic",
        "hires": had_hires(meta),
        "replay": replays(generation, into),
        "mode": generation.get("mode"),
    }


def settings(db, source: Dict[str, Any], into: bool = False) -> Optional[Dict[str, Any]]:
    """The loader's settings for a source: a Civitai image's or a generation's."""
    if source.get("kind") == "generation":
        return generation_settings(db, source, into)
    return civitai_settings(db, source)


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
