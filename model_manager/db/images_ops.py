"""
Internal module for image table operations.

This module handles images table operations.
Used by ModelsDatabase facade - do not import directly.
"""
import json
from ..civitai.prompt_filter import MIN_PROMPT_LENGTH
from ..nsfw import SFW_MAX, UNKNOWN, image_level
from typing import Tuple, Optional, List, Dict, Any, Callable



# The order a gallery shows a version's images in: Civitai's, as stored in
# `position`, page by page. id only breaks ties, and orders rows stored before
# positions were kept (schema v19) - they have none until the next sync.
GALLERY_ORDER = "page, position, id"

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
        """How explicit an image is. The rule lives in model_manager.nsfw."""
        return image_level(img)

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
            images: List of image dicts to store, in the order Civitai gave
                them. That order is kept as `position`, because it is
                Civitai's ranking and the id says nothing about it.
        """
        with self._cursor() as cursor:
            for position, img in enumerate(images):
                img_id = img.get("id")
                if img_id:
                    url = img.get("url")
                    width = img.get("width")
                    height = img.get("height")
                    effective_nsfw_level = self.calculate_effective_nsfw_level(img)
                    created_at = img.get("createdAt")

                    cursor.execute("""
                        INSERT OR REPLACE INTO images
                        (id, version_id, page, position, url, width, height,
                         effective_nsfw_level, created_at, data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (img_id, version_id, page, position, url, width, height,
                          effective_nsfw_level, created_at, json.dumps(img)))

    def restamp_levels(self) -> Tuple[int, int, int]:
        """
        Judge every stored image again, as image_level() now would.

        A level is stamped when an image is stored, so a change to how images
        are judged - the prompt words, above all - leaves the rows on the old
        verdict. The payload is stored beside it, so nothing is refetched.
        A version's safe cover that is now an unsafe image is cleared, and
        the grid falls back to the version's first image that is still safe
        until a scan or sync picks the cover again.

        Returns:
            (images changed, images read, safe covers cleared)
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT id, version_id, effective_nsfw_level, data FROM images")
            rows = cursor.fetchall()
        changed = []
        for image_id, version_id, stored, data in rows:
            if not data:
                continue
            try:
                level = image_level(json.loads(data))
            except (ValueError, TypeError):
                continue
            if level != stored:
                changed.append((level, image_id, version_id))
        with self._cursor() as cursor:
            cursor.executemany(
                "UPDATE images SET effective_nsfw_level = ? WHERE id = ? AND version_id = ?",
                changed)
            cursor.execute(
                "UPDATE model_versions SET safe_cover_url = '' WHERE safe_cover_url IN"
                " (SELECT url FROM images WHERE effective_nsfw_level > ?)", (SFW_MAX,))
            covers = cursor.rowcount
        return len(changed), len(rows), covers

    # A prompt is stored inside the image's JSON, so it is read back out with
    # json_extract rather than given a column. Measured over 101,369 images, a
    # full scan of every one takes about a second; a gallery is a few hundred
    # rows of that, so no index earns its keep here.
    _PROMPT = "TRIM(COALESCE(json_extract(data, '$.meta.prompt'), ''))"

    def _prompt_filter(self, require_prompt: bool) -> str:
        """The SQL for "has a prompt worth reading", or nothing."""
        if not require_prompt:
            return ""
        return " AND LENGTH(%s) >= %d" % (self._PROMPT, MIN_PROMPT_LENGTH)

    def get_images(
        self,
        version_id: int,
        page: Optional[int] = None,
        max_nsfw_level: Optional[int] = None,
        require_prompt: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get cached images for a version.

        Args:
            version_id: Civitai model version ID.
            page: Specific page number, or None for all pages.
            max_nsfw_level: If set, only return images with effective_nsfw_level <= this value.
                           Use 5 for SFW only (PG + PG-13).
            require_prompt: Drop images whose prompt is too short to be one.

        Returns:
            List of image dicts.
        """
        with self._cursor() as cursor:
            if max_nsfw_level is not None:
                nsfw_filter = " AND effective_nsfw_level <= ?"
                nsfw_param = (max_nsfw_level,)
            else:
                nsfw_filter = ""
                nsfw_param = ()

            nsfw_filter += self._prompt_filter(require_prompt)

            if page is not None:
                cursor.execute(
                    f"SELECT data FROM images WHERE version_id = ? AND page = ?{nsfw_filter} "
                    f"ORDER BY {GALLERY_ORDER}",
                    (version_id, page) + nsfw_param
                )
            else:
                cursor.execute(
                    f"SELECT data FROM images WHERE version_id = ?{nsfw_filter} "
                    f"ORDER BY {GALLERY_ORDER}",
                    (version_id,) + nsfw_param
                )

            rows = cursor.fetchall()
            return [json.loads(row["data"]) for row in rows]

    def get_all_images_for_version(
        self,
        version_id: int,
        max_nsfw_level: Optional[int] = None,
        require_prompt: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get all cached images for a version (all pages).

        Args:
            version_id: Civitai model version ID.
            max_nsfw_level: If set, only return images with effective_nsfw_level <= this value.

        Returns:
            List of all cached image dicts.
        """
        return self.get_images(version_id, page=None, max_nsfw_level=max_nsfw_level,
                               require_prompt=require_prompt)

    def get_image_counts(self, version_id: int, max_nsfw_level: Optional[int] = None,
                         require_prompt: bool = False) -> Dict[str, int]:
        """
        Get total and filtered image counts for a version.

        Args:
            version_id: Civitai model version ID.
            max_nsfw_level: If set, count images with effective_nsfw_level <= this value.

        Returns:
            Dict with 'total' and 'filtered' counts, and 'hidden' (total - filtered).
        """
        with self._cursor() as cursor:
            # Total count
            cursor.execute(
                "SELECT COUNT(*) FROM images WHERE version_id = ?",
                (version_id,)
            )
            total = cursor.fetchone()[0]

            # What each filter hides on its own, so the panel can say which
            # one is responsible rather than reporting one number for both.
            nsfw_clause = "" if max_nsfw_level is None else " AND effective_nsfw_level <= ?"
            nsfw_param = () if max_nsfw_level is None else (max_nsfw_level,)
            prompt_clause = self._prompt_filter(require_prompt)

            cursor.execute(
                "SELECT COUNT(*) FROM images WHERE version_id = ?" + nsfw_clause + prompt_clause,
                (version_id,) + nsfw_param
            )
            filtered = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM images WHERE version_id = ?" + nsfw_clause,
                (version_id,) + nsfw_param
            )
            nsfw_kept = cursor.fetchone()[0]

            # What each gallery switch is acting on right now: the number beside
            # it, and the number its banner states - the two must always agree.
            # Each counts its own kind among the images the *other* switch lets
            # through, so it is the number a click would hide or bring back,
            # and it moves when the other switch does. It is not 0 when the
            # switch is showing everything: it is then how many it is showing.
            cursor.execute(
                "SELECT COUNT(*) FROM images WHERE version_id = ? AND effective_nsfw_level > ?"
                + prompt_clause,
                (version_id, SFW_MAX)
            )
            nsfw_count = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM images WHERE version_id = ?" + nsfw_clause
                + " AND LENGTH(%s) < %d" % (self._PROMPT, MIN_PROMPT_LENGTH),
                (version_id,) + nsfw_param
            )
            promptless_count = cursor.fetchone()[0]

            return {
                "total": total,
                "filtered": filtered,
                "hidden_nsfw": total - nsfw_kept,
                "hidden_promptless": nsfw_kept - filtered,
                "hidden": total - filtered,
                "nsfw_count": nsfw_count,
                "promptless_count": promptless_count,
            }

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

            return {row["version_id"]: row["max_nsfw"] or UNKNOWN for row in cursor.fetchall()}

    def get_max_nsfw_level(self, version_id: int) -> int:
        """
        Get max NSFW level for a single version from cached images.

        Args:
            version_id: Civitai version ID

        Returns:
            Max effective_nsfw_level (default 64/Unknown if no images)
        """
        result = self.get_max_nsfw_levels([version_id])
        return result.get(version_id, UNKNOWN)

    # ==================== Cleanup ====================

    def count_by_version(self, version_ids: Optional[List[int]] = None) -> Dict[int, int]:
        """
        How many images are cached for each version.

        The sync dialog costs a gallery refresh from these: generation data is
        fetched 30 ids per request, so what a refresh will cost depends on how
        many images the galleries hold. Last time's counts are the only guide
        available before the fetch, and galleries change slowly.

        Args:
            version_ids: Restrict to these versions, or None for every one.

        Returns:
            Version id -> image count. Versions with no cached images are absent.
        """
        with self._cursor() as cursor:
            if version_ids is None:
                cursor.execute("SELECT version_id, COUNT(*) AS n FROM images GROUP BY version_id")
            else:
                ids = [int(v) for v in version_ids if v]
                if not ids:
                    return {}
                cursor.execute(
                    "SELECT version_id, COUNT(*) AS n FROM images WHERE version_id IN (%s)"
                    " GROUP BY version_id" % ",".join("?" * len(ids)),
                    ids,
                )
            return {row["version_id"]: row["n"] for row in cursor.fetchall()}

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
