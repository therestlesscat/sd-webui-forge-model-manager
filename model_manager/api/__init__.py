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
  scheduler.py    the generation queue: running it, its tasks, and acting on them
  annotations.py  marking a Civitai result with what we know locally
  prompts.py      deciding whether a model has usable prompts

Each module exposes register(app) and owns whatever state its endpoints need,
so adding an endpoint means editing one file rather than scrolling one.

on_app_started is registered by scripts/model_manager_ui.py, each time Forge
runs it - not here, at import, which happens once a process.
"""
import threading

from fastapi import FastAPI

from . import civitai, common, gallery, generations, images, jobs, models, notes, scheduler, settings, webui
from .. import prompt_levels, repairs, update_check
from ..scheduler import runner
from ..db import database_behind, database_state, get_models_db
from ..console import say, say_failure


def setup_api(app: FastAPI):
    """Attach every endpoint to the running app."""
    models.register(app)
    images.register(app)
    generations.register(app)
    gallery.register(app)
    jobs.register(app)
    civitai.register(app)
    webui.register(app)
    settings.register(app)
    notes.register(app)
    scheduler.register(app)
    repairs.register(app, common)
    say("API endpoints registered")


def on_app_started(demo, app):
    setup_api(app)
    # A database newer than this copy knows is not touched (#136): the page
    # says so, from ui-options. Whether a newer copy is out is still asked.
    newer = database_state()
    if newer:
        say(f"The database {newer['path']} is at schema v{newer['schema']}, newer than this copy of the "
            f"extension knows (v{newer['known']}): update this copy. Nothing reads or writes it until then.")
        update_check.start_in_background()
        return
    # Whether a newer version is out: now, then every 12 hours.
    update_check.start_in_background()
    if database_behind():
        # Migrated now, whatever tabs are on, in a thread of its own: the page
        # is served meanwhile, with a notice over every tab until it ends
        # (#285). With only the Civitai Browser on, nothing else would open
        # the database, and the notice would stay. What reads it waits.
        threading.Thread(target=_migrate_then_start, name="ModelManager-migrate", daemon=True).start()
        return
    _start_services()


def _migrate_then_start():
    try:
        get_models_db()
    except Exception:
        say_failure("The database's migration failed; it is as it was, its backup beside it")
        return
    _start_services()


def _start_services():
    # Each of these is left out while the tabs it serves are off (tabs.py).
    # Stored image levels, redone if the NSFW prompt words changed.
    prompt_levels.start_in_background()
    # Queued tasks a restart or a crash left running are stopped (#155).
    runner.recover()
