"""
Internal module for image table operations.

This module handles images table operations.
Used by ModelsDatabase facade - do not import directly.
"""
import json
from typing import Optional, List, Dict, Any, Callable


class ImagesOps:
    """
    Operations for images table.

    Receives a cursor factory from the parent facade.
    """

    def __init__(self, cursor_factory: Callable):
        """
        Initialize with cursor factory from facade.

        Args:
            cursor_factory: Callable that returns a context manager yielding a cursor.
        """
        self._cursor = cursor_factory

    # ==================== Images ====================

    @staticmethod
    def calculate_effective_nsfw_level(img: Dict[str, Any]) -> int:
        """
        Calculate effective NSFW level from image data.

        Uses max of:
        - browsingLevel (primary, integer from API)
        - nsfwLevel (string: None=1, Soft=4, Mature=8, X=16)
        - nsfw boolean: true=2, false=1

        NSFW levels: 1=PG, 2=PG-13, 4=R, 8=X, 16=XXX, 32=Blocked, 64=Unknown

        Args:
            img: Image dict from Civitai API.

        Returns:
            Effective NSFW level.
        """
        # browsingLevel is the primary source (integer)
        browsing_level = img.get("browsingLevel") or 64  # Default to Unknown

        # nsfwLevel string mapping
        nsfw_level_str = img.get("nsfwLevel", "")
        nsfw_level_map = {
            "None": 1,
            "Soft": 4,
            "Mature": 8,
            "X": 16,
        }
        nsfw_level = nsfw_level_map.get(nsfw_level_str, 64)  # Default to Unknown

        # nsfw boolean
        nsfw_bool = 2 if img.get("nsfw") else 1

        return max(browsing_level, nsfw_level, nsfw_bool)

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
                    url = img.get("url")
                    width = img.get("width")
                    height = img.get("height")
                    effective_nsfw_level = self.calculate_effective_nsfw_level(img)
                    created_at = img.get("createdAt")

                    cursor.execute("""
                        INSERT OR REPLACE INTO images
                        (id, version_id, page, url, width, height, effective_nsfw_level, created_at, data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (img_id, version_id, page, url, width, height, effective_nsfw_level, created_at, json.dumps(img)))

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

    # ==================== NSFW Levels ====================

    def get_max_nsfw_levels(self, version_ids: List[int]) -> Dict[int, int]:
        """
        Get max NSFW level for each version from cached images.

        Args:
            version_ids: List of Civitai version IDs

        Returns:
            Dict mapping version_id to max effective_nsfw_level
        """
        if not version_ids:
            return {}

        with self._cursor() as cursor:
            placeholders = ','.join(['?'] * len(version_ids))
            cursor.execute(f"""
                SELECT version_id, MAX(effective_nsfw_level) as max_nsfw
                FROM images
                WHERE version_id IN ({placeholders})
                GROUP BY version_id
            """, version_ids)

            return {row["version_id"]: row["max_nsfw"] or 64 for row in cursor.fetchall()}

    def get_max_nsfw_level(self, version_id: int) -> int:
        """
        Get max NSFW level for a single version from cached images.

        Args:
            version_id: Civitai version ID

        Returns:
            Max effective_nsfw_level (default 64/Unknown if no images)
        """
        result = self.get_max_nsfw_levels([version_id])
        return result.get(version_id, 64)

    # ==================== Cleanup ====================

    def clear_version(self, version_id: int):
        """
        Clear all cached images for a version.

        Args:
            version_id: Civitai model version ID.
        """
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM images WHERE version_id = ?", (version_id,))

    def clear_all(self):
        """Clear all image data."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM images")

    # ==================== Stats ====================

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get image cache statistics.

        Returns:
            Dict with total_images, total_versions.
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM images")
            total_images = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(DISTINCT version_id) as count FROM images")
            total_versions = cursor.fetchone()["count"]

        return {
            "total_images": total_images,
            "total_versions": total_versions
        }
