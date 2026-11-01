"""
Migration v47 (#374): a kept download is one file - `downloads` keyed by
(install, file_id), not (install, version_id) - and nothing else.

A library of every kind, brought to v46 with models and kept downloads in it,
is migrated. Every kept row comes over, in its order, under its file: one
with no file id takes its version's primary from the model's stored list,
else its version id negated - a stand-in the queue names at its turn. Two
files of one version can then be kept apart. Every other table, index and row
is as it was. Run again, it changes nothing. A new database is made with it.
"""
import json
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

WORK = os.path.join(TESTS, 'work', 'migration_v47')
COLUMNS = ('install', 'version_id', 'position', 'model_id', 'file_id', 'file_index', 'file_name',
           'partial_path', 'total_bytes')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def everything(connection):
    """Every row of every table, as stored, in a fixed order - but the schema's version and the kept downloads."""
    tables = [r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    rows = {table: sorted((tuple(r) for r in connection.execute(f'SELECT * FROM "{table}"')), key=repr)
            for table in tables if table != 'downloads'}
    rows['schema_info'] = [r for r in rows.get('schema_info', []) if r[0] != 'version']
    return rows


def schema(connection):
    """Every table's and index's SQL, by name, but the downloads table's."""
    return {name: sql for name, sql in connection.execute("SELECT name, sql FROM sqlite_master")
            if name != 'downloads' and not name.startswith('sqlite_autoindex_downloads')}


def kept(connection):
    return [dict(zip(COLUMNS, r)) for r in connection.execute(
        f"SELECT {', '.join(COLUMNS)} FROM downloads ORDER BY install, position")]


def version(connection):
    row = connection.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()
    return row[0] if row else None


def row(install, position, version_id, file_id, model_id=42, partial=None):
    return {'install': install, 'version_id': version_id, 'position': position, 'model_id': model_id,
            'file_id': file_id, 'file_index': None, 'file_name': 'f_%d.safetensors' % version_id,
            'partial_path': partial, 'total_bytes': 100}


STORED = [{'id': 501, 'files': [{'id': 5011, 'name': 'full.safetensors'},
                                {'id': 5012, 'name': 'pruned.safetensors', 'primary': True}]},
          {'id': 502, 'files': [{'id': 5021, 'name': 'only.safetensors'}]}]
OLD_ROWS = [row('here', 0, 501, None, partial='C:\\m\\f_501.safetensors.partial'),
            row('here', 1, 502, None),
            row('here', 2, 503, None),                      # its model's list does not name it
            row('here', 3, 504, None, model_id=None),        # no model to look in
            row('here', 4, 505, 5051),
            row('other', 0, 506, 5061),
            row('other', 1, 507, 5061)]                     # one shared file, from two versions
NEW_ROWS = [dict(OLD_ROWS[0], file_id=5012), dict(OLD_ROWS[1], file_id=5021), dict(OLD_ROWS[2], file_id=-503),
            dict(OLD_ROWS[3], file_id=-504), OLD_ROWS[4], OLD_ROWS[5]]


def v46_library(directory):
    """A library of every kind at v46, with models and kept downloads in it."""
    path, connection = generation_fixture.v36_database(directory)
    generation_fixture.varied(connection, directory)
    cursor = connection.cursor()
    migrations.run_migrations(cursor, 36, 46, path, directory)
    connection.commit()
    cursor.execute("INSERT OR REPLACE INTO models (id, name, type, nsfw_level, versions) "
                   "VALUES (42, 'Two files', 'Checkpoint', 1, ?)", (json.dumps(STORED),))
    cursor.execute("DELETE FROM downloads")
    cursor.executemany(f"INSERT INTO downloads ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                       [tuple(r[c] for c in COLUMNS) for r in OLD_ROWS])
    connection.commit()
    return path, connection


# ------------------------------------------------------------ the migration
check('v47 is a schema this copy has passed', SCHEMA_VERSION >= 47)
path, connection = v46_library(os.path.join(WORK, 'library'))
before, shape = everything(connection), schema(connection)
check('the library keeps downloads, some with no file id', [r['file_id'] for r in kept(connection)],
      [None, None, None, None, 5051, 5061, 5061])
cursor = connection.cursor()
try:
    migrations.run_migrations(cursor, 46, 47, path, os.path.dirname(path))
    connection.commit()
    raised = None
except Exception as error:
    connection.rollback()
    raised = f'{type(error).__name__}: {error}'
check('the migration runs without raising', raised, None)
check('every row comes over in its order, under its file: the stored primary, or a stand-in where no list names it',
      kept(connection), NEW_ROWS)
check('a second row of one file under one install is the same download: the first stays',
      [r['version_id'] for r in kept(connection) if r['install'] == 'other'], [506])
check('keyed by install and file', [r[1] for r in sorted(
    (r for r in connection.execute("PRAGMA table_info(downloads)") if r[5]), key=lambda r: r[5])],
    ['install', 'file_id'])
try:
    connection.execute(f"INSERT INTO downloads ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                       tuple(dict(OLD_ROWS[4], position=5, file_id=5052)[c] for c in COLUMNS))
    second_file = 'kept'
except sqlite3.IntegrityError as error:
    second_file = str(error)
connection.rollback()
check('a second file of a version already kept can be kept beside it', second_file, 'kept')
try:
    connection.execute(f"INSERT INTO downloads ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                       tuple(dict(OLD_ROWS[4], position=6, version_id=599)[c] for c in COLUMNS))
    same_file = 'kept'
except sqlite3.IntegrityError:
    same_file = 'refused'
connection.rollback()
check('one file kept twice is refused', same_file, 'refused')
check('every row of every other table as it was', [t for t in sorted(set(before) | set(everything(connection)))
                                                    if before.get(t) != everything(connection).get(t)], [])
check('every other table and index as it was', schema(connection), shape)
check('no table left over', [r[0] for r in connection.execute(
    "SELECT name FROM sqlite_master WHERE name LIKE 'downloads_%'")], [])
check('the version is 47', version(connection), '47')

shape_after, rows_after = (schema(connection), kept(connection)), everything(connection)
try:
    migrations.run_migrations(cursor, 46, 47, path, os.path.dirname(path))
    connection.commit()
except Exception as error:
    connection.rollback()
    check('run twice, it does not raise', str(error), None)
check('run twice, it changes nothing', ((schema(connection), kept(connection)), everything(connection)),
      (shape_after, rows_after))
connection.close()

# ------------------------------------------------------------ a new database
NEW = os.path.join(WORK, 'new')
os.makedirs(NEW, exist_ok=True)
for name in os.listdir(NEW):
    os.remove(os.path.join(NEW, name))
try:
    ModelsDatabase(extension_dir=ROOT, custom_db_path=os.path.join(NEW, 'models.db')).close()
    raised = None
except Exception as error:
    raised = f'{type(error).__name__}: {error}'
check('a new database is made without raising', raised, None)
raw = sqlite3.connect(os.path.join(NEW, 'models.db'))
check('a new database is made at this version, keyed by install and file',
      (version(raw), [r[1] for r in sorted((r for r in raw.execute("PRAGMA table_info(downloads)") if r[5]),
                                           key=lambda r: r[5])]),
      (str(SCHEMA_VERSION), ['install', 'file_id']))
raw.close()

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
