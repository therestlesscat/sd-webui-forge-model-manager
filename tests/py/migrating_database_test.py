"""
A database migrating at this start, said to the page (#285).

v42 took half a minute on one library, and a WebUI that looks stuck may be
stopped. The page's tabs asked the database and waited, with nothing said.
Now the server keeps the migration's state - about to run, how far it has
got, or failed - and ui-options and a route of its own answer it at once,
without the database, while the migration holds it. A failed migration is
not run again by every request, each with a backup of its own. And startup
migrates the database in a thread of its own whatever tabs are on: with only
the Civitai Browser on, nothing opened it, and the notice would have stayed.

What is checked, on throwaway v41 databases under tests/work: the state
before, during and after a migration, through ui-options and the route; a
read waiting for the migration and getting the migrated database; a failure
said, and not run again; startup migrating with only the Civitai Browser on,
and starting its other work after.
"""
import os
import shutil
import sqlite3
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'migrating_database')
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
opts = webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import model_manager.api as api                          # noqa: E402
import model_manager.db.database as database             # noqa: E402
from model_manager.db import migrations, SCHEMA_VERSION  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


OLD = SCHEMA_VERSION - 1
template = os.path.join(WORK, 'template.db')
conn = sqlite3.connect(template)
conn.execute("CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT)")
migrations.run_migrations(conn.cursor(), 0, OLD, template, WORK)
conn.execute("INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', ?)", (str(OLD),))
conn.commit()
conn.close()


def library(name):
    """A fresh copy of a database one schema behind, set as the one this WebUI opens."""
    folder = os.path.join(WORK, name)
    os.makedirs(folder)
    path = os.path.join(folder, 'models.db')
    shutil.copyfile(template, path)
    opts.model_manager_database_path = path
    database._db_instance = None
    database._migration = None
    return path


def schema(path):
    conn = sqlite3.connect('file:%s?mode=ro' % path.replace('\\', '/'), uri=True)
    try:
        return int(conn.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()[0])
    finally:
        conn.close()


def state():
    read = getattr(database, 'migration_state', None)
    return read() if read else 'no migration_state'


def within(seconds, read):
    """What `read()` answers, from a thread of its own; 'no answer' if it takes longer."""
    box = []
    worker = threading.Thread(target=lambda: box.append(read()), daemon=True)
    worker.start()
    worker.join(seconds)
    return box[0] if box else 'no answer'


def until(seconds, done):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if done():
            return True
        time.sleep(0.02)
    return False


app = FastAPI()
api.setup_api(app)
http = TestClient(app)
said = lambda: http.get('/model-manager/ui-options').json().get('database_migrating', 'missing')
asked = lambda: http.get('/model-manager/database/migration').json()

real_v42 = migrations._migrate_to_v42

# ------------------------------------------------------------ before it runs
path = library('pending')
pending = {'from': OLD, 'to': SCHEMA_VERSION, 'progress': '', 'error': None}
check('a database one schema behind reads as about to migrate', state(), pending)
check('ui-options says so to the page', within(5, said), pending)
check('and so does the route the page asks every second', within(5, asked), {'success': True, 'migrating': pending})
check('nothing was opened to say it', schema(path), OLD)
opts.model_manager_database_path = os.path.join(WORK, 'not_yet.db')
check('a database not made yet does not', state(), None)

# ------------------------------------------------------------- while it runs
path = library('running')
halfway, go_on = threading.Event(), threading.Event()


def held_v42(cursor, db_path, progress=None):
    if progress:
        progress('1 of 2 images')
    halfway.set()
    go_on.wait(20)
    # Called as it is called: HEAD's took no progress.
    return real_v42(cursor, db_path, *([progress] if progress else []))


migrations._migrate_to_v42 = held_v42
opened = []
migrating = threading.Thread(target=lambda: opened.append(database.get_models_db()), daemon=True)
migrating.start()
check('the migration started', halfway.wait(10), True)
running = {'from': OLD, 'to': SCHEMA_VERSION, 'progress': '1 of 2 images', 'error': None}
check('while it runs, ui-options answers at once, with how far it has got', within(5, said), running)
check('and so does its route', within(5, asked), {'success': True, 'migrating': running})
waiting = []
reader = threading.Thread(target=lambda: waiting.append(database.get_models_db()), daemon=True)
reader.start()
reader.join(0.3)
check('a read meanwhile - a generation recorded - waits for it', reader.is_alive(), True)
go_on.set()
migrating.join(20)
reader.join(20)
migrations._migrate_to_v42 = real_v42
check('then gets the migrated database', (len(waiting), waiting[0] is opened[0] if waiting and opened else None),
      (1, True))
check('once it is committed, nothing is said', (state(), within(5, said), within(5, asked).get('migrating')),
      (None, None, None))
check('and the database is at the new schema', schema(path), SCHEMA_VERSION)

# ------------------------------------------------------------- when it fails
path = library('failed')
calls = []


def failing_v42(cursor, db_path, progress=None):
    calls.append(db_path)
    raise RuntimeError('a made-up failure')


migrations._migrate_to_v42 = failing_v42
try:
    for _ in range(3):
        try:
            database.get_models_db()
            raised = None
        except Exception as e:
            raised = str(e)
finally:
    migrations._migrate_to_v42 = real_v42
failed = state()
check('a failed migration is said, with its error',
      (failed.get('from'), failed.get('to'), 'a made-up failure' in str(failed.get('error')))
      if isinstance(failed, dict) else failed, (OLD, SCHEMA_VERSION, True))
check('the route says it too, for the page to stop asking',
      'a made-up failure' in str((within(5, asked).get('migrating') or {}).get('error')), True)
check('every later open says the failure again', 'a made-up failure' in str(raised), True)
check('and runs it once, not once a request, each with a backup of its own', len(calls), 1)
check('the database is as it was', schema(path), OLD)

# ---------------------------------------------- startup, the Civitai Browser alone
path = library('startup')
for key in ('model_manager_queue_enabled', 'model_manager_record_generations', 'model_manager_gallery_tab',
            'model_manager_model_manager_enabled'):
    setattr(opts, key, False)
opts.model_manager_civitai_browser_enabled = True
started = []
real = (api.runner.recover, api.prompt_levels.start_in_background, api.update_check.start_in_background)
api.runner.recover = lambda: started.append(('recover', schema(path)))
api.prompt_levels.start_in_background = lambda: started.append(('restamp', schema(path)))
api.update_check.start_in_background = lambda: started.append(('update check', None))
try:
    api.on_app_started(None, FastAPI())
    migrated = until(20, lambda: len(started) == 3)
finally:
    api.runner.recover, api.prompt_levels.start_in_background, api.update_check.start_in_background = real
check('startup migrates the database with only the Civitai Browser on',
      (migrated, schema(path), state()), (True, SCHEMA_VERSION, None))
check('and its other work starts once the database is migrated',
      started, [('update check', None), ('restamp', SCHEMA_VERSION), ('recover', SCHEMA_VERSION)])

database._db_instance = None
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
