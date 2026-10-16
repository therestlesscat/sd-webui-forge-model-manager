"""
The database file's space and its backups (#287): db/upkeep.py and its routes.

A compact is a VACUUM and the TRUNCATE checkpoint after it. What is checked:
the space the window is told of; a compact keeping every row - the hidden
row numbers of `files` too - and giving the space back; a reader open
through it, the file shrinking once the window asks after the reader ends;
a write of this WebUI arriving mid-compact waiting for it, past its busy
timeout, and the next call after it waiting as long as ever; another
program's write refusing it, nothing changed; the flag cleared when it
fails; what stops one - each long job, a working queue, too little room;
Cancel; two presses. The backups: only the names migrations give, in the
database's folder, each with the version it holds; a delete by names alone,
refused whole on a name not listed, refused while a migration runs, a copy
held open said to be in use.

Throwaway databases under tests/work. The busy timeout is cut to 0.3 s, and a
VACUUM slowed past it by a progress handler on the compact's connection - a
sleep on Windows lasts at least its clock's tick, 15.5 ms.
"""
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'database_upkeep')
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
opts = webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import model_manager.db.database as database             # noqa: E402
database.BUSY_SECONDS = 0.3
from model_manager.db import ModelsDatabase              # noqa: E402
from model_manager.db import upkeep                      # noqa: E402
from model_manager.jobs import jobs                      # noqa: E402
import model_manager.scheduler.runner as runner          # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


opened = []


def fresh(name, filler=12000):
    """A database at today's schema with a dropped table's pages free, and `files` rows with gaps."""
    path = os.path.join(WORK, name)
    db = ModelsDatabase(WORK, path)
    opened.append(db)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE filler (id INTEGER PRIMARY KEY, d TEXT)")
    conn.executemany("INSERT INTO filler (d) VALUES (?)", (('x' * 1500 + str(i),) for i in range(filler)))
    conn.executemany("INSERT INTO files (file_path, file_name) VALUES (?, ?)",
                     ((f'C:\\m\\{i:05d}.safetensors', f'{i:05d}.safetensors') for i in range(3000)))
    conn.commit()
    conn.execute("DELETE FROM files WHERE rowid % 3 = 0")
    conn.execute("DROP TABLE filler")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path, db


def use(path, db):
    database._db_instance = db
    opts.model_manager_database_path = path


def ro(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def contents(path):
    """Every table's rows, the hidden row number with them where there is one, hashed."""
    conn = ro(path)
    try:
        found = {}
        for name, sql in conn.execute("SELECT name, sql FROM sqlite_master "
                                      "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
            rowid = 'WITHOUT ROWID' not in sql.upper()
            rows = conn.execute(f'SELECT {"rowid, " if rowid else ""}* FROM "{name}"').fetchall()
            found[name] = hashlib.sha256('\n'.join(sorted(map(repr, rows))).encode()).hexdigest()
        return found
    finally:
        conn.close()


def files_rowids(path):
    conn = ro(path)
    try:
        return conn.execute("SELECT rowid, file_path FROM files ORDER BY file_path").fetchall()
    finally:
        conn.close()


def pages(path):
    conn = ro(path)
    try:
        return [conn.execute(f"PRAGMA {p}").fetchone()[0] for p in ('page_size', 'page_count', 'freelist_count')]
    finally:
        conn.close()


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def size(path):
    return os.path.getsize(path) if os.path.exists(path) else 0


def compact(path, timeout=60):
    """A compact through the job registry, as the route starts one; its progress once it ends."""
    reason = upkeep.start(path)
    if reason:
        return reason
    jobs.join(timeout)
    return jobs.progress(upkeep.KIND)


real_open = upkeep.Compact._open


def slowed(conn):
    """A VACUUM slowed: a short sleep every 100 steps of SQLite's machine."""
    conn.set_progress_handler(lambda: (time.sleep(0.001), 0)[1], 100)
    return conn


def wait_for(test, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return True
        time.sleep(0.01)
    return False


# ------------------------------------------------- 1. what the window hears
path, db = fresh('space.db')
use(path, db)
page_size, page_count, free = pages(path)
before = (digest(path), os.path.getmtime(path))
space = upkeep.space(path)
check('1. free space is the free pages times the page size',
      (space['free_bytes'], space['page_size']), (free * page_size, page_size))
check('1. the size kept is the pages in use', space['kept_bytes'], (page_count - free) * page_size)
check('1. there is something to free: over the floor', space['free_bytes'] > upkeep.MIN_FREE, True)
check('1. and nothing stops a compact', space['blocked'], None)
check('1. asking writes nothing', (digest(path), os.path.getmtime(path)), before)

# --------------------------------------------------- 2. a compact keeps every row
rows, rowids = contents(path), files_rowids(path)
progress = compact(path)
check('2. the compact ends done, the file shrunk', (progress.state, progress.shrunk), ('done', True))
check('2. every table\'s rows the same', contents(path), rows)
check('2. the hidden row numbers of files the same, gaps and all', files_rowids(path), rowids)
conn = ro(path)
check('2. the integrity check passes, still in WAL mode',
      (conn.execute("PRAGMA integrity_check").fetchone()[0], conn.execute("PRAGMA journal_mode").fetchone()[0]),
      ('ok', 'wal'))
conn.close()
page_size, page_count, free = pages(path)
check('2. the file is the pages it keeps, none free', (size(path), free), (page_size * page_count, 0))
check('2. and the WAL is empty', size(path + '-wal'), 0)
check('2. what it says: before and after, as the disk holds them', (progress.before > progress.after,
      progress.after), (True, size(path) + size(path + '-wal')))
check('2. the flag is down after it', database.compacting.is_set(), False)
space = upkeep.space(path)
check('2. asked after, the window hears the file is compact', space['free_bytes'] < upkeep.MIN_FREE, True)

# ------------------------------------------ 3. a reader open through the compact
path, db = fresh('reader.db')
use(path, db)
jobs.reset()
reader = sqlite3.connect(path)
reader.execute('BEGIN')
reader.execute('SELECT COUNT(*) FROM files').fetchone()
tries = upkeep.CHECKPOINT_TRIES, upkeep.CHECKPOINT_WAIT
upkeep.CHECKPOINT_TRIES, upkeep.CHECKPOINT_WAIT = 2, 0.1
try:
    progress = compact(path)
finally:
    upkeep.CHECKPOINT_TRIES, upkeep.CHECKPOINT_WAIT = tries
check('3. with a reader open, the compact is done but the file not yet smaller',
      (progress.state, progress.shrunk), ('done', False))
held = size(path)
upkeep.space(path)
check('3. asked while the reader is still open, it stays so, and the ask does not wait',
      (jobs.progress(upkeep.KIND).shrunk, size(path)), (False, held))
reader.rollback()
reader.close()
upkeep.space(path)
page_size, page_count, free = pages(path)
check('3. once the reader ends, the next ask of the window gives the space back',
      (jobs.progress(upkeep.KIND).shrunk, size(path), size(path + '-wal')), (True, page_size * page_count, 0))

# --------------------------- 4. a write of this WebUI arriving mid-compact waits
path, db = fresh('writer.db', filler=6000)
use(path, db)
jobs.reset()
upkeep.Compact._open = lambda self: slowed(real_open(self))
seen = {}


def writer():
    # In once the VACUUM holds the database: the flag goes up just before it.
    wait_for(database.compacting.is_set)
    time.sleep(0.2)
    started = time.time()
    try:
        db.set_info('written_during_compact', 'yes')
        seen['write'] = 'ok'
    except sqlite3.OperationalError as e:
        seen['write'] = str(e)
    seen['waited'] = time.time() - started
    wait_for(lambda: not database.compacting.is_set())
    db.get_info('written_during_compact')
    seen['after'] = db._get_connection().execute('PRAGMA busy_timeout').fetchone()[0]


thread = threading.Thread(target=writer)
thread.start()
try:
    progress = compact(path)
finally:
    upkeep.Compact._open = real_open
thread.join(30)
took = progress.finished - progress.started
check('4. the slowed compact ran well past the writer\'s arrival and 0.3 s busy timeout', took > 0.9, True)
check('4. the write arriving mid-compact landed after it, not "database is locked"', seen.get('write'), 'ok')
check('4. having waited past its own 0.3 s timeout for the VACUUM', seen.get('waited', 0) > 0.3, True)
check('4. it is in the database', db.get_info('written_during_compact'), 'yes')
check('4. the next call of that thread waits 0.3 s again, not an hour', seen.get('after'), 300)

# ------------------------------------------- 5. another program holds a write
path, db = fresh('locked.db')
use(path, db)
jobs.reset()
rows, held = contents(path), digest(path)
locker = sqlite3.connect(path, isolation_level=None)
locker.execute('BEGIN IMMEDIATE')
locker.execute("INSERT INTO schema_info (key, value) VALUES ('held', 'x')")
progress = compact(path)
locker.execute('ROLLBACK')
locker.close()
check('5. a write held elsewhere: the compact fails, told apart as another program\'s',
      (progress.state, progress.locked), ('failed', True))
check('5. the file is byte for byte as it was, every row the same', (digest(path), contents(path)), (held, rows))
check('5. the flag is down', database.compacting.is_set(), False)

# --------------------------------------------- 6. a compact failing inside
jobs.reset()
real_checkpoint = upkeep.Compact._checkpoint


def broken(self, conn):
    raise RuntimeError('broken on purpose')


upkeep.Compact._checkpoint = broken
try:
    progress = compact(path)
finally:
    upkeep.Compact._checkpoint = real_checkpoint
check('6. a compact that raises ends failed, with its error', (progress.state, progress.error),
      ('failed', 'broken on purpose'))
check('6. and leaves the flag down: calls wait 0.3 s again', database.compacting.is_set(), False)
db.get_info('anything')
check('6. this thread\'s connection waits 0.3 s', db._get_connection().execute('PRAGMA busy_timeout').fetchone()[0],
      300)

# ------------------------------------------------------ 7. what stops one
path, db = fresh('stops.db')
use(path, db)
jobs.reset()
mtime = os.path.getmtime(path)
for kind, name in (('sync', 'Sync with Civitai'), ('images', 'Sync images'),
                   ('restamp', 'judging stored images again')):
    hold = threading.Event()
    jobs.start(kind, lambda: SimpleNamespace(progress=SimpleNamespace(fail=lambda m: None)),
               lambda s: hold.wait(10))
    check(f'7. {kind} running stops a compact, saying so', upkeep.start(path),
          f'Compacting waits for {name} to end.')
    check(f'7. and the window hears the same', upkeep.space(path)['blocked'], f'Compacting waits for {name} to end.')
    hold.set()
    jobs.join(10)
real_working = runner.working
runner.working = lambda: True
try:
    check('7. a working queue stops one', upkeep.start(path), 'Compacting waits for the queue to end or pause.')
finally:
    runner.working = real_working
check('7. no VACUUM ran for any of them', (os.path.getmtime(path), jobs.progress(upkeep.KIND)), (mtime, None))
real_running = runner._running
try:
    runner._running = lambda: SimpleNamespace(progress=SimpleNamespace(state='paused'))
    paused = runner.working()
    runner._running = lambda: SimpleNamespace(progress=SimpleNamespace(state='running'))
    running = runner.working()
    runner._running = lambda: None
    stopped = runner.working()
finally:
    runner._running = real_running
check('7. a paused queue does not stop one; a running one does; none does not',
      (paused, running, stopped), (False, True, False))

# ------------------------------------------------------------------ 8. room
Usage = namedtuple('Usage', 'total used free')
real_usage, real_same = shutil.disk_usage, upkeep._same_disk
temp = tempfile.gettempdir()
kept = upkeep.space(path)['kept_bytes']
need = int(kept * upkeep.ROOM_SHARE)


def room_with(database_free, temp_free, same):
    shutil.disk_usage = lambda p: Usage(10 ** 12, 0, temp_free if os.path.abspath(p) == os.path.abspath(temp)
                                         else database_free)
    upkeep._same_disk = lambda a, b: same
    try:
        return upkeep.start(path)
    finally:
        shutil.disk_usage, upkeep._same_disk = real_usage, real_same


folder_drive = upkeep._drive(os.path.dirname(path))
temp_drive = upkeep._drive(temp)
check('8. enough on both disks: it starts', room_with(10 ** 12, 10 ** 12, False) is None, True)
jobs.join(30)
path, db = fresh('room.db')
use(path, db)
jobs.reset()
kept = upkeep.space(path)['kept_bytes']
need = int(kept * upkeep.ROOM_SHARE)
check('8. too little in the temp folder\'s disk: refused, naming it and the numbers',
      room_with(10 ** 12, 1024, False),
      f'Compacting needs about {upkeep.size_text(need)} free on {temp_drive} and 1.00 KB is free.')
check('8. one disk for both: it needs the two together',
      room_with(need + 1, need + 1, True),
      f'Compacting needs about {upkeep.size_text(need * 2)} free on {folder_drive} '
      f'and {upkeep.size_text(need + 1)} is free.')
backup = os.path.join(WORK, 'room.db.backup_20261001_101010_v43')
with open(backup, 'wb') as f:
    f.write(b'\0' * (need + 10))
# A new database has one already: v4 copies the file before it runs.
beside = sum(b['bytes'] for b in upkeep.backups(path))
check('8. short on the database\'s disk, the backups beside it enough: it says so',
      room_with(10, 10 ** 12, False),
      f'Compacting needs about {upkeep.size_text(need)} free on {folder_drive} and 10 B is free. '
      f'Deleting the old backups below would free {upkeep.size_text(beside)}.')
with open(backup, 'wb') as f:
    f.write(b'\0' * 10)
check('8. the backups not enough: not said',
      room_with(10, 10 ** 12, False),
      f'Compacting needs about {upkeep.size_text(need)} free on {folder_drive} and 10 B is free.')
os.remove(backup)
check('8. nothing ran', jobs.progress(upkeep.KIND), None)

# ---------------------------------------------------------------- 9. cancel
jobs.reset()
rows, before_size = contents(path), size(path)
upkeep.Compact._open = lambda self: slowed(real_open(self))
try:
    upkeep.start(path)
    wait_for(database.compacting.is_set)
    time.sleep(0.3)
    check('9. cancel reaches a running compact', upkeep.cancel(), True)
    jobs.join(30)
finally:
    upkeep.Compact._open = real_open
progress = jobs.progress(upkeep.KIND)
check('9. cancelled', progress.state, 'cancelled')
check('9. every row, and the size, as they were', (contents(path), size(path)), (rows, before_size))
check('9. the flag is down', database.compacting.is_set(), False)
check('9. nothing to cancel once it ended', upkeep.cancel(), False)

# ----------------------------------------------- 10. two presses, and the routes
import model_manager.api as api                          # noqa: E402

app = FastAPI()
api.setup_api(app)
http = TestClient(app)
jobs.reset()
upkeep.Compact._open = lambda self: slowed(real_open(self))
try:
    first = http.post('/model-manager/database/compact')
    second = http.post('/model-manager/database/compact')
    running = http.get('/model-manager/database/compact').json()
    cancelled = http.post('/model-manager/database/compact/cancel')
    jobs.join(60)
finally:
    upkeep.Compact._open = real_open
check('10. the first press starts it', (first.status_code, first.json()['compact']['state']), (200, 'running'))
check('10. the second is refused while it runs', (second.status_code, second.json()['error']),
      (409, 'Already compacting.'))
check('10. the poll hears it running', running['compact']['state'], 'running')
check('10. Cancel through its route', cancelled.status_code, 200)
answer = http.get('/model-manager/database/space').json()
check('10. the window hears it cancelled', (answer['success'], answer['compact']['state']), (True, 'cancelled'))
check('10. cancel with none running is refused', http.post('/model-manager/database/compact/cancel').status_code, 409)

# --------------------------------------------------------------- 11. backups
folder = os.path.join(WORK, 'backups')
os.makedirs(os.path.join(folder, 'sub'))
os.makedirs(os.path.join(folder, 'models.db.backup_20261002_101010_v5'))
main = os.path.join(folder, 'models.db')
backup_db = ModelsDatabase(folder, main)
opened.append(backup_db)
# v4 backs a new database up too: only the suite's own copies from here.
for made in os.listdir(folder):
    if made.startswith('models.db.backup_') and os.path.isfile(os.path.join(folder, made)):
        os.remove(os.path.join(folder, made))


def write(name, data=b'x' * 100):
    with open(os.path.join(folder, name), 'wb') as f:
        f.write(data)


write('models.db.backup_20261001_101010_v42', b'x' * 300)
old = sqlite3.connect(os.path.join(folder, 'models.db.backup_20260901_090909'))
old.execute("CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT)")
old.execute("INSERT INTO schema_info VALUES ('version', '30')")
old.commit()
old.close()
write('models.db.backup_20260801_080808', b'not a database' * 10)
write('images_cache.db.backup_20250101_010101')
for decoy in ('models.db-shm-decoy', 'models.db.backup_x', 'other.db.backup_20261001_101010_v3',
              'models.db.backup_20261001_101010_v42.tmp', 'models.db.backup_2026100_101010', 'models.dbx'):
    write(decoy)
write(os.path.join('sub', 'models.db.backup_20261003_101010_v6'))
found = upkeep.backups(main)
check('11. only the names migrations give, newest first',
      [b['name'] for b in found],
      ['models.db.backup_20261001_101010_v42', 'models.db.backup_20260901_090909',
       'models.db.backup_20260801_080808', 'images_cache.db.backup_20250101_010101'])
check('11. each with the version it holds: _v42 holds 41; one without, read from inside; unreadable, none',
      [(b['kind'], b['holds']) for b in found],
      [('database', 41), ('database', 30), ('database', None), ('image_cache', None)])
check('11. when it was made, from its name', found[0]['made'], '2026-10-01T10:10:10')
check('11. and its size', found[0]['bytes'], 300)
check('11. the database\'s own files are never one', any(b['name'].startswith('models.db-') for b in found), False)

# ----------------------------------------------------------- 12. deleting
use(main, backup_db)
v42, v30 = 'models.db.backup_20261001_101010_v42', 'models.db.backup_20260901_090909'


def there(name):
    return os.path.exists(os.path.join(folder, name))


for names in ([v42, 'models.db'], [v42, 'models.db-wal'], [v42, '..\\models.db'],
              [v42, 'models.db.backup_20261002_101010_v5'], [v42, 'models.db.backup_20261003_101010_v6']):
    r = http.post('/model-manager/database/backups/delete', json={'names': names})
    check(f'12. {names[1]!r} among the names: all refused', (r.status_code, r.json()['success']), (409, False))
    check(f'12. and nothing deleted ({names[1]!r})', there(v42), True)
check('12. the database and the folder named like a backup are untouched',
      (there('models.db'), os.path.isdir(os.path.join(folder, 'models.db.backup_20261002_101010_v5'))), (True, True))
r = http.post('/model-manager/database/backups/delete', json={'names': [v42, v30]})
check('12. real names alone: both deleted, each said', (r.status_code, r.json()['results']),
      (200, [{'name': v42, 'deleted': True, 'error': None}, {'name': v30, 'deleted': True, 'error': None}]))
check('12. gone from the folder', (there(v42), there(v30)), (False, False))

# ---------------------------------------------- 13. a copy held open elsewhere
held_name, free_name = 'models.db.backup_20260801_080808', 'images_cache.db.backup_20250101_010101'
holder = open(os.path.join(folder, held_name), 'rb')
try:
    answer = upkeep.delete_backups(main, [held_name, free_name])
finally:
    holder.close()
if os.name == 'nt':
    check('13. the one held open is in use by another program; the other is deleted', answer.get('results'),
          [{'name': held_name, 'deleted': False, 'error': 'in use by another program'},
           {'name': free_name, 'deleted': True, 'error': None}])
else:
    check('13. (not Windows: an open file can be deleted)', answer['success'], True)

# ------------------------------------------------- 14. while a migration runs
write('models.db.backup_20261005_101010_v44')
database._migration = {'from': 43, 'to': 44, 'progress': '', 'error': None}
try:
    answer = upkeep.delete_backups(main, ['models.db.backup_20261005_101010_v44'])
finally:
    database._migration = None
check('14. refused while a migration runs', answer['success'], False)
check('14. nothing deleted', there('models.db.backup_20261005_101010_v44'), True)
r = http.post('/model-manager/database/backups/delete', json={'names': ['models.db.backup_20261005_101010_v44']})
check('14. once it has ended, it can be', (r.status_code, there('models.db.backup_20261005_101010_v44')),
      (200, False))

for db in opened:
    db.close()
database._db_instance = None
jobs.reset()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
