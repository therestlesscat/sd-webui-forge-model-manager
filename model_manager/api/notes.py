"""
Notes to the user, per release (model_manager/release_notes.py): the ones a tab shows, all
of them for the settings window's "What's new", and dismissing one. And whether a newer
version is out (model_manager/update_check.py), for the tabs' headers.
"""
from typing import Optional

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

from ..db import get_models_db
from ..release_notes import dismiss, notes_for
from ..update_check import status as update_status


def register(app: FastAPI):
    @app.get("/model-manager/notes")
    def get_notes(tab: Optional[str] = None):
        """
        With `tab` ("model_manager", "civitai_browser", "generations"): the
        notes that tab shows - that apply to this install and are not
        dismissed. Without: every note that applies, dismissed or not, each
        with `dismissed`, for "What's new".
        """
        try:
            return JSONResponse({"success": True, "notes": notes_for(get_models_db(), tab)})
        except Exception as e:
            print(f"[ModelManager] Notes error: {e}")
            return JSONResponse({"success": False, "error": str(e), "notes": []}, status_code=500)

    @app.post("/model-manager/notes/dismiss")
    def dismiss_note(id: str = Form(...)):
        """Dismiss a note: gone from the tabs, for every browser using this database."""
        try:
            dismiss(get_models_db(), id)
            return JSONResponse({"success": True})
        except Exception as e:
            print(f"[ModelManager] Could not dismiss note {id}: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/update")
    def get_update():
        """The version out, as last read from GitHub, and whether it is newer than this one."""
        return JSONResponse({"success": True, **update_status()})
