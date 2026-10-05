"""
A sidecar that names no version is no Civitai data (#131).

Other tools leave `{"error": "Model not found"}` beside a file, or a stub such
as `{"id": 5, "name": "x"}`. The scan took any sidecar that read as JSON for
an identification: the row was flagged, a sync skipped it as already synced,
and the flag could never come down. A stub with an id also wrote its name over
that model's, and tied the file to it - which a metadata sync then filed as
the model's newest version.

What a row is identified by is its Civitai version id: a sidecar without one
is read as no sidecar, and a row without one is never flagged. Since 0.48 a
sidecar is read only by a sync, for a model Civitai no longer has
(hash_trust_test.py) - and a stub is no more an identification there.
"""
import io
import json
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

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.db.library import LIBRARY             # noqa: E402
from model_manager.civitai import (                      # noqa: E402
    CivitaiNotFoundError, TokenBucketRateLimiter,
)
from model_manager.sync_service import SyncService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'stub_sidecar')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
models_dir = facts['models_dir']


def model_file(name, sidecar):
    path = os.path.join(models_dir, 'Lora', name)
    io.open(path, 'wb').write(name.encode('utf-8') * 16)
    fixtures.sidecar(path, sidecar)
    return path


def row(path):
    raw = sqlite3.connect(facts['db_path'])
    raw.row_factory = sqlite3.Row
    found = raw.execute(f'SELECT * FROM {LIBRARY} WHERE file_path = ?', (path,)).fetchone()
    raw.close()
    return found


ERROR = model_file('error_left.safetensors', {'error': 'Model not found'})
STUB = model_file('stub_left.safetensors', {'id': 5, 'name': 'x'})
NO_IDS = model_file('no_ids.safetensors', {'id': 6, 'name': 'y', 'modelVersions': [{'name': 'v'}]})
REAL = model_file('real.safetensors', {
    'id': 5, 'name': 'The Real Name', 'type': 'LORA',
    'modelVersions': [{'id': 55, 'name': 'v1',
                       'files': [{'name': 'real.safetensors'}]}]})

# ------------------------------------------------- what a sync reads of them
class Client:
    """Civitai, knowing no file and no model, and saying what it was asked."""

    def __init__(self):
        self.asked = []
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def get_model_by_hash(self, value):
        self.asked.append(('by_hash', value))
        raise CivitaiNotFoundError('no such hash')

    def get_model(self, model_id):
        self.asked.append(('model', model_id))
        return None

    def close(self):
        pass


for path in (ERROR, STUB, NO_IDS, REAL):
    db.insert_missing_versions([{'file_path': path, 'file_name': os.path.basename(path)}])

# The real one first: its model is then the one a stub could write over.
client = Client()
SyncService(client=client).sync_model(REAL)
check('a sidecar naming a version, for a model Civitai does not have, files the file',
      (row(REAL)['has_civitai_data'], row(REAL)['id'], row(REAL)['model_id']), (1, 55, 5))
for label, path in (('an error left by another tool', ERROR),
                    ('a stub with a model id', STUB),
                    ('versions without an id', NO_IDS)):
    client = Client()
    result = SyncService(client=client).sync_model(path)
    stored = row(path)
    check('%s is no Civitai data' % label, (stored['has_civitai_data'], stored['model_id']), (0, None))
    check('%s is not asked about: Civitai is asked about no model' % label,
          [a for a in client.asked if a[0] == 'model'], [])
    check('%s leaves the file looked up, and not on Civitai' % label,
          (result.not_found, bool(stored['civitai_lookup_failed_at'])), (True, True))
check("the stub does not write its name over the model's",
      db.get_civitai_model(5)['name'], 'The Real Name')

# What Scan Disk once wrote - a stub's row flagged and tied to its model -
# a file without a version cannot hold since v32: the migration leaves it
# with none (version_files_test.py).

# The rule is the upsert's, whoever writes: no version id, no identification.
db.upsert_version({'file_path': STUB, 'file_name': 'stub_left.safetensors',
                   'has_civitai_data': True, 'model_id': 5})
check('no writer can flag a row without a version id', row(STUB)['has_civitai_data'], 0)
db.upsert_version({'file_path': os.path.join(models_dir, 'Lora', 'new_row.safetensors'),
                   'file_name': 'new_row.safetensors', 'has_civitai_data': True})
check('nor insert one flagged',
      row(os.path.join(models_dir, 'Lora', 'new_row.safetensors'))['has_civitai_data'], 0)

# Identified stays identified: a walk past a file whose sidecar has gone has
# not learned it is unknown.
os.remove(os.path.splitext(REAL)[0] + '.civitai.info')
from modules import paths                                # noqa: E402  (webui_stub's)
paths.models_path = models_dir
SyncService(client=Client()).walk_library()
paths.models_path = ''
check('an identified row keeps its flag and its model when its sidecar goes',
      (row(REAL)['has_civitai_data'], row(REAL)['id'], row(REAL)['model_id']), (1, 55, 5))

# -------------------------------------------------- what a sync then does
# Asked about above; as if never asked, so only its sidecar could make a sync skip it.
db.set_lookup_failed(STUB, failed=False)
client = Client()
result = SyncService(client=client).sync_model(STUB)
check('a sync does not skip a file whose sidecar named no version', result.skipped, False)
check('it looks the file up', bool(client.asked) and client.asked[0][0], 'by_hash')

# A metadata sync refreshes what has a version id: a row tied to a model
# without one would be filed as that model's newest version.
linked = [v['file_path'] for v in db.get_linked_versions()]
check('a row with no version id is not refreshed by a metadata sync', NO_IDS in linked, False)
check('one with a version id is', REAL in linked, True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
