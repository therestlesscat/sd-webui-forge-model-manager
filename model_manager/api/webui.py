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

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from ..console import say
from .common import gate

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


def _listed_upscaler(db, file_path: str):
    """
    The name Forge lists an upscaler's gallery's file under - or, where it
    does not list that copy, another copy of it the library holds: by its
    Civitai file, then its version. Forge reads the folder it was given
    alone (--esrgan-models-path, else its own), and the same upscaler can
    be in both: the gallery's card showed the copy in the other, and Send
    said "not listed" though Forge offered it (#138).
    """
    from ..forge_host import upscaler_name
    name = upscaler_name(file_path)
    if name:
        return name
    row = db.get_version(file_path) or {}
    file_id, version_id = row.get("civitai_file_id"), row.get("id")
    copies = (db.library_files(file_ids=[file_id]) if file_id is not None else []) \
        + (db.library_files(version_ids=[version_id]) if version_id is not None else [])
    tried = {file_path}
    for copy in copies:
        if copy["file_path"] in tried:
            continue
        tried.add(copy["file_path"])
        name = upscaler_name(copy["file_path"])
        if name:
            return name
    return None


def _image_checkpoint(db, file_path: str, version_ids: str, hashes: str, model_name: str) -> dict:
    """
    The image's checkpoint for a send from a gallery that is not a
    checkpoint's: {checkpoint: Forge's name for it} or {checkpoint_problem}.
    See forge_modules_for().
    """
    from ..forge_host import checkpoint_name
    from ..model_dirs import folder_of
    from ..send_plan import image_checkpoint
    try:
        found = image_checkpoint(db, file_path, version_ids.split(","), hashes.split(","), model_name)
    except Exception as e:
        say(f"Could not work out the image's checkpoint: {e}")
        return {}
    path = found.get("path")
    if path:
        name = checkpoint_name(path)
        if name:
            return {"checkpoint": name}
        reason = "not_listed" if folder_of(path)[0] is not None else "elsewhere"
        return {"checkpoint_problem": {"reason": reason, "name": os.path.basename(path), "path": path}}
    if found.get("missing"):
        return {"checkpoint_problem": {"reason": "missing", "name": found["missing"]}}
    if found.get("not_checkpoint"):
        return {"checkpoint_problem": {"reason": "not_checkpoint"}}
    return {}


def _listed_label(path: str, installed: dict):
    """The label Forge lists a module file under, by its path; None if it does not list it."""
    wanted = os.path.normcase(os.path.abspath(path))
    return next((label for label, listed in installed.items()
                 if listed and os.path.normcase(os.path.abspath(listed)) == wanted), None)


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
                          vae: str = ""):
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

        Returns:
            preset: Forge's UI preset, or null if unknown. source: how it was
            decided (send_plan.py). manage_modules: whether modules are this
            call's business at all - SD and SDXL checkpoints bring their own,
            and keep the image's VAE as before. select: labels to select;
            missing: kinds nothing installed is; not_found: file names the
            settings give that are not installed. target: exactly what the
            VAE / Text Encoder control should hold once the image is sent -
            `select` for a model whose modules are managed, else the image's
            own VAE as Forge lists it, or nothing; vae_not_found: the image's
            VAE, when it names one this install does not have. bundled: the
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
        from ..file_identity import classify_file
        from ..forge_host import installed_modules, saved_modules
        from ..forge_modules import CLASS_FOR_PRESET, NEEDS, match_vae, pick, preferred_modules
        from ..send_plan import SendModel, plan_model

        db = get_models_db()
        try:
            found = plan_model(db, file_path, base_model,
                               version_ids.split(","), hashes.split(","), model_name)
        except Exception as e:
            say(f"Could not work out the architecture: {e}")
            found = SendModel()
        preset, model_class, source = found.preset, found.model_class, found.source
        bundled_te, bundled_vae = found.bundled_text_encoder, found.bundled_vae

        answer = {"success": True, "preset": preset, "model_class": model_class,
                  "source": source, "video": found.video,
                  "manage_modules": preset not in (None, "sd", "xl"),
                  "select": [], "missing": [], "needed": [], "not_found": [],
                  "target": [], "vae_not_found": None, "bundled": [],
                  "checkpoint": None, "checkpoint_problem": None, "own_not_listed": None,
                  "upscaler": None, "upscaler_not_listed": None}
        gallery_type = ((db.get_version(file_path) or {}).get("file_type") if file_path else None)
        if gallery_type != "Checkpoint":
            answer.update(_image_checkpoint(db, file_path, version_ids, hashes, model_name))
        if gallery_type == "Upscaler":
            answer["upscaler"] = _listed_upscaler(db, file_path)
            answer["upscaler_not_listed"] = None if answer["upscaler"] else os.path.basename(file_path)

        # The gallery's own VAE or text encoder, as Forge lists it: the
        # primary, which nothing picked for the image takes the place of.
        installed = installed_modules()
        own = None
        if gallery_type in ("VAE", "Text Encoder"):
            own = _listed_label(file_path, installed)
            answer["own_not_listed"] = None if own else os.path.basename(file_path)
        own_vae = gallery_type == "VAE"

        if not answer["manage_modules"]:
            # SD and SDXL bring their own: the image's VAE, if it names one
            named = None if own and own_vae else match_vae(vae.strip(), installed)
            answer["target"] = [label for label in (named, own) if label]
            answer["vae_not_found"] = vae.strip() if vae.strip() and not named and not (own and own_vae) else None
            return JSONResponse(answer)

        # What the checkpoint brings itself, of what its model needs: seen to
        # work with nothing selected for Krea 2 (Qwen3-VL 4B) and Flux.1
        # (CLIP-L, T5-XXL, ae) all-in-one checkpoints in Forge Neo 2.29.1.
        encoders, vae_kind = NEEDS.get(model_class or CLASS_FOR_PRESET.get(preset or "") or "", ((), None))
        answer["bundled"] = ((list(encoders) if bundled_te else [])
                             + ([vae_kind] if vae_kind and bundled_vae else []))
        modules = {label: classify_file(path) for label, path in installed.items()}
        answer.update(pick(model_class, preset, bundled_te, bundled_vae,
                           modules, saved_modules(preset), preferred_modules(preset), own, own_vae))
        answer["target"] = list(answer["select"])
        return JSONResponse(answer)

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
        from ..forge_host import restartable, samplers, schedulers, setting
        from ..model_dirs import shown_roots
        from ..generations import GENERATIONS_HIDE_NSFW, generations_enabled
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
        generations_hide_nsfw = bool(setting(GENERATIONS_HIDE_NSFW))
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
                "card_originals": card_originals,
                "generations_hide_nsfw": generations_hide_nsfw,
                "generations_enabled": generations_on,
                "queue_enabled": queue_on,
                "queue_ask_above": queue_ask_above,
                "tabs": tabs,
                "restartable": can_restart,
                # What the paths the pages show are read from (shownPath, ui_options.mjs).
                "path_roots": shown_roots(),
            })

        except Exception as e:
            import traceback
            say(f"UI options error: {e}")
            traceback.print_exc()
            # The key question is answerable even when the rest is not, and
            # the banner should not depend on samplers being readable.
            return JSONResponse(
                {"success": False, "error": str(e), "has_api_key": has_api_key,
                 "nsfw_detection": nsfw_detection,
                 "gallery_hide_nsfw": gallery_hide_nsfw,
                 "hide_promptless_images": hide_promptless_images,
                 "gallery_originals": gallery_originals, "card_originals": card_originals,
                 "generations_hide_nsfw": generations_hide_nsfw,
                 "generations_enabled": generations_on,
                 "queue_enabled": queue_on,
                 "tabs": tabs, "restartable": can_restart},
                status_code=500
            )

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
