"""Metadata sync: batching, hash reuse, payload ordering, and column safety."""

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

WORK = os.path.join(TESTS, 'work', 'meta_test')
import io
import json
import os
import shutil
import sqlite3
import sys



fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))

# ----------------------------------------------------------- HashResult reuse
from model_manager.hashing import HashResult
from model_manager.sync_service import SyncService

stored = {"sha256": "AA" * 32, "autov2": "AABBCCDDEE", "crc32": "12345678",
          "blake3": "BB" * 32, "autov1": "DEADBEEF", "tensor_sha256": "CC" * 32,
          "autov3": "112233445566"}
h = HashResult.from_stored(stored)
check('from_stored keeps sha256', h.sha256, stored['sha256'])
check('from_stored keeps autov3', h.autov3, stored['autov3'])
check('from_stored keeps blake3', h.blake3, stored['blake3'])
check('from_stored on empty dict', HashResult.from_stored({}).sha256, None)
check('from_stored on None', HashResult.from_stored(None).sha256, None)
check('from_stored ignores junk keys', HashResult.from_stored({"nope": 1}).sha256, None)

# A round trip through what the DB actually stores must survive.
svc = SyncService.__new__(SyncService)
check('round trip through _hashes_to_dict', svc._hashes_to_dict(h), stored)

# ------------------------------------------------- payload version reordering
order = SyncService._payload_with_version_first
payload = {"id": 1, "modelVersions": [{"id": 10}, {"id": 20}, {"id": 30}]}
check('matched version moves to front',
      [v["id"] for v in order(dict(payload), 20)["modelVersions"]], [20, 10, 30])
check('already first stays first',
      [v["id"] for v in order(dict(payload), 10)["modelVersions"]], [10, 20, 30])
check('unknown version leaves order alone',
      [v["id"] for v in order(dict(payload), 99)["modelVersions"]], [10, 20, 30])
check('no version id leaves order alone',
      [v["id"] for v in order(dict(payload), None)["modelVersions"]], [10, 20, 30])
check('empty payload survives', order({}, 5), {})
check('no versions key survives', order({"id": 1}, 5), {"id": 1})

# Two local files sharing one model must each get their own ordering.
shared = {"id": 7, "modelVersions": [{"id": 100}, {"id": 200}]}
a = order(json.loads(json.dumps(shared)), 200)
b = order(json.loads(json.dumps(shared)), 100)
check('per-file copies do not interfere',
      ([v["id"] for v in a["modelVersions"]], [v["id"] for v in b["modelVersions"]]),
      ([200, 100], [100, 200]))

# ------------------------------------------------- get_linked_versions on real data
if True:
    # A library built for this test, so every number below is one this file
    # decided rather than one that happened to be true of somebody's models.
    db, facts = fixtures.build(WORK)
    DB = facts['db_path']

    linked = db.get_linked_versions()
    raw = sqlite3.connect(DB)
    total = raw.execute('SELECT COUNT(*) FROM model_versions').fetchone()[0]
    with_model = raw.execute(
        'SELECT COUNT(*) FROM model_versions WHERE model_id IS NOT NULL AND file_path IS NOT NULL'
    ).fetchone()[0]

    print('  versions in library        : %d' % total)
    print('  linked to a Civitai model  : %d' % len(linked))
    check('get_linked_versions matches the query', len(linked), with_model)
    check('every row has a model_id', all(v['model_id'] for v in linked))
    check('every row has a path', all(v['file_path'] for v in linked))
    check('hashes come back as a dict', all(isinstance(v['file_hashes'], dict) for v in linked))

    with_sha = [v for v in linked if v['file_hashes'].get('sha256')]
    print('  with a stored sha256       : %d  <- these need no re-hashing' % len(with_sha))

    # How many rows happen to carry a hash is a fact about the library, not
    # about the code - files linked by a scan or a sidecar never had one. What
    # must hold is that a sync does not throw away the hashes that do exist:
    # the reuse path a metadata sync takes for each row is from_stored ->
    # _hashes_to_dict -> upsert_version, so walk it over the real rows.
    reuse = SyncService.__new__(SyncService)
    lost = [v['file_path'] for v in with_sha
            if not reuse._hashes_to_dict(
                HashResult.from_stored(v['file_hashes'])).get('sha256')]
    check('the sync reuse path keeps every stored sha256', lost, [])

    changed = [v['file_path'] for v in with_sha
               if reuse._hashes_to_dict(HashResult.from_stored(v['file_hashes']))['sha256']
               != v['file_hashes']['sha256']]
    check('and does not alter them', changed, [])

    # Every hash kind stored anywhere must survive the same trip, or a sync
    # would quietly drop a column Civitai gave us.
    kinds = {k for v in linked for k in v['file_hashes']}
    dropped = sorted(k for k in kinds
                     if any(k not in reuse._hashes_to_dict(HashResult.from_stored(v['file_hashes']))
                            for v in linked if v['file_hashes'].get(k)))
    print('  hash kinds in the library  : %s' % ', '.join(sorted(kinds)))
    check('no hash kind is dropped on the way back', dropped, [])

    distinct = {v['model_id'] for v in linked}
    batches = (len(distinct) + 99) // 100
    print('  distinct Civitai models    : %d' % len(distinct))
    print('  API calls, batched by 100  : %d   (one per model would be %d)'
          % (batches, len(distinct)))
    check('batching is a real saving', batches < len(distinct) / 10)

    # The columns a metadata sync must never touch.
    before = raw.execute("""
        SELECT id, downloaded_at, next_images_cursor, images_sync_last_date
        FROM model_versions WHERE downloaded_at IS NOT NULL LIMIT 5
    """).fetchall()
    print('  rows with downloaded_at    : %d sampled' % len(before))
    check('upsert_version leaves downloaded_at out of its SET list',
          'downloaded_at = excluded' not in io.open(
              'model_manager/db/models_ops.py', encoding='utf-8').read())
    check('upsert_version leaves the image cursor out of its SET list',
          'next_images_cursor = excluded' not in io.open(
              'model_manager/db/models_ops.py', encoding='utf-8').read())
    raw.close()

# ---------------------------------------------------- batching call shape
from model_manager.civitai import CivitaiClient

sent = []
class Spy(CivitaiClient):
    def _request(self, method, endpoint, params=None, absolute_url=None):
        sent.append((endpoint, params))
        ids = [int(x) for x in params['ids'].split(',')]
        return {"items": [{"id": i, "name": "m%d" % i} for i in ids if i != 999]}

c = Spy(None)
res = c.get_models_by_ids(list(range(1, 251)))
check('250 ids become 3 calls', len(sent), 3)
check('first batch is 100 ids', len(sent[0][1]['ids'].split(',')), 100)
check('last batch is the remainder', len(sent[2][1]['ids'].split(',')), 50)
check('limit matches the batch size', sent[0][1]['limit'], 100)
check('result is keyed by id', res[7]['name'], 'm7')
check('all ids returned', len(res), 250)

sent.clear()
res = c.get_models_by_ids([5, 5, 5, 999, 6])
check('duplicates are collapsed', sent[0][1]['ids'], '5,999,6')
check('an id Civitai drops is simply absent', 999 in res, False)
check('the others still come back', sorted(res), [5, 6])

sent.clear()
check('no ids means no calls', c.get_models_by_ids([]), {})
check('really no calls', len(sent), 0)
sent.clear()
c.get_models_by_ids([0, None, 3])
check('falsy ids are dropped', sent[0][1]['ids'], '3')
c.close()

print()
if fails:
    print('\n'.join('FAIL ' + f for f in fails))
    print('%d failure(s)' % len(fails))
    sys.exit(1)
print('All checks passed.')
