"""
Migration v46 (#262): when Civitai answered 404 for a model, kept on its row
(`models.civitai_gone_at`), so a metadata sync does not ask about a deleted
model again at every run - nothing else.

A library of every kind, brought to v45 with models in it, is migrated. The
column is there, empty on every row; every other table, index, column and row
is as it was. Run again, it changes nothing. A new database is made with it.
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
from model_manager.db import migrations                  # noqa: E402
from model_manager.db.database import ModelsDatabase, SCHEMA_VERSION  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'migration_v46')
COLUMN = 'civitai_gone_at'

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def columns(connection, table):
    return [c[1] for c in connection.execute(f'PRAGMA table_info("{table}")')]


def everything(connection):
    """Every row of every table, as stored, in a fixed order - but the schema's
    version, and the models' rows without the column v46 adds."""
    tables = [r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    rows = {}
    for table in tables:
        kept = ', '.join(f'"{c}"' for c in columns(connection, table) if not (table == 'models' and c == COLUMN))
        rows[table] = sorted((tuple(r) for r in connection.execute(f'SELECT {kept} FROM "{table}"')), key=repr)
    rows['schema_info'] = [r for r in rows.get('schema_info', []) if r[0] != 'version']
    return rows


def schema(connection):
    """Every table's and index's SQL, by name, but the models table's."""
    return {name: sql for name, sql in connection.execute("SELECT name, sql FROM sqlite_master")
            if name != 'models'}


def version(connection):
    row = connection.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()
    return row[0] if row else None


def v45_library(directory):
    """A library of every kind at v45, with models in it."""
    path, connection = generation_fixture.v36_database(directory)
    generation_fixture.varied(connection, directory)
    cursor = connection.cursor()
    migrations.run_migrations(cursor, 36, 45, path, directory)
    connection.commit()
    for model_id, name, synced in ((1, 'Known', '2026-10-16T12:00:00'), (2, 'Filed from a sidecar', None),
                                   (3, 'Left out of the batch', '2026-10-04T21:00:00')):
        cursor.execute("INSERT OR REPLACE INTO models (id, name, type, nsfw_level, civitai_synced_at) "
                       "VALUES (?, ?, 'LORA', 1, ?)", (model_id, name, synced))
    connection.commit()
    return path, connection


# ------------------------------------------------------------ the migration
check('v46 is a schema this copy has passed', SCHEMA_VERSION >= 46)
path, connection = v45_library(os.path.join(WORK, 'library'))
before, shape, model_columns = everything(connection), schema(connection), columns(connection, 'models')
check('the library holds models', len(before['models']) >= 3)
check('and no such column yet', COLUMN in model_columns, False)
cursor = connection.cursor()
try:
    migrations.run_migrations(cursor, 45, 46, path, os.path.dirname(path))
    connection.commit()
    raised = None
except Exception as error:
    connection.rollback()
    raised = f'{type(error).__name__}: {error}'
check('the migration runs without raising', raised, None)
check('the column is added to the models, last', columns(connection, 'models'), model_columns + [COLUMN])
check('empty on every row: no model is known gone yet',
      connection.execute(f'SELECT COUNT(*) FROM models WHERE "{COLUMN}" IS NOT NULL').fetchone()[0]
      if COLUMN in columns(connection, 'models') else 'no column', 0)
check('every row of every table as it was', [t for t in sorted(set(before) | set(everything(connection)))
                                              if before.get(t) != everything(connection).get(t)], [])
check('every other table and index as it was', schema(connection), shape)
check('the version is 46', version(connection), '46')

shape_after, rows_after = (schema(connection), columns(connection, 'models')), everything(connection)
try:
    migrations.run_migrations(cursor, 45, 46, path, os.path.dirname(path))
    connection.commit()
except Exception as error:
    connection.rollback()
    check('run twice, it does not raise', str(error), None)
check('run twice, it changes nothing',
      ((schema(connection), columns(connection, 'models')), everything(connection)), (shape_after, rows_after))
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
check('a new database is made at this version, with the column',
      (version(raw), COLUMN in columns(raw, 'models')), (str(SCHEMA_VERSION), True))
raw.close()

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
