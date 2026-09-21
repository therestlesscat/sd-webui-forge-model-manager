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

    from ..nsfw import image_level

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


def run_migrations(cursor, from_version: int, to_version: int,
                   db_path: str, db_dir: str):
    """Bring a database from `from_version` up to `to_version`."""
    print(f"[ModelManager] Migrating database from v{from_version} to v{to_version}...")

    if from_version < 2:
        _migrate_to_v2(cursor, db_path, db_dir)

    if from_version < 3:
        _migrate_to_v3(cursor)

    if from_version < 4:
        _migrate_to_v4(cursor, db_path, db_dir)

    if from_version < 5:
        _migrate_to_v5(cursor)

    if from_version < 6:
        _migrate_to_v6(cursor)

    if from_version < 7:
        _migrate_to_v7(cursor)

    if from_version < 8:
        _migrate_to_v8(cursor)

    if from_version < 9:
        _migrate_to_v9(cursor)

    if from_version < 10:
        _migrate_to_v10(cursor)

    if from_version < 11:
        _migrate_to_v11(cursor)

    if from_version < 12:
        _migrate_to_v12(cursor)

    if from_version < 13:
        _migrate_to_v13(cursor)

    if from_version < 14:
        _migrate_to_v14(cursor)

    cursor.execute(
        "INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', ?)",
        (str(to_version),)
    )
    print("[ModelManager] Database migration complete.")
