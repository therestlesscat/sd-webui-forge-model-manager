"""
What Forge itself knows.

Samplers and schedulers come from the running WebUI rather than from us or
from Civitai, and the browser needs them to match an image's generation
parameters to something it can actually select. Whether a Civitai API key has
been set is the same kind of question - it is a WebUI setting - and it rides
along here rather than costing a second request at startup.

And what version of the page's own shared scripts the WebUI is serving,
which it does not say itself.
"""
import os
from typing import List, Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from ..console import say, say_failure
from .common import gate, refused

# Why Restart WebUI is not offered (#186).
NOT_RESTARTABLE = ("This WebUI was not started by webui.bat or webui.sh: "
                   "a restart would leave it shut down")

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "javascript")
SHARED_SCRIPTS = os.path.join(_SCRIPTS, "shared")
TAB_SCRIPTS = os.path.join(_SCRIPTS, "tabs")


def shared_version() -> str:
    """
    The newest modification time among javascript/shared/ and
    javascript/tabs/, as the version the loader asks for both with.

    The WebUI stamps only the scripts it lists, javascript/*.mjs - the loader
    alone, since the tabs' scripts moved to javascript/tabs/ (#183) - each with
    its own mtime; the tabs used theirs for the shared modules too. A release
    that changed only a shared file left every URL as it was, and Gradio's
    file route sends no Cache-Control, so a browser could keep the copy it
    held. One version for all also loads each module once.
    """
    newest = 0.0
    for folder in (SHARED_SCRIPTS, TAB_SCRIPTS):
        for root, _, files in os.walk(folder):
            for name in files:
                if name.endswith((".mjs", ".js")):
                    newest = max(newest, os.path.getmtime(os.path.join(root, name)))
    return str(int(newest))


def register(app: FastAPI):
    """Attach this module's endpoints to the app."""
    @app.get("/model-manager/asset-version")
    @gate("always")
    def asset_version():
        """
        The version the loader imports javascript/shared/ and the tabs with;
        never cached. Asked before anything, so with every tab off too.
        """
        return JSONResponse({"success": True, "version": shared_version()},
                            headers={"Cache-Control": "no-store"})

    @app.get("/model-manager/forge-modules")
    @gate("send")
    def forge_modules_for(file_path: str = "", base_model: str = "",
                          version_ids: str = "", hashes: str = "", model_name: str = "",
                          vae: str = "", module: List[str] = Query(default=[]), use_version: int = 0):
        """
        What Send to txt2img should set up in Forge before sending an image.

        The UI preset for the model the image will generate with, and the
        text encoders and VAE it needs that its file does not bring, picked
        from what Forge offers. Which model that is: see send_plan.py. A plain
        `def`: it reads file headers, and may ask Civitai once.

        Args:
            file_path: The gallery's file - the version shown.
            base_model: The gallery version's baseModel on Civitai.
            version_ids: Comma-separated Civitai version ids the image names
                as checkpoints.
            hashes: Comma-separated hashes the image names its checkpoint by.
            model_name: The checkpoint's name in the image's generation data.
            vae: The VAE the image's generation data names, if any.
            module: Every module it names - its VAE, then each `Module N`
                Forge wrote (#204) - once per name.
            use_version: Send with the library's file of this version, not
                the checkpoint the image names - another file of its version,
                or another version of its model, picked in the Resources
                dialog (#278). The answer's `instead` names the file.

        Returns:
            preset: Forge's UI preset, or null if unknown. source: how it was
            decided (send_plan.py). embeddings: the kind of embedding the
            model loads (forge_host.embedding_kind), for the chips to say
            which Forge skips (#179). manage_modules: whether modules are this
            call's business at all - SD and SDXL checkpoints bring their own,
            and keep the image's VAE as before. select: labels to select;
            missing: kinds nothing installed is; not_found: file names the
            settings give that are not installed. target: exactly what the
            VAE / Text Encoder control should hold once the image is sent -
            `select` for a model whose modules are managed, else the image's
            modules as Forge lists them, or nothing - of a managed model, the
            image's own file of each kind before the plan's pick;
            modules_not_found: the names the image gives that this install
            does not have. bundled: the
            kinds the model needs that the checkpoint carries itself, and so
            are not selected - for the page to say so, as an empty control
            otherwise reads as a send that failed.

            From a gallery that is not a checkpoint's (#134): checkpoint, the
            name Forge lists the image's checkpoint under, to select; or
            checkpoint_problem, why it cannot be - {reason: missing, name},
            {reason: elsewhere | not_listed, name, path} for one the library
            has in a folder this WebUI does not load, or that Forge has not
            listed yet, {reason: not_checkpoint} - and the page sends nothing.
            From a VAE's or a text encoder's, that file is in `target` in its
            kind's place; own_not_listed, its name when Forge does not list it.
            From an upscaler's, upscaler: the name Forge lists it under, for
            Hires fix's; upscaler_not_listed, its file's when Forge does not.
        """
        from ..db import get_models_db
        from ..send import civitai_plan
        return JSONResponse(civitai_plan(get_models_db(), file_path, base_model, version_ids, hashes, model_name,
                                         vae, module, use_version))

    @app.get("/model-manager/send/plan")
    @gate("send")
    def send_plan(kind: str, image: int = 0, file_path: str = "", base_model: str = "", version_ids: str = "",
                  hashes: str = "", model_name: str = "", generation: int = 0, task: int = 0,
                  use_version: int = 0, text: int = 0, upscaler: str = "", denoise: Optional[float] = None,
                  video: str = "", frames: int = 0, prompt: Optional[str] = None,
                  negative_prompt: Optional[str] = None):
        """
        How to set Forge up before a Send, for any source (#302): see
        send.plan(). `kind` is civitai - the image's id, the gallery's
        `file_path` and `base_model`, the checkpoint the page read of the
        image - generation, or task. A generation's answers while the
        Generations tab is on, a task's while the Queue is, as their own
        routes did. A plain `def`: it reads file headers, and may ask Civitai
        once.

        With `text`, a Civitai image's settings instead - the infotext, its
        scheduler, whether it had Hires fix (send.civitai_settings) - for
        Forge's own paste button where the tab's loader was not built: the
        source as the page hands the loader, `upscaler` to `negative_prompt`.
        """
        from ..db import get_models_db
        from ..send import civitai_settings, plan
        from ..tabs import on
        if text and kind == "civitai":
            found = civitai_settings(get_models_db(), {
                "image": image, "upscaler": upscaler or None, "denoise": denoise, "video": video == "true",
                "frames": frames or None, "prompt": prompt, "negative_prompt": negative_prompt})
            if found is None:
                return JSONResponse({"success": False, "error": "The image is not in the library"}, status_code=404)
            return JSONResponse({"success": True, **found})
        area = {"generation": "generations", "task": "queue"}.get(kind)
        if area and not on(area):
            return refused(area)
        try:
            found = plan(get_models_db(), {"kind": kind, "image": image, "file_path": file_path,
                                           "base_model": base_model, "version_ids": version_ids,
                                           "hashes": hashes, "model_name": model_name,
                                           "generation": generation, "task": task, "use_version": use_version})
        except ValueError as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=400)
        if found is None:
            return JSONResponse({"success": False, "error": f"No such {kind}"}, status_code=404)
        return JSONResponse({"success": True, **found})

    @app.get("/model-manager/forge-modules/current")
    @gate("send")
    def forge_modules_current():
        """
        The modules Forge holds now - what it will load - for Send to check
        its change took: the control can show one thing while Forge's setting
        holds another. modules is null where Forge is not there to ask.
        """
        from ..forge_host import current_modules
        return JSONResponse({"success": True, "modules": current_modules()})

    @app.get("/model-manager/ui-options")
    @gate("always")
    def get_ui_options():
        """Get samplers, schedulers, and whether Civitai can be asked properly."""
        from ..civitai import api_key_from_settings
        from ..forge_host import DEFAULTS, restartable, samplers, schedulers, setting, short_name
        from ..model_dirs import shown_roots
        from ..db import database_state, migration_state
        from ..generations import GENERATIONS_DELETE_FILES, GENERATIONS_HIDE_NSFW, generations_enabled
        from ..grids import GALLERY_GRID, GENERATIONS_GRID, grid
        from ..scheduler import queue_enabled
        from ..tabs import TABS, built, on
        has_api_key = api_key_from_settings() is not None
        # How the Civitai Browser's gallery opens, asked each time a model is;
        # the Model Manager's asks the details endpoint, which reads the same
        # settings.
        gallery_hide_nsfw = bool(setting('model_manager_gallery_hide_nsfw'))
        hide_promptless_images = bool(setting('model_manager_hide_promptless_images'))
        # Images as uploaded, not resized (#192): galleries, and the grids' cards.
        gallery_originals = bool(setting('model_manager_gallery_originals'))
        card_originals = bool(setting('model_manager_card_originals'))
        # Whether a model card's video plays by itself (#220).
        card_videos_play = bool(setting('model_manager_card_videos_play'))
        # Whether the Civitai Browser marks on-site-only versions (#229).
        civitai_on_site_marks = bool(setting('model_manager_civitai_on_site_marks'))
        # How many of Civitai's images a page loads at once (#213): a whole
        # number of at least 1, else the default.
        try:
            images_at_once = int(setting('model_manager_civitai_images_at_once'))
        except (TypeError, ValueError):
            images_at_once = 0
        if images_at_once < 1:
            images_at_once = DEFAULTS['model_manager_civitai_images_at_once']
        generations_hide_nsfw = bool(setting(GENERATIONS_HIDE_NSFW))
        # How each tab places its grid (#240): Fast or Classic.
        generations_grid = grid(GENERATIONS_GRID)
        gallery_grid = grid(GALLERY_GRID)
        # Whether the delete question's files box starts ticked (#107).
        generations_delete_files = bool(setting(GENERATIONS_DELETE_FILES))
        # "Your generations": off, nothing is recorded and every tab of them is
        # hidden (generations_enabled in generations.py).
        generations_on = generations_enabled()
        # The queue: off, its tab and the Queue buttons are hidden (scheduler/__init__.py).
        queue_on = queue_enabled()
        # Each tab: whether it is on, and whether this start created it -
        # one switched on since needs a restart (tabs.py).
        made = built()
        tabs = {tab: {"on": on(tab), "built": tab in made} for tab in TABS}
        # Whether Restart WebUI is offered after a tab switch: the WebUI comes back (#186).
        can_restart = restartable()
        # Above how many images Generate asks whether to queue them (#166); 0 never.
        try:
            queue_ask_above = max(0, int(setting('model_manager_queue_ask_above') or 0))
        except (TypeError, ValueError):
            queue_ask_above = 0
        # Which judges prompts, as in force: "model" only when the trained
        # model is chosen and on. The pages say so when it is.
        try:
            from ..nsfw import prompt_model_threshold
            nsfw_detection = "model" if prompt_model_threshold() is not None else "words"
        except Exception:
            nsfw_detection = "words"

        try:
            return JSONResponse({
                "success": True,
                "samplers": samplers(),
                "schedulers": schedulers(),
                "has_api_key": has_api_key,
                "nsfw_detection": nsfw_detection,
                "gallery_hide_nsfw": gallery_hide_nsfw,
                "hide_promptless_images": hide_promptless_images,
                "gallery_originals": gallery_originals,
                "card_originals": card_originals, "card_videos_play": card_videos_play,
                "civitai_on_site_marks": civitai_on_site_marks,
                "images_at_once": images_at_once,
                "generations_hide_nsfw": generations_hide_nsfw,
                "generations_delete_files": generations_delete_files,
                "generations_grid": generations_grid,
                "gallery_grid": gallery_grid,
                "generations_enabled": generations_on,
                "queue_enabled": queue_on,
                "queue_ask_above": queue_ask_above,
                "tabs": tabs,
                "restartable": can_restart,
                # What the paths the pages show are read from (shownPath, ui_options.mjs).
                "path_roots": shown_roots(),
                # Who ignores a file in a folder an option replaced: "Ignored by Neo" (#195).
                "webui_short_name": short_name(),
                # A database newer than this copy knows: the tabs are covered, none starts (#136).
                "database_newer": database_state(),
                # A migration running or failed at this start: the tabs wait under a notice (#285).
                "database_migrating": migration_state(),
            })

        except Exception as e:
            say_failure(f"UI options error: {e}")
            # The key question is answerable even when the rest is not, and
            # the banner should not depend on samplers being readable.
            return JSONResponse(
                {"success": False, "error": str(e), "has_api_key": has_api_key,
                 "nsfw_detection": nsfw_detection,
                 "gallery_hide_nsfw": gallery_hide_nsfw,
                 "hide_promptless_images": hide_promptless_images,
                 "gallery_originals": gallery_originals, "card_originals": card_originals,
                 "card_videos_play": card_videos_play,
                 "civitai_on_site_marks": civitai_on_site_marks,
                 "images_at_once": images_at_once,
                 "generations_hide_nsfw": generations_hide_nsfw,
                 "generations_delete_files": generations_delete_files,
                 "generations_grid": generations_grid, "gallery_grid": gallery_grid,
                 "generations_enabled": generations_on,
                 "queue_enabled": queue_on,
                 "tabs": tabs, "restartable": can_restart},
                status_code=500
            )

    @app.get("/model-manager/database/migration")
    @gate("always")
    def database_migration():
        """
        The migration the page's notice waits on (#285): running, with how far
        it has got, or failed with its error; None once it is done. Read
        without the database, which waits for it.
        """
        from ..db import migration_state
        return JSONResponse({"success": True, "migrating": migration_state()})

    @app.post("/model-manager/restart")
    @gate("always")
    def restart():
        """
        Restart the WebUI: a tab switch's cleanest slate, the server and the
        page afresh (#186). Once the answer is sent, so the page hears it and
        waits for the new process. Refused where the WebUI would not come back.
        """
        from ..forge_host import restart_webui, restartable
        if not restartable():
            return JSONResponse({"success": False, "error": NOT_RESTARTABLE}, status_code=409)
        say("Restarting the WebUI, as asked after a tab switch")
        return JSONResponse({"success": True}, background=BackgroundTask(restart_webui))
