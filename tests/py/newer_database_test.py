"""
A database newer than this copy of the extension knows (#136).

Two WebUIs can share one database. Update one copy, and its migration moves
the database on; the other copy, older, refuses it (_init_db, since v32) -
but said so in the console alone, and every request failed on its own. Now
the server reads the database's schema read-only, never through
ModelsDatabase, and ui-options tells the page, which covers the tabs with a
notice. Startup leaves the database alone.

What is checked: database_state for a newer database, a current one and none
at all; ui-options carrying it; on_app_started not touching the database; and
the file left byte for byte as it was. Throwaway databases under tests/work.
"""
import hashlib
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

WORK = os.path.join(TESTS, 'work', 'newer_database')
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
from model_manager.db import ModelsDatabase, SCHEMA_VERSION  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def made(name, schema):
    """A database file whose schema_info says `schema`, and nothing else."""
    path = os.path.join(WORK, name)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO schema_info VALUES ('version', ?)", (str(schema),))
    conn.commit()
    conn.close()
    return path


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def state():
    read = getattr(database, 'database_state', None)
    return read() if read else 'no database_state'


newer = made('newer.db', SCHEMA_VERSION + 1)
current = made('current.db', SCHEMA_VERSION)
before = digest(newer)

# ----------------------------------------------------------- read, read-only
opts.model_manager_database_path = newer
check('a database at a newer schema is said to be, with both versions and its file',
      state(), {'schema': SCHEMA_VERSION + 1, 'known': SCHEMA_VERSION, 'path': newer})
opts.model_manager_database_path = current
check('one at this copy\'s schema is not', state(), None)
nowhere = os.path.join(WORK, 'not_yet.db')
opts.model_manager_database_path = nowhere
check('no file yet is not, and none is made', (state(), os.path.exists(nowhere)), (None, False))

# ----------------------------------------------------------------- the page
opts.model_manager_database_path = newer
app = FastAPI()
api.setup_api(app)
http = TestClient(app)
answer = http.get('/model-manager/ui-options').json()
check('ui-options tells the page, before any tab starts',
      answer.get('database_newer'), {'schema': SCHEMA_VERSION + 1, 'known': SCHEMA_VERSION, 'path': newer})
opts.model_manager_database_path = current
check('and says nothing of a database this copy knows',
      http.get('/model-manager/ui-options').json().get('database_newer', 'missing'), None)

# ------------------------------------------------------------------ startup
# What startup starts, recorded: none may reach the database, nor Civitai.
opts.model_manager_database_path = newer
opts.model_manager_queue_enabled = True
started = []
real = (api.runner.recover, api.prompt_levels.start_in_background, api.update_check.start_in_background)
api.runner.recover = lambda: started.append('recover')
api.prompt_levels.start_in_background = lambda: started.append('restamp')
api.update_check.start_in_background = lambda: started.append('update check')
try:
    try:
        api.on_app_started(None, FastAPI())
        raised = None
    except Exception as e:
        raised = repr(e)
finally:
    api.runner.recover, api.prompt_levels.start_in_background, api.update_check.start_in_background = real
check('startup with a newer database does not raise', raised, None)
check('and starts nothing that asks it - only the update check, which may say a newer copy is out',
      started, ['update check'])

# ---------------------------------------- every other way in, refused unopened
# Any of the 80 callers of get_models_db - the settings window's file in use,
# its notes - opened it through ModelsDatabase, whose first connection sets
# the journal mode, writing the file, before _init_db refused it.
database._db_instance = None
try:
    database.get_models_db()
    refused_unopened = None
except RuntimeError as e:
    refused_unopened = 'newer than this copy' in str(e)
check('get_models_db refuses it too, as before', refused_unopened, True)
check('without a journal of its own beside it',
      [os.path.exists(newer + suffix) for suffix in ('-wal', '-shm')], [False, False])

# --------------------------------------------------- what must not change
check('all of the above left the newer database byte for byte as it was', digest(newer), before)
# Last: opened through ModelsDatabase, the file's journal mode is set before
# the refusal, which writes its header.
try:
    ModelsDatabase(WORK, newer)
    refused = None
except RuntimeError as e:
    refused = 'newer than this copy' in str(e)
check('opening it through ModelsDatabase still refuses it', refused, True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
