"""
Everything Gradio renders.

  settings.py             the options page
  tab_model_manager.py    the Model Manager tab's markup
  tab_civitai_browser.py  the Civitai Browser tab's markup
  tab_generations.py      the Generations tab's markup
  tab_queue.py            the Queue tab's markup, and the Queue buttons' wiring

The markup is static; the tabs are filled in by the scripts under javascript/tabs/, which the
loader (javascript/loader.mjs) loads for the tabs that are on.
"""
from .settings import on_ui_settings
from .tab_civitai_browser import create_civitai_browser_ui
from .tab_generations import create_generations_ui
from .tab_model_manager import create_ui
from .tab_queue import create_queue_ui

__all__ = ["on_ui_settings", "create_civitai_browser_ui", "create_generations_ui", "create_queue_ui",
           "create_ui"]
