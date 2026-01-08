"""
Internal module for model and version table operations.

This module handles civitai_models and model_versions tables.
Used by ModelsDatabase facade - do not import directly.
"""
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Callable
from contextlib import contextmanager


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

    def upsert_civitai_model(self, model_data: Dict[str, Any]):
        """Insert or update a Civitai model record. Preserves is_bookmarked on update."""
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT INTO civitai_models (
                    id, name, description, type, nsfw, nsfw_level, tags,
                    creator_username, creator_image_url,
                    stats_download_count, stats_thumbs_up, stats_rating,
                    allow_no_credit, allow_commercial_use, allow_derivatives,
                    allow_different_license, supports_generation, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    type = excluded.type,
                    nsfw = excluded.nsfw,
                    nsfw_level = excluded.nsfw_level,
                    tags = excluded.tags,
                    creator_username = excluded.creator_username,
                    creator_image_url = excluded.creator_image_url,
                    stats_download_count = excluded.stats_download_count,
                    stats_thumbs_up = excluded.stats_thumbs_up,
                    stats_rating = excluded.stats_rating,
                    allow_no_credit = excluded.allow_no_credit,
                    allow_commercial_use = excluded.allow_commercial_use,
                    allow_derivatives = excluded.allow_derivatives,
                    allow_different_license = excluded.allow_different_license,
                    supports_generation = excluded.supports_generation,
                    updated_at = excluded.updated_at
            """, (
                model_data.get("id"),
                model_data.get("name"),
                model_data.get("description"),
                model_data.get("type", "Checkpoint"),
                1 if model_data.get("nsfw") else 0,
                model_data.get("nsfw_level", 64),  # Default to Unknown
                json.dumps(model_data.get("tags", [])),
                model_data.get("creator_username"),
                model_data.get("creator_image_url"),
                model_data.get("stats_download_count", 0),
                model_data.get("stats_thumbs_up", 0),
                model_data.get("stats_rating", 0),
                1 if model_data.get("allow_no_credit", True) else 0,
                model_data.get("allow_commercial_use"),
                1 if model_data.get("allow_derivatives", True) else 0,
                1 if model_data.get("allow_different_license", True) else 0,
                1 if model_data.get("supports_generation") else 0,
                datetime.now().isoformat()
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
        """Insert or update a model version record."""
        with self._cursor() as cursor:
            # Handle file_hashes - can be dict or already JSON string
            file_hashes = version_data.get("file_hashes")
            if isinstance(file_hashes, dict):
                file_hashes = json.dumps(file_hashes)

            cursor.execute("""
                INSERT OR REPLACE INTO model_versions (
                    id, model_id, version_name, base_model, published_at, created_at,
                    nsfw_level, trained_words, description,
                    stats_download_count, stats_thumbs_up,
                    file_path, file_name, file_size, file_hashes, file_modified, file_extension,
                    has_civitai_data, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                version_data.get("id"),
                version_data.get("model_id"),
                version_data.get("version_name"),
                version_data.get("base_model"),
                version_data.get("published_at"),
                version_data.get("created_at"),
                version_data.get("nsfw_level", 64),  # Default to Unknown
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
                datetime.now().isoformat()
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
        sort_by: str = "file_modified",
        sort_order: str = "desc",
        limit: int = 50,
        offset: int = 0,
        preview_least_nsfw: bool = True
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Query models grouped by civitai_model_id.
        Returns latest version per group with version count.

        Args:
            preview_least_nsfw: If True, preview is image with lowest NSFW level.
                               If False, preview is most recent image by created_at.
        """
        conditions = []
        params = []

        # Build WHERE conditions for versions
        if search:
            conditions.append("""(
                v.file_name LIKE ? OR
                v.trained_words LIKE ? OR
                COALESCE(m.name, v.file_name) LIKE ? OR
                COALESCE(m.tags, '[]') LIKE ?
            )""")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

        if model_type:
            conditions.append("COALESCE(m.type, 'Unknown') = ?")
            params.append(model_type)

        if base_model:
            conditions.append("v.base_model = ?")
            params.append(base_model)

        if nsfw_levels:
            # Effective NSFW level = max(model nsfw, version nsfw, max image nsfw)
            # Image effective_nsfw_level is pre-calculated at sync time
            effective_level_expr = """MAX(
                COALESCE(m.nsfw_level, 64),
                COALESCE(v.nsfw_level, 64),
                COALESCE((
                    SELECT MAX(effective_nsfw_level) FROM images WHERE version_id = v.id
                ), 64)
            )"""

            if nsfw_mode == "contains":
                # Contains mode: show models with exact match of combined levels
                combined_mask = sum(nsfw_levels)
                conditions.append(f"({effective_level_expr}) = ?")
                params.append(combined_mask)
            else:
                # Max mode (default): show models whose highest level <= max selected
                max_level = max(nsfw_levels)
                conditions.append(f"({effective_level_expr}) < ?")
                params.append(max_level * 2)

        if has_civitai is not None:
            conditions.append("v.has_civitai_data = ?")
            params.append(1 if has_civitai else 0)

        if is_bookmarked is not None:
            conditions.append("COALESCE(m.is_bookmarked, 0) = ?")
            params.append(1 if is_bookmarked else 0)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Validate sort field
        valid_sort_fields = {
            "name": "COALESCE(cm_name, file_name)",
            "display_name": "COALESCE(cm_name, file_name)",
            "file_name": "file_name",
            "file_size": "file_size",
            "file_modified": "file_modified",
            "base_model": "base_model",
            "nsfw_level": "nsfw_level",
            "rating": "COALESCE(cm_stats_rating, 0)",
            "download_count": "COALESCE(cm_stats_download_count, stats_download_count)",
            "published_at": "published_at",
            "scanned_at": "scanned_at",
            "downloaded_at": "downloaded_at",
            "updated_at": "cm_updated_at"
        }
        sort_field = valid_sort_fields.get(sort_by, "file_modified")
        sort_dir = "DESC" if sort_order.lower() == "desc" else "ASC"

        # Build outer WHERE clause (filters on CTE results)
        outer_conditions = ["rn = 1"]
        outer_params = []
        if min_versions is not None and min_versions > 1:
            outer_conditions.append("local_version_count >= ?")
            outer_params.append(min_versions)
        outer_where = " AND ".join(outer_conditions)

        # Build preview subquery based on setting
        if preview_least_nsfw:
            preview_subquery = """(
                SELECT url FROM images
                WHERE version_id = v.id
                ORDER BY effective_nsfw_level ASC, created_at DESC, id DESC
                LIMIT 1
            )"""
        else:
            preview_subquery = """(
                SELECT url FROM images
                WHERE version_id = v.id
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            )"""

        # Query for latest version per model group
        query = f"""
            WITH ranked AS (
                SELECT
                    v.*,
                    m.id as cm_id,
                    m.name as cm_name,
                    m.description as cm_description,
                    m.type as cm_type,
                    m.nsfw as cm_nsfw,
                    m.nsfw_level as cm_nsfw_level,
                    m.tags as cm_tags,
                    m.creator_username as cm_creator_username,
                    m.creator_image_url as cm_creator_image_url,
                    m.stats_download_count as cm_stats_download_count,
                    m.stats_thumbs_up as cm_stats_thumbs_up,
                    m.stats_rating as cm_stats_rating,
                    m.allow_no_credit as cm_allow_no_credit,
                    m.allow_commercial_use as cm_allow_commercial_use,
                    m.allow_derivatives as cm_allow_derivatives,
                    m.allow_different_license as cm_allow_different_license,
                    m.supports_generation as cm_supports_generation,
                    m.is_bookmarked as cm_is_bookmarked,
                    m.updated_at as cm_updated_at,
                    COALESCE((
                        SELECT MAX(effective_nsfw_level) FROM images WHERE version_id = v.id
                    ), 64) as max_image_nsfw,
                    {preview_subquery} as preview_url,
                    ROW_NUMBER() OVER (
                        PARTITION BY COALESCE(v.model_id, v.file_path)
                        ORDER BY v.published_at DESC NULLS LAST
                    ) as rn,
                    COUNT(*) OVER (
                        PARTITION BY COALESCE(v.model_id, v.file_path)
                    ) as local_version_count
                FROM model_versions v
                LEFT JOIN civitai_models m ON v.model_id = m.id
                WHERE {where_clause}
            )
            SELECT * FROM ranked WHERE {outer_where}
            ORDER BY {sort_field} {sort_dir}
        """

        # Get total count
        count_query = f"""
            WITH ranked AS (
                SELECT
                    v.file_path,
                    ROW_NUMBER() OVER (
                        PARTITION BY COALESCE(v.model_id, v.file_path)
                        ORDER BY v.published_at DESC NULLS LAST
                    ) as rn,
                    COUNT(*) OVER (
                        PARTITION BY COALESCE(v.model_id, v.file_path)
                    ) as local_version_count
                FROM model_versions v
                LEFT JOIN civitai_models m ON v.model_id = m.id
                WHERE {where_clause}
            )
            SELECT COUNT(*) FROM ranked WHERE {outer_where}
        """

        # Combine inner params (WHERE clause) with outer params (version count filter)
        all_params = params + outer_params

        with self._cursor() as cursor:
            cursor.execute(count_query, all_params)
            total_count = cursor.fetchone()[0]

        with self._cursor() as cursor:
            paginated_query = f"{query} LIMIT ? OFFSET ?"
            cursor.execute(paginated_query, all_params + [limit, offset])
            rows = cursor.fetchall()

        models = [self._grouped_row_to_dict(row) for row in rows]
        return models, total_count

    # ==================== Utility Methods ====================

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
            "allow_no_credit": bool(row["allow_no_credit"]),
            "allow_commercial_use": row["allow_commercial_use"],
            "allow_derivatives": bool(row["allow_derivatives"]),
            "allow_different_license": bool(row["allow_different_license"]),
            "supports_generation": bool(row["supports_generation"]),
            "updated_at": row["updated_at"],
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
        }

    def _grouped_row_to_dict(self, row) -> Dict[str, Any]:
        """Convert a grouped query row (version + model) to a dictionary."""
        result = {
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
            "preview_url": row["preview_url"] if "preview_url" in row.keys() else None,
            "has_civitai_data": bool(row["has_civitai_data"]),
            "scanned_at": row["scanned_at"],
            "downloaded_at": row["downloaded_at"] if "downloaded_at" in row.keys() else None,
            "next_images_cursor": row["next_images_cursor"] if "next_images_cursor" in row.keys() else None,
            "images_sync_last_date": row["images_sync_last_date"] if "images_sync_last_date" in row.keys() else None,
            "local_version_count": row["local_version_count"],
            "max_image_nsfw": row["max_image_nsfw"],
            "is_bookmarked": bool(row["cm_is_bookmarked"]) if row["cm_is_bookmarked"] else False,
            "updated_at": row["cm_updated_at"] if "cm_updated_at" in row.keys() else None,
        }

        # Civitai model data (if available)
        if row["cm_id"]:
            result["civitai_model"] = {
                "id": row["cm_id"],
                "name": row["cm_name"],
                "description": row["cm_description"],
                "type": row["cm_type"],
                "nsfw": bool(row["cm_nsfw"]),
                "nsfw_level": row["cm_nsfw_level"],
                "tags": json.loads(row["cm_tags"] or "[]"),
                "creator_username": row["cm_creator_username"],
                "creator_image_url": row["cm_creator_image_url"],
                "stats_download_count": row["cm_stats_download_count"],
                "stats_thumbs_up": row["cm_stats_thumbs_up"],
                "stats_rating": row["cm_stats_rating"],
                "allow_no_credit": bool(row["cm_allow_no_credit"]) if row["cm_allow_no_credit"] is not None else True,
                "allow_commercial_use": row["cm_allow_commercial_use"],
                "allow_derivatives": bool(row["cm_allow_derivatives"]) if row["cm_allow_derivatives"] is not None else True,
                "allow_different_license": bool(row["cm_allow_different_license"]) if row["cm_allow_different_license"] is not None else True,
                "supports_generation": bool(row["cm_supports_generation"]) if row["cm_supports_generation"] is not None else False,
            }
            result["display_name"] = row["cm_name"]
            result["model_type"] = row["cm_type"]
            result["tags"] = json.loads(row["cm_tags"] or "[]")
            result["creator"] = row["cm_creator_username"]
            result["download_count"] = row["cm_stats_download_count"] or row["stats_download_count"]
            result["rating"] = row["cm_stats_rating"] or 0
        else:
            result["civitai_model"] = None
            result["display_name"] = os.path.splitext(row["file_name"])[0]
            result["model_type"] = "Unknown"
            result["tags"] = []
            result["creator"] = None
            result["download_count"] = row["stats_download_count"] or 0
            result["rating"] = 0

        return result
