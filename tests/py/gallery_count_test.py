"""
A refresh of a model's images: the first page, or as many as it has (#103).

Every refresh - a metadata sync with images, a force sync, Resync Images -
fetched one batch and replaced the whole stored gallery with it: one paged to
600 was left with 100. Replacing stays (Civitai's order changes, so old pages
beside a fresh first one would repeat and skip images); what is now chosen is
how many come back: the first page, at the page size, or as many as the
version has stored. The sync dialog shows what each costs, and how many
stored images the first would delete.
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

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.gallery as gallery                  # noqa: E402
from model_manager.civitai import TokenBucketRateLimiter  # noqa: E402
from model_manager.sync_estimates import estimate_metadata_sync  # noqa: E402
from model_manager.sync_service import SyncService       # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(os.path.join(TESTS, 'work', 'gallery_count'))
dbmod._db_instance = db
opts.model_manager_gallery_page_size = 100


class Civitai(object):
    """A version's gallery on Civitai: `available` images, paged by cursor."""

    def __init__(self, available, fail_at=None):
        self.available = available
        self.fail_at = fail_at              # the batch, from 0, that raises
        self.asked = []
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)
        self.api_key = None

    def get_model_images(self, version_id, cursor=None, limit=100):
        start = int(cursor or 0)
        if self.fail_at is not None and start // 100 == self.fail_at:
            raise RuntimeError('Civitai: overloaded (503)')
        self.asked.append((version_id, start, limit))
        ids = range(start, min(start + min(limit, 100), self.available))
        end = start + len(ids)
        return {'images': [{'id': version_id * 10000 + i, 'url': 'u%d' % i, 'meta': None} for i in ids],
                'next_cursor': str(end) if end < self.available else None}

    def get_models_by_ids(self, ids):
        return {}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def get_checkpoint_types(self, ids):
        return {}

    def close(self):
        pass


# ---------------------------------------------------------- the shared fetch
fetch_gallery = getattr(gallery, 'fetch_gallery', None)
check('there is one fetch for a gallery of a given size', fetch_gallery is not None)
if fetch_gallery:
    civitai = Civitai(250)
    images, cursor = fetch_gallery(civitai, 7, 250)
    check('as many as asked for, Civitai\'s cursor followed a hundred at a time',
          (len(images), [a[1:] for a in civitai.asked], cursor), (250, [(0, 100), (100, 100), (200, 50)], None))
    civitai = Civitai(250)
    images, cursor = fetch_gallery(civitai, 7, 100)
    check('a first page is one request, with the cursor to what follows',
          (len(images), len(civitai.asked), cursor), (100, 1, '100'))
    civitai = Civitai(40)
    check('fewer when Civitai has fewer', len(fetch_gallery(civitai, 7, 300)[0]), 40)


# ------------------------------------------------------- a sync's galleries
LINKED = facts['linked_paths'][0]
VERSION = db.get_version(LINKED)['id']


def stored_gallery(count):
    """The version's stored gallery: `count` images, each with a prompt."""
    db.replace_first_page(VERSION, [{'id': VERSION * 10000 + i, 'url': 'old%d' % i,
                                     'meta': {'prompt': 'kept %d' % i}} for i in range(count)], None)


def metadata_sync(civitai, **options):
    sync = SyncService(client=civitai)
    sync.sync_metadata(model_paths=[LINKED], include_images=True, include_prompts=False, **options)
    return db.get_images(VERSION)


stored_gallery(300)
try:
    after = metadata_sync(Civitai(1000), keep_image_count=True)
    check('"as many as it has": a gallery of 300 comes back with 300', len(after), 300)
    check('their prompts carried over, whatever page they were on',
          sum(1 for img in after if (img.get('meta') or {}).get('prompt', '').startswith('kept')), 300)
    stored_gallery(300)
    check('"the first page": 100, as before', len(metadata_sync(Civitai(1000), keep_image_count=False)), 100)
    stored_gallery(300)
    check('the first page is still the default', len(metadata_sync(Civitai(1000))), 100)
    stored_gallery(30)
    check('a gallery smaller than a page comes back as a whole page',
          len(metadata_sync(Civitai(1000), keep_image_count=True)), 100)
    stored_gallery(300)
    after = metadata_sync(Civitai(1000, fail_at=2), keep_image_count=True)
    check('a batch that fails leaves the stored gallery as it was: all or nothing',
          (len(after), after[0]['url']), (300, 'old0'))
except TypeError as e:
    check('a sync can be asked for as many as each has (%s)' % e, False)

# ----------------------------------------------------------- the estimate
stored_gallery(350)
estimate = estimate_metadata_sync(model_paths=[LINKED], include_images=True, include_prompts=False)
options = estimate.get('image_options') or {}
check('the estimate costs both: the first page one request, as many as it has four',
      ((options.get('first') or {}).get('requests'), (options.get('kept') or {}).get('requests')), (1, 4))
# Versions, not models: the cut is per version, and said as models the
# count before a delete was in the wrong unit (#208).
check('and says how many stored images the first page would delete, from how many versions',
      options.get('deletes'), {'images': 250, 'versions': 1})
# The dialog names the first page by its size: "First 100 images per model".
# Sent by nobody, it read "First undefined images per model".
check('and the size of a page, which the first option is named by', options.get('page'), 100)
try:
    lines = [estimate_metadata_sync(model_paths=[LINKED], include_images=True, keep_image_count=keep)
             ['requests']['images'] for keep in (False, True)]
except TypeError as e:
    lines = str(e)
check('the images line costs the first page unless asked for the rest', lines, [1, 4])

# ------------------------------------------------- a force sync of a file
# Identifying a file fetches its gallery too: the same choice.
import io as _io                                         # noqa: E402
FRESH = os.path.join(facts['models_dir'], 'Lora', 'count_fresh.safetensors')
_io.open(FRESH, 'wb').write(b'fresh weights for the count')
FRESH_VERSION = 90001


class Identifying(Civitai):
    def get_model_by_hash(self, value):
        return {'id': FRESH_VERSION, 'modelId': 90000, 'name': 'v1', 'baseModel': 'SDXL 1.0',
                'nsfwLevel': 1, 'files': [{'name': 'count_fresh.safetensors', 'primary': True}]}

    def get_model(self, model_id):
        return {'id': 90000, 'name': 'Counted', 'type': 'LORA', 'nsfwLevel': 1,
                'modelVersions': [self.get_model_by_hash(None)]}


for keep, want in ((True, 300), (False, 100)):
    db.replace_first_page(FRESH_VERSION, [{'id': FRESH_VERSION * 10000 + i, 'url': 'old%d' % i,
                                           'meta': {'prompt': 'kept'}} for i in range(300)], None)
    sync = SyncService(client=Identifying(1000))
    sync.keep_image_count = keep
    sync.sync_model(FRESH, force=True)
    check('a force sync of a file refetches %s' % ('as many as it has' if keep else 'its first page'),
          len(db.get_images(FRESH_VERSION)), want)

# ---------------------------------------- the model's Sync, and the API
# The Sync button in a model's header asks first, and syncs each of its
# files that way (Resync Images, which asked it for one version, is gone).
from fastapi import FastAPI                              # noqa: E402
from fastapi.testclient import TestClient                # noqa: E402
import model_manager.api.models as models_api            # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

app = FastAPI()
setup_api(app)
web = TestClient(app)
told = []


class Told(SyncService):
    """The sync, saying how it was asked to refetch rather than reading files."""

    def __init__(self, client=None):
        super().__init__(client=Civitai(0))

    def sync_model(self, model_path, force=False, classify_checkpoint=True, known=None):
        told.append(self.keep_image_count)
        return type('Result', (), {'success': True, 'error': None})()


real_service = models_api.SyncService
models_api.SyncService = Told
try:
    model_id = db.get_version(LINKED)['model_id']
    for keep in ('true', 'false'):
        web.post('/model-manager/models/force-sync', data={'model_id': model_id, 'keep_image_count': keep})
    check('the model\'s Sync refetches each file as it was asked: as many as each has, or the first page',
          (told[:1], told[-1:]), ([True], [False]))
    told.clear()
    web.post('/model-manager/models/force-sync', data={'model_id': model_id})
    check('and the first page when nobody says', told[:1], [False])
finally:
    models_api.SyncService = real_service

stored_gallery(350)
answer = web.get('/model-manager/sync/estimate', params={'force_mode': 'identified'}).json()
force = answer.get('force_images') or {}
check('a force sync is costed both ways too, over the files it would sync, its page size said',
      ((force.get('first') or {}).get('requests', 0) >= 1, (force.get('deletes') or {}).get('images', 0) >= 250,
       force.get('page')), (True, True, 100))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
