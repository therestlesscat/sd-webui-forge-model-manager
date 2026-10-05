"""
Work that takes long enough to need watching.

Syncing with Civitai - a force sync, which hashes, or one that refreshes by id,
each after a walk of the library - starts on a background thread and reports
progress until it finishes or is cancelled. Which job runs, and how far along
it is, is model_manager.jobs': both are the "sync", one at a time.
"""
from typing import Any, Optional
from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

from ..db import get_models_db
from ..jobs import jobs
from ..model_dirs import misplaced_files
from ..sync_estimates import (estimate_metadata_sync, files_to_hash, gallery_refresh_options,
                              sync_window_counts, window_cutoff)
from ..sync_service import SyncService
from .common import failed
from .. import console
from ..console import say

#: What progress and cancel answer before a job of the kind has run.
NOT_STARTED = {"sync": "No sync in progress"}


def _start(kind: str, make, run, started: str) -> JSONResponse:
    if not jobs.start(kind, make, run):
        return JSONResponse({"success": False, "error": f"{kind.capitalize()} already in progress"},
                            status_code=409)
    return JSONResponse({"success": True, "message": started})


def _progress_body(kind: str) -> dict:
    progress = jobs.progress(kind)
    if progress is None:
        return {"success": True, "progress": None, "message": NOT_STARTED[kind]}
    return {"success": True, "progress": progress.to_dict()}


def _progress(kind: str) -> JSONResponse:
    return JSONResponse(_progress_body(kind))


def _cancel(kind: str) -> JSONResponse:
    if not jobs.cancel(kind):
        return JSONResponse({"success": False, "error": NOT_STARTED[kind]})
    return JSONResponse({"success": True, "message": "Cancel requested"})


def _yes(value: Any) -> bool:
    """A form's "true" - it sends strings."""
    return str(value).lower() in ("true", "1", "yes")


def register(app: FastAPI):
    """Attach this module's endpoints to the app."""
    @app.post("/model-manager/sync")
    async def start_sync(
        force: str = Form(default="false"),  # Form data comes as string
        targets: str = Form(default="all"),
        paths: str = Form(default=""),  # Comma-separated paths, empty = all models
        keep_image_count: str = Form(default="false"),
        reread_headers: str = Form(default="false"),
        move_misplaced: str = Form(default="false"),
    ):
        """
        Start syncing models with Civitai, identifying each file by its hash.

        Args:
            force: Re-sync even if civitai data exists ("true" or "false").
            targets: "all", "identified", or "unidentified" - which of the
                files on disk to work on. Anything but "all" implies force,
                since picking a set is the point of asking.
            paths: Comma-separated model paths, or empty for all.
            keep_image_count: "true" to refetch as many images as each
                gallery has stored, rather than its first page (#103).
            reread_headers: "true" to read every file's header again in the
                walk the sync starts with, not only new or changed files.
            move_misplaced: "true" to move each file in another type's
                folder into its own (see /model-manager/sync/misplaced). Only
                ever asked for by its own box in the dialog.

        Returns immediately. Poll /model-manager/sync/progress for status.
        """
        # Parse force as boolean (form data sends strings)
        target_set = targets if targets in ("all", "identified", "unidentified") else "all"
        # Choosing a set is itself a request to re-read them, so it forces.
        force_bool = (str(force).lower() in ('true', '1', 'yes')
                      or target_set != "all")
        say(f"Sync requested: targets={target_set} force={force_bool}")

        model_paths = None
        if paths:
            model_paths = [p.strip() for p in paths.split(",") if p.strip()]

        return _start("sync", SyncService,
                      lambda sync: sync.sync_all(model_paths=model_paths, force=force_bool,
                                                 targets=target_set,
                                                 keep_image_count=_yes(keep_image_count),
                                                 reread_headers=_yes(reread_headers),
                                                 move_misplaced=_yes(move_misplaced)),
                      "Sync started")

    @app.post("/model-manager/sync/metadata")
    async def start_metadata_sync(
        include_images: str = Form(default="false"),
        include_prompts: str = Form(default="true"),
        stale_days: int = Form(default=0),
        downloaded_days: int = Form(default=0),
        paths: str = Form(default=""),  # Comma-separated paths, empty = all models
        keep_image_count: str = Form(default="false"),
        reread_headers: str = Form(default="false"),
        move_misplaced: str = Form(default="false"),
    ):
        """
        Refresh Civitai data for models that already resolve, without hashing.

        /model-manager/sync identifies files: it reads every byte to hash them
        and asks Civitai what they are. Once that has happened the answer is
        stored, so refreshing descriptions, tags, stats and licences needs only
        the ids we hold - fetched a hundred models per request.

        Args:
            include_images: Also refetch each version's gallery ("true"/"false").
            include_prompts: Look up the generation data behind those images.
                It costs a request per thirty images, which is most of a full
                sync, so the dialog lets it be left out.
            stale_days: Only models last refreshed longer ago than this many
                days. 0 means every model, however recently it was refreshed.
            downloaded_days: Only versions downloaded within this many days.
                0 means every version, however long ago it arrived.
            paths: Comma-separated model paths, or empty for all.
            keep_image_count: With images, "true" to refetch as many as each
                gallery has stored, rather than its first page (#103).
            reread_headers, move_misplaced: the walk's, as /model-manager/sync.

        It starts with a walk of the library, and ends identifying the files
        Civitai has never been asked about (SyncService.sync_metadata).
        Shares the progress and cancel endpoints with the full sync. Returns
        immediately; poll /model-manager/sync/progress.
        """
        with_images = str(include_images).lower() in ('true', '1', 'yes')
        with_prompts = str(include_prompts).lower() in ('true', '1', 'yes')
        synced_before = window_cutoff(stale_days) if stale_days > 0 else None
        downloaded_after = window_cutoff(downloaded_days) if downloaded_days > 0 else None

        model_paths = None
        if paths:
            model_paths = [p.strip() for p in paths.split(",") if p.strip()]

        return _start("sync", SyncService,
                      lambda sync: sync.sync_metadata(model_paths=model_paths,
                                                      include_images=with_images,
                                                      include_prompts=with_prompts,
                                                      synced_before=synced_before,
                                                      downloaded_after=downloaded_after,
                                                      keep_image_count=_yes(keep_image_count),
                                                      reread_headers=_yes(reread_headers),
                                                      move_misplaced=_yes(move_misplaced)),
                      "Metadata sync started" + (" (with images)" if with_images else ""))

    @app.get("/model-manager/sync/estimate")
    def get_sync_estimate(
        include_images: str = "false",
        include_prompts: str = "true",
        stale_days: int = 0,
        downloaded_days: int = 0,
        paths: str = "",
        keep_image_count: str = "false",
        force_mode: str = "",
    ):
        """
        What a metadata sync would cost, before anyone starts one.

        The dialog asks for this as its controls change, so the choice between
        "metadata only" and "with images and prompts" is made against minutes
        and requests rather than against a guess. Counts come out of the same
        code that does the batching, so they cannot drift from it.

        Returns the estimate for the current selection, plus how many versions
        each staleness window would take - the numbers shown beside them.
        `force_mode` - all, identified, unidentified - costs a force sync's
        galleries instead (`force_images`): its files are counted, not its
        requests, but either way of refetching the images is (#103).
        """
        try:
            with_images = str(include_images).lower() in ('true', '1', 'yes')
            with_prompts = str(include_prompts).lower() in ('true', '1', 'yes')
            model_paths = [p.strip() for p in paths.split(",") if p.strip()] if paths else None

            estimate = estimate_metadata_sync(
                model_paths=model_paths,
                synced_before=window_cutoff(stale_days) if stale_days > 0 else None,
                downloaded_after=window_cutoff(downloaded_days) if downloaded_days > 0 else None,
                include_images=with_images,
                include_prompts=with_prompts,
                keep_image_count=_yes(keep_image_count),
            )
            unidentified = get_models_db().count_unidentified()
            force_images = None
            if force_mode in ("all", "identified", "unidentified"):
                db = get_models_db()
                ids = ([v["id"] for v in db.get_linked_versions() if v.get("id")]
                       if force_mode != "unidentified" else [])
                force_images = gallery_refresh_options(db, ids, include_prompts=False)
                # A file not identified yet has no gallery stored: its first
                # page, either way.
                extra = unidentified.get("unidentified", 0) if force_mode != "identified" else 0
                for option in ("first", "kept"):
                    force_images[option]["requests"] += extra
            return JSONResponse({
                "success": True,
                "estimate": estimate,
                "windows": sync_window_counts(model_paths),
                "download_windows": sync_window_counts(model_paths, basis="downloaded"),
                # For the hashing option, which is costed in files rather than
                # in requests. From the database, so the estimate, asked at
                # every change, does not walk the disk: /sync/new-files does,
                # once per opening.
                "unidentified": unidentified,
                "force_images": force_images,
            })
        except Exception as e:
            return failed(e)

    @app.get("/model-manager/sync/new-files")
    def get_files_to_hash():
        """
        The files every sync will read in full, and their total size: new on
        disk, or never asked about. Asked once each time the dialog opens -
        a walk of the folders, which the estimate, asked at every change,
        does not make.
        """
        try:
            return JSONResponse({"success": True, **files_to_hash()})
        except Exception as e:
            return failed(e)

    @app.get("/model-manager/sync/misplaced")
    def get_sync_misplaced():
        """The files in another type's folder, for the sync dialog to show before it moves any."""
        try:
            return JSONResponse({"success": True, "files": misplaced_files(get_models_db())})
        except Exception as e:
            return failed(e)

    @app.get("/model-manager/sync/progress")
    async def get_sync_progress(since: Optional[int] = None):
        """
        Get current sync progress - and, with `since`, the console's lines
        said after that one (`log`), and the number to ask from next
        (`log_next`): what the sync's log panel shows. -1 asks from where the
        sync began (the progress's `log_from`).
        """
        body = _progress_body("sync")
        if since is not None:
            # -1: from where this sync began - a page that has read none yet.
            if since < 0:
                since = (body["progress"] or {}).get("log_from", console.said())
            body["log"], body["log_next"] = console.since(since)
        return JSONResponse(body)

    @app.post("/model-manager/sync/cancel")
    async def cancel_sync():
        """Cancel active sync operation."""
        return _cancel("sync")
