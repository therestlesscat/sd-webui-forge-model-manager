"""
What Forge itself knows.

Samplers and schedulers come from the running WebUI rather than from us or
from Civitai, and the browser needs them to match an image's generation
parameters to something it can actually select. Whether a Civitai API key has
been set is the same kind of question - it is a WebUI setting - and it rides
along here rather than costing a second request at startup.
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse


def register(app: FastAPI):
    """Attach this module's endpoints to the app."""
    @app.get("/model-manager/forge-modules")
    def forge_modules_for(file_path: str = "", base_model: str = "",
                          version_ids: str = "", hashes: str = "", model_name: str = ""):
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

        Returns:
            preset: Forge's UI preset, or null if unknown. source: how it was
            decided (send_plan.py). manage_modules: whether modules are this
            call's business at all - SD and SDXL checkpoints bring their own,
            and keep the image's VAE as before. select: labels to select;
            missing: kinds nothing installed is; not_found: file names the
            settings give that are not installed.
        """
        from ..db import get_models_db
        from ..forge_modules import (classify_file, installed_modules, pick,
                                     preferred_modules, saved_modules)
        from ..send_plan import SendModel, plan_model

        try:
            found = plan_model(get_models_db(), file_path, base_model,
                               version_ids.split(","), hashes.split(","), model_name)
        except Exception as e:
            print(f"[ModelManager] Could not work out the architecture: {e}")
            found = SendModel()
        preset, model_class, source = found.preset, found.model_class, found.source
        bundled_te, bundled_vae = found.bundled_text_encoder, found.bundled_vae

        answer = {"success": True, "preset": preset, "model_class": model_class,
                  "source": source, "manage_modules": preset not in (None, "sd", "xl"),
                  "select": [], "missing": [], "needed": [], "not_found": []}
        if not answer["manage_modules"]:
            return JSONResponse(answer)

        modules = {label: classify_file(path) for label, path in installed_modules().items()}
        answer.update(pick(model_class, preset, bundled_te, bundled_vae,
                           modules, saved_modules(preset), preferred_modules(preset)))
        return JSONResponse(answer)

    @app.get("/model-manager/ui-options")
    async def get_ui_options():
        """Get samplers, schedulers, and whether Civitai can be asked properly."""
        has_api_key = False
        # The gallery asks for this before it renders, so it has to survive
        # the samplers being unreadable - hence its own try, like the key.
        image_browsing = "continuous"
        try:
            from modules import shared
            has_api_key = bool(
                (getattr(shared.opts, 'model_manager_civitai_api_key', '') or '').strip()
            )
            image_browsing = getattr(
                shared.opts, 'model_manager_image_browsing', 'continuous')
        except Exception:
            pass

        try:
            from modules import sd_samplers, sd_schedulers

            # Get sampler names
            samplers = [s.name for s in sd_samplers.all_samplers]

            # Get scheduler labels
            schedulers = [s.label for s in sd_schedulers.schedulers]

            return JSONResponse({
                "success": True,
                "samplers": samplers,
                "schedulers": schedulers,
                "has_api_key": has_api_key,
                "image_browsing": image_browsing,
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] UI options error: {e}")
            traceback.print_exc()
            # The key question is answerable even when the rest is not, and
            # the banner should not depend on samplers being readable.
            return JSONResponse(
                {"success": False, "error": str(e), "has_api_key": has_api_key,
                 "image_browsing": image_browsing},
                status_code=500
            )
