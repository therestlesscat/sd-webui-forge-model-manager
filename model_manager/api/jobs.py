"""
Work that takes long enough to need watching.

Scanning the disk, syncing with Civitai, refreshing metadata - each starts on
a background thread and reports progress until it finishes or is cancelled.

The module-level state below is why these live together: there is at most one
scan and one sync at a time, and every endpoint here reads or writes that fact.
"""
import threading
from typing import Optional
from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

from ..scan_service import ScanService, ScanProgress
from ..db import get_models_db
from ..sync_service import (
    SyncService,
    SyncProgress,
    estimate_metadata_sync,
    sync_window_counts,
    window_cutoff,
)

# There is one scan and one sync at a time; these say which, and how far along.
_active_sync: Optional[SyncService] = None
_sync_thread: Optional[threading.Thread] = None
_sync_progress: Optional[SyncProgress] = None

_active_scan: Optional[ScanService] = None
_scan_thread: Optional[threading.Thread] = None
_scan_progress: Optional[ScanProgress] = None


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
        global _active_sync, _sync_thread, _sync_progress

        # Parse force as boolean (form data sends strings)
        target_set = targets if targets in ("all", "identified", "unidentified") else "all"
        # Choosing a set is itself a request to re-read them, so it forces.
        force_bool = (str(force).lower() in ('true', '1', 'yes')
                      or target_set != "all")
        print(f"[ModelManager] Sync requested: targets={target_set} force={force_bool}")

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
                    force=force_bool,
                    targets=target_set
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
        global _active_sync, _sync_thread, _sync_progress

        with_images = str(include_images).lower() in ('true', '1', 'yes')
        with_prompts = str(include_prompts).lower() in ('true', '1', 'yes')
        synced_before = window_cutoff(stale_days) if stale_days > 0 else None
        downloaded_after = window_cutoff(downloaded_days) if downloaded_days > 0 else None

        if _sync_thread is not None and _sync_thread.is_alive():
            return JSONResponse(
                {"success": False, "error": "Sync already in progress"},
                status_code=409
            )

        model_paths = None
        if paths:
            model_paths = [p.strip() for p in paths.split(",") if p.strip()]

        _active_sync = SyncService()

        def run_metadata_sync():
            global _sync_progress
            try:
                _sync_progress = _active_sync.sync_metadata(
                    model_paths=model_paths,
                    include_images=with_images,
                    include_prompts=with_prompts,
                    synced_before=synced_before,
                    downloaded_after=downloaded_after
                )
            except Exception as e:
                import traceback
                print(f"[ModelManager] Metadata sync error: {e}")
                traceback.print_exc()
                _sync_progress = SyncProgress(is_complete=True)
                _sync_progress.error_messages.append(str(e))

        _sync_thread = threading.Thread(target=run_metadata_sync, daemon=True)
        _sync_thread.start()

        return JSONResponse({
            "success": True,
            "message": "Metadata sync started" + (" (with images)" if with_images else "")
        })

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
            import traceback
            traceback.print_exc()
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

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
