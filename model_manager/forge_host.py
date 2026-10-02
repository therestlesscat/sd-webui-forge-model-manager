"""
What the extension asks of the WebUI it runs in.

The extension's settings live in Forge's options (shared.opts), registered
by ui/settings.py under Settings -> Model Manager. Each was read where it
was used, with its own default written beside the read and its own guard
for a WebUI that was not there - thirty-odd copies, which agreed only
because nobody had changed one yet. DEFAULTS is the one list of them;
registration takes its defaults from it, and setting() is how they are read.

Forge is imported only when something is asked, so the rest of the
extension, and its tests, work where it is not installed: a setting then
reads as its default.
"""
from typing import Any

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
