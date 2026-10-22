"""
Migration v45 (#336): two indexes on Civitai's images' resources, by version
and by model, for the search's version: and model: keys - nothing else.

A library of every kind, brought to v44 with Civitai images and their
resources, is migrated. The two indexes are there on their columns, every
other table, index and row is as it was, and the search's own conditions are
answered through them. Run again, it changes nothing. A new database is made
with them.
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

import generation_fixture                                # noqa: E402
from model_manager.db import gallery_ops, migrations     # noqa: E402
from model_manager.db.database import ModelsDatabase, SCHEMA_VERSION  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'migration_v45')
INDEXES = {'idx_image_resources_version': ['version_id', 'image_id'],
           'idx_image_resources_model': ['model_id', 'image_id']}

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def everything(connection):
    """Every row of every table, as stored, in a fixed order, but the schema's version."""
    tables = [r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    rows = {t: sorted((tuple(r) for r in connection.execute(f'SELECT * FROM "{t}"')), key=repr) for t in tables}
    rows['schema_info'] = [r for r in rows.get('schema_info', []) if r[0] != 'version']
    return rows


def schema(connection):
    """Every table's and index's SQL, by name, but the two v45 adds."""
    return {name: sql for name, sql in connection.execute("SELECT name, sql FROM sqlite_master")
            if name not in INDEXES}


def index_columns(connection, name):
    return [c[2] for c in connection.execute(f'PRAGMA index_info("{name}")')]


def version(connection):
    row = connection.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()
    return row[0] if row else None


def plan(connection, condition, values):
    """How SQLite answers one of the search's conditions on Civitai's images."""
    try:
        return ' | '.join(r[3] for r in connection.execute(
            f'EXPLAIN QUERY PLAN SELECT p.id FROM images p WHERE {condition}', values))
    except sqlite3.Error as error:
        return str(error)


def v44_library(directory):
    """A library of every kind at v44, with Civitai images and their resources."""
    path, connection = generation_fixture.v36_database(directory)
    generation_fixture.varied(connection, directory)
    cursor = connection.cursor()
    migrations.run_migrations(cursor, 36, 44, path, directory)
    connection.commit()
    for image_id in range(1, 41):
        cursor.execute("INSERT INTO images (id, width, height) VALUES (?, 512, 768)", (image_id,))
        cursor.execute("INSERT INTO image_galleries (version_id, image_id, page, position, effective_nsfw_level) "
                       "VALUES (?, ?, 1, ?, 1)", (1 + image_id % 3, image_id, image_id))
        for position, version_id in enumerate((100 + image_id % 5, 200 + image_id % 7)):
            cursor.execute("INSERT INTO image_resources (image_id, position, role, type, model_id, version_id, "
                           "weight, name, version_name) VALUES (?, ?, 'lora', 'LORA', ?, ?, 0.8, 'a LoRA', 'v1')",
                           (image_id, position, version_id // 10, version_id))
    connection.commit()
    return path, connection


# ------------------------------------------------------------ the migration
check('v45 is a schema this copy has passed', SCHEMA_VERSION >= 45)
path, connection = v44_library(os.path.join(WORK, 'library'))
before, shape = everything(connection), schema(connection)
check('the library holds Civitai images with resources', len(before['image_resources']), 80)
cursor = connection.cursor()
try:
    migrations.run_migrations(cursor, 44, 45, path, os.path.dirname(path))
    connection.commit()
    raised = None
except Exception as error:
    connection.rollback()
    raised = f'{type(error).__name__}: {error}'
check('the migration runs without raising', raised, None)
check('the two indexes, on their columns', {name: index_columns(connection, name) for name in INDEXES}, INDEXES)
check('every row of every table as it was', [t for t in sorted(set(before) | set(everything(connection)))
                                              if before.get(t) != everything(connection).get(t)], [])
check('every other table and index as it was', schema(connection), shape)
check('the version is 45', version(connection), '45')
by_versions = getattr(gallery_ops, '_BY_VERSIONS', 'p.id IN (SELECT image_id FROM image_resources '
                      'WHERE version_id IN (SELECT value FROM json_each(:versions)))')
by_models = getattr(gallery_ops, '_BY_MODELS', 'p.id IN (SELECT image_id FROM image_resources '
                    'WHERE model_id IN (SELECT value FROM json_each(:models)))')
check("the search's version: is answered through its index",
      'idx_image_resources_version' in plan(connection, by_versions, {'versions': '[101, 203]'}), True)
check("the search's model: is answered through its index",
      'idx_image_resources_model' in plan(connection, by_models, {'models': '[10, 20]'}), True)

shape_after, rows_after = schema(connection), everything(connection)
try:
    migrations.run_migrations(cursor, 44, 45, path, os.path.dirname(path))
    connection.commit()
except Exception as error:
    connection.rollback()
    check('run twice, it does not raise', str(error), None)
check('run twice, it changes nothing', (schema(connection), everything(connection), len(
    [n for n in connection.execute("SELECT name FROM sqlite_master WHERE name IN (?, ?)", tuple(INDEXES))])),
      (shape_after, rows_after, 2))
connection.close()

# ------------------------------------------------------------ a new database
NEW = os.path.join(WORK, 'new')
os.makedirs(NEW, exist_ok=True)
for name in os.listdir(NEW):
    os.remove(os.path.join(NEW, name))
try:
    ModelsDatabase(extension_dir=ROOT, custom_db_path=os.path.join(NEW, 'models.db'))
    raised = None
except Exception as error:
    raised = f'{type(error).__name__}: {error}'
check('a new database is made without raising', raised, None)
raw = sqlite3.connect(os.path.join(NEW, 'models.db'))
check('a new database is made at this version, with the two indexes',
      (version(raw), {name: index_columns(raw, name) for name in INDEXES}), (str(SCHEMA_VERSION), INDEXES))
raw.close()

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
