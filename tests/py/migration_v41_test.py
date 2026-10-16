"""
Migration v41 (#284): five tables of your generations named for them, and
the two indexes named after `prompts` with them - a rename, nothing else.

A library of every kind, brought to v40 with a row in each of the five
tables, is migrated. Each table comes out under its new name holding the
rows it held, every other table is as it was, the indexes are there on the
same columns, and a backup of the v40 database is beside it. Run again, it
changes nothing and backs up nothing. A new database is made at v41 with no
backup left behind. A rename that loses a row, and an index made on other
columns, each raise, and the transaction leaves the database at v40.
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

WORK = os.path.join(TESTS, 'work', 'migration_v41')

RENAMED = {'prompts': 'generation_prompts', 'image_details': 'generation_image_details',
           'image_thumbnails': 'generation_thumbnails', 'image_sources': 'generation_sources',
           'removed_images': 'generation_images_removed'}
INDEXES = {'idx_generation_prompts_grouped': ['grouped_as'],
           'idx_generation_prompts_lookup': ['id', 'grouped_as', 'length']}

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def everything(connection, names=None):
    """Every row of every table, as stored, in a fixed order - under the names
    `names` maps them to, so a renamed table compares with its old self."""
    names = names or {}
    tables = [r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    rows = {names.get(t, t): sorted((tuple(r) for r in connection.execute(f'SELECT * FROM "{t}"')), key=repr)
            for t in tables}
    # Which version the database is at is the one row a migration has to change.
    rows['schema_info'] = [r for r in rows.get('schema_info', []) if r[0] != 'version']
    return rows


def names(connection, kind):
    return {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))}


def index_columns(connection, name):
    return [c[2] for c in connection.execute(f'PRAGMA index_info("{name}")')]


def backups(directory):
    return sorted(n for n in os.listdir(directory) if '.backup_' in n)


def version(connection):
    row = connection.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()
    return row[0] if row else None


def v40_library(directory):
    """A library of every kind at v40, a row in each of the five tables."""
    path, connection = generation_fixture.v36_database(directory)
    generation_fixture.varied(connection, directory)
    cursor = connection.cursor()
    migrations.run_migrations(cursor, 36, 40, path, directory)
    connection.commit()
    cursor.execute("INSERT INTO image_sources (path) VALUES ('C:\\outputs\\added')")
    cursor.execute("INSERT INTO removed_images (path, size, mtime_ns) VALUES ('C:\\outputs\\gone.png', 10, 20)")
    cursor.execute("INSERT INTO image_thumbnails (path, thumbnail, size, mtime_ns) "
                   "VALUES ('C:\\outputs\\a.png', 'C:\\thumbs\\a.webp', 30, 40)")
    connection.commit()
    return path, connection


# ------------------------------------------------------------ the migration
check('v41 is the schema this copy writes', SCHEMA_VERSION, 41)
path, connection = v40_library(os.path.join(WORK, 'library'))
before = everything(connection)
check('the library holds a row in each of the five tables',
      {t: len(before[t]) > 0 for t in RENAMED}, {t: True for t in RENAMED})
# The v37 step of the fixture backs it up too: only v41's are counted.
earlier = backups(os.path.dirname(path))
check('no backup for v41 before the migration', [n for n in earlier if n.endswith('_v41')], [])

cursor = connection.cursor()
# A raise is a failure of its own, so the checks below still say what is wrong.
try:
    migrations.run_migrations(cursor, 40, 41, path, os.path.dirname(path))
    connection.commit()
    raised = None
except RuntimeError as error:
    connection.rollback()
    raised = str(error)
check('the migration runs without raising', raised, None)
tables = names(connection, 'table')
check('each table under its new name', {new: new in tables for new in RENAMED.values()},
      {new: True for new in RENAMED.values()})
check('no table left under its old name', sorted(set(RENAMED) & tables), [])
after = everything(connection, {new: old for old, new in RENAMED.items()})
check('every row of every table as it was, the renamed ones under their new names',
      [t for t in sorted(set(before) | set(after)) if before.get(t) != after.get(t)], [])
check('the prompt indexes under their new names, on the same columns',
      {name: index_columns(connection, name) for name in INDEXES}, INDEXES)
check('the old prompt indexes are gone', sorted({'idx_prompts_grouped', 'idx_prompts_lookup'}
                                                & names(connection, 'index')), [])
try:
    named = connection.execute("SELECT COUNT(*) FROM generation_prompts INDEXED BY idx_generation_prompts_lookup "
                               "WHERE id > 0").fetchone()[0]
except sqlite3.Error as error:
    named = str(error)
check('an index on the new table answers a query that names it', named, len(before['prompts']))

made = [n for n in backups(os.path.dirname(path)) if n not in earlier]
check('one backup beside the database, named for v41', [n.endswith('_v41') for n in made], [True])
if made:
    saved = sqlite3.connect(os.path.join(os.path.dirname(path), made[0]))
    check('the backup is the v40 database: its version, its names, its rows',
          (version(saved), everything(saved) == before), ('40', True))
    saved.close()

try:
    migrations.run_migrations(cursor, 40, 41, path, os.path.dirname(path))
    connection.commit()
except RuntimeError as error:
    connection.rollback()
    check('run twice, it does not raise', str(error), None)
check('run twice, it changes nothing', everything(connection, {new: old for old, new in RENAMED.items()}), after)
check('and backs up nothing more', backups(os.path.dirname(path)), sorted(earlier + made))
connection.close()

# ------------------------------------------------------------ a new database
NEW = os.path.join(WORK, 'new')
os.makedirs(NEW, exist_ok=True)
for name in os.listdir(NEW):
    os.remove(os.path.join(NEW, name))
try:
    ModelsDatabase(extension_dir=ROOT, custom_db_path=os.path.join(NEW, 'models.db'))
    raised = None
except RuntimeError as error:
    raised = str(error)
check('a new database is made without raising', raised, None)
raw = sqlite3.connect(os.path.join(NEW, 'models.db'))
check('a new database is made at v41, under the new names',
      (version(raw), set(RENAMED.values()) <= names(raw, 'table'), sorted(set(RENAMED) & names(raw, 'table'))),
      (str(SCHEMA_VERSION), True, []))
# v4 backs up a new database too, as it always has: only v41's are counted.
check('with nothing to lose, v41 backs up nothing', [n for n in backups(NEW) if n.endswith('_v41')], [])
raw.close()


# ------------------------------------------------------------ breaks
class Breaking:
    """A cursor that does one thing wrong after a statement it is told of."""

    def __init__(self, cursor, after, then):
        self._cursor, self._after, self._then = cursor, after, then
        self.connection = cursor.connection

    def execute(self, sql, *args):
        if self._after in sql and self._then:
            if self._then.startswith('CREATE INDEX'):
                sql, self._then = self._then, None
                return self._cursor.execute(sql)
            result = self._cursor.execute(sql, *args)
            self._cursor.execute(self._then)
            self._then = None
            return result
        return self._cursor.execute(sql, *args)


def broken(label, after, then):
    """Migrate a fresh v40 library through a cursor that breaks; it must raise and leave v40."""
    path, connection = v40_library(os.path.join(WORK, label))
    before = everything(connection)
    raised = None
    try:
        migrations._migrate_to_v41(Breaking(connection.cursor(), after, then), path)
    except RuntimeError as error:
        raised = str(error)
    connection.rollback()
    check(f'{label}: it raises', raised is not None)
    check(f'{label}: the database is still at v40, its tables and rows as they were',
          (version(connection), everything(connection) == before, sorted(set(RENAMED) - names(connection, 'table'))),
          ('40', True, []))
    connection.close()


broken('a row lost', 'RENAME TO "generation_sources"', 'DELETE FROM generation_sources')
broken('an index on other columns', 'idx_generation_prompts_lookup',
       'CREATE INDEX "idx_generation_prompts_lookup" ON "generation_prompts"(id, grouped_as)')

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
