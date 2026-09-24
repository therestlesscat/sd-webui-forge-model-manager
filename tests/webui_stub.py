"""
Enough of the WebUI for the extension to import.

`model_manager.api` registers a callback with `modules.script_callbacks` at
import time, and most of the extension reads settings off `modules.shared.opts`
- neither of which exists outside Forge. Installing these before the first
import lets the endpoints be exercised without launching anything.

Call `install()` first thing, before importing anything from `model_manager`.
"""
import sys
import types


DEFAULTS = {
    "model_manager_civitai_api_key": "",
    "model_manager_civitai_requests_per_second": 6,
    "model_manager_page_size": 20,
    "model_manager_civitai_page_size": 20,
    "model_manager_card_size": "200x280",
    "model_manager_civitai_card_size": "200x280",
    "model_manager_preview_least_nsfw": True,
    "model_manager_civitai_folder_template": "",
    "model_manager_civitai_min_prompt_images": 1,
    "model_manager_civitai_sfw_fill_page": False,
    "model_manager_hash_threads": 4,
    "model_manager_database_path": "",
}


class Options(object):
    """shared.opts: attribute access, and a getattr default that works."""

    def __init__(self, values):
        self.__dict__.update(values)

    def __contains__(self, key):
        return key in self.__dict__


def install(**overrides):
    """
    Put a fake `modules` package on sys.modules and return its options.

    Args:
        **overrides: settings to differ from DEFAULTS - an API key, say, or a
            model directory.

    Returns:
        The Options object, so a test can change a setting mid-run.
    """
    values = dict(DEFAULTS)
    values.update(overrides)
    opts = Options(values)

    modules = types.ModuleType("modules")
    shared = types.ModuleType("modules.shared")
    callbacks = types.ModuleType("modules.script_callbacks")
    paths = types.ModuleType("modules.paths")

    shared.opts = opts
    shared.cmd_opts = Options({"ckpt_dir": None, "lora_dir": None, "vae_dir": None})

    # Registered at import; nothing here needs to fire them.
    for name in ("on_app_started", "on_ui_settings", "on_ui_tabs", "on_ui_train_tabs"):
        setattr(callbacks, name, lambda *a, **k: None)

    # /model-manager/ui-options reads these straight off the WebUI.
    samplers = types.ModuleType("modules.sd_samplers")
    schedulers = types.ModuleType("modules.sd_schedulers")

    class _Named(object):
        def __init__(self, name):
            self.name = name
            self.label = name

    samplers.all_samplers = [_Named(n) for n in ("Euler a", "Euler", "DPM++ 2M")]
    schedulers.schedulers = [_Named(n) for n in ("Automatic", "Karras", "Simple")]
    modules.sd_samplers = samplers
    modules.sd_schedulers = schedulers
    sys.modules.update({"modules.sd_samplers": samplers,
                        "modules.sd_schedulers": schedulers})

    paths.models_path = values.get("models_path", "")
    paths.data_path = values.get("data_path", "")

    modules.shared = shared
    modules.script_callbacks = callbacks
    modules.paths = paths

    sys.modules.update({
        "modules": modules,
        "modules.shared": shared,
        "modules.script_callbacks": callbacks,
        "modules.paths": paths,
    })
    return opts


def uninstall():
    """Take it back off, so a suite that wants the real absence can have it."""
    for name in ("modules.sd_schedulers", "modules.sd_samplers", "modules.paths",
                 "modules.script_callbacks", "modules.shared", "modules"):
        sys.modules.pop(name, None)
