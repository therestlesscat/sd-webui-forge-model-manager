"""
The database itself: how it is opened, and everything that can be asked of it.

One SQLite file holds the whole library. This module owns the connection and
hands the actual queries to the operation modules beside it - it is the single
door in, so callers never import those directly.

WHAT LIVES WHERE
  migrations.py         schema history; read only when the schema changes
  models_ops.py         models and versions: writing them, reading them back
  query.py              turning a filter bar into one grouped SQL query
  images_ops.py         the image rows belonging to a version
  browse_cache_ops.py   the Civitai Browser's own image cache

Connections are per-thread: scans and syncs run on several threads at once and
SQLite objects cannot cross between them.
"""
import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

from .migrations import run_migrations
from .models_ops import ModelsOps
from .images_ops import ImagesOps
from .browse_cache_ops import BrowserCacheOps


# The schema this code expects. Bumping it means adding a migration.
SCHEMA_VERSION = 14


class ModelsDatabase:
    """
    SQLite database for model metadata and images.

    A facade: it owns the connection and delegates the work to the operation
    modules, so the rest of the extension has one thing to import.
    """

    DB_NAME = "models.db"

    def __init__(self, extension_dir: str, custom_db_path: Optional[str] = None):
        """Initialize the database.

        Args:
            extension_dir: The extension directory (used as fallback for db location)
            custom_db_path: Optional full path to database file (including filename)
        """
        if custom_db_path:
            self.db_path = custom_db_path
            self.db_dir = os.path.dirname(custom_db_path)
        else:
            self.db_dir = extension_dir
            self.db_path = os.path.join(extension_dir, self.DB_NAME)

        self._local = threading.local()
        self._init_db()

        self._models = ModelsOps(self._cursor)
        self._images = ImagesOps(self._cursor)
        self._browser_cache = BrowserCacheOps(self._cursor)

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            # Wait for locks rather than failing, and use WAL so a read during
            # a long scan does not block.
            self._local.connection = sqlite3.connect(self.db_path, timeout=30.0)
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA journal_mode=WAL")
        return self._local.connection

    @contextmanager
    def _cursor(self):
        """Context manager for database cursor."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def _init_db(self):
        """Create the version table and run whatever migrations are missing."""
        with self._cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_info (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            cursor.execute("SELECT value FROM schema_info WHERE key = 'version'")
            row = cursor.fetchone()
            current_version = int(row[0]) if row else 0

            if current_version < SCHEMA_VERSION:
                run_migrations(cursor, current_version, SCHEMA_VERSION,
                               self.db_path, self.db_dir)

    # ==================== Models & versions ====================

    def upsert_civitai_model(self, model_data: Dict[str, Any]):
        """Insert or update a Civitai model record."""
        self._models.upsert_civitai_model(model_data)

    def get_civitai_model(self, model_id: int) -> Optional[Dict[str, Any]]:
        """Get a Civitai model by ID."""
        return self._models.get_civitai_model(model_id)

    def set_bookmark(self, model_id: int, bookmarked: bool) -> bool:
        """Set bookmark status for a model."""
        return self._models.set_bookmark(model_id, bookmarked)

    def upsert_version(self, version_data: Dict[str, Any]):
        """Insert or update a model version record."""
        self._models.upsert_version(version_data)

    def delete_version(self, file_path: str):
        """Delete a version record by file path."""
        self._models.delete_version(file_path)

    def set_lookup_failed(self, file_path: str, failed: bool = True):
        """
        Note whether Civitai knows this file, so a sync can stop retrying.

        Called with False once a lookup succeeds, so a model that turns up on
        Civitai later stops being marked.
        """
        stamp = datetime.now().isoformat() if failed else None
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE model_versions SET civitai_lookup_failed_at = ? WHERE file_path = ?",
                (stamp, file_path)
            )

    def count_lookup_failed(self) -> int:
        """How many files a sync will skip because Civitai did not know them."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM model_versions WHERE civitai_lookup_failed_at IS NOT NULL"
            )
            return cursor.fetchone()[0]

    def set_downloaded_at(self, file_path: str):
        """
        Record when a version was downloaded (called after a Civitai download).

        Uses the file's own modification time, which is when the download
        finished writing. Wall-clock "now" would instead capture when the
        follow-up sync completed - that trails the download by seconds for a
        small file and much longer for a large one, which reorders a batch of
        downloads relative to the order they actually arrived.

        Never overwrites an existing value: re-syncing a model must not rewrite
        the day it was obtained.
        """
        try:
            downloaded_at = datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat()
        except OSError:
            downloaded_at = datetime.now().isoformat()

        with self._cursor() as cursor:
            cursor.execute("""
                UPDATE model_versions
                SET downloaded_at = ?
                WHERE file_path = ? AND downloaded_at IS NULL
            """, (downloaded_at, file_path))

    def get_version(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get a version by file path."""
        return self._models.get_version(file_path)

    def get_versions_for_model(self, model_id: int) -> List[Dict[str, Any]]:
        """Get all local versions for a Civitai model."""
        return self._models.get_versions_for_model(model_id)

    def get_local_version_count(self, model_id: int) -> int:
        """Get count of local versions for a model."""
        return self._models.get_local_version_count(model_id)

    def query_models_grouped(
        self,
        search: Optional[str] = None,
        model_type: Optional[str] = None,
        base_model: Optional[str] = None,
        nsfw_levels: Optional[List[int]] = None,
        nsfw_mode: str = "max",
        has_civitai: Optional[bool] = None,
        is_bookmarked: Optional[bool] = None,
        min_versions: Optional[int] = None,
        commercial_use: Optional[str] = None,
        allow_derivatives: Optional[bool] = None,
        allow_different_license: Optional[bool] = None,
        sort_by: str = "file_modified",
        sort_order: str = "desc",
        limit: int = 50,
        offset: int = 0,
        preview_least_nsfw: bool = True
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Query models grouped by civitai_model_id."""
        return self._models.query_models_grouped(
            search=search,
            model_type=model_type,
            base_model=base_model,
            nsfw_levels=nsfw_levels,
            nsfw_mode=nsfw_mode,
            has_civitai=has_civitai,
            is_bookmarked=is_bookmarked,
            min_versions=min_versions,
            commercial_use=commercial_use,
            allow_derivatives=allow_derivatives,
            allow_different_license=allow_different_license,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
            preview_least_nsfw=preview_least_nsfw
        )

    def count_images_by_version(self, version_ids: Optional[List[int]] = None) -> Dict[int, int]:
        """How many images are cached per version. See db/images_ops.py."""
        return self._images.count_by_version(version_ids)

    def get_linked_versions(self, synced_before: Optional[str] = None) -> List[Dict[str, Any]]:
        """Local versions that already resolve to a Civitai model."""
        return self._models.get_linked_versions(synced_before)

    def get_all_version_paths(self) -> List[str]:
        """Get all version file paths in the database."""
        return self._models.get_all_version_paths()

    def get_distinct_values(self, column: str) -> List[str]:
        """Get distinct values for a column."""
        return self._models.get_distinct_values(column)

    def get_distinct_model_types(self) -> List[str]:
        """Get distinct model types."""
        return self._models.get_distinct_model_types()

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        return self._models.get_stats()

    # ==================== Image Operations (delegated) ====================

    def store_images(self, version_id: int, page: int, images: List[Dict[str, Any]]):
        """Store a page of images in the cache."""
        self._images.store_images(version_id, page, images)

    def get_images(
        self,
        version_id: int,
        page: Optional[int] = None,
        max_nsfw_level: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get cached images for a version, optionally filtered by NSFW level."""
        return self._images.get_images(version_id, page, max_nsfw_level)

    def get_all_images_for_version(
        self,
        version_id: int,
        max_nsfw_level: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all cached images for a version, optionally filtered by NSFW level."""
        return self._images.get_all_images_for_version(version_id, max_nsfw_level)

    def get_image_counts(
        self,
        version_id: int,
        max_nsfw_level: Optional[int] = None
    ) -> Dict[str, int]:
        """Get total and filtered image counts for a version."""
        return self._images.get_image_counts(version_id, max_nsfw_level)

    def get_cached_page_count(self, version_id: int) -> int:
        """Get how many pages have been cached for a version."""
        return self._images.get_cached_page_count(version_id)

    def get_max_nsfw_levels(self, version_ids: List[int]) -> Dict[int, int]:
        """Get max NSFW level for each version from cached images."""
        return self._images.get_max_nsfw_levels(version_ids)

    def get_max_nsfw_level(self, version_id: int) -> int:
        """Get max NSFW level for a single version."""
        return self._images.get_max_nsfw_level(version_id)

    def clear_version_images(self, version_id: int):
        """Clear all cached images for a version."""
        self._images.clear_version(version_id)

    def update_version_images_state(
        self,
        version_id: int,
        next_cursor: Optional[str],
        update_sync_date: bool = True
    ):
        """
        Update image sync state for a version.

        Args:
            version_id: Civitai version ID (the 'id' column in model_versions).
            next_cursor: Next cursor for pagination (None if all loaded).
            update_sync_date: Whether to update images_sync_last_date.
        """
        with self._cursor() as cursor:
            if update_sync_date:
                cursor.execute("""
                    UPDATE model_versions
                    SET next_images_cursor = ?,
                        images_sync_last_date = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (next_cursor, version_id))
            else:
                cursor.execute("""
                    UPDATE model_versions
                    SET next_images_cursor = ?
                    WHERE id = ?
                """, (next_cursor, version_id))

    def get_version_by_id(self, version_id: int) -> Optional[Dict[str, Any]]:
        """Get a version record by its Civitai version ID."""
        return self._models.get_version_by_id(version_id)

    def get_image_cache_stats(self) -> Dict[str, Any]:
        """Get image cache statistics."""
        stats = self._images.get_cache_stats()
        # Add db size
        db_size = 0
        if os.path.exists(self.db_path):
            db_size = os.path.getsize(self.db_path) / (1024 * 1024)
        stats["db_size_mb"] = round(db_size, 2)
        return stats

    # ==================== Browser Cache Operations (delegated) ====================

    def get_cached_browse_images(self, version_id: int) -> List[Dict[str, Any]]:
        """Get cached images for Civitai browser."""
        return self._browser_cache.get_cached_images(version_id)

    def store_browse_images(
        self,
        model_id: int,
        version_id: int,
        images: List[Dict[str, Any]]
    ):
        """Store images in Civitai browser cache."""
        self._browser_cache.store_images(model_id, version_id, images)

    def update_browse_images(self, version_id: int, images: List[Dict[str, Any]]):
        """Update payloads of already-cached Civitai browser images."""
        self._browser_cache.update_image_data(version_id, images)

    def get_browse_cursor(self, version_id: int) -> Optional[str]:
        """Get cached cursor for Civitai browser pagination."""
        return self._browser_cache.get_cursor(version_id)

    def store_browse_cursor(
        self,
        model_id: int,
        version_id: int,
        cursor_value: str
    ):
        """Store cursor in Civitai browser cache."""
        self._browser_cache.store_cursor(model_id, version_id, cursor_value)

    def clear_browse_version_cache(self, version_id: int):
        """Clear all cached data for a version in Civitai browser."""
        self._browser_cache.clear_version_cache(version_id)

    def get_browse_cached_image_count(self, version_id: int) -> int:
        """Get count of cached images for a version in Civitai browser."""
        return self._browser_cache.get_cached_image_count(version_id)

    # ==================== Combined Operations ====================

    def clear_all(self):
        """Clear all records (models and images)."""
        self._models.clear_all()
        self._images.clear_all()

    def set_metadata(self, key: str, value: str):
        """Set a metadata value in schema_info."""
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO schema_info (key, value) VALUES (?, ?)",
                (key, value)
            )

    def get_metadata(self, key: str) -> Optional[str]:
        """Get a metadata value from schema_info."""
        with self._cursor() as cursor:
            cursor.execute("SELECT value FROM schema_info WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else None

    def close(self):
        """Close the database connection."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None


# Global database instance
_db_instance: Optional[ModelsDatabase] = None
_db_lock = threading.Lock()


def get_models_db() -> ModelsDatabase:
    """Get the global models database instance."""
    global _db_instance

    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                # up out of db/, then out of model_manager/, to the extension root
                ext_dir = os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))))

                # Check for custom database path in settings
                custom_db_path = None
                try:
                    from modules import shared
                    custom_path = getattr(shared.opts, 'model_manager_database_path', '')
                    if custom_path and custom_path.strip():
                        custom_db_path = custom_path.strip()
                        print(f"[ModelManager] Using custom database path: {custom_db_path}")
                except Exception as e:
                    print(f"[ModelManager] Could not read custom database path setting: {e}")

                _db_instance = ModelsDatabase(ext_dir, custom_db_path)

    return _db_instance
