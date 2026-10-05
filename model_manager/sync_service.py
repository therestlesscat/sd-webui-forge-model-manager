"""
Sync service for fetching model data from Civitai.
"""
import os
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Callable, Set, Tuple

from .civitai import (
    CivitaiClient,
    CivitaiAPIError,
    CivitaiNotFoundError,
    apply_generation_data,
    enrich_images_with_generation_data,
    generation_ids_needing_lookup,
    keep_generation_data,
)
from .hashing import HashResult, ModelHasher, fingerprint
from .model_dirs import (file_modified, find_model_files, forget_gone, library_dirs,
                         move_misplaced_files)
from .payload_rows import file_row, model_row, version_row
from .storage import get_metadata_paths, names_a_version, read_model_payload, write_civitai_info
from .file_identity import identify
from .identity_store import needs_check, record_architecture, store_architecture
from .nsfw import showcase_is_complete, version_covers
from .db import get_models_db
from .forge_host import DEFAULTS, setting
from .gallery import fetch_gallery, refresh_size
from .console import said, say



@dataclass
class SyncResult:
    """Result of syncing a single model."""
    success: bool = False
    skipped: bool = False
    not_found: bool = False
    error: Optional[str] = None
    model_id: Optional[int] = None
    version_id: Optional[int] = None
    image_count: int = 0


@dataclass
class SyncProgress:
    """Progress tracking for sync operation."""
    total: int = 0
    processed: int = 0
    synced: int = 0
    skipped: int = 0
    errors: int = 0
    not_found: int = 0
    added: int = 0          # files the database had never seen
    removed: int = 0        # rows whose file is no longer on disk
    moved: int = 0          # files moved into their type's folder
    not_moved: int = 0      # left in another type's: their name is taken there
    # The console's line count when it started (console.said): the page's
    # log panel shows what was said from there.
    log_from: int = 0
    cancelling: bool = False    # asked to stop: what is in progress finishes first
    cancelled: bool = False     # stopped short by it
    current_model: str = ""
    error_messages: List[str] = field(default_factory=list)
    is_complete: bool = False

    def fail(self, message: str):
        """Finished by an error: counted, so the page shows the message."""
        self.errors += 1
        self.error_messages.append(message)
        self.is_complete = True

    def to_dict(self) -> dict:
        return asdict(self)


class SyncService:
    """
    Service for syncing local models with Civitai.

    Fetches model metadata, descriptions, and images from Civitai API
    and keeps them in the database, writing each file's .civitai.info beside it.
    """

    def __init__(self, client: Optional[CivitaiClient] = None):
        """
        Initialize the sync service.

        Args:
            client: CivitaiClient instance. If None, creates from settings.
        """
        self.client = client or CivitaiClient.from_settings()
        # A refreshed gallery: its first page, or as many images as it has
        # stored (#103). The syncs the dialog starts set it; a download's
        # and one model's take the first page, as before.
        self.keep_image_count = False
        self._cancel_requested = False
        # Polled before the run replaces it: from now, not from the console's first line.
        self._progress = SyncProgress(log_from=said())
        # The files being synced right now, by name: what a cancel waits for.
        self._in_flight: List[str] = []
        # sync_all() and sync_metadata() each replace this with a fresh lock,
        # but sync_model() can be called on its own - after a download, say -
        # and _classify_checkpoints() takes it either way.
        self._progress_lock = threading.Lock()
        # The versions whose gallery this run has fetched, while one runs over
        # several files (sync_all, a model's Sync): a version's files share
        # one gallery, and it was fetched once per file (#133). None fetches
        # every time, as one file's sync does.
        self.galleries_fetched: Optional[Set[int]] = None
        self._galleries_lock = threading.Lock()

    def _first_for_gallery(self, version_id: int) -> bool:
        """Whether this run is still to fetch this version's gallery - and,
        if so, that it now has."""
        with self._galleries_lock:
            if self.galleries_fetched is None:
                return True
            if version_id in self.galleries_fetched:
                return False
            self.galleries_fetched.add(version_id)
            return True

    def calculate_hashes(self, file_path: str) -> HashResult:
        """
        A model file's SHA-256, with AutoV2 and AutoV1, which come free: what
        it is asked about first. The other kinds are read only when needed
        (ModelHasher.complete).

        Args:
            file_path: Path to the model file.

        Returns:
            HashResult with those hashes.
        """
        model_name = os.path.basename(file_path)
        say(f"Calculating hashes for {model_name}...")
        return ModelHasher.calculate_first(file_path)

    def _lookup_by_hash_with_fallback(
        self,
        file_path: str,
        hashes: HashResult
    ) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
        """
        Try to find model on Civitai using multiple hash types with fallback.

        Tries SHA256 -> AutoV1 -> AutoV2 first; only when none of them is
        known reads the file again for the rest, and tries AutoV3
        (safetensors) -> BLAKE3 -> CRC32.

        Args:
            file_path: Path to model file.
            hashes: Pre-calculated hash values.

        Returns:
            Tuple of (version_data, matched_hash_type, matched_hash_value) or (None, None, None).

        Raises:
            CivitaiAPIError: when the SHA-256 could not be asked about and no
                other hash answered. Only Civitai's 404 for it says it does not
                know the file; an outage used to say so too, and every file
                looked up during one was marked "not on Civitai" and skipped
                by every sync after.
        """
        model_name = os.path.basename(file_path)
        fallback_order = ModelHasher.get_fallback_order(file_path)
        unasked = None

        # Also check .cm-info.json for stored hashes
        cm_info_hashes = ModelHasher.load_cm_info_hashes(file_path)

        def ask(kinds):
            nonlocal unasked
            for hash_type in kinds:
                # Get hash value from our calculations
                hash_value = getattr(hashes, hash_type, None)

                # Skip if we don't have this hash
                if not hash_value:
                    # Check if .cm-info.json has it
                    if cm_info_hashes and hash_type in cm_info_hashes:
                        hash_value = cm_info_hashes[hash_type]
                    else:
                        continue

                try:
                    version_data = self.client.get_model_by_hash(hash_value)
                    if version_data:
                        say(f"Found {model_name} via {hash_type.upper()}: {hash_value[:16]}...")
                        return version_data, hash_type, hash_value
                except CivitaiNotFoundError:
                    # This hash didn't match, try next
                    continue
                except CivitaiAPIError as e:
                    # API error, log but continue trying other hashes
                    say(f"API error with {hash_type}: {e}")
                    if hash_type == "sha256":
                        unasked = e
                    continue
            return None

        found = ask(ModelHasher.FIRST_LOOKUPS)
        if found:
            return found
        if unasked is not None:
            # No answer about the SHA-256: reading the file again for the
            # rest would be asked of a Civitai that is not answering.
            raise CivitaiAPIError(f"Civitai could not be asked about {model_name}: {unasked}")

        # None of them is known to Civitai: the rest are read from the file -
        # a second read, for the files Civitai does not know by SHA-256.
        ModelHasher.complete(file_path, hashes)
        found = ask(ModelHasher.later_lookups(file_path))
        if found:
            return found

        # If we have .cm-info.json hashes that we didn't calculate, try those too
        if cm_info_hashes:
            for hash_type, hash_value in cm_info_hashes.items():
                # Skip if already tried
                if hash_type in fallback_order:
                    continue

                try:
                    version_data = self.client.get_model_by_hash(hash_value)
                    if version_data:
                        say(f"Found {model_name} via .cm-info.json {hash_type.upper()}: {hash_value[:16]}...")
                        return version_data, hash_type, hash_value
                except (CivitaiNotFoundError, CivitaiAPIError):
                    continue

        return None, None, None

    def sync_model(self, model_path: str, force: bool = False,
                   classify_checkpoint: bool = True,
                   known: Optional[Dict[str, Any]] = None,
                   rehash: bool = False) -> SyncResult:
        """
        Sync a single model with Civitai - see _sync_model().

        A forced sync, which is also what a finished download runs, reads the
        file's architecture again as well (architecture.py): it is when a
        file is new, or may no longer be what was read. Whatever Civitai
        said, and never a reason for the sync to fail.
        """
        result = self._sync_model(model_path, force=force,
                                  classify_checkpoint=classify_checkpoint, known=known,
                                  rehash=rehash)
        if force:
            try:
                record_architecture(get_models_db(), model_path, force=True)
            except Exception as e:
                say(f"Architecture check failed for "
                      f"{os.path.basename(model_path)}: {e}")
        return result

    def _sync_model(self, model_path: str, force: bool = False,
                    classify_checkpoint: bool = True,
                    known: Optional[Dict[str, Any]] = None,
                    rehash: bool = False) -> SyncResult:
        """
        Sync a single model with Civitai.

        Steps:
        1. Check if .civitai.info exists and has full data (skip if complete, unless force)
        2. Calculate multiple hash types (SHA256, AutoV3, CRC32, BLAKE3, AutoV1, AutoV2)
        3. Try by-hash endpoint with fallback through hash types
        4. Call model endpoint to get full model data (description, tags, stats)
        5. Fetch images for the version
        6. Save full model data to .civitai.info

        Args:
            model_path: Path to the model file.
            force: Re-sync even if civitai data exists.
            classify_checkpoint: Ask whether a checkpoint was trained or merged.
                Two requests, and worth it for one file - a download, say. Set
                False when syncing many, and classify them together afterwards:
                per file it would be two requests each rather than two per
                hundred. See _classify_checkpoints().
            known: What a download already knows about the file - "hashes"
                (a HashResult, from Civitai's list for the file, trusted
                because the downloaded bytes matched its SHA-256), "version"
                and "model" (Civitai's payloads). Hashing the file and looking
                it up are skipped: they are what give the rest.
            rehash: Read the file for its hashes even when the ones stored
                were read from it and it has not changed since - a force
                sync's. Otherwise those are asked with (_trusted_hashes).

        Returns:
            SyncResult with status and details.
        """
        result = SyncResult()
        model_name = os.path.basename(model_path)

        # Check if already synced (using database as source of truth)
        if not force:
            db = get_models_db()
            existing = db.get_version(model_path)
            # Identified, and its sidecar there to say so. A sidecar that has
            # gone is written back by syncing the file again.
            if existing and existing.get("has_civitai_data") and os.path.exists(
                    get_metadata_paths(model_path)[0]):
                say(f"Skipping {model_name} (already synced)")
                result.skipped = True
                return result
            # Civitai has already been asked about this file and did not know
            # it. Most LoRAs, VAEs and text encoders never came from Civitai,
            # so without this the next run would re-read the whole file to
            # recompute its hashes and ask again, for nothing. Force ignores
            # this, because a model can appear on Civitai later.
            if existing and existing.get("civitai_lookup_failed_at"):
                say(f"Skipping {model_name} "
                      f"(not on Civitai as of {existing['civitai_lookup_failed_at'][:10]})")
                result.skipped = True
                return result

        say(f"Processing {model_name}...")

        known = known if known and known.get("hashes") and known.get("version") else None
        # What the file was when its hashes were read: stored with them, the
        # mark that they are the file's own - read now, read before and
        # unchanged since (_trusted_hashes compared it), or a download's.
        if known:
            hashes = known["hashes"]
            # Its bytes matched Civitai's SHA-256 as they arrived.
            checked = fingerprint(model_path)
        else:
            # Before reading: a file written meanwhile then reads as changed.
            checked = fingerprint(model_path)
            hashes = None if rehash else self._trusted_hashes(model_path)
            if hashes is None:
                hashes = self.calculate_hashes(model_path)
        if not hashes.sha256:
            result.error = "Failed to calculate hashes"
            return result

        try:
            if known:
                version_data = dict(known["version"])
                version_data.setdefault("modelId", (known.get("model") or {}).get("id"))
            else:
                # Try to find model using fallback hash lookup
                version_data, matched_hash_type, matched_hash = self._lookup_by_hash_with_fallback(
                    model_path, hashes
                )

            if not version_data:
                say(f"{model_name} not found on Civitai (tried all hash types)")
                db = get_models_db()
                # Kept, as for a file Civitai knows: asking again later, or
                # an image's resource naming it, needs no reading.
                if checked:
                    db.store_file_hashes(model_path, self._hashes_to_dict(hashes), checked)
                # Raises when Civitai cannot say whether it has the model the
                # sidecar names: then the file is asked about again next time.
                self._identify_by_sidecar(model_path, hashes, checked)
                db.set_lookup_failed(model_path)
                result.not_found = True
                return result

            if not known:
                # Found by its SHA-256, the file is Civitai's byte for byte:
                # the other kinds Civitai lists for it are the file's own, and
                # are not read. Found by part of it (AutoV1), a prefix (AutoV2)
                # or a later kind, it may not be - what it lacks is read.
                if matched_hash_type == "sha256":
                    self._adopt_listed_hashes(hashes, version_data)
                ModelHasher.complete(model_path, hashes)

            version_id = version_data.get("id")
            model_id = version_data.get("modelId")

            result.version_id = version_id
            result.model_id = model_id

            # Fetch full model data (includes description, tags, stats)
            full_model_data = (known or {}).get("model")
            if model_id and not full_model_data:
                say(f"Fetching full model data for {model_name}...")
                full_model_data = self.client.get_model(model_id)

            # Prepare data to save
            if full_model_data:
                data_to_save = full_model_data
            else:
                # Fallback to version-only data if full model fetch failed
                say(f"Warning: Could not fetch full model data for {model_name}")
                data_to_save = version_data

            data_to_save = self._payload_with_version_first(data_to_save, version_id)

            if not write_civitai_info(model_path, data_to_save):
                result.error = "Failed to write civitai.info"
                return result

            # The first page of the gallery, at the size it is paged in, so
            # opening the model needs no request of its own
            if version_id and self._first_for_gallery(version_id):
                say(f"Fetching images for {model_name}...")
                db = get_models_db()
                stored = db.count_images_by_version([version_id]).get(version_id, 0)
                images, next_cursor = fetch_gallery(self.client, version_id,
                                                    refresh_size(stored, self.keep_image_count))
                # /images returns meta: null - generation data comes from a
                # separate endpoint. Keep what is stored, then look up the
                # rest; without both, a re-sync replaced prompts with nulls.
                keep_generation_data(images, db.get_images(version_id))
                enrich_images_with_generation_data(self.client, images)
                result.image_count = len(images)

                db.replace_first_page(version_id, images, next_cursor)

            # Update database with model and version data. A failure here
            # means the model will not show up in the UI, so it must not be
            # reported as a successful sync.
            db_error = self._update_database(model_path, data_to_save, hashes, hashes_checked=checked)
            if db_error:
                result.error = f"Database update failed: {db_error}"
                return result

            # It was found, so drop any earlier "not on Civitai" note. The
            # accessor rather than `db`, which is only bound on some paths.
            get_models_db().set_lookup_failed(model_path, failed=False)

            # Two requests, and worth it for one file: without this a model
            # only learns its type at the next full sync.
            if classify_checkpoint and model_id and data_to_save.get("type") == "Checkpoint":
                self._classify_checkpoints({model_id: data_to_save})

            result.success = True
            has_more = next_cursor is not None if version_id else False
            say(f"Synced {model_name}: {result.image_count} images (has_more: {has_more})")

            return result

        except CivitaiNotFoundError:
            get_models_db().set_lookup_failed(model_path)
            result.not_found = True
            return result

        except CivitaiAPIError as e:
            # No answer, so nothing is noted about the file - but its hashes
            # are kept: asking again reads nothing.
            if checked:
                get_models_db().store_file_hashes(model_path, self._hashes_to_dict(hashes), checked)
            result.error = str(e)
            return result

        except Exception as e:
            result.error = f"Unexpected error: {e}"
            return result

    def _adopt_listed_hashes(self, hashes: HashResult, version_data: Dict[str, Any]) -> None:
        """
        The kinds Civitai lists for the file whose SHA-256 is this one, where
        `hashes` has none: the same bytes, so the same hashes, as a download
        takes them (download_service). AutoV3 above all, which images name
        LoRAs by.
        """
        mine = (hashes.sha256 or "").upper()
        for listed_file in version_data.get("files") or []:
            listed = HashResult.from_stored(
                {str(k).lower(): v for k, v in ((listed_file or {}).get("hashes") or {}).items()})
            if (listed.sha256 or "").upper() != mine:
                continue
            for name in HashResult.KNOWN:
                if not getattr(hashes, name) and getattr(listed, name):
                    setattr(hashes, name, getattr(listed, name))
            for kind, value in listed.extra.items():
                hashes.extra.setdefault(kind, value)
            return

    def _trusted_hashes(self, model_path: str) -> Optional[HashResult]:
        """
        The hashes stored for a file, when they were read from it and it has
        not changed since (hashing.fingerprint): Civitai is asked with them,
        and gigabytes are not read again. None when there are none, when they
        came from elsewhere - a sidecar, a library from before they were
        marked - or when the file has changed.
        """
        row = get_models_db().get_version(model_path)
        if not row or not row.get("hashes_checked") or row["hashes_checked"] != fingerprint(model_path):
            return None
        hashes = HashResult.from_stored(row.get("file_hashes"))
        if not hashes.sha256:
            return None
        say(f"{os.path.basename(model_path)}: asking with the hashes read from it before")
        return hashes

    def _identify_by_sidecar(self, model_path: str, hashes: HashResult,
                             checked: Optional[str]) -> bool:
        """
        The one time a sidecar is read: Civitai knows no file with these
        hashes, and has no model by the id the sidecar names either - a 404
        for it: deleted, most likely. The sidecar is then all there is, and
        the file is filed under what it says - the version's own level, no
        showcase's. A model Civitai has leaves the file unidentified and its
        sidecar unread: what the model holds is Civitai's to say, and it
        holds no file with these bytes.

        Raises CivitaiAPIError when Civitai cannot be asked about the model.
        Returns whether the sidecar filed the file.
        """
        payload = read_model_payload(model_path)
        model_id = (payload or {}).get("id")
        if not model_id or not names_a_version(payload):
            return False
        if self.client.get_model(model_id) is not None:
            return False

        name = os.path.basename(model_path)
        versions = [v for v in payload.get("modelVersions") or [] if isinstance(v, dict) and v.get("id")]
        version = next((v for v in versions
                        if any(isinstance(f, dict) and f.get("name") == name for f in v.get("files") or [])),
                       versions[0])
        stored = self._hashes_to_dict(hashes)
        stat = os.stat(model_path)
        showcase = version.get("images")
        cover_url, safe_cover_url = version_covers(
            showcase, complete=bool(showcase) and showcase_is_complete(showcase))
        db = get_models_db()
        db.upsert_civitai_model(model_row(payload))
        db.upsert_version({
            **version_row(version, model_id),
            **file_row(version, name, stored),
            "file_path": model_path,
            "file_name": name,
            "file_size": stat.st_size,
            "file_modified": file_modified(model_path),
            "file_extension": os.path.splitext(model_path)[1].lower(),
            # The hashes are the file's own, read just now or before.
            "file_hashes": stored if checked else None,
            "hashes_checked": checked,
            "cover_url": cover_url,
            "safe_cover_url": safe_cover_url,
        })
        say(f"{name}: model {model_id} is not on Civitai either - "
              f"filed as its .civitai.info says")
        return True

    def _record_found_files(self, model_paths: List[str]) -> int:
        """
        Give every file found a row, so local-only models are not invisible.

        Civitai does not know most LoRAs, VAEs and text encoders, and a sync
        that recorded only what Civitai recognised left them out of the library
        entirely: the file is on disk and the grid has never heard of it. Of a
        row already present only the size and modified time are brought up to
        date - see insert_missing_versions() for why the rest is left alone.
        """
        rows = []
        for path in model_paths:
            row = {
                "file_path": path,
                "file_name": os.path.basename(path),
                "file_extension": os.path.splitext(path)[1].lower(),
                "file_size": 0,
                "file_modified": None,
            }
            try:
                stat = os.stat(path)
                row["file_size"] = stat.st_size
                row["file_modified"] = file_modified(path)
            except OSError:
                pass
            rows.append(row)

        db = get_models_db()
        added = db.insert_missing_versions(rows)
        if added:
            say(f"Recorded {added} file(s) the database had not seen")
        # A file that could not be read says nothing of its size.
        db.refresh_file_stats([r for r in rows if r["file_modified"] is not None])
        return added

    def walk_library(self, reread_headers: bool = False,
                     move_misplaced: bool = False) -> List[str]:
        """
        Bring the library's rows in line with the disk, before any request:
        every file found has a row, with its size and date as they are now,
        and its header read if it is new or changed since (every header, with
        `reread_headers`); a file in another type's folder is moved into its
        own when asked; and the rows of files gone from disk are forgotten,
        with what only they kept. What Scan Disk did, but for reading the
        sidecars.

        The walk covers every folder of the library, whatever the sync goes on
        to work on: what a walk did not find is evidence only against the
        whole disk. One that finds nothing forgets nothing.

        Returns the files found.
        """
        db = get_models_db()
        fixed = db.normalize_version_paths()
        if fixed:
            say(f"Stored {fixed} file paths as a walk finds them")
        with self._progress_lock:
            self._progress.current_model = "Reading your model folders..."
        found = find_model_files(library_dirs())
        self._progress.added = self._record_found_files(found)
        self._read_headers(found, force=reread_headers)

        # Never unasked, never over a file, and with their row, pin and
        # generations. Before the diff, which then finds them where they are.
        if move_misplaced and found and not self._cancel_requested:
            moves = move_misplaced_files(db)
            with self._progress_lock:
                self._progress.moved = moves.moved
                self._progress.not_moved = len(moves.not_moved)
                self._progress.errors += len(moves.errors)
                self._progress.error_messages.extend(moves.errors)
            if moves.moved:
                found = find_model_files(library_dirs())

        # A cancelled walk forgets nothing: it has not looked everywhere.
        if self._cancel_requested:
            say("Cancelled while reading your model folders: nothing is forgotten")
        if found and not self._cancel_requested:
            self._progress.removed = self._forget_missing_files(found)
            models_gone, images_gone = db.prune_orphans()
            if models_gone or images_gone:
                say(f"Forgot {models_gone} models with no files left "
                      f"and {images_gone} of their images")
        return found

    #: Files whose header is read at once: a header is small, and the walk
    #: waits on the disk rather than on the reading.
    HEADER_THREADS = 4

    def _read_headers(self, paths: List[str], force: bool = False) -> int:
        """
        What each file is, from its own header (identity_store): only for a
        file new or changed since it was last read, or every one with `force`
        - after an update that tells more kinds of file apart. Read on the
        workers, stored here; a header that cannot be read is that file's
        failure, never the sync's.

        Returns how many were read.
        """
        db = get_models_db()

        def read(path: str):
            if self._cancel_requested:
                return None
            try:
                modified = needs_check(db, path, force=force)
                if modified is not None:
                    return path, identify(path), modified
            except Exception as e:
                say(f"Architecture check failed for {os.path.basename(path)}: {e}")
            return None

        read_count = 0
        looked = 0
        with ThreadPoolExecutor(max_workers=self.HEADER_THREADS) as executor:
            for future in as_completed([executor.submit(read, p) for p in paths]):
                result = future.result()
                looked += 1
                # Before the sync has a total of its own: the page shows this alone.
                with self._progress_lock:
                    self._progress.current_model = f"Reading your model folders: {looked}/{len(paths)}"
                if result is None:
                    continue
                path, found, modified = result
                with self._progress_lock:
                    self._progress.current_model += f" - {os.path.basename(path)}"
                try:
                    store_architecture(db, path, found, modified)
                    read_count += 1
                except Exception as e:
                    say(f"Could not store what {os.path.basename(path)} is: {e}")
        if read_count:
            say(f"Read the headers of {read_count} file(s)")
        return read_count

    def _forget_missing_files(self, found_paths: List[str]) -> int:
        """
        Drop rows for files that are no longer on disk.

        Only ever called with the whole result of a disk walk. A partial list -
        a target set, a search, an explicit path - is not evidence that
        anything was deleted, and diffing against one would empty the library.
        """
        gone = forget_gone(get_models_db(), found_paths)
        if gone:
            say(f"Removed {len(gone)} model(s) no longer on disk")
        return len(gone)

    def _filter_by_identification(self, model_paths: List[str], targets: str) -> List[str]:
        """
        Keep only the files that already resolve to Civitai, or only those that do not.

        A path the database has never seen counts as unidentified: it is a file
        that arrived since the last scan, which is exactly what someone asking
        for the unidentified ones wants swept up.
        """
        db = get_models_db()
        identified = set()
        for version in db.get_linked_versions():
            if version.get("file_path"):
                identified.add(version["file_path"])

        if targets == "identified":
            return [p for p in model_paths if p in identified]
        return [p for p in model_paths if p not in identified]

    def _update_database(self, model_path: str, civitai_data: Dict, hashes: HashResult,
                         hashes_checked: Optional[str] = None,
                         write_hashes: bool = True) -> Optional[str]:
        """
        Update the database with model and version data from Civitai response.

        Args:
            model_path: Path to the local model file.
            civitai_data: Full Civitai model response (or version-only if model fetch failed).
            hashes: HashResult with all computed hashes.
            hashes_checked: What the file was when they were read from it
                (hashing.fingerprint), if they were.
            write_hashes: False when the hashes are the ones already stored:
                they are kept, and whether they are the file's own with them.

        Returns:
            None on success, or an error message describing the failure.
        """
        try:
            db = get_models_db()
            file_name = os.path.basename(model_path)
            file_ext = os.path.splitext(model_path)[1].lower()

            # Get file stats
            file_size = 0
            modified = None
            try:
                stat = os.stat(model_path)
                file_size = stat.st_size
                modified = file_modified(model_path)
            except OSError:
                pass

            model_id = civitai_data.get("id")
            versions = civitai_data.get("modelVersions", [])

            if model_id and versions:
                civitai_model = model_row(civitai_data)
                db.upsert_civitai_model(civitai_model, from_civitai=True)

                # Find the matched version (first in list since we reordered it)
                matched_version = versions[0] if versions else None

                if matched_version:
                    version_data = {
                        **version_row(matched_version, model_id),
                        **file_row(matched_version, file_name, self._hashes_to_dict(hashes)),
                        "file_path": model_path,
                        "file_name": file_name,
                        "file_size": file_size,
                        "file_hashes": self._hashes_to_dict(hashes) if write_hashes else None,
                        "hashes_checked": hashes_checked,
                        "file_modified": modified,
                        "file_extension": file_ext,
                        "has_civitai_data": True,
                    }
                    # A full model payload (/models/{id}, or /models?ids= with
                    # nsfw=true) carries the whole showcase.
                    version_data["cover_url"], version_data["safe_cover_url"] = \
                        version_covers(matched_version.get("images"), complete=True)

                    db.upsert_version(version_data)

            else:
                # Version-only response (model fetch failed)
                version_data = {
                    **version_row(civitai_data, civitai_data.get("modelId")),
                    **file_row(civitai_data, file_name, self._hashes_to_dict(hashes)),
                    "file_path": model_path,
                    "file_name": file_name,
                    "file_size": file_size,
                    "file_hashes": self._hashes_to_dict(hashes) if write_hashes else None,
                    "hashes_checked": hashes_checked,
                    "file_modified": modified,
                    "file_extension": file_ext,
                    "has_civitai_data": True,
                }
                # by-hash strips all but PG and stops at ten, whatever it is
                # asked: its first image is safe, but it cannot say which is
                # the cover.
                version_data["cover_url"], version_data["safe_cover_url"] = \
                    version_covers(civitai_data.get("images"), complete=False)

                db.upsert_version(version_data)

            return None

        except Exception as e:
            import traceback
            say(f"Error updating database for {os.path.basename(model_path)}: {e}")
            traceback.print_exc()
            return str(e)

    def _hashes_to_dict(self, hashes: HashResult) -> Dict[str, str]:
        """
        Convert HashResult to a dict for storage.

        Only includes non-None hash values.

        Args:
            hashes: HashResult with computed hashes.

        Returns:
            Dict mapping hash type to value.
        """
        return hashes.to_dict()

    def sync_all(
        self,
        model_paths: Optional[List[str]] = None,
        force: bool = False,
        targets: str = "all",
        callback: Optional[Callable[[SyncProgress], None]] = None,
        max_workers: Optional[int] = None,
        keep_image_count: bool = False,
        reread_headers: bool = False,
        move_misplaced: bool = False,
    ) -> SyncProgress:
        """
        Sync multiple models with Civitai using multiple threads.

        Args:
            model_paths: Specific paths to sync, or None for every file a walk
                of the library finds (walk_library) - the walk comes first.
            targets: Which of the files found to work on - "all", "identified"
                for the ones that already resolve to a Civitai model, or
                "unidentified" for the ones that do not. A file on disk that
                the database has never seen is unidentified by definition, and
                so is one Civitai was asked about and did not recognise.
            force: Re-sync even if civitai data exists.
            callback: Called after each model with progress update.
            max_workers: Number of parallel threads, or None to take the
                setting. Hashing is bound by reading and hashing bytes, and
                both scale with threads, so this is the dial that matters for
                a full sync.
            keep_image_count: Refetch as many images as each gallery has
                stored, rather than its first page (refresh_size).
            reread_headers, move_misplaced: the walk's (walk_library).

        Returns:
            Final SyncProgress with summary.
        """
        self._cancel_requested = False
        self._progress_lock = threading.Lock()
        self._progress = SyncProgress(log_from=said())
        self.keep_image_count = keep_image_count

        if max_workers is None:
            max_workers = configured_hash_threads()

        # The walk rests on having seen the whole disk, so it runs before
        # `targets` narrows the list: the complete set is the evidence, not
        # whichever subset is about to be worked on.
        found = None
        if model_paths is None:
            found = model_paths = self.walk_library(reread_headers=reread_headers,
                                                    move_misplaced=move_misplaced)

        if targets in ("identified", "unidentified"):
            model_paths = self._filter_by_identification(model_paths, targets)
        # Every sync identifies the files Civitai has never been asked about,
        # and the ones changed since they were read, this one too.
        if targets == "identified" and found:
            new, changed = files_to_identify(found)
            listed = {os.path.normcase(p) for p in model_paths}
            model_paths += [p for p in new + changed if os.path.normcase(p) not in listed]

        self._progress.total = len(model_paths)
        say(f"Starting sync with {max_workers} threads for {len(model_paths)} models")

        # A force sync reads every file again, whatever is stored.
        self._sync_files(model_paths, force, max_workers, rehash=force)

        # Said before it is complete: the page's last poll reads the log with it.
        self._progress.cancelled = self._cancel_requested
        say(f"Sync {'cancelled' if self._cancel_requested else 'complete'}: {self._progress.synced} synced, "
            f"{self._progress.not_found} not found, {self._progress.skipped} skipped, "
            f"{self._progress.errors} errors")
        self._progress.current_model = ""
        self._progress.is_complete = True

        return self._progress

    def _sync_files(self, model_paths: List[str], force: bool, max_workers: int,
                    rehash: bool = False) -> None:
        """
        sync_model() for each of these files, a few at a time, counted on the
        progress as each ends; then one question about trained or merged for
        the checkpoints among them that were found.
        """
        synced_model_ids = set()
        self.galleries_fetched = set()

        def process_model(path: str) -> tuple:
            """Process a single model and return (path, result)."""
            if self._cancel_requested:
                return path, None
            name = os.path.basename(path)
            with self._progress_lock:
                self._in_flight.append(name)
            try:
                # Not per file: the classifier answers about a hundred ids at a
                # time, so they are collected and asked about together below.
                return path, self.sync_model(path, force=force, classify_checkpoint=False, rehash=rehash)
            finally:
                with self._progress_lock:
                    self._in_flight.remove(name)
                    left = len(self._in_flight)
                if self._cancel_requested:
                    say(f"{name}: finished after the cancel"
                        + (f" - {left} still finishing" if left else " - the last one"))

        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            futures = {executor.submit(process_model, path): path for path in model_paths}

            # Process results as they complete
            for future in as_completed(futures):
                if self._cancel_requested:
                    break

                path, result = future.result()
                if result is None:
                    continue

                if result.success and result.model_id:
                    synced_model_ids.add(result.model_id)

                model_name = os.path.basename(path)

                # Thread-safe progress update
                with self._progress_lock:
                    self._progress.current_model = model_name
                    self._progress.processed += 1

                    if result.success:
                        self._progress.synced += 1
                    elif result.skipped:
                        self._progress.skipped += 1
                    elif result.not_found:
                        self._progress.not_found += 1
                    else:
                        self._progress.errors += 1
                        if result.error:
                            error_msg = f"{model_name}: {result.error}"
                            self._progress.error_messages.append(error_msg)
                            # Keep only last 10 errors
                            if len(self._progress.error_messages) > 10:
                                self._progress.error_messages = self._progress.error_messages[-10:]

        self.galleries_fetched = None

        # One question for everything that was identified, rather than two
        # requests per file. Only the checkpoints among them are asked about.
        if synced_model_ids and not self._cancel_requested:
            checkpoints = set(get_models_db().checkpoint_model_ids()) & synced_model_ids
            if checkpoints:
                self._classify_checkpoints({i: {"type": "Checkpoint"} for i in checkpoints})

    @staticmethod
    def _payload_with_version_first(model_data: Dict, version_id: Optional[int]) -> Dict:
        """
        Put the version we hold locally at the front of modelVersions.

        Everything downstream - the sidecar, _update_database, the details
        panel - reads modelVersions[0] as "the one this file is".
        """
        versions = model_data.get("modelVersions")
        if not versions or version_id is None:
            return model_data

        matched = [v for v in versions if v.get("id") == version_id]
        if not matched:
            return model_data

        others = [v for v in versions if v.get("id") != version_id]
        model_data["modelVersions"] = matched + others
        return model_data

    def sync_metadata(
        self,
        model_paths: Optional[List[str]] = None,
        include_images: bool = False,
        include_prompts: bool = True,
        synced_before: Optional[str] = None,
        downloaded_after: Optional[str] = None,
        callback: Optional[Callable[[SyncProgress], None]] = None,
        max_workers: Optional[int] = None,
        keep_image_count: bool = False,
        reread_headers: bool = False,
        move_misplaced: bool = False,
    ) -> SyncProgress:
        """
        Refresh Civitai data for models that already resolve, without hashing
        them - after a walk of the library (walk_library), and then
        identifying the files it holds that no sync has asked about.

        sync_all() exists to *identify* a file: it reads every byte to compute
        hashes and asks Civitai which version they belong to. Once that has
        happened the answer is recorded, so refreshing descriptions, tags,
        stats and licences only needs the model ids we already hold. That turns
        an hours-long pass over a large library into a handful of requests,
        since ids are fetched a hundred at a time.

        Of the files that have never resolved, the ones Civitai has never been
        asked about - new on disk, mostly - are hashed and looked up, as
        sync_all() does; the ones it was asked about and did not know are left
        to a force sync.

        Args:
            model_paths: Restrict to these files, or None for everything.
            include_images: Also refetch each version's gallery. This is the
                expensive half: images cannot be batched, and the existing
                rows for a version are replaced.
            include_prompts: Look up the generation data behind those images.
                Civitai's public endpoint returns meta: null, so without this
                the galleries arrive without prompts - and with it, they cost
                a request per thirty images, which is most of a full sync.
            synced_before: Only refresh models last refreshed before this ISO
                timestamp, for "everything I have not touched in a week".
            downloaded_after: Only refresh versions downloaded since this ISO
                timestamp, for "whatever I added this week".
            callback: Called after each version with progress.
            max_workers: Threads used for the per-version work. None derives
                it from the configured request rate, which is what actually
                bounds the sync - a thread beyond that only waits for a token.
            keep_image_count: With images, refetch as many as each gallery
                has stored, rather than its first page (refresh_size).
            reread_headers, move_misplaced: the walk's (walk_library).

        Returns:
            Final SyncProgress with summary.
        """
        self._cancel_requested = False
        self._progress_lock = threading.Lock()
        self._progress = SyncProgress(log_from=said())

        self.keep_image_count = keep_image_count
        if max_workers is None:
            max_workers = self._workers_for_rate()

        # The whole disk, whatever this sync refreshes: see walk_library().
        found = self.walk_library(reread_headers=reread_headers,
                                  move_misplaced=move_misplaced)
        db = get_models_db()
        new_files, changed = files_to_identify(found)

        versions = db.get_linked_versions(synced_before=synced_before,
                                          downloaded_after=downloaded_after)

        if model_paths is not None:
            wanted = set(model_paths)
            versions = [v for v in versions if v["file_path"] in wanted]

        missing = [v for v in versions if not os.path.exists(v["file_path"])]
        versions = [v for v in versions if os.path.exists(v["file_path"])]

        # Proof about one row rather than a diff: this file was about to be
        # refreshed and it is not there, so the row goes. Sound whatever the
        # scope is, because nothing is inferred from what was not looked at.
        for version in missing:
            db.delete_version(version["file_path"])
        if missing:
            say(f"Removed {len(missing)} model(s) no longer on disk")

        # With images this runs twice - over the files for their metadata, then
        # over their versions for the galleries, which a version's files share
        # - so the bar counts both passes rather than filling up halfway.
        galleries = len({v["id"] for v in versions}) if include_images else 0
        self._progress.total = len(versions) + galleries + len(new_files) + len(changed)
        self._progress.removed += len(missing)
        for version in missing:
            self._progress.error_messages.append(
                f"Removed, file no longer on disk: {os.path.basename(version['file_path'])}"
            )

        if versions and not self._refresh_metadata(versions, include_images, include_prompts,
                                                   callback, max_workers):
            # Civitai did not answer: a file looked up now would be taken for
            # one it does not know.
            self._progress.is_complete = True
            return self._progress

        if new_files and not self._cancel_requested:
            say(f"Identifying {len(new_files)} file(s) Civitai has not been asked about")
            self._sync_files(new_files, force=False, max_workers=configured_hash_threads())
        # Asked about again whatever was said of them before: they are not
        # the files that was said of.
        if changed and not self._cancel_requested:
            say(f"Identifying {len(changed)} file(s) changed since they were read")
            self._sync_files(changed, force=True, max_workers=configured_hash_threads())

        self._progress.cancelled = self._cancel_requested
        say(f"Metadata sync {'cancelled' if self._cancel_requested else 'complete'}: "
            f"{self._progress.synced} updated, "
            f"{self._progress.not_found} not on Civitai, {self._progress.errors} errors")
        self._progress.is_complete = True
        self._progress.current_model = ""
        return self._progress

    def _refresh_metadata(self, versions: List[Dict[str, Any]], include_images: bool,
                          include_prompts: bool,
                          callback: Optional[Callable[[SyncProgress], None]],
                          max_workers: int) -> bool:
        """
        sync_metadata()'s refresh of the versions already identified: their
        models fetched a hundred at a time, each file's sidecar and rows
        written from them, the checkpoints classified, then the galleries if
        asked. False when Civitai could not be asked at all.
        """
        model_ids = list(dict.fromkeys(v["model_id"] for v in versions))
        say(f"Metadata sync: {len(versions)} versions across "
              f"{len(model_ids)} models (images={include_images})")

        self._progress.current_model = f"Fetching {len(model_ids)} models from Civitai..."
        if callback:
            callback(self._progress)

        try:
            fetched = self.client.get_models_by_ids(model_ids)
        except Exception as e:
            self._progress.error_messages.append(f"Could not fetch models: {e}")
            return False

        say(f"Metadata sync: Civitai returned {len(fetched)} of {len(model_ids)}")

        def process(version: Dict[str, Any]) -> None:
            if self._cancel_requested:
                return

            path = version["file_path"]
            name = os.path.basename(path)
            model_data = fetched.get(version["model_id"])

            with self._progress_lock:
                self._progress.current_model = name

            if not model_data:
                with self._progress_lock:
                    self._progress.processed += 1
                    self._progress.not_found += 1
                return

            try:
                # A fresh copy per version: the reordering below is per file,
                # and several local files can share one model.
                payload = self._payload_with_version_first(
                    json.loads(json.dumps(model_data)), version["id"]
                )

                if not write_civitai_info(path, payload):
                    raise RuntimeError("could not write civitai.info")

                db_error = self._update_database(
                    path, payload, HashResult.from_stored(version["file_hashes"]), write_hashes=False
                )
                if db_error:
                    raise RuntimeError(db_error)

                with self._progress_lock:
                    self._progress.processed += 1
                    self._progress.synced += 1

            except Exception as e:
                with self._progress_lock:
                    self._progress.processed += 1
                    self._progress.errors += 1
                    self._progress.error_messages.append(f"{name}: {e}")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process, v) for v in versions]
            for future in as_completed(futures):
                future.result()
                if callback:
                    callback(self._progress)
                if self._cancel_requested:
                    break

        if not self._cancel_requested:
            self._classify_checkpoints(fetched)

        if include_images and not self._cancel_requested:
            self._refresh_galleries(versions, callback, max_workers, include_prompts)
        return True

    # Galleries are refreshed a chunk of versions at a time, not one by one.
    # The generation data behind them is fetched by id, 30 ids per request,
    # and a batch filled from one gallery is mostly half-empty: 90 images
    # means three full requests and one carrying ten. Pooling a chunk's ids
    # fills every batch but the last, which over this library is ~470 fewer
    # requests - and the rate limiter charges one token per request.
    GALLERY_CHUNK = 40

    def _workers_for_rate(self) -> int:
        """
        How many threads the configured request rate can keep busy.

        Every request takes a token from one shared bucket, so throughput is
        the rate, not the thread count; threads only exist to cover the time
        a request spends in flight. One thread per request-per-second covers a
        round trip of up to a second, which is past what Civitai takes.
        """
        rate = getattr(getattr(self.client, "rate_limiter", None),
                       "tokens_per_second", 4.0)
        return max(4, min(int(rate + 0.5), 12))

    def _classify_checkpoints(self, fetched: Dict[int, Dict[str, Any]]) -> int:
        """
        Record which of the checkpoints just refreshed are trained or merged.

        Civitai will filter on checkpointType but never returns it, so unlike
        everything else a sync stores this cannot ride along with the payload
        - it costs two requests per hundred checkpoints. Only checkpoints are
        asked about; the question is meaningless for anything else.

        Args:
            fetched: What Civitai returned, keyed by model id.

        Returns:
            How many models were classified.
        """
        checkpoints = [model_id for model_id, model in fetched.items()
                       if (model or {}).get("type") == "Checkpoint"]
        if not checkpoints:
            return 0

        with self._progress_lock:
            self._progress.current_model = (
                f"Checking {len(checkpoints)} checkpoints for trained or merged..."
            )

        try:
            types = self.client.get_checkpoint_types(checkpoints)
        except Exception as e:
            say(f"Could not classify checkpoints: {e}")
            return 0

        if types:
            get_models_db().set_checkpoint_types(types)
            say(f"Classified {len(types)} of {len(checkpoints)} checkpoints")
        return len(types)

    def _refresh_galleries(self,
                           versions: List[Dict[str, Any]],
                           callback: Optional[Callable[[SyncProgress], None]],
                           max_workers: int,
                           include_prompts: bool = True) -> None:
        """
        Replace each version's cached gallery with a fresh one (refresh_size):
        once a version, however many of its files are in `versions`.
        """
        seen: Set[int] = set()
        versions = [v for v in versions
                    if v.get("id") and not (v["id"] in seen or seen.add(v["id"]))]
        db = get_models_db()
        # Read once: a setting changed mid-sync would give one sync two sizes
        stored = db.count_images_by_version([v["id"] for v in versions if v.get("id")])
        sizes = {version_id: refresh_size(stored.get(version_id, 0), self.keep_image_count)
                 for version_id in stored}
        page_size = refresh_size(0, False)

        for start in range(0, len(versions), self.GALLERY_CHUNK):
            if self._cancel_requested:
                return

            chunk = versions[start:start + self.GALLERY_CHUNK]
            # (version id, images, Civitai's cursor to the next page, or
            # False when the fetch failed and there is no cursor to keep)
            galleries: List[Tuple[int, List[Dict[str, Any]], Any]] = []

            def fetch(version: Dict[str, Any]) -> None:
                if self._cancel_requested or not version.get("id"):
                    # Linked to a model but with no version id of its own, so
                    # there is no gallery to ask for.
                    return
                name = os.path.basename(version["file_path"])
                with self._progress_lock:
                    self._progress.current_model = f"Images: {name}"
                try:
                    images, next_cursor = fetch_gallery(self.client, version["id"],
                                                        sizes.get(version["id"], page_size))
                except Exception as e:
                    with self._progress_lock:
                        self._progress.errors += 1
                        self._progress.error_messages.append(f"{name}: images: {e}")
                    images = []
                    next_cursor = False
                with self._progress_lock:
                    galleries.append((version["id"], images, next_cursor))

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for future in as_completed([executor.submit(fetch, v) for v in chunk]):
                    future.result()

            # Prompts already stored stay, whether or not this sync looks any
            # up - and are then not looked up again.
            for version_id, images, _ in galleries:
                keep_generation_data(images, db.get_images(version_id))

            # One pooled lookup for the whole chunk, then hand each gallery
            # back the rows that belong to it.
            pooled: List[int] = []
            if include_prompts:
                for _, images, _ in galleries:
                    pooled.extend(generation_ids_needing_lookup(images))

            generation_data: Dict[int, Dict[str, Any]] = {}
            if pooled:
                try:
                    generation_data = self.client.get_generation_data(pooled)
                except Exception as e:
                    say(f"Generation data lookup failed: {e}")

            with self._progress_lock:
                self._progress.processed += len(chunk) - len(galleries)

            for version_id, images, next_cursor in galleries:
                if generation_data:
                    apply_generation_data(images, generation_data)
                try:
                    # A gallery that failed to load says nothing about what
                    # the version has, so the stored one stays as it is. It
                    # used to be cleared and nothing stored in its place: a
                    # network error during a sync emptied the galleries it
                    # touched. The failure is already counted as an error.
                    # With where Civitai's next page starts, as a sync of one
                    # model keeps it. Without it "Download More Images" asked
                    # for the first page again - these images - and showed
                    # nothing new until a second click: 718 of 1,051 files in
                    # one library had images and no cursor.
                    if next_cursor is not False:
                        db.replace_first_page(version_id, images, next_cursor)
                except Exception as e:
                    with self._progress_lock:
                        self._progress.errors += 1
                        self._progress.error_messages.append(f"images {version_id}: {e}")

                with self._progress_lock:
                    self._progress.processed += 1

            if callback:
                callback(self._progress)

    def cancel(self):
        """
        Request cancellation of the sync operation: no new file starts, and
        the ones in progress finish - a file is never left half-synced. Said,
        with which they are, for the log and the page.
        """
        self._cancel_requested = True
        with self._progress_lock:
            self._progress.cancelling = True
            running = list(self._in_flight)
        if running:
            say(f"Cancelling: no new file starts; finishing the {len(running)} in progress "
                f"({', '.join(running)}), then stopping")
        else:
            say("Cancelling: stopping after what is in progress")

    @property
    def progress(self) -> SyncProgress:
        """Get current sync progress."""
        return self._progress


def files_to_identify(found: List[str]) -> Tuple[List[str], List[str]]:
    """
    Of the files a walk found, the ones every sync hashes and looks up: the
    ones Civitai has never been asked about, and the ones changed since their
    hashes were read from them (hashing.fingerprint) - other files now, for
    all anyone can tell. A file whose hashes are not marked as its own - a
    sidecar's, or stored before they were marked - is never taken as changed.

    Returns (never asked about, changed).
    """
    db = get_models_db()
    unasked = {os.path.normcase(p) for p in db.never_asked_paths()}
    checked = {os.path.normcase(p): mark for p, mark in db.hashes_checked_by_path().items()}
    new, changed = [], []
    for path in found:
        key = os.path.normcase(path)
        if key in unasked:
            new.append(path)
        elif key in checked and checked[key] != fingerprint(path):
            changed.append(path)
    return new, changed


def configured_hash_threads() -> int:
    """
    How many files to hash at once, as the settings have it.

    Unlike the metadata sync, this is not bound by an API rate: it is bound by
    reading and hashing bytes, and both scale nearly linearly with threads. The
    right number depends on the disk the models are on, which is why it is a
    setting rather than a constant.
    """
    try:
        configured = setting('model_manager_hash_threads')
        if configured:
            return max(1, min(int(configured), 16))
    except (TypeError, ValueError):
        pass
    return DEFAULTS['model_manager_hash_threads']
