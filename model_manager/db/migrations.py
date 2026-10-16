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


def _migrate_to_v36(cursor):
    """
    A generation keeps the named inputs of the press that made it (#7) - what
    Generate was sent, as a queued task keeps it - so its Send sets each
    control back as Load to UI does, not through Forge's paste, which loses
    the hires checkpoint and modules and the refiner's. One column, empty for
    every generation recorded before: their Send corrects the paste from
    the paths they kept.
    """
    print("[ModelManager] Migrating to v36: what each generation was sent...")
    cursor.execute("PRAGMA table_info(generations)")
    if "inputs" not in {row[1] for row in cursor.fetchall()}:
        cursor.execute("ALTER TABLE generations ADD COLUMN inputs TEXT")
    print("[ModelManager] Migration to v36 complete")


# v37's tables, as they were made. The indexes are made after the old tables
# are dropped: two of their names were the old tables' too.
_V37_TABLES = """
    CREATE TABLE prompts_v37 (
        id         INTEGER PRIMARY KEY,
        text       TEXT NOT NULL UNIQUE,
        grouped_as INTEGER NOT NULL,
        length     INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE generations_v37 (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at        TEXT NOT NULL,
        mode              TEXT NOT NULL,
        forge             TEXT,
        prompt_id         INTEGER,
        negative_id       INTEGER,
        image_count       INTEGER NOT NULL DEFAULT 0,
        prompt_nsfw_level INTEGER,
        user_nsfw_level   INTEGER
    );
    CREATE TABLE generation_details_v37 (
        generation_id      INTEGER PRIMARY KEY,
        checkpoint_path    TEXT,
        modules            TEXT,
        hr_checkpoint_path TEXT,
        hr_modules         TEXT,
        refiner_path       TEXT,
        infotext           TEXT,
        styles             TEXT,
        hr_prompt          TEXT,
        hr_negative_prompt TEXT,
        n_iter             INTEGER,
        batch_size         INTEGER,
        width              INTEGER,
        height             INTEGER,
        checkpoint_hash    TEXT,
        params             TEXT,
        extra_params       TEXT,
        script_args        TEXT,
        settings           TEXT,
        inputs             TEXT
    );
    CREATE TABLE generation_images_v37 (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        generation_id     INTEGER NOT NULL,
        position          INTEGER NOT NULL,
        iteration         INTEGER,
        path              TEXT NOT NULL,
        prompt_id         INTEGER,
        negative_id       INTEGER,
        seed              INTEGER,
        subseed           INTEGER,
        width             INTEGER,
        height            INTEGER,
        prompt_nsfw_level INTEGER,
        user_nsfw_level   INTEGER
    );
    CREATE TABLE image_details_v37 (
        image_id           INTEGER PRIMARY KEY,
        infotext           TEXT,
        meta               TEXT,
        loras              TEXT,
        hr_prompt          TEXT,
        hr_negative_prompt TEXT
    );
    CREATE TABLE generation_resources_v37 (
        image_id      INTEGER NOT NULL,
        generation_id INTEGER NOT NULL,
        role          TEXT NOT NULL,
        position      INTEGER NOT NULL,
        name          TEXT NOT NULL,
        file_path     TEXT,
        weight        REAL,
        PRIMARY KEY (image_id, role, position)
    ) WITHOUT ROWID;
"""
_V37_INDEXES = """
    CREATE INDEX IF NOT EXISTS idx_prompts_grouped ON prompts(grouped_as);
    CREATE INDEX IF NOT EXISTS idx_prompts_lookup ON prompts(id, grouped_as, length);
    CREATE INDEX IF NOT EXISTS idx_generations_created ON generations(created_at, id);
    CREATE INDEX IF NOT EXISTS idx_images_generation
        ON generation_images(generation_id, position, prompt_nsfw_level, user_nsfw_level);
    CREATE INDEX IF NOT EXISTS idx_images_prompt ON generation_images(prompt_id);
    CREATE INDEX IF NOT EXISTS idx_resources_path ON generation_resources(file_path, generation_id);
    CREATE INDEX IF NOT EXISTS idx_resources_role ON generation_resources(role, name, image_id);
    CREATE INDEX IF NOT EXISTS idx_resources_role_generation
        ON generation_resources(role, generation_id, name, file_path);
"""
# Columns kept as they are, by the table that keeps them.
_V37_GENERATION = ("id", "created_at", "mode", "forge", "image_count",
                   "prompt_nsfw_level", "user_nsfw_level")
_V37_GENERATION_DETAILS = ("checkpoint_path", "modules", "hr_checkpoint_path", "hr_modules",
                           "refiner_path", "infotext", "styles", "hr_prompt", "hr_negative_prompt",
                           "n_iter", "batch_size", "width", "height", "checkpoint_hash", "params",
                           "extra_params", "script_args", "settings", "inputs")
_V37_IMAGE = ("id", "generation_id", "position", "iteration", "path", "seed", "subseed",
              "width", "height", "prompt_nsfw_level", "user_nsfw_level")
_V37_IMAGE_DETAILS = ("infotext", "meta", "loras", "hr_prompt", "hr_negative_prompt")


def _v37_tidy(text):
    """A prompt with its spacing tidied, as v37 found the Generations tab grouping
    prompts (_one_line in api/generations.py): frozen here, as migrations must be."""
    return " ".join(str(text if text is not None else "").split())


def _v37_list(value):
    try:
        found = json.loads(value) if value else []
    except (TypeError, ValueError):
        return []
    return found if isinstance(found, list) else []


def _v37_row(cursor, row):
    return dict(row) if hasattr(row, "keys") else dict(zip([d[0] for d in cursor.description], row))


def _v37_stem(path):
    return os.path.splitext(os.path.basename(path or ""))[0]


def _v37_resources(generation, image, files, module_roles):
    """
    The files one image used, each as (role, position, name, path, weight):
    named by the lists the generation and the image recorded, and spelled as
    generation_files spells them - the library's spelling, which followed a
    file that was moved. A recorded path is matched to its generation_files
    row ignoring case; what is left, by its file name, which a move keeps -
    after every exact match, so a name never takes another file's row. A
    generation_files row no list names is kept as `other`.
    """
    entries = []
    if generation["checkpoint_path"]:
        entries.append(["checkpoint", 0, generation["checkpoint_path"], None])
    for position, path in enumerate(_v37_list(generation["modules"])):
        if isinstance(path, str) and path:
            entries.append(["module", position, path, None])
    if generation["hr_checkpoint_path"]:
        entries.append(["hr_checkpoint", 0, generation["hr_checkpoint_path"], None])
    for position, path in enumerate(_v37_list(generation["hr_modules"])):
        if isinstance(path, str) and path:
            entries.append(["hr_module", position, path, None])
    if generation["refiner_path"]:
        entries.append(["refiner", 0, generation["refiner_path"], None])
    for position, lora in enumerate(_v37_list(image["loras"])):
        if isinstance(lora, dict):
            entries.append(["lora", position, lora.get("path") if isinstance(lora.get("path"), str) else None,
                            lora])

    unclaimed = list(files)
    spelled = [None] * len(entries)
    for test in (lambda f, p: f.lower() == p.lower(),
                 lambda f, p: os.path.basename(f).lower() == os.path.basename(p).lower()):
        for index, (_, _, path, _) in enumerate(entries):
            if spelled[index] is None and path:
                found = next((f for f in unclaimed if test(f, path)), None)
                if found is not None:
                    unclaimed.remove(found)
                    spelled[index] = found
    for index, (_, _, path, _) in enumerate(entries):
        # The same file named twice - a LoRA loaded twice, a hires checkpoint
        # that is the checkpoint - shares its one generation_files row.
        if spelled[index] is None and path:
            spelled[index] = next((f for f in files if f.lower() == path.lower()), None) or \
                next((f for f in files if os.path.basename(f).lower() == os.path.basename(path).lower()), path)

    rows = []
    for (role, position, path, lora), found in zip(entries, spelled):
        if role == "lora":
            weight = lora.get("te_multiplier")
            if weight is None:
                weight = lora.get("weight")
            if not isinstance(weight, (int, float)) or isinstance(weight, bool):
                weight = None
            name = lora.get("name")
            rows.append(("lora", position, str(name) if name else "", found, weight))
        else:
            if role == "module":
                role = module_roles.get((found or "").lower(), "module")
            rows.append((role, position, _v37_stem(path), found, None))
    for position, path in enumerate(unclaimed):
        rows.append(("other", position, _v37_stem(path), path, None))
    return rows


def _migrate_to_v37(cursor, db_path: str):
    """
    The generation tables, redesigned to hold tens of thousands of images
    (#231). Lists, groups and filters read narrow tables; what one tile or one
    Send reads is kept apart, in a details table for each; each prompt text
    once; and every file an image used one row of generation_resources, with
    its role and its place in the list it came from. generation_files goes.

    Lossless: every value of every row is kept, the same value and type -
    the lists and paths as Forge recorded them in the details tables, the
    resources an index made from them. Before anything is dropped, every old
    row is rebuilt from the new tables and compared, and the resources'
    files must be the same set as generation_files; any difference raises,
    and the caller's transaction leaves the old tables as they were. The
    database is backed up first, beside it, as v25 and v32 did.

    Prompts group by `grouped_as`: the row holding the text with its spacing
    tidied, made where no prompt had it, so recording a prompt finds its
    group by one lookup - 0 for a prompt that tidies to nothing, as a
    missing one does.
    """
    print("[ModelManager] Migrating to v37: the generation tables, for tens of thousands of images...")
    tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "generation_files" not in tables and "generation_resources" in tables:
        print("[ModelManager] Migration to v37 already done")
        return
    connection = cursor.connection
    if connection.in_transaction:
        connection.commit()
    if cursor.execute("SELECT EXISTS (SELECT 1 FROM generations)").fetchone()[0]:
        backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup = sqlite3.connect(backup_path)
        try:
            connection.backup(backup)
        finally:
            backup.close()
        print(f"[ModelManager] Backed up the database to {backup_path}")

    # One transaction for every step: the caller's commit ends it, a raise
    # rolls it back.
    cursor.execute("BEGIN")
    for name in ("prompts", "generations", "generation_details", "generation_images",
                 "image_details", "generation_resources"):
        cursor.execute(f"DROP TABLE IF EXISTS {name}_v37")
    for statement in _V37_TABLES.split(";"):
        if statement.strip():
            cursor.execute(statement)

    sequences = {name: seq for name, seq in cursor.execute(
        "SELECT name, seq FROM sqlite_sequence WHERE name IN ('generations', 'generation_images')")}

    # Prompts: each text once, in the order first met. A prompt groups by the
    # row holding its tidied text - made if no prompt had it - so recording
    # one finds its group by one lookup.
    prompt_ids = {}

    def prompt_id(text):
        if text is None:
            return None
        if text not in prompt_ids:
            tidied = _v37_tidy(text)
            grouped = 0 if tidied == "" else None if tidied == text else prompt_id(tidied)
            new_id = len(prompt_ids) + 1
            prompt_ids[text] = new_id
            cursor.execute("INSERT INTO prompts_v37 (id, text, grouped_as) VALUES (?, ?, ?)",
                           (new_id, text, new_id if grouped is None else grouped))
        return prompt_ids[text]

    generations = {}
    for row in cursor.execute("SELECT * FROM generations ORDER BY id").fetchall():
        row = _v37_row(cursor, row)
        generations[row["id"]] = row
        cursor.execute(
            f"INSERT INTO generations_v37 ({', '.join(_V37_GENERATION)}, prompt_id, negative_id) "
            f"VALUES ({', '.join('?' * (len(_V37_GENERATION) + 2))})",
            [row[c] for c in _V37_GENERATION] + [prompt_id(row["prompt"]), prompt_id(row["negative_prompt"])])
        cursor.execute(
            f"INSERT INTO generation_details_v37 (generation_id, {', '.join(_V37_GENERATION_DETAILS)}) "
            f"VALUES ({', '.join('?' * (len(_V37_GENERATION_DETAILS) + 1))})",
            [row["id"]] + [row[c] for c in _V37_GENERATION_DETAILS])

    files_of = {}
    for path, image_id in cursor.execute("SELECT file_path, image_id FROM generation_files "
                                         "ORDER BY image_id, file_path").fetchall():
        files_of.setdefault(image_id, []).append(path)
    # A module's role, from what the library read the file to be; a file the
    # library does not hold is a module, nothing more.
    module_roles = {}
    for path, file_type in cursor.execute("SELECT file_path, file_type FROM files "
                                          "WHERE file_type IN ('VAE', 'Text Encoder')").fetchall():
        module_roles[path.lower()] = "vae" if file_type == "VAE" else "text_encoder"

    for row in cursor.execute("SELECT * FROM generation_images ORDER BY id").fetchall():
        row = _v37_row(cursor, row)
        cursor.execute(
            f"INSERT INTO generation_images_v37 ({', '.join(_V37_IMAGE)}, prompt_id, negative_id) "
            f"VALUES ({', '.join('?' * (len(_V37_IMAGE) + 2))})",
            [row[c] for c in _V37_IMAGE] + [prompt_id(row["prompt"]), prompt_id(row["negative_prompt"])])
        cursor.execute(
            f"INSERT INTO image_details_v37 (image_id, {', '.join(_V37_IMAGE_DETAILS)}) "
            f"VALUES ({', '.join('?' * (len(_V37_IMAGE_DETAILS) + 1))})",
            [row["id"]] + [row[c] for c in _V37_IMAGE_DETAILS])
        generation = generations.get(row["generation_id"]) or {
            "checkpoint_path": None, "modules": None, "hr_checkpoint_path": None,
            "hr_modules": None, "refiner_path": None}
        cursor.executemany(
            "INSERT INTO generation_resources_v37 (image_id, generation_id, role, position, name, "
            "file_path, weight) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(row["id"], row["generation_id"], *resource)
             for resource in _v37_resources(generation, row, files_of.get(row["id"], []), module_roles)])

    # How long each prompt is, trimmed as a prompt worth reading is
    # (prompt_rules.readable): read for every image the prompt switch counts,
    # it is kept beside the group, where an index holds both.
    cursor.execute("UPDATE prompts_v37 SET length = LENGTH(TRIM(text, char(32) || char(9) || char(13) || char(10)))")

    _v37_check(cursor)

    for name in ("generation_files", "generation_images", "generations"):
        cursor.execute(f"DROP TABLE {name}")
    for name in ("prompts", "generations", "generation_details", "generation_images",
                 "image_details", "generation_resources"):
        cursor.execute(f"ALTER TABLE {name}_v37 RENAME TO {name}")
    for statement in _V37_INDEXES.split(";"):
        if statement.strip():
            cursor.execute(statement)
    # A deleted id is never given again: each table keeps the highest ever given.
    for name, seq in sequences.items():
        cursor.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (seq, name))
        if not cursor.rowcount:
            cursor.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (name, seq))
    print(f"[ModelManager] Migration to v37 complete: {len(generations)} generations, "
          f"{len(prompt_ids)} distinct prompts")


def _v37_check(cursor):
    """
    Every old row, rebuilt from v37's tables, equal in every column - value
    and SQLite type - and the resources' files the same set as
    generation_files. Raises on any difference, naming the first.
    """
    def same(old, new):
        return f"({old} IS {new} AND typeof({old}) = typeof({new}))"

    checks = {
        "generations": (
            "SELECT o.id FROM generations o LEFT JOIN generations_v37 n ON n.id = o.id "
            "LEFT JOIN generation_details_v37 d ON d.generation_id = o.id "
            "LEFT JOIN prompts_v37 p ON p.id = n.prompt_id LEFT JOIN prompts_v37 q ON q.id = n.negative_id "
            "WHERE n.id IS NULL OR d.generation_id IS NULL OR NOT ("
            + " AND ".join([same(f"o.{c}", f"n.{c}") for c in _V37_GENERATION]
                           + [same(f"o.{c}", f"d.{c}") for c in _V37_GENERATION_DETAILS]
                           + [same("o.prompt", "p.text"), same("o.negative_prompt", "q.text")])
            + ") LIMIT 1"),
        "generation_images": (
            "SELECT o.id FROM generation_images o LEFT JOIN generation_images_v37 n ON n.id = o.id "
            "LEFT JOIN image_details_v37 d ON d.image_id = o.id "
            "LEFT JOIN prompts_v37 p ON p.id = n.prompt_id LEFT JOIN prompts_v37 q ON q.id = n.negative_id "
            "WHERE n.id IS NULL OR d.image_id IS NULL OR NOT ("
            + " AND ".join([same(f"o.{c}", f"n.{c}") for c in _V37_IMAGE]
                           + [same(f"o.{c}", f"d.{c}") for c in _V37_IMAGE_DETAILS]
                           + [same("o.prompt", "p.text"), same("o.negative_prompt", "q.text")])
            + ") LIMIT 1"),
        # The two sets equal: each generation_files row among the resources,
        # and each resource's file one generation_files named for its image.
        "generation_files": (
            "SELECT o.image_id FROM generation_files o WHERE NOT EXISTS (SELECT 1 FROM "
            "generation_resources_v37 r WHERE r.image_id = o.image_id AND r.generation_id = o.generation_id "
            "AND r.file_path IS o.file_path) LIMIT 1"),
        "generation_resources": (
            "SELECT r.image_id FROM generation_resources_v37 r WHERE r.file_path IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM generation_files o WHERE o.image_id = r.image_id "
            "AND o.generation_id = r.generation_id AND o.file_path IS r.file_path) LIMIT 1"),
    }
    for table, sql in checks.items():
        row = cursor.execute(sql).fetchone()
        if row is not None:
            raise RuntimeError(f"[ModelManager] v37 would lose data: {table} row {row[0]} does not "
                               "come back the same. Nothing was changed.")
    for old, new in (("generations", "generations_v37"), ("generation_images", "generation_images_v37"),
                     ("generations", "generation_details_v37"),
                     ("generation_images", "image_details_v37")):
        if cursor.execute(f"SELECT COUNT(*) FROM {old}").fetchone()[0] != \
                cursor.execute(f"SELECT COUNT(*) FROM {new}").fetchone()[0]:
            raise RuntimeError(f"[ModelManager] v37 would lose data: {new} has not as many rows as "
                               f"{old}. Nothing was changed.")


def _migrate_to_v38(cursor):
    """
    Images already on disk, synced into the Generations tab (#233). Nothing is
    changed or dropped; v38 only adds:

    - image_sources: each folder a sync brought images from, once, and
      generations.source_id naming it - empty for a generation the recorder
      wrote. Remove folder takes back what its folder brought; a number keeps
      the narrow table narrow, where a path would add about 80 bytes a row;
    - removed_images: files whose rows were deleted with the file kept, as it
      was then, so a sync does not bring them back;
    - an index on each image's path, ignoring case: the recorder replaces an
      imported row for the file it saves, and a sync skips what is held.
    """
    print("[ModelManager] Migrating to v38: images synced from folders...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS image_sources (
            id   INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE COLLATE NOCASE
        )
    """)
    cursor.execute("PRAGMA table_info(generations)")
    if "source_id" not in {row[1] for row in cursor.fetchall()}:
        cursor.execute("ALTER TABLE generations ADD COLUMN source_id INTEGER")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS removed_images (
            path     TEXT PRIMARY KEY COLLATE NOCASE,
            size     INTEGER,
            mtime_ns INTEGER
        ) WITHOUT ROWID
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_path ON generation_images(path COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_generations_source ON generations(source_id) "
                   "WHERE source_id IS NOT NULL")
    print("[ModelManager] Migration to v38 complete")


def _migrate_to_v39(cursor):
    """
    Thumbnails of your generations (#5). Nothing is changed or dropped; v39
    only adds image_thumbnails: one row per image a sync or the recorder
    made a thumbnail for - keyed by the image's path, which Force sync and
    the recorder keep where an image's id changes - with the thumbnail's
    full path, NULL when the image needs none (no taller than a thumbnail),
    and the image's size and modified time when it was
    made: a changed image shows its full file until it is made again.
    """
    print("[ModelManager] Migrating to v39: thumbnails of your generations...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS image_thumbnails (
            path      TEXT PRIMARY KEY COLLATE NOCASE,
            thumbnail TEXT,
            size      INTEGER,
            mtime_ns  INTEGER
        ) WITHOUT ROWID
    """)
    print("[ModelManager] Migration to v39 complete")


def _migrate_to_v40(cursor):
    """
    Three indexes, so a delete finds the prompts it leaves unnamed without
    reading every row (#248): every delete now drops a prompt nothing names
    any more, and a prompt is named by four columns and by the prompts it
    heads. An image's prompt and a prompt's head have indexes since v37; an
    image's negative prompt and a generation's two had none, and a prompt
    nothing named was found so only by reading every row - 13 ms a delete,
    36 s for a Remove folder freeing 2,235 prompts, at 76,000 images.
    Nothing else is changed: prompts earlier versions left behind stay.
    """
    print("[ModelManager] Migrating to v40: indexes for the prompts a delete frees...")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_negative ON generation_images(negative_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_generations_prompt ON generations(prompt_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_generations_negative ON generations(negative_id)")
    print("[ModelManager] Migration to v40 complete")


def _back_up(connection, db_path: str, version: int) -> str:
    """
    A copy of the whole database beside it, before migration `version`
    changes what is there - through SQLite's backup API, as v25 did: the
    database is in WAL mode, and a copy of its main file alone can miss what
    was written last. Named for the version too: one run can back up twice
    in a second - a database coming from v36 does, for v37 and for v41 - and
    the second would have written over the first.

    A transaction an earlier migration of the same run left open is committed
    first, or the backup waits on it for ever; each migration tolerates being
    run again, so committing them is safe, and the backup then holds them.
    """
    if connection.in_transaction:
        connection.commit()
    path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_v{version}"
    target = sqlite3.connect(path)
    try:
        connection.backup(target)
    finally:
        target.close()
    print(f"[ModelManager] Backed up the database to {path}")
    return path


# v41's renames: each table of your own images named for them, beside
# Civitai's `images` (#284). The two indexes named after their table go with it.
_V41_TABLES = (
    ("prompts", "generation_prompts"),
    ("image_details", "generation_image_details"),
    ("image_thumbnails", "generation_thumbnails"),
    ("image_sources", "generation_sources"),
    ("removed_images", "generation_images_removed"),
)
_V41_INDEXES = (
    ("idx_prompts_grouped", "idx_generation_prompts_grouped", "generation_prompts", ("grouped_as",)),
    ("idx_prompts_lookup", "idx_generation_prompts_lookup", "generation_prompts", ("id", "grouped_as", "length")),
)


def _migrate_to_v41(cursor, db_path: str):
    """
    Five tables of your generations renamed, so every one says whose it is
    (#284): beside `images`, which holds Civitai's, `prompts`, `image_details`,
    `image_thumbnails`, `image_sources` and `removed_images` read as Civitai's.
    Renamed in place - no row is copied or changed - and the two indexes named
    after `prompts` made again under the new name. Backed up first wherever one
    of them holds a row, as asked for this one; checked before the commit, a
    difference raising so the transaction leaves the database at v40.
    """
    print("[ModelManager] Migrating to v41: the tables of your generations named for them...")
    tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    renames = [(old, new) for old, new in _V41_TABLES if old in tables and new not in tables]
    indexes = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    if not renames and all(new in indexes for _, new, _, _ in _V41_INDEXES):
        print("[ModelManager] Migration to v41 already done")
        return
    counts = {old: cursor.execute(f'SELECT COUNT(*) FROM "{old}"').fetchone()[0] for old, _ in renames}

    connection = cursor.connection
    if connection.in_transaction:
        connection.commit()
    if any(counts.values()):
        _back_up(connection, db_path, 41)

    # One transaction for every step: the caller's commit ends it, a raise
    # rolls it back.
    cursor.execute("BEGIN")
    for old, new in renames:
        cursor.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
    for old, new, table, columns in _V41_INDEXES:
        cursor.execute(f'DROP INDEX IF EXISTS "{old}"')
        cursor.execute(f'CREATE INDEX IF NOT EXISTS "{new}" ON "{table}"({", ".join(columns)})')

    tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for old, new in renames:
        if old in tables or new not in tables:
            raise RuntimeError(f"[ModelManager] v41 did not rename {old} to {new}")
        found = cursor.execute(f'SELECT COUNT(*) FROM "{new}"').fetchone()[0]
        if found != counts[old]:
            raise RuntimeError(f"[ModelManager] v41 would lose data: {new} holds {found} rows, "
                               f"{old} held {counts[old]}")
    for old, new, table, columns in _V41_INDEXES:
        where = {row[0]: row[1] for row in cursor.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type = 'index' AND name IN (?, ?)", (old, new))}
        on = tuple(row[2] for row in cursor.execute(f'PRAGMA index_info("{new}")'))
        if old in where or where.get(new) != table or on != columns:
            raise RuntimeError(f"[ModelManager] v41 did not make {new} on {table}{columns}")
    print("[ModelManager] Migration to v41 complete")


# v42's tables (#283): each Civitai image stored once. `images` narrow, read
# by search and grouping; `image_galleries` which versions show an image,
# where, and its level; `image_records` the record as Civitai sent it, whole;
# `image_resources` and `image_prompts` made from the record, never the source.
_V42_TABLES = """
CREATE TABLE images_v42 (
    id          INTEGER PRIMARY KEY,
    prompt_id   INTEGER,
    negative_id INTEGER,
    width       INTEGER,
    height      INTEGER,
    media_type  TEXT NOT NULL DEFAULT 'image',
    created_at  TEXT
);
CREATE TABLE image_galleries (
    version_id           INTEGER NOT NULL,
    image_id             INTEGER NOT NULL,
    page                 INTEGER NOT NULL,
    position             INTEGER,
    effective_nsfw_level INTEGER,
    PRIMARY KEY (version_id, image_id)
) WITHOUT ROWID;
CREATE TABLE image_records (
    image_id INTEGER PRIMARY KEY,
    url      TEXT,
    data     TEXT NOT NULL
);
CREATE TABLE image_resources (
    image_id     INTEGER NOT NULL,
    position     INTEGER NOT NULL,
    role         TEXT NOT NULL,
    type         TEXT,
    model_id     INTEGER,
    version_id   INTEGER,
    weight       REAL,
    name         TEXT,
    version_name TEXT,
    PRIMARY KEY (image_id, position)
) WITHOUT ROWID;
CREATE TABLE image_prompts (
    id         INTEGER PRIMARY KEY,
    text       TEXT NOT NULL UNIQUE,
    grouped_as INTEGER NOT NULL,
    length     INTEGER NOT NULL DEFAULT 0
)
"""
_V42_INDEXES = """
CREATE INDEX idx_images_prompt ON images(prompt_id);
CREATE INDEX idx_images_negative ON images(negative_id);
CREATE INDEX idx_images_created ON images(created_at);
CREATE INDEX idx_images_size ON images(width, height);
CREATE INDEX idx_image_galleries_order ON image_galleries(version_id, page, position, image_id, effective_nsfw_level);
CREATE INDEX idx_image_galleries_level ON image_galleries(version_id, effective_nsfw_level);
CREATE INDEX idx_image_galleries_image ON image_galleries(image_id, version_id, effective_nsfw_level);
CREATE INDEX idx_image_resources_image ON image_resources(role, image_id, version_id);
CREATE INDEX idx_image_prompts_grouped ON image_prompts(grouped_as);
CREATE INDEX idx_image_prompts_lookup ON image_prompts(id, grouped_as, length)
"""
# Your generations' image indexes, named `idx_images_*` since v37-v40 as if they
# were `images`': renamed for their table first, as #284 named the tables, so
# `idx_images_*` is Civitai's `images`' alone.
_V42_RENAMED_INDEXES = (
    ("idx_images_generation", "idx_generation_images_generation",
     "generation_images(generation_id, position, prompt_nsfw_level, user_nsfw_level)"),
    ("idx_images_prompt", "idx_generation_images_prompt", "generation_images(prompt_id)"),
    ("idx_images_negative", "idx_generation_images_negative", "generation_images(negative_id)"),
    ("idx_images_path", "idx_generation_images_path", "generation_images(path COLLATE NOCASE)"),
)
# Civitai's resource types, as the grouping reads them: frozen, as a migration's
# rules must be. Anything else is `other`.
_V42_ROLES = {"checkpoint": "checkpoint", "lora": "lora", "locon": "lora", "dora": "lora",
              "textualinversion": "embedding", "vae": "vae", "upscaler": "upscaler"}
# A prompt's length, trimmed as a prompt worth reading is (prompt_rules.trimmed_sql), frozen.
_V42_LENGTH = "LENGTH(TRIM(COALESCE(text, ''), char(32) || char(9) || char(13) || char(10)))"


def _v42_resources(record):
    """Each resource the record lists, as image_resources' columns from `position` on."""
    meta = record.get("meta") if isinstance(record, dict) else None
    listed = meta.get("civitaiResources") if isinstance(meta, dict) else None
    rows = []
    for position, entry in enumerate(listed if isinstance(listed, list) else []):
        if isinstance(entry, dict):
            kind = entry.get("type")
            rows.append((position, _V42_ROLES.get(str(kind or "").lower(), "other"), kind, entry.get("modelId"),
                         entry.get("modelVersionId"), entry.get("weight"), entry.get("name"),
                         entry.get("modelVersionName")))
    return rows


def _v42_prompt(record, key):
    meta = record.get("meta") if isinstance(record, dict) else None
    text = meta.get(key) if isinstance(meta, dict) else None
    return text if isinstance(text, str) else None


# What v42 expects of the tables it made, read from each record as it was
# written - by Python, as the extension reads records everywhere - into tables
# of the new ones' column types, so a value stored with a conversion (a weight
# sent as "0.8") compares as stored.
_V42_EXPECTED = """
CREATE TEMP TABLE v42_prompts (image_id INTEGER, prompt TEXT, negative TEXT);
CREATE TEMP TABLE v42_resources (image_id INTEGER, position INTEGER, role TEXT, type TEXT, model_id INTEGER,
                                 version_id INTEGER, weight REAL, name TEXT, version_name TEXT)
"""
_V42_RESOURCE_COLUMNS = "image_id, position, role, type, model_id, version_id, weight, name, version_name"


def _v42_check(cursor, merged):
    """
    The new tables against the old one before it is dropped: every row's
    gallery facts, value and type; each image's address, size and date its
    newest copy's - Civitai can date an image again between two galleries'
    fetches (10 of one library's images), and the newest copy wins, as for
    the record (#283); the record byte for byte where nothing was carried
    over; each image's prompts and resources as its record lists them
    (_V42_EXPECTED). Each read goes through the old table once, by an index
    or a group: a check that asked each row about its image's other copies
    read the whole table again per row, 127,000 times (#283). Raises on any
    difference.
    """
    def same(old, new):
        return f"({old} IS {new} AND typeof({old}) = typeof({new}))"

    def none(label, sql, args=()):
        found = cursor.execute(sql, args).fetchone()[0]
        if found:
            raise RuntimeError(f"[ModelManager] v42 would lose data: {found} {label}")

    old_rows, gallery_rows = (cursor.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                              for t in ("images", "image_galleries"))
    if old_rows != gallery_rows:
        raise RuntimeError(f"[ModelManager] v42 would lose data: {gallery_rows} gallery rows for {old_rows} images rows")
    none("rows whose gallery, page, place or level did not come through",
         "SELECT COUNT(*) FROM images o WHERE NOT EXISTS (SELECT 1 FROM image_galleries g "
         "WHERE g.version_id = o.version_id AND g.image_id = o.id AND "
         f"{same('o.page', 'g.page')} AND {same('o.position', 'g.position')} AND "
         f"{same('o.effective_nsfw_level', 'g.effective_nsfw_level')})")
    newest = "SELECT * FROM images WHERE rowid IN (SELECT MAX(rowid) FROM images GROUP BY id)"
    none("images whose address, size or date is not their newest copy's",
         f"SELECT COUNT(*) FROM ({newest}) o LEFT JOIN images_v42 n ON n.id = o.id "
         "LEFT JOIN image_records r ON r.image_id = o.id WHERE n.id IS NULL OR r.image_id IS NULL OR NOT ("
         f"{same('o.url', 'r.url')} AND {same('o.width', 'n.width')} AND {same('o.height', 'n.height')} "
         f"AND {same('o.created_at', 'n.created_at')})")
    distinct = cursor.execute("SELECT COUNT(DISTINCT id) FROM images").fetchone()[0]
    for table in ("images_v42", "image_records"):
        count = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count != distinct:
            raise RuntimeError(f"[ModelManager] v42 would lose data: {table} holds {count} images of {distinct}")
    changed = cursor.execute(f"SELECT COUNT(*) FROM ({newest}) o JOIN image_records r ON r.image_id = o.id "
                             "WHERE r.data IS NOT o.data").fetchone()[0]
    if changed != len(merged):
        raise RuntimeError(f"[ModelManager] v42 changed {changed} records, carrying data over into {len(merged)}")
    prompts = ("SELECT n.id, p.text, q.text FROM images_v42 n LEFT JOIN image_prompts p ON p.id = n.prompt_id "
               "LEFT JOIN image_prompts q ON q.id = n.negative_id")
    expected = "SELECT image_id, prompt, negative FROM temp.v42_prompts"
    none("images whose prompts are not their record's", f"SELECT COUNT(*) FROM ({prompts} EXCEPT {expected})")
    none("records whose prompts no image holds", f"SELECT COUNT(*) FROM ({expected} EXCEPT {prompts})")
    stored = f"SELECT {_V42_RESOURCE_COLUMNS} FROM image_resources"
    expected = f"SELECT {_V42_RESOURCE_COLUMNS} FROM temp.v42_resources"
    none("resources a record lists and image_resources lacks", f"SELECT COUNT(*) FROM ({expected} EXCEPT {stored})")
    none("resources image_resources holds that no record lists", f"SELECT COUNT(*) FROM ({stored} EXCEPT {expected})")


def _v42_room(db_path: str) -> None:
    """
    Room for v42 beside the database: its backup, a copy of the whole file,
    and the new tables, written before the old one goes - about twice the
    database. Refused before anything is written, saying what it needs: a
    full disk failed mid-way, with only SQLite's own words.
    """
    if not os.path.isfile(db_path):
        return
    size = sum(os.path.getsize(p) for p in (db_path, db_path + "-wal") if os.path.isfile(p))
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(db_path))).free
    if free < 2 * size:
        raise RuntimeError(
            f"[ModelManager] Updating the database (v42) needs about {2 * size / 1e9:.1f} GB free beside it - "
            f"a backup of it and its new tables - and {free / 1e9:.1f} GB is free. The database is unchanged: "
            "free some space and start the WebUI again.")


def _migrate_to_v42(cursor, db_path: str):
    """
    Each Civitai image stored once (#283), in the tables search and grouping
    read. `images` held a row per gallery an image showed in, each with the
    whole record; 7,742 of one library's 117,142 images had several. The
    newest copy - the highest row number, each write having replaced its row -
    becomes the image's record, with the generation data an older copy had
    where the newest has no prompt, as a sync carries it over
    (keep_generation_data). Its prompts and resources are copied out of it.
    Backed up first, built beside the old table in one transaction, and
    checked (_v42_check) before the old table is dropped.
    """
    print("[ModelManager] Migrating to v42: each Civitai image stored once...")
    tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "image_records" in tables:
        print("[ModelManager] Migration to v42 already done")
        return
    connection = cursor.connection
    if connection.in_transaction:
        connection.commit()
    if cursor.execute("SELECT EXISTS (SELECT 1 FROM images)").fetchone()[0]:
        _v42_room(db_path)
        _back_up(connection, db_path, 42)
    total = cursor.execute("SELECT COUNT(DISTINCT id) FROM images").fetchone()[0]

    # One transaction for every step: the caller's commit ends it, a raise
    # rolls it back.
    cursor.execute("BEGIN")
    for statement in (_V42_TABLES + ";" + _V42_EXPECTED).split(";"):
        if statement.strip():
            cursor.execute(statement)
    cursor.execute("INSERT INTO image_galleries (version_id, image_id, page, position, effective_nsfw_level) "
                   "SELECT version_id, id, page, position, effective_nsfw_level FROM images")

    prompt_ids = {}

    def prompt_id(text):
        if text is None:
            return None
        if text not in prompt_ids:
            tidied = " ".join(text.split())
            grouped = 0 if tidied == "" else None if tidied == text else prompt_id(tidied)
            new_id = len(prompt_ids) + 1
            prompt_ids[text] = new_id
            cursor.execute("INSERT INTO image_prompts (id, text, grouped_as) VALUES (?, ?, ?)",
                           (new_id, text, new_id if grouped is None else grouped))
        return prompt_ids[text]

    merged = set()
    reader = connection.cursor()
    copies = []
    done = [0]

    def write(copies):
        newest = copies[0]
        image_id, url, width, height, created_at, data = newest
        try:
            record = json.loads(data)
        except (TypeError, ValueError):
            record = None
        if isinstance(record, dict):
            meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
            if not meta.get("prompt"):
                for older in copies[1:]:
                    try:
                        old = json.loads(older[5]).get("meta")
                    except (TypeError, ValueError, AttributeError):
                        old = None
                    if isinstance(old, dict) and old.get("prompt"):
                        carried = dict(old)
                        carried.update({k: v for k, v in meta.items() if v is not None})
                        record["meta"] = carried
                        data = json.dumps(record)
                        merged.add(image_id)
                        break
        cursor.execute("INSERT INTO images_v42 (id, prompt_id, negative_id, width, height, media_type, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (image_id, prompt_id(_v42_prompt(record, "prompt")),
                        prompt_id(_v42_prompt(record, "negativePrompt")), width, height,
                        record.get("type") if isinstance(record, dict) and isinstance(record.get("type"), str)
                        else "image", created_at))
        cursor.execute("INSERT INTO image_records (image_id, url, data) VALUES (?, ?, ?)", (image_id, url, data))
        resources = [(image_id,) + row for row in _v42_resources(record)]
        cursor.executemany("INSERT INTO image_resources (image_id, position, role, type, model_id, version_id, "
                           "weight, name, version_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", resources)
        # What the check will expect, read from the record as it was written.
        cursor.execute("INSERT INTO temp.v42_prompts VALUES (?, ?, ?)",
                       (image_id, _v42_prompt(record, "prompt"), _v42_prompt(record, "negativePrompt")))
        cursor.executemany(f"INSERT INTO temp.v42_resources ({_V42_RESOURCE_COLUMNS}) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", resources)
        done[0] += 1
        # A large library takes a while: said as it goes, so a WebUI that looks
        # stuck is not stopped for it (stopped, it starts over, nothing lost).
        if done[0] % 20000 == 0:
            print(f"[ModelManager] v42: {done[0]:,} of {total:,} images...")

    for row in reader.execute("SELECT id, url, width, height, created_at, data FROM images ORDER BY id, rowid DESC"):
        if copies and copies[0][0] != row[0]:
            write(copies)
            copies = []
        copies.append(tuple(row))
    if copies:
        write(copies)
    reader.close()
    cursor.execute(f"UPDATE image_prompts SET length = {_V42_LENGTH}")

    print(f"[ModelManager] v42: {done[0]:,} images written; checking them against the old table...")
    _v42_check(cursor, merged)
    cursor.execute("DROP TABLE temp.v42_prompts")
    cursor.execute("DROP TABLE temp.v42_resources")
    cursor.execute("DROP TABLE images")
    cursor.execute("ALTER TABLE images_v42 RENAME TO images")
    for old, new, on in _V42_RENAMED_INDEXES:
        cursor.execute(f"DROP INDEX IF EXISTS {old}")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS {new} ON {on}")
    for statement in _V42_INDEXES.split(";"):
        if statement.strip():
            cursor.execute(statement)
    print(f"[ModelManager] Migration to v42 complete: "
          f"{cursor.execute('SELECT COUNT(*) FROM images').fetchone()[0]} images, "
          f"{len(merged)} given an older copy's generation data")


def run_migrations(cursor, from_version: int, to_version: int,
                   db_path: str, db_dir: str):
    """Bring a database from `from_version` up to `to_version`, and no further."""
    print(f"[ModelManager] Migrating database from v{from_version} to v{to_version}...")

    # Only v4, v25, v32, v37, v41 and v42 take the path; v4 the directory too.
    # Each makes a backup first.
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
        33: _migrate_to_v33, 34: _migrate_to_v34, 35: _migrate_to_v35, 36: _migrate_to_v36,
        37: lambda c: _migrate_to_v37(c, db_path),
        38: _migrate_to_v38, 39: _migrate_to_v39, 40: _migrate_to_v40,
        41: lambda c: _migrate_to_v41(c, db_path),
        42: lambda c: _migrate_to_v42(c, db_path),
    }
    for version in sorted(steps):
        if from_version < version <= to_version:
            steps[version](cursor)

    cursor.execute(
        "INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', ?)",
        (str(to_version),)
    )
    print("[ModelManager] Database migration complete.")
