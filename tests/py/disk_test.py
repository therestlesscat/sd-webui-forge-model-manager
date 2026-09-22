"""
A sync's view of the disk: record what is there, forget what is not.

The dangerous half of this is the diff. It is only sound when the whole disk
was walked, so most of what follows is about the cases where it must NOT fire:
a target set, an explicit path list, a metadata sync of any scope.
"""

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

WORK = os.path.join(TESTS, 'work', 'disk_test')
import io
import os
import shutil
import sqlite3
import sys


FAKE = os.path.join(WORK, 'newcomers')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# A library built for this test, so every number below is one this file
# decided rather than one that happened to be true of somebody's models.
db, facts = fixtures.build(WORK)
DB = facts['db_path']
os.makedirs(FAKE, exist_ok=True)

from model_manager.db import ModelsDatabase
import model_manager.db.database as dbmod
import model_manager.sync_service as ss

dbmod._db_instance = db
ss.write_civitai_info = lambda path, payload: True


def rows():
    raw = sqlite3.connect(DB)
    out = {r[0] for r in raw.execute(
        'SELECT file_path FROM model_versions WHERE file_path IS NOT NULL')}
    raw.close()
    return out


svc = ss.SyncService.__new__(ss.SyncService)

# --- recording ---------------------------------------------------------------
before = rows()
newcomers = []
for i in range(3):
    path = os.path.join(FAKE, 'brand_new_%d.safetensors' % i)
    io.open(path, 'wb').write(b'x' * (1000 + i))
    newcomers.append(path)

added = svc._record_found_files(newcomers)
check('every new file gets a row', added, 3)
check('and they are all there', set(newcomers) <= rows())

raw = sqlite3.connect(DB)
raw.row_factory = sqlite3.Row
row = raw.execute('SELECT * FROM model_versions WHERE file_path = ?', (newcomers[0],)).fetchone()
check('the row carries the file size', row['file_size'], 1000)
check('and its name', row['file_name'], 'brand_new_0.safetensors')
check('and is marked as having no Civitai data', row['has_civitai_data'], 0)
check('and is visible to the grid rather than Unknown', row['nsfw_level'], 1)

# recording again must not duplicate, nor disturb an identified row
identified = raw.execute(
    'SELECT file_path, id, model_id FROM model_versions'
    ' WHERE model_id IS NOT NULL LIMIT 1').fetchone()
raw.close()

check('recording is idempotent', svc._record_found_files(newcomers), 0)
added_again = svc._record_found_files([identified['file_path']])
check('an identified file is not re-inserted', added_again, 0)

raw = sqlite3.connect(DB)
raw.row_factory = sqlite3.Row
after = raw.execute('SELECT id, model_id FROM model_versions WHERE file_path = ?',
                    (identified['file_path'],)).fetchone()
raw.close()
check('and keeps its Civitai ids',
      (after['id'], after['model_id']), (identified['id'], identified['model_id']))

# --- forgetting --------------------------------------------------------------
everything = sorted(rows())
check('a walk that finds everything removes nothing',
      svc._forget_missing_files(everything), 0)

kept = [p for p in everything if p not in newcomers]
removed = svc._forget_missing_files(kept)
check('a walk that misses three files removes three', removed, 3)
check('and they are gone', rows() & set(newcomers), set())

# A walk that found nothing means a bad directory setting or an unmounted
# drive, not a library that was deleted.
check('a walk that found nothing deletes nothing', svc._forget_missing_files([]), 0)
# The newcomers were removed just above, so this is the fixture again.
check('and the library is untouched', len(rows()), fixtures.VERSIONS)

# --- the guard ---------------------------------------------------------------
# This is the one that matters: the diff must never run on a partial view.
import inspect
src = inspect.getsource(ss.SyncService.sync_all)
check('the diff is gated on having walked', 'if walked:' in src)
check('and runs before the targets narrow anything',
      src.index('_forget_missing_files') < src.index('_filter_by_identification'))

calls = [line.strip() for line in src.splitlines() if '_forget_missing_files' in line]
check('there is exactly one call to it', len(calls), 1)


class Stub:
    def get_models_by_ids(self, ids):
        return {}
    def get_model_version_by_hash(self, *a, **k):
        return None
    def close(self):
        pass


# an explicit path list is not a walk, so nothing may be forgotten. Use a tiny
# real file, so the hashing this triggers is instant.
tiny = os.path.join(FAKE, 'tiny.safetensors')
io.open(tiny, 'wb').write(b'y' * 64)
svc._record_found_files([tiny])
survivors = len(rows())
ss.SyncService(client=Stub()).sync_all(model_paths=[tiny], targets='all')
check('an explicit path list deletes nothing', len(rows()), survivors)

# A metadata sync is not a walk either - but it does delete what it can prove
# is gone, which is the row it was about to refresh and could not find.
raw = sqlite3.connect(DB)
raw.row_factory = sqlite3.Row
linked = raw.execute(
    "SELECT file_path FROM model_versions"
    " WHERE model_id IS NOT NULL AND file_path LIKE 'F:%' LIMIT 1").fetchone()['file_path']
vanished = os.path.join(FAKE, 'deleted_since.safetensors')
raw.execute('UPDATE model_versions SET file_path = ? WHERE file_path = ?', (vanished, linked))
raw.commit()
moved = raw.execute('SELECT COUNT(*) FROM model_versions WHERE file_path = ?',
                    (vanished,)).fetchone()[0]
raw.close()
check('a linked row now points at a file that is not there', moved, 1)

before_meta = len(rows())
progress = ss.SyncService(client=Stub()).sync_metadata(include_images=False)
check('a metadata sync forgets the file it could not find', progress.removed, 1)
check('and says so rather than calling it skipped',
      any('no longer on disk' in m for m in progress.error_messages))
check('the vanished row is gone', vanished in rows(), False)
check('and it took exactly that one row', len(rows()), before_meta - 1)

print('%d rows in the library at the end' % len(rows()))
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
