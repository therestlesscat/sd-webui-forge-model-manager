"""
The HTTP surface the two tabs talk to.

Everything the browser can ask for, grouped by what it is asking about:

  models.py       which models do I have, and what is this one
  images.py       a version's gallery
  jobs.py         scanning and syncing, and how far along they are
  civitai.py      searching and downloading from Civitai
  webui.py        what Forge itself knows, such as samplers
  annotations.py  marking a Civitai result with what we know locally
  prompts.py      deciding whether a model has usable prompts

Each module exposes register(app) and owns whatever state its endpoints need,
so adding an endpoint means editing one file rather than scrolling one.
"""
from fastapi import FastAPI
from modules import script_callbacks

from . import civitai, images, jobs, models, webui

print("[ModelManager API] === api package loading ===")


def setup_api(app: FastAPI):
    """Attach every endpoint to the running app."""
    models.register(app)
    images.register(app)
    jobs.register(app)
    civitai.register(app)
    webui.register(app)
    print("[ModelManager] API endpoints registered")


def on_app_started(demo, app):
    print(f"[ModelManager] on_app_started called with app: {app}")
    setup_api(app)


print("[ModelManager] Registering on_app_started callback...")
script_callbacks.on_app_started(on_app_started)
print("[ModelManager] on_app_started callback registered")
