"""
Internal module for model and version table operations.

This module handles civitai_models and model_versions tables.
Used by ModelsDatabase facade - do not import directly.
"""
import os
import json
import time
from datetime import datetime
from .query import query_models_grouped
from ..nsfw import UNKNOWN
from typing import Optional, List, Dict, Any, Tuple, Callable
from contextlib import contextmanager


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


class ModelsOps:
    """
    Operations for civitai_models and model_versions tables.

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
            cursor.execute("""
                INSERT INTO civitai_models (
                    id, name, description, type, nsfw, nsfw_level, tags,
                    creator_username, creator_image_url,
                    stats_download_count, stats_thumbs_up, stats_thumbs_down, stats_rating,
                    allow_no_credit, allow_commercial_use, allow_derivatives,
                    allow_different_license, supports_generation, updated_at,
                    civitai_synced_at, checkpoint_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    -- The same rule as upsert_version(): a source that says
                    -- nothing about a field must not erase what is recorded.
                    -- A scan reading a thin .civitai.info cannot see the
                    -- licence flags or the vote counts, and used to write a
                    -- permissive default and a zero over both.
                    name = excluded.name,
                    description = COALESCE(excluded.description, civitai_models.description),
                    type = COALESCE(excluded.type, civitai_models.type),
                    nsfw = COALESCE(excluded.nsfw, civitai_models.nsfw),
                    nsfw_level = COALESCE(NULLIF(excluded.nsfw_level, 64), civitai_models.nsfw_level),
                    tags = COALESCE(NULLIF(excluded.tags, '[]'), civitai_models.tags),
                    creator_username = COALESCE(excluded.creator_username, civitai_models.creator_username),
                    creator_image_url = COALESCE(excluded.creator_image_url, civitai_models.creator_image_url),
                    stats_download_count = COALESCE(NULLIF(excluded.stats_download_count, 0), civitai_models.stats_download_count),
                    stats_thumbs_up = COALESCE(NULLIF(excluded.stats_thumbs_up, 0), civitai_models.stats_thumbs_up),
                    stats_thumbs_down = COALESCE(NULLIF(excluded.stats_thumbs_down, 0), civitai_models.stats_thumbs_down),
                    stats_rating = COALESCE(NULLIF(excluded.stats_rating, 0), civitai_models.stats_rating),
                    allow_no_credit = COALESCE(excluded.allow_no_credit, civitai_models.allow_no_credit),
                    allow_commercial_use = COALESCE(excluded.allow_commercial_use, civitai_models.allow_commercial_use),
                    allow_derivatives = COALESCE(excluded.allow_derivatives, civitai_models.allow_derivatives),
                    allow_different_license = COALESCE(excluded.allow_different_license, civitai_models.allow_different_license),
                    supports_generation = COALESCE(excluded.supports_generation, civitai_models.supports_generation),
                    updated_at = excluded.updated_at,
                    -- only moves forward when the data came from the API
                    civitai_synced_at = COALESCE(excluded.civitai_synced_at,
                                                 civitai_models.civitai_synced_at),
                    checkpoint_type = COALESCE(excluded.checkpoint_type,
                                               civitai_models.checkpoint_type)
            """, (
                model_data.get("id"),
                model_data.get("name"),
                model_data.get("description"),
                model_data.get("type", "Checkpoint"),
                1 if model_data.get("nsfw") else 0,
                model_data.get("nsfw_level", UNKNOWN),
                # json.dumps(None) is the string "null", which COALESCE
                # would happily keep. Absent has to reach SQL as NULL.
                _json_or_none(model_data.get("tags")),
                model_data.get("creator_username"),
                model_data.get("creator_image_url"),
                model_data.get("stats_download_count", 0),
                model_data.get("stats_thumbs_up", 0),
                model_data.get("stats_thumbs_down", 0),
                model_data.get("stats_rating", 0),
                _flag(model_data.get("allow_no_credit")),
                self._format_commercial_use(model_data.get("allow_commercial_use")),
                _flag(model_data.get("allow_derivatives")),
                _flag(model_data.get("allow_different_license")),
                _flag(model_data.get("supports_generation")),
                now,
                now if from_civitai else None,
                model_data.get("checkpoint_type")
            ))

    def get_civitai_model(self, model_id: int) -> Optional[Dict[str, Any]]:
        """Get a Civitai model by ID."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM civitai_models WHERE id = ?", (model_id,))
            row = cursor.fetchone()
            if row:
                return self._civitai_model_row_to_dict(row)
        return None

    def set_bookmark(self, model_id: int, bookmarked: bool) -> bool:
        """Set bookmark status for a model. Returns True if updated."""
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE civitai_models SET is_bookmarked = ? WHERE id = ?",
                (1 if bookmarked else 0, model_id)
            )
            return cursor.rowcount > 0

    # ==================== Model Versions ====================

    def upsert_version(self, version_data: Dict[str, Any]):
        """
        Insert or update a model version record.

        Updates only the columns supplied here. INSERT OR REPLACE would delete
        the existing row and insert a fresh one, silently resetting every
        column not named below - downloaded_at, and the image pagination state
        - so a scan or a re-sync would erase when a model was obtained and how
        far its gallery had been fetched.

        ADDING A COLUMN: it must be added in three places - the INSERT column
        list, the VALUES tuple, and the ON CONFLICT ... DO UPDATE SET list.
        Miss the SET list and the column is written on insert but silently
        never updated afterwards.

        The metadata columns keep what they hold when the incoming value says
        nothing - NULL, '[]', 0, or Unknown. A caller that knows a value has
        genuinely become empty cannot express that here, which is the right
        trade: the callers are a scan reading whatever sidecar is on disk and a
        sync reading whatever Civitai returned, and neither can tell an absent
        field from a cleared one.

        Columns deliberately absent from the SET list are owned by other
        flows and must not be touched here: downloaded_at (set once, from the
        download), next_images_cursor and images_sync_last_date (written by
        image syncing, and written *before* this runs during a sync), and
        civitai_lookup_failed_at (written by the sync itself, either side of
        this call).
        """
        with self._cursor() as cursor:
            # Handle file_hashes - can be dict or already JSON string
            file_hashes = version_data.get("file_hashes")
            if isinstance(file_hashes, dict):
                file_hashes = json.dumps(file_hashes)

            cursor.execute("""
                INSERT INTO model_versions (
                    id, model_id, version_name, base_model, published_at, created_at,
                    nsfw_level, trained_words, description,
                    stats_download_count, stats_thumbs_up,
                    file_path, file_name, file_size, file_hashes, file_modified, file_extension,
                    has_civitai_data, scanned_at, cover_url, safe_cover_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    -- Absent is not the same as empty. A .civitai.info that
                    -- says nothing about trained words is not a model that has
                    -- none, and a scan reading a thin sidecar must not empty
                    -- the row it lands on. Each of these keeps what is already
                    -- there when the incoming value carries no information:
                    -- NULL, an empty list, a zero count, or Unknown.
                    id = COALESCE(excluded.id, model_versions.id),
                    model_id = COALESCE(excluded.model_id, model_versions.model_id),
                    version_name = COALESCE(excluded.version_name, model_versions.version_name),
                    base_model = COALESCE(excluded.base_model, model_versions.base_model),
                    published_at = COALESCE(excluded.published_at, model_versions.published_at),
                    created_at = COALESCE(excluded.created_at, model_versions.created_at),
                    nsfw_level = COALESCE(NULLIF(excluded.nsfw_level, 64),
                                          model_versions.nsfw_level),
                    trained_words = COALESCE(NULLIF(excluded.trained_words, '[]'),
                                             model_versions.trained_words),
                    description = COALESCE(excluded.description, model_versions.description),
                    stats_download_count = COALESCE(NULLIF(excluded.stats_download_count, 0),
                                                    model_versions.stats_download_count),
                    stats_thumbs_up = COALESCE(NULLIF(excluded.stats_thumbs_up, 0),
                                               model_versions.stats_thumbs_up),
                    file_name = excluded.file_name,
                    file_size = excluded.file_size,
                    file_hashes = COALESCE(excluded.file_hashes, model_versions.file_hashes),
                    file_modified = excluded.file_modified,
                    file_extension = excluded.file_extension,
                    has_civitai_data = excluded.has_civitai_data,
                    scanned_at = excluded.scanned_at,
                    -- NULL is "this source cannot say" (a stripped showcase
                    -- has no reliable cover); '' is "has none", and is kept.
                    cover_url = COALESCE(excluded.cover_url, model_versions.cover_url),
                    safe_cover_url = COALESCE(excluded.safe_cover_url, model_versions.safe_cover_url)
            """, (
                version_data.get("id"),
                version_data.get("model_id"),
                version_data.get("version_name"),
                version_data.get("base_model"),
                version_data.get("published_at"),
                version_data.get("created_at"),
                version_data.get("nsfw_level", UNKNOWN),
                json.dumps(version_data.get("trained_words", [])),
                version_data.get("description"),
                version_data.get("stats_download_count", 0),
                version_data.get("stats_thumbs_up", 0),
                version_data.get("file_path"),
                version_data.get("file_name"),
                version_data.get("file_size"),
                file_hashes,
                version_data.get("file_modified"),
                version_data.get("file_extension"),
                1 if version_data.get("has_civitai_data") else 0,
                datetime.now().isoformat(),
                version_data.get("cover_url"),
                version_data.get("safe_cover_url"),
            ))

    def delete_version(self, file_path: str):
        """Delete a version record by file path."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM model_versions WHERE file_path = ?", (file_path,))

    def get_version(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get a version by file path."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM model_versions WHERE file_path = ?", (file_path,))
            row = cursor.fetchone()
            if row:
                return self._version_row_to_dict(row)
        return None

    def get_versions_for_model(self, model_id: int) -> List[Dict[str, Any]]:
        """Get all local versions for a Civitai model, ordered by published_at desc."""
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT * FROM model_versions
                WHERE model_id = ?
                ORDER BY published_at DESC
            """, (model_id,))
            rows = cursor.fetchall()
            return [self._version_row_to_dict(row) for row in rows]

    def get_version_by_id(self, version_id: int) -> Optional[Dict[str, Any]]:
        """Get a version by its Civitai version ID (the 'id' column)."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM model_versions WHERE id = ?", (version_id,))
            row = cursor.fetchone()
            if row:
                return self._version_row_to_dict(row)
        return None

    def get_local_version_count(self, model_id: int) -> int:
        """Get count of local versions for a model."""
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM model_versions WHERE model_id = ?", (model_id,))
            return cursor.fetchone()[0]

    # ==================== Grouped Queries ====================

    def query_models_grouped(self, **filters) -> Tuple[List[Dict[str, Any]], int]:
        """Query models grouped by Civitai model id. See db/query.py."""
        return query_models_grouped(self._cursor, **filters)

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
            One dict per version, each with its stored hashes, when it was
            downloaded, and when its model was last refreshed (None if never).
        """
        where = "v.model_id IS NOT NULL AND v.file_path IS NOT NULL"
        params: List[Any] = []
        if synced_before:
            where += " AND (m.civitai_synced_at IS NULL OR m.civitai_synced_at < ?)"
            params.append(synced_before)

        if downloaded_after:
            where += " AND v.downloaded_at IS NOT NULL AND v.downloaded_at >= ?"
            params.append(downloaded_after)

        with self._cursor() as cursor:
            cursor.execute("""
                SELECT v.id, v.model_id, v.file_path, v.file_hashes,
                       v.downloaded_at,
                       m.civitai_synced_at AS model_synced_at
                FROM model_versions v
                LEFT JOIN civitai_models m ON m.id = v.model_id
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

        Insert-only on purpose. upsert_version() names id and model_id in its
        SET list, so upserting a bare row for a file that is already
        identified would wipe the very ids that make it identified. Here a
        file_path that already has a row is simply skipped.

        Args:
            rows: file_path, file_name, file_extension, file_size, file_modified.

        Returns:
            How many rows were actually inserted.
        """
        if not rows:
            return 0

        now = datetime.now().isoformat()
        with self._cursor() as cursor:
            before = cursor.execute("SELECT COUNT(*) FROM model_versions").fetchone()[0]
            cursor.executemany("""
                INSERT INTO model_versions (
                    file_path, file_name, file_extension, file_size, file_modified,
                    has_civitai_data, nsfw_level, scanned_at
                ) VALUES (?, ?, ?, ?, ?, 0, 1, ?)
                ON CONFLICT(file_path) DO NOTHING
            """, [
                (r.get("file_path"), r.get("file_name"), r.get("file_extension"),
                 r.get("file_size"), r.get("file_modified"), now)
                for r in rows if r.get("file_path")
            ])
            after = cursor.execute("SELECT COUNT(*) FROM model_versions").fetchone()[0]
            return after - before

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
                "UPDATE civitai_models SET checkpoint_type = ? WHERE id = ?",
                [(value, model_id) for model_id, value in types.items()]
            )
            return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else len(types)

    def checkpoint_model_ids(self) -> List[int]:
        """Civitai ids of the checkpoints that have a local file."""
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT m.id
                FROM civitai_models m
                JOIN model_versions v ON v.model_id = m.id
                WHERE m.type = 'Checkpoint' AND v.file_path IS NOT NULL
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
                    SUM(CASE WHEN has_civitai_data = 1 THEN 1 ELSE 0 END) AS identified,
                    SUM(CASE WHEN COALESCE(has_civitai_data, 0) = 0
                              AND civitai_lookup_failed_at IS NOT NULL
                             THEN 1 ELSE 0 END) AS asked_not_found
                FROM model_versions
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
        wanted = [h.lower() for h in hashes if h]
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
                hash_value.lower(),
                version.get("id"),
                version.get("modelId"),
                model.get("name"),
                version.get("name"),
                model.get("type"),
                datetime.now().isoformat(),
            ))

    def hashes_from_local_models(self, hashes: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Resolve what we can from our own rows, before asking Civitai anything.

        A version row's id is the Civitai modelVersionId, and the row already
        carries the AutoV2 hash that an image's legacy resource list names - so
        anything in this library resolves for free.
        """
        wanted = {h.lower() for h in hashes if h}
        if not wanted:
            return {}

        found = {}
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT v.id, v.model_id, v.version_name, v.file_hashes, m.name, m.type
                FROM model_versions v
                LEFT JOIN civitai_models m ON m.id = v.model_id
                WHERE v.file_hashes IS NOT NULL AND v.id IS NOT NULL
            """)
            for row in cursor.fetchall():
                try:
                    stored = json.loads(row["file_hashes"]) or {}
                except (TypeError, ValueError):
                    continue
                autov2 = (stored.get("autov2") or stored.get("AutoV2") or "").lower()
                if autov2 and autov2 in wanted:
                    found[autov2] = {
                        "hash": autov2,
                        "version_id": row["id"],
                        "model_id": row["model_id"],
                        "name": row["name"],
                        "version_name": row["version_name"],
                        "model_type": row["type"],
                    }
        return found

    def get_all_version_paths(self) -> List[str]:
        """Get all version file paths in the database."""
        with self._cursor() as cursor:
            cursor.execute("SELECT file_path FROM model_versions")
            return [row[0] for row in cursor.fetchall()]

    def get_distinct_values(self, column: str) -> List[str]:
        """Get distinct values for a column (for filter dropdowns)."""
        column_mapping = {
            "model_type": ("civitai_models", "type"),
            "type": ("civitai_models", "type"),
            "base_model": ("model_versions", "base_model"),
            "creator": ("civitai_models", "creator_username"),
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

    def get_distinct_model_types(self) -> List[str]:
        """Get distinct model types from both tables."""
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT type FROM civitai_models
                WHERE type IS NOT NULL AND type != ''
                UNION
                SELECT DISTINCT 'Unknown' FROM model_versions
                WHERE model_id IS NULL
                ORDER BY 1
            """)
            return [row[0] for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM model_versions")
            total_versions = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM model_versions WHERE has_civitai_data = 1")
            with_civitai = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM civitai_models")
            total_models = cursor.fetchone()[0]

        return {
            "total_versions": total_versions,
            "total_civitai_models": total_models,
            "with_civitai_data": with_civitai,
            "without_civitai_data": total_versions - with_civitai
        }

    def clear_all(self):
        """Clear all model records."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM model_versions")
            cursor.execute("DELETE FROM civitai_models")

    # ==================== Row Converters ====================

    def _civitai_model_row_to_dict(self, row) -> Dict[str, Any]:
        """Convert a civitai_models row to a dictionary."""
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
        """Convert a model_versions row to a dictionary."""
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
        }
