"""
A sidecar that names no version is no Civitai data (#131).

Other tools leave `{"error": "Model not found"}` beside a file, or a stub such
as `{"id": 5, "name": "x"}`. The scan took any sidecar that read as JSON for
an identification: the row was flagged, a sync skipped it as already synced,
and the flag could never come down. A stub with an id also wrote its name over
that model's, and tied the file to it - which a metadata sync then filed as
the model's newest version.

What a row is identified by is its Civitai version id: a sidecar without one
is read as no sidecar, a row without one is never flagged, and a scan puts
right what an earlier one wrote.
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
from model_manager.scan_service import ScanService       # noqa: E402
from model_manager.sync_service import SyncService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'stub_sidecar')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
models_dir = facts['models_dir']
scan = ScanService()


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

# ----------------------------------------------------------- what a scan reads
for label, path in (('an error left by another tool', ERROR),
                    ('a stub with a model id', STUB),
                    ('versions without an id', NO_IDS)):
    civitai_model, version = scan.extract_metadata(path)
    check('%s is no Civitai data' % label, version['has_civitai_data'], False)
    check('%s gives no model to store' % label, civitai_model, None)
    check('%s ties the file to no model' % label, version.get('model_id'), None)

civitai_model, version = scan.extract_metadata(REAL)
check('a sidecar naming a version is still Civitai data',
      (version['has_civitai_data'], version['id'], civitai_model['id']), (True, 55, 5))

# ------------------------------------------------------------- the whole scan
progress = scan.scan_models(directories=[models_dir])
check('the scan completes', progress.is_complete, True)
for label, path in (('the error', ERROR), ('the stub', STUB), ('versions without an id', NO_IDS)):
    stored = row(path)
    check('%s is stored as not identified' % label,
          (stored['has_civitai_data'], stored['model_id']), (0, None))
check('the real sidecar is stored as identified',
      (row(REAL)['has_civitai_data'], row(REAL)['id']), (1, 55))
check("the stub does not write its name over the model's",
      db.get_civitai_model(5)['name'], 'The Real Name')

# What an earlier scan wrote - a stub's row flagged and tied to its model -
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

# Identified stays identified: a scan that finds no sidecar beside a file a
# sync identified has not learned it is unknown.
os.remove(os.path.splitext(REAL)[0] + '.civitai.info')
scan.scan_models(directories=[models_dir])
check('an identified row keeps its flag and its model when its sidecar goes',
      (row(REAL)['has_civitai_data'], row(REAL)['id'], row(REAL)['model_id']), (1, 55, 5))

# -------------------------------------------------- what a sync then does
class Client:
    """Civitai, knowing no file, and saying what it was asked."""

    def __init__(self):
        self.asked = []
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def get_model_by_hash(self, value):
        self.asked.append(('by_hash', value))
        raise CivitaiNotFoundError('no such hash')

    def close(self):
        pass


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
