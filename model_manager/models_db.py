"""
SQLite database for model metadata.

Facade class that provides unified access to all database operations.
Delegates to internal modules for models and images operations.
"""
import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

from ._models_ops import ModelsOps
from ._images_ops import ImagesOps
from ._browser_cache_ops import BrowserCacheOps


# Schema version for migrations
SCHEMA_VERSION = 10


class ModelsDatabase:
    """
    SQLite database facade for model metadata and images.

    Provides unified access to:
    - Model/version operations (via ModelsOps)
    - Image operations (via ImagesOps)
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

        # Initialize operation delegates
        self._models = ModelsOps(self._cursor)
        self._images = ImagesOps(self._cursor)
        self._browser_cache = BrowserCacheOps(self._cursor)

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            # Add timeout to wait for locks (30 seconds) and enable WAL mode for better concurrency
            self._local.connection = sqlite3.connect(self.db_path, timeout=30.0)
            self._local.connection.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrent read/write performance
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

    # ==================== Schema & Migrations ====================

    def _init_db(self):
        """Create database tables and run migrations if needed."""
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
                self._migrate(cursor, current_version)

    def _migrate(self, cursor, from_version: int):
        """Run migrations from current version to latest."""
        print(f"[ModelManager] Migrating database from v{from_version} to v{SCHEMA_VERSION}...")

        if from_version < 2:
            self._migrate_to_v2(cursor)

        if from_version < 3:
            self._migrate_to_v3(cursor)

        if from_version < 4:
            self._migrate_to_v4(cursor)

        if from_version < 5:
            self._migrate_to_v5(cursor)

        if from_version < 6:
            self._migrate_to_v6(cursor)

        if from_version < 7:
            self._migrate_to_v7(cursor)

        if from_version < 8:
            self._migrate_to_v8(cursor)

        if from_version < 9:
            self._migrate_to_v9(cursor)

        if from_version < 10:
            self._migrate_to_v10(cursor)

        cursor.execute(
            "INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),)
        )
        print(f"[ModelManager] Database migration complete.")

    def _migrate_to_v3(self, cursor):
        """Add max_image_nsfw column to model_versions (legacy, removed in v4)."""
        print("[ModelManager] Migrating to schema v3 (adding max_image_nsfw column)...")
        cursor.execute("PRAGMA table_info(model_versions)")
        columns = [row[1] for row in cursor.fetchall()]
        if "max_image_nsfw" not in columns:
            cursor.execute("ALTER TABLE model_versions ADD COLUMN max_image_nsfw INTEGER DEFAULT 1")
            print("[ModelManager] Added max_image_nsfw column to model_versions.")

    def _migrate_to_v4(self, cursor):
        """
        Consolidate images into models.db and remove max_image_nsfw column.
        """
        import shutil

        print("[ModelManager] Migrating to schema v4 (consolidating images, removing max_image_nsfw)...")

        # Backup databases
        backup_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        models_backup = f"{self.db_path}.backup_{backup_time}"
        shutil.copy2(self.db_path, models_backup)
        print(f"[ModelManager] Backed up models.db to {models_backup}")

        images_cache_path = os.path.join(self.db_dir, "images_cache.db")
        if os.path.exists(images_cache_path):
            images_backup = f"{images_cache_path}.backup_{backup_time}"
            shutil.copy2(images_cache_path, images_backup)
            print(f"[ModelManager] Backed up images_cache.db to {images_backup}")

        # Create images table with proper columns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY,
                version_id INTEGER NOT NULL,
                page INTEGER NOT NULL,
                url TEXT,
                width INTEGER,
                height INTEGER,
                nsfw INTEGER DEFAULT 0,
                nsfw_level TEXT,
                browsing_level INTEGER DEFAULT 1,
                created_at TEXT,
                data TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_version ON images(version_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_version_page ON images(version_id, page)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_nsfw_level ON images(nsfw_level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_browsing_level ON images(browsing_level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_created_at ON images(created_at)")

        # Create pagination table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pagination (
                version_id INTEGER PRIMARY KEY,
                total_count INTEGER DEFAULT 0,
                total_pages INTEGER DEFAULT 1,
                fetched_pages INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        print("[ModelManager] Created images and pagination tables.")

        # Migrate data from images_cache.db if it exists
        if os.path.exists(images_cache_path):
            try:
                cursor.execute("ATTACH DATABASE ? AS old_cache", (images_cache_path,))
                cursor.execute("""
                    INSERT OR IGNORE INTO images (
                        id, version_id, page, url, width, height,
                        nsfw, nsfw_level, browsing_level, created_at, data
                    )
                    SELECT
                        id,
                        version_id,
                        page,
                        json_extract(data, '$.url'),
                        json_extract(data, '$.width'),
                        json_extract(data, '$.height'),
                        CASE WHEN json_extract(data, '$.nsfw') IN (1, 'true', 'True') THEN 1 ELSE 0 END,
                        json_extract(data, '$.nsfwLevel'),
                        COALESCE(CAST(json_extract(data, '$.browsingLevel') AS INTEGER), 1),
                        json_extract(data, '$.createdAt'),
                        data
                    FROM old_cache.images
                """)
                images_count = cursor.rowcount
                print(f"[ModelManager] Migrated {images_count} images from images_cache.db")

                cursor.execute("INSERT OR IGNORE INTO pagination SELECT * FROM old_cache.pagination")
                pagination_count = cursor.rowcount
                print(f"[ModelManager] Migrated {pagination_count} pagination records")

                cursor.execute("DETACH DATABASE old_cache")
                os.rename(images_cache_path, images_cache_path + ".migrated")
                print("[ModelManager] Renamed images_cache.db to images_cache.db.migrated")

            except Exception as e:
                print(f"[ModelManager] Warning: Could not migrate images_cache.db: {e}")
                import traceback
                traceback.print_exc()
                try:
                    cursor.execute("DETACH DATABASE old_cache")
                except:
                    pass

        # Recreate model_versions without max_image_nsfw column
        print("[ModelManager] Removing max_image_nsfw column from model_versions...")
        cursor.execute("PRAGMA table_info(model_versions)")
        columns = [row[1] for row in cursor.fetchall()]

        if "max_image_nsfw" in columns:
            cursor.execute("""
                CREATE TABLE model_versions_new (
                    id INTEGER,
                    model_id INTEGER,
                    version_name TEXT,
                    base_model TEXT,
                    published_at TEXT,
                    created_at TEXT,
                    nsfw_level INTEGER DEFAULT 64,
                    trained_words TEXT DEFAULT '[]',
                    description TEXT,
                    stats_download_count INTEGER DEFAULT 0,
                    stats_thumbs_up INTEGER DEFAULT 0,
                    file_path TEXT UNIQUE NOT NULL,
                    file_name TEXT NOT NULL,
                    file_size INTEGER,
                    file_hash TEXT,
                    file_modified TEXT,
                    file_extension TEXT,
                    preview_path TEXT,
                    preview_url TEXT,
                    has_civitai_data INTEGER DEFAULT 0,
                    scanned_at TEXT,
                    PRIMARY KEY (file_path),
                    FOREIGN KEY (model_id) REFERENCES civitai_models(id)
                )
            """)

            cursor.execute("""
                INSERT INTO model_versions_new
                SELECT id, model_id, version_name, base_model, published_at, created_at,
                       nsfw_level, trained_words, description,
                       stats_download_count, stats_thumbs_up,
                       file_path, file_name, file_size, file_hash, file_modified, file_extension,
                       preview_path, preview_url, has_civitai_data, scanned_at
                FROM model_versions
            """)

            cursor.execute("DROP TABLE model_versions")
            cursor.execute("ALTER TABLE model_versions_new RENAME TO model_versions")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_model_id ON model_versions(model_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_base_model ON model_versions(base_model)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_nsfw_level ON model_versions(nsfw_level)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_file_modified ON model_versions(file_modified)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_published_at ON model_versions(published_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_has_civitai ON model_versions(has_civitai_data)")

            print("[ModelManager] Removed max_image_nsfw column from model_versions.")

        print("[ModelManager] Schema v4 migration complete.")

    def _migrate_to_v5(self, cursor):
        """Add is_bookmarked column to civitai_models for bookmark feature."""
        print("[ModelManager] Migrating to schema v5 (adding is_bookmarked column)...")

        # Check if column already exists
        cursor.execute("PRAGMA table_info(civitai_models)")
        columns = [row[1] for row in cursor.fetchall()]

        if "is_bookmarked" not in columns:
            cursor.execute("ALTER TABLE civitai_models ADD COLUMN is_bookmarked INTEGER DEFAULT 0")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_is_bookmarked ON civitai_models(is_bookmarked)")
            print("[ModelManager] Added is_bookmarked column and index to civitai_models.")

        print("[ModelManager] Schema v5 migration complete.")

    def _migrate_to_v6(self, cursor):
        """Add cursor-based image pagination columns and drop pagination table."""
        print("[ModelManager] Migrating to schema v6 (cursor-based image pagination)...")

        # Add new columns to model_versions
        cursor.execute("PRAGMA table_info(model_versions)")
        columns = [row[1] for row in cursor.fetchall()]

        if "next_images_cursor" not in columns:
            cursor.execute("ALTER TABLE model_versions ADD COLUMN next_images_cursor TEXT DEFAULT NULL")
            print("[ModelManager] Added next_images_cursor column to model_versions.")

        if "images_sync_last_date" not in columns:
            cursor.execute("ALTER TABLE model_versions ADD COLUMN images_sync_last_date TEXT DEFAULT NULL")
            print("[ModelManager] Added images_sync_last_date column to model_versions.")

        # Drop pagination table (no longer needed with cursor-based pagination)
        cursor.execute("DROP TABLE IF EXISTS pagination")
        print("[ModelManager] Dropped pagination table.")

        # Clear all existing images (force re-sync with new cursor logic)
        cursor.execute("DELETE FROM images")
        print("[ModelManager] Cleared images table for cursor-based re-sync.")

        print("[ModelManager] Schema v6 migration complete.")

    def _migrate_to_v7(self, cursor):
        """Replace file_hash with file_hashes JSON column for multi-hash support."""
        print("[ModelManager] Migrating to schema v7 (multi-hash support)...")

        # Need to recreate table to remove file_hash and add file_hashes
        cursor.execute("""
            CREATE TABLE model_versions_new (
                id INTEGER,
                model_id INTEGER,
                version_name TEXT,
                base_model TEXT,
                published_at TEXT,
                created_at TEXT,
                nsfw_level INTEGER DEFAULT 64,
                trained_words TEXT DEFAULT '[]',
                description TEXT,
                stats_download_count INTEGER DEFAULT 0,
                stats_thumbs_up INTEGER DEFAULT 0,
                file_path TEXT UNIQUE NOT NULL,
                file_name TEXT NOT NULL,
                file_size INTEGER,
                file_hashes TEXT DEFAULT NULL,
                file_modified TEXT,
                file_extension TEXT,
                preview_path TEXT,
                preview_url TEXT,
                has_civitai_data INTEGER DEFAULT 0,
                scanned_at TEXT,
                next_images_cursor TEXT DEFAULT NULL,
                images_sync_last_date TEXT DEFAULT NULL,
                PRIMARY KEY (file_path),
                FOREIGN KEY (model_id) REFERENCES civitai_models(id)
            )
        """)

        # Copy data, converting old file_hash to file_hashes JSON if exists
        cursor.execute("""
            INSERT INTO model_versions_new
            SELECT
                id, model_id, version_name, base_model, published_at, created_at,
                nsfw_level, trained_words, description,
                stats_download_count, stats_thumbs_up,
                file_path, file_name, file_size,
                CASE WHEN file_hash IS NOT NULL AND file_hash != ''
                     THEN json_object('sha256', file_hash)
                     ELSE NULL
                END,
                file_modified, file_extension,
                preview_path, preview_url, has_civitai_data, scanned_at,
                next_images_cursor, images_sync_last_date
            FROM model_versions
        """)

        cursor.execute("DROP TABLE model_versions")
        cursor.execute("ALTER TABLE model_versions_new RENAME TO model_versions")

        # Recreate indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_model_id ON model_versions(model_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_base_model ON model_versions(base_model)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_nsfw_level ON model_versions(nsfw_level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_file_modified ON model_versions(file_modified)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_published_at ON model_versions(published_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_has_civitai ON model_versions(has_civitai_data)")

        print("[ModelManager] Replaced file_hash with file_hashes column.")
        print("[ModelManager] Schema v7 migration complete.")

    def _migrate_to_v8(self, cursor):
        """Remove preview columns and simplify images NSFW to effective_nsfw_level."""
        print("[ModelManager] Migrating to schema v8 (preview from images, simplified NSFW)...")

        # Recreate model_versions without preview_path and preview_url
        cursor.execute("""
            CREATE TABLE model_versions_new (
                id INTEGER,
                model_id INTEGER,
                version_name TEXT,
                base_model TEXT,
                published_at TEXT,
                created_at TEXT,
                nsfw_level INTEGER DEFAULT 64,
                trained_words TEXT DEFAULT '[]',
                description TEXT,
                stats_download_count INTEGER DEFAULT 0,
                stats_thumbs_up INTEGER DEFAULT 0,
                file_path TEXT UNIQUE NOT NULL,
                file_name TEXT NOT NULL,
                file_size INTEGER,
                file_hashes TEXT DEFAULT NULL,
                file_modified TEXT,
                file_extension TEXT,
                has_civitai_data INTEGER DEFAULT 0,
                scanned_at TEXT,
                next_images_cursor TEXT DEFAULT NULL,
                images_sync_last_date TEXT DEFAULT NULL,
                PRIMARY KEY (file_path),
                FOREIGN KEY (model_id) REFERENCES civitai_models(id)
            )
        """)

        # Copy data (excluding preview_path and preview_url)
        cursor.execute("""
            INSERT INTO model_versions_new
            SELECT
                id, model_id, version_name, base_model, published_at, created_at,
                nsfw_level, trained_words, description,
                stats_download_count, stats_thumbs_up,
                file_path, file_name, file_size, file_hashes,
                file_modified, file_extension,
                has_civitai_data, scanned_at,
                next_images_cursor, images_sync_last_date
            FROM model_versions
        """)

        cursor.execute("DROP TABLE model_versions")
        cursor.execute("ALTER TABLE model_versions_new RENAME TO model_versions")

        # Recreate indexes for model_versions
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_model_id ON model_versions(model_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_base_model ON model_versions(base_model)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_nsfw_level ON model_versions(nsfw_level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_file_modified ON model_versions(file_modified)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_published_at ON model_versions(published_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_has_civitai ON model_versions(has_civitai_data)")

        print("[ModelManager] Removed preview_path and preview_url from model_versions.")

        # Recreate images table with effective_nsfw_level instead of nsfw, nsfw_level, browsing_level
        cursor.execute("""
            CREATE TABLE images_new (
                id INTEGER PRIMARY KEY,
                version_id INTEGER NOT NULL,
                page INTEGER NOT NULL,
                url TEXT,
                width INTEGER,
                height INTEGER,
                effective_nsfw_level INTEGER DEFAULT 1,
                created_at TEXT,
                data TEXT NOT NULL
            )
        """)

        # We can't easily migrate the NSFW data, so just clear and re-sync
        cursor.execute("DROP TABLE images")
        cursor.execute("ALTER TABLE images_new RENAME TO images")

        # Recreate indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_version ON images(version_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_version_nsfw ON images(version_id, effective_nsfw_level)")

        # Reset image sync state to force re-sync
        cursor.execute("UPDATE model_versions SET next_images_cursor = NULL, images_sync_last_date = NULL")

        print("[ModelManager] Simplified images table with effective_nsfw_level.")
        print("[ModelManager] Schema v8 migration complete. Images will re-sync on next load.")

    def _migrate_to_v9(self, cursor):
        """Add civitai_browser_cache table for Civitai Browser feature."""
        print("[ModelManager] Migrating to schema v9 (Civitai Browser cache)...")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS civitai_browser_cache (
                model_id INTEGER NOT NULL,
                version_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                data_id TEXT NOT NULL,
                cached_at TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (version_id, type, data_id)
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_browser_cache_version_type ON civitai_browser_cache(version_id, type)")

        print("[ModelManager] Schema v9 migration complete.")

    def _migrate_to_v10(self, cursor):
        """Add downloaded_at column and scanned_at index to model_versions."""
        print("[ModelManager] Migrating to schema v10 (adding downloaded_at column)...")

        # Check if column already exists
        cursor.execute("PRAGMA table_info(model_versions)")
        columns = [row[1] for row in cursor.fetchall()]

        if "downloaded_at" not in columns:
            cursor.execute("ALTER TABLE model_versions ADD COLUMN downloaded_at TEXT DEFAULT NULL")
            print("[ModelManager] Added downloaded_at column to model_versions.")

        # Create indexes for sorting by date
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_scanned_at ON model_versions(scanned_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_downloaded_at ON model_versions(downloaded_at)")

        print("[ModelManager] Schema v10 migration complete.")

    def _migrate_to_v2(self, cursor):
        """Migrate from v1 (flat models table) to v2 (normalized schema)."""
        print("[ModelManager] Migrating to schema v2 (normalized model/version tables)...")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='models'")
        old_table_exists = cursor.fetchone() is not None

        self._create_v2_tables(cursor)

        if old_table_exists:
            print("[ModelManager] Migrating existing data...")
            cursor.execute("SELECT * FROM models")
            old_rows = cursor.fetchall()

            for row in old_rows:
                cursor.execute("""
                    INSERT OR IGNORE INTO model_versions (
                        id, model_id, version_name, base_model, published_at, created_at,
                        nsfw_level, trained_words, description,
                        stats_download_count, stats_thumbs_up,
                        file_path, file_name, file_size, file_hash, file_modified, file_extension,
                        preview_path, preview_url, has_civitai_data, scanned_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row['civitai_version_id'],
                    row['civitai_model_id'],
                    None,
                    row['base_model'],
                    row['published_at'],
                    None,
                    self._nsfw_text_to_level(row['nsfw_level']),
                    row['trained_words'],
                    None,
                    row['download_count'],
                    0,
                    row['file_path'],
                    row['file_name'],
                    row['file_size'],
                    None,
                    row['file_modified'],
                    row['file_extension'],
                    row['preview_path'],
                    row['preview_url'],
                    row['has_civitai_data'],
                    row['scanned_at']
                ))

                if row['civitai_model_id']:
                    cursor.execute("""
                        INSERT OR IGNORE INTO civitai_models (id, name, type, tags, creator_username)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        row['civitai_model_id'],
                        row['display_name'],
                        row['model_type'],
                        row['tags'],
                        row['creator']
                    ))

            print(f"[ModelManager] Migrated {len(old_rows)} models.")
            cursor.execute("ALTER TABLE models RENAME TO models_v1_backup")
            print("[ModelManager] Old 'models' table renamed to 'models_v1_backup'.")
            cursor.execute("DROP TABLE IF EXISTS metadata")

    def _nsfw_text_to_level(self, text: str) -> int:
        """Convert old NSFW text level to numeric."""
        mapping = {
            'PG': 1, 'PG-13': 2, 'R': 4, 'X': 8, 'XXX': 16, 'Banned': 32, 'Unknown': 64
        }
        return mapping.get(text, 64)  # Default to Unknown

    def _create_v8_schema(self, cursor):
        """Create v8 schema for fresh installs."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS civitai_models (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                type TEXT NOT NULL DEFAULT 'Checkpoint',
                nsfw INTEGER DEFAULT 0,
                nsfw_level INTEGER DEFAULT 64,
                tags TEXT DEFAULT '[]',
                creator_username TEXT,
                creator_image_url TEXT,
                stats_download_count INTEGER DEFAULT 0,
                stats_thumbs_up INTEGER DEFAULT 0,
                stats_rating REAL DEFAULT 0,
                allow_no_credit INTEGER DEFAULT 1,
                allow_commercial_use TEXT,
                allow_derivatives INTEGER DEFAULT 1,
                allow_different_license INTEGER DEFAULT 1,
                supports_generation INTEGER DEFAULT 0,
                is_bookmarked INTEGER DEFAULT 0,
                updated_at TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_versions (
                id INTEGER,
                model_id INTEGER,
                version_name TEXT,
                base_model TEXT,
                published_at TEXT,
                created_at TEXT,
                nsfw_level INTEGER DEFAULT 64,
                trained_words TEXT DEFAULT '[]',
                description TEXT,
                stats_download_count INTEGER DEFAULT 0,
                stats_thumbs_up INTEGER DEFAULT 0,
                file_path TEXT UNIQUE NOT NULL,
                file_name TEXT NOT NULL,
                file_size INTEGER,
                file_hashes TEXT DEFAULT NULL,
                file_modified TEXT,
                file_extension TEXT,
                has_civitai_data INTEGER DEFAULT 0,
                scanned_at TEXT,
                downloaded_at TEXT DEFAULT NULL,
                next_images_cursor TEXT DEFAULT NULL,
                images_sync_last_date TEXT DEFAULT NULL,
                PRIMARY KEY (file_path),
                FOREIGN KEY (model_id) REFERENCES civitai_models(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY,
                version_id INTEGER NOT NULL,
                page INTEGER NOT NULL,
                url TEXT,
                width INTEGER,
                height INTEGER,
                effective_nsfw_level INTEGER DEFAULT 64,
                created_at TEXT,
                data TEXT NOT NULL
            )
        """)

        # Create all indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_model_id ON model_versions(model_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_base_model ON model_versions(base_model)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_nsfw_level ON model_versions(nsfw_level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_file_modified ON model_versions(file_modified)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_published_at ON model_versions(published_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_has_civitai ON model_versions(has_civitai_data)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_scanned_at ON model_versions(scanned_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_downloaded_at ON model_versions(downloaded_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_civitai_model_type ON civitai_models(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_is_bookmarked ON civitai_models(is_bookmarked)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_version ON images(version_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_version_nsfw ON images(version_id, effective_nsfw_level)")

    def _create_v2_tables(self, cursor):
        """Create v2 schema tables (original v2 schema, migrations transform to current)."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS civitai_models (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                type TEXT NOT NULL DEFAULT 'Checkpoint',
                nsfw INTEGER DEFAULT 0,
                nsfw_level INTEGER DEFAULT 64,
                tags TEXT DEFAULT '[]',
                creator_username TEXT,
                creator_image_url TEXT,
                stats_download_count INTEGER DEFAULT 0,
                stats_thumbs_up INTEGER DEFAULT 0,
                stats_rating REAL DEFAULT 0,
                allow_no_credit INTEGER DEFAULT 1,
                allow_commercial_use TEXT,
                allow_derivatives INTEGER DEFAULT 1,
                allow_different_license INTEGER DEFAULT 1,
                supports_generation INTEGER DEFAULT 0,
                updated_at TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_versions (
                id INTEGER,
                model_id INTEGER,
                version_name TEXT,
                base_model TEXT,
                published_at TEXT,
                created_at TEXT,
                nsfw_level INTEGER DEFAULT 64,
                trained_words TEXT DEFAULT '[]',
                description TEXT,
                stats_download_count INTEGER DEFAULT 0,
                stats_thumbs_up INTEGER DEFAULT 0,
                file_path TEXT UNIQUE NOT NULL,
                file_name TEXT NOT NULL,
                file_size INTEGER,
                file_hash TEXT,
                file_modified TEXT,
                file_extension TEXT,
                preview_path TEXT,
                preview_url TEXT,
                has_civitai_data INTEGER DEFAULT 0,
                scanned_at TEXT,
                PRIMARY KEY (file_path),
                FOREIGN KEY (model_id) REFERENCES civitai_models(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY,
                version_id INTEGER NOT NULL,
                page INTEGER NOT NULL,
                url TEXT,
                width INTEGER,
                height INTEGER,
                nsfw INTEGER DEFAULT 0,
                nsfw_level TEXT,
                browsing_level INTEGER DEFAULT 1,
                created_at TEXT,
                data TEXT NOT NULL
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_model_id ON model_versions(model_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_base_model ON model_versions(base_model)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_nsfw_level ON model_versions(nsfw_level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_file_modified ON model_versions(file_modified)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_published_at ON model_versions(published_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_has_civitai ON model_versions(has_civitai_data)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_civitai_model_type ON civitai_models(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_version ON images(version_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_version_page ON images(version_id, page)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_nsfw_level ON images(nsfw_level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_browsing_level ON images(browsing_level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_created_at ON images(created_at)")

    # ==================== Model Operations (delegated) ====================

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

    def set_downloaded_at(self, file_path: str):
        """Set downloaded_at timestamp for a version (called after Civitai download)."""
        with self._cursor() as cursor:
            cursor.execute("""
                UPDATE model_versions
                SET downloaded_at = ?
                WHERE file_path = ?
            """, (datetime.now().isoformat(), file_path))

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
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
            preview_least_nsfw=preview_least_nsfw
        )

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

    def get_images(self, version_id: int, page: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get cached images for a version."""
        return self._images.get_images(version_id, page)

    def get_all_images_for_version(self, version_id: int) -> List[Dict[str, Any]]:
        """Get all cached images for a version."""
        return self._images.get_all_images_for_version(version_id)

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
                ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
