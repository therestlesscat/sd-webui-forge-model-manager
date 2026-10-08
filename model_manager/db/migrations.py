"""
Schema history.

Every version the database has ever had, and the steps between them. This is
write-once material: once a migration ships it is never edited, only added to,
because someone out there is still on the version before it.

Nothing here is read during normal work - open the database, run what is
missing, and never look at this file again until the schema changes.

ADDING A MIGRATION
  1. bump SCHEMA_VERSION in database.py
  2. add _migrate_to_v<N>(cursor), guarded so it can run twice safely
  3. add it to run_migrations() in order
A migration must tolerate being re-run: check PRAGMA table_info before adding
a column, and use CREATE ... IF NOT EXISTS.
"""
import json
import os
import shutil
import sqlite3
from datetime import datetime


def _migrate_to_v2(cursor):
    """Migrate from v1 (flat models table) to v2 (normalized schema)."""
    print("[ModelManager] Migrating to schema v2 (normalized model/version tables)...")

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='models'")
    old_table_exists = cursor.fetchone() is not None

    _create_v2_tables(cursor)

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
                _nsfw_text_to_level(row['nsfw_level']),
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

def _migrate_to_v3(cursor):
    """Add max_image_nsfw column to model_versions (legacy, removed in v4)."""
    print("[ModelManager] Migrating to schema v3 (adding max_image_nsfw column)...")
    cursor.execute("PRAGMA table_info(model_versions)")
    columns = [row[1] for row in cursor.fetchall()]
    if "max_image_nsfw" not in columns:
        cursor.execute("ALTER TABLE model_versions ADD COLUMN max_image_nsfw INTEGER DEFAULT 1")
        print("[ModelManager] Added max_image_nsfw column to model_versions.")

def _migrate_to_v4(cursor, db_path: str, db_dir: str):
    """
    Consolidate images into models.db and remove max_image_nsfw column.
    """
    import shutil

    print("[ModelManager] Migrating to schema v4 (consolidating images, removing max_image_nsfw)...")

    # Backup databases
    backup_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    models_backup = f"{db_path}.backup_{backup_time}"
    shutil.copy2(db_path, models_backup)
    print(f"[ModelManager] Backed up models.db to {models_backup}")

    images_cache_path = os.path.join(db_dir, "images_cache.db")
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

def _migrate_to_v5(cursor):
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

def _migrate_to_v6(cursor):
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

def _migrate_to_v7(cursor):
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

def _migrate_to_v8(cursor):
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

def _migrate_to_v9(cursor):
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

def _migrate_to_v10(cursor):
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

def _migrate_to_v11(cursor):
    """Add query-optimized indexes for model list and preview lookups."""
    print("[ModelManager] Migrating to schema v11 (query optimization indexes)...")
    _create_v11_indexes(cursor)
    print("[ModelManager] Schema v11 migration complete.")

def _migrate_to_v12(cursor):
    """Add thumbs-down, so a model's reception can be read as a ratio.

    Civitai retired star ratings; thumbs up and down are what it reports
    now. stats_thumbs_up was already stored, its counterpart was not, and
    stats_rating is derived from the pair at sync time. Existing rows read
    0 until they are synced again.
    """
    print("[ModelManager] Migrating to schema v12 (adding stats_thumbs_down column)...")

    cursor.execute("PRAGMA table_info(civitai_models)")
    columns = {row[1] for row in cursor.fetchall()}

    if "stats_thumbs_down" not in columns:
        cursor.execute(
            "ALTER TABLE civitai_models ADD COLUMN stats_thumbs_down INTEGER DEFAULT 0"
        )

    print("[ModelManager] Migration to v12 complete")

def _migrate_to_v13(cursor):
    """Record when a Civitai hash lookup came back empty.

    A model that was never on Civitai - most LoRAs, VAEs and text encoders
    arrive from elsewhere - has has_civitai_data 0 forever, which is the
    only thing a sync checks before deciding to work on a file. So every
    run re-read those files in full to recompute six hashes and asked
    Civitai again, always for nothing.

    This column is that missing memory. It is advisory: a forced sync
    ignores it, because a model can appear on Civitai later.
    """
    print("[ModelManager] Migrating to schema v13 (remembering failed Civitai lookups)...")

    cursor.execute("PRAGMA table_info(model_versions)")
    columns = {row[1] for row in cursor.fetchall()}

    if "civitai_lookup_failed_at" not in columns:
        cursor.execute(
            "ALTER TABLE model_versions ADD COLUMN civitai_lookup_failed_at TEXT"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_version_lookup_failed "
            "ON model_versions(civitai_lookup_failed_at)"
        )

    print("[ModelManager] Migration to v13 complete")

def _create_v11_indexes(cursor):
    """Create indexes used by grouped model list and preview queries."""
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_images_version_nsfw_created_id "
        "ON images(version_id, effective_nsfw_level, created_at DESC, id DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_images_version_created_id "
        "ON images(version_id, created_at DESC, id DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_version_model_published "
        "ON model_versions(model_id, published_at DESC)"
    )

def _nsfw_text_to_level( text: str) -> int:
    """Convert old NSFW text level to numeric."""
    mapping = {
        'PG': 1, 'PG-13': 2, 'R': 4, 'X': 8, 'XXX': 16, 'Banned': 32, 'Unknown': 64
    }
    return mapping.get(text, 64)  # Default to Unknown

def _create_v8_schema(cursor):
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
    _create_v11_indexes(cursor)

def _create_v2_tables(cursor):
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


def _v14_image_level(image) -> int:
    """
    How explicit one image is, as nsfw.image_level judged it when v14 was
    written (9120570): Civitai's fields only - browsingLevel, then nsfwLevel
    as a number or its legacy name, then the nsfw flag.

    A frozen copy. v14 used to import the live image_level, which has since
    learnt to read the person's prompt words and trained model - settings
    that may not be loaded this early, and a rule v14 was never written
    with - and renaming it would have stopped every pre-v14 database from
    opening. What prompts add is prompt_levels' to stamp, after startup.
    """
    pg, pg13, r, xxx, unknown = 1, 2, 4, 16, 64
    browsing = image.get("browsingLevel")
    if isinstance(browsing, int) and browsing > 0:
        return browsing
    legacy = image.get("nsfwLevel")
    if isinstance(legacy, int) and legacy > 0:
        return legacy
    if isinstance(legacy, str):
        level = {"None": pg, "Soft": pg13, "Mature": r, "X": xxx}.get(legacy)
        if level:
            return level
    if image.get("nsfw") is True:
        return r
    if image.get("nsfw") is False:
        return pg
    return unknown


def _migrate_to_v14(cursor):
    """Recompute every stored image level under the corrected rule.

    effective_nsfw_level is stamped when an image is written, so changing how
    it is judged leaves every existing row on the old verdict. The raw payload
    is stored alongside it, so the levels can be recomputed in place rather
    than refetched.

    The old legacy-string map read Soft as R and Mature as X - one grade
    harsher than Civitai means - so models were filtered out of views they
    belonged in.
    """
    print("[ModelManager] Migrating to schema v14 (recomputing image NSFW levels)...")

    image_level = _v14_image_level
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

    cursor.executemany(
        "UPDATE images SET effective_nsfw_level = ? WHERE id = ? AND version_id = ?",
        changed
    )

    print(f"[ModelManager] Reclassified {len(changed)} of {len(rows)} images")
    print("[ModelManager] Migration to v14 complete")


def _migrate_to_v15(cursor):
    """Separate "we fetched this from Civitai" from "we wrote this row".

    updated_at is stamped every time a civitai_models row is written, and a
    scan writes one for every model it finds - reading the sidecar on disk,
    without asking Civitai anything. So a Scan Disk made every model look as
    though it had just been synced, and the sync dialog's staleness windows,
    which are the whole point of choosing one, all read zero.

    civitai_synced_at is only stamped when the data actually came back from
    Civitai. Existing rows inherit updated_at, which is the best estimate
    available and errs towards calling them fresh.
    """
    print("[ModelManager] Migrating to schema v15 (recording real Civitai syncs)...")

    cursor.execute("PRAGMA table_info(civitai_models)")
    columns = {row[1] for row in cursor.fetchall()}

    if "civitai_synced_at" not in columns:
        cursor.execute("ALTER TABLE civitai_models ADD COLUMN civitai_synced_at TEXT")
        cursor.execute("UPDATE civitai_models SET civitai_synced_at = updated_at")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_model_civitai_synced_at"
            " ON civitai_models(civitai_synced_at)"
        )

    print("[ModelManager] Migration to v15 complete")


def _migrate_to_v16(cursor):
    """Forget the sync times inherited from updated_at.

    v15 gave civitai_synced_at the value of updated_at, which was the best
    estimate available - except that updated_at is exactly the field v15
    existed to stop trusting. A scan stamps it for every model it finds, so
    what was copied in was "when you last pressed Scan Disk", dressed up as
    "when Civitai was last asked". Every model therefore claimed to have been
    synced moments ago and the staleness windows stayed empty.

    NULL means no record of a sync, which the windows already read as "due" -
    so they now offer everything until each model is genuinely synced, and are
    right from then on. A model synced today loses that fact once, which is
    the cheaper mistake: the other direction hides it forever.
    """
    print("[ModelManager] Migrating to schema v16 (forgetting inherited sync times)...")

    cursor.execute("UPDATE civitai_models SET civitai_synced_at = NULL")
    print("[ModelManager] Cleared %d inherited sync times" % cursor.rowcount)
    print("[ModelManager] Migration to v16 complete")


def _migrate_to_v17(cursor):
    """Somewhere to record whether a checkpoint was trained or merged.

    Civitai accepts checkpointType as a search filter but returns it on
    neither the model nor the version, so the value cannot simply be read off
    the payload a sync already fetches - see get_checkpoint_types(). It is
    stored rather than asked for each time.

    NULL means nobody has established it, which is how the filter offers it:
    the same three-valued treatment the licence columns get.
    """
    print("[ModelManager] Migrating to schema v17 (checkpoint trained or merged)...")

    cursor.execute("PRAGMA table_info(civitai_models)")
    columns = {row[1] for row in cursor.fetchall()}

    if "checkpoint_type" not in columns:
        cursor.execute("ALTER TABLE civitai_models ADD COLUMN checkpoint_type TEXT")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_model_checkpoint_type"
            " ON civitai_models(checkpoint_type)"
        )

    print("[ModelManager] Migration to v17 complete")


def _migrate_to_v18(cursor):
    """Remember what a resource hash resolved to, so it is asked once.

    An image's generation data names the resources that went into it twice:
    Civitai's own list, which carries modelVersionId, and the legacy list from
    the infotext, which carries an AutoV2 hash and a filename. The two share no
    key, so merging them means resolving the hashes - one request each, and
    Civitai has no batch endpoint for them.

    Across a library of 101,369 images there are only 14,644 distinct hashes,
    and the common ones recur in hundreds of images, so the answers are worth
    keeping. version_id NULL with a checked_at set means Civitai was asked and
    did not know it - the same "do not ask again" the file sync records in
    civitai_lookup_failed_at.
    """
    print("[ModelManager] Migrating to schema v18 (resolved resource hashes)...")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resource_hashes (
            hash TEXT PRIMARY KEY,
            version_id INTEGER,
            model_id INTEGER,
            name TEXT,
            version_name TEXT,
            model_type TEXT,
            checked_at TEXT NOT NULL
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_resource_hashes_version"
        " ON resource_hashes(version_id)"
    )


def _migrate_to_v19(cursor):
    """Remember the order Civitai gave a version's images in.

    Civitai returns a version's images in its own ranking - not by date, not
    by id. They were stored keyed on the image id and read back ORDER BY id,
    so the Model Manager showed them oldest-first while the Civitai Browser,
    which keeps the order it was given, showed Civitai's. The two galleries of
    one model disagreed, and so did the "first 20" each judges a model by.

    `position` is an image's place within its page as Civitai sent it. Rows
    stored before this have none and keep sorting by id until their version
    is synced again, which replaces them all at once.
    """
    print("[ModelManager] Migrating to schema v19 (image order from Civitai)...")

    cursor.execute("PRAGMA table_info(images)")
    columns = {row[1] for row in cursor.fetchall()}

    if "position" not in columns:
        cursor.execute("ALTER TABLE images ADD COLUMN position INTEGER")

    print("[ModelManager] Migration to v19 complete")


def _migrate_to_v20(cursor):
    """Remember each version's cover images, for the card preview.

    The Civitai Browser's card shows a version's cover - the first image its
    creator attached - or, with NSFW not allowed, the first PG one. The Model
    Manager picked from the community gallery instead, by rating and date,
    so the same model showed a different preview in each tab.

    cover_url and pg_cover_url hold those two. NULL means not known yet, and
    '' means known to have none - a version with no PG image shows none with
    NSFW not allowed, as the Civitai Browser does.
    """
    print("[ModelManager] Migrating to schema v20 (version cover images)...")

    cursor.execute("PRAGMA table_info(model_versions)")
    columns = {row[1] for row in cursor.fetchall()}
    for column in ("cover_url", "pg_cover_url"):
        if column not in columns:
            cursor.execute(f"ALTER TABLE model_versions ADD COLUMN {column} TEXT")

    print("[ModelManager] Migration to v20 complete")


def _migrate_to_v21(cursor):
    """The NSFW-hidden cover is the first PG or PG-13 image, not the first PG.

    v20 stored the first PG image as pg_cover_url, copying what Civitai's API
    shows with NSFW off. Everywhere else here, safe means PG or PG-13, and
    the card now follows that: safe_cover_url is the first showcase image
    rated PG-13 or below.

    Values already stored are PG, so they are safe and are kept until a sync
    or scan replaces them. '' - "no PG image" - is not "no safe image", so it
    is cleared to unknown, and those versions look in the gallery until then.
    """
    print("[ModelManager] Migrating to schema v21 (safe cover is PG-13 or below)...")

    cursor.execute("PRAGMA table_info(model_versions)")
    columns = {row[1] for row in cursor.fetchall()}
    if "pg_cover_url" in columns and "safe_cover_url" not in columns:
        cursor.execute("ALTER TABLE model_versions RENAME COLUMN pg_cover_url TO safe_cover_url")
    elif "safe_cover_url" not in columns:
        cursor.execute("ALTER TABLE model_versions ADD COLUMN safe_cover_url TEXT")
    cursor.execute("UPDATE model_versions SET safe_cover_url = NULL WHERE safe_cover_url = ''")

    print("[ModelManager] Migration to v21 complete")


def _migrate_to_v22(cursor):
    """Remember what each model file's own header says it is.

    Send to txt2img has to switch Forge Neo's UI preset to a model's
    architecture, and load the text encoders and VAE it lacks - which the
    header shows, and Civitai's baseModel does not. See architecture.py.

    architecture is the Forge UI preset ("flux", "qwen", ...), or NULL when
    Forge did not recognise the file; architecture_class is Forge's model
    class, which one preset can hold several of that need different text
    encoders (Flux and Chroma, Flux.2 klein 4B and 9B); architecture_checked is the file's
    modified time when it was read, NULL for never, so a scan only reads
    files that are new or have changed.
    """
    print("[ModelManager] Migrating to schema v22 (model architecture)...")

    cursor.execute("PRAGMA table_info(model_versions)")
    columns = {row[1] for row in cursor.fetchall()}
    for column, kind in (("architecture", "TEXT"), ("architecture_class", "TEXT"),
                         ("bundled_text_encoder", "INTEGER"),
                         ("bundled_vae", "INTEGER"), ("architecture_checked", "TEXT")):
        if column not in columns:
            cursor.execute(f"ALTER TABLE model_versions ADD COLUMN {column} {kind}")

    print("[ModelManager] Migration to v22 complete")


def _migrate_to_v23(cursor):
    """Remember what each file is, by its own contents. See file_identity.py.

    file_type is what the file is - Checkpoint, LORA, LoCon, VAE, Text
    Encoder, ... - where Civitai's type is only what the uploader filed it
    under; identified_by says what decided it. NULL until a file is read,
    and the Type filter falls back to Civitai's type meanwhile.

    architecture now covers every file, not only checkpoints: a LoRA's is
    the model it was trained for. So the files read before - checkpoints
    only, and never a .ckpt or .pt - are marked unread, and the next Scan
    Disk reads them all once.
    """
    print("[ModelManager] Migrating to schema v23 (what each file is)...")

    cursor.execute("PRAGMA table_info(model_versions)")
    columns = {row[1] for row in cursor.fetchall()}
    for column in ("file_type", "identified_by"):
        if column not in columns:
            cursor.execute(f"ALTER TABLE model_versions ADD COLUMN {column} TEXT")
    cursor.execute("UPDATE model_versions SET architecture_checked = NULL WHERE file_type IS NULL")

    print("[ModelManager] Migration to v23 complete")


def _migrate_to_v24(cursor):
    """An index on images in the order a gallery shows them.

    The grid finds each card's first image, and "Only Show Models with SFW
    images" a version's first 20, in gallery order (GALLERY_ORDER: page,
    position, id). No index had that order, so each lookup sorted the
    version's images, and the grid used to rank the whole table to avoid
    doing it per row - 740 ms of a 1.3 s load on 100,651 images. The level
    is included so the SFW sample reads the index alone.
    """
    print("[ModelManager] Migrating to schema v24 (gallery-order image index)...")
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'images'")
    if cursor.fetchone() is None:
        print("[ModelManager] No images table; nothing to index")
        return
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_images_gallery"
        " ON images(version_id, page, position, id, effective_nsfw_level)"
    )
    print("[ModelManager] Migration to v24 complete")


def _migrate_to_v25(cursor, db_path: str):
    """Key images by (version_id, id): one row per gallery an image is in.

    A Civitai image is in the gallery of every resource it used, and the key
    was the image id alone, so storing one gallery took each shared image
    from any other: whichever was fetched last kept it. In one library 41,532
    of 101,242 images named two or more of its galleries, and they vanished
    from all but one. SQLite cannot change a primary key, so the table is
    rebuilt - every column and index it has, carried over as they are. The
    images already taken stay where they are until their galleries are
    fetched again. Measured on a 585 MB library: 6.5 s.

    The whole table is rewritten, so the database is backed up first, beside
    it, as v4 did. Through SQLite's backup API rather than a file copy: the
    database is in WAL mode, and a copy of the main file alone can miss what
    was written last.
    """
    print("[ModelManager] Migrating to schema v25 (images keyed by gallery and image)...")
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'images'")
    if cursor.fetchone() is None:
        print("[ModelManager] No images table; nothing to rekey")
        return
    cursor.execute("PRAGMA table_info(images)")
    columns = cursor.fetchall()
    if any(col[1] == "version_id" and col[5] for col in columns):
        print("[ModelManager] Images already keyed by gallery")
        return

    # Only where there is something to lose: a new database runs every
    # migration on its first start, and would leave an empty copy behind.
    cursor.execute("SELECT EXISTS (SELECT 1 FROM images)")
    if cursor.fetchone()[0]:
        # Migrations before this one in the same run write inside a
        # transaction still open on this connection, and a backup waits on it
        # for ever. Each migration tolerates being run again, so committing
        # them is safe - and the backup then holds them.
        if cursor.connection.in_transaction:
            cursor.connection.commit()
        backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup = sqlite3.connect(backup_path)
        try:
            cursor.connection.backup(backup)
        finally:
            backup.close()
        print(f"[ModelManager] Backed up the database to {backup_path}")

    cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'index'"
                   " AND tbl_name = 'images' AND sql IS NOT NULL")
    indexes = [row[0] for row in cursor.fetchall()]
    names = [col[1] for col in columns]
    definitions = []
    for _, name, kind, notnull, default, _ in columns:
        definition = f"{name} {kind}".strip()
        if notnull or name in ("id", "version_id"):
            definition += " NOT NULL"
        if default is not None:
            definition += f" DEFAULT {default}"
        definitions.append(definition)
    column_list = ", ".join(names)

    # A crash after the CREATE, which runs before the copy's transaction
    # opens, would leave this behind; the copy, drop and rename roll back
    # together.
    cursor.execute("DROP TABLE IF EXISTS images_v25")
    cursor.execute(f"CREATE TABLE images_v25 ({', '.join(definitions)},"
                   " PRIMARY KEY (version_id, id))")
    cursor.execute(f"INSERT INTO images_v25 ({column_list}) SELECT {column_list} FROM images")
    cursor.execute("DROP TABLE images")
    cursor.execute("ALTER TABLE images_v25 RENAME TO images")
    for sql in indexes:
        cursor.execute(sql)
    print("[ModelManager] Migration to v25 complete")


def _migrate_to_v26(cursor):
    """Remember every version Civitai lists for a model, not only the local ones.

    versions is Civitai's modelVersions, trimmed to what the details panel
    shows and a download needs. versions_synced_at is when that list came
    from Civitai itself; NULL means it was read from sidecars, which can be
    older than the model and so are only added to, never trusted to remove.
    Both NULL until a scan, a sync or the details panel fills them.
    """
    print("[ModelManager] Migrating to schema v26 (every version of a model)...")

    cursor.execute("PRAGMA table_info(civitai_models)")
    columns = {row[1] for row in cursor.fetchall()}
    if not columns:
        # No such table: a database made for one test, with only what it needs.
        print("[ModelManager] Migration to v26 complete (no models table)")
        return
    for column in ("versions", "versions_synced_at"):
        if column not in columns:
            cursor.execute(f"ALTER TABLE civitai_models ADD COLUMN {column} TEXT")

    print("[ModelManager] Migration to v26 complete")


def _migrate_to_v27(cursor):
    """Record the images you generate: three tables.

    generations holds a press of Generate - everything Forge had for it: the
    prompt as typed, the files it loaded, every processing field, the
    always-on scripts' arguments and the settings an infotext carries.
    generation_images holds each result saved to disk, with the infotext
    written into its file. generation_files is an index and nothing else:
    which image each model file was used for, so a model's gallery finds its
    generations without reading every one. A file's path is spelled as
    model_versions spells it, so the gallery joins on equality.

    The prompt's NSFW level is stamped on each image and on its generation -
    derived, and stamped again when the prompt words change; the user's own
    rating is kept apart, empty until set.
    """
    print("[ModelManager] Migrating to schema v27 (your generations)...")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            mode TEXT NOT NULL,
            forge TEXT,
            prompt TEXT,
            negative_prompt TEXT,
            styles TEXT,
            hr_prompt TEXT,
            hr_negative_prompt TEXT,
            n_iter INTEGER,
            batch_size INTEGER,
            width INTEGER,
            height INTEGER,
            checkpoint_path TEXT,
            checkpoint_hash TEXT,
            modules TEXT,
            hr_checkpoint_path TEXT,
            hr_modules TEXT,
            refiner_path TEXT,
            params TEXT,
            extra_params TEXT,
            script_args TEXT,
            settings TEXT,
            infotext TEXT,
            image_count INTEGER NOT NULL DEFAULT 0,
            prompt_nsfw_level INTEGER,
            user_nsfw_level INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generation_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generation_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            iteration INTEGER,
            path TEXT NOT NULL,
            infotext TEXT,
            meta TEXT,
            prompt TEXT,
            negative_prompt TEXT,
            seed INTEGER,
            subseed INTEGER,
            hr_prompt TEXT,
            hr_negative_prompt TEXT,
            loras TEXT,
            width INTEGER,
            height INTEGER,
            prompt_nsfw_level INTEGER,
            user_nsfw_level INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generation_files (
            file_path TEXT NOT NULL,
            image_id INTEGER NOT NULL,
            generation_id INTEGER NOT NULL,
            PRIMARY KEY (file_path, image_id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_generations_created ON generations(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_generation_images_generation "
                   "ON generation_images(generation_id, position)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_generation_files_generation "
                   "ON generation_files(generation_id)")

    print("[ModelManager] Migration to v27 complete")


def _migrate_to_v28(cursor):
    """
    Drop the Civitai Browser's image cache. Since 0.30.3 the Browser reads
    Civitai's images live and nothing reads or writes the table; what it held -
    on one library, 16,807 images and 754 cursors, about 81 MB - was never
    cleared, and was as old as each fetch. The space goes back to the file
    only on a VACUUM, which this does not run: it rewrites the whole file.
    """
    print("[ModelManager] Migrating to v28: dropping the Civitai Browser's old image cache...")
    cursor.execute("DROP INDEX IF EXISTS idx_browser_cache_version_type")
    cursor.execute("DROP TABLE IF EXISTS civitai_browser_cache")
    print("[ModelManager] Migration to v28 complete")


def _migrate_to_v29(cursor):
    """
    Pins: a card the grid puts first whenever it matches the filters. A card
    is a Civitai model, or a file Civitai does not know, so a pin names one
    or the other. Kept apart from both tables, as a bookmark would be lost
    with its model's row: a pin is the person's, and holds while a file is
    gone and back.
    """
    print("[ModelManager] Migrating to v29: pins...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pins (
            model_id INTEGER UNIQUE,
            file_path TEXT UNIQUE COLLATE NOCASE,
            pinned_at TEXT NOT NULL,
            CHECK ((model_id IS NULL) <> (file_path IS NULL))
        )
    """)
    print("[ModelManager] Migration to v29 complete")


def _migrate_to_v30(cursor):
    """
    An index for looking a file up by its path, case aside. Windows ignores
    the case of a path and SQL does not: a walk spelling a stored file another
    way made a second row for it, so a path is now looked up case-blind before
    it is stored (models_ops._stored_spelling), as the generations' already
    were (library_spelling). Without the index, each of those scanned the table.

    Only an index: a copy of the extension at v29 sharing the database runs
    as before, and leaves it alone.
    """
    print("[ModelManager] Migrating to v30: finding a file by its path, case aside...")
    if cursor.execute("PRAGMA table_info(model_versions)").fetchall():
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_path_nocase "
                       "ON model_versions(file_path COLLATE NOCASE)")
    print("[ModelManager] Migration to v30 complete")


def _migrate_to_v31(cursor):
    """
    A LoRA's alias - ss_output_name from its metadata - which Forge loads it
    by beside its file name, and puts in a prompt when "Alias from file" is
    chosen. A chip looks a LoRA up by it (#11).

    Every LoRA-family file is marked unread, so the next Scan Disk reads each
    one's alias; nothing else is read again. The family is written out here,
    not imported: a migration keeps the rule it was written with.
    """
    print("[ModelManager] Migrating to v31: a LoRA's alias...")
    cursor.execute("PRAGMA table_info(model_versions)")
    columns = {row[1] for row in cursor.fetchall()}
    if columns and "lora_alias" not in columns:
        cursor.execute("ALTER TABLE model_versions ADD COLUMN lora_alias TEXT")
    if {"file_type", "architecture_checked"} <= columns:
        cursor.execute("UPDATE model_versions SET architecture_checked = NULL WHERE file_type IN "
                       "('LORA', 'LoCon', 'LoHa', 'LoKr', 'DoRA', 'LyCORIS Full')")
    print("[ModelManager] Migration to v31 complete")


# The columns of a file, and of the version its files share (#133): what
# model_versions held together, one copy of a version per file. Written out,
# not read from the code: a migration keeps the shape it was written with.
_V32_FILE_COLUMNS = (
    "file_path", "file_name", "file_size", "file_hashes", "file_modified", "file_extension",
    "scanned_at", "downloaded_at", "civitai_lookup_failed_at", "architecture",
    "architecture_class", "bundled_text_encoder", "bundled_vae", "architecture_checked",
    "file_type", "identified_by", "lora_alias",
)
_V32_VERSION_COLUMNS = (
    "model_id", "version_name", "base_model", "published_at", "created_at", "nsfw_level",
    "trained_words", "description", "stats_download_count", "stats_thumbs_up",
    "cover_url", "safe_cover_url",
)
# What a copy says nothing with, beside NULL: an empty list of words, a level
# of Unknown (64, as nsfw.py had it). '' in a cover column says "has none".
_V32_SAYS_NOTHING = {"trained_words": ("[]",), "nsfw_level": (64,)}
_V32_HIGHEST = ("stats_download_count", "stats_thumbs_up")


def _create_v32_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS versions (
            id INTEGER PRIMARY KEY,
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
            cover_url TEXT,
            safe_cover_url TEXT,
            next_images_cursor TEXT DEFAULT NULL,
            images_sync_last_date TEXT DEFAULT NULL,
            FOREIGN KEY (model_id) REFERENCES models(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            file_path TEXT PRIMARY KEY NOT NULL,
            version_id INTEGER,
            file_name TEXT NOT NULL,
            file_size INTEGER,
            file_hashes TEXT DEFAULT NULL,
            file_modified TEXT,
            file_extension TEXT,
            scanned_at TEXT,
            downloaded_at TEXT DEFAULT NULL,
            civitai_lookup_failed_at TEXT,
            architecture TEXT,
            architecture_class TEXT,
            bundled_text_encoder INTEGER,
            bundled_vae INTEGER,
            architecture_checked TEXT,
            file_type TEXT,
            identified_by TEXT,
            lora_alias TEXT,
            civitai_file_id INTEGER,
            civitai_file_type TEXT,
            fp TEXT,
            size TEXT,
            format TEXT,
            civitai_primary INTEGER,
            FOREIGN KEY (version_id) REFERENCES versions(id)
        )
    """)
    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_versions_model_published ON versions(model_id, published_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_versions_base_model ON versions(base_model)",
        "CREATE INDEX IF NOT EXISTS idx_versions_nsfw_level ON versions(nsfw_level)",
        "CREATE INDEX IF NOT EXISTS idx_versions_published_at ON versions(published_at)",
        "CREATE INDEX IF NOT EXISTS idx_files_version ON files(version_id)",
        "CREATE INDEX IF NOT EXISTS idx_files_path_nocase ON files(file_path COLLATE NOCASE)",
        "CREATE INDEX IF NOT EXISTS idx_files_file_modified ON files(file_modified)",
        "CREATE INDEX IF NOT EXISTS idx_files_scanned_at ON files(scanned_at)",
        "CREATE INDEX IF NOT EXISTS idx_files_downloaded_at ON files(downloaded_at)",
        "CREATE INDEX IF NOT EXISTS idx_files_lookup_failed ON files(civitai_lookup_failed_at)",
        "CREATE INDEX IF NOT EXISTS idx_files_civitai_file ON files(civitai_file_id)",
    ):
        cursor.execute(sql)


def _v32_merge(copies):
    """
    One version from its copies, one per file. The copy whose gallery was
    synced last speaks first - its cursor and the date it was written go
    together - then the others, for whatever it says nothing about; the stats,
    each copy as of its own last sync, take the highest.
    """
    # Newest gallery sync first, then the undated, newest scan first.
    dated = sorted((c for c in copies if c["images_sync_last_date"]),
                   key=lambda c: (c["images_sync_last_date"], c["scanned_at"] or ""), reverse=True)
    undated = sorted((c for c in copies if not c["images_sync_last_date"]),
                     key=lambda c: c["scanned_at"] or "", reverse=True)
    copies = dated + undated
    merged = {"next_images_cursor": copies[0]["next_images_cursor"],
              "images_sync_last_date": copies[0]["images_sync_last_date"]}
    for column in _V32_VERSION_COLUMNS:
        held = [c[column] for c in copies if c[column] is not None]
        saying = [v for v in held if v not in _V32_SAYS_NOTHING.get(column, ())]
        if column in _V32_HIGHEST and saying:
            merged[column] = max(saying)
        else:
            # Where no copy says more, what they hold: Unknown stays Unknown.
            merged[column] = (saying or held or [None])[0]
    return merged


def _v32_civitai_files(cursor, models_table: str):
    """
    Each file's id on Civitai and what Civitai says of it - its type there,
    fp, size, format, whether primary - from its version's files in the
    version list kept on its model (v26), by name, its case aside: what a
    library holds of them before a sync matches each by its hash. A file the
    list does not name - renamed on disk - is left for the sync.
    """
    listed = {}
    for (versions,) in cursor.execute(f"SELECT versions FROM {models_table} WHERE versions IS NOT NULL").fetchall():
        try:
            for version in json.loads(versions):
                if isinstance(version, dict) and version.get("id") is not None:
                    listed[version["id"]] = [f for f in version.get("files") or [] if isinstance(f, dict)]
        except (TypeError, ValueError):
            continue
    rows = []
    for path, name, version_id in cursor.execute(
            "SELECT file_path, file_name, version_id FROM files WHERE version_id IS NOT NULL").fetchall():
        found = next((f for f in listed.get(version_id, ())
                      if str(f.get("name") or "").lower() == str(name or "").lower()), None)
        if found is None:
            continue
        meta = found.get("metadata") if isinstance(found.get("metadata"), dict) else {}
        primary = found.get("primary")
        rows.append((found.get("id"), found.get("type"), meta.get("fp"), meta.get("size"), meta.get("format"),
                     None if primary is None else (1 if primary else 0), path))
    cursor.executemany("UPDATE files SET civitai_file_id = ?, civitai_file_type = ?, fp = ?, size = ?, "
                       "format = ?, civitai_primary = ? WHERE file_path = ?", rows)


def _migrate_to_v32(cursor, db_path: str):
    """
    A version is one row, and its files rows of their own (#133).

    model_versions held one row per file, with its own copy of the version's
    data: a version with two files was fetched, counted and read as two, and
    its copies drifted - in one library, 26 of 36 such versions had copies
    disagreeing on their gallery's cursor. Its rows become a file each in
    `files`, and each version one row in `versions`, merged from its copies
    (_v32_merge). A file Civitai does not know has no version, and no model:
    it is a row of `files` alone. So no table is named for Civitai, and
    civitai_models becomes `models`.

    model_versions is dropped, not kept beside: a copy of the extension from
    before this version, sharing the database, finds no table to read or
    write, and fails rather than writes the old shape. The database is backed
    up first, beside it, as v25 did.

    The tables are made outside the copy's transaction: while model_versions
    is there, the split is not done, and is done again from it.
    """
    print("[ModelManager] Migrating to schema v32 (a version's files apart from it)...")
    tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    copies = {}
    if "model_versions" in tables:
        if cursor.execute("SELECT EXISTS (SELECT 1 FROM model_versions)").fetchone()[0]:
            if cursor.connection.in_transaction:
                cursor.connection.commit()
            backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            backup = sqlite3.connect(backup_path)
            try:
                cursor.connection.backup(backup)
            finally:
                backup.close()
            print(f"[ModelManager] Backed up the database to {backup_path}")
        cursor.execute("DROP TABLE IF EXISTS files")
        cursor.execute("DROP TABLE IF EXISTS versions")
    _create_v32_tables(cursor)

    if "model_versions" in tables:
        names = ", ".join(_V32_FILE_COLUMNS)
        # In table order, which decides between files that share a hash or an id.
        cursor.execute(f"INSERT INTO files ({names}, version_id) "
                       f"SELECT {names}, id FROM model_versions ORDER BY rowid")
        columns = _V32_VERSION_COLUMNS + ("id", "next_images_cursor", "images_sync_last_date", "scanned_at")
        for row in cursor.execute(f"SELECT {', '.join(columns)} FROM model_versions "
                                  "WHERE id IS NOT NULL ORDER BY rowid").fetchall():
            copy = dict(zip(columns, row))
            copies.setdefault(copy["id"], []).append(copy)
        written = ("id",) + _V32_VERSION_COLUMNS + ("next_images_cursor", "images_sync_last_date")
        cursor.executemany(
            f"INSERT INTO versions ({', '.join(written)}) VALUES ({', '.join('?' * len(written))})",
            [tuple({"id": version_id, **_v32_merge(group)}[c] for c in written)
             for version_id, group in copies.items()])
        _v32_civitai_files(cursor, "civitai_models" if "civitai_models" in tables else "models")
        cursor.execute("DROP TABLE model_versions")

    if "civitai_models" in tables and "models" not in tables:
        cursor.execute("ALTER TABLE civitai_models RENAME TO models")
    print(f"[ModelManager] Migration to v32 complete: {len(copies)} versions")

def _migrate_to_v33(cursor):
    """
    When a file's hashes were read from the file itself: `hashes_checked`,
    its size and modified time then (hashing.fingerprint). A stored hash is
    trusted - Civitai asked with it, rather than gigabytes read again - only
    while the file is as it was. Nothing is filled in: of the hashes already
    stored, the ones Scan Disk copied from a sidecar cannot be told from the
    ones a sync read, and none is trusted.

    It is also a fence: a copy of the extension from before it refuses the
    database (_init_db) - and with it, its Scan Disk, which would write a
    sidecar's hashes over a file's own.
    """
    print("[ModelManager] Migrating to v33: when a file's hashes were read...")
    cursor.execute("PRAGMA table_info(files)")
    columns = {row[1] for row in cursor.fetchall()}
    if columns and "hashes_checked" not in columns:
        cursor.execute("ALTER TABLE files ADD COLUMN hashes_checked TEXT")
    print("[ModelManager] Migration to v33 complete")


def _migrate_to_v34(cursor):
    """
    The generation queue (#17). `tasks` holds one row per press of Queue:
    every input Generate would have been sent, by name, kept to run later,
    and what the queue made of it. `task_generations` names the generations
    a task's run made - one per cell of an X/Y/Z plot, so a task can have
    several. A task belongs to the install that queued it (`install`): two
    WebUIs sharing this database have different extensions, and neither can
    run the other's tasks.
    """
    print("[ModelManager] Migrating to v34: the generation queue...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            install TEXT NOT NULL,
            forge TEXT,
            mode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            inputs TEXT NOT NULL,
            checkpoint TEXT,
            modules TEXT,
            username TEXT,
            first_seed INTEGER,
            error TEXT,
            retry_of INTEGER,
            hidden INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_generations (
            task_id INTEGER NOT NULL,
            generation_id INTEGER NOT NULL,
            PRIMARY KEY (task_id, generation_id)
        )
    """)
    # The queue's next task, and Active in run order; History newest first.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_queue ON tasks(install, status, id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_history "
                   "ON tasks(install, hidden, finished_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_retry_of ON tasks(retry_of)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_generations_generation "
                   "ON task_generations(generation_id)")
    print("[ModelManager] Migration to v34 complete")


def _migrate_to_v35(cursor):
    """
    The download queue, kept across a restart in a table of its own (#187).
    Until now each install kept a JSON list in schema_info, under
    "downloads:<install>", and only of downloads with a .partial: a restart
    forgot every download still waiting. `downloads` holds each install's
    downloads not over, one row each, in the list's order (`position`); the
    lists kept so far become its rows, and their keys go. A list that cannot
    be read is dropped with its key.

    Scan Disk's `last_scan` goes too: nothing has read it since 0.48.3, and
    nothing ever did.
    """
    print("[ModelManager] Migrating to v35: the download queue...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            install TEXT NOT NULL,
            version_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            model_id INTEGER,
            file_id INTEGER,
            file_index INTEGER,
            file_name TEXT,
            partial_path TEXT,
            total_bytes INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (install, version_id)
        )
    """)
    cursor.execute("SELECT key, value FROM schema_info WHERE key LIKE 'downloads:%'")
    for key, value in cursor.fetchall():
        install = key[len("downloads:"):]
        try:
            entries = [e for e in json.loads(value or "[]") if isinstance(e, dict)]
        except (TypeError, ValueError):
            print(f"[ModelManager] v35: could not read the downloads kept under {key}; dropped")
            entries = []
        for position, entry in enumerate(entries):
            if entry.get("version_id") is None:
                continue
            cursor.execute(
                "INSERT OR IGNORE INTO downloads (install, version_id, position, model_id, file_id, "
                "file_index, file_name, partial_path, total_bytes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (install, entry["version_id"], position, entry.get("model_id"), entry.get("file_id"),
                 entry.get("file_index"), entry.get("file_name"), entry.get("partial_path"),
                 entry.get("total_bytes") or 0))
        cursor.execute("DELETE FROM schema_info WHERE key = ?", (key,))
    cursor.execute("DELETE FROM schema_info WHERE key = 'last_scan'")
    print("[ModelManager] Migration to v35 complete")


def run_migrations(cursor, from_version: int, to_version: int,
                   db_path: str, db_dir: str):
    """Bring a database from `from_version` up to `to_version`, and no further."""
    print(f"[ModelManager] Migrating database from v{from_version} to v{to_version}...")

    # Only v4, v25 and v32 take the path; v4 the directory too. Each makes a
    # backup first.
    steps = {
        2: _migrate_to_v2, 3: _migrate_to_v3,
        4: lambda c: _migrate_to_v4(c, db_path, db_dir),
        5: _migrate_to_v5, 6: _migrate_to_v6, 7: _migrate_to_v7, 8: _migrate_to_v8,
        9: _migrate_to_v9, 10: _migrate_to_v10, 11: _migrate_to_v11, 12: _migrate_to_v12,
        13: _migrate_to_v13, 14: _migrate_to_v14, 15: _migrate_to_v15, 16: _migrate_to_v16,
        17: _migrate_to_v17, 18: _migrate_to_v18, 19: _migrate_to_v19, 20: _migrate_to_v20,
        21: _migrate_to_v21, 22: _migrate_to_v22, 23: _migrate_to_v23, 24: _migrate_to_v24,
        25: lambda c: _migrate_to_v25(c, db_path),
        26: _migrate_to_v26, 27: _migrate_to_v27, 28: _migrate_to_v28, 29: _migrate_to_v29,
        30: _migrate_to_v30, 31: _migrate_to_v31,
        32: lambda c: _migrate_to_v32(c, db_path),
        33: _migrate_to_v33, 34: _migrate_to_v34, 35: _migrate_to_v35,
    }
    for version in sorted(steps):
        if from_version < version <= to_version:
            steps[version](cursor)

    cursor.execute(
        "INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', ?)",
        (str(to_version),)
    )
    print("[ModelManager] Database migration complete.")
