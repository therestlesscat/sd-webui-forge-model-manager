"""
What Civitai fails on during a sync is tried again at its end, patiently
(CivitaiClient.patiently: six retries, waiting 2, 4, 8, 8, 8 and 8 seconds):
the whole model where it could not say what the file is, its images alone
where only they failed. A model's details are stored before its images are
fetched: a gallery Civitai cannot serve no longer costs the model them - 21
files of one force sync kept their old details that way. What fails twice is
an error; a model whose images failed twice keeps its fresh details and its
stored gallery.
"""
import contextlib
import os
import sys
import threading

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
import model_manager.sync_service as sync_module         # noqa: E402
from modules import paths                                # noqa: E402  (webui_stub's)
from model_manager import console                        # noqa: E402
from model_manager.architecture import Architecture     # noqa: E402
from model_manager.civitai import (                      # noqa: E402
    CivitaiAPIError, CivitaiAuthError, TokenBucketRateLimiter,
)
from model_manager.sync_service import SyncService      # noqa: E402

WORK = os.path.join(TESTS, 'work', 'sync_retry')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
models = facts['models_dir']
paths.models_path = ''
sync_module.identify = lambda path: Architecture(None, None, False, False, 'LORA', 'read for the test')
OVERLOADED = 'Civitai: Image search is temporarily overloaded - please retry. (503)'


class Client:
    """Civitai, failing as often as it is told to - and saying, of each
    request, whether it was asked patiently."""

    def __init__(self, by_hash=None, models=None, fail_images=0, fail_hash=0, refuse=False):
        self.by_hash = by_hash or {}
        self.models = models or {}
        self.fail_images = fail_images
        self.fail_hash = fail_hash
        self.refuse = refuse
        self.asked = []
        self.local = threading.local()
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    @contextlib.contextmanager
    def patiently(self):
        self.local.patient = True
        try:
            yield self
        finally:
            self.local.patient = False

    def patient(self):
        return getattr(self.local, 'patient', False)

    def get_model_by_hash(self, value):
        self.asked.append(('by_hash', self.patient()))
        if self.refuse:
            raise CivitaiAuthError(401)
        if self.fail_hash and len(value) == 64:      # the SHA-256
            self.fail_hash -= 1
            raise CivitaiAPIError(OVERLOADED)
        return self.by_hash.get(value.upper())

    def get_model(self, model_id):
        return self.models.get(model_id)

    def get_models_by_ids(self, ids):
        return {i: self.models[i] for i in ids if i in self.models}

    def get_model_images(self, version_id, cursor=None, limit=None):
        self.asked.append(('images', self.patient()))
        if self.fail_images:
            self.fail_images -= 1
            raise CivitaiAPIError(OVERLOADED)
        return {'images': [{'id': version_id * 10 + 1, 'url': 'https://image.civitai.com/x/%d.jpeg' % version_id,
                            'nsfwLevel': 1, 'meta': {'prompt': 'a prompt'}}], 'next_cursor': None}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def get_checkpoint_types(self, ids):
        return {}


hashed = []

def service(**answers):
    sync = SyncService(client=Client(**answers))
    real = sync.calculate_hashes
    sync.calculate_hashes = lambda path: (hashed.append(path), real(path))[1]
    return sync


def model_file(name, fill, model_id):
    """A file Civitai knows, as version model_id + 1 of model model_id."""
    path = os.path.join(models, 'Lora', name)
    with open(path, 'wb') as f:
        f.write(fill * 4096)
    db.insert_missing_versions([{'file_path': path, 'file_name': name}])
    sha = SyncService(client=Client()).calculate_hashes(path).sha256
    version = {'id': model_id + 1, 'modelId': model_id, 'name': 'v1', 'nsfwLevel': 1, 'baseModel': 'SDXL 1.0',
               'files': [{'id': model_id * 10, 'name': name, 'hashes': {'SHA256': sha}}]}
    model = {'id': model_id, 'name': 'Model %d' % model_id, 'type': 'LORA', 'modelVersions': [dict(version)]}
    return path, {sha: version}, {model_id: model}


def row(path):
    return db.get_version(path) or {}


def said_since(mark):
    return [line['text'] for line in console.since(mark)[0]]


def images_of(version_id):
    return [image['id'] for image in db.get_images(version_id)]


# --------------------------------------------- images: failed, then at the end
A, by_hash, model = model_file('retry_a.safetensors', b'a', 8100)
mark = console.said()
sync = service(by_hash=by_hash, models=model, fail_images=1)
progress = sync.sync_all(model_paths=[A], force=True)
check('a model whose images fail has its details stored all the same', row(A).get('id'), 8101)
check('its images are asked for again at the end, patiently',
      [a for a in sync.client.asked if a[0] == 'images'], [('images', False), ('images', True)])
check('and stored then', images_of(8101), [81011])
check('counted once, synced, no error', (progress.synced, progress.errors, progress.processed), (1, 0, 1))
check('the log says so', ('retry_a.safetensors: its images are tried again at the end, more patiently' in said_since(mark),
                          'retry_a.safetensors: 1 images, at the second try' in said_since(mark)), (True, True))

# ------------------------------------------------- images: failed twice
B, by_hash, model = model_file('retry_b.safetensors', b'b', 8200)
db.store_images(8201, 1, [{'id': 999, 'url': 'https://image.civitai.com/x/kept.jpeg'}])
mark = console.said()
sync = service(by_hash=by_hash, models=model, fail_images=2)
progress = sync.sync_all(model_paths=[B], force=True)
check('images failing twice: the model\'s details are stored', row(B).get('id'), 8201)
check('its stored gallery stays', images_of(8201), [999])
check('synced, and one error - its images', (progress.synced, progress.errors), (1, 1))
check('saying which', progress.error_messages, ['retry_b.safetensors: images: ' + OVERLOADED])
check('in the log too', 'retry_b.safetensors: its images could not be fetched, twice - the stored ones stay'
      in said_since(mark), True)

# --------------------------------------------- the lookup: failed, then at the end
C, by_hash, model = model_file('retry_c.safetensors', b'c', 8300)
hashed.clear()
mark = console.said()
sync = service(by_hash=by_hash, models=model, fail_hash=1)
progress = sync.sync_all(model_paths=[C], force=True)
# The first time, its SHA-256 got no answer and its AutoV2 no match; the
# second, its SHA-256 is answered.
check('Civitai not answering about a file: asked again at the end, patiently',
      [a for a in sync.client.asked if a[0] == 'by_hash'], [('by_hash', False), ('by_hash', False), ('by_hash', True)])
check('and identified then', (row(C).get('id'), progress.synced, progress.errors, progress.processed), (8301, 1, 0, 1))
check('read once: its hashes were kept for the second try', hashed, [C])
check('the log says it is tried again',
      any(t.startswith('retry_c.safetensors: Civitai did not answer') for t in said_since(mark)), True)

# ------------------------------------------------- the lookup: failed twice
D, by_hash, model = model_file('retry_d.safetensors', b'd', 8400)
sync = service(by_hash=by_hash, models=model, fail_hash=2)
progress = sync.sync_all(model_paths=[D], force=True)
check('failing twice is an error', (progress.synced, progress.errors, progress.processed), (0, 1, 1))
check('not "not on Civitai": Civitai never said so', row(D).get('civitai_lookup_failed_at'), None)

# ------------------------------------------------- a refused key
E, by_hash, model = model_file('retry_e.safetensors', b'e', 8500)
sync = service(by_hash=by_hash, models=model, refuse=True)
progress = sync.sync_all(model_paths=[E], force=True)
check('a refused key is not asked again: it would refuse again',
      ([a for a in sync.client.asked if a[0] == 'by_hash'], progress.errors), ([('by_hash', False)], 1))

# ------------------------------------------- one model's Sync: no queue to go back to
F, by_hash, model = model_file('retry_f.safetensors', b'f', 8600)
db.store_images(8601, 1, [{'id': 998, 'url': 'https://image.civitai.com/x/kept.jpeg'}])
result = service(by_hash=by_hash, models=model, fail_images=5).sync_model(F, force=True)
check('a model synced alone whose images fail is synced, its images\' failure said',
      (result.success, result.images_error, result.error), (True, OVERLOADED, None))
check('with its details stored, and its gallery kept', (row(F).get('id'), images_of(8601)), (8601, [998]))

# -------------------------------------- an "All models" sync's galleries, too
G, by_hash, model = model_file('retry_g.safetensors', b'g', 8700)
service(by_hash=by_hash, models=model).sync_all(model_paths=[G], force=True)
sync = service(models=model, fail_images=1)
progress = sync.sync_metadata(model_paths=[G], include_images=True, include_prompts=False)
check('a gallery an "All models" sync fails on is fetched again at its end, patiently',
      ([a for a in sync.client.asked if a[0] == 'images'], images_of(8701), progress.errors),
      ([('images', False), ('images', True)], [87011], 0))
db.store_images(8701, 2, [{'id': 997, 'url': 'https://image.civitai.com/x/kept.jpeg'}])
before = images_of(8701)
sync = service(models=model, fail_images=2)
progress = sync.sync_metadata(model_paths=[G], include_images=True, include_prompts=False)
check('failing twice, it keeps its stored gallery, and is one error',
      (images_of(8701), progress.errors, progress.error_messages[-1:]),
      (before, 1, ['retry_g.safetensors: images: ' + OVERLOADED]))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
