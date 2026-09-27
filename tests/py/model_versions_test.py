"""
Every version of a model, kept so the details panel can show the ones not
downloaded without asking Civitai.

Civitai's list comes in two ways, and they are not equally fresh. A sync
brings the list as Civitai has it now, and replaces what is held: a version
deleted there is gone. A sidecar is as old as its file's last sync, so a scan
only adds what it lists, and once Civitai's own list is held adds nothing -
an old sidecar would bring a deleted version back, and its Download would
fail.
"""
import json
import os
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

WORK = os.path.join(TESTS, 'work', 'model_versions_test')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db


def version(vid, index=None, published='2025-01-01', **extra):
    v = {'id': vid, 'name': 'v%d' % vid, 'baseModel': 'SDXL 1.0', 'publishedAt': published,
         'trainedWords': ['w%d' % vid], 'images': [{'url': 'http://x/%d.jpg' % vid}] * 3,
         'downloadUrl': 'http://x/dl/%d' % vid, 'stats': {'downloadCount': 1},
         'files': [{'id': vid * 10, 'name': 'f%d.safetensors' % vid, 'sizeKB': 1024.5, 'primary': True,
                    'type': 'Model', 'metadata': {'format': 'SafeTensor', 'size': 'pruned', 'fp': 'fp16'},
                    'hashes': {'SHA256': 'AB'}, 'downloadUrl': 'http://x/f', 'pickleScanResult': 'Success'}]}
    if index is not None:
        v['index'] = index
    v.update(extra)
    return v


def model(mid, versions):
    return {'id': mid, 'name': 'Model %d' % mid, 'type': 'LORA', 'versions': versions}


def ids(mid):
    listed, _ = db.get_civitai_versions(mid)
    return [v['id'] for v in listed or []]


# ------------------------------------------------------------------ a sync
M = 5550001
paid = version(3, index=0, published='2025-03-01', paidAccess={'permanent': False, 'endsAt': '2099-01-01'})
# As a sync hands it on: the file's own version moved to the front.
db.upsert_civitai_model(model(M, [version(2, index=1, published='2025-02-01'), paid,
                                  version(1, index=2, published='2025-01-01')]), from_civitai=True)
listed, synced_at = db.get_civitai_versions(M)
check('1. a sync keeps every version, in Civitai\'s order rather than the sync\'s', ids(M), [3, 2, 1])
check('   and says when Civitai listed them', bool(synced_at), True)
check('   what a version needs, and no more: no images, no download URLs, no hashes',
      (sorted(listed[1]), sorted(listed[1]['files'][0])),
      (['baseModel', 'files', 'id', 'index', 'name', 'publishedAt', 'trainedWords'],
       ['id', 'metadata', 'name', 'primary', 'sizeKB', 'type']))
check('   a paywall is kept, to be read the way the Civitai Browser reads it',
      listed[0]['paidAccess'], {'permanent': False, 'endsAt': '2099-01-01'})

db.upsert_civitai_model({'id': M, 'name': 'Model %d' % M, 'description': 'from a thin sidecar'})
check('2. an update that says nothing about versions keeps them', ids(M), [3, 2, 1])

db.upsert_civitai_model(model(M, [version(1, index=5)]))
check('3. once Civitai\'s list is held, a sidecar adds nothing - it would bring back a deleted version',
      ids(M), [3, 2, 1])
db.upsert_civitai_model(model(M, [version(4, index=9)]))
check('   not even one Civitai does not list', ids(M), [3, 2, 1])

db.upsert_civitai_model(model(M, [version(4, index=0, published='2025-04-01'), version(1, index=1)]),
                        from_civitai=True)
check('4. the next sync replaces the list: 4 is new, 3 and 2 were deleted', ids(M), [4, 1])

# ------------------------------------------------------------- sidecars only
S = 5550002
db.upsert_civitai_model(model(S, [version(21, index=0, published='2025-02-01'),
                                  version(20, index=1, published='2025-01-01')]))
listed, synced_at = db.get_civitai_versions(S)
check('5. before any sync, a sidecar\'s list is kept', ids(S), [21, 20])
check('   with no date: nobody asked Civitai', synced_at, None)
db.upsert_civitai_model(model(S, [version(20, index=0, published='2025-01-01')]))
check('6. a sidecar that lists fewer removes nothing', ids(S), [21, 20])
db.upsert_civitai_model(model(S, [version(22, index=0, published='2025-03-01'),
                                  version(20, index=1, published='2025-01-01')]))
check('7. and one that lists more adds them, newest first', ids(S), [22, 21, 20])

# ------------------------------------------------ the scan and the sync pass it
from model_manager.scan_service import ScanService, as_model_payload   # noqa: E402
path = facts['linked_paths'][0]
local = db.get_version(path)
payload = {'id': local['model_id'], 'name': 'Linked', 'type': 'LORA',
           'modelVersions': [version(local['id'], index=1), version(990001, index=0, published='2026-01-01')]}
extracted = ScanService()._extract_civitai_metadata(as_model_payload(payload),
                                                    {'file_name': os.path.basename(path)}, path)
check('8. a scan hands on the sidecar\'s versions', [v['id'] for v in extracted.get('versions') or []],
      [local['id'], 990001])

from model_manager.sync_service import SyncService   # noqa: E402
from model_manager.hashing import HashResult          # noqa: E402
error = SyncService()._update_database(path, json.loads(json.dumps(payload)),
                                       HashResult.from_stored(local['file_hashes']))
check('   and a sync stores Civitai\'s', (error, ids(local['model_id'])), (None, [990001, local['id']]))

# ------------------------------------------------------------------ the endpoint
try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; the endpoint checks need the WebUI\'s python')
    FastAPI = None

if FastAPI:
    import model_manager.civitai as civitai_pkg                   # noqa: E402
    from model_manager.api import setup_api                       # noqa: E402

    asked = []
    class NoCivitai:
        def __init__(self, *a, **k):
            asked.append('constructed')
        @classmethod
        def from_settings(cls, *a, **k):
            asked.append('from_settings')
            return cls()
        def __getattr__(self, name):
            asked.append(name)
            raise AssertionError('Civitai asked: ' + name)
    import model_manager.api.models as models_api                 # noqa: E402
    models_api.CivitaiClient = NoCivitai

    app = FastAPI()
    setup_api(app)
    client = TestClient(app)

    answer = client.get('/model-manager/models/versions', params={'model_id': local['model_id']}).json()
    listed = answer.get('civitai_versions') or []
    check('9. the endpoint lists Civitai\'s versions, the local one marked',
          [(v['id'], v['local']) for v in listed], [(990001, False), (local['id'], True)])
    check('   with the local versions as before', [v['file_path'] for v in answer.get('versions', [])],
          [v['file_path'] for v in db.get_versions_for_model(local['model_id'])])
    check('   and when Civitai listed them', bool(answer.get('versions_synced_at')), True)

    # A library synced before the list was kept: the column is empty, and the
    # sidecar beside the file has it.
    other = facts['linked_paths'][-1]
    lv = db.get_version(other)
    with db._cursor() as cursor:
        cursor.execute('UPDATE civitai_models SET versions = NULL, versions_synced_at = NULL WHERE id = ?',
                       (lv['model_id'],))
    fixtures.sidecar(other, {'id': lv['model_id'], 'name': 'Old', 'modelVersions': [
        version(lv['id'], index=0), version(880001, index=1, paidAccess={'permanent': True})]})
    answer = client.get('/model-manager/models/versions', params={'model_id': lv['model_id']}).json()
    listed = answer.get('civitai_versions') or []
    check('10. with nothing held, the sidecar is read once and kept',
          ([v['id'] for v in listed], ids(lv['model_id'])), ([lv['id'], 880001], [lv['id'], 880001]))
    check('    paid_access is worked out as the Civitai Browser does',
          [v['paid_access'] for v in listed], [None, {'permanent': True, 'ends_at': None}])
    check('    and says it did not come from Civitai', answer.get('versions_synced_at'), None)
    check('11. Civitai was never asked', asked, [])

    none = client.get('/model-manager/models/versions', params={'model_id': 123456789}).json()
    check('12. a model nothing is known about has no versions, and no error',
          (none.get('success'), none.get('civitai_versions')), (True, []))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
