"""
SQLite database for model metadata.

Stores pre-computed metadata for fast filtering/sorting without
reading JSON files for every model on each page load.
"""
import os
import json
import sqlite3
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager


class ModelsDatabase:
    """
    SQLite database for model metadata.

    Schema:
        models (
            file_path TEXT PRIMARY KEY,
            file_name TEXT,
            file_size INTEGER,
            file_modified TEXT,  -- ISO timestamp
            file_extension TEXT,
            display_name TEXT,
            model_type TEXT,
            base_model TEXT,
            nsfw_level TEXT,  -- Computed: PG, PG-13, R, X, XXX, Unknown
            has_civitai_data INTEGER,  -- 0 or 1
            civitai_model_id INTEGER,
            civitai_version_id INTEGER,
            preview_path TEXT,
            preview_url TEXT,
            trained_words TEXT,  -- JSON array
            tags TEXT,  -- JSON array
            rating REAL,
            download_count INTEGER,
            creator TEXT,
            published_at TEXT,  -- ISO timestamp
            scanned_at TEXT  -- When this record was updated
        )
    """

    DB_NAME = "models.db"

    def __init__(self, extension_dir: str):
        """Initialize the database."""
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
                CREATE TABLE IF NOT EXISTS models (
                    file_path TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    file_size INTEGER,
                    file_modified TEXT,
                    file_extension TEXT,
                    display_name TEXT,
                    model_type TEXT,
                    base_model TEXT,
                    nsfw_level TEXT DEFAULT 'Unknown',
                    has_civitai_data INTEGER DEFAULT 0,
                    civitai_model_id INTEGER,
                    civitai_version_id INTEGER,
                    preview_path TEXT,
                    preview_url TEXT,
                    trained_words TEXT DEFAULT '[]',
                    tags TEXT DEFAULT '[]',
                    rating REAL DEFAULT 0,
                    download_count INTEGER DEFAULT 0,
                    creator TEXT,
                    published_at TEXT,
                    scanned_at TEXT
                )
            """)

            # Create indexes for common filter/sort fields
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_type ON models(model_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_base_model ON models(base_model)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_nsfw_level ON models(nsfw_level)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_has_civitai ON models(has_civitai_data)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_display_name ON models(display_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rating ON models(rating)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_download_count ON models(download_count)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_modified ON models(file_modified)")

            # Metadata table for tracking scan state
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

    def upsert_model(self, model_data: Dict[str, Any]):
        """Insert or update a model record."""
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT OR REPLACE INTO models (
                    file_path, file_name, file_size, file_modified, file_extension,
                    display_name, model_type, base_model, nsfw_level,
                    has_civitai_data, civitai_model_id, civitai_version_id,
                    preview_path, preview_url, trained_words, tags,
                    rating, download_count, creator, published_at, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                model_data.get("file_path"),
                model_data.get("file_name"),
                model_data.get("file_size"),
                model_data.get("file_modified"),
                model_data.get("file_extension"),
                model_data.get("display_name"),
                model_data.get("model_type"),
                model_data.get("base_model"),
                model_data.get("nsfw_level", "Unknown"),
                1 if model_data.get("has_civitai_data") else 0,
                model_data.get("civitai_model_id"),
                model_data.get("civitai_version_id"),
                model_data.get("preview_path"),
                model_data.get("preview_url"),
                json.dumps(model_data.get("trained_words", [])),
                json.dumps(model_data.get("tags", [])),
                model_data.get("rating", 0),
                model_data.get("download_count", 0),
                model_data.get("creator"),
                model_data.get("published_at"),
                datetime.now().isoformat()
            ))

    def delete_model(self, file_path: str):
        """Delete a model record."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM models WHERE file_path = ?", (file_path,))

    def get_model(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get a single model by file path."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM models WHERE file_path = ?", (file_path,))
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
        return None

    def query_models(
        self,
        search: Optional[str] = None,
        model_type: Optional[str] = None,
        base_model: Optional[str] = None,
        nsfw_levels: Optional[List[str]] = None,
        nsfw_max: Optional[str] = None,
        has_civitai: Optional[bool] = None,
        sort_by: str = "display_name",
        sort_order: str = "asc",
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Query models with filters, sorting, and pagination.

        Returns:
            Tuple of (list of model dicts, total count matching filters)
        """
        conditions = []
        params = []

        # Search filter (display_name, file_name, tags)
        if search:
            conditions.append("(display_name LIKE ? OR file_name LIKE ? OR tags LIKE ?)")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])

        # Model type filter
        if model_type:
            conditions.append("model_type = ?")
            params.append(model_type)

        # Base model filter
        if base_model:
            conditions.append("base_model = ?")
            params.append(base_model)

        # NSFW level filter
        if nsfw_levels:
            placeholders = ",".join("?" * len(nsfw_levels))
            conditions.append(f"nsfw_level IN ({placeholders})")
            params.extend(nsfw_levels)
        elif nsfw_max:
            # Filter by max level
            level_order = ["PG", "PG-13", "R", "X", "XXX"]
            if nsfw_max in level_order:
                max_idx = level_order.index(nsfw_max)
                allowed = level_order[:max_idx + 1]
                placeholders = ",".join("?" * len(allowed))
                conditions.append(f"nsfw_level IN ({placeholders})")
                params.extend(allowed)

        # Has civitai data filter
        if has_civitai is not None:
            conditions.append("has_civitai_data = ?")
            params.append(1 if has_civitai else 0)

        # Build WHERE clause
        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Validate sort field
        valid_sort_fields = {
            "display_name", "file_name", "file_size", "file_modified",
            "model_type", "base_model", "nsfw_level", "rating", "download_count",
            "published_at"
        }
        if sort_by not in valid_sort_fields:
            sort_by = "display_name"

        sort_dir = "DESC" if sort_order.lower() == "desc" else "ASC"

        # Get total count
        with self._cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM models WHERE {where_clause}", params)
            total_count = cursor.fetchone()[0]

        # Get paginated results
        with self._cursor() as cursor:
            query = f"""
                SELECT * FROM models
                WHERE {where_clause}
                ORDER BY {sort_by} {sort_dir}
                LIMIT ? OFFSET ?
            """
            cursor.execute(query, params + [limit, offset])
            rows = cursor.fetchall()

        models = [self._row_to_dict(row) for row in rows]
        return models, total_count

    def get_all_model_paths(self) -> List[str]:
        """Get all model file paths in the database."""
        with self._cursor() as cursor:
            cursor.execute("SELECT file_path FROM models")
            return [row[0] for row in cursor.fetchall()]

    def get_distinct_values(self, column: str) -> List[str]:
        """Get distinct values for a column (for filter dropdowns)."""
        valid_columns = {"model_type", "base_model", "nsfw_level", "creator"}
        if column not in valid_columns:
            return []

        with self._cursor() as cursor:
            cursor.execute(f"SELECT DISTINCT {column} FROM models WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}")
            return [row[0] for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM models")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM models WHERE has_civitai_data = 1")
            with_civitai = cursor.fetchone()[0]

        return {
            "total_models": total,
            "with_civitai_data": with_civitai,
            "without_civitai_data": total - with_civitai
        }

    def set_metadata(self, key: str, value: str):
        """Set a metadata value."""
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, value)
            )

    def get_metadata(self, key: str) -> Optional[str]:
        """Get a metadata value."""
        with self._cursor() as cursor:
            cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else None

    def clear_all(self):
        """Clear all model records."""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM models")

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a database row to a dictionary."""
        return {
            "file_path": row["file_path"],
            "file_name": row["file_name"],
            "file_size": row["file_size"],
            "file_modified": row["file_modified"],
            "file_extension": row["file_extension"],
            "display_name": row["display_name"],
            "model_type": row["model_type"],
            "base_model": row["base_model"],
            "nsfw_level": row["nsfw_level"],
            "has_civitai_data": bool(row["has_civitai_data"]),
            "civitai_model_id": row["civitai_model_id"],
            "civitai_version_id": row["civitai_version_id"],
            "preview_path": row["preview_path"],
            "preview_url": row["preview_url"],
            "trained_words": json.loads(row["trained_words"] or "[]"),
            "tags": json.loads(row["tags"] or "[]"),
            "rating": row["rating"],
            "download_count": row["download_count"],
            "creator": row["creator"],
            "published_at": row["published_at"],
        }

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
                ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                _db_instance = ModelsDatabase(ext_dir)

    return _db_instance
