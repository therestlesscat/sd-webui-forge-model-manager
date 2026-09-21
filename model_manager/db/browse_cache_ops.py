"""
Internal module for Civitai browser cache operations.

This module handles civitai_browser_cache table operations.
Used by ModelsDatabase facade - do not import directly.
"""
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable


class BrowserCacheOps:
    """
    Operations for civitai_browser_cache table.

    Receives a cursor factory from the parent facade.
    """

    def __init__(self, cursor_factory: Callable):
        """
        Initialize with cursor factory from facade.

        Args:
            cursor_factory: Callable that returns a context manager yielding a cursor.
        """
        self._cursor = cursor_factory

    # ==================== Images Cache ====================

    def get_cached_images(self, version_id: int) -> List[Dict[str, Any]]:
        """
        Get cached images for a version.

        Args:
            version_id: Civitai version ID.

        Returns:
            List of image data dicts, ordered by cached_at.
        """
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT data FROM civitai_browser_cache
                WHERE version_id = ? AND type = 'image'
                ORDER BY cached_at ASC
            """, (version_id,))

            return [json.loads(row["data"]) for row in cursor.fetchall()]

    def store_images(
        self,
        model_id: int,
        version_id: int,
        images: List[Dict[str, Any]]
    ):
        """
        Store images in cache.

        Args:
            model_id: Civitai model ID.
            version_id: Civitai version ID.
            images: List of image data dicts.
        """
        if not images:
            return

        cached_at = datetime.now().isoformat()

        with self._cursor() as cursor:
            for img in images:
                img_id = img.get("id")
                if img_id:
                    cursor.execute("""
                        INSERT OR REPLACE INTO civitai_browser_cache
                        (model_id, version_id, type, data_id, cached_at, data)
                        VALUES (?, ?, 'image', ?, ?, ?)
                    """, (
                        model_id,
                        version_id,
                        str(img_id),
                        cached_at,
                        json.dumps(img)
                    ))

    def update_image_data(self, version_id: int, images: List[Dict[str, Any]]):
        """
        Update the stored payload of already-cached images.

        Used when re-fetching generation metadata for rows that were cached
        while the API was returning `meta: null`. Keeps model_id and cached_at.

        Args:
            version_id: Civitai version ID.
            images: Image data dicts to write back.
        """
        if not images:
            return

        with self._cursor() as cursor:
            for img in images:
                img_id = img.get("id")
                if img_id:
                    cursor.execute("""
                        UPDATE civitai_browser_cache
                        SET data = ?
                        WHERE version_id = ? AND type = 'image' AND data_id = ?
                    """, (json.dumps(img), version_id, str(img_id)))

    # ==================== Cursor Cache ====================

    def get_cursor(self, version_id: int) -> Optional[str]:
        """
        Get cached cursor for a version.

        Args:
            version_id: Civitai version ID.

        Returns:
            Cursor string or None if not cached.
        """
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT data FROM civitai_browser_cache
                WHERE version_id = ? AND type = 'cursor' AND data_id = 'cursor'
            """, (version_id,))

            row = cursor.fetchone()
            return row["data"] if row else None

    def store_cursor(
        self,
        model_id: int,
        version_id: int,
        cursor_value: str
    ):
        """
        Store cursor in cache.

        Args:
            model_id: Civitai model ID.
            version_id: Civitai version ID.
            cursor_value: Cursor string from Civitai API.
        """
        cached_at = datetime.now().isoformat()

        with self._cursor() as cursor:
            cursor.execute("""
                INSERT OR REPLACE INTO civitai_browser_cache
                (model_id, version_id, type, data_id, cached_at, data)
                VALUES (?, ?, 'cursor', 'cursor', ?, ?)
            """, (model_id, version_id, cached_at, cursor_value))

    # ==================== Cache Management ====================

    def clear_version_cache(self, version_id: int):
        """
        Clear all cached data for a version.

        Args:
            version_id: Civitai version ID.
        """
        with self._cursor() as cursor:
            cursor.execute("""
                DELETE FROM civitai_browser_cache
                WHERE version_id = ?
            """, (version_id,))

    def get_cached_image_count(self, version_id: int) -> int:
        """
        Get count of cached images for a version.

        Args:
            version_id: Civitai version ID.

        Returns:
            Number of cached images.
        """
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) as count FROM civitai_browser_cache
                WHERE version_id = ? AND type = 'image'
            """, (version_id,))

            row = cursor.fetchone()
            return row["count"] if row else 0
