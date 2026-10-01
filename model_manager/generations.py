"""
Recording the images you generate.

Each press of Generate - txt2img or img2img - is recorded whole once Forge has
finished it: everything Forge had for it, each result saved to disk with the
infotext written into its file, and the model files every result used, so
each file's gallery can show it. scripts/model_manager_generations.py hands
Forge's hooks to the functions here; nothing else calls them.

What the hooks can see, and when - the same in Forge Neo and the original:

  before_process      the prompts as typed. Styles are merged in later, and
                      Dynamic Prompts overwrites p.prompt and p.main_prompt in
                      process; before either, they are what was typed.
  process             the files loaded: the checkpoint, and the text encoders
                      and VAE, once per-call settings have been applied.
  process_batch       the LoRAs each iteration loaded - wildcards can pick
                      different ones for each.
  postprocess_image_after_composite
                      each result, just before it is saved. Every script's
                      hook is handed the same object, and Forge saves the
                      image it holds once they are all done - which may not be
                      the image this hook sees: forge-helpers' hires cap
                      replaces it. So the object is kept, not the image.
  on_image_saved      every image Forge saves: results, and grids, masks and
                      the "before" copies. A save is a result's when its image
                      is the one a kept object holds; its path and the
                      infotext written into it are taken then.
  postprocess         the end: what was saved is written to the database.

Nothing is recorded when the setting is off, when Forge saved nothing ("Always
save all generated images" off), or for a video - Forge Neo's Wan writes one
file per iteration and says only where the last went.

A failure here is printed and swallowed: recording must never cost a
generation.
"""
import dataclasses
import enum
import importlib.util
import os
import sys
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from .db import get_models_db
from .nsfw import generated_level

# Whether generations are recorded at all; registered in ui/settings.py.
RECORD_GENERATIONS = "model_manager_record_generations"

# What a generation's state is kept under on p, for the hooks that follow.
_ATTR = "_model_manager_generation"

# A JSON value kept this deep, and no deeper: script arguments are objects
# holding objects, and a cycle among them must not recurse forever.
_MAX_DEPTH = 6

# Fields of p that are the machinery of a run rather than a setting: the
# loaded model, conditionings, the random generator, latents, masks in
# tensor form. Forge rebuilds them from the settings.
_RUNTIME_FIELDS = frozenset({
    "sd_model", "c", "uc", "hr_c", "hr_uc", "rng", "sampler", "scripts",
    "scripts_value", "script_args_value", "scripts_setup_complete",
    "cached_c", "cached_uc", "cached_hr_c", "cached_hr_uc", "init_latent",
    "image_conditioning", "nmask", "mask_for_overlay", "latent_mask",
    "overlay_images", "color_corrections", "paste_to", "extra_result_images",
    "pixels_after_sampling", "extra_network_data", "hr_extra_network_data",
    "hr_checkpoint_info", "sd_model_hash", "sd_vae_hash",
})

_lock = threading.Lock()


class _Generation(object):
    """What the hooks gather for one generation, kept on p."""

    def __init__(self):
        self.created_at = datetime.now().isoformat(timespec="seconds")
        self.typed: Dict[str, Any] = {}
        self.loaded: Dict[str, Any] = {}
        self.loras: Dict[int, List[Dict[str, Any]]] = {}
        self.results: List[Any] = []                 # PostprocessImageArgs, as handed out
        self.saved: Dict[int, Dict[str, Any]] = {}   # by result index
        self.other_saves = 0


# ------------------------------------------------------------------- hooks

def before_process(p) -> None:
    """Start a generation, and keep the prompts as they were typed."""
    if not _recording():
        return
    generation = _Generation()
    generation.typed = {
        "prompt": _text(getattr(p, "prompt", None)),
        "negative_prompt": _text(getattr(p, "negative_prompt", None)),
        "styles": list(getattr(p, "styles", None) or []),
        "hr_prompt": _text(getattr(p, "hr_prompt", None)),
        "hr_negative_prompt": _text(getattr(p, "hr_negative_prompt", None)),
    }
    setattr(p, _ATTR, generation)


def process(p) -> None:
    """The files the generation loaded, now that per-call settings apply."""
    generation = getattr(p, _ATTR, None)
    if generation is None:
        return
    try:
        generation.loaded = _loaded_files(p)
    except Exception as e:
        _report("reading the files a generation loaded", e)


def process_batch(p) -> None:
    """The LoRAs this iteration loaded, and those its hires pass names."""
    generation = getattr(p, _ATTR, None)
    if generation is None:
        return
    try:
        generation.loras[int(getattr(p, "iteration", 0))] = _iteration_loras(p)
    except Exception as e:
        _report("reading an iteration's LoRAs", e)


def result_ready(p, pp) -> None:
    """A result, about to be saved. The object is kept; see the module's note."""
    generation = getattr(p, _ATTR, None)
    if generation is not None:
        generation.results.append(pp)


def image_saved(params) -> None:
    """on_image_saved: keep the save if it is one of this generation's results."""
    p = getattr(params, "p", None)
    generation = getattr(p, _ATTR, None) if p is not None else None
    if generation is None:
        return
    try:
        image = params.image
        for pp in generation.results:
            if pp.image is image:
                path = getattr(image, "already_saved_as", None) or params.filename
                generation.saved[int(pp.index)] = {
                    "path": os.path.normpath(os.path.abspath(path)),
                    "infotext": (params.pnginfo or {}).get("parameters"),
                    "width": image.width,
                    "height": image.height,
                }
                return
        generation.other_saves += 1
    except Exception as e:
        _report("reading a saved image", e)


def postprocess(p, processed) -> Optional[int]:
    """Write the generation to the database. Returns its id, if one was written."""
    generation = getattr(p, _ATTR, None)
    if generation is None:
        return None
    try:
        delattr(p, _ATTR)
    except AttributeError:
        pass
    try:
        if getattr(processed, "video_path", None):
            print("[ModelManager] Generation not recorded: videos are not, yet")
            return None
        if not generation.saved:
            print(f"[ModelManager] Generation not recorded: none of its "
                  f"{len(generation.results)} results was saved to disk")
            return None
        return _write(p, processed, generation)
    except Exception as e:
        _report("recording a generation", e)
        return None


# ----------------------------------------------------------------- reading

def _recording() -> bool:
    try:
        from modules import shared
        return bool(getattr(shared.opts, RECORD_GENERATIONS, True))
    except Exception:
        return False


def generations_enabled() -> bool:
    """
    Whether "Your generations" is on - one switch for all of it: off, nothing
    is recorded (_recording), the Generations tab is not created at the next
    start, and the page hides it and each model's "Your generations" at once.
    What was recorded is kept either way. For the UI, a setting that cannot
    be read is on, as by default.
    """
    try:
        from modules import shared
        return bool(getattr(shared.opts, RECORD_GENERATIONS, True))
    except Exception:
        return True


def _text(value: Any) -> Optional[str]:
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, str) else None


def _path(path: Any) -> Optional[str]:
    if not path or not isinstance(path, str):
        return None
    return os.path.normpath(os.path.abspath(path))


def _checkpoint_path(name: Any) -> Optional[str]:
    """A checkpoint named as Forge's UI names it, as a file."""
    if not name or not isinstance(name, str) or name.startswith("Use same"):
        return None
    try:
        from modules import sd_models
        info = sd_models.get_closet_checkpoint_match(name)
        return _path(info.filename) if info else None
    except Exception:
        return None


def _module_paths(values: Any) -> List[str]:
    """Text encoders and VAE, named by path or by file name, as files."""
    if not isinstance(values, (list, tuple)):
        return []
    try:
        from modules_forge import main_entry
        known = getattr(main_entry, "module_list", {}) or {}
    except Exception:
        known = {}
    paths = []
    for value in values:
        if not isinstance(value, str) or value in ("Use same choices", "Built-in"):
            continue
        path = value if os.path.isabs(value) else known.get(os.path.basename(value))
        if path:
            paths.append(_path(path))
    return paths


def _loaded_files(p) -> Dict[str, Any]:
    from modules import shared
    loaded: Dict[str, Any] = {}
    model = getattr(shared, "sd_model", None) or getattr(p, "sd_model", None)
    info = getattr(model, "sd_checkpoint_info", None)
    if info is not None:
        loaded["checkpoint_path"] = _path(getattr(info, "filename", None))
        loaded["checkpoint_hash"] = getattr(info, "sha256", None) or getattr(info, "shorthash", None)
    # The modules this call runs with: Neo keeps a per-call VAE override
    # apart from the setting, and writes its infotext from it.
    overridden = getattr(sys.modules.get("modules.processing"), "_overridden_modules", None)
    modules = overridden or getattr(shared.opts, "forge_additional_modules", None) or []
    loaded["modules"] = _module_paths(list(modules))
    if getattr(p, "enable_hr", False):
        loaded["hr_checkpoint_path"] = _checkpoint_path(getattr(p, "hr_checkpoint_name", None))
        hr_modules = getattr(p, "hr_additional_modules", None)
        loaded["hr_modules"] = (None if hr_modules is None or "Use same choices" in hr_modules
                                else _module_paths(hr_modules))
    loaded["refiner_path"] = _checkpoint_path(getattr(p, "refiner_checkpoint", None))
    return loaded


def _number(value: Any) -> Any:
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _networks_module():
    # The built-in LoRA extension's module; absent when it is disabled.
    return sys.modules.get("networks")


def _iteration_loras(p) -> List[Dict[str, Any]]:
    networks = _networks_module()
    if networks is None:
        return []
    loras = []
    for net in getattr(networks, "loaded_networks", None) or []:
        on_disk = getattr(net, "network_on_disk", None)
        loras.append({
            "name": getattr(net, "name", None),
            "path": _path(getattr(on_disk, "filename", None)),
            "te_multiplier": getattr(net, "te_multiplier", None),
            "unet_multiplier": getattr(net, "unet_multiplier", None),
            "pass": "base",
        })
    # The hires pass loads its own when its prompt names them, during
    # sampling and after this hook; they are found by name, as Forge does.
    if getattr(p, "enable_hr", False):
        by_name = getattr(networks, "available_networks", {}) or {}
        by_alias = getattr(networks, "available_network_aliases", {}) or {}
        for entry in (getattr(p, "hr_extra_network_data", None) or {}).get("lora", []) or []:
            items = getattr(entry, "items", None) or []
            if not items:
                continue
            on_disk = by_name.get(items[0]) or by_alias.get(items[0])
            loras.append({
                "name": items[0],
                "path": _path(getattr(on_disk, "filename", None)),
                # The prompt's text, "0.7"; a number, as the base pass's are.
                "weight": _number(items[1]) if len(items) > 1 else None,
                "pass": "hires",
            })
    return loras


def _jsonable(value: Any, depth: int = 0) -> Any:
    """A value as JSON can hold it. Images are left out, and say so."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= _MAX_DEPTH:
        return {"omitted": "too deep"}
    kind = type(value).__name__
    module = type(value).__module__ or ""
    # Images - PIL's, and arrays and tensors of pixels - are not kept: a
    # ControlNet unit carries its input image, and storing files for inputs
    # was left out on purpose. The key stays, saying what was there.
    if (module.startswith("PIL.") or callable(getattr(value, "getpixel", None))
            or kind == "ndarray" or module.startswith("torch")):
        return {"omitted": kind}
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v, depth + 1) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name, None), depth + 1)
                for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return _jsonable(value.value, depth + 1)
    if hasattr(value, "__dict__"):
        return {k: _jsonable(v, depth + 1) for k, v in vars(value).items()
                if not k.startswith("_")}
    return {"omitted": kind}


def _params(p) -> Dict[str, Any]:
    """Every field of p, under Forge's own names, but the run's machinery."""
    if dataclasses.is_dataclass(p):
        names = [f.name for f in dataclasses.fields(p)]
    else:
        names = [k for k in vars(p) if not k.startswith("_")]
    return {name: _jsonable(getattr(p, name, None)) for name in names
            if name not in _RUNTIME_FIELDS and name != _ATTR}


def _extra_params(p) -> Dict[str, Any]:
    """extra_generation_params with one value for the whole generation.
    Those that differ per image - lists, callables - are in each infotext."""
    extra = getattr(p, "extra_generation_params", None) or {}
    return {k: v for k, v in extra.items() if v is None or isinstance(v, (str, int, float, bool))}


def _script_args(p) -> Dict[str, Any]:
    """Each always-on script's arguments, by its title."""
    runner = getattr(p, "scripts", None)
    args = list(getattr(p, "script_args", None) or [])
    found: Dict[str, Any] = {}
    for script in getattr(runner, "alwayson_scripts", None) or []:
        start, end = getattr(script, "args_from", None), getattr(script, "args_to", None)
        if start is None or end is None or start >= end:
            continue
        try:
            title = script.title()
        except Exception:
            title = type(script).__name__
        found[title] = _jsonable(args[start:end])
    return found


def _settings() -> Dict[str, Any]:
    """The settings Forge marks as belonging in an infotext, as they are now."""
    from modules import shared
    data = getattr(shared.opts, "data", None) or {}
    found: Dict[str, Any] = {}
    for key, info in (getattr(shared.opts, "data_labels", None) or {}).items():
        if getattr(info, "infotext", None):
            found[key] = _jsonable(data.get(key, getattr(info, "default", None)))
    for key in ("sd_model_checkpoint", "forge_additional_modules", "sd_vae"):
        if key in data:
            found[key] = _jsonable(data[key])
    return found


def _forge() -> str:
    """Which Forge made it, and its version."""
    try:
        # Neo keeps Forge's own packages there; the original Forge does not.
        neo = importlib.util.find_spec("modules_forge.packages") is not None
    except ImportError:
        neo = False
    version = ""
    try:
        from modules import launch_utils
        version = launch_utils.git_tag()
    except Exception:
        pass
    # Neo's tag names it already - "neo 2.29" - which read "Forge Neo neo 2.29".
    if neo and version.lower().startswith("neo"):
        version = version[3:].strip()
    return ("Forge Neo" if neo else "Forge") + (f" {version}" if version else "")


def _parse_generation_parameters(infotext: str) -> Dict[str, Any]:
    """Forge's own infotext parser - the one its paste uses."""
    try:
        from modules.infotext_utils import parse_generation_parameters
    except ImportError:
        from modules.generation_parameters_copypaste import parse_generation_parameters
    return parse_generation_parameters(infotext)


# An infotext's names for what a Civitai image's meta calls otherwise; the
# gallery's cards and the NSFW rule read those.
_META_NAMES = {"Prompt": "prompt", "Negative prompt": "negativePrompt", "Steps": "steps",
               "Sampler": "sampler", "CFG scale": "cfgScale", "Seed": "seed"}


def infotext_meta(infotext: Optional[str], width: Optional[int] = None,
                  height: Optional[int] = None) -> Dict[str, Any]:
    """
    An infotext as a Civitai image's meta: its prompt as `prompt`, its steps as
    `steps` and so on, the rest under the infotext's own names. Derived from
    the infotext, which is kept as written; this can be made again from it.
    """
    if not infotext:
        return {}
    parsed = _parse_generation_parameters(infotext)
    meta = {}
    for key, value in parsed.items():
        meta[_META_NAMES.get(key, key)] = value
    if "Size" not in meta and meta.get("Size-1") and meta.get("Size-2"):
        meta["Size"] = f"{meta['Size-1']}x{meta['Size-2']}"
    if "Size" not in meta and width and height:
        meta["Size"] = f"{width}x{height}"
    return meta


def _main_infotext(p, first: Optional[str]) -> Optional[str]:
    """The generation's infotext, as Forge writes it for a grid; the first
    result's when Forge cannot say."""
    try:
        from modules import processing
        return processing.create_infotext(p, p.all_prompts, p.all_seeds, p.all_subseeds,
                                          use_main_prompt=True)
    except Exception:
        return first


def _at(values: Any, index: int) -> Any:
    try:
        return values[index]
    except (TypeError, IndexError):
        return None


# ----------------------------------------------------------------- writing

def _write(p, processed, generation: _Generation) -> int:
    db = get_models_db()

    batch_size = int(getattr(p, "batch_size", 1) or 1)
    hires = bool(getattr(p, "enable_hr", False))
    loaded = generation.loaded

    images: List[Dict[str, Any]] = []
    used: List[List[str]] = []
    for index in sorted(generation.saved):
        saved = generation.saved[index]
        iteration = index // batch_size
        loras = generation.loras.get(iteration, [])
        meta = infotext_meta(saved["infotext"], saved["width"], saved["height"])
        images.append({
            "position": index,
            "iteration": iteration,
            "path": saved["path"],
            "infotext": saved["infotext"],
            "meta": meta,
            "prompt": _at(getattr(p, "all_prompts", None), index),
            "negative_prompt": _at(getattr(p, "all_negative_prompts", None), index),
            "seed": _at(getattr(p, "all_seeds", None), index),
            "subseed": _at(getattr(p, "all_subseeds", None), index),
            "hr_prompt": _at(getattr(p, "all_hr_prompts", None), index) if hires else None,
            "hr_negative_prompt": (_at(getattr(p, "all_hr_negative_prompts", None), index)
                                   if hires else None),
            "loras": loras,
            "width": saved["width"],
            "height": saved["height"],
            "prompt_nsfw_level": generated_level(meta),
        })
        files = [loaded.get("checkpoint_path"), loaded.get("hr_checkpoint_path"),
                 loaded.get("refiner_path")]
        files += loaded.get("modules") or []
        files += loaded.get("hr_modules") or []
        files += [lora.get("path") for lora in loras]
        used.append([f for f in files if f])

    # Each file as the library spells it, so a gallery joins on equality; a
    # file the library does not hold keeps Forge's spelling, normalised.
    spelled = db.library_spelling({f for files in used for f in files})
    used = [[spelled.get(f, f) for f in files] for files in used]

    row = dict(generation.typed)
    row.update({
        "created_at": generation.created_at,
        "mode": "img2img" if hasattr(p, "init_images") else "txt2img",
        "forge": _forge(),
        "n_iter": getattr(p, "n_iter", None),
        "batch_size": batch_size,
        "width": getattr(p, "width", None),
        "height": getattr(p, "height", None),
        "checkpoint_path": loaded.get("checkpoint_path"),
        "checkpoint_hash": loaded.get("checkpoint_hash"),
        "modules": loaded.get("modules"),
        "hr_checkpoint_path": loaded.get("hr_checkpoint_path"),
        "hr_modules": loaded.get("hr_modules"),
        "refiner_path": loaded.get("refiner_path"),
        "params": _params(p),
        "extra_params": _extra_params(p),
        "script_args": _script_args(p),
        "settings": _settings(),
        "infotext": _main_infotext(p, images[0]["infotext"]),
        "image_count": len(images),
        "prompt_nsfw_level": max(image["prompt_nsfw_level"] for image in images),
    })

    with _lock:
        generation_id = db.record_generation(row, images, used)
    files = {f for files in used for f in files}
    print(f"[ModelManager] Recorded generation {generation_id} ({row['mode']}): "
          f"{len(images)} of {len(generation.results)} results saved, "
          f"{generation.other_saves} other images saved and not recorded, "
          f"{len(files)} model files, {len(spelled)} of them in the library")
    return generation_id


def _report(what: str, error: Exception) -> None:
    print(f"[ModelManager] Error {what}: {error}")
