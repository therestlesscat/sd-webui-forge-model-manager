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
