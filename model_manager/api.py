"""
API endpoints for Model Manager.
Provides REST API for model listing, filtering, and details.
"""
import threading
from typing import Optional
from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse
from modules import script_callbacks

from .scanner import scan_models, filter_models, sort_models
from .sync_service import SyncService, SyncProgress
from .scan_service import ScanService, ScanProgress
from .models_db import get_models_db
from .images_cache import get_images_cache
from .civitai_api import CivitaiClient


# Global sync state
_active_sync: Optional[SyncService] = None
_sync_thread: Optional[threading.Thread] = None
_sync_progress: Optional[SyncProgress] = None

# Global scan state
_active_scan: Optional[ScanService] = None
_scan_thread: Optional[threading.Thread] = None
_scan_progress: Optional[ScanProgress] = None


def setup_api(app: FastAPI):
    """Register API endpoints."""

    @app.get("/model-manager/models")
    async def get_models(
        search: str = "",
        type: str = "",
        base_model: str = "",
        nsfw_max: str = "",
        nsfw_levels: str = "",  # Comma-separated list of levels
        has_civitai: str = "",
        sort_by: str = "name",
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 0,  # 0 = use setting
    ):
        """Get models with optional filters and pagination using database."""
        try:
            from modules import shared

            # Use setting for page size if not specified
            if page_size <= 0:
                page_size = int(getattr(shared.opts, 'model_manager_page_size', 10))

            # Map sort field names
            sort_field_map = {
                "name": "display_name",
                "file_name": "file_name",
                "size": "file_size",
                "date": "file_modified",
                "rating": "rating",
                "downloads": "download_count",
                "type": "model_type",
                "base_model": "base_model",
            }
            db_sort_by = sort_field_map.get(sort_by, "display_name")

            # Calculate offset
            offset = (page - 1) * page_size

            # Query database
            db = get_models_db()
            models, total_count = db.query_models(
                search=search if search else None,
                model_type=type if type and type != "All" else None,
                base_model=base_model if base_model and base_model != "All" else None,
                nsfw_levels=[l.strip() for l in nsfw_levels.split(",") if l.strip()] if nsfw_levels else None,
                nsfw_max=nsfw_max if nsfw_max else None,
                has_civitai=True if has_civitai == "Yes" else (False if has_civitai == "No" else None),
                sort_by=db_sort_by,
                sort_order=sort_order,
                limit=page_size,
                offset=offset
            )

            return JSONResponse({
                "success": True,
                "models": models,
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "has_more": offset + len(models) < total_count,
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] API error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/models/details")
    async def get_model_details(path: str):
        """Get detailed info for a specific model by file path."""
        try:
            from .storage import load_model_metadata
            import os
            from datetime import datetime

            if not os.path.exists(path):
                return JSONResponse(
                    {"success": False, "error": "Model file not found"},
                    status_code=404
                )

            # Load metadata from .civitai.info
            model_info, version_info, _ = load_model_metadata(path)

            # Build response
            stat = os.stat(path)
            result = {
                "file_path": path,
                "file_name": os.path.basename(path),
                "file_size": stat.st_size,
                "file_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }

            if model_info:
                result["civitai_model"] = {
                    "id": model_info.id,
                    "name": model_info.name,
                    "description": model_info.description,
                    "type": model_info.type.value,
                    "nsfw": model_info.nsfw.value,
                    "tags": model_info.tags,
                    "creator": model_info.creator,
                    "rating": model_info.rating,
                    "download_count": model_info.download_count,
                }

            version_id = None
            if version_info:
                version_id = version_info.id
                result["civitai_version"] = {
                    "id": version_info.id,
                    "name": version_info.name,
                    "base_model": version_info.base_model,
                    "trained_words": version_info.trained_words,
                    "published_at": version_info.published_at.isoformat() if version_info.published_at else None,
                }

            # Get images from SQLite cache
            if version_id:
                cache = get_images_cache()
                images = cache.get_all_images_for_version(version_id)
                pagination = cache.get_pagination_state(version_id)

                if images:
                    result["images"] = images  # Raw image data from cache

                if pagination:
                    result["images_pagination"] = {
                        "total_count": pagination.get("total_count", 0),
                        "total_pages": pagination.get("total_pages", 1),
                        "fetched_pages": pagination.get("fetched_pages", 1),
                        "version_id": version_id,
                    }

            return JSONResponse({"success": True, "model": result})

        except Exception as e:
            import traceback
            print(f"[ModelManager] API error: {e}")
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
        Load more images for a model from Civitai using page-based pagination.

        Args:
            version_id: Civitai version ID.

        Returns:
            New images and pagination state.
        """
        try:
            if not version_id:
                return JSONResponse(
                    {"success": False, "error": "version_id is required"},
                    status_code=400
                )

            # Get current pagination state from cache
            cache = get_images_cache()
            pagination = cache.get_pagination_state(version_id)

            if not pagination:
                return JSONResponse({
                    "success": False,
                    "error": "No pagination data found. Please sync the model first."
                }, status_code=404)

            fetched_pages = pagination.get("fetched_pages", 1)
            total_pages = pagination.get("total_pages", 1)

            # Check if there are more pages
            if fetched_pages >= total_pages:
                return JSONResponse({
                    "success": True,
                    "images": [],
                    "has_more": False,
                    "message": "No more images available"
                })

            # Fetch next page from Civitai
            next_page = fetched_pages + 1
            client = CivitaiClient.from_settings()
            try:
                result = client.get_model_images(
                    version_id=version_id,
                    limit=200,
                    page=next_page
                )
            finally:
                client.close()

            new_images = result.get("images", [])
            total_count = result.get("total_count", 0)
            total_pages = result.get("total_pages", 1)

            if not new_images:
                return JSONResponse({
                    "success": True,
                    "images": [],
                    "has_more": False,
                    "message": "No more images available"
                })

            # Store images in cache
            cache.store_images(version_id, next_page, new_images)

            # Update pagination state
            cache.update_pagination_state(
                version_id=version_id,
                total_count=total_count,
                total_pages=total_pages,
                fetched_pages=next_page
            )

            print(f"[ModelManager] Loaded {len(new_images)} more images for version {version_id} "
                  f"(page {next_page}/{total_pages})")

            return JSONResponse({
                "success": True,
                "images": new_images,
                "page": next_page,
                "total_pages": total_pages,
                "total_count": total_count,
                "has_more": next_page < total_pages
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
            All cached images and pagination state.
        """
        try:
            cache = get_images_cache()

            images = cache.get_all_images_for_version(version_id)
            pagination = cache.get_pagination_state(version_id)

            return JSONResponse({
                "success": True,
                "images": images,
                "pagination": pagination
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Get cached images error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.post("/model-manager/sync")
    async def start_sync(
        force: str = Form(default="false"),  # Form data comes as string
        paths: str = Form(default="")  # Comma-separated paths, empty = all models
    ):
        """
        Start syncing models with Civitai.

        Args:
            force: Re-sync even if civitai data exists ("true" or "false").
            paths: Comma-separated model paths, or empty for all.

        Returns immediately. Poll /model-manager/sync/progress for status.
        """
        global _active_sync, _sync_thread, _sync_progress

        # Parse force as boolean (form data sends strings)
        force_bool = str(force).lower() in ('true', '1', 'yes')
        print(f"[ModelManager] Sync requested with force={force} -> {force_bool}")

        # Check if sync already running
        if _sync_thread is not None and _sync_thread.is_alive():
            return JSONResponse(
                {"success": False, "error": "Sync already in progress"},
                status_code=409
            )

        # Parse paths
        model_paths = None
        if paths:
            model_paths = [p.strip() for p in paths.split(",") if p.strip()]

        # Create sync service and start in background
        _active_sync = SyncService()

        def run_sync():
            global _sync_progress
            try:
                _sync_progress = _active_sync.sync_all(
                    model_paths=model_paths,
                    force=force_bool
                )
            except Exception as e:
                import traceback
                print(f"[ModelManager] Sync error: {e}")
                traceback.print_exc()
                _sync_progress = SyncProgress(is_complete=True)
                _sync_progress.error_messages.append(str(e))

        _sync_thread = threading.Thread(target=run_sync, daemon=True)
        _sync_thread.start()

        return JSONResponse({
            "success": True,
            "message": "Sync started"
        })

    @app.get("/model-manager/sync/progress")
    async def get_sync_progress():
        """Get current sync progress."""
        global _active_sync, _sync_progress

        # If no sync has been started
        if _active_sync is None and _sync_progress is None:
            return JSONResponse({
                "success": True,
                "progress": None,
                "message": "No sync in progress"
            })

        # Get live progress from service if available
        if _active_sync is not None:
            progress = _active_sync.progress
        else:
            progress = _sync_progress

        return JSONResponse({
            "success": True,
            "progress": progress.to_dict() if progress else None
        })

    @app.post("/model-manager/sync/cancel")
    async def cancel_sync():
        """Cancel active sync operation."""
        global _active_sync

        if _active_sync is None:
            return JSONResponse({
                "success": False,
                "error": "No sync in progress"
            })

        _active_sync.cancel()

        return JSONResponse({
            "success": True,
            "message": "Cancel requested"
        })

    @app.post("/model-manager/scan")
    async def start_scan():
        """
        Start scanning model directories to populate the database.

        Scans all model directories, reads metadata files, and stores
        computed metadata in SQLite for fast querying.

        Returns immediately. Poll /model-manager/scan/progress for status.
        """
        global _active_scan, _scan_thread, _scan_progress

        # Check if scan already running
        if _scan_thread is not None and _scan_thread.is_alive():
            return JSONResponse(
                {"success": False, "error": "Scan already in progress"},
                status_code=409
            )

        # Create scan service and start in background
        _active_scan = ScanService()

        def run_scan():
            global _scan_progress
            try:
                _scan_progress = _active_scan.scan_models()
            except Exception as e:
                import traceback
                print(f"[ModelManager] Scan error: {e}")
                traceback.print_exc()
                _scan_progress = ScanProgress(is_complete=True)
                _scan_progress.errors.append(str(e))

        _scan_thread = threading.Thread(target=run_scan, daemon=True)
        _scan_thread.start()

        return JSONResponse({
            "success": True,
            "message": "Scan started"
        })

    @app.get("/model-manager/scan/progress")
    async def get_scan_progress():
        """Get current scan progress."""
        global _active_scan, _scan_progress

        # If no scan has been started
        if _active_scan is None and _scan_progress is None:
            return JSONResponse({
                "success": True,
                "progress": None,
                "message": "No scan in progress"
            })

        # Get live progress from service if available
        if _active_scan is not None:
            progress = _active_scan.progress
        else:
            progress = _scan_progress

        return JSONResponse({
            "success": True,
            "progress": progress.to_dict() if progress else None
        })

    @app.post("/model-manager/scan/cancel")
    async def cancel_scan():
        """Cancel active scan operation."""
        global _active_scan

        if _active_scan is None:
            return JSONResponse({
                "success": False,
                "error": "No scan in progress"
            })

        _active_scan.cancel()

        return JSONResponse({
            "success": True,
            "message": "Cancel requested"
        })

    @app.get("/model-manager/stats")
    async def get_stats():
        """Get database statistics."""
        try:
            db = get_models_db()
            stats = db.get_stats()
            last_scan = db.get_metadata("last_scan")

            return JSONResponse({
                "success": True,
                "stats": stats,
                "last_scan": last_scan
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Stats error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/filters")
    async def get_filter_options():
        """Get distinct values for filter dropdowns."""
        try:
            db = get_models_db()

            return JSONResponse({
                "success": True,
                "model_types": db.get_distinct_values("model_type"),
                "base_models": db.get_distinct_values("base_model"),
                "nsfw_levels": db.get_distinct_values("nsfw_level"),
                "creators": db.get_distinct_values("creator"),
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Filters error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.post("/model-manager/models/delete")
    async def delete_model(path: str = Form(...)):
        """
        Delete a model and all related files.

        Deletes:
        - The model file itself
        - Associated metadata files (.civitai.info, .preview.png, etc.)
        - The containing folder if it's named after the model and becomes empty

        Args:
            path: Full path to the model file.

        Returns:
            Success status and list of deleted files.
        """
        import os
        import glob

        try:
            if not os.path.exists(path):
                return JSONResponse(
                    {"success": False, "error": "Model file not found"},
                    status_code=404
                )

            deleted_files = []
            model_dir = os.path.dirname(path)
            model_basename = os.path.splitext(os.path.basename(path))[0]

            # Find all related files (same base name, different extensions)
            base_path = os.path.splitext(path)[0]
            related_patterns = [
                path,  # The model file itself
                base_path + ".civitai.info",
                base_path + ".preview.png",
                base_path + ".preview.jpg",
                base_path + ".preview.jpeg",
                base_path + ".png",
                base_path + ".jpg",
                base_path + ".images.json",  # Legacy file
            ]

            # Delete all related files
            for file_path in related_patterns:
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        deleted_files.append(os.path.basename(file_path))
                        print(f"[ModelManager] Deleted: {file_path}")
                    except Exception as e:
                        print(f"[ModelManager] Failed to delete {file_path}: {e}")

            # Check if folder should be deleted
            # Only delete if folder name matches model name and is now empty
            folder_name = os.path.basename(model_dir)
            if folder_name.lower() == model_basename.lower():
                # Check if folder is empty
                remaining_files = os.listdir(model_dir)
                if not remaining_files:
                    try:
                        os.rmdir(model_dir)
                        deleted_files.append(f"[folder] {folder_name}/")
                        print(f"[ModelManager] Deleted empty folder: {model_dir}")
                    except Exception as e:
                        print(f"[ModelManager] Failed to delete folder {model_dir}: {e}")
                else:
                    print(f"[ModelManager] Folder not empty, keeping: {model_dir} ({len(remaining_files)} files remaining)")

            # Remove from database
            db = get_models_db()
            db.delete_model(path)

            # Clear images from cache if we have version info
            try:
                from .storage import read_civitai_info
                # We already deleted the file, so we can't read it
                # The images will be orphaned in cache but that's okay
            except Exception:
                pass

            return JSONResponse({
                "success": True,
                "deleted": deleted_files,
                "message": f"Deleted {len(deleted_files)} files"
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Delete error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/ui-options")
    async def get_ui_options():
        """Get samplers and schedulers from WebUI."""
        try:
            from modules import sd_samplers, sd_schedulers

            # Get sampler names
            samplers = [s.name for s in sd_samplers.all_samplers]

            # Get scheduler labels
            schedulers = [s.label for s in sd_schedulers.schedulers]

            return JSONResponse({
                "success": True,
                "samplers": samplers,
                "schedulers": schedulers
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] UI options error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    print("[ModelManager] API endpoints registered")


# Register API on app start
def on_app_started(demo, app):
    setup_api(app)


script_callbacks.on_app_started(on_app_started)
