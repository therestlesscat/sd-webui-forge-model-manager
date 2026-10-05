"""
The HTTP surface the two tabs talk to.

Everything the browser can ask for, grouped by what it is asking about:

  models.py       which models do I have, and what is this one
  images.py       a version's gallery
  generations.py  a model's gallery of your own generations
  jobs.py         scanning and syncing, and how far along they are
  civitai.py      searching and downloading from Civitai
  webui.py        what Forge itself knows, such as samplers
  settings.py     the settings window: the settings, and saving them
  notes.py        notes to the user per release, and dismissing them; a newer version
  annotations.py  marking a Civitai result with what we know locally
  prompts.py      deciding whether a model has usable prompts

Each module exposes register(app) and owns whatever state its endpoints need,
so adding an endpoint means editing one file rather than scrolling one.

on_app_started is registered by scripts/model_manager_ui.py, each time Forge
runs it - not here, at import, which happens once a process.
"""
from fastapi import FastAPI

from . import civitai, generations, images, jobs, models, notes, settings, webui
from .. import prompt_levels, update_check
from ..console import say


def setup_api(app: FastAPI):
    """Attach every endpoint to the running app."""
    models.register(app)
    images.register(app)
    generations.register(app)
    jobs.register(app)
    civitai.register(app)
    webui.register(app)
    settings.register(app)
    notes.register(app)
    say("API endpoints registered")


def on_app_started(demo, app):
    setup_api(app)
    # Stored image levels, redone if the NSFW prompt words changed.
    prompt_levels.start_in_background()
    # Whether a newer version is out: now, then every 12 hours.
    update_check.start_in_background()
