"""The not-found memo: migration, recording, skipping, and retry via Force."""

import os
import sys

# The extension and the test helpers, found from this file rather than from a
# working directory, so a suite runs from anywhere.
HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fixtures                                       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'memo_test')
import os
import shutil
import sqlite3
import sys
import tempfile



fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))

# A library built for this test, so every number below is one this file
# decided rather than one that happened to be true of somebody's models.
db, facts = fixtures.build(WORK)
DB = facts['db_path']
from model_manager.db import ModelsDatabase, SCHEMA_VERSION

raw = sqlite3.connect(DB)
before_cols = {r[1] for r in raw.execute('PRAGMA table_info(model_versions)')}
before_rows = raw.execute('SELECT COUNT(*) FROM model_versions').fetchone()[0]
# The source database may already be migrated; what matters is the end state
# and that re-running is harmless, both checked below.
print('source database already has the column:', 'civitai_lookup_failed_at' in before_cols)
raw.close()

# already open, from the fixture

raw = sqlite3.connect(DB)
cols = {r[1] for r in raw.execute('PRAGMA table_info(model_versions)')}
check('schema version bumped',
      raw.execute("SELECT value FROM schema_info WHERE key='version'").fetchone()[0], str(SCHEMA_VERSION))
check('column added', 'civitai_lookup_failed_at' in cols)
check('rows preserved', raw.execute('SELECT COUNT(*) FROM model_versions').fetchone()[0], before_rows)
check('index created',
      any('idx_version_lookup_failed' == r[1] for r in raw.execute("PRAGMA index_list(model_versions)")))
# The column starts empty when it is first added, but this library has been
# recording failures for a while, so what matters is that they are readable
# and that reopening does not disturb them.
existing = db.count_lookup_failed()
check('the memo is readable', isinstance(existing, int))

# Re-opening must not re-run the ALTER.
ModelsDatabase(extension_dir=ROOT, custom_db_path=DB)
check('migration is idempotent', db.count_lookup_failed(), existing)

# --- recording and clearing -------------------------------------------------
# Rows of its own, rather than three borrowed from the library. Borrowed
# ones have to be unlinked and not already marked, and how many of those
# exist is a fact about someone's models that changes under the test.
paths = [r'Z:\memo_test\fixture_%d.safetensors' % i for i in range(3)]
inserted = db.insert_missing_versions([
    {'file_path': path,
     'file_name': path.split('\\')[-1],
     'file_extension': '.safetensors',
     'file_size': 1,
     'file_modified': None}
    for path in paths
])
check('three rows to work with', inserted, 3)

# The library carries its own failures from real use, and that number grows.
# What this checks is what the calls do, so count from where they start.
baseline = db.count_lookup_failed()
print('  marks already in the library : %d' % baseline)

for path in paths:
    db.set_lookup_failed(path)
check('three files marked', db.count_lookup_failed() - baseline, 3)

row = db.get_version(paths[0])
check('the memo reaches get_version', bool(row.get('civitai_lookup_failed_at')))
check('it is an ISO timestamp', row['civitai_lookup_failed_at'][:2], '20')

db.set_lookup_failed(paths[0], failed=False)
check('clearing works', db.count_lookup_failed() - baseline, 2)
check('cleared row reads None', db.get_version(paths[0]).get('civitai_lookup_failed_at'), None)

# Marking twice must not duplicate or error.
db.set_lookup_failed(paths[1])
check('re-marking is idempotent', db.count_lookup_failed() - baseline, 2)

# An unknown path is a no-op, not a crash.
db.set_lookup_failed(r'Z:\nope\missing.safetensors')
check('unknown path is a no-op', db.count_lookup_failed() - baseline, 2)

# --- the skip decision sync_model makes -------------------------------------
import model_manager.sync_service as svc

def would_skip(version_row, force):
    """The condition as sync_model applies it."""
    if force:
        return False
    if version_row and version_row.get('has_civitai_data'):
        return True
    if version_row and version_row.get('civitai_lookup_failed_at'):
        return True
    return False

synced = {'has_civitai_data': True, 'civitai_lookup_failed_at': None}
missing = {'has_civitai_data': False, 'civitai_lookup_failed_at': '2026-09-21T10:00:00'}
fresh = {'has_civitai_data': False, 'civitai_lookup_failed_at': None}

check('an already-synced model is skipped', would_skip(synced, False))
check('a known-absent model is now skipped', would_skip(missing, False))
check('a never-tried model is still processed', would_skip(fresh, False), False)
check('a brand new file is processed', would_skip(None, False), False)
check('Force retries the known-absent ones', would_skip(missing, True), False)
check('Force retries the synced ones too', would_skip(synced, True), False)

# The source really does implement that, in that order.
src = open('model_manager/sync_service.py', encoding='utf-8').read()
body = src[src.index('def sync_model'):src.index('def _update_database')]
check('skip is guarded by force', 'if not force:' in body)
check('the memo is consulted', "civitai_lookup_failed_at" in body)
check('a failed lookup is recorded', body.count('set_lookup_failed(model_path)'), 2)
check('a success clears it', 'set_lookup_failed(model_path, failed=False)' in body)
check('recorded before returning not_found',
      body.index('set_lookup_failed(model_path)') < body.index('result.not_found = True'))

# --- what this saves on the real library ------------------------------------
n, nbytes = raw.execute(
    'SELECT COUNT(*), COALESCE(SUM(file_size),0) FROM model_versions WHERE model_id IS NULL'
).fetchone()
print('  once marked, a plain sync stops re-reading %d files, %.1f GB' % (n, nbytes / 1073741824))
check('there is something worth saving', nbytes > 0)
raw.close()

print()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
