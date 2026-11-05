"""
Migration v49 (#400): a task's checkpoints in a table of their own -
`task_checkpoints`, a row per checkpoint - and `tasks` without its
`checkpoint` and `modules` columns.

A library of every kind, brought to v48 with tasks in it, is migrated. Every
task comes out as one row, at place 0, its checkpoint and modules equal to
the old columns, value and type alike: a task saved with no checkpoint, and
a `modules` of NULL beside one of '[]', included. The database is backed up
first. Every other table, index and row is as it was. A row that comes out
different raises inside the migration, and leaves the database at v48 - a
trigger that rewrites a NULL `modules` as '[]' is the break. Run again, it
changes nothing. A new database is made with it.
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

WORK = os.path.join(TESTS, 'work', 'migration_v49')
MOVED = ('checkpoint', 'modules')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def columns(connection, table):
    return [r[1] for r in connection.execute(f'PRAGMA table_info("{table}")')]


def everything(connection):
    """
    Every row of every table, as stored, in a fixed order - `tasks` without
    the two columns v49 moves, and neither the schema's version nor the new
    table.
    """
    tables = [r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND name != 'task_checkpoints' ORDER BY name")]
    rows = {}
    for table in tables:
        kept = [c for c in columns(connection, table) if not (table == 'tasks' and c in MOVED)]
        rows[table] = sorted((tuple(r) for r in connection.execute(
            f'SELECT {", ".join(chr(34) + c + chr(34) for c in kept)} FROM "{table}"')), key=repr)
    rows['schema_info'] = [r for r in rows.get('schema_info', []) if r[0] != 'version']
    return rows


def schema(connection):
    """Every table's and index's SQL, by name, but `tasks`' and the new table's."""
    return {name: sql for name, sql in connection.execute("SELECT name, sql FROM sqlite_master")
            if name not in ('tasks', 'task_checkpoints') and not name.startswith('sqlite_autoindex_task_checkpoints')}


def old_checkpoints(connection):
    """Each task's two columns, as v48 keeps them; a note in their place once they are gone."""
    if not set(MOVED) <= set(columns(connection, 'tasks')):
        return 'the columns are gone'
    return [tuple(r) for r in connection.execute(
        "SELECT id, 0, checkpoint, typeof(checkpoint), modules, typeof(modules) FROM tasks ORDER BY id")]


def new_checkpoints(connection):
    return [tuple(r) for r in connection.execute(
        "SELECT task_id, place, checkpoint, typeof(checkpoint), modules, typeof(modules) "
        "FROM task_checkpoints ORDER BY task_id, place")]


def version(connection):
    row = connection.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()
    return row[0] if row else None


# Each a task as v48 kept it: its checkpoint and its modules, as written.
TASKS = [('sdxl\\model.safetensors [abc123]', '["F:\\\\models\\\\VAE\\\\sdxl_vae.safetensors"]'),
         (None, '[]'),                                   # Forge had no checkpoint selected
         ('flux1-dev.safetensors', '["ae.safetensors", "t5xxl.safetensors"]'),
         ('model.safetensors', None),                    # modules never written
         (None, None)]


def v48_library(directory):
    """A library of every kind at v48, with tasks in it."""
    for name in os.listdir(directory) if os.path.isdir(directory) else []:
        if '.backup_' in name:
            os.remove(os.path.join(directory, name))
    path, connection = generation_fixture.v36_database(directory)
    generation_fixture.varied(connection, directory)
    cursor = connection.cursor()
    migrations.run_migrations(cursor, 36, 48, path, directory)
    connection.commit()
    cursor.execute("DELETE FROM tasks")
    for n, (checkpoint, modules) in enumerate(TASKS):
        cursor.execute("INSERT INTO tasks (install, forge, mode, status, inputs, checkpoint, modules, created_at) "
                       "VALUES ('here', 'neo', 'txt2img', 'pending', ?, ?, ?, '2026-11-05')",
                       ('{"fixed": {"prompt": "task %d"}}' % n, checkpoint, modules))
    connection.commit()
    return path, connection


def migrate(connection, path):
    cursor = connection.cursor()
    try:
        migrations.run_migrations(cursor, 48, 49, path, os.path.dirname(path))
        connection.commit()
        return None
    except Exception as error:
        connection.rollback()
        return f'{type(error).__name__}: {error}'


def backups(directory):
    return [name for name in os.listdir(directory) if name.endswith('_v49')]


# ------------------------------------------------------------ the migration
check('v49 is a schema this copy has passed', SCHEMA_VERSION >= 49)
directory = os.path.join(WORK, 'library')
path, connection = v48_library(directory)
before, shape, old = everything(connection), schema(connection), old_checkpoints(connection)
check('the library keeps tasks with and without a checkpoint, modules NULL beside []',
      [(r[3], r[5]) for r in old], [('text', 'text'), ('null', 'text'), ('text', 'text'), ('text', 'null'),
                                    ('null', 'null')])
check('the migration runs without raising', migrate(connection, path), None)
check('every task comes out as one row at place 0, its checkpoint and modules equal, type and all',
      new_checkpoints(connection), old)
check("tasks keep neither column", [c for c in MOVED if c in columns(connection, 'tasks')], [])
check('a row holds its settings, status and error, none yet',
      [tuple(r) for r in connection.execute("SELECT settings, status, error FROM task_checkpoints")],
      [(None, None, None)] * len(TASKS))
check('keyed by task and place', [r[1] for r in sorted(
    (r for r in connection.execute("PRAGMA table_info(task_checkpoints)") if r[5]), key=lambda r: r[5])],
    ['task_id', 'place'])
check('the database was backed up first', len(backups(directory)), 1)
check('every row of every other table as it was', [t for t in sorted(set(before) | set(everything(connection)))
                                                    if before.get(t) != everything(connection).get(t)], [])
check('every other table and index as it was', schema(connection), shape)
check('the version is 49', version(connection), '49')

after = (new_checkpoints(connection), everything(connection), schema(connection))
check('run twice, it does not raise', migrate(connection, path), None)
check('run twice, it changes nothing', (new_checkpoints(connection), everything(connection), schema(connection)),
      after)
check('nor backs up again', len(backups(directory)), 1)
connection.close()

# ------------------------------------------------- a difference raises
directory = os.path.join(WORK, 'broken')
path, connection = v48_library(directory)
old = old_checkpoints(connection)
# The break: the new table exists already, with a trigger that writes a NULL
# `modules` as '[]' - the difference v37 once made between "Use same" and none.
connection.executescript("""
    CREATE TABLE task_checkpoints (task_id INTEGER NOT NULL, place INTEGER NOT NULL, checkpoint TEXT,
        modules TEXT, settings TEXT, status TEXT, error TEXT, PRIMARY KEY (task_id, place));
    CREATE TRIGGER v49_break AFTER INSERT ON task_checkpoints WHEN NEW.modules IS NULL
    BEGIN UPDATE task_checkpoints SET modules = '[]' WHERE task_id = NEW.task_id AND place = NEW.place; END;
""")
raised = migrate(connection, path)
check('a row that comes out different raises', bool(raised and 'v49 would lose data' in raised), True)
check('and the tasks keep both columns, as they were', old_checkpoints(connection), old)
check('no row is left in the new table', new_checkpoints(connection), [])
check('the version stays 48', version(connection), '48')
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
check('a new database is made at this version, its tasks without the two columns, its table there',
      (version(raw), [c for c in MOVED if c in columns(raw, 'tasks')], columns(raw, 'task_checkpoints')),
      (str(SCHEMA_VERSION), [], ['task_id', 'place', 'checkpoint', 'modules', 'settings', 'status', 'error']))
check('and backed up nothing: it had no task', backups(NEW), [])
raw.close()

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
