"""
A version's gallery.

Reading cached images, fetching the next page, and re-fetching a version's
images from Civitai. Kept apart from models.py because a gallery is paged and
refreshed on its own schedule, and its endpoints are about pictures rather
than about the model they belong to.
"""
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse, RedirectResponse, Response

from typing import Any, Dict, Optional, Tuple

from ..db import get_models_db
from ..forge_host import setting
from ..nsfw import SFW_MAX, stamp_levels
from ..civitai import (
    CivitaiClient, enrich_images_with_generation_data, keep_generation_data,
)
from ..gallery import filter_images, gallery_page_size
from .common import failed

# How many batches of 100 "Download More Images" asks Civitai for, at most,
# while every one holds only images already stored.
LOAD_MORE_BATCHES = 5


def gallery_switches(hide_nsfw: Optional[bool],
                     hide_promptless: Optional[bool]) -> Tuple[bool, bool]:
    """
    The Model Manager gallery's two switches: as the page set them, or, until
    it has, as the settings say. The page sends neither on a model's first
    load, so that the settings are read at all.
    """
    if hide_nsfw is None:
        hide_nsfw = setting('model_manager_gallery_hide_nsfw')
    if hide_promptless is None:
        hide_promptless = setting('model_manager_hide_promptless_images')
    return hide_nsfw, hide_promptless


def civitai_has_more(version: Optional[Dict[str, Any]]) -> bool:
    """
    Whether Civitai may have images of this version not stored yet: a cursor
    to the next batch, or no sign a sync ever looked - a version never
    synced, or one a bulk sync stored before it kept the cursor. A sync that
    reached the end leaves no cursor and its date.
    """
    if not version:
        return False
    return bool(version.get("next_images_cursor")) or not version.get("images_sync_last_date")


# How many batches a page may fetch from Civitai before showing what it has:
# a page of 100 needs one at most, a large one a few.
PAGE_FETCHES = 5


def gallery_page(db, version_id: int, page: int, hide_nsfw: bool, hide_promptless: bool,
                 fetch: bool = True) -> Dict[str, Any]:
    """
    Page `page` of a version's gallery: the images stored at places
    (page - 1) * size + 1 to page * size, in gallery order, before the
    switches - which only decide which of them are drawn. A page does not
    depend on how the images came, nor on the page size they came under:
    when fewer are stored than the page reaches, the rest are fetched from
    Civitai first, in its batches of 100, until there are enough or Civitai
    has no more.

    Returns:
        images: the page's images the switches let through, judged;
        page: its number and size, how many images it holds, how many are
            shown, what each switch hid, whether more come after it, and
            the error if fetching failed - what is stored is shown anyway;
        images_state: the gallery's totals, for the banner.
    """
    size = gallery_page_size()
    page = max(1, int(page or 1))
    version = db.get_version_by_id(version_id)
    stored = db.count_images_by_version([version_id]).get(version_id, 0)
    error = None
    fetches = 0
    while fetch and stored < page * size and civitai_has_more(version) and fetches < PAGE_FETCHES:
        fetches += 1
        try:
            brought = download_more(db, version)
        except Exception as e:
            error = str(e)
            print(f"[ModelManager] Fetching images for page {page} of version {version_id} failed: {e}")
            break
        version = db.get_version_by_id(version_id)
        stored = db.count_images_by_version([version_id]).get(version_id, 0)
        # Nothing new ends it: download_more() has already passed over up to
        # LOAD_MORE_BATCHES batches of stored images to find any.
        if not brought.get("downloaded_count"):
            break

    rows = db.get_image_page(version_id, (page - 1) * size, size)
    shown, counts = filter_images(rows, hide_nsfw, hide_promptless)
    return {
        "images": stamp_levels(shown),
        "page": {
            "number": page,
            "size": size,
            "count": len(rows),
            "shown": counts["filtered"],
            "hidden_nsfw": counts["hidden_nsfw"],
            "hidden_promptless": counts["hidden_promptless"],
            "hidden_both": counts["hidden_both"],
            "more": stored > page * size or civitai_has_more(version),
            "error": error,
        },
        "images_state": gallery_state(db, version_id, hide_nsfw, hide_promptless),
    }


STILL_HOST = "image.civitai.com"
STILL_IMAGE_SECONDS = 7 * 24 * 3600
STILL_NONE_SECONDS = 24 * 3600


def still_answer(url: str, head=requests.head):
    """
    The response for /model-manager/video-still: a cached redirect to `url`
    if Civitai serves an image there, a cached 404 if it serves anything
    else. Only Civitai's image server's addresses are followed - nothing else
    is asked for, or redirected to. Civitai not answering, it is redirected
    to all the same, uncached: the check is a guard, not a gate.
    """
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or parsed.hostname != STILL_HOST:
        return Response(status_code=400)
    try:
        reply = head(url, allow_redirects=True, timeout=15)
        kind = (reply.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except Exception as e:
        print(f"[ModelManager] Could not check a video's still: {e}")
        return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})
    if reply.status_code < 400 and kind.startswith("image/"):
        return RedirectResponse(url, status_code=302,
                                headers={"Cache-Control": f"private, max-age={STILL_IMAGE_SECONDS}"})
    return Response(status_code=404, headers={"Cache-Control": f"private, max-age={STILL_NONE_SECONDS}"})


def gallery_state(db, version_id: int, hide_nsfw: bool, hide_promptless: bool) -> Dict[str, Any]:
    """The gallery's totals, as the banner states them, over every stored image."""
    max_level = SFW_MAX if hide_nsfw else None
    counts = db.get_image_counts(version_id, max_nsfw_level=max_level,
                                 require_prompt=hide_promptless)
    record = db.get_version_by_id(version_id)
    return {
        "version_id": version_id,
        "next_cursor": record.get("next_images_cursor") if record else None,
        "sync_date": record.get("images_sync_last_date") if record else None,
        "total_count": counts["total"],
        "filtered_count": counts["filtered"],
        "hidden_count": counts["hidden"],
        "hidden_nsfw": counts["hidden_nsfw"],
        "hidden_promptless": counts["hidden_promptless"],
        "hidden_both": counts["hidden_both"],
        "nsfw_count": counts["nsfw_count"],
        "promptless_count": counts["promptless_count"],
        "promptless_total": counts["promptless_total"],
        "hide_nsfw_images": hide_nsfw,
        "hide_promptless_images": hide_promptless,
    }


def download_more(db, version: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetch the next batch of a version's images from Civitai, and store those
    not stored already, on a page of their own after the last.

    Args:
        version: The version's model_versions row, for its id and cursor.

    Returns:
        images (the new ones, judged), next_cursor, downloaded_count, and a
        message when nothing new came.
    """
    version_id = version["id"]
    cursor = version.get("next_images_cursor")

    # Only images not already stored are new. A version whose first
    # page a bulk sync stored has no cursor - the sync used not to
    # keep one - so the first batch asked for is the one it already
    # has: that batch is passed over and the next one asked for. It
    # used to be stored again under a new page number, and the click
    # showed nothing new.
    stored = db.get_image_ids(version_id)
    client = CivitaiClient.from_settings()
    try:
        for _ in range(LOAD_MORE_BATCHES):
            result = client.get_model_images(
                version_id=version_id,
                cursor=cursor,
                limit=100
            )
            new_images = [img for img in result.get("images", [])
                          if img.get("id") not in stored]
            next_cursor = result.get("next_cursor")
            if new_images or not next_cursor:
                break
            cursor = next_cursor
        # /images returns meta: null - fetch generation data separately
        enrich_images_with_generation_data(client, new_images)
    finally:
        client.close()

    if not new_images:
        # Nothing new: at the end of the gallery, or still among
        # images already stored after LOAD_MORE_BATCHES batches, in
        # which case the next click carries on from there.
        db.update_version_images_state(version_id, next_cursor)
        return {
            "images": [],
            "next_cursor": next_cursor,
            "downloaded_count": 0,
            "message": ("Only images already downloaded so far" if next_cursor
                        else "No more images available"),
        }

    # A page of its own, after the last one stored: the gallery orders
    # by page, then by Civitai's position within it. The number used
    # to come from the image count - reading every image to count
    # them - and fell back onto the last page's number whenever that
    # count was not a multiple of 100, interleaving the two batches.
    page_number = db.get_cached_page_count(version_id) + 1

    # Store images in database
    db.store_images(version_id, page_number, new_images)

    # Update cursor and sync date
    db.update_version_images_state(version_id, next_cursor)

    print(f"[ModelManager] Downloaded {len(new_images)} more images for version {version_id} "
          f"(page {page_number}, has_more: {next_cursor is not None})")

    return {
        "images": stamp_levels(new_images),
        "next_cursor": next_cursor,
        "downloaded_count": len(new_images),
    }


def register(app: FastAPI):
    """Attach this module's endpoints to the app.

    The ones that wait on Civitai, or on a sync, are plain `def`, not `async
    def`. This app is the WebUI's own, and it serves every request from one
    event loop: an async handler runs on that loop, and one that blocks in
    `requests` holds it, so every other request in the WebUI - Gradio's
    included - waits until Civitai answers. FastAPI runs a plain `def` handler
    on a worker thread instead. tests/py/loop_test.py holds this in place.
    """
    @app.post("/model-manager/images/resync")
    def resync_images(version_id: int = Form(default=0)):
        """
        Replace a version's images with a fresh first page, at the page size.

        The stored gallery is replaced only once the fetch has worked, and
        the generation data it held is carried over to the fresh copies, so
        a lookup that fails does not lose prompts.

        Args:
            version_id: Civitai version ID.

        Returns:
            New images and cursor state.
        """
        try:
            if not version_id:
                return JSONResponse(
                    {"success": False, "error": "version_id is required"},
                    status_code=400
                )

            from ..civitai import CivitaiClient

            db = get_models_db()

            # Fetch fresh images from Civitai (first batch, no cursor). The
            # stored gallery is only replaced once this has worked: clearing
            # it first left a model with no images whenever Civitai failed.
            client = CivitaiClient.from_settings()
            try:
                result = client.get_model_images(version_id, cursor=None, limit=gallery_page_size())
                images = result.get("images", [])
                # /images returns meta: null. Keep the generation data already
                # stored, then look up the rest - a lookup that fails, or
                # cannot run without an API key, no longer loses prompts.
                keep_generation_data(images, db.get_images(version_id))
                enrich_images_with_generation_data(client, images)
            finally:
                client.close()

            next_cursor = result.get("next_cursor")

            db.replace_first_page(version_id, images, next_cursor)

            print(f"[ModelManager] Resynced {len(images)} images for version {version_id} "
                  f"(has_more: {next_cursor is not None})")

            return JSONResponse({
                "success": True,
                "images": stamp_levels(images),
                "next_cursor": next_cursor,
                "fetched_count": len(images)
            })

        except Exception as e:
            return failed(e, "Resync images error")

    @app.get("/model-manager/images/gallery-page")
    def get_gallery_page(version_id: int, page: int = 1,
                         hide_nsfw_images: Optional[bool] = None,
                         hide_promptless_images: Optional[bool] = None):
        """
        Page `page` of a version's gallery, fetching from Civitai what the
        library lacks to fill it - see gallery_page(). A plain def: it can
        wait on Civitai.

        Args:
            version_id: Civitai version ID.
            page: Which page, from 1.
            hide_nsfw_images, hide_promptless_images: The switches; the
                settings decide either one not sent.
        """
        try:
            hide_nsfw, hide_promptless = gallery_switches(hide_nsfw_images,
                                                          hide_promptless_images)
            return JSONResponse({"success": True, **gallery_page(
                get_models_db(), version_id, page, hide_nsfw, hide_promptless)})
        except Exception as e:
            return failed(e, "Gallery page error")

    @app.get("/model-manager/video-still")
    def video_still(url: str = ""):
        """
        A video card's still, checked: a redirect to Civitai's still when it
        is an image, a 404 when it is not. Civitai's still of a video
        (`anim=false`) is now and then the whole original instead - a 32 MB
        MP4 for 1 video in 80 - which the browser downloaded in full as the
        poster, and could not draw. Only the headers are asked for here; the
        browser fetches the image from Civitai as before. The answer is
        remembered by the browser (Cache-Control): a week for an image, a day
        for none, so a still Civitai makes later is picked up. A plain def:
        it waits on Civitai.
        """
        return still_answer(url)
