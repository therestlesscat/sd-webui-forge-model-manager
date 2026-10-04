"""
What the extension asks of the WebUI it runs in.

The one module of the extension's package that imports Forge (`modules`,
`modules_forge`); ui/settings.py, which builds Forge's settings page, is the
other, and tests/tools/check_forge_imports.py keeps it so. Twenty files used
to ask Forge themselves, each with its own guard for a WebUI that was not
there, and where Neo and the original Forge keep a thing in different places
- the infotext parser, the detector's converter, the preset control - each
asker had to know.

The extension's settings live in Forge's options (shared.opts), registered
by ui/settings.py under Settings -> Model Manager. Each was read where it
was used, with its own default written beside the read and its own guard
for a WebUI that was not there - thirty-odd copies, which agreed only
because nobody had changed one yet. DEFAULTS is the one list of them;
registration takes its defaults from it, and setting() is how they are read.

Forge is imported only when something is asked, so the rest of the
extension, and its tests, work where it is not installed: a setting then
reads as its default, a list Forge keeps as empty, and a question only Forge
can answer raises, as it did where it was asked before.
"""
import importlib.util
import os
import sys
from typing import Any, Callable, Dict, List, Optional

# Every setting the extension registers, and its default: what it reads as
# until a person saves it, and wherever Forge cannot be asked. In the order
# Settings -> Model Manager lists them.
DEFAULTS = {
    "model_manager_civitai_api_key": "",
    "model_manager_page_size": 20,
    "model_manager_database_path": "",
    "model_manager_preview_least_nsfw": True,
    "model_manager_gallery_hide_nsfw": True,
    "model_manager_civitai_page_size": 20,
    "model_manager_hide_promptless_images": True,
    "model_manager_record_generations": True,
    "model_manager_generations_hide_nsfw": True,
    "model_manager_gallery_page_size": 100,
    "model_manager_civitai_folder_template": "_{baseModel}/{modelName}",
    "model_manager_civitai_requests_per_second": 6,
    "model_manager_hash_threads": 4,
    "model_manager_civitai_min_prompt_images": 1,
    "model_manager_civitai_sfw_fill_page": False,
    "model_manager_card_size": "200x280",
    "model_manager_civitai_card_size": "200x280",
    "model_manager_nsfw_prompt_words": "",
    "model_manager_nsfw_detection": "model",
    "model_manager_nsfw_prompt_model_percent": 2.0,
    "model_manager_check_updates": True,
    # The text encoders and VAE named for each preset (forge_modules.MODULE_PRESETS).
    "model_manager_modules_flux": "",
    "model_manager_modules_klein": "",
    "model_manager_modules_lumina": "",
    "model_manager_modules_zit": "",
    "model_manager_modules_anima": "",
    "model_manager_modules_wan": "",
    "model_manager_modules_qwen": "",
    "model_manager_modules_krea": "",
    "model_manager_modules_ernie": "",
    "model_manager_modules_pid": "",
}


def available() -> bool:
    """Whether there is a WebUI to ask - none where a tool imports the extension."""
    try:
        from modules import shared  # noqa: F401
    except ImportError:
        return False
    return True


def setting(key: str) -> Any:
    """
    One of the extension's settings: what Forge holds, else its default.

    A key not in DEFAULTS raises KeyError - a misspelt name read as a
    default would never be noticed.
    """
    default = DEFAULTS[key]
    try:
        from modules import shared
    except ImportError:
        return default
    return getattr(shared.opts, key, default)


# ------------------------------------------------------- Forge's own settings

def registered_options() -> Dict[str, Any]:
    """Every setting registered with the WebUI, the extension's and everyone
    else's: key -> its OptionInfo, in the order they were registered."""
    from modules import shared
    return shared.opts.data_labels


def store_settings(values: Dict[str, Any]) -> List[str]:
    """Set settings, and write Forge's config file if any changed - the keys
    that did."""
    from modules import shared
    changed = [key for key, value in values.items() if shared.opts.set(key, value)]
    if changed:
        shared.opts.save(shared.config_filename)
    return changed


def infotext_settings() -> Dict[str, Any]:
    """The settings Forge marks as belonging in an infotext, as they are now."""
    from modules import shared
    data = getattr(shared.opts, "data", None) or {}
    found: Dict[str, Any] = {}
    for key, info in (getattr(shared.opts, "data_labels", None) or {}).items():
        if getattr(info, "infotext", None):
            found[key] = data.get(key, getattr(info, "default", None))
    for key in ("sd_model_checkpoint", "forge_additional_modules", "sd_vae"):
        if key in data:
            found[key] = data[key]
    return found


# --------------------------------------------------------- where models live

def model_folders():
    """The WebUI's command-line options and models path; empty outside it."""
    try:
        from modules import paths, shared
        return getattr(shared, "cmd_opts", None), getattr(paths, "models_path", "") or ""
    except ImportError:
        return None, ""


def webui_root() -> str:
    """The WebUI's own folder, which the pages show paths from; empty outside it."""
    try:
        from modules import paths
        return getattr(paths, "script_path", "") or ""
    except ImportError:
        return ""


# ---------------------------------------------------------------- checkpoints

def checkpoint_name(path: str) -> Optional[str]:
    """
    The name Forge lists a checkpoint file under, for its selectCheckpoint(),
    or None if Forge does not list it - it is gone, or outside every folder
    Forge looks in. Found by the file, not guessed from its folders.
    """
    if not path:
        return None
    try:
        from modules import sd_models
        wanted = os.path.normcase(os.path.abspath(path))
        for info in sd_models.checkpoints_list.values():
            if os.path.normcase(os.path.abspath(info.filename)) == wanted:
                return info.title
    except Exception as e:
        print(f"[ModelManager] Could not ask Forge for its checkpoints: {e}")
    return None


def upscaler_name(path: str) -> Optional[str]:
    """
    The name Forge lists an upscaler file under, for txt2img's Hires
    "Upscaler", or None if it does not list it (#134). Both WebUIs name a
    file by its name less its extension, the original Forge's built-ins
    apart ("R-ESRGAN 4x+"), and read their upscalers once, at startup: one
    added since is not offered until a restart. Found by the file.
    """
    if not path:
        return None
    try:
        from modules import shared
        wanted = os.path.normcase(os.path.abspath(path))
        for scaler in getattr(shared, "sd_upscalers", None) or []:
            listed = getattr(scaler, "data_path", None)
            if listed and not str(listed).startswith("http") \
                    and os.path.normcase(os.path.abspath(listed)) == wanted:
                return scaler.name
    except Exception as e:
        print(f"[ModelManager] Could not ask Forge for its upscalers: {e}")
    return None


def closest_checkpoint(name: str):
    """The checkpoint Forge means by a name as its UI writes one - with a
    hash, or without its folder - or None."""
    from modules import sd_models
    return sd_models.get_closet_checkpoint_match(name)


def loaded_model():
    """The model Forge has loaded, or None."""
    from modules import shared
    return getattr(shared, "sd_model", None)


# ---------------------------------------------------- text encoders and VAE

def installed_modules() -> Dict[str, str]:
    """
    The modules Forge offers in its VAE / Text Encoder control: label -> path.

    Forge's own list (modules_forge.main_entry.module_list), keyed by the
    file name it shows. Empty where Forge is not there to ask.
    """
    try:
        from modules_forge import main_entry
        return dict(main_entry.module_list)
    except Exception:
        return {}


def saved_modules(preset: str) -> List[str]:
    """The modules Forge remembers for a UI preset, as the labels it shows."""
    try:
        from modules import shared
        paths = getattr(shared.opts, f"forge_additional_modules_{preset}", None) or []
        return [os.path.basename(p) for p in paths]
    except Exception:
        return []


def current_modules() -> Optional[List[str]]:
    """
    The modules Forge holds now, as the labels it shows - what it will load,
    whatever its control shows. None where Forge is not there to ask.
    """
    try:
        from modules import shared
        return sorted(os.path.basename(p) for p in shared.opts.forge_additional_modules or [])
    except Exception:
        return None


def loaded_modules() -> List[str]:
    """
    The text encoders and VAE a generation runs with, as Forge names them.
    Neo keeps a per-call override apart from the setting, and writes its
    infotext from it.
    """
    from modules import shared
    overridden = getattr(sys.modules.get("modules.processing"), "_overridden_modules", None)
    return overridden or getattr(shared.opts, "forge_additional_modules", None) or []


# ---------------------------------------- presets, samplers and schedulers

def available_presets() -> Optional[List[str]]:
    """
    The UI presets this WebUI has, from its own preset control - Forge Neo's
    dozen, or the original Forge's sd, xl, flux and all. None where it cannot
    be asked.
    """
    try:
        from modules_forge import main_entry
        choices = getattr(getattr(main_entry, "ui_forge_preset", None), "choices", None)
        if choices:
            return [c[1] if isinstance(c, (tuple, list)) else c for c in choices]
    except Exception:
        pass
    try:
        from modules_forge.presets import PresetArch
        return PresetArch.choices()
    except Exception:
        return None


def samplers() -> List[str]:
    """The samplers Forge offers, by name."""
    from modules import sd_samplers
    return [s.name for s in sd_samplers.all_samplers]


def schedulers() -> List[str]:
    """The schedulers Forge offers, by label."""
    from modules import sd_schedulers
    return [s.label for s in sd_schedulers.schedulers]


# ------------------------------------- which Forge, and where the two differ

def forge_name() -> str:
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


def parse_generation_parameters(infotext: str) -> Dict[str, Any]:
    """Forge's own infotext parser - the one its paste uses."""
    try:
        from modules.infotext_utils import parse_generation_parameters
    except ImportError:
        from modules.generation_parameters_copypaste import parse_generation_parameters
    return parse_generation_parameters(infotext)


def main_infotext(p, first: Optional[str]) -> Optional[str]:
    """The generation's infotext, as Forge writes it for a grid; the first
    result's when Forge cannot say."""
    try:
        from modules import processing
        return processing.create_infotext(p, p.all_prompts, p.all_seeds, p.all_subseeds,
                                          use_main_prompt=True)
    except Exception:
        return first


def diffusers_converter() -> Callable:
    """
    Forge's converter from diffusers' layout to its own, which its loader
    tries when the detector does not recognise a state dict.
    """
    try:
        from modules_forge.packages.comfy.utils import convert_diffusers_mmdit
    except ImportError:
        # The original Forge keeps it with the detector. Without this every
        # checkpoint scanned there was recorded as unrecognised.
        from huggingface_guess.detection import convert_diffusers_mmdit
    return convert_diffusers_mmdit
