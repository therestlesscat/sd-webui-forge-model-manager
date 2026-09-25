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


def run_migrations(cursor, from_version: int, to_version: int,
                   db_path: str, db_dir: str):
    """Bring a database from `from_version` up to `to_version`."""
    print(f"[ModelManager] Migrating database from v{from_version} to v{to_version}...")

    if from_version < 2:
        # Only v4 takes the path and the directory; it makes a backup first.
        _migrate_to_v2(cursor)

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

    if from_version < 15:
        _migrate_to_v15(cursor)

    if from_version < 16:
        _migrate_to_v16(cursor)

    if from_version < 17:
        _migrate_to_v17(cursor)

    if from_version < 18:
        _migrate_to_v18(cursor)

    if from_version < 19:
        _migrate_to_v19(cursor)

    if from_version < 20:
        _migrate_to_v20(cursor)

    if from_version < 21:
        _migrate_to_v21(cursor)

    if from_version < 22:
        _migrate_to_v22(cursor)

    if from_version < 23:
        _migrate_to_v23(cursor)

    if from_version < 24:
        _migrate_to_v24(cursor)

    cursor.execute(
        "INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', ?)",
        (str(to_version),)
    )
    print("[ModelManager] Database migration complete.")
