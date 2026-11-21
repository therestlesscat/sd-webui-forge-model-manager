"""
Two WebUIs sharing one database, migrating it at the same start (#428).

Both read the old version at startup. The first migrated; the second waited
for the write lock, which the first lets go of between steps and inside seven
of them, and either gave up with "database is locked" or ran a step the first
was running or had run. Now the first holds a lock file beside the database
(`models.db.migrating`) for its whole run, and the second waits on it, then
reads the version again.

Each WebUI is a child process opening the same throwaway database through
ModelsDatabase, every step's run logged to a file. The first holds inside a
step, its write lock taken and the step not committed, until the suite lets
it go once the second waits. What is checked: the second waits and ends with
the database at 49, every step run once, by the first; its migration state
says it waits; two on a missing file; the first killed while holding; the
wait running out; the other WebUI, a newer copy, taking the database past
this one meanwhile; a current database never touching the lock file; a lock
file that cannot be used - other data, a folder, read-only; no lock file
left; the lock file opened again when the path no longer names it; and
what the startup thread says of a migration that never ran, and
says again at a Reload UI. Waits are cut short in the children: "database is
locked" after 2 s, and the wait for the other WebUI 30 s - 1 s where it is to
run out.
"""
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

WAITING = 'Waiting for the other WebUI sharing this database to finish updating it.'


def child(spec):
    """One WebUI's start: ModelsDatabase opened on `spec['path']`, its steps logged, one held."""
    from model_manager import console
    import model_manager.db.database as database
    from model_manager.db import migrations
    import threading

    database.BUSY_SECONDS = spec['busy']
    database.COMPACT_WAIT_SECONDS = spec['wait']
    # A newer copy of the extension: its run ends by writing this version.
    database.SCHEMA_VERSION = spec.get('schema') or database.SCHEMA_VERSION
    role, hold, signals = spec['role'], spec.get('hold'), spec['signals']

    def signal(name, text=''):
        with open(os.path.join(signals, f'{role}.{name}'), 'w') as f:
            f.write(text)

    def logged(version, step):
        def run(cursor, *args, **kwargs):
            with open(spec['log'], 'a') as f:
                f.write(f'{role} {version}\n')
            result = step(cursor, *args, **kwargs)
            if version == hold:
                signal('holding', str(cursor.connection.in_transaction))
                go = os.path.join(signals, 'go')
                until = time.time() + 40
                while not os.path.exists(go) and time.time() < until:
                    time.sleep(0.05)
            return result
        return run

    if spec.get('linger'):
        # The first's lock let go of, it lingers before going on: the database
        # must hold its run by then, committed before the lock goes.
        import contextlib
        real_alone = database._migrating_alone

        @contextlib.contextmanager
        def lingering(*args, **kwargs):
            with real_alone(*args, **kwargs):
                yield
            time.sleep(spec['linger'])
        database._migrating_alone = lingering

    for version in range(2, 50):
        name = f'_migrate_to_v{version}'
        if hasattr(migrations, name):
            setattr(migrations, name, logged(version, getattr(migrations, name)))

    def watch():
        # Read beside the code, never through migration_state(), whose
        # fallback reads the repository's own models.db (tests/AGENTS.md,
        # "In a suite, `database_path()` names the repository's own stale
        # `models.db`").
        while True:
            with database._migration_lock:
                state = dict(database._migration or {})
            if state.get('progress') == WAITING:
                signal('waiting', 'state')
                return
            lines, _ = console.since(0)
            if any('Waiting for the other WebUI' in line['text'] for line in lines):
                signal('waiting', 'console')
                return
            time.sleep(0.05)
    threading.Thread(target=watch, daemon=True).start()

    result = {'error': None, 'case': None}
    try:
        database.ModelsDatabase(os.path.dirname(spec['path']), spec['path']).close()
    except Exception as error:
        result = {'error': f'{type(error).__name__}: {error}', 'case': getattr(error, 'case', None)}
    with database._migration_lock:
        result['state'] = dict(database._migration) if database._migration else None
    print('RESULT ' + json.dumps(result), flush=True)


if len(sys.argv) > 2 and sys.argv[1] == 'child':
    webui_stub.install()
    child(json.loads(sys.argv[2]))
    sys.exit(0)

opts = webui_stub.install()
import model_manager.db.database as database             # noqa: E402
from model_manager.db import migrations, SCHEMA_VERSION  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'migration_together')
# A run stopped mid-way can leave check 15's read-only file, which rmtree cannot delete.
for folder, _, names in os.walk(WORK):
    for name in names:
        os.chmod(os.path.join(folder, name), stat.S_IREAD | stat.S_IWRITE)
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def v41():
    """A database at v41, as a WebUI leaves it: WAL, its schema_info saying 41."""
    folder = os.path.join(WORK, 'template')
    os.makedirs(folder)
    path = os.path.join(folder, 'models.db')
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT)")
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        migrations.run_migrations(cursor, 0, 41, path, folder)
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    return path


TEMPLATE = v41()


def place(name, copy=True):
    """A folder of its own for one situation, with a copy of the v41 database unless told not to."""
    folder = os.path.join(WORK, name)
    os.makedirs(os.path.join(folder, 'signals'))
    path = os.path.join(folder, 'models.db')
    if copy:
        shutil.copyfile(TEMPLATE, path)
    return path, os.path.join(folder, 'signals'), os.path.join(folder, 'steps.log')


def start(role, path, signals, log, hold=None, wait=30.0, schema=None, linger=None):
    spec = {'role': role, 'path': path, 'signals': signals, 'log': log, 'hold': hold,
            'busy': 2.0, 'wait': wait, 'schema': schema, 'linger': linger}
    return subprocess.Popen([sys.executable, os.path.abspath(__file__), 'child', json.dumps(spec)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT,
                            encoding='utf-8', errors='replace')


def until(test, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return True
        time.sleep(0.05)
    return test()


def ended(process, seconds=40):
    """The child's result, once it ends; killed and said so if it does not."""
    try:
        out, _ = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        out, _ = process.communicate()
        return {'error': 'did not end in time', 'case': None, 'state': None}
    for line in out.splitlines():
        if line.startswith('RESULT '):
            return json.loads(line[len('RESULT '):])
    return {'error': 'no result: ' + out[-600:], 'case': None, 'state': None}


def there(signals, name):
    return os.path.exists(os.path.join(signals, name))


def version(path):
    """The version the file says, or the error reading it: just after a child was killed,
    Windows can answer "disk I/O error" for a moment (seen once in 3 runs)."""
    for _ in range(20):
        connection = sqlite3.connect(path, timeout=5)
        try:
            row = connection.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error as error:
            failed = f'{type(error).__name__}: {error}'
        finally:
            connection.close()
        time.sleep(0.1)
    return failed


def steps(log):
    if not os.path.exists(log):
        return []
    with open(log) as f:
        return [line.strip() for line in f if line.strip()]


def by(role, first, last):
    return [f'{role} {v}' for v in range(first, last + 1)]


children = []
try:
    # ------------------------------ 7, 8, 9, 16: the second starts mid-step
    path, signals, log = place('together')
    first = start('A', path, signals, log, hold=43)
    children.append(first)
    holding = until(lambda: there(signals, 'A.holding'), 30)
    check('7. (set-up) the first holds inside step 43, its write lock taken',
          (holding, holding and open(os.path.join(signals, 'A.holding')).read()), (True, 'True'))
    second = start('B', path, signals, log)
    children.append(second)
    until(lambda: there(signals, 'B.waiting') or second.poll() is not None, 10)
    waited = there(signals, 'B.waiting') and open(os.path.join(signals, 'B.waiting')).read()
    open(os.path.join(signals, 'go'), 'w').close()
    a, b = ended(first), ended(second)
    check('7. the first completes', a['error'], None)
    check('7. the second waits for it and completes without an error, the database at 49',
          (b['error'], version(path)), (None, SCHEMA_VERSION))
    check('8. steps 42 to 49 each run once, by the first; none by the second', steps(log), by('A', 42, 49))
    check('9. while it waits, the second\'s migration state says so', waited, 'state')
    check('16. no lock file once the last WebUI lets go of it',
          [os.path.exists(path + suffix) for suffix in ('.migrating', '.migrating-journal')], [False, False])

    # ------------------------------------------------- 16: one WebUI alone
    path, signals, log = place('alone')
    alone = ended(start('A', path, signals, log))
    check('16. a migration alone ends at 49', (alone['error'], version(path)), (None, SCHEMA_VERSION))
    check('16. and leaves no lock file', os.path.exists(path + '.migrating'), False)

    # --------------------------------------- 10: two on a file not made yet
    path, signals, log = place('new', copy=False)
    first = start('A', path, signals, log, hold=2)
    children.append(first)
    holding = until(lambda: there(signals, 'A.holding'), 30)
    check('10. (set-up) the first holds inside its first step', holding, True)
    second = start('B', path, signals, log)
    children.append(second)
    until(lambda: there(signals, 'B.waiting') or second.poll() is not None, 10)
    check('10. (set-up) the second waits on the first - its console says so: a new file has no notice',
          there(signals, 'B.waiting') and open(os.path.join(signals, 'B.waiting')).read(), 'console')
    open(os.path.join(signals, 'go'), 'w').close()
    a, b = ended(first), ended(second)
    check('10. both complete, the database at 49', (a['error'], b['error'], version(path)),
          (None, None, SCHEMA_VERSION))
    check('10. every step run once, by the first', steps(log), by('A', 2, 49))
    connection = sqlite3.connect(path)
    first_rows = connection.execute("SELECT key FROM schema_info WHERE key IN ('created_by', ?, ?) ORDER BY key",
                                    (database.JUDGED_KEY, database.FILLED_KEY)).fetchall()
    connection.close()
    # INSERT OR IGNORE: a second write would leave the same rows. What the
    # rows written before the lock do is the deadlock above.
    check('10. a new database\'s first rows are there', len(first_rows), 3)

    # ------------------------------- 11: the first killed while it holds the lock
    path, signals, log = place('killed')
    first = start('A', path, signals, log, hold=43)
    children.append(first)
    until(lambda: there(signals, 'A.holding'), 30)
    second = start('B', path, signals, log)
    children.append(second)
    until(lambda: there(signals, 'B.waiting') or second.poll() is not None, 10)
    check('11. (set-up) the second waits on the first before the first is killed', there(signals, 'B.waiting'), True)
    first.kill()
    first.communicate()
    b = ended(second)
    check('11. killed holding the lock, the first lets go of it: the second takes over and ends at 49',
          (b['error'], version(path)), (None, SCHEMA_VERSION))
    check('11. running 43 to 49 itself - the first\'s step 43 was never committed',
          [line for line in steps(log) if line.startswith('B')], by('B', 43, 49))

    # --------------------------------------------------- 12: the wait runs out
    path, signals, log = place('waited_out')
    first = start('A', path, signals, log, hold=43)
    children.append(first)
    until(lambda: there(signals, 'A.holding'), 30)
    second = start('B', path, signals, log, wait=1.0)
    children.append(second)
    b = ended(second, 15)
    open(os.path.join(signals, 'go'), 'w').close()
    a = ended(first)
    check('12. the wait running out, the second stops, naming the other WebUI, and runs no step',
          ('still updating' in str(b['error']), b['case'], [line for line in steps(log) if line.startswith('B')]),
          (True, 'waited', []))
    check('12. its migration state names the case, for the page\'s notice',
          ((b['state'] or {}).get('case'), 'still updating' in str((b['state'] or {}).get('error'))), ('waited', True))
    check('12. the first goes on and ends at 49', (a['error'], version(path)), (None, SCHEMA_VERSION))

    # ------------- 17: the other WebUI, a newer copy, updates it past this one
    path, signals, log = place('newer')
    first = start('A', path, signals, log, hold=43, schema=SCHEMA_VERSION + 1, linger=1.5)
    children.append(first)
    until(lambda: there(signals, 'A.holding'), 30)
    second = start('B', path, signals, log)
    children.append(second)
    until(lambda: there(signals, 'B.waiting') or second.poll() is not None, 10)
    open(os.path.join(signals, 'go'), 'w').close()
    a, b = ended(first), ended(second)
    check('17. (set-up) the first, a newer copy, ends with the database past this copy',
          (a['error'], version(path)), (None, SCHEMA_VERSION + 1))
    check('17. the second, waiting meanwhile, refuses it as newer and runs no step',
          ('newer than this copy' in str(b['error']), b['case'],
           [line for line in steps(log) if line.startswith('B')]), (True, 'newer', []))
    check('17. its migration state names the case, with the versions and the file, for the page\'s notice',
          ((b['state'] or {}).get('case'), (b['state'] or {}).get('newer')),
          ('newer', {'schema': SCHEMA_VERSION + 1, 'known': SCHEMA_VERSION, 'path': path}))
finally:
    for process in children:
        if process.poll() is None:
            process.kill()
            process.communicate()

# ------------------------------------- 13: a current database leaves it alone
# A folder where the lock file would be: any use of it fails.
current = os.path.join(WORK, 'current', 'models.db')
os.makedirs(os.path.dirname(current))
database.ModelsDatabase(os.path.dirname(current), current).close()
kept = os.path.exists(current + '.migrating')
check('16. a new database made alone leaves no lock file', kept, False)
if kept:
    os.remove(current + '.migrating')
os.makedirs(current + '.migrating')
database._migration = None
try:
    database.ModelsDatabase(os.path.dirname(current), current).close()
    opened = None
except Exception as error:
    opened = f'{type(error).__name__}: {error}'
check('13. a WebUI starting on a database at 49 opens it, and never the lock file', opened, None)

# ----------------------------------------- 15: a lock file that cannot be used
def junk(lock):
    with open(lock, 'wb') as f:
        f.write(b'not a database, ' * 64)


def folder(lock):
    os.makedirs(lock)


def read_only(lock):
    open(lock, 'wb').close()
    os.chmod(lock, stat.S_IREAD)


for name, make in (('other data', junk), ('a folder', folder), ('a read-only file', read_only)):
    path, _, _ = place('unusable_' + name.replace(' ', '_').replace('-', '_'))
    lock = path + '.migrating'
    make(lock)
    left = (os.path.isdir(lock), os.path.isfile(lock) and open(lock, 'rb').read())
    database._migration = None
    try:
        database.ModelsDatabase(os.path.dirname(path), path).close()
        raised = None
    except Exception as error:
        raised = str(error)
    state = database._migration or {}
    check(f'15. {name} for a lock file: the migration fails, naming the file, and runs nothing',
          (raised is not None and lock in raised, state.get('case'), version(path)), (True, 'lock_file', 41))
    check(f'15. {name}: the file is left as it is',
          (os.path.isdir(lock), os.path.isfile(lock) and open(lock, 'rb').read()), left)
    if os.path.isfile(lock):
        os.chmod(lock, stat.S_IREAD | stat.S_IWRITE)
database._migration = None

# ------------------ 19: the lock file removed or made anew as it is taken
# Linux lets the first WebUI remove the file the waiter has open, and the
# waiter's lock is then on a file the path no longer names. Windows refuses
# the removal, so the path is made to name another file once, by a stand-in.
reopen = os.path.join(WORK, 'reopen')
os.makedirs(reopen)
looked = []
real_named = getattr(database, '_file_named', None)


def moved_once(path):
    looked.append(path)
    return ('another file',) if len(looked) == 2 else real_named(path)


database._file_named = moved_once
try:
    with database._migrating_alone(os.path.join(reopen, 'models.db'), 0):
        taken = None
except Exception as error:                # HEAD has no _migrating_alone: a failed check, not a crash
    taken = f'{type(error).__name__}: {error}'
finally:
    database._file_named = real_named
check('19. a lock file the path no longer names once taken: opened again by its path, and taken',
      (taken, len(looked)), (None, 4))
check('19. and removed once let go of', os.listdir(reopen), [])

# ------------------------- 18: what the startup thread says when it never ran
# The migration's thread said "What it finished is kept, and the next start
# goes on from the step that failed" of any failure: of a run that never
# started too.
from model_manager import console                         # noqa: E402
import model_manager.api as api                           # noqa: E402
path, _, _ = place('console')
junk(path + '.migrating')
opts.model_manager_database_path = path
database._db_instance = None
database._migration = None
started = []
real_start = api._start_services
api._start_services = lambda: started.append('services')
before = console.said()
try:
    api._migrate_then_start()
    said_now = ' '.join(line['text'] for line in console.since(before)[0])
    # A Reload UI starts the thread again; the stop is kept, and said again.
    again = console.said()
    api._migrate_then_start()
    said_again = ' '.join(line['text'] for line in console.since(again)[0])
finally:
    api._start_services = real_start
    database._db_instance = None
    database._migration = None
check('18. a migration stopped by an unusable lock file: the console names the file, and claims no steps kept',
      ('cannot be used' in said_now, path + '.migrating' in said_now, 'What it finished is kept' in said_now, started),
      (True, True, False, []))
check('18. and at a Reload UI, kept, it says the same again',
      ('cannot be used' in said_again, 'What it finished is kept' in said_again, started), (True, False, []))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
