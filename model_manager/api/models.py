"""
What the Model Manager grid asks about models.

Listing and filtering them, opening one, its versions, the values its filters
offer, bookmarking, deleting, and resolving a hash to a model. Anything that
answers "which models do I have, and what is this one".
"""
import time
from typing import Optional
from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

from ..db import get_models_db
from ..nsfw import NAME_TO_LEVEL, SFW_MAX
from ..sync_service import SyncService
from ..civitai import CivitaiClient


# The most resource hashes /resolve-hashes asks Civitai about in one request.
# Each is its own request with no batch endpoint behind it, and without an API
# key the rate limit makes each one about two seconds.
MAX_HASH_LOOKUPS = 20


def register(app: FastAPI):
    """Attach this module's endpoints to the app.

    The ones that wait on Civitai, or on a sync, are plain `def`, not `async
    def`. This app is the WebUI's own, and it serves every request from one
    event loop: an async handler runs on that loop, and one that blocks in
    `requests` holds it, so every other request in the WebUI - Gradio's
    included - waits until Civitai answers. FastAPI runs a plain `def` handler
    on a worker thread instead. tests/py/loop_test.py holds this in place.
    """
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
        # "" = any, "true"/"false" = that value, "unknown" = no Civitai licence
        allow_derivatives: str = "",
        allow_different_license: str = "",
        # "", "Trained", "Merge", or "unknown" - only checkpoints have one
        checkpoint_type: str = "",
        # Return only the file paths the filters select, with no paging. The
        # sync dialog uses it to turn "these results" into a scope; it reuses
        # this endpoint so the filters cannot be parsed one way here and
        # another way there.
        paths_only: bool = False,
        sort_by: str = "downloaded_at",
        sort_order: str = "desc",
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
                page_size = int(getattr(shared.opts, 'model_manager_page_size', 20))

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
                "download_count", "published_at",
                # offered by the sort dropdown; without these they silently
                # fell through to sorting by name
                "downloaded_at", "scanned_at", "updated_at",
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
                    if name in NAME_TO_LEVEL:
                        nsfw_level_ints.append(NAME_TO_LEVEL[name])
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
                allow_derivatives=allow_derivatives or None,
                allow_different_license=allow_different_license or None,
                checkpoint_type=checkpoint_type or None,
                sort_by=db_sort_by,
                sort_order=sort_order,
                limit=1000000 if paths_only else page_size,
                offset=0 if paths_only else offset,
                preview_least_nsfw=preview_least_nsfw
            )

            if paths_only:
                # Grouped rows carry one version each; a sync works on models,
                # so every local version of a matched model belongs in scope.
                model_ids = {m["model_id"] for m in models if m.get("model_id")}
                paths = {m["file_path"] for m in models if m.get("file_path")}
                for version in db.get_linked_versions():
                    if version["model_id"] in model_ids:
                        paths.add(version["file_path"])
                return JSONResponse({
                    "success": True,
                    "paths": sorted(paths),
                    "models": total_count,
                })
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

            def parse_card_size(size_str: str):
                try:
                    if 'x' in size_str.lower():
                        parts = size_str.lower().split('x')
                        return int(parts[0].strip()), int(parts[1].strip())
                except (ValueError, IndexError):
                    pass
                return 200, 280

            card_size_str = getattr(shared.opts, 'model_manager_card_size', '200x280')
            card_width, card_height = parse_card_size(card_size_str)
            page_size = int(getattr(shared.opts, 'model_manager_page_size', 20))

            return JSONResponse({
                "success": True,
                "preview_least_nsfw": getattr(shared.opts, 'model_manager_preview_least_nsfw', True),
                "page_size": page_size,
                "card_width": card_width,
                "card_height": card_height,
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
    async def get_model_details(path: str, hide_nsfw_images: Optional[bool] = None,
                                hide_promptless_images: Optional[bool] = None):
        """Get detailed info for a specific model by file path."""
        try:
            from ..storage import load_model_metadata
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
                            "thumbs_up": db_model.get("stats_thumbs_up", 0),
                            "thumbs_down": db_model.get("stats_thumbs_down", 0),
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
                if hide_promptless_images is None:
                    hide_promptless_images = getattr(
                        shared.opts, 'model_manager_hide_promptless_images', True)

                max_nsfw_level = SFW_MAX if hide_nsfw_images else None

                images = db.get_all_images_for_version(
                    version_id, max_nsfw_level=max_nsfw_level,
                    require_prompt=hide_promptless_images)
                image_counts = db.get_image_counts(
                    version_id, max_nsfw_level=max_nsfw_level,
                    require_prompt=hide_promptless_images)

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
                    "hidden_nsfw": image_counts["hidden_nsfw"],
                    "hidden_promptless": image_counts["hidden_promptless"],
                    "nsfw_count": image_counts["nsfw_count"],
                    "promptless_count": image_counts["promptless_count"],
                    "hide_nsfw_images": hide_nsfw_images,
                    "hide_promptless_images": hide_promptless_images,
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
    def force_sync_model(model_id: int = Form(...)):
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
            # Only ever a file the library itself recorded. This used to delete
            # whatever path it was sent - plus its .png/.jpg/.civitai.info
            # siblings - and the request is a plain form POST, so another page
            # or a script in this one could name any file the WebUI can write.
            # The UI only sends paths it read from the database, so it cannot
            # tell the difference. Checked before touching the disk, so this is
            # not a way to ask whether an arbitrary file exists either.
            if not get_models_db().get_version(path):
                return JSONResponse(
                    {"success": False, "error": "Not a model in the library"},
                    status_code=403
                )

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
                from ..storage import read_civitai_info
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

    @app.post("/model-manager/resolve-hashes")
    def resolve_hashes(hashes: str = Form(default="")):
        """
        Resolve several resource hashes at once, for the resources panel.

        An image names its resources twice - Civitai's list, which carries
        modelVersionId, and the legacy infotext list, which carries an AutoV2
        hash. The two share no key, so merging them exactly means turning the
        hashes into version ids.

        Answered from three places in order, cheapest first: this library's own
        rows, where a version id and an AutoV2 hash already sit together; what
        a previous lookup recorded; and finally Civitai, one request per hash,
        because it has no batch endpoint for them. Everything Civitai says is
        written down, including that it has never heard of a hash, so the same
        dead hash is not asked about again.

        Args:
            hashes: Comma-separated AutoV2 hashes.

        Returns:
            resolved: hash -> {version_id, model_id, name, version_name,
                model_type, view_url, download_url}. A hash Civitai does not
                know is present with a null version_id, so the caller can tell
                "unknown" from "not asked".
            deferred: hashes not asked about this time, past MAX_HASH_LOOKUPS.
                Send them again for the rest.
        """
        try:
            wanted = []
            for value in (hashes or "").split(","):
                value = value.strip().lower()
                if value and value not in wanted:
                    wanted.append(value)

            if not wanted:
                return JSONResponse({"success": True, "resolved": {}, "deferred": []})

            db = get_models_db()
            known = db.hashes_from_local_models(wanted)
            known.update({k: v for k, v in db.resolved_hashes(wanted).items()
                          if k not in known})

            # Civitai is asked about at most MAX_HASH_LOOKUPS of them per
            # request; anything past that comes back as `deferred`, to be asked
            # again. Answers from the library or the cache are free and never
            # deferred, so a big image whose hashes are mostly known still
            # resolves in one go. Without an API key a lookup is two seconds,
            # so an uncapped request for one image's 234 hashes took minutes
            # with nothing to show for it until the end.
            missing = [h for h in wanted if h not in known]
            deferred = missing[MAX_HASH_LOOKUPS:]
            missing = missing[:MAX_HASH_LOOKUPS]
            if missing:
                client = CivitaiClient.from_settings()
                try:
                    for value in missing:
                        try:
                            version = client.get_model_by_hash(value)
                        except Exception as e:
                            # One hash failing must not lose the rest; leave it
                            # unresolved rather than recording a wrong answer.
                            print(f"[ModelManager] Resolve {value} failed: {e}")
                            continue
                        db.remember_hash(value, version)
                        model = (version or {}).get("model") or {}
                        known[value] = {
                            "hash": value,
                            "version_id": (version or {}).get("id"),
                            "model_id": (version or {}).get("modelId"),
                            "name": model.get("name"),
                            "version_name": (version or {}).get("name"),
                            "model_type": model.get("type"),
                        }
                finally:
                    client.close()

            resolved = {}
            for value, row in known.items():
                version_id = row.get("version_id")
                resolved[value] = {
                    "version_id": version_id,
                    "model_id": row.get("model_id"),
                    "name": row.get("name"),
                    "version_name": row.get("version_name"),
                    "model_type": row.get("model_type"),
                    "view_url": f"https://civitai.com/model-versions/{version_id}" if version_id else None,
                    "download_url": f"https://civitai.com/api/download/models/{version_id}" if version_id else None,
                }

            return JSONResponse({"success": True, "resolved": resolved,
                                 "deferred": deferred})

        except Exception as e:
            import traceback
            print(f"[ModelManager] Resolve hashes error: {e}")
            traceback.print_exc()
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/resolve-hash")
    def resolve_hash(hash: str):
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
