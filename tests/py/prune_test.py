"""
Every sync, download and delete clears what no file names any more (#200).

prune_orphans takes every version no file points to, the images of versions
gone, and every model with no version left, unless bookmarked. It ran only
after the walk - a sync from the dialog of the whole library - so a file
identified again as another model, or deleted, left its old version, model
and gallery behind until then. And a sync saved a model's row and then its
version's in two transactions: a cleanup between the two would take the new
model, as an orphan.

What is checked: a sync of some files, a model's Sync button and a delete
each clear what they left; a version another file still names, and a
bookmarked model, are kept; the walk still clears; and a model and its
version are saved as one, or not at all.
"""
import io
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

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.sync_service as sync_module         # noqa: E402
from modules import paths                                # noqa: E402  (webui_stub's)
from model_manager.api import setup_api                  # noqa: E402
from model_manager.architecture import Architecture     # noqa: E402
from model_manager.civitai import TokenBucketRateLimiter  # noqa: E402
from model_manager.sync_service import SyncService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'prune')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
models = facts['models_dir']
paths.models_path = models
sync_module.identify = lambda path: Architecture(None, None, False, False, 'LORA', 'read for the test')


class Client:
    """Civitai, answering by SHA-256 what the test set."""

    def __init__(self):
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def get_model_by_hash(self, value):
        return KNOWN.get(value.upper(), (None, None))[0]

    def get_model(self, model_id):
        return MODELS.get(model_id)

    def get_models_by_ids(self, ids):
        return {i: MODELS[i] for i in ids if i in MODELS}

    def get_model_images(self, version_id, cursor=None, limit=None):
        return {'items': [], 'metadata': {}}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def get_checkpoint_types(self, ids):
        return {}


KNOWN, MODELS = {}, {}      # sha256 -> (version payload, model id); model id -> model payload
sync_module.CivitaiClient = type('Stub', (), {'from_settings': staticmethod(Client)})


def write(name, fill, size=64):
    path = os.path.join(models, 'Lora', name)
    io.open(path, 'wb').write(fill * size)
    return path


def known_as(path, model_id, version_id, name):
    """Civitai knows the file's bytes as this model and version."""
    sha = SyncService(client=Client()).calculate_hashes(path).sha256
    model = {'id': model_id, 'name': name, 'type': 'LORA', 'nsfwLevel': 1,
             'modelVersions': [{'id': version_id, 'name': 'v1', 'nsfwLevel': 1, 'baseModel': 'SDXL 1.0',
                                'images': [], 'files': [{'id': version_id * 10, 'name': os.path.basename(path)}]}]}
    MODELS[model_id] = model
    KNOWN[sha.upper()] = (dict(model['modelVersions'][0], modelId=model_id), model_id)


def identify(path, model_id, version_id, name):
    known_as(path, model_id, version_id, name)
    db.insert_missing_versions([{'file_path': path, 'file_name': os.path.basename(path)}])
    SyncService(client=Client()).sync_model(path, force=True)
    db.store_images(version_id, page=1, images=[fixtures._image(version_id * 100 + n, 1) for n in range(2)])


def held(model_id, version_id):
    """Whether the version row, the model row and the version's images are still there."""
    with sqlite3.connect(facts['db_path']) as c:
        version = c.execute('SELECT COUNT(*) FROM versions WHERE id = ?', (version_id,)).fetchone()[0]
        model = c.execute('SELECT COUNT(*) FROM models WHERE id = ?', (model_id,)).fetchone()[0]
        images = c.execute('SELECT COUNT(*) FROM images WHERE version_id = ?', (version_id,)).fetchone()[0]
    return bool(version), bool(model), images


app = FastAPI()
setup_api(app)
http = TestClient(app)

# --------------------------------------------- a sync of some files (#200)
SWAP = write('swap.safetensors', b'a')
identify(SWAP, 7100, 7101, 'Was')
check('a file identified, with its version, model and gallery', held(7100, 7101), (True, True, 2))
write('swap.safetensors', b'b', size=96)
known_as(SWAP, 7200, 7201, 'Now')
SyncService(client=Client()).sync_all(model_paths=[SWAP], force=True)
check('a sync of some files, the file identified again: what it was is cleared',
      held(7100, 7101), (False, False, 0))

# ------------------------------------------------ a model's Sync button
write('swap.safetensors', b'c', size=80)
known_as(SWAP, 7300, 7301, 'Then')
answer = http.post('/model-manager/models/force-sync', data={'model_id': 7200})
check('a model\'s Sync button answers', answer.status_code, 200)
check('and, the file identified again, clears what it was', held(7200, 7201)[:2], (False, False))

# ------------------------------------------------------------ deleting
GONE = write('gone.safetensors', b'g')
identify(GONE, 7400, 7401, 'Gone')
http.post('/model-manager/models/delete', data={'path': GONE})
check('deleting a file clears its version, model and gallery', held(7400, 7401), (False, False, 0))

TWIN_A = write('twin_a.safetensors', b't')
TWIN_B = write('twin_b.safetensors', b't')
identify(TWIN_A, 7500, 7501, 'Twins')
db.insert_missing_versions([{'file_path': TWIN_B, 'file_name': 'twin_b.safetensors'}])
SyncService(client=Client()).sync_model(TWIN_B, force=True)
# Synced, its gallery was fetched afresh - and this Civitai has none: stored again.
db.store_images(7501, page=1, images=[fixtures._image(750100 + n, 1) for n in range(2)])
http.post('/model-manager/models/delete', data={'path': TWIN_A})
check('a version another file still names is kept, with its gallery', held(7500, 7501), (True, True, 2))

KEPT = write('kept.safetensors', b'k')
identify(KEPT, 7600, 7601, 'Kept')
db.set_bookmark(7600, True)
http.post('/model-manager/models/delete', data={'path': KEPT})
check('a bookmarked model is kept', held(7600, 7601)[1], True)
check('its version, no file left, is cleared', held(7600, 7601)[0], False)

# ------------------------------------------------------- the walk, still
with sqlite3.connect(facts['db_path']) as c:
    c.execute("INSERT INTO models (id, name) VALUES (7700, 'Orphan')")
    c.execute("INSERT INTO versions (id, model_id) VALUES (7701, 7700)")
SyncService(client=Client()).walk_library()
check('the walk still clears what no file names', held(7700, 7701)[:2], (False, False))

# ------------------------------------------- a model and its version, as one
save = getattr(db, 'upsert_identified', None)
model_row = {'id': 7800, 'name': 'Half saved', 'type': 'LORA'}
version_row = {'id': 7801, 'model_id': 7800, 'file_path': write('half.safetensors', b'h'),
               'file_name': 'half.safetensors', 'file_hashes': {'sha256': object()}}
try:
    if save:
        save(model_row, version_row)
    else:
        db.upsert_civitai_model(model_row)
        db.upsert_version(version_row)
except Exception:
    pass
check('a model and its version are saved as one: a version that fails leaves no model row',
      held(7800, 7801)[:2], (False, False))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
