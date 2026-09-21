"""
A version's gallery.

Reading cached images, fetching the next page, and re-fetching a version's
images from Civitai. Kept apart from models.py because a gallery is paged and
refreshed on its own schedule, and its endpoints are about pictures rather
than about the model they belong to.
"""
from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

from ..db import get_models_db
from ..civitai import CivitaiClient, enrich_images_with_generation_data


def register(app: FastAPI):
    """Attach this module's endpoints to the app."""
    @app.post("/model-manager/images/resync")
    async def resync_images(version_id: int = Form(default=0)):
        """
        Clear and re-fetch images for a version using cursor pagination.

        Deletes all existing images and fetches fresh first batch (100 images).

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

            # Clear existing images for this version
            db.clear_version_images(version_id)

            # Fetch fresh images from Civitai (first batch, no cursor)
            client = CivitaiClient.from_settings()
            try:
                result = client.get_model_images(version_id, cursor=None, limit=100)
                images = result.get("images", [])
                # /images returns meta: null - fetch generation data separately
                enrich_images_with_generation_data(client, images)
            finally:
                client.close()

            next_cursor = result.get("next_cursor")

            # Store in database
            if images:
                db.store_images(version_id, page=1, images=images)

            # Update cursor and sync date
            db.update_version_images_state(version_id, next_cursor)

            print(f"[ModelManager] Resynced {len(images)} images for version {version_id} "
                  f"(has_more: {next_cursor is not None})")

            return JSONResponse({
                "success": True,
                "images": images,
                "next_cursor": next_cursor,
                "fetched_count": len(images)
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Resync images error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.post("/model-manager/images/load-more")
    async def load_more_images(
        version_id: int = Form(default=0)
    ):
        """
        Download more images for a model from Civitai using cursor pagination.

        Args:
            version_id: Civitai version ID.

        Returns:
            New images and updated cursor state.
        """
        try:
            if not version_id:
                return JSONResponse(
                    {"success": False, "error": "version_id is required"},
                    status_code=400
                )

            db = get_models_db()

            # Get version record to get stored cursor
            version = db.get_version_by_id(version_id)
            if not version:
                return JSONResponse(
                    {"success": False, "error": "Version not found"},
                    status_code=404
                )

            cursor = version.get("next_images_cursor")

            # Fetch images using cursor (100 per batch)
            client = CivitaiClient.from_settings()
            try:
                result = client.get_model_images(
                    version_id=version_id,
                    cursor=cursor,
                    limit=100
                )
                new_images = result.get("images", [])
                # /images returns meta: null - fetch generation data separately
                enrich_images_with_generation_data(client, new_images)
            finally:
                client.close()

            next_cursor = result.get("next_cursor")

            if not new_images:
                # No images returned, mark as fully loaded
                db.update_version_images_state(version_id, None)
                return JSONResponse({
                    "success": True,
                    "images": [],
                    "next_cursor": None,
                    "message": "No more images available"
                })

            # Calculate page number for storage (based on current image count)
            current_images = db.get_all_images_for_version(version_id)
            current_count = len(current_images)
            page_number = (current_count // 100) + 1

            # Store images in database
            db.store_images(version_id, page_number, new_images)

            # Update cursor and sync date
            db.update_version_images_state(version_id, next_cursor)

            print(f"[ModelManager] Downloaded {len(new_images)} more images for version {version_id} "
                  f"(total stored: {current_count + len(new_images)}, has_more: {next_cursor is not None})")

            return JSONResponse({
                "success": True,
                "images": new_images,
                "next_cursor": next_cursor,
                "downloaded_count": len(new_images)
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Load more images error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/images/cached")
    async def get_cached_images(version_id: int):
        """
        Get all cached images for a version.

        Args:
            version_id: Civitai version ID.

        Returns:
            All cached images and cursor state.
        """
        try:
            db = get_models_db()

            images = db.get_all_images_for_version(version_id)
            version_record = db.get_version_by_id(version_id)

            return JSONResponse({
                "success": True,
                "images": images,
                "images_state": {
                    "version_id": version_id,
                    "next_cursor": version_record.get("next_images_cursor") if version_record else None,
                    "sync_date": version_record.get("images_sync_last_date") if version_record else None,
                }
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Get cached images error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )
