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
    def forge_modules_for(file_path: str = "", base_model: str = ""):
        """
        What Send to txt2img should set up in Forge before sending an image.

        The UI preset for the model's architecture, and the text encoders and
        VAE it needs that its file does not bring, picked from what Forge
        offers. A plain `def`: it reads file headers.

        Args:
            file_path: The checkpoint the image is sent with - a checkpoint's
                own gallery. Its header is read if it has not been.
            base_model: Civitai's baseModel, for a gallery that is not a
                checkpoint's, or a file Forge does not recognise.

        Returns:
            preset: Forge's UI preset, or null if unknown. manage_modules:
            whether modules are this call's business at all - SD and SDXL
            checkpoints bring their own, and keep the image's VAE as before.
            select: labels to select; missing: kinds nothing installed is.
        """
        from ..architecture import preset_for_base_model, record_architecture
        from ..db import get_models_db
        from ..forge_modules import (classify_file, installed_modules, pick,
                                     saved_modules)

        preset = model_class = None
        bundled_te = bundled_vae = False
        source = None
        try:
            if file_path:
                db = get_models_db()
                record_architecture(db, file_path)
                row = db.get_version(file_path) or {}
                if row.get("architecture"):
                    preset, model_class = row["architecture"], row.get("architecture_class")
                    bundled_te, bundled_vae = row["bundled_text_encoder"], row["bundled_vae"]
                    source = "file"
                base_model = base_model or row.get("base_model") or ""
            if not preset:
                preset = preset_for_base_model(base_model)
                source = "civitai" if preset else None
        except Exception as e:
            print(f"[ModelManager] Could not work out the architecture: {e}")

        answer = {"success": True, "preset": preset, "model_class": model_class,
                  "source": source, "manage_modules": preset not in (None, "sd", "xl"),
                  "select": [], "missing": [], "needed": []}
        if not answer["manage_modules"]:
            return JSONResponse(answer)

        modules = {label: classify_file(path) for label, path in installed_modules().items()}
        answer.update(pick(model_class, preset, bundled_te, bundled_vae,
                           modules, saved_modules(preset)))
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
