"""
The Model Manager's New version badge and filter (#218), from the grid's route.

A card says which versions Civitai lists before every version the library
holds of its model - from the stored list, with when Civitai last gave it -
and whether each is early access or on-site only, from what the last sync
stored. Newer Version: Available lists only those models, by the SQL form of
the same rule (newer_versions_test holds the two forms to each other).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                       # noqa: E402

webui_stub.install()                                    # before model_manager

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'mm_newer')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db

app = FastAPI()
setup_api(app)
client = TestClient(app)


def held_of(model_id):
    with db._cursor() as cursor:
        cursor.execute("SELECT DISTINCT v.id FROM versions v JOIN files f ON f.version_id = v.id "
                       "WHERE v.model_id = ? ORDER BY v.id", (model_id,))
        return [row[0] for row in cursor.fetchall()]


def version(version_id, name, **extra):
    return dict({'id': version_id, 'name': name, 'baseModel': 'SDXL 1.0', 'files': []}, **extra)


# Model A: two versions Civitai lists before the one held - the newest early
# access, the next one on-site only. Model B: the held one is Civitai's first.
A, B = facts['checkpoint_ids'][0], facts['checkpoint_ids'][1]
held_a, held_b = held_of(A)[0], held_of(B)[0]
db.store_civitai_versions(A, [version(990001, 'v3', index=0, earlyAccessDeadline='2099-01-01T00:00:00Z'),
                              version(990002, 'v2', index=1, baseModel='Illustrious'),
                              version(held_a, 'v1', index=2)], from_civitai=True)
db.store_civitai_versions(B, [version(held_b, 'v2', index=0), version(990003, 'v1', index=1)], from_civitai=True)
db.store_version_lookups([{'id': 990002, 'usageControl': 'Generation'}])


def cards(**params):
    r = client.get('/model-manager/models', params=dict(page_size=100, **params))
    body = r.json()
    return {m.get('model_id') or m.get('file_name'): m for m in body.get('models', [])}, body.get('total')


shown, total = cards()
a, b = shown.get(A, {}), shown.get(B, {})
check('a card lists the versions Civitai has before every one held, newest first',
      [v.get('id') for v in a.get('newer_versions') or []], [990001, 990002])
check('each with its name and base model',
      [(v.get('name'), v.get('base_model')) for v in a.get('newer_versions') or []],
      [('v3', 'SDXL 1.0'), ('v2', 'Illustrious')])
check('and what keeps it from a plain download: early access, on-site only',
      [(v.get('paid'), v.get('on_site_only')) for v in a.get('newer_versions') or []],
      [('Early Access', None), (None, True)])
check('with when Civitai last gave the list', bool(a.get('versions_synced_at')), True)
check('a model whose held version is Civitai\'s first has none', b.get('newer_versions'), [])
local_only = [m for key, m in shown.items() if not m.get('model_id')]
check('a file Civitai does not know has none',
      bool(local_only) and all(m.get('newer_versions') == [] for m in local_only), True)

newer, newer_total = cards(newer_version='available')
check('Newer Version: Available lists only the models with a newer version',
      (A in newer, B in newer, any(not m.get('model_id') for m in newer.values())), (True, False, False))
check('and counts them so', newer_total, len(newer))
check('every card it lists has a newer version, by the badge\'s own rule',
      all(m.get('newer_versions') for m in newer.values()), True)
check('anything else for it is no filter', cards(newer_version='')[1], total)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
