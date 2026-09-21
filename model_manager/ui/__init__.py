"""
Everything Gradio renders.

  settings.py             the options page
  tab_model_manager.py    the Model Manager tab's markup
  tab_civitai_browser.py  the Civitai Browser tab's markup

The markup is static; the tabs are filled in by the scripts under javascript/.
"""
from .settings import on_ui_settings
from .tab_civitai_browser import create_civitai_browser_ui
from .tab_model_manager import create_ui

__all__ = ["on_ui_settings", "create_civitai_browser_ui", "create_ui"]
