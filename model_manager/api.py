"""
API endpoints for Model Manager.
Provides REST API for model listing, filtering, and details.
"""
import threading
import time
from typing import Optional
from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse
from modules import script_callbacks

from .sync_service import SyncService, SyncProgress
from .scan_service import ScanService, ScanProgress
from .models_db import get_models_db
from .civitai_api import CivitaiClient

print("[ModelManager API] === api.py TOP-LEVEL CODE EXECUTING ===")

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

    # NSFW level bitmask mapping
    NSFW_LEVEL_MAP = {
        "PG": 1,
        "PG-13": 2,
        "R": 4,
        "X": 8,
        "XXX": 16,
        "Blocked": 32,
        "Unknown": 64,  # Highest level - includes all models
    }

    @app.get("/model-manager/models")
    async def get_models(
        search: str = "",
        type: str = "",
        base_model: str = "",
        nsfw_max: str = "",
        nsfw_levels: str = "",  # Comma-separated list of levels (PG, PG-13, R, X, XXX, Unknown)
        nsfw_mode: str = "max",  # "max" = up to selected level, "contains" = has any selected level
        has_civitai: str = "",
        is_bookmarked: Optional[bool] = None,  # None = all, True = bookmarked only
        min_versions: str = "",  # Minimum number of local versions
        preview_least_nsfw: Optional[bool] = None,  # None = use setting, True/False = override
        commercial_use: str = "",  # Filter by commercial use: None, Image, Rent, RentCivit, Sell
        allow_derivatives: Optional[bool] = None,  # None = all, True/False = filter
        allow_different_license: Optional[bool] = None,  # None = all, True/False = filter
        sort_by: str = "name",
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 0,  # 0 = use setting
    ):
        """
        Get models with optional filters and pagination using database.
        Returns models grouped by Civitai model ID (latest version per group).
        """
        try:
            request_start = time.perf_counter()
            from modules import shared

            # Use setting for page size if not specified
            if page_size <= 0:
                page_size = int(getattr(shared.opts, 'model_manager_page_size', 10))

            # Parse card size setting (format: WIDTHxHEIGHT)
            def parse_card_size(size_str: str):
                try:
                    if 'x' in size_str.lower():
                        parts = size_str.lower().split('x')
                        return int(parts[0].strip()), int(parts[1].strip())
                except (ValueError, IndexError):
                    pass
                return 200, 280  # Default

            card_size_str = getattr(shared.opts, 'model_manager_card_size', '200x280')
            card_width, card_height = parse_card_size(card_size_str)

            # Valid sort columns in DB
            valid_sort_columns = {
                "name", "display_name", "file_name", "file_size", "file_modified",
                "model_type", "base_model", "nsfw_level", "rating",
                "download_count", "published_at"
            }

            # Map short aliases to DB columns
            sort_aliases = {
                "name": "display_name",
                "size": "file_size",
                "date": "file_modified",
                "downloads": "download_count",
                "type": "model_type",
            }

            # Use alias if exists, otherwise use directly if valid, else default
            if sort_by in sort_aliases:
                db_sort_by = sort_aliases[sort_by]
            elif sort_by in valid_sort_columns:
                db_sort_by = sort_by
            else:
                db_sort_by = "name"

            # Calculate offset
            offset = (page - 1) * page_size

            # Convert NSFW level names to integers
            nsfw_level_ints = None
            if nsfw_levels:
                level_names = [l.strip() for l in nsfw_levels.split(",") if l.strip()]
                nsfw_level_ints = []
                for name in level_names:
                    if name in NSFW_LEVEL_MAP:
                        nsfw_level_ints.append(NSFW_LEVEL_MAP[name])
                # Remove duplicates and ensure we have at least some levels
                if nsfw_level_ints:
                    nsfw_level_ints = list(set(nsfw_level_ints))

            # Parse min_versions
            min_versions_int = None
            if min_versions:
                try:
                    min_versions_int = int(min_versions)
                except ValueError:
                    pass

            # Get preview setting - use parameter if provided, otherwise use setting
            if preview_least_nsfw is None:
                preview_least_nsfw = getattr(shared.opts, 'model_manager_preview_least_nsfw', True)
            preview_least_nsfw = bool(preview_least_nsfw)

            # Query database with grouped query
            db = get_models_db()
            query_start = time.perf_counter()
            models, total_count = db.query_models_grouped(
                search=search if search else None,
                model_type=type if type and type != "All" else None,
                base_model=base_model if base_model and base_model != "All" else None,
                nsfw_levels=nsfw_level_ints,
                nsfw_mode=nsfw_mode if nsfw_mode in ("max", "contains") else "max",
                has_civitai=True if has_civitai == "Yes" else (False if has_civitai == "No" else None),
                is_bookmarked=is_bookmarked,
                min_versions=min_versions_int,
                commercial_use=commercial_use if commercial_use else None,
                allow_derivatives=allow_derivatives,
                allow_different_license=allow_different_license,
                sort_by=db_sort_by,
                sort_order=sort_order,
                limit=page_size,
                offset=offset,
                preview_least_nsfw=preview_least_nsfw
            )
            query_ms = (time.perf_counter() - query_start) * 1000

            # Get the setting value for JS to initialize checkbox
            preview_least_nsfw_setting = getattr(shared.opts, 'model_manager_preview_least_nsfw', True)

            response = JSONResponse({
                "success": True,
                "models": models,
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "card_width": card_width,
                "card_height": card_height,
                "has_more": offset + len(models) < total_count,
                "preview_least_nsfw_setting": preview_least_nsfw_setting,
            })
            total_ms = (time.perf_counter() - request_start) * 1000
            print(
                f"[ModelManager] /models page={page} size={page_size} returned={len(models)} total={total_count} "
                f"query_ms={query_ms:.1f} total_ms={total_ms:.1f}"
            )
            return response

        except Exception as e:
            import traceback
            print(f"[ModelManager] API error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/filter-defaults")
    async def get_filter_defaults():
        """Get default filter values needed before first model load."""
        try:
            from modules import shared

            return JSONResponse({
                "success": True,
                "preview_least_nsfw": getattr(shared.opts, 'model_manager_preview_least_nsfw', True),
            })
        except Exception as e:
            import traceback
            print(f"[ModelManager] Filter defaults error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/models/details")
    async def get_model_details(path: str, hide_nsfw_images: Optional[bool] = None):
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

            # Build response with file info
            stat = os.stat(path)
            result = {
                "file_path": path,
                "file_name": os.path.basename(path),
                "file_size": stat.st_size,
                "file_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }

            # Try database first (more reliable - uses filename matching during scan)
            version_id = None
            db = get_models_db()
            db_version = db.get_version(path)

            if db_version and db_version.get("id"):
                version_id = db_version["id"]
                result["civitai_version"] = {
                    "id": version_id,
                    "name": db_version.get("version_name"),
                    "base_model": db_version.get("base_model"),
                    "trained_words": db_version.get("trained_words", []),
                    "published_at": db_version.get("published_at"),
                }

                # Get model info from database if available
                model_id = db_version.get("model_id")
                if model_id:
                    db_model = db.get_civitai_model(model_id)
                    if db_model:
                        result["civitai_model"] = {
                            "id": db_model["id"],
                            "name": db_model.get("name"),
                            "description": db_model.get("description"),
                            "type": db_model.get("type"),
                            "nsfw": db_model.get("nsfw_level"),
                            "tags": db_model.get("tags", []),
                            "creator": db_model.get("creator_username"),
                            "rating": db_model.get("stats_rating", 0),
                            "download_count": db_model.get("stats_download_count", 0),
                        }

            # Fall back to .civitai.info parsing (with filename matching)
            if not version_id:
                model_info, version_info, _ = load_model_metadata(path)

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

                if version_info:
                    version_id = version_info.id
                    result["civitai_version"] = {
                        "id": version_info.id,
                        "name": version_info.name,
                        "base_model": version_info.base_model,
                        "trained_words": version_info.trained_words,
                        "published_at": version_info.published_at.isoformat() if version_info.published_at else None,
                    }

            # Get images and cursor state from database
            if version_id:
                db = get_models_db()
                version_record = db.get_version_by_id(version_id)

                # Determine NSFW filter - use parameter if provided, else use setting
                from modules import shared
                if hide_nsfw_images is None:
                    hide_nsfw_images = getattr(shared.opts, 'model_manager_preview_least_nsfw', True)

                # max_nsfw_level=5 means only PG (1) and PG-13 (2, 4) are shown
                max_nsfw_level = 5 if hide_nsfw_images else None

                images = db.get_all_images_for_version(version_id, max_nsfw_level=max_nsfw_level)
                image_counts = db.get_image_counts(version_id, max_nsfw_level=max_nsfw_level)

                if images:
                    result["images"] = images  # Raw image data from cache

                # Return cursor state for button visibility
                result["images_state"] = {
                    "version_id": version_id,
                    "next_cursor": version_record.get("next_images_cursor") if version_record else None,
                    "sync_date": version_record.get("images_sync_last_date") if version_record else None,
                    "total_count": image_counts["total"],
                    "filtered_count": image_counts["filtered"],
                    "hidden_count": image_counts["hidden"],
                    "hide_nsfw_images": hide_nsfw_images,
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

    @app.get("/model-manager/models/versions")
    async def get_model_versions(model_id: int):
        """
        Get all local versions for a Civitai model.

        Args:
            model_id: Civitai model ID.

        Returns:
            List of all local versions for this model.
        """
        try:
            db = get_models_db()
            versions = db.get_versions_for_model(model_id)

            return JSONResponse({
                "success": True,
                "model_id": model_id,
                "versions": versions,
                "count": len(versions)
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Get versions error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

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

            from .civitai_api import CivitaiClient

            db = get_models_db()

            # Clear existing images for this version
            db.clear_version_images(version_id)

            # Fetch fresh images from Civitai (first batch, no cursor)
            client = CivitaiClient.from_settings()
            try:
                result = client.get_model_images(version_id, cursor=None, limit=100)
            finally:
                client.close()

            images = result.get("images", [])
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
            finally:
                client.close()

            new_images = result.get("images", [])
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

    @app.post("/model-manager/models/force-sync")
    async def force_sync_model(model_id: int = Form(...)):
        """
        Force sync a model and all its local versions.

        Fetches fresh data from Civitai for the model and all versions
        that exist locally.

        Args:
            model_id: Civitai model ID.

        Returns:
            Success status and count of synced versions.
        """
        try:
            db = get_models_db()

            # Find all local versions of this model
            versions = db.get_versions_for_model(model_id)

            if not versions:
                return JSONResponse({
                    "success": False,
                    "error": "No local versions found for this model"
                }, status_code=404)

            # Create sync service and sync each version
            sync_service = SyncService()
            synced_count = 0
            errors = []

            for version in versions:
                file_path = version.get("file_path")
                if not file_path:
                    continue

                import os
                if not os.path.exists(file_path):
                    errors.append(f"File not found: {file_path}")
                    continue

                result = sync_service.sync_model(file_path, force=True)
                if result.success:
                    synced_count += 1
                elif result.error:
                    errors.append(f"{os.path.basename(file_path)}: {result.error}")

            return JSONResponse({
                "success": True,
                "synced_count": synced_count,
                "total_versions": len(versions),
                "errors": errors if errors else None
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Force sync error: {e}")
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
            db.delete_version(path)

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

    @app.post("/model-manager/bookmark")
    async def toggle_bookmark(
        model_id: int = Form(...),
        bookmarked: bool = Form(...)
    ):
        """
        Set bookmark status for a model.

        Args:
            model_id: Civitai model ID.
            bookmarked: True to bookmark, False to remove bookmark.

        Returns:
            Success status.
        """
        try:
            db = get_models_db()
            success = db.set_bookmark(model_id, bookmarked)

            if not success:
                return JSONResponse(
                    {"success": False, "error": "Model not found"},
                    status_code=404
                )

            return JSONResponse({
                "success": True,
                "model_id": model_id,
                "is_bookmarked": bookmarked
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Bookmark error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/resolve-hash")
    async def resolve_hash(hash: str):
        """
        Resolve a model hash to Civitai version info.

        Args:
            hash: Model file hash (SHA256 or AutoV2).

        Returns:
            Version info with model ID, version ID, name, and download URL.
        """
        try:
            if not hash or len(hash) < 10:
                return JSONResponse(
                    {"success": False, "error": "Invalid hash"},
                    status_code=400
                )

            client = CivitaiClient.from_settings()
            try:
                version_data = client.get_model_by_hash(hash)
            finally:
                client.close()

            if not version_data:
                return JSONResponse({
                    "success": False,
                    "error": "Not found on Civitai"
                }, status_code=404)

            version_id = version_data.get("id")
            model_id = version_data.get("modelId")
            model_name = version_data.get("model", {}).get("name", "Unknown")
            version_name = version_data.get("name", "")

            return JSONResponse({
                "success": True,
                "version_id": version_id,
                "model_id": model_id,
                "model_name": model_name,
                "version_name": version_name,
                "download_url": f"https://civitai.com/api/download/models/{version_id}" if version_id else None,
                "view_url": f"https://civitai.com/model-versions/{version_id}" if version_id else None
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Hash resolve error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    # ==================== Civitai Browser Endpoints ====================

    @app.get("/model-manager/civitai/models")
    async def civitai_search_models(
        query: str = "",
        types: str = "",          # Comma-separated: Checkpoint,LORA,etc
        base_models: str = "",    # Comma-separated: SD 1.5,SDXL,etc
        nsfw: bool = False,
        sort: str = "Most Downloaded",
        period: str = "AllTime",
        tag: str = "",
        cursor: str = "",         # Cursor for pagination (empty = first page)
        limit: int = 0,  # 0 = use setting
    ):
        """
        Search Civitai models with local ownership detection.

        Uses cursor-based pagination. Pass cursor from previous response's nextCursor.
        Returns models from Civitai with ownership indicators for locally owned versions.
        """
        try:
            from modules import shared

            # Use setting for page size if not specified
            if limit <= 0:
                limit = int(getattr(shared.opts, 'model_manager_civitai_page_size', 10))

            # Parse card size setting (format: WIDTHxHEIGHT)
            def parse_card_size(size_str: str):
                try:
                    if 'x' in size_str.lower():
                        parts = size_str.lower().split('x')
                        return int(parts[0].strip()), int(parts[1].strip())
                except (ValueError, IndexError):
                    pass
                return 200, 280  # Default

            card_size_str = getattr(shared.opts, 'model_manager_civitai_card_size', '200x280')
            card_width, card_height = parse_card_size(card_size_str)

            # Parse comma-separated values
            type_list = [t.strip() for t in types.split(",") if t.strip()] if types else None
            base_model_list = [b.strip() for b in base_models.split(",") if b.strip()] if base_models else None

            # Search Civitai
            client = CivitaiClient.from_settings()
            try:
                result = client.search_models(
                    query=query,
                    types=type_list,
                    base_models=base_model_list,
                    sort=sort,
                    period=period,
                    nsfw=nsfw,
                    tag=tag,
                    limit=limit,
                    cursor=cursor if cursor else None
                )
            finally:
                client.close()

            items = result.get("items", [])
            next_cursor = result.get("nextCursor")

            # Get local ownership info
            db = get_models_db()

            # Collect all model_ids and version_ids from results
            model_ids = set()
            version_ids = set()
            for model in items:
                model_ids.add(model.get("id"))
                for version in model.get("modelVersions", []):
                    version_ids.add(version.get("id"))

            # Query local database for owned versions
            owned_versions = set()
            owned_models = set()

            if model_ids or version_ids:
                # Query versions table for matches
                with db._cursor() as db_cursor:
                    # Check by model_id
                    if model_ids:
                        placeholders = ",".join("?" * len(model_ids))
                        db_cursor.execute(f"""
                            SELECT DISTINCT model_id, id FROM model_versions
                            WHERE model_id IN ({placeholders})
                        """, list(model_ids))
                        for row in db_cursor.fetchall():
                            owned_models.add(row["model_id"])
                            owned_versions.add(row["id"])

                    # Check by version_id
                    if version_ids:
                        placeholders = ",".join("?" * len(version_ids))
                        db_cursor.execute(f"""
                            SELECT DISTINCT model_id, id FROM model_versions
                            WHERE id IN ({placeholders})
                        """, list(version_ids))
                        for row in db_cursor.fetchall():
                            owned_models.add(row["model_id"])
                            owned_versions.add(row["id"])

            # Attach ownership info to each model and version
            for model in items:
                model_id = model.get("id")
                model["owned_locally"] = model_id in owned_models
                model["owned_versions"] = [
                    v.get("id") for v in model.get("modelVersions", [])
                    if v.get("id") in owned_versions
                ]
                # Mark each version with ownership
                for version in model.get("modelVersions", []):
                    version["owned_locally"] = version.get("id") in owned_versions

            return JSONResponse({
                "success": True,
                "models": items,
                "nextCursor": next_cursor,
                "pageSize": limit,
                "cardWidth": card_width,
                "cardHeight": card_height
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Civitai search error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/civitai/models/{model_id}")
    async def civitai_get_model(model_id: int):
        """
        Get full model details from Civitai with local ownership status.
        """
        try:
            client = CivitaiClient.from_settings()
            try:
                model = client.get_model(model_id)
            finally:
                client.close()

            if not model:
                return JSONResponse(
                    {"success": False, "error": "Model not found"},
                    status_code=404
                )

            # Get local ownership info
            db = get_models_db()
            version_ids = [v.get("id") for v in model.get("modelVersions", [])]

            owned_versions = set()
            if version_ids:
                with db._cursor() as cursor:
                    placeholders = ",".join("?" * len(version_ids))
                    cursor.execute(f"""
                        SELECT id FROM model_versions
                        WHERE id IN ({placeholders})
                    """, version_ids)
                    owned_versions = {row["id"] for row in cursor.fetchall()}

            model["owned_locally"] = len(owned_versions) > 0
            model["owned_versions"] = list(owned_versions)

            # Mark each version with ownership
            for version in model.get("modelVersions", []):
                version["owned_locally"] = version.get("id") in owned_versions

            return JSONResponse({
                "success": True,
                "model": model
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Civitai get model error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/civitai/versions/{version_id}/images")
    async def civitai_get_version_images(
        version_id: int,
        model_id: int = 0,
        use_cache: bool = True
    ):
        """
        Get images for a Civitai version with caching.

        First checks cache, then fetches from Civitai if needed.
        """
        try:
            db = get_models_db()

            # Check cache first
            if use_cache:
                cached_images = db.get_cached_browse_images(version_id)
                cached_cursor = db.get_browse_cursor(version_id)

                if cached_images:
                    return JSONResponse({
                        "success": True,
                        "images": cached_images,
                        "next_cursor": cached_cursor,
                        "from_cache": True,
                        "cached_count": len(cached_images)
                    })

            # Fetch from Civitai (first batch)
            client = CivitaiClient.from_settings()
            try:
                result = client.get_model_images(version_id, cursor=None, limit=10)
            finally:
                client.close()

            images = result.get("images", [])
            next_cursor = result.get("next_cursor")

            # Cache images
            if images:
                db.store_browse_images(model_id, version_id, images)
                if next_cursor:
                    db.store_browse_cursor(model_id, version_id, next_cursor)

            return JSONResponse({
                "success": True,
                "images": images,
                "next_cursor": next_cursor,
                "from_cache": False,
                "fetched_count": len(images)
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Civitai images error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.post("/model-manager/civitai/versions/{version_id}/images/load-more")
    async def civitai_load_more_images(version_id: int, model_id: int = Form(...)):
        """
        Load more images for a Civitai version using cached cursor.
        """
        try:
            db = get_models_db()

            # Get cached cursor
            cursor = db.get_browse_cursor(version_id)

            if not cursor:
                return JSONResponse({
                    "success": True,
                    "images": [],
                    "next_cursor": None,
                    "message": "No more images (no cursor)"
                })

            # Fetch from Civitai
            client = CivitaiClient.from_settings()
            try:
                result = client.get_model_images(version_id, cursor=cursor, limit=10)
            finally:
                client.close()

            images = result.get("images", [])
            next_cursor = result.get("next_cursor")

            # Store new images and update cursor
            if images:
                db.store_browse_images(model_id, version_id, images)

            if next_cursor:
                db.store_browse_cursor(model_id, version_id, next_cursor)
            else:
                # Clear cursor to indicate no more images
                db.store_browse_cursor(model_id, version_id, "")

            return JSONResponse({
                "success": True,
                "images": images,
                "next_cursor": next_cursor,
                "fetched_count": len(images)
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Civitai load more error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/civitai/versions/{version_id}/images/cached")
    async def civitai_get_cached_images(version_id: int):
        """
        Get only cached images for a version (no API call).
        """
        try:
            db = get_models_db()

            images = db.get_cached_browse_images(version_id)
            cursor = db.get_browse_cursor(version_id)

            return JSONResponse({
                "success": True,
                "images": images,
                "next_cursor": cursor if cursor else None,
                "cached_count": len(images)
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Civitai cached images error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.post("/model-manager/civitai/download")
    async def civitai_download_model(
        version_id: int = Form(...),
        model_id: int = Form(...),
        file_index: int = Form(default=0)
    ):
        """
        Start downloading a model version from Civitai.

        Requires model_id and version_id. Fetches full model/version data
        then queues the download.
        """
        try:
            from .download_service import get_download_service

            # Fetch model and version data from Civitai
            client = CivitaiClient.from_settings()
            try:
                model_data = client.get_model(model_id)
            finally:
                client.close()

            if not model_data:
                return JSONResponse(
                    {"success": False, "error": "Model not found on Civitai"},
                    status_code=404
                )

            # Find the requested version
            version_data = None
            for v in model_data.get("modelVersions", []):
                if v.get("id") == version_id:
                    version_data = v
                    break

            if not version_data:
                return JSONResponse(
                    {"success": False, "error": "Version not found"},
                    status_code=404
                )

            # Queue download
            service = get_download_service()
            progress = service.queue_download(
                version_id=version_id,
                model_data=model_data,
                version_data=version_data,
                file_index=file_index
            )

            return JSONResponse({
                "success": True,
                "message": "Download queued",
                "progress": progress.to_dict()
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Civitai download error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/civitai/download/progress")
    async def civitai_download_progress(version_id: Optional[int] = None):
        """
        Get download progress for one or all downloads.
        """
        try:
            from .download_service import get_download_service

            service = get_download_service()

            if version_id:
                progress = service.get_progress(version_id)
                if not progress:
                    return JSONResponse({
                        "success": True,
                        "progress": None,
                        "message": "No download found for this version"
                    })
                return JSONResponse({
                    "success": True,
                    "progress": progress.to_dict()
                })
            else:
                all_progress = service.get_all_progress()
                return JSONResponse({
                    "success": True,
                    "downloads": all_progress
                })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Download progress error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.post("/model-manager/civitai/download/cancel")
    async def civitai_cancel_download(version_id: int = Form(default=0)):
        """
        Cancel a download. If version_id=0, cancels all downloads.
        """
        try:
            from .download_service import get_download_service

            service = get_download_service()

            if version_id:
                service.cancel(version_id)
                return JSONResponse({
                    "success": True,
                    "message": f"Cancelled download for version {version_id}"
                })
            else:
                service.cancel_all()
                return JSONResponse({
                    "success": True,
                    "message": "Cancelled all downloads"
                })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Cancel download error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/civitai/tags")
    async def civitai_search_tags(
        query: str = "",
        limit: int = 20,
    ):
        """
        Search Civitai tags for autocomplete.

        Args:
            query: Search text to filter tags.
            limit: Max results to return (default 20).

        Returns:
            List of tag names matching the query.
        """
        try:
            # Don't search if query is too short
            if len(query) < 3:
                return JSONResponse({
                    "success": True,
                    "tags": []
                })

            client = CivitaiClient.from_settings()
            try:
                result = client.search_tags(query=query, limit=limit)
            finally:
                client.close()

            # Extract just the tag names
            tags = [tag.get("name") for tag in result.get("items", []) if tag.get("name")]

            return JSONResponse({
                "success": True,
                "tags": tags
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Tags search error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e), "tags": []},
                status_code=500
            )

    print("[ModelManager] API endpoints registered")


# Register API on app start
def on_app_started(demo, app):
    print(f"[ModelManager] on_app_started called with app: {app}")
    setup_api(app)


print("[ModelManager] Registering on_app_started callback...")
script_callbacks.on_app_started(on_app_started)
print("[ModelManager] on_app_started callback registered")
