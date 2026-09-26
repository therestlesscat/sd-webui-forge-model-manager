"""
Standing between the browser and Civitai.

Searching, streaming results as they qualify, fetching a model, its images,
downloading a file, tags, and the enum lists the filters are built from.

Nothing here touches the local library except to mark what is already owned.
"""
import json
import threading
import time
from typing import Dict, List, Optional
from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse, StreamingResponse

from ..db import get_models_db
from ..civitai import (
    CivitaiClient,
    decode_filter_token,
    enrich_images_with_generation_data,
    iter_models_with_usable_prompts,
    search_models_with_usable_prompts,
    size_range_check,
)
from .annotations import annotate_local_ownership, annotate_paid_access
from .prompts import PROMPT_CHECK_WORKERS, inspect_model

# Cached Civitai enums (model types, base models). They change only when
# Civitai ships a new base model, and the browser asks for them on every tab
# load, so serve them from memory and refresh a few times a day.
_enums_cache: Optional[Dict[str, List[str]]] = None
_enums_cached_at: float = 0.0
_enums_lock = threading.Lock()
ENUMS_TTL_SECONDS = 6 * 60 * 60

# A filtered page is filled from as many searches as it takes, up to this
# many. Only the size filter can need them: its check is free, so a narrow
# range over a broad search is bounded by the search calls, not the checks.
MAX_FILTER_SEARCHES = 5
# Civitai's largest search page. The size filter asks for the most it can
# per call, since each call is the whole cost of checking a batch.
SIZE_FILTER_BATCH = 100


def _filter_options(client, db, *, require_prompt, sfw_only, nsfw, size_check,
                    limit, min_usable, fill_page=False):
    """
    The filter loop's arguments for the filters asked for.

    "Only Show Models with SFW images" means nothing once NSFW models are included, so it
    is ignored then, whatever the request says - the browser greys it out,
    and this is the same rule on the server's side.

    A filter that checks models one at a time stops a page on a 429 rather
    than sitting out Retry-After: most models fail the SFW check, so it makes
    the most requests of anything here, and a page it cuts short can be
    resumed.

    `fill_page` is the "Fill every page" setting. It lifts the per-page limits
    on checks and searches while the SFW check is on, so a page runs until it
    is full or Civitai has no more to give. The 429 stop above still applies,
    and is then the only thing that ends a page early.

    Returns:
        (whether the SFW check is on, the loop's keyword arguments)
    """
    sfw = bool(sfw_only and not nsfw)
    costly = require_prompt or sfw
    if costly:
        client.wait_on_rate_limit = False

    inspect = (
        (lambda m: inspect_model(client, db, m, want_prompts=require_prompt,
                                 want_sfw=sfw, min_usable=min_usable))
        if costly else None
    )
    unbounded = sfw and fill_page
    return sfw, dict(
        inspect=inspect,
        page_size=limit,
        max_checks=None if unbounded else max(limit * 4, 20),
        batch_size=max(limit * 2, 20) if costly else SIZE_FILTER_BATCH,
        workers=PROMPT_CHECK_WORKERS,
        accept=size_check,
        max_searches=None if unbounded else MAX_FILTER_SEARCHES,
    )


def _fill_page_setting() -> bool:
    """Whether "Fill every page with Only Show Models with SFW images" is on."""
    from modules import shared
    return bool(getattr(shared.opts, 'model_manager_civitai_sfw_fill_page', False))


def _filter_stats(summary, *, require_prompt, sfw, size_check, min_usable):
    """What a filtered page passed over, for the browser's status line."""
    return {
        "checked": summary["checked"],
        "dropped": summary["dropped"],
        "unsafe": summary["unsafe"],
        "failed": summary["failed"],
        "rejected": summary["rejected"],
        "promptFilter": require_prompt,
        "sfwFilter": sfw,
        "sizeFilter": size_check is not None,
        "budgetReached": summary["budget_reached"],
        "rateLimited": summary["rate_limited"],
        "minUsable": min_usable,
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
    @app.get("/model-manager/civitai/models")
    def civitai_search_models(
        query: str = "",
        types: str = "",          # Comma-separated: Checkpoint,LORA,etc
        base_models: str = "",    # Comma-separated: SD 1.5,SDXL,etc
        nsfw: bool = False,
        sort: str = "Most Downloaded",
        period: str = "AllTime",
        tag: str = "",
        checkpoint_type: str = "",  # Trained or Merge; checkpoints only
        cursor: str = "",         # Cursor for pagination (empty = first page)
        require_prompt: bool = False,  # Only models with usable-prompt images
        sfw_only: bool = False,   # Only models whose first images are all SFW
        min_size_gb: float = 0,   # Latest version's primary file; 0 = no bound
        max_size_gb: float = 0,
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
                limit = int(getattr(shared.opts, 'model_manager_civitai_page_size', 20))

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

            search_params = dict(
                query=query,
                types=type_list,
                base_models=base_model_list,
                sort=sort,
                period=period,
                nsfw=nsfw,
                tag=tag,
                checkpoint_type=checkpoint_type,
            )

            # Search Civitai
            client = CivitaiClient.from_settings()
            filter_stats = None
            size_check = size_range_check(min_size_gb, max_size_gb)
            try:
                min_usable = max(int(getattr(
                    shared.opts, 'model_manager_civitai_min_prompt_images', 1)), 1)
                sfw, options = _filter_options(
                    client, get_models_db(), require_prompt=require_prompt,
                    sfw_only=sfw_only, nsfw=nsfw, size_check=size_check,
                    limit=limit, min_usable=min_usable,
                    fill_page=_fill_page_setting())

                if require_prompt or sfw or size_check:
                    # Civitai can filter on none of these, so models are
                    # checked locally and the page is filled from what
                    # survives.
                    filtered = search_models_with_usable_prompts(
                        client, search_params, None,
                        start_token=cursor if cursor else None,
                        **options,
                    )
                    items = filtered["models"]
                    next_cursor = filtered["nextCursor"]
                    filter_stats = _filter_stats(
                        filtered, require_prompt=require_prompt, sfw=sfw,
                        size_check=size_check, min_usable=min_usable)
                else:
                    # Un-ticking the filter mid-listing can hand us a filter
                    # token; Civitai would reject it, so unwrap the real cursor
                    plain_cursor, _ = decode_filter_token(cursor if cursor else None)
                    result = client.search_models(
                        **search_params,
                        limit=limit,
                        cursor=plain_cursor
                    )
                    items = result.get("items", [])
                    next_cursor = result.get("nextCursor")
            finally:
                client.close()

            # Get local ownership info
            db = get_models_db()
            annotate_local_ownership(db, items)
            annotate_paid_access(items)

            return JSONResponse({
                "success": True,
                "models": items,
                "nextCursor": next_cursor,
                "pageSize": limit,
                "cardWidth": card_width,
                "cardHeight": card_height,
                "filterStats": filter_stats,
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Civitai search error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500
            )

    @app.get("/model-manager/civitai/models/stream")
    async def civitai_search_models_stream(
        query: str = "",
        types: str = "",
        base_models: str = "",
        nsfw: bool = False,
        sort: str = "Most Downloaded",
        period: str = "AllTime",
        tag: str = "",
        checkpoint_type: str = "",
        cursor: str = "",
        require_prompt: bool = True,
        sfw_only: bool = False,
        min_size_gb: float = 0,
        max_size_gb: float = 0,
        limit: int = 0,
    ):
        """
        Search Civitai with the usable-prompt or size filter, streaming results.

        A filtered page can take a while to fill: prompt checks cost API calls,
        and a narrow size range can take several searches.
        This emits newline-delimited JSON as the work happens, letting the UI
        show each model the moment it qualifies instead of waiting for the
        whole page:

            {"type": "meta",     ...}                 once, first
            {"type": "progress", "checked", ...}      periodically
            {"type": "model",    "model": {...}}      per qualifying model
            {"type": "done",     "nextCursor", ...}   once, last
            {"type": "error",    "error": "..."}      on failure

        Results and paging are identical to the non-streaming endpoint.
        """
        from modules import shared

        if limit <= 0:
            limit = int(getattr(shared.opts, 'model_manager_civitai_page_size', 20))

        def parse_card_size(size_str: str):
            try:
                if 'x' in size_str.lower():
                    parts = size_str.lower().split('x')
                    return int(parts[0].strip()), int(parts[1].strip())
            except (ValueError, IndexError):
                pass
            return 200, 280

        card_width, card_height = parse_card_size(
            getattr(shared.opts, 'model_manager_civitai_card_size', '200x280'))

        search_params = dict(
            query=query,
            types=[t.strip() for t in types.split(",") if t.strip()] if types else None,
            base_models=[b.strip() for b in base_models.split(",") if b.strip()] if base_models else None,
            sort=sort,
            period=period,
            nsfw=nsfw,
            tag=tag,
            checkpoint_type=checkpoint_type,
        )
        min_usable = max(int(getattr(
            shared.opts, 'model_manager_civitai_min_prompt_images', 1)), 1)
        size_check = size_range_check(min_size_gb, max_size_gb)

        def generate():
            client = CivitaiClient.from_settings()
            db = get_models_db()
            try:
                yield json.dumps({
                    "type": "meta",
                    "pageSize": limit,
                    "cardWidth": card_width,
                    "cardHeight": card_height,
                    "minUsable": min_usable,
                }) + "\n"

                sfw, options = _filter_options(
                    client, db, require_prompt=require_prompt, sfw_only=sfw_only,
                    nsfw=nsfw, size_check=size_check, limit=limit,
                    min_usable=min_usable, fill_page=_fill_page_setting())

                for kind, payload in iter_models_with_usable_prompts(
                    client, search_params, None,
                    start_token=cursor if cursor else None,
                    **options,
                ):
                    if kind == "model":
                        annotate_local_ownership(db, [payload])
                        annotate_paid_access([payload])
                        yield json.dumps({"type": "model", "model": payload}) + "\n"
                    elif kind == "progress":
                        yield json.dumps({"type": "progress", **payload}) + "\n"
                    elif kind == "done":
                        yield json.dumps({
                            "type": "done",
                            "nextCursor": payload["nextCursor"],
                            "filterStats": _filter_stats(
                                payload, require_prompt=require_prompt, sfw=sfw,
                                size_check=size_check, min_usable=min_usable),
                        }) + "\n"

            except Exception as e:
                import traceback
                print(f"[ModelManager] Civitai stream error: {e}")
                traceback.print_exc()
                yield json.dumps({"type": "error", "error": str(e)}) + "\n"
            finally:
                client.close()

        return StreamingResponse(
            generate(),
            media_type="application/x-ndjson",
            # proxies and buffering layers would otherwise hold the whole
            # response back, defeating the point of streaming
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/model-manager/civitai/models/{model_id}")
    def civitai_get_model(model_id: int):
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

            annotate_paid_access([model])

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
    def civitai_get_version_images(
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
                    # Rows cached while the API returned `meta: null` have no
                    # prompt - backfill them now that we can fetch it again.
                    needs_backfill = any(
                        not (img.get("meta") or {}).get("prompt") for img in cached_images
                    )

                    if needs_backfill:
                        client = CivitaiClient.from_settings()
                        try:
                            enriched = enrich_images_with_generation_data(client, cached_images)
                        finally:
                            client.close()

                        if enriched:
                            db.update_browse_images(version_id, cached_images)
                            print(f"[ModelManager] Backfilled generation data for {enriched} "
                                  f"cached images (version {version_id})")

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
                images = result.get("images", [])
                # /images returns meta: null - fetch generation data separately
                enrich_images_with_generation_data(client, images)
            finally:
                client.close()

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
    def civitai_load_more_images(version_id: int, model_id: int = Form(...)):
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
                images = result.get("images", [])
                # /images returns meta: null - fetch generation data separately
                enrich_images_with_generation_data(client, images)
            finally:
                client.close()

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
    def civitai_download_model(
        version_id: int = Form(...),
        model_id: Optional[int] = Form(default=None),
        file_index: Optional[int] = Form(default=None),
        file_id: Optional[int] = Form(default=None),
        newer_if_gone: bool = Form(default=False),
    ):
        """
        Start downloading a model version from Civitai.

        Fetches full model/version data then queues the download. Without
        model_id, Civitai is asked which model the version belongs to - an
        image's resources do not always say.

        file_id names one of the version's files outright and is what the file
        picker sends; file_index picks one by position. Leave both out and the
        file Civitai marks primary is used, which is not always the first one.

        newer_if_gone is for a version an image names: uploaders delete
        versions, and the image's is then gone for good. The model's newest
        version is downloaded instead, and the answer says so. With it, a
        version this library already has is not downloaded again.

        Returns:
            progress, and version_id / version_name - the version being
            downloaded, which with newer_if_gone may not be the one asked
            for; substituted says it is not. already_installed instead of
            progress when the library has it.
        """
        try:
            from ..download_service import get_download_service

            # Fetch model and version data from Civitai
            client = CivitaiClient.from_settings()
            try:
                if not model_id:
                    version = client.get_model_version(version_id)
                    model_id = (version or {}).get("modelId")
                    if not model_id:
                        return JSONResponse(
                            {"success": False, "error": "Version not found on Civitai"},
                            status_code=404
                        )
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

            substituted = False
            if not version_data and newer_if_gone and model_data.get("modelVersions"):
                # Civitai lists a model's versions newest first.
                version_data = model_data["modelVersions"][0]
                substituted = True

            if not version_data:
                return JSONResponse(
                    {"success": False, "error": "Version not found"},
                    status_code=404
                )

            chosen = {"version_id": version_data.get("id"),
                      "version_name": version_data.get("name"),
                      "substituted": substituted}
            local = get_models_db().get_version_by_id(version_data.get("id")) if newer_if_gone else None
            if local and local.get("file_path"):
                return JSONResponse({"success": True, "already_installed": True, **chosen})

            # Queue download
            service = get_download_service()
            progress = service.queue_download(
                version_id=version_data.get("id"),
                model_data=model_data,
                version_data=version_data,
                file_index=file_index,
                file_id=file_id
            )

            return JSONResponse({
                "success": True,
                "message": "Download queued",
                "progress": progress.to_dict(),
                **chosen,
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
            from ..download_service import get_download_service

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
            from ..download_service import get_download_service

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
    def civitai_search_tags(
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

    @app.get("/model-manager/civitai/enums")
    def civitai_enums():
        """
        Model types and base models Civitai currently accepts as filters.

        Feeds the Civitai Browser's Type and Base Model dropdowns so they do not
        have to be hardcoded. Cached for ENUMS_TTL_SECONDS. On failure the
        browser keeps the static options already in the page, so a Civitai
        outage or a missing network just leaves the dropdowns as they were.
        """
        global _enums_cache, _enums_cached_at

        try:
            with _enums_lock:
                fresh = (
                    _enums_cache is not None
                    and (time.time() - _enums_cached_at) < ENUMS_TTL_SECONDS
                )
                if not fresh:
                    client = CivitaiClient.from_settings()
                    try:
                        _enums_cache = client.get_enums()
                    finally:
                        client.close()
                    _enums_cached_at = time.time()

                enums = _enums_cache or {}

            # ActiveBaseModel drops the base models Civitai has retired, which
            # is what a browse filter wants; fall back to the full list.
            base_models = enums.get("ActiveBaseModel") or enums.get("BaseModel") or []

            return JSONResponse({
                "success": True,
                "model_types": enums.get("ModelType", []),
                "base_models": base_models,
            })

        except Exception as e:
            import traceback
            print(f"[ModelManager] Enums error: {e}")
            traceback.print_exc()
            return JSONResponse(
                {"success": False, "error": str(e), "model_types": [], "base_models": []},
                status_code=500
            )
