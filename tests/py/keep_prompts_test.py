"""
Replacing a gallery keeps the prompts it already had.

/images returns meta: null; the prompt, settings and resources come from a
separate lookup, which a sync can skip and which fails without an API key.
Every path that replaced a stored gallery wrote it back with only what
/images said, so a sync without "Image prompts", or a lookup that failed,
erased every prompt the gallery held. Resync Images (gone since) also cleared the gallery
before fetching, so a fetch that failed left the model with no images.

Now the fresh images replace everything but the generation data, which each
takes from its stored copy when it has none of its own, and nothing is
cleared until the fetch has worked. (The bulk sync's side of this is in
sync_test.py.)
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

opts = webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.civitai import TokenBucketRateLimiter, keep_generation_data  # noqa: E402
from model_manager.sync_service import SyncService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'keep_prompts')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ------------------------------------------------------------ the helper
fresh = [{'id': 1, 'url': 'new', 'meta': None},
         {'id': 2, 'url': 'new', 'meta': {'prompt': 'its own', 'steps': 30}},
         {'id': 3, 'url': 'new', 'meta': {'Size': '512x512'}},
         {'id': 4, 'url': 'new', 'meta': None}]
stored = [{'id': 1, 'url': 'old', 'meta': {'prompt': 'kept', 'steps': 20}},
          {'id': 2, 'url': 'old', 'meta': {'prompt': 'old one'}},
          {'id': 3, 'url': 'old', 'meta': {'prompt': 'kept too', 'Size': '1x1'}}]
check('it counts the images that kept theirs', keep_generation_data(fresh, stored), 2)
check('an image with none takes its stored copy\'s', fresh[0]['meta'], {'prompt': 'kept', 'steps': 20})
check('but not the stored url - only the generation data', fresh[0]['url'], 'new')
check('an image with a prompt of its own keeps it', fresh[1]['meta'], {'prompt': 'its own', 'steps': 30})
check('and what the fresh meta does carry wins over the stored',
      fresh[2]['meta'], {'prompt': 'kept too', 'Size': '512x512'})
check('an image never stored has nothing to take', fresh[3]['meta'], None)
check('nothing stored, nothing kept', keep_generation_data([{'id': 9, 'meta': None}], None), 0)


# ------------------------------------------------- a model's Sync, its file
db, facts = fixtures.build(WORK)
dbmod._db_instance = db
version = facts['version_ids'][3]
path = db.get_version_by_id(version)['file_path']
before = {img['id']: img['meta'] for img in db.get_images(version)}
payload = {'id': version, 'modelId': 60, 'name': 'v1', 'files': [{'name': os.path.basename(path)}]}


class Civitai:
    """Knows the file; answers /images with the stored ids at a new url; generation data as told."""

    images_fail = False
    generation = {}
    limits = []
    api_key = 'a-key'
    rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def get_model_by_hash(self, value):
        return payload

    def get_model(self, model_id):
        return {'id': 60, 'name': 'M', 'type': 'LORA', 'modelVersions': [payload]}

    def get_checkpoint_types(self, ids):
        return {}

    def get_model_images(self, version_id, cursor=None, limit=None):
        Civitai.limits.append(limit)
        if Civitai.images_fail:
            raise RuntimeError('Civitai is down')
        return {'images': [{'id': i, 'url': 'fresh', 'meta': None} for i in before]
                + [{'id': 777777, 'url': 'fresh', 'meta': None}], 'next_cursor': None}

    def get_generation_data(self, ids, workers=1, errors=None):
        if Civitai.generation is None:
            raise RuntimeError('no API key')
        return Civitai.generation

    def close(self):
        pass


def sync():
    """A force sync of the file, as a model's Sync runs it: whether it worked."""
    try:
        return SyncService(client=Civitai()).sync_model(path, force=True).success
    except Exception:
        return False


Civitai.generation = None            # the lookup fails
opts.model_manager_gallery_page_size = 50
worked = sync()
opts.model_manager_gallery_page_size = 100
check('a sync asks for the first page at the gallery page size set', Civitai.limits, [50])
check('a sync whose prompt lookup fails still succeeds', worked, True)
after = {img['id']: img for img in db.get_images(version)}
check('and every image keeps the prompt it had',
      {i: after[i]['meta'] for i in before}, before)
check('while taking the fresh copy of everything else',
      {after[i]['url'] for i in before}, {'fresh'})
check('and a new image comes in', 777777 in after)

Civitai.images_fail = True
check('a sync whose fetch fails says so', sync(), False)
check('and leaves the gallery as it was, rather than empty',
      sorted(img['id'] for img in db.get_images(version)), sorted(after))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
