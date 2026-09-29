"""
A model's gallery of your own generations: the second tab beside its Civitai
images.

A gallery shows the generations that used any file of the open model's
version - as the Civitai tab shows one gallery per version - one card per
generation, a page of cards at a time, through the same two switches. What is
recorded, and how, is model_manager/generations.py's.

An image file is served by its record's id, never by a path the page sends:
only what was recorded can be opened.
"""
import os
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Form
from fastapi.responses import FileResponse, JSONResponse

from ..civitai.prompt_filter import MIN_PROMPT_LENGTH
from ..db import get_models_db
from ..nsfw import PG, SFW_MAX
from .images import GALLERY_PAGE_SIZE, gallery_switches, page_bounds

# The images a card shows before "Show images".
PREVIEW_IMAGES = 4


def _filtered(rows: List[Dict[str, Any]], hide_nsfw: bool,
              hide_promptless: bool) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    The images the switches let through, and the counts the banner states -
    meaning what ImagesOps.get_image_counts() means by each, so the banner
    reads the same in both tabs.
    """
    safe = [r["level"] is not None and r["level"] <= SFW_MAX for r in rows]
    readable = [r["prompt_length"] >= MIN_PROMPT_LENGTH for r in rows]
    nsfw_kept = [i for i in range(len(rows)) if safe[i] or not hide_nsfw]
    shown = [i for i in nsfw_kept if readable[i] or not hide_promptless]
    return [rows[i] for i in shown], {
        "total": len(rows),
        "filtered": len(shown),
        "hidden_nsfw": len(rows) - len(nsfw_kept),
        "hidden_promptless": len(nsfw_kept) - len(shown),
        "hidden": len(rows) - len(shown),
        "nsfw_count": sum(1 for i in range(len(rows))
                          if not safe[i] and (readable[i] or not hide_promptless)),
        "promptless_count": sum(1 for i in nsfw_kept if not readable[i]),
    }


def _image(row: Dict[str, Any]) -> Dict[str, Any]:
    """An image as the page draws one: its generation data as a Civitai
    image's meta, its level stamped as every image the page gets is."""
    level = row.get("user_nsfw_level")
    from_prompt = level is None
    if level is None:
        level = row.get("prompt_nsfw_level")
    return {
        "id": row["id"],
        "generation_id": row["generation_id"],
        "position": row["position"],
        "iteration": row.get("iteration"),
        "seed": row.get("seed"),
        "width": row.get("width"),
        "height": row.get("height"),
        "meta": row.get("meta") or {},
        "infotext": row.get("infotext"),
        "url": f"/model-manager/generations/images/{row['id']}/file",
        "exists": bool(row.get("path")) and os.path.isfile(row["path"]),
        "mm_level": level,
        # What set the level, for the badge's "X · prompt": nobody rates
        # these images, so it is the prompt unless the user has.
        "mm_level_from_prompt": from_prompt and level != PG,
    }


def generation_page(db, path: str, hide_nsfw: bool, hide_promptless: bool,
                    offset: int = 0, limit: int = GALLERY_PAGE_SIZE) -> Dict[str, Any]:
    """
    One page of a gallery's generation cards, newest first, and the state the
    gallery draws around them.
    """
    offset, limit = page_bounds(offset, limit)
    files = db.generation_gallery_files(path)
    shown, counts = _filtered(db.generation_gallery_images(files), hide_nsfw, hide_promptless)

    by_generation: Dict[int, List[Dict[str, Any]]] = {}
    for row in shown:
        by_generation.setdefault(row["generation_id"], []).append(row)
    order = list(by_generation)
    page = order[offset:offset + limit]

    generations = db.get_generations(page)
    previews = [r["id"] for g in page for r in by_generation[g][:PREVIEW_IMAGES]]
    images = db.get_generation_images(previews)
    cards = []
    for generation_id in page:
        card = dict(generations.get(generation_id) or {"id": generation_id})
        card["matching_count"] = len(by_generation[generation_id])
        card["images"] = [_image(images[r["id"]]) for r in by_generation[generation_id][:PREVIEW_IMAGES]
                          if r["id"] in images]
        cards.append(card)

    return {
        "generations": cards,
        "state": {
            "offset": offset,
            "generation_count": len(order),
            # Every generation filed here, filtered or not: the tab's label.
            "stored_generations": db.count_generations(files),
            "hide_nsfw_images": hide_nsfw,
            "hide_promptless_images": hide_promptless,
            **counts,
        },
    }


def register(app: FastAPI):
    """Attach this module's endpoints to the app."""

    @app.get("/model-manager/generations/page")
    async def get_generation_page(path: str, offset: int = 0, limit: int = GALLERY_PAGE_SIZE,
                                  hide_nsfw_images: Optional[bool] = None,
                                  hide_promptless_images: Optional[bool] = None):
        """
        One page of the open model's generation cards, through the gallery's
        two switches - the settings decide either one not sent.

        Args:
            path: The open model's file; its version's files make the gallery.
            offset: How many cards come before the page.
            limit: The most cards the page may hold.
        """
        try:
            hide_nsfw, hide_promptless = gallery_switches(hide_nsfw_images,
                                                          hide_promptless_images)
            page = generation_page(get_models_db(), path, hide_nsfw, hide_promptless,
                                   offset, limit)
            return JSONResponse({"success": True, **page})
        except Exception as e:
            import traceback
            print(f"[ModelManager] Generation page error: {e}")
            traceback.print_exc()
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/generations/{generation_id}/images")
    async def get_generation_all_images(generation_id: int, path: str,
                                        hide_nsfw_images: Optional[bool] = None,
                                        hide_promptless_images: Optional[bool] = None):
        """Every image of one generation this gallery shows, for "Show images"."""
        try:
            db = get_models_db()
            hide_nsfw, hide_promptless = gallery_switches(hide_nsfw_images,
                                                          hide_promptless_images)
            rows = [r for r in db.generation_gallery_images(db.generation_gallery_files(path))
                    if r["generation_id"] == generation_id]
            shown, _ = _filtered(rows, hide_nsfw, hide_promptless)
            images = db.get_generation_images([r["id"] for r in shown])
            return JSONResponse({"success": True,
                                 "images": [_image(images[r["id"]]) for r in shown
                                            if r["id"] in images]})
        except Exception as e:
            print(f"[ModelManager] Generation images error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/generations/images/{image_id}/file")
    async def get_generation_image_file(image_id: int):
        """A generated image, by its record: only what was recorded is served."""
        path = get_models_db().get_generation_image_path(image_id)
        if not path or not os.path.isfile(path):
            return JSONResponse({"success": False, "error": "Image not found"}, status_code=404)
        return FileResponse(path)

    @app.post("/model-manager/generations/{generation_id}/delete")
    def delete_generation(generation_id: int, delete_files: bool = Form(default=False)):
        """
        Remove a generation's records, and with delete_files its image files.

        Only the files its images were saved to are touched - nothing a path
        from the page names - and of those, only ones no other record names.

        Returns:
            deleted_files, and failed: the files that could not be removed,
            with why.
        """
        try:
            paths = get_models_db().delete_generation(generation_id)
            deleted, failed = [], []
            if delete_files:
                for path in paths:
                    if not os.path.isfile(path):
                        continue
                    try:
                        os.remove(path)
                        deleted.append(path)
                    except OSError as e:
                        failed.append({"path": path, "error": str(e)})
            print(f"[ModelManager] Deleted generation {generation_id}"
                  + (f" and {len(deleted)} of its image files" if delete_files else ""))
            return JSONResponse({"success": True, "deleted_files": len(deleted),
                                 "failed": failed})
        except Exception as e:
            print(f"[ModelManager] Delete generation error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)
