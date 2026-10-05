"""
Where Forge picks the extension up.

Forge loads every scripts/*.py, so this file exists to register the callbacks
and nothing else. The markup lives in model_manager/ui/, the endpoints in
model_manager/api/.

Every callback is registered here, each time Forge runs this file: Settings ->
Reload UI clears them all and runs the scripts again, in the same process,
with the extension already imported. It used to delete the extension's modules
and import the API afresh, to pick up edited code - after the recording script
and the settings had imported theirs, so two copies ran side by side. A
change to the code needs a restart, as the scripts and the stylesheet do.
"""
from modules import script_callbacks

from model_manager import api
from model_manager.generations import generations_enabled
from model_manager.ui import (
    create_civitai_browser_ui,
    create_generations_ui,
    create_ui,
    on_ui_settings,
)
from model_manager.version import describe
from model_manager.console import say


def create_all_tabs():
    """
    Create all Model Manager tabs: Generations first, before the Model
    Manager - unless "Your generations" is off, when it is not created at all.
    """
    tabs = [(create_generations_ui(), "Generations", "generations_tab")] if generations_enabled() else []
    tabs += create_ui()
    civitai_tab = create_civitai_browser_ui()
    tabs.append((civitai_tab, "Civitai Browser", "civitai_browser_tab"))
    return tabs


script_callbacks.on_ui_settings(on_ui_settings)
script_callbacks.on_ui_tabs(create_all_tabs)
script_callbacks.on_app_started(api.on_app_started)

say(f"Version {describe()['version']} loaded")
