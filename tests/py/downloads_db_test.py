"""
The download queue's storage (#187): db/downloads_ops.py through the
ModelsDatabase facade - and migration v35, on a database at v34.

What is kept is one install's downloads not over, in the list's order: a save
replaces that install's rows, and leaves another's alone. The library's files
of a download are asked by Civitai's file id alone, so a sibling file of the
same version is never taken for it. v35 moves what v34 kept in schema_info - one
JSON list per install - into the table, and forgets Scan Disk's last_scan.
"""
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
from model_manager.db.database import ModelsDatabase, SCHEMA_VERSION   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'downloads_db')
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def asked(db, name, *args):
    """
    A facade method's answer - None where this code has none, the error
    where it raises - so either fails a check, not the suite.
    """
    method = getattr(db, name, None)
    if method is None:
        return None
    try:
        return method(*args)
    except Exception as e:                               # noqa: BLE001
        return repr(e)


db = ModelsDatabase(extension_dir=ROOT, custom_db_path=os.path.join(WORK, 'models.db'))


def row(version_id, partial=None, **more):
    entry = {'version_id': version_id, 'model_id': 42, 'file_id': version_id * 10, 'file_index': None,
             'file_name': 'f_%d.safetensors' % version_id, 'partial_path': partial, 'total_bytes': 100}
    entry.update(more)
    return entry


# ------------------------------------------------------------- keep and read
HERE_INSTALL, OTHER_INSTALL = 'install-here', 'install-other'
asked(db, 'keep_downloads', HERE_INSTALL, [row(3, 'C:\\m\\f_3.safetensors.partial'), row(1), row(2)])
asked(db, 'keep_downloads', OTHER_INSTALL, [row(9)])
check('kept rows come back as kept, in the order given',
      asked(db, 'kept_downloads', HERE_INSTALL),
      [row(3, 'C:\\m\\f_3.safetensors.partial'), row(1), row(2)])
check("another install's are its own", [r['version_id'] for r in asked(db, 'kept_downloads', OTHER_INSTALL) or []], [9])
asked(db, 'keep_downloads', HERE_INSTALL, [row(2), row(4, file_id=None, total_bytes=0)])
check('a save replaces the rows: gone ones go, the order is the new one',
      asked(db, 'kept_downloads', HERE_INSTALL), [row(2), row(4, file_id=None, total_bytes=0)])
check("and leaves another install's alone", [r['version_id'] for r in asked(db, 'kept_downloads', OTHER_INSTALL) or []], [9])
asked(db, 'keep_downloads', HERE_INSTALL, [])
check('nothing to keep leaves no row', asked(db, 'kept_downloads', HERE_INSTALL), [])
with sqlite3.connect(db.db_path) as c:
    try:
        count = c.execute('SELECT COUNT(*) FROM downloads').fetchone()[0]
    except sqlite3.OperationalError as e:
        count = repr(e)
    check('the table holds only what is kept', count, 1)

# ------------------------------------------------------ the library's files
# A version with two files - an fp16 and an fp32 - and a file of another.
with sqlite3.connect(db.db_path) as c:
    c.executemany('INSERT INTO files (file_path, version_id, file_name, civitai_file_id) VALUES (?, ?, ?, ?)',
                  [('C:\\m\\a_fp16.safetensors', 10, 'a_fp16.safetensors', 100),
                   ('C:\\m\\a_fp32.safetensors', 10, 'a_fp32.safetensors', 101),
                   ('C:\\m\\b.safetensors', 11, 'b.safetensors', None)])
check('the very file, by its Civitai id', asked(db, 'held_files', 100), ['C:\\m\\a_fp16.safetensors'])
check('not its sibling', asked(db, 'held_files', 101), ['C:\\m\\a_fp32.safetensors'])
check('a file the library does not have is none', asked(db, 'held_files', 999), [])
check('with no file id, none - not any file of the version', asked(db, 'held_files', None), [])
db.close()

# -------------------------------------------------------------------- v35
OLD = os.path.join(WORK, 'v34.db')
with sqlite3.connect(db.db_path) as c:
    c.execute('VACUUM INTO ?', (OLD,))
LEFT = row(5, 'C:\\m\\f_5.safetensors.partial', total_bytes=50)
with sqlite3.connect(OLD) as c:
    c.execute('DROP TABLE IF EXISTS downloads')
    c.execute("UPDATE schema_info SET value = '34' WHERE key = 'version'")
    c.executemany('INSERT OR REPLACE INTO schema_info (key, value) VALUES (?, ?)', [
        ('downloads:aaa', json.dumps([LEFT, row(6)])),
        ('downloads:bbb', json.dumps([row(7)])),
        ('downloads:bad', 'not json'),
        ('last_scan', '2026-10-04T13:46:19.199537'),
        ('saved_search:model_manager', '{"search": "x"}'),
    ])
ModelsDatabase(extension_dir=ROOT, custom_db_path=OLD).close()
with sqlite3.connect(OLD) as c:
    c.row_factory = sqlite3.Row
    check('v35 brings it to the schema this code expects',
          c.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()[0], str(SCHEMA_VERSION))
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    moved = ([dict(r) for r in c.execute('SELECT * FROM downloads ORDER BY install, position')]
             if 'downloads' in tables else [])
    check("each install's kept downloads become its rows, in their order",
          [(r['install'], r['position'], r['version_id'], r['partial_path'], r['total_bytes']) for r in moved],
          [('aaa', 0, 5, 'C:\\m\\f_5.safetensors.partial', 50), ('aaa', 1, 6, None, 100), ('bbb', 0, 7, None, 100)])
    check('with what each needs to resume', {k: moved[0][k] for k in ('model_id', 'file_id', 'file_index', 'file_name')}
          if moved else None, {'model_id': 42, 'file_id': 50, 'file_index': None, 'file_name': 'f_5.safetensors'})
    keys = sorted(r[0] for r in c.execute('SELECT key FROM schema_info'))
    check('schema_info keeps no download, readable or not, and no last_scan - and keeps the rest',
          [[k for k in keys if k.startswith('downloads:') or k == 'last_scan'],
           'saved_search:model_manager' in keys], [[], True])
    migrate = getattr(migrations, '_migrate_to_v35', None)
    again = 'not run'
    if migrate:
        try:
            migrate(c.cursor())
            again = c.execute('SELECT COUNT(*) FROM downloads').fetchone()[0]
        except Exception as e:                           # noqa: BLE001
            again = repr(e)
    check('v35 runs twice without harm', again, 3)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
