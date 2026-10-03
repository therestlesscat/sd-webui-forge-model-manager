"""
Replacing a gallery's stored images is all or nothing (#73).

A refresh - a sync of a model, Resync Images as was - cleared a version's images, stored the new
ones and recorded the cursor in three steps, each committed on its own: a
failure after the clear, while storing, left the model with no images until
the next sync. They are one transaction now (db.replace_first_page), used by
every place that replaces a gallery.

Here Civitai's answer holds an image the database cannot store, part-way.
"""
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

import model_manager.db.database as dbmod                # noqa: E402
from model_manager.civitai import TokenBucketRateLimiter  # noqa: E402
from model_manager.db import ModelsDatabase              # noqa: E402
from model_manager.sync_service import SyncService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'gallery_replace')
os.makedirs(WORK, exist_ok=True)
for name in os.listdir(WORK):
    os.remove(os.path.join(WORK, name))

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db = ModelsDatabase(WORK, custom_db_path=os.path.join(WORK, 'replace.db'))
dbmod._db_instance = db
VERSION = 5001
FILE = os.path.join(WORK, 'm.safetensors')
with open(FILE, 'wb') as f:
    f.write(b'weights')
db.upsert_version({'file_path': FILE, 'file_name': 'm.safetensors',
                   'file_extension': '.safetensors', 'id': VERSION, 'has_civitai_data': True})
db.store_images(VERSION, 1, [{'id': i, 'url': 'old%d' % i, 'browsingLevel': 1} for i in (1, 2, 3)])
db.update_version_images_state(VERSION, 'old-cursor')


VERSION_PAYLOAD = {'id': VERSION, 'modelId': 50, 'name': 'v1', 'files': [{'name': 'm.safetensors'}]}


class Civitai:
    """Civitai, knowing the file, and answering its gallery as told."""
    answer = {}

    def __init__(self):
        self.api_key = None
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def get_model_by_hash(self, value):
        return VERSION_PAYLOAD

    def get_model(self, model_id):
        return {'id': 50, 'name': 'M', 'type': 'LORA', 'modelVersions': [VERSION_PAYLOAD]}

    def get_model_images(self, version_id, cursor=None, limit=100):
        return Civitai.answer

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def get_checkpoint_types(self, ids):
        return {}

    def close(self):
        pass


def sync():
    """A force sync of the file, as a model's Sync runs it: whether it worked."""
    try:
        return SyncService(client=Civitai()).sync_model(FILE, force=True).success
    except Exception:
        return False
stored = lambda: [i['id'] for i in db.get_images(VERSION, page=1)]
cursor = lambda: db.get_version_by_id(VERSION)['next_images_cursor']

# Part-way through, an image that cannot be written: a set is no JSON.
Civitai.answer = {'images': [{'id': 10, 'url': 'new10', 'browsingLevel': 1},
                             {'id': 11, 'url': 'new11', 'browsingLevel': 1, 'odd': {1, 2}}],
                  'next_cursor': 'new-cursor'}
check('a sync that fails while storing says so', sync(), False)
check('and the gallery it was replacing is still there', stored(), [1, 2, 3])
check('with where it got to', cursor(), 'old-cursor')

Civitai.answer = {'images': [{'id': 10, 'url': 'new10', 'browsingLevel': 1},
                             {'id': 11, 'url': 'new11', 'browsingLevel': 1}],
                  'next_cursor': 'new-cursor'}
check('one that works replaces it', (sync(), stored()), (True, [10, 11]))
check('and records where Civitai\'s next page starts', cursor(), 'new-cursor')

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
