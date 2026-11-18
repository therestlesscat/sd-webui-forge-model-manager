"""
A migration run that fails partway goes on from the failed step (#391).

Each step is committed with its version, so a run that fails keeps the steps
before the one that failed, saved as such, and the next start runs only what
is left. Until 0.80.7 the version was written at the run's end alone, while a
step that backs up committed the steps before it: a failure later left them
committed under the start's version, the next start ran them again over the
tables they had changed, and from v26 or older it failed at every start.

Databases at every version from v2 to v48 are failed after v37, v42 or v49
and started again: each finishes with exactly a fresh database's tables, and
the failure leaves the version of the step before it. v25 and v32, which
commit and back up only when they hold rows, fail inside with rows in them.
v47's rename, run outside any transaction before, is undone with its copy.
A new database whose first run fails still records which version created it.
A fresh database is made as before: the same tables, one backup beside it.
"""
import contextlib
import io
import json
import os
import shutil
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

from model_manager.db import migrations                  # noqa: E402
from model_manager.db.database import ModelsDatabase, SCHEMA_VERSION  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'migration_rerun')
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


class MadeUp(Exception):
    """The failure put into a run."""


def run(path, start, fault=None, deny=None):
    """
    One start's migration, as `_init_tables` runs it: from `start` to this
    copy's version, committed at the end, rolled back on a failure. `fault`
    fails the run just after that step returns; `deny(action, table)` makes
    SQLite refuse a statement, a failure inside a step. The error's text, or None.
    """
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row             # as _get_connection opens it: v37 reads rows by name
    connection.execute("PRAGMA journal_mode=WAL")
    cursor = connection.cursor()
    original = getattr(migrations, f'_migrate_to_v{fault}') if fault else None
    if fault:
        def failing(*args, **kwargs):
            original(*args, **kwargs)
            raise MadeUp(f'made-up failure after v{fault}')
        setattr(migrations, f'_migrate_to_v{fault}', failing)
    if deny:
        connection.set_authorizer(lambda action, a, b, db, trigger:
                                  sqlite3.SQLITE_DENY if deny(action, a) else sqlite3.SQLITE_OK)
    try:
        cursor.execute("CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT)")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            migrations.run_migrations(cursor, start, SCHEMA_VERSION, path, os.path.dirname(path))
        connection.commit()
        return None
    except Exception as error:
        connection.rollback()
        return f'{type(error).__name__}: {error}'
    finally:
        if fault:
            setattr(migrations, f'_migrate_to_v{fault}', original)
        connection.set_authorizer(None)
        connection.close()


def version(path):
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()
        return int(row[0]) if row else 0
    finally:
        connection.close()


def shape(path):
    """Every table and index, with its SQL."""
    connection = sqlite3.connect(path)
    try:
        return sorted(tuple(r) for r in connection.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
    finally:
        connection.close()


def rows(path):
    """Every row of every table, as stored, the version row too, in a fixed order."""
    connection = sqlite3.connect(path)
    try:
        tables = [r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: sorted((tuple(r) for r in connection.execute(f'SELECT * FROM "{t}"')), key=repr)
                for t in tables}
    finally:
        connection.close()


def copy(source, folder):
    """A copy of a database in a folder of its own, through SQLite's backup."""
    os.makedirs(folder)
    path = os.path.join(folder, 'models.db')
    a, b = sqlite3.connect(source), sqlite3.connect(path)
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()
    return path


def step_by_step(folder):
    """A new database brought one step at a time to every version, a copy kept at each."""
    os.makedirs(folder)
    path = os.path.join(folder, 'models.db')
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT)")
    at = {}
    with contextlib.redirect_stdout(io.StringIO()):
        for target in range(2, SCHEMA_VERSION + 1):
            migrations.run_migrations(cursor, target - 1 if target > 2 else 0, target, path, folder)
            connection.commit()
            at[target] = copy(path, os.path.join(folder, f'v{target}'))
    connection.close()
    return at


def filled(path, table, values):
    """One row in `table`: the given values, and a stand-in for every other column that needs one."""
    connection = sqlite3.connect(path)
    try:
        row = {}
        for _, name, kind, notnull, default, pk in connection.execute(f'PRAGMA table_info("{table}")'):
            if name in values:
                row[name] = values[name]
            elif (notnull or pk) and default is None:
                row[name] = 1 if 'INT' in (kind or '').upper() else f'{name}_1'
        connection.execute(f'INSERT INTO "{table}" ({", ".join(row)}) VALUES ({", ".join("?" * len(row))})',
                           tuple(row.values()))
        connection.commit()
    finally:
        connection.close()


AT = step_by_step(os.path.join(WORK, 'steps'))
FRESH = shape(AT[SCHEMA_VERSION])
check('this copy migrates to v49 or later, as the cases below assume', SCHEMA_VERSION >= 49)

# ------------------------------------------------- every start, failed and started again
# After v37, v42 and v49: each commits what came before it to back up, the
# commit that left the steps before it under the start's version.
landed, unclean, cases = [], [], 0
for fault in (37, 42, 49):
    for start in range(2, fault):
        cases += 1
        path = copy(AT[start], os.path.join(WORK, 'rerun', f'{start}_{fault}'))
        error = run(path, start, fault=fault)
        stored = version(path)
        if error is None or 'made-up failure' not in error or stored != fault - 1:
            landed.append((start, fault, stored, error))
        again = run(path, stored)
        if again is not None or version(path) != SCHEMA_VERSION or shape(path) != FRESH:
            unclean.append((start, fault, again or 'tables differ'))
check(f'a failed run leaves the version of the step before the failure ({cases} cases)', landed, [])
check(f'started again, it finishes with exactly a fresh database\'s tables ({cases} cases)', unclean, [])

# After a step that commits nothing of its own: a run that committed only
# where a step does would undo every step since the last such commit.
landed = []
for start, fault in ((26, 30), (38, 40), (41, 47), (42, 46)):
    path = copy(AT[start], os.path.join(WORK, 'quiet', f'{start}_{fault}'))
    run(path, start, fault=fault)
    landed.append((start, fault, version(path)))
check('after a step that commits nothing itself, the failure still leaves the step before it', landed,
      [(26, 30, 29), (38, 40, 39), (41, 47, 46), (42, 46, 45)])

# ------------------------------------------------- v25 and v32, failed inside with rows in them
# They commit and back up only where a table holds rows; a failure then comes
# after that commit, partway through their own work. Each starts a step before
# its own, so the version it leaves tells the step before it from the start.
for start, step, table, values, refused in (
        (23, 25, 'images', {'id': 7, 'version_id': 70, 'page': 1, 'data': json.dumps({'id': 7, 'url': 'u'})},
         'images_v25'),
        (30, 32, 'model_versions', {'id': 70, 'model_id': 700, 'file_path': 'C:\\m\\a.safetensors',
                                    'file_name': 'a.safetensors'}, 'files')):
    clean = copy(AT[start], os.path.join(WORK, f'rows_v{step}', 'clean'))
    filled(clean, table, values)
    failed = copy(clean, os.path.join(WORK, f'rows_v{step}', 'failed'))
    check(f'v{step}: the clean run from v{start} with a row in {table} finishes', run(clean, start), None)
    error = run(failed, start, deny=lambda action, name: action == sqlite3.SQLITE_INSERT and name == refused)
    check(f'v{step}: refused its INSERT into {refused}, the run fails inside v{step}',
          bool(error) and 'not authorized' in error, True)
    check(f'v{step}: it made its backup before failing',
          any('.backup_' in f for f in os.listdir(os.path.dirname(failed))), True)
    check(f'v{step}: the failure leaves v{step - 1}', version(failed), step - 1)
    check(f'v{step}: started again, it finishes', run(failed, version(failed)), None)
    check(f'v{step}: with every row the clean run has', rows(failed), rows(clean))

# ------------------------------------------------- v47's rename, undone with its copy
COLUMNS = ('install', 'version_id', 'position', 'model_id', 'file_id', 'file_index', 'file_name',
           'partial_path', 'total_bytes')
KEPT = ('here', 501, 0, 42, 5011, None, 'f_501.safetensors', None, 100)
path = copy(AT[46], os.path.join(WORK, 'v47'))
connection = sqlite3.connect(path)
connection.execute(f"INSERT INTO downloads ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})", KEPT)
connection.commit()
connection.close()
renamed = []
def at_the_copy(action, name):
    """Refuse the INSERT into the new downloads table: the moment after the rename."""
    if action == sqlite3.SQLITE_ALTER_TABLE:
        renamed.append(name)
    return action == sqlite3.SQLITE_INSERT and name == 'downloads' and bool(renamed)
error = run(path, 46, deny=at_the_copy)
check('v47 is stopped at its copy, after its rename', (bool(error) and 'not authorized' in error, bool(renamed)),
      (True, True))
connection = sqlite3.connect(path)
tables = sorted(r[0] for r in connection.execute(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'downloads%'"))
kept = [tuple(r) for r in connection.execute(f"SELECT {', '.join(COLUMNS)} FROM downloads")]
connection.close()
check('the rename is undone with the copy: downloads keeps its row, no downloads_v46', (tables, kept),
      (['downloads'], [KEPT]))
check('and the database stays at v46', version(path), 46)
check('started again, it finishes', run(path, version(path)), None)
connection = sqlite3.connect(path)
check('with the kept download carried over', [tuple(r) for r in connection.execute(
    f"SELECT {', '.join(COLUMNS)} FROM downloads")], [KEPT])
connection.close()

# ------------------------------------------------- a new database's first run, failed
NEW = os.path.join(WORK, 'new')
os.makedirs(NEW)
original = migrations._migrate_to_v42
def failing_v42(*args, **kwargs):
    original(*args, **kwargs)
    raise MadeUp('made-up failure after v42')
migrations._migrate_to_v42 = failing_v42
try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        ModelsDatabase(extension_dir=ROOT, custom_db_path=os.path.join(NEW, 'models.db'))
    raised = None
except MadeUp as error:
    raised = str(error)
finally:
    migrations._migrate_to_v42 = original
check('a new database\'s first run fails after v42', raised, 'made-up failure after v42')
try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        ModelsDatabase(extension_dir=ROOT, custom_db_path=os.path.join(NEW, 'models.db')).close()
    raised = None
except Exception as error:
    raised = f'{type(error).__name__}: {error}'
check('started again, it opens', raised, None)
raw = sqlite3.connect(os.path.join(NEW, 'models.db'))
info = dict(raw.execute("SELECT key, value FROM schema_info"))
raw.close()
check('started again, it is at this version and records which version created it',
      (info.get('version'), 'created_by' in info), (str(SCHEMA_VERSION), True))

# A library updated from an older version is no new database: it is given no
# `created_by`, which the release notes read as made by this version.
OLD = copy(AT[48], os.path.join(WORK, 'updated'))
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    ModelsDatabase(extension_dir=ROOT, custom_db_path=OLD).close()
raw = sqlite3.connect(OLD)
info = dict(raw.execute("SELECT key, value FROM schema_info"))
raw.close()
check('a library updated from v48 is migrated, and records no version as its creator',
      (info.get('version'), 'created_by' in info), (str(SCHEMA_VERSION), False))

# ------------------------------------------------- a fresh database, as before
FOLDER = os.path.join(WORK, 'fresh')
os.makedirs(FOLDER)
path = os.path.join(FOLDER, 'models.db')
check('a fresh database migrates from v0 in one run', run(path, 0), None)
check('with the same tables as one brought a step at a time', shape(path), FRESH)
check('at this version', rows(path)['schema_info'], [('version', str(SCHEMA_VERSION))])
check('and one backup beside it, v4\'s', len([f for f in os.listdir(FOLDER) if '.backup_' in f]), 1)

shutil.rmtree(WORK, ignore_errors=True)
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
