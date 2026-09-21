"""
Where Forge picks the extension up.

Forge loads every scripts/*.py, so this file exists to register the callbacks
and nothing else. The markup lives in model_manager/ui/, the endpoints in
model_manager/api/.

The module cache is cleared first because Forge can rebuild the UI without
restarting the process, and a stale module would keep serving the old code.
"""
import sys

from modules import script_callbacks

from model_manager.ui import (
    create_civitai_browser_ui,
    create_ui,
    on_ui_settings,
)


def create_all_tabs():
    """Create all Model Manager tabs."""
    tabs = create_ui()
    civitai_tab = create_civitai_browser_ui()
    tabs.append((civitai_tab, "Civitai Browser", "civitai_browser_tab"))
    return tabs


script_callbacks.on_ui_settings(on_ui_settings)
script_callbacks.on_ui_tabs(create_all_tabs)

# Importing the api package registers its own on_app_started callback.
print("[ModelManager] Importing API module...")
try:
    import importlib
    # Forge can rebuild the UI without restarting, so drop anything cached.
    for name in [k for k in sys.modules if k.startswith('model_manager')]:
        del sys.modules[name]
    from model_manager import api
    print(f"[ModelManager] API module imported from: {api.__file__}")
except Exception as e:
    print(f"[ModelManager] ERROR importing API module: {e}")
    import traceback
    traceback.print_exc()

print("[ModelManager] Extension loaded")
