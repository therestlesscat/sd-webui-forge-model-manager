"""
SQLite cache for storing Civitai model images.

All images are stored here during sync and load-more operations.
Uses page-based pagination for simplicity and reliability.
"""
import os
import json
import sqlite3
import threading
from typing import Optional, List, Dict, Any
from contextlib import contextmanager


class ImagesCache:
    """
    SQLite-based cache for model images.

    Schema:
        images (
            id INTEGER PRIMARY KEY,  -- Civitai image ID
            version_id INTEGER,      -- Civitai model version ID
            page INTEGER,            -- Page number (1 = first page from sync)
            data TEXT,               -- Full image JSON
            created_at TIMESTAMP
        )

        pagination (
            version_id INTEGER PRIMARY KEY,
            total_count INTEGER,     -- Total images available on Civitai
            total_pages INTEGER,     -- Total pages available
            fetched_pages INTEGER,   -- How many pages we've fetched (1 = just sync)
            updated_at TIMESTAMP
        )
    """

    DB_NAME = "images_cache.db"

    def __init__(self, extension_dir: str):
        """
        Initialize the cache.

        Args:
            extension_dir: Path to the extension directory.
        """
        self.db_path = os.path.join(extension_dir, self.DB_NAME)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.db_path)
            self._local.connection.row_factory = sqlite3.Row
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
        """Create database tables if they don't exist."""
        with self._cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY,
                    version_id INTEGER NOT NULL,
                    page INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_images_version
                ON images(version_id, page)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pagination (
                    version_id INTEGER PRIMARY KEY,
                    total_count INTEGER DEFAULT 0,
                    total_pages INTEGER DEFAULT 1,
                    fetched_pages INTEGER DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migrate old cursors table if exists
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='cursors'
            """)
            if cursor.fetchone():
                cursor.execute("DROP TABLE cursors")

    def get_pagination_state(self, version_id: int) -> Optional[Dict[str, Any]]:
        """
        Get pagination state for a version.

        Args:
            version_id: Civitai model version ID.

        Returns:
            Dict with total_count, total_pages, fetched_pages, or None.
        """
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM pagination WHERE version_id = ?",
                (version_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "version_id": row["version_id"],
                    "total_count": row["total_count"],
                    "total_pages": row["total_pages"],
                    "fetched_pages": row["fetched_pages"]
                }
        return None

    def update_pagination_state(
        self,
        version_id: int,
        total_count: int,
        total_pages: int,
        fetched_pages: int
    ):
        """
        Update pagination state for a version.

        Args:
            version_id: Civitai model version ID.
            total_count: Total images available.
            total_pages: Total pages available.
            fetched_pages: How many pages we've fetched.
        """
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT OR REPLACE INTO pagination
                (version_id, total_count, total_pages, fetched_pages, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (version_id, total_count, total_pages, fetched_pages))

    def store_images(
        self,
        version_id: int,
        page: int,
        images: List[Dict[str, Any]]
    ):
        """
        Store a page of images in the cache.

        Args:
            version_id: Civitai model version ID.
            page: Page number (1 = first load-more, 2 = second, etc).
            images: List of image dicts to store.
        """
        with self._cursor() as cursor:
            for img in images:
                img_id = img.get("id")
                if img_id:
                    cursor.execute("""
                        INSERT OR REPLACE INTO images (id, version_id, page, data)
                        VALUES (?, ?, ?, ?)
                    """, (img_id, version_id, page, json.dumps(img)))

    def get_images(
        self,
        version_id: int,
        page: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get cached images for a version.

        Args:
            version_id: Civitai model version ID.
            page: Specific page number, or None for all pages.

        Returns:
            List of image dicts.
        """
        with self._cursor() as cursor:
            if page is not None:
                cursor.execute(
                    "SELECT data FROM images WHERE version_id = ? AND page = ? ORDER BY id",
                    (version_id, page)
                )
            else:
                cursor.execute(
                    "SELECT data FROM images WHERE version_id = ? ORDER BY page, id",
                    (version_id,)
                )

            rows = cursor.fetchall()
            return [json.loads(row["data"]) for row in rows]

    def get_all_images_for_version(self, version_id: int) -> List[Dict[str, Any]]:
        """
        Get all cached images for a version (all pages).

        Args:
            version_id: Civitai model version ID.

        Returns:
            List of all cached image dicts.
        """
        return self.get_images(version_id, page=None)

    def get_cached_page_count(self, version_id: int) -> int:
        """
        Get how many pages have been cached for a version.

        Args:
            version_id: Civitai model version ID.

        Returns:
            Number of distinct pages cached.
        """
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT MAX(page) as max_page FROM images WHERE version_id = ?",
                (version_id,)
            )
            row = cursor.fetchone()
            return row["max_page"] or 0

    def clear_version(self, version_id: int):
        """
        Clear all cached data for a version.

        Args:
            version_id: Civitai model version ID.
        """
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM images WHERE version_id = ?", (version_id,))
            cursor.execute("DELETE FROM pagination WHERE version_id = ?", (version_id,))

    def clear_all(self):
        """Clear all cached data."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM images")
            cursor.execute("DELETE FROM pagination")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with total_images, total_versions, db_size_mb.
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM images")
            total_images = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(DISTINCT version_id) as count FROM images")
            total_versions = cursor.fetchone()["count"]

        db_size = 0
        if os.path.exists(self.db_path):
            db_size = os.path.getsize(self.db_path) / (1024 * 1024)  # MB

        return {
            "total_images": total_images,
            "total_versions": total_versions,
            "db_size_mb": round(db_size, 2)
        }

    def close(self):
        """Close the database connection."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None


# Global cache instance
_cache_instance: Optional[ImagesCache] = None
_cache_lock = threading.Lock()


def get_images_cache() -> ImagesCache:
    """
    Get the global images cache instance.

    Returns:
        ImagesCache instance.
    """
    global _cache_instance

    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                # Get extension directory
                ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                _cache_instance = ImagesCache(ext_dir)

    return _cache_instance
