"""
Replacing a gallery's stored images is all or nothing (#73).

A refresh - Resync Images, a sync - cleared a version's images, stored the new
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

from fastapi import FastAPI                              # noqa: E402
from fastapi.testclient import TestClient                # noqa: E402

import model_manager.civitai as civitai                  # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.api import images as images_api       # noqa: E402
from model_manager.db import ModelsDatabase              # noqa: E402

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
db.upsert_version({'file_path': os.path.join(WORK, 'm.safetensors'), 'file_name': 'm.safetensors',
                   'file_extension': '.safetensors', 'id': VERSION, 'has_civitai_data': True})
db.store_images(VERSION, 1, [{'id': i, 'url': 'old%d' % i, 'browsingLevel': 1} for i in (1, 2, 3)])
db.update_version_images_state(VERSION, 'old-cursor')


class Civitai:
    answer = {}

    def __init__(self):
        self.api_key = None

    @classmethod
    def from_settings(cls):
        return cls()

    def get_model_images(self, version_id, cursor=None, limit=100):
        return Civitai.answer

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def close(self):
        pass


civitai.CivitaiClient = Civitai
app = FastAPI()
images_api.register(app)
client = TestClient(app)
stored = lambda: [i['id'] for i in db.get_images(VERSION, page=1)]
cursor = lambda: db.get_version_by_id(VERSION)['next_images_cursor']

# Part-way through, an image that cannot be written: a set is no JSON.
Civitai.answer = {'images': [{'id': 10, 'url': 'new10', 'browsingLevel': 1},
                             {'id': 11, 'url': 'new11', 'browsingLevel': 1, 'odd': {1, 2}}],
                  'next_cursor': 'new-cursor'}
r = client.post('/model-manager/images/resync', data={'version_id': VERSION})
check('a resync that fails while storing says so', r.json().get('success'), False)
check('and the gallery it was replacing is still there', stored(), [1, 2, 3])
check('with where it got to', cursor(), 'old-cursor')

Civitai.answer = {'images': [{'id': 10, 'url': 'new10', 'browsingLevel': 1},
                             {'id': 11, 'url': 'new11', 'browsingLevel': 1}],
                  'next_cursor': 'new-cursor'}
r = client.post('/model-manager/images/resync', data={'version_id': VERSION})
check('one that works replaces it', (r.json().get('success'), stored()), (True, [10, 11]))
check('and records where Civitai\'s next page starts', cursor(), 'new-cursor')

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
