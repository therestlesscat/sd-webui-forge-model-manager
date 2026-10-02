"""
Work that takes long enough to need watching.

Scanning the disk, syncing with Civitai, refreshing metadata - each starts on
a background thread and reports progress until it finishes or is cancelled.
Which job runs, and how far along it is, is model_manager.jobs': a full sync
and a metadata sync are both the "sync", one at a time, beside one "scan".
"""
from typing import Optional
from fastapi import Body, FastAPI, Form
from fastapi.responses import JSONResponse

from ..db import get_models_db
from ..jobs import jobs
from ..scan_service import ScanService, misplaced_files
from ..sync_service import (
    SyncService,
    estimate_metadata_sync,
    sync_window_counts,
    window_cutoff,
)
from .common import failed

#: What progress and cancel answer before a job of the kind has run.
NOT_STARTED = {"sync": "No sync in progress", "scan": "No scan in progress"}


def _start(kind: str, make, run, started: str) -> JSONResponse:
    if not jobs.start(kind, make, run):
        return JSONResponse({"success": False, "error": f"{kind.capitalize()} already in progress"},
                            status_code=409)
    return JSONResponse({"success": True, "message": started})


def _progress(kind: str) -> JSONResponse:
    progress = jobs.progress(kind)
    if progress is None:
        return JSONResponse({"success": True, "progress": None, "message": NOT_STARTED[kind]})
    return JSONResponse({"success": True, "progress": progress.to_dict()})


def _cancel(kind: str) -> JSONResponse:
    if not jobs.cancel(kind):
        return JSONResponse({"success": False, "error": NOT_STARTED[kind]})
    return JSONResponse({"success": True, "message": "Cancel requested"})


def register(app: FastAPI):
    """Attach this module's endpoints to the app."""
    @app.post("/model-manager/sync")
    async def start_sync(
        force: str = Form(default="false"),  # Form data comes as string
        targets: str = Form(default="all"),
        paths: str = Form(default="")  # Comma-separated paths, empty = all models
    ):
        """
        Start syncing models with Civitai, identifying each file by its hash.

        Args:
            force: Re-sync even if civitai data exists ("true" or "false").
            targets: "all", "identified", or "unidentified" - which of the
                files on disk to work on. Anything but "all" implies force,
                since picking a set is the point of asking.
            paths: Comma-separated model paths, or empty for all.

        Returns immediately. Poll /model-manager/sync/progress for status.
        """
        # Parse force as boolean (form data sends strings)
        target_set = targets if targets in ("all", "identified", "unidentified") else "all"
        # Choosing a set is itself a request to re-read them, so it forces.
        force_bool = (str(force).lower() in ('true', '1', 'yes')
                      or target_set != "all")
        print(f"[ModelManager] Sync requested: targets={target_set} force={force_bool}")

        model_paths = None
        if paths:
            model_paths = [p.strip() for p in paths.split(",") if p.strip()]

        return _start("sync", SyncService,
                      lambda sync: sync.sync_all(model_paths=model_paths, force=force_bool,
                                                 targets=target_set),
                      "Sync started")

    @app.post("/model-manager/sync/metadata")
    async def start_metadata_sync(
        include_images: str = Form(default="false"),
        include_prompts: str = Form(default="true"),
        stale_days: int = Form(default=0),
        downloaded_days: int = Form(default=0),
        paths: str = Form(default="")  # Comma-separated paths, empty = all models
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
                                                      downloaded_after=downloaded_after),
                      "Metadata sync started" + (" (with images)" if with_images else ""))

    @app.get("/model-manager/sync/estimate")
    async def get_sync_estimate(
        include_images: str = "false",
        include_prompts: str = "true",
        stale_days: int = 0,
        downloaded_days: int = 0,
        paths: str = ""
    ):
        """
        What a metadata sync would cost, before anyone starts one.

        The dialog asks for this as its controls change, so the choice between
        "metadata only" and "with images and prompts" is made against minutes
        and requests rather than against a guess. Counts come out of the same
        code that does the batching, so they cannot drift from it.

        Returns the estimate for the current selection, plus how many versions
        each staleness window would take - the numbers shown beside them.
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
            )
            return JSONResponse({
                "success": True,
                "estimate": estimate,
                "windows": sync_window_counts(model_paths),
                "download_windows": sync_window_counts(model_paths, basis="downloaded"),
                # For the hashing option, which is costed in files rather than
                # in requests. From the database, so opening the dialog does
                # not walk the disk; the sync itself will, and may find more.
                "unidentified": get_models_db().count_unidentified(),
            })
        except Exception as e:
            return failed(e)

    @app.get("/model-manager/sync/progress")
    async def get_sync_progress():
        """Get current sync progress."""
        return _progress("sync")

    @app.post("/model-manager/sync/cancel")
    async def cancel_sync():
        """Cancel active sync operation."""
        return _cancel("sync")

    @app.post("/model-manager/scan")
    async def start_scan(options: Optional[dict] = Body(default=None)):
        """
        Start scanning model directories to populate the database.

        Scans all model directories, reads metadata files, and stores
        computed metadata in SQLite for fast querying.

        options.reread_headers: read what every file is from its header
        again, not only new or changed files - after an update that
        recognises more kinds of file.

        options.move_misplaced: move each file sitting in another type's
        folder into its own (see /model-manager/scan/misplaced). Only ever
        asked for by its own box in the dialog, never by a note's button.

        Returns immediately. Poll /model-manager/scan/progress for status.
        """
        reread_headers = bool((options or {}).get("reread_headers"))
        move_misplaced = bool((options or {}).get("move_misplaced"))

        return _start("scan", ScanService,
                      lambda scan: scan.scan_models(reread_headers=reread_headers,
                                                    move_misplaced=move_misplaced),
                      "Scan started")

    @app.get("/model-manager/scan/misplaced")
    def get_misplaced():
        """The files in another type's folder, for Scan Disk's dialog to show before it moves any."""
        try:
            return JSONResponse({"success": True, "files": misplaced_files(get_models_db())})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/scan/progress")
    async def get_scan_progress():
        """Get current scan progress."""
        return _progress("scan")

    @app.post("/model-manager/scan/cancel")
    async def cancel_scan():
        """Cancel active scan operation."""
        return _cancel("scan")
