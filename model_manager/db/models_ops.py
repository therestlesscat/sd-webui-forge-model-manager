"""
Internal module for model and version table operations.

This module handles the `models`, `versions` and `files` tables.
Used by ModelsDatabase facade - do not import directly.
"""
import os
import json
from datetime import datetime, timezone
from ..hashing import hash_key, read_hashes
from .library import LIBRARY
from .query import GridQuery, query_models_grouped
from ..nsfw import UNKNOWN
from typing import Optional, List, Dict, Any, Set, Tuple, Callable, NamedTuple

# Whether the disk ignores case, as Windows does. file_path is unique as SQL
# compares it, case and all, so a walk spelling a stored file another way
# made a second row for it (#99), and every other read or write by path found
# nothing for it (#120): each finds the stored row through _stored_spelling.
# Where case matters, two spellings are two files and are left apart.
_CASE_BLIND = os.path.normcase("A") == os.path.normcase("a")


def _stored_spelling(cursor, path: Optional[str]) -> Optional[str]:
    """The path as the library already spells this file, if it holds it; else the path."""
    if not path or not _CASE_BLIND:
        return path
    row = cursor.execute("SELECT file_path FROM files WHERE file_path = ? COLLATE NOCASE "
                         "ORDER BY file_path = ? DESC LIMIT 1", (path, path)).fetchone()
    return row[0] if row else path


def _json_or_none(value):
    """A JSON column, or NULL when there is nothing to say."""
    return None if value is None else json.dumps(value)


def _permissive(value):
    """A licence flag as the rest of the code reads it: unknown means allowed."""
    return True if value is None else bool(value)


def _flag(value):
    """1, 0, or NULL for "nobody said".

    The licence columns are three-valued in every query that reads them -
    query.py asks `IS NULL` for the unknown case - so an absent field has to
    arrive here as NULL rather than as a cheerful default.
    """
    return None if value is None else (1 if value else 0)


# ------------------------------------------------------------------ upserts
# How an update treats each column of a row already there. upsert_civitai_model()
# and upsert_version() are generated from these lists - the INSERT, its
# placeholders and the ON CONFLICT ... SET - and take their values by name.
# They were written out by hand, each column in four places; one left out of
# the SET list was written once and never updated again.
#
# A source that says nothing about a field must not erase what is recorded
# (AGENTS.md, "Absent is not empty"). A scan reading a thin .civitai.info
# cannot tell "no trigger words" from "not mentioned", and used to write the
# second over the first - and a zero over vote counts, a permissive default
# over licence flags.

KEY = None       # the row is found by it: written on insert, never updated


def overwrite(table: str, column: str) -> str:
    """The new value, whatever it is."""
    return f"excluded.{column}"


def keep(table: str, column: str) -> str:
    """The new value, unless it is NULL: nobody said."""
    return f"COALESCE(excluded.{column}, {table}.{column})"


def keep_unless(nothing: str) -> Callable[[str, str], str]:
    """The new value, unless it is NULL or `nothing` - a source's way of saying
    nothing: an empty list, a zero count, Unknown."""
    def rule(table: str, column: str) -> str:
        return f"COALESCE(NULLIF(excluded.{column}, {nothing}), {table}.{column})"
    return rule


class Column(NamedTuple):
    name: str
    update: Optional[Callable[[str, str], str]]
    placeholder: str = "?"


MODEL_COLUMNS = (
    Column("id", KEY),
    Column("name", overwrite),
    Column("description", keep),
    # A sidecar with no type is stored as 'Unknown', which must not replace a
    # type already known.
    Column("type", keep_unless("'Unknown'"), placeholder="COALESCE(?, 'Unknown')"),
    Column("nsfw", keep),
    Column("nsfw_level", keep_unless(f"{UNKNOWN}")),
    Column("tags", keep_unless("'[]'")),
    Column("creator_username", keep),
    Column("creator_image_url", keep),
    Column("stats_download_count", keep_unless("0")),
    Column("stats_thumbs_up", keep_unless("0")),
    Column("stats_thumbs_down", keep_unless("0")),
    Column("stats_rating", keep_unless("0")),
    Column("allow_no_credit", keep),
    Column("allow_commercial_use", keep),
    Column("allow_derivatives", keep),
    Column("allow_different_license", keep),
    Column("supports_generation", keep),
    Column("updated_at", overwrite),
    # Only moves forward when the data came from the API.
    Column("civitai_synced_at", keep),
    Column("checkpoint_type", keep),
)
MODEL_COLUMNS_ELSEWHERE = {
    "is_bookmarked": "set_bookmark(): the person's",
    "versions": "_store_versions(): every version Civitai lists",
    "versions_synced_at": "_store_versions(): when a sync wrote the list",
}

# A version is one row, found by its Civitai id, and written only when the
# writer has one (#131): a stub sidecar another tool left - an error, a model
# id alone - once flagged a file with none, tied it to a model, and kept it so.
VERSION_COLUMNS = (
    Column("id", KEY),
    Column("model_id", keep),
    Column("version_name", keep),
    Column("base_model", keep),
    Column("published_at", keep),
    Column("created_at", keep),
    Column("nsfw_level", keep_unless(f"{UNKNOWN}")),
    Column("trained_words", keep_unless("'[]'")),
    Column("description", keep),
    Column("stats_download_count", keep_unless("0")),
    Column("stats_thumbs_up", keep_unless("0")),
    # NULL is "this source cannot say" (a stripped showcase has no reliable
    # cover); '' is "has none", and is kept.
    Column("cover_url", keep),
    Column("safe_cover_url", keep),
)
# Written by flows of their own, which an upsert must not touch - the image
# paging during a sync is written before the upsert runs.
VERSION_COLUMNS_ELSEWHERE = {
    "next_images_cursor": "update_version_images_state(): image syncing",
    "images_sync_last_date": "update_version_images_state(): image syncing",
}

FILE_COLUMNS = (
    Column("file_path", KEY),
    # Identified stays identified: a scan that finds no sidecar has not
    # learned the file is unknown to Civitai.
    Column("version_id", keep),
    Column("file_name", overwrite),
    Column("file_size", overwrite),
    Column("file_hashes", keep),
    Column("file_modified", overwrite),
    Column("file_extension", overwrite),
    Column("scanned_at", overwrite),
    # What Civitai's list says of the file (payload_rows.file_row): a source
    # that cannot match it - a renamed file, a stripped sidecar - says nothing.
    Column("civitai_file_id", keep),
    Column("civitai_file_type", keep),
    Column("fp", keep),
    Column("size", keep),
    Column("format", keep),
    Column("civitai_primary", keep),
)
FILE_COLUMNS_ELSEWHERE = {
    "downloaded_at": "set_downloaded_at(): once, from the download",
    "civitai_lookup_failed_at": "set_lookup_failed(): the sync, either side of the upsert",
    "architecture": "set_architecture(): what the file itself is (identity_store.py)",
    "architecture_class": "set_architecture()",
    "bundled_text_encoder": "set_architecture()",
    "bundled_vae": "set_architecture()",
    "architecture_checked": "set_architecture()",
    "file_type": "set_architecture()",
    "identified_by": "set_architecture()",
    "lora_alias": "set_architecture()",
}


def _upsert(table: str, columns: Tuple[Column, ...]) -> str:
    """The INSERT ... ON CONFLICT DO UPDATE for a table's columns."""
    key = next(column.name for column in columns if column.update is KEY)
    updates = ",\n    ".join(f"{column.name} = {column.update(table, column.name)}"
                              for column in columns if column.update is not KEY)
    return (f"INSERT INTO {table} ({', '.join(column.name for column in columns)})\n"
            f"VALUES ({', '.join(column.placeholder for column in columns)})\n"
            f"ON CONFLICT({key}) DO UPDATE SET\n    {updates}")


def _row(columns: Tuple[Column, ...], values: Dict[str, Any]) -> Tuple[Any, ...]:
    """The values in the columns' order - given by name, so none lands in
    another's place. A name that is no column is a mistake, and said."""
    extra = set(values) - {column.name for column in columns}
    if extra:
        raise KeyError(f"not columns of the upsert: {sorted(extra)}")
    return tuple(values[column.name] for column in columns)


_MODEL_UPSERT = _upsert("models", MODEL_COLUMNS)
_VERSION_UPSERT = _upsert("versions", VERSION_COLUMNS)
_FILE_UPSERT = _upsert("files", FILE_COLUMNS)


# What the details panel shows of a version it does not hold, and what a
# download of it needs. Everything else in Civitai's version - its images,
# download URLs, scan results - is left out: a model can list dozens.
_VERSION_FIELDS = ("id", "index", "name", "baseModel", "publishedAt", "updatedAt",
                   "availability", "trainedWords", "paidAccess", "earlyAccessDeadline")
_FILE_FIELDS = ("id", "name", "sizeKB", "primary", "type", "metadata")


def version_summary(version: Dict[str, Any]) -> Dict[str, Any]:
    """One of Civitai's modelVersions, trimmed to what is stored of it."""
    summary = {k: version[k] for k in _VERSION_FIELDS if version.get(k) is not None}
    summary["files"] = [{k: f[k] for k in _FILE_FIELDS if f.get(k) is not None}
                        for f in (version.get("files") or []) if isinstance(f, dict)]
    return summary


def _civitai_order(versions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Versions in the order Civitai shows them.

    A sync puts the file's own version first in the payload it hands on, so
    the list is put back by Civitai's `index`. A list with no index - one
    merged from sidecars, or written by another tool - goes newest first.
    """
    if versions and all(isinstance(v.get("index"), int) for v in versions):
        return sorted(versions, key=lambda v: v["index"])
    return sorted(versions, key=lambda v: v.get("publishedAt") or "", reverse=True)


class ModelsOps:
    """
    Operations for the `models`, `versions` and `files` tables.

    Receives a cursor factory from the parent facade.
    """

    def __init__(self, cursor_factory: Callable):
        """
        Initialize with cursor factory from facade.

        Args:
            cursor_factory: Callable that returns a context manager yielding a cursor.
        """
        self._cursor = cursor_factory

    # ==================== Civitai Models ====================

    @staticmethod
    def _format_commercial_use(value: Any) -> Optional[str]:
        """
        Normalise allowCommercialUse for storage.

        Civitai returns a list (e.g. ["Image", "Rent"]), which SQLite cannot
        bind. Existing rows hold the PostgreSQL array literal "{Image,Rent}",
        and the commercial-use filter matches that format, so keep writing it.
        """
        if isinstance(value, (list, tuple, set)):
            return "{" + ",".join(str(v) for v in value) + "}"
        return value

    def upsert_civitai_model(self, model_data: Dict[str, Any],
                             from_civitai: bool = False):
        """
        Insert or update a Civitai model record. Preserves is_bookmarked.

        Args:
            model_data: The model as Civitai describes it.
            from_civitai: True when this data just came back from the API.
                A scan writes these rows too, from the sidecar on disk, having
                asked Civitai nothing - so only a real fetch may claim the
                model was synced. Otherwise a Scan Disk makes every model
                look freshly synced and the staleness windows all read zero.
        """
        now = datetime.now().isoformat()
        with self._cursor() as cursor:
            cursor.execute(_MODEL_UPSERT, _row(MODEL_COLUMNS, {
                "id": model_data.get("id"),
                "name": model_data.get("name"),
                "description": model_data.get("description"),
                "type": model_data.get("type"),
                "nsfw": 1 if model_data.get("nsfw") else 0,
                "nsfw_level": model_data.get("nsfw_level", UNKNOWN),
                # json.dumps(None) is the string "null", which COALESCE
                # would happily keep. Absent has to reach SQL as NULL.
                "tags": _json_or_none(model_data.get("tags")),
                "creator_username": model_data.get("creator_username"),
                "creator_image_url": model_data.get("creator_image_url"),
                "stats_download_count": model_data.get("stats_download_count", 0),
                "stats_thumbs_up": model_data.get("stats_thumbs_up", 0),
                "stats_thumbs_down": model_data.get("stats_thumbs_down", 0),
                "stats_rating": model_data.get("stats_rating", 0),
                "allow_no_credit": _flag(model_data.get("allow_no_credit")),
                "allow_commercial_use": self._format_commercial_use(model_data.get("allow_commercial_use")),
                "allow_derivatives": _flag(model_data.get("allow_derivatives")),
                "allow_different_license": _flag(model_data.get("allow_different_license")),
                "supports_generation": _flag(model_data.get("supports_generation")),
                "updated_at": now,
                "civitai_synced_at": now if from_civitai else None,
                "checkpoint_type": model_data.get("checkpoint_type"),
            }))
            if model_data.get("versions"):
                self._store_versions(cursor, model_data.get("id"), model_data["versions"],
                                     from_civitai, now)

    def store_civitai_versions(self, model_id: int, versions: List[Dict[str, Any]],
                               from_civitai: bool = False) -> bool:
        """Record the versions Civitai lists for a model. See _store_versions."""
        with self._cursor() as cursor:
            return self._store_versions(cursor, model_id, versions, from_civitai,
                                        datetime.now().isoformat())

    @staticmethod
    def _store_versions(cursor, model_id, versions, from_civitai: bool, now: str) -> bool:
        """
        Keep a model's list of versions: every one Civitai has, local or not.

        A list fetched from Civitai replaces what is held - a version deleted
        there is gone. A sidecar's list is only added to what is held, and
        not at all once Civitai's own list is: a sidecar is as old as the
        file's last sync, and would bring deleted versions back.

        Returns whether anything was written.
        """
        incoming = [version_summary(v) for v in versions if isinstance(v, dict) and v.get("id")]
        if not model_id or not incoming:
            return False
        if from_civitai:
            cursor.execute(
                "UPDATE models SET versions = ?, versions_synced_at = ? WHERE id = ?",
                (json.dumps(_civitai_order(incoming)), now, model_id))
            return cursor.rowcount > 0

        cursor.execute("SELECT versions, versions_synced_at FROM models WHERE id = ?",
                       (model_id,))
        row = cursor.fetchone()
        if row is None or row[1]:
            return False
        held = json.loads(row[0]) if row[0] else []
        known = {v["id"] for v in held}
        added = [v for v in incoming if v["id"] not in known]
        if not added:
            return False
        merged = held + added
        if held:
            # The index of one sidecar says nothing about another's.
            merged = [{k: v for k, v in version.items() if k != "index"} for version in merged]
        cursor.execute("UPDATE models SET versions = ? WHERE id = ?",
                       (json.dumps(_civitai_order(merged)), model_id))
        return True

    def get_civitai_versions(self, model_id: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """A model's stored versions, and when Civitai last listed them.

        (None, None) when nothing has recorded them yet.
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT versions, versions_synced_at FROM models WHERE id = ?",
                           (model_id,))
            row = cursor.fetchone()
        if not row or not row[0]:
            return None, None
        return json.loads(row[0]), row[1]

    def get_civitai_model(self, model_id: int) -> Optional[Dict[str, Any]]:
        """Get a Civitai model by ID."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM models WHERE id = ?", (model_id,))
            row = cursor.fetchone()
            if row:
                return self._civitai_model_row_to_dict(row)
        return None

    def set_bookmark(self, model_id: int, bookmarked: bool) -> bool:
        """Set bookmark status for a model. Returns True if updated."""
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE models SET is_bookmarked = ? WHERE id = ?",
                (1 if bookmarked else 0, model_id)
            )
            return cursor.rowcount > 0

    def set_pin(self, model_id: Optional[int], file_path: Optional[str], pinned: bool) -> bool:
        """
        Pin a card, or unpin it: a Civitai model by its id, a file Civitai
        does not know by its path. Unpinning a model also takes the pins of
        its files - one pinned before Civitai knew it still pins the card.
        Returns whether anything was given to pin.
        """
        if not model_id and not file_path:
            return False
        with self._cursor() as cursor:
            if not pinned:
                if model_id:
                    cursor.execute("""
                        DELETE FROM pins WHERE model_id = ?
                           OR file_path IN (SELECT f.file_path FROM files f
                                            JOIN versions cv ON cv.id = f.version_id
                                            WHERE cv.model_id = ?)
                    """, (model_id, model_id))
                if file_path:
                    cursor.execute("DELETE FROM pins WHERE file_path = ?", (file_path,))
                return True
            cursor.execute(
                "INSERT OR IGNORE INTO pins (model_id, file_path, pinned_at) VALUES (?, ?, ?)",
                (model_id or None, None if model_id else file_path,
                 datetime.now(timezone.utc).isoformat()))
            return True

    # ==================== Model Versions ====================

    def upsert_version(self, version_data: Dict[str, Any]):
        """
        Insert or update a file, and the version it is of - a row of each, in
        one transaction. A file with no Civitai version id writes no version.

        Updates only the columns of FILE_COLUMNS and VERSION_COLUMNS. INSERT
        OR REPLACE would delete the existing row and insert a fresh one,
        silently resetting every other column - downloaded_at, and the image
        pagination state - so a scan or a re-sync would erase when a model was
        obtained and how far its gallery had been fetched. The _ELSEWHERE
        tables name them, and what writes each.

        ADDING A COLUMN: an entry in FILE_COLUMNS or VERSION_COLUMNS - how an
        update treats it - and its value below, by name.
        upsert_columns_test.py fails on a column of a table in no list.

        The metadata columns keep what they hold when the incoming value says
        nothing - NULL, '[]', 0, or Unknown. A caller that knows a value has
        genuinely become empty cannot express that here, which is the right
        trade: the callers are a scan reading whatever sidecar is on disk and a
        sync reading whatever Civitai returned, and neither can tell an absent
        field from a cleared one.
        """
        version_id = version_data.get("id")
        with self._cursor() as cursor:
            # The row the library already has for this file, however it is spelt.
            file_path = _stored_spelling(cursor, version_data.get("file_path"))
            file_name = (os.path.basename(file_path) if file_path != version_data.get("file_path")
                         else version_data.get("file_name"))

            # Handle file_hashes - can be dict or already JSON string
            file_hashes = version_data.get("file_hashes")
            if isinstance(file_hashes, dict):
                file_hashes = json.dumps(file_hashes)

            if version_id is not None:
                cursor.execute(_VERSION_UPSERT, _row(VERSION_COLUMNS, {
                    "id": version_id,
                    "model_id": version_data.get("model_id"),
                    "version_name": version_data.get("version_name"),
                    "base_model": version_data.get("base_model"),
                    "published_at": version_data.get("published_at"),
                    "created_at": version_data.get("created_at"),
                    "nsfw_level": version_data.get("nsfw_level", UNKNOWN),
                    "trained_words": json.dumps(version_data.get("trained_words", [])),
                    "description": version_data.get("description"),
                    "stats_download_count": version_data.get("stats_download_count", 0),
                    "stats_thumbs_up": version_data.get("stats_thumbs_up", 0),
                    "cover_url": version_data.get("cover_url"),
                    "safe_cover_url": version_data.get("safe_cover_url"),
                }))
            cursor.execute(_FILE_UPSERT, _row(FILE_COLUMNS, {
                "file_path": file_path,
                "version_id": version_id,
                "file_name": file_name,
                "file_size": version_data.get("file_size"),
                "file_hashes": file_hashes,
                "file_modified": version_data.get("file_modified"),
                "file_extension": version_data.get("file_extension"),
                "scanned_at": datetime.now().isoformat(),
                "civitai_file_id": version_data.get("civitai_file_id"),
                "civitai_file_type": version_data.get("civitai_file_type"),
                "fp": version_data.get("fp"),
                "size": version_data.get("size"),
                "format": version_data.get("format"),
                "civitai_primary": _flag(version_data.get("civitai_primary")),
            }))

    def prune_orphans(self) -> Tuple[int, int]:
        """
        Forget what only files that are gone kept: versions no longer on
        disk and their gallery images, and models none of whose files are.

        A bookmarked model is kept: the bookmark is the person's, not
        Civitai's, and comes back with the model if it is downloaded again.

        Returns:
            (models forgotten, images forgotten)
        """
        with self._cursor() as cursor:
            cursor.execute("""
                DELETE FROM versions WHERE id NOT IN
                    (SELECT version_id FROM files WHERE version_id IS NOT NULL)
            """)
            cursor.execute("""
                DELETE FROM images WHERE version_id NOT IN (SELECT id FROM versions)
            """)
            images = cursor.rowcount
            cursor.execute("""
                DELETE FROM models
                WHERE COALESCE(is_bookmarked, 0) = 0
                  AND id NOT IN (SELECT model_id FROM versions WHERE model_id IS NOT NULL)
            """)
            return cursor.rowcount, images

    def normalize_version_paths(self) -> int:
        """
        Store each file's path as a scan finds it: absolute, with no "..".
        A download filed under a folder given as "models\\..\\embeddings" was
        stored so, and a scan - which finds it as "embeddings" - took the row
        for a file gone from disk. A path another row already holds is left
        as it is, for the scan to settle.

        Returns:
            How many rows were changed.
        """
        changed = 0
        with self._cursor() as cursor:
            cursor.execute("SELECT file_path FROM files WHERE file_path IS NOT NULL")
            stored = [row[0] for row in cursor.fetchall()]
            taken = set(stored)
            for path in stored:
                clean = os.path.abspath(path)
                if clean != path and clean not in taken:
                    cursor.execute("UPDATE files SET file_path = ? WHERE file_path = ?",
                                   (clean, path))
                    taken.add(clean)
                    changed += 1
        return changed

    def files_with_types(self) -> List[Dict[str, Any]]:
        """
        Every file a header has been read for: its path, what it is, what said
        so, Forge's model class if its detector took it, its hashes.
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT file_path, file_type, identified_by, architecture_class, file_hashes "
                           "FROM files "
                           "WHERE file_type IS NOT NULL AND file_type <> 'Unknown' AND file_path IS NOT NULL")
            return [{"file_path": r["file_path"], "file_type": r["file_type"],
                     "identified_by": r["identified_by"], "architecture_class": r["architecture_class"],
                     "file_hashes": json.loads(r["file_hashes"]) if r["file_hashes"] else None}
                    for r in cursor.fetchall()]

    def move_version(self, old_path: str, new_path: str) -> None:
        """
        A file moved on disk: its row, its pin and the generations that used
        it follow, in one transaction. A scan would otherwise take the old
        path for a file gone and the new for a new one - losing when it was
        downloaded, its pin, and its generations' link to it.

        A row already naming the new path, in any spelling, is of a file gone
        since - nothing is moved onto a file (model_dirs.relocate) - which the
        scan's diff would forget anyway, and it is replaced: it once stopped
        the row following its file (#126). What is kept by that path - a
        pin, generations' links - stays, and the moved file's join it, one of
        each: as when a download lands on the path, and, where the file was
        moved there by hand and back, its own.
        """
        with self._cursor() as cursor:
            old_path = _stored_spelling(cursor, old_path)
            there = _stored_spelling(cursor, new_path)
            if there != old_path:
                cursor.execute("DELETE FROM files WHERE file_path = ?", (there,))
            cursor.execute("UPDATE files SET file_path = ?, file_name = ? WHERE file_path = ?",
                           (new_path, os.path.basename(new_path), old_path))
            for path in dict.fromkeys((old_path, there)):
                if path == new_path:
                    continue
                for table in ("pins", "generation_files"):
                    cursor.execute(f"UPDATE OR IGNORE {table} SET file_path = ? WHERE file_path = ?",
                                   (new_path, path))
                    cursor.execute(f"DELETE FROM {table} WHERE file_path = ?", (path,))

    def delete_version(self, file_path: str):
        """Forget a file. Its version stays until prune_orphans(), with its gallery."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM files WHERE file_path = ?",
                           (_stored_spelling(cursor, file_path),))

    def get_version(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get a version by file path."""
        with self._cursor() as cursor:
            cursor.execute(f"SELECT * FROM {LIBRARY} WHERE file_path = ?", (_stored_spelling(cursor, file_path),))
            row = cursor.fetchone()
            if row:
                return self._version_row_to_dict(row)
        return None

    def get_versions_for_model(self, model_id: int) -> List[Dict[str, Any]]:
        """
        Every local file of a Civitai model, each with its version: newest
        published first, a version's files together, in a fixed order.
        """
        with self._cursor() as cursor:
            cursor.execute(f"""
                SELECT * FROM {LIBRARY}
                WHERE model_id = ?
                ORDER BY published_at DESC, id DESC, file_path
            """, (model_id,))
            rows = cursor.fetchall()
            return [self._version_row_to_dict(row) for row in rows]

    def get_version_by_id(self, version_id: int) -> Optional[Dict[str, Any]]:
        """
        A version the library has a file of, by its Civitai id: its first
        file's row, in table order. None when no file of it is held.
        """
        with self._cursor() as cursor:
            cursor.execute(f"SELECT * FROM {LIBRARY} WHERE id = ? ORDER BY file_order LIMIT 1",
                           (version_id,))
            row = cursor.fetchone()
            if row:
                return self._version_row_to_dict(row)
        return None

    # ==================== Grouped Queries ====================

    def query_models_grouped(self, grid: GridQuery, counts: Optional[Dict[str, int]] = None
                             ) -> Tuple[List[Dict[str, Any]], int]:
        """The grid's page and how many cards match. See query.py."""
        return query_models_grouped(self._cursor, grid, counts)

    def get_linked_versions(self,
                            synced_before: Optional[str] = None,
                            downloaded_after: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Every local version that already resolves to a Civitai model.

        A metadata refresh reuses the ids and hashes recorded by an earlier
        sync, so it never has to re-read a multi-gigabyte file. Versions with
        no model_id have never resolved and cannot be refreshed this way.

        Args:
            synced_before: ISO timestamp. Keep only versions whose model was
                last refreshed before it, so a caller can ask for "everything
                I have not touched in a week" without fetching the rest. A
                model that has never been refreshed always qualifies.
            downloaded_after: ISO timestamp. Keep only versions downloaded
                since then - the opposite direction, because what is wanted
                there is the recent arrivals rather than the neglected ones.
                A version with no recorded download date never qualifies: it
                predates the column, and guessing would drop the whole library
                into every window.

        Returns:
            One dict per file, each with its version id, its stored hashes,
            when it was downloaded, and when its model was last refreshed
            (None if never). A version with two files is in it twice.
        """
        where = "v.id IS NOT NULL AND v.model_id IS NOT NULL AND v.file_path IS NOT NULL"
        params: List[Any] = []
        if synced_before:
            where += " AND (m.civitai_synced_at IS NULL OR m.civitai_synced_at < ?)"
            params.append(synced_before)

        if downloaded_after:
            where += " AND v.downloaded_at IS NOT NULL AND v.downloaded_at >= ?"
            params.append(downloaded_after)

        with self._cursor() as cursor:
            cursor.execute(f"""
                SELECT v.id, v.model_id, v.file_path, v.file_hashes,
                       v.downloaded_at,
                       m.civitai_synced_at AS model_synced_at
                FROM {LIBRARY} v
                LEFT JOIN models m ON m.id = v.model_id
                WHERE %s
            """ % where, params)
            return [
                {
                    "id": row["id"],
                    "model_id": row["model_id"],
                    "file_path": row["file_path"],
                    "file_hashes": json.loads(row["file_hashes"]) if row["file_hashes"] else {},
                    "downloaded_at": row["downloaded_at"],
                    "model_synced_at": row["model_synced_at"],
                }
                for row in cursor.fetchall()
            ]

    def insert_missing_versions(self, rows: List[Dict[str, Any]]) -> int:
        """
        Record files the database has never seen, and leave the rest alone.

        Insert-only on purpose: a file that already has a row holds more than
        a walk knows about it, and a walk has nothing to add. A file_path the
        library already holds - in any case, on a disk that ignores case - is
        simply skipped.

        Args:
            rows: file_path, file_name, file_extension, file_size, file_modified.

        Returns:
            How many rows were actually inserted.
        """
        if not rows:
            return 0

        now = datetime.now().isoformat()
        with self._cursor() as cursor:
            before = cursor.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            cursor.executemany("""
                INSERT INTO files (
                    file_path, file_name, file_extension, file_size, file_modified, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO NOTHING
            """, [
                (_stored_spelling(cursor, r.get("file_path")), r.get("file_name"), r.get("file_extension"),
                 r.get("file_size"), r.get("file_modified"), now)
                for r in rows if r.get("file_path")
            ])
            after = cursor.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            return after - before

    def refresh_file_stats(self, rows: List[Dict[str, Any]]) -> int:
        """
        A walk's own facts about files already in the library - size and
        modified time, as the disk has them now - and nothing else: what the
        rest of a row says came from more than a walk. A path the library
        does not hold is skipped.

        Args:
            rows: file_path, file_size, file_modified.

        Returns:
            How many rows changed.
        """
        changed = 0
        with self._cursor() as cursor:
            for r in rows:
                if not r.get("file_path"):
                    continue
                cursor.execute("""
                    UPDATE files SET file_size = ?, file_modified = ?
                    WHERE file_path = ?
                      AND (file_size IS NOT ? OR file_modified IS NOT ?)
                """, (r.get("file_size"), r.get("file_modified"),
                      _stored_spelling(cursor, r["file_path"]),
                      r.get("file_size"), r.get("file_modified")))
                changed += max(cursor.rowcount, 0)
        return changed

    def never_asked_paths(self) -> List[str]:
        """Files no sync has identified, nor asked Civitai about: what a sync hashes."""
        with self._cursor() as cursor:
            cursor.execute("SELECT file_path FROM files WHERE version_id IS NULL "
                           "AND civitai_lookup_failed_at IS NULL AND file_path IS NOT NULL")
            return [row[0] for row in cursor.fetchall()]

    def set_checkpoint_types(self, types: Dict[int, str]) -> int:
        """
        Record which checkpoints are trained and which are merged.

        Written on its own rather than through upsert_civitai_model() because
        it arrives on its own: the classifier answers about a set of ids, with
        no model payload attached.

        Args:
            types: Model id -> "Trained" or "Merge".

        Returns:
            How many rows were updated.
        """
        if not types:
            return 0
        with self._cursor() as cursor:
            cursor.executemany(
                "UPDATE models SET checkpoint_type = ? WHERE id = ?",
                [(value, model_id) for model_id, value in types.items()]
            )
            return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else len(types)

    def checkpoint_model_ids(self) -> List[int]:
        """Civitai ids of the checkpoints that have a local file."""
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT m.id
                FROM models m
                JOIN versions cv ON cv.model_id = m.id
                JOIN files f ON f.version_id = cv.id
                WHERE m.type = 'Checkpoint'
            """)
            return [row["id"] for row in cursor.fetchall()]

    def count_unidentified(self) -> Dict[str, int]:
        """
        How many local files Civitai has no data for, and why not.

        The sync dialog costs its hashing option from these. It counts what is
        in the database, which is what the last scan found - a file added
        since is not here, and will turn up when the sync walks the model
        folders itself. So the number is a floor, not a total.
        """
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN version_id IS NOT NULL THEN 1 ELSE 0 END) AS identified,
                    SUM(CASE WHEN version_id IS NULL
                              AND civitai_lookup_failed_at IS NOT NULL
                             THEN 1 ELSE 0 END) AS asked_not_found
                FROM files
                WHERE file_path IS NOT NULL
            """)
            row = cursor.fetchone()
            total = row["total"] or 0
            identified = row["identified"] or 0
            asked = row["asked_not_found"] or 0
            return {
                "total": total,
                "identified": identified,
                "unidentified": total - identified,
                "asked_not_found": asked,
                "never_asked": total - identified - asked,
            }

    # ---------------------------------------------------------- resource hashes

    def resolved_hashes(self, hashes: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        What we already know about these resource hashes.

        Answers for hashes Civitai did not recognise are kept too, with a null
        version_id, so the same dead hash is not asked about on every image
        that names it.

        Args:
            hashes: AutoV2 hashes, any case.

        Returns:
            Dict keyed by lowercase hash. A value with version_id None means
            "asked, not on Civitai".
        """
        wanted = [hash_key(h) for h in hashes if h]
        if not wanted:
            return {}

        found = {}
        with self._cursor() as cursor:
            for start in range(0, len(wanted), 500):
                chunk = wanted[start:start + 500]
                placeholders = ",".join("?" * len(chunk))
                cursor.execute(
                    "SELECT hash, version_id, model_id, name, version_name, model_type"
                    " FROM resource_hashes WHERE hash IN (%s)" % placeholders,
                    chunk
                )
                for row in cursor.fetchall():
                    found[row["hash"]] = dict(row)
        return found

    def remember_hash(self, hash_value: str, version: Optional[Dict[str, Any]]):
        """
        Record what a resource hash resolved to, or that it resolved to nothing.

        Args:
            hash_value: AutoV2 hash.
            version: Civitai version payload, or None if it does not know it.
        """
        version = version or {}
        model = version.get("model") or {}
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT INTO resource_hashes
                    (hash, version_id, model_id, name, version_name, model_type, checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hash) DO UPDATE SET
                    version_id = excluded.version_id,
                    model_id = excluded.model_id,
                    name = excluded.name,
                    version_name = excluded.version_name,
                    model_type = excluded.model_type,
                    checked_at = excluded.checked_at
            """, (
                hash_key(hash_value),
                version.get("id"),
                version.get("modelId"),
                model.get("name"),
                version.get("name"),
                model.get("type"),
                datetime.now().isoformat(),
            ))

    # ------------------------------------------------- finding local files
    # Four lookups find files in the library - by hash, version id or name -
    # for the Resources dialog, Send to txt2img and the chips under a prompt.
    # Each read every column of every row and parsed every row's hashes: 8 ms
    # a call on a library of 1,536 files, and Send asked once per hash. They
    # read only what finds a file now, each row's hashes once through
    # read_hashes() - the one fold of their case - and whole rows only for
    # what they found. In table order, which decides between files that
    # share a hash or an id.

    @staticmethod
    def _hashed_files(cursor) -> List[Tuple[str, Optional[int], Dict[str, str]]]:
        """(file path, version id, {kind: hash}) for every file with stored hashes."""
        cursor.execute("SELECT file_path, version_id, file_hashes FROM files "
                       "WHERE file_path IS NOT NULL AND file_hashes IS NOT NULL ORDER BY rowid")
        return [(row["file_path"], row["version_id"], read_hashes(row["file_hashes"]))
                for row in cursor.fetchall()]

    @staticmethod
    def _paths_of_versions(cursor, version_ids) -> List[Tuple[int, str]]:
        """(version id, file path) for every file of these versions, in table order."""
        ids = list(dict.fromkeys(version_ids))
        found = []
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            cursor.execute("SELECT rowid, version_id, file_path FROM files"
                           " WHERE file_path IS NOT NULL AND version_id IN (%s)" % ",".join("?" * len(chunk)),
                           chunk)
            found += [(row[0], row["version_id"], row["file_path"]) for row in cursor.fetchall()]
        return [(version_id, path) for _, version_id, path in sorted(found)]

    def _whole_rows(self, cursor, paths) -> Dict[str, Dict[str, Any]]:
        """{file path: its row, as _version_row_to_dict() gives it}."""
        paths = list(dict.fromkeys(paths))
        found = {}
        for start in range(0, len(paths), 500):
            chunk = paths[start:start + 500]
            cursor.execute(f"SELECT * FROM {LIBRARY} WHERE file_path IN (%s)"
                           % ",".join("?" * len(chunk)), chunk)
            for row in cursor.fetchall():
                found[row["file_path"]] = self._version_row_to_dict(row)
        return found

    def hashes_from_local_models(self, hashes: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Resolve what we can from our own rows, before asking Civitai anything.

        A version row's id is the Civitai modelVersionId, and the row already
        carries the AutoV2 hash that an image's legacy resource list names - so
        anything in this library resolves for free.
        """
        wanted = {hash_key(h) for h in hashes if h}
        if not wanted:
            return {}

        with self._cursor() as cursor:
            named = {}          # AutoV2 -> file path: the last file to have it
            for path, version_id, stored in self._hashed_files(cursor):
                autov2 = stored.get("autov2", "")
                if autov2 and autov2 in wanted and version_id is not None:
                    named[autov2] = path
            if not named:
                return {}
            paths = list(dict.fromkeys(named.values()))
            cursor.execute(f"""
                SELECT v.file_path, v.id, v.model_id, v.version_name, m.name, m.type
                FROM {LIBRARY} v
                LEFT JOIN models m ON m.id = v.model_id
                WHERE v.file_path IN (%s)
            """ % ",".join("?" * len(paths)), paths)
            rows = {row["file_path"]: row for row in cursor.fetchall()}
        return {autov2: {
            "hash": autov2,
            "version_id": rows[path]["id"],
            "model_id": rows[path]["model_id"],
            "name": rows[path]["name"],
            "version_name": rows[path]["version_name"],
            "model_type": rows[path]["type"],
        } for autov2, path in named.items()}

    def versions_named_by(self, version_ids: List[int], hashes: List[str]) -> List[Dict[str, Any]]:
        """
        Local versions an image's resources name: by any hash stored for the
        file - images carry AutoV2, AutoV3, SHA256 and others - or by Civitai
        version id. Hash matches first: a hash names one file, where an
        image's version ids name everything it used.
        """
        wanted = {hash_key(h) for h in hashes if h}
        ids = [int(i) for i in version_ids if str(i).isdigit()]
        with self._cursor() as cursor:
            by_hash = [path for path, _, stored in (self._hashed_files(cursor) if wanted else ())
                       if any(v in wanted for v in stored.values())]
            named = set(by_hash)
            by_id: Dict[int, List[str]] = {}
            for version_id, path in self._paths_of_versions(cursor, ids):
                if path not in named:
                    by_id.setdefault(version_id, []).append(path)
            rows = self._whole_rows(cursor, by_hash + [p for paths in by_id.values() for p in paths])
        return [rows[p] for p in by_hash] + [rows[p] for i in ids for p in by_id.get(i, [])]

    def local_versions_by_key(self, version_ids: List[int], hashes: List[str],
                              usable: Optional[Callable[[str], bool]] = None
                              ) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """
        The local file each of an image's resources names, keyed by what named
        it: {version id: row} and {hash: row}, the first file in table order.
        versions_named_by() answers "which files", this "which file for which
        resource" - what a per-resource answer needs. `usable`, given a path,
        says which files may answer at all: of two copies, the one it takes.
        """
        wanted = {hash_key(h) for h in hashes if h}
        ids = [int(i) for i in version_ids if str(i).isdigit()]
        take = usable or (lambda path: True)
        with self._cursor() as cursor:
            id_paths: Dict[int, str] = {}
            for version_id, path in self._paths_of_versions(cursor, ids):
                if take(path):
                    id_paths.setdefault(version_id, path)
            hash_paths: Dict[str, str] = {}
            for path, _, stored in (self._hashed_files(cursor) if wanted else ()):
                for value in stored.values():
                    if value in wanted and take(path):
                        hash_paths.setdefault(value, path)
            rows = self._whole_rows(cursor, list(id_paths.values()) + list(hash_paths.values()))
        return ({i: rows[p] for i, p in id_paths.items()},
                {h: rows[p] for h, p in hash_paths.items()})

    def owned_by_library(self, model_ids, version_ids) -> Tuple[Set[int], Set[int]]:
        """
        Which of these models and versions the library holds: (model ids,
        version ids). A model is held if any file in the library is of it - by
        its model id, or by a version id of it - including a version Civitai
        no longer lists. The Civitai Browser's search cards and its details
        panel each had a rule of their own, and a model held through a deleted
        version was "Owned" on one and not on the other.
        """
        owned_models, owned_versions = set(), set()
        with self._cursor() as cursor:
            for column, ids in (("model_id", set(model_ids)), ("id", set(version_ids))):
                ids.discard(None)
                if not ids:
                    continue
                cursor.execute(
                    f"SELECT DISTINCT model_id, id FROM {LIBRARY} "
                    f"WHERE {column} IN ({','.join('?' * len(ids))})", list(ids))
                for row in cursor.fetchall():
                    owned_models.add(row["model_id"])
                    owned_versions.add(row["id"])
        return owned_models, owned_versions

    def local_versions_by_name(self, names: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        The local files named each of these, by file name without its
        extension, ignoring case: {name (lower case): [row, ...]}. For a
        resource no id or hash finds - a file Scan Disk added and no sync has
        identified yet. Several files can share a name, in different folders.
        """
        wanted = {str(n).lower() for n in names if n}
        if not wanted:
            return {}
        with self._cursor() as cursor:
            cursor.execute("SELECT file_path FROM files WHERE file_path IS NOT NULL ORDER BY rowid")
            named: Dict[str, List[str]] = {}
            for row in cursor.fetchall():
                stem = os.path.splitext(os.path.basename(row["file_path"]))[0].lower()
                if stem in wanted:
                    named.setdefault(stem, []).append(row["file_path"])
            rows = self._whole_rows(cursor, [p for paths in named.values() for p in paths])
        return {stem: [rows[p] for p in paths] for stem, paths in named.items()}

    def local_versions_by_alias(self, aliases: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        The local files whose LoRA alias is each of these: {alias: [row, ...]}.
        Exactly, case and all - as Forge matches an alias, where a file name
        is matched as Windows spells it (local_versions_by_name).
        """
        wanted = sorted({str(a) for a in aliases if a})
        if not wanted:
            return {}
        with self._cursor() as cursor:
            named: Dict[str, List[str]] = {}
            for start in range(0, len(wanted), 500):
                chunk = wanted[start:start + 500]
                cursor.execute("SELECT file_path, lora_alias FROM files WHERE lora_alias IN (%s) "
                               "AND file_path IS NOT NULL ORDER BY rowid" % ",".join("?" * len(chunk)), chunk)
                for row in cursor.fetchall():
                    named.setdefault(row["lora_alias"], []).append(row["file_path"])
            rows = self._whole_rows(cursor, [p for paths in named.values() for p in paths])
        return {alias: [rows[p] for p in paths] for alias, paths in named.items()}

    def get_all_version_paths(self) -> List[str]:
        """Get all version file paths in the database."""
        with self._cursor() as cursor:
            cursor.execute("SELECT file_path FROM files")
            return [row[0] for row in cursor.fetchall()]

    def get_distinct_values(self, column: str) -> List[str]:
        """Get distinct values for a column (for filter dropdowns)."""
        column_mapping = {
            "model_type": ("models", "type"),
            "type": ("models", "type"),
            "base_model": (LIBRARY, "base_model"),
            "creator": ("models", "creator_username"),
        }

        if column not in column_mapping:
            return []

        table, col = column_mapping[column]

        with self._cursor() as cursor:
            cursor.execute(f"""
                SELECT DISTINCT {col} FROM {table}
                WHERE {col} IS NOT NULL AND {col} != ''
                ORDER BY {col}
            """)
            return [row[0] for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM files")
            total_versions = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM files WHERE version_id IS NOT NULL")
            with_civitai = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM models")
            total_models = cursor.fetchone()[0]

        return {
            "total_versions": total_versions,
            "total_civitai_models": total_models,
            "with_civitai_data": with_civitai,
            "without_civitai_data": total_versions - with_civitai
        }

    # ==================== Row Converters ====================

    def _civitai_model_row_to_dict(self, row) -> Dict[str, Any]:
        """Convert a models row to a dictionary."""
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "type": row["type"],
            "nsfw": bool(row["nsfw"]),
            "nsfw_level": row["nsfw_level"],
            "tags": json.loads(row["tags"] or "[]"),
            "creator_username": row["creator_username"],
            "creator_image_url": row["creator_image_url"],
            "stats_download_count": row["stats_download_count"],
            "stats_thumbs_up": row["stats_thumbs_up"],
            "stats_rating": row["stats_rating"],
            "allow_no_credit": _permissive(row["allow_no_credit"]),
            "allow_commercial_use": row["allow_commercial_use"],
            # NULL is "unknown", which query.py reads as permissive; the
            # two must not disagree about the same row.
            "allow_derivatives": _permissive(row["allow_derivatives"]),
            "allow_different_license": _permissive(row["allow_different_license"]),
            "supports_generation": bool(row["supports_generation"]),
            "updated_at": row["updated_at"],
            "checkpoint_type": row["checkpoint_type"],
        }

    def _version_row_to_dict(self, row) -> Dict[str, Any]:
        """Convert a LIBRARY row - a file with its version - to a dictionary."""
        return {
            "id": row["id"],
            "model_id": row["model_id"],
            "version_name": row["version_name"],
            "base_model": row["base_model"],
            "published_at": row["published_at"],
            "created_at": row["created_at"],
            "nsfw_level": row["nsfw_level"],
            "trained_words": json.loads(row["trained_words"] or "[]"),
            "description": row["description"],
            "stats_download_count": row["stats_download_count"],
            "stats_thumbs_up": row["stats_thumbs_up"],
            "file_path": row["file_path"],
            "file_name": row["file_name"],
            "file_size": row["file_size"],
            "file_hashes": json.loads(row["file_hashes"]) if row["file_hashes"] else None,
            "file_modified": row["file_modified"],
            "file_extension": row["file_extension"],
            "has_civitai_data": bool(row["has_civitai_data"]),
            "scanned_at": row["scanned_at"],
            "downloaded_at": row["downloaded_at"] if "downloaded_at" in row.keys() else None,
            "next_images_cursor": row["next_images_cursor"] if "next_images_cursor" in row.keys() else None,
            "images_sync_last_date": row["images_sync_last_date"] if "images_sync_last_date" in row.keys() else None,
            "civitai_lookup_failed_at": row["civitai_lookup_failed_at"] if "civitai_lookup_failed_at" in row.keys() else None,
            "architecture": row["architecture"] if "architecture" in row.keys() else None,
            "architecture_class": row["architecture_class"] if "architecture_class" in row.keys() else None,
            "bundled_text_encoder": bool(row["bundled_text_encoder"]) if "bundled_text_encoder" in row.keys() else False,
            "bundled_vae": bool(row["bundled_vae"]) if "bundled_vae" in row.keys() else False,
            "architecture_checked": row["architecture_checked"] if "architecture_checked" in row.keys() else None,
            "file_type": row["file_type"] if "file_type" in row.keys() else None,
            "identified_by": row["identified_by"] if "identified_by" in row.keys() else None,
            "lora_alias": row["lora_alias"] if "lora_alias" in row.keys() else None,
            "civitai_file_id": row["civitai_file_id"],
            "civitai_file_type": row["civitai_file_type"],
            "fp": row["fp"],
            "size": row["size"],
            "format": row["format"],
            "civitai_primary": None if row["civitai_primary"] is None else bool(row["civitai_primary"]),
        }
