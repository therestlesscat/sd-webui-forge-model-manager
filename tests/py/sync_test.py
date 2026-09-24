"""
Syncing a library with Civitai: identifying files, then refreshing what they are.

Two different jobs live here. sync_all() reads every byte of every file to hash
it and asks Civitai which version those bytes are; sync_metadata() takes the
ids that answered and refreshes their descriptions, tags, stats and licences a
hundred models per request. The first is slow and only has to happen once.

IMPORTANT: sync_metadata() writes a `.civitai.info` beside each model file it
refreshes, taking the path from the database row - so a stubbed database over a
real library will overwrite real sidecars. Everything here runs against the
fixture, whose paths are under tests/work, and the client is always injected.
Never point this at a real models directory.
"""
import io
import json
import os
import shutil
import sys
import threading

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
from model_manager.civitai import (                      # noqa: E402
    CivitaiAPIError, CivitaiNotFoundError, TokenBucketRateLimiter,
)
from model_manager.hashing import HashResult             # noqa: E402
from model_manager.sync_service import (                 # noqa: E402
    SYNC_WINDOWS, SyncProgress, SyncService, configured_hash_threads,
    estimate_metadata_sync, sync_window_counts, window_cutoff,
)

WORK = os.path.join(TESTS, 'work', 'sync')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db

LINKED = facts['linked_paths'][0]
LOCAL_ONLY = facts['local_only_paths'][0]
CHECKPOINT_ID = facts['checkpoint_ids'][0]
VERSION_ID = facts['version_ids'][0]


# ------------------------------------------------------------- a stub Civitai
class Client:
    """Stands in for CivitaiClient, answering whatever the test set."""

    def __init__(self, **answers):
        self.by_hash = answers.get('by_hash', {})
        self.model = answers.get('model')
        self.models = answers.get('models', {})
        self.images = answers.get('images', {'images': [], 'next_cursor': None})
        self.types = answers.get('types', {})
        self.generation = answers.get('generation', {})
        self.raises = answers.get('raises')
        self.models_raises = answers.get('models_raises')
        self.images_raises = answers.get('images_raises')
        self.types_raises = answers.get('types_raises')
        self.asked = []
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def get_model_by_hash(self, value):
        self.asked.append(('by_hash', value))
        if self.raises is not None:
            raise self.raises
        if value in self.by_hash:
            return self.by_hash[value]
        raise CivitaiNotFoundError('no such hash')

    def get_model(self, model_id):
        self.asked.append(('model', model_id))
        return self.model

    def get_models_by_ids(self, ids):
        self.asked.append(('models', list(ids)))
        if self.models_raises is not None:
            raise self.models_raises
        return self.models

    def get_model_images(self, version_id, cursor=None, limit=None):
        self.asked.append(('images', version_id))
        if self.images_raises is not None:
            raise self.images_raises
        # Image ids are unique across Civitai and the cache is keyed on them,
        # so a test refreshing two galleries must hand out different ones.
        if callable(self.images):
            return self.images(version_id)
        return self.images

    def get_generation_data(self, ids):
        self.asked.append(('generation', list(ids)))
        return self.generation

    def get_checkpoint_types(self, ids):
        self.asked.append(('types', list(ids)))
        if self.types_raises is not None:
            raise self.types_raises
        return self.types

    def close(self):
        self.asked.append(('close',))


def version_payload(version_id, model_id):
    """What the by-hash endpoint returns: a version, with its model nested."""
    return {'id': version_id, 'modelId': model_id, 'name': 'v1',
            'baseModel': 'SDXL 1.0', 'nsfwLevel': 1, 'trainedWords': ['trigger'],
            'publishedAt': '2026-03-01T00:00:00Z',
            'stats': {'downloadCount': 11, 'thumbsUpCount': 2}}


def model_payload(model_id, version_ids, model_type='Checkpoint', **extra):
    """What the model endpoint returns."""
    payload = {
        'id': model_id, 'name': 'Model %d' % model_id, 'type': model_type,
        'description': '<p>fresh</p>', 'tags': ['t'], 'nsfw': False,
        'nsfwLevel': 1, 'creator': {'username': 'someone', 'image': 'i.png'},
        'stats': {'downloadCount': 99, 'thumbsUpCount': 8, 'thumbsDownCount': 2},
        'allowNoCredit': True, 'allowCommercialUse': ['Image'],
        'allowDerivatives': True, 'allowDifferentLicense': False,
        'supportsGeneration': True,
        'modelVersions': [version_payload(v, model_id) for v in version_ids],
    }
    payload.update(extra)
    return payload


def service(**answers):
    """A SyncService with an injected client, so nothing reaches the network."""
    client = Client(**answers)
    return SyncService(client=client), client


# --------------------------------------------------------------- the hashes
sync, client = service()
hashes = sync.calculate_hashes(LINKED)
check('a file is hashed', len(hashes.sha256 or ''), 64)
check('with the kinds Civitai might know',
      all(getattr(hashes, kind) for kind in ('sha256', 'crc32', 'blake3', 'autov2')),
      True)
check('and they survive the round trip to the database',
      HashResult.from_stored(sync._hashes_to_dict(hashes)).sha256, hashes.sha256)

# -------------------------------------------------------- finding it by hash
found = version_payload(70001, 70000)
sync, client = service(by_hash={hashes.sha256: found})
data, kind, value = sync._lookup_by_hash_with_fallback(LINKED, hashes)
check('the first hash that answers wins', kind, 'sha256')
check('carrying the version', data['id'], 70001)
check('and the value that matched', value, hashes.sha256)

sync, client = service(by_hash={hashes.crc32: found})
data, kind, _ = sync._lookup_by_hash_with_fallback(LINKED, hashes)
check('a later kind is tried when the first does not answer', kind, 'crc32')
# AutoV3 reads the safetensors header, which the fixture's zero-filled files
# do not have, so there is no value to try and it is skipped rather than asked.
check('having tried the earlier ones it had a value for',
      [a[1] for a in client.asked], [hashes.sha256, hashes.crc32])

sync, client = service()
check('a file Civitai knows nothing about answers nothing',
      sync._lookup_by_hash_with_fallback(LINKED, hashes), (None, None, None))

sync, client = service(raises=CivitaiAPIError('server said no'))
check('an API error on every kind is not a crash',
      sync._lookup_by_hash_with_fallback(LINKED, hashes), (None, None, None))

# A hash we do not compute, left by another extension.
CM_INFO = os.path.splitext(LINKED)[0] + '.cm-info.json'
io.open(CM_INFO, 'w', encoding='utf-8').write(
    json.dumps({'Hashes': {'AutoV3': 'a' * 64, 'Weird': 'b' * 32}}))
sync, client = service(by_hash={('b' * 32).upper(): found})
data, kind, _ = sync._lookup_by_hash_with_fallback(LINKED, HashResult())
check('a kind only .cm-info.json has is tried too', kind, 'weird')
check('and one it shares with our own list is used when we have no value',
      ('A' * 64) in [a[1] for a in client.asked], True)
os.remove(CM_INFO)

# ------------------------------------------------------- syncing one model
sync, client = service()
result = sync.sync_model(LINKED)
check('a model already identified is skipped', result.skipped, True)
check('without asking Civitai anything', client.asked, [])

sync, client = service()
db.set_lookup_failed(LOCAL_ONLY)
result = sync.sync_model(LOCAL_ONLY)
check('so is one Civitai has already been asked about and did not know',
      result.skipped, True)
check('again without a request', client.asked, [])

sync, client = service()
result = sync.sync_model(LOCAL_ONLY, force=True)
check('but forcing asks anyway', result.not_found, True)
check('having tried every kind of hash it has', len(client.asked) > 1, True)
db.set_lookup_failed(LOCAL_ONLY, failed=False)

# a file that is not there cannot be hashed
sync, client = service()
result = sync.sync_model(os.path.join(WORK, 'absent.safetensors'))
check('a file that is gone is an error, not a crash',
      result.error, 'Failed to calculate hashes')

# the whole happy path
FRESH = os.path.join(facts['models_dir'], 'Stable-diffusion', 'fresh.safetensors')
io.open(FRESH, 'wb').write(b'fresh weights')
fresh_hashes = sync.calculate_hashes(FRESH)
sync, client = service(
    by_hash={fresh_hashes.sha256: version_payload(70011, 70010)},
    model=model_payload(70010, [70011, 70012]),
    images={'images': [{'id': 1, 'url': 'u1', 'meta': {'prompt': 'p'}},
                       {'id': 2, 'url': 'u2', 'meta': None}],
            'next_cursor': 'more'},
    types={70010: 'Merge'})
result = sync.sync_model(FRESH)
# A single checkpoint goes all the way through, classification included. It
# used not to: _classify_checkpoints() takes self._progress_lock, which only
# sync_all() and sync_metadata() created, so every download of a checkpoint
# reported "no attribute '_progress_lock'" after writing everything correctly.
check('a file Civitai recognises syncs', result.success, True)
check('with nothing to report', result.error, None)
check('naming the version', result.version_id, 70011)
check('and the model', result.model_id, 70010)
check('with its images counted', result.image_count, 2)

sidecar = os.path.splitext(FRESH)[0] + '.civitai.info'
written = json.loads(io.open(sidecar, encoding='utf-8').read())
check('a sidecar is written', written['id'], 70010)
check('with the version this file actually is put first',
      [v['id'] for v in written['modelVersions']], [70011, 70012])

row = db.get_version(FRESH)
check('the database has the file', row['id'], 70011)
check('marked as identified', row['has_civitai_data'], True)
check('with the hashes that found it', row['file_hashes']['sha256'], fresh_hashes.sha256)
check('its trigger words', row['trained_words'], ['trigger'])
check('and the images are stored', len(db.get_images(70011)), 2)
check('and it was asked whether it was trained or merged',
      [a for a in client.asked if a[0] == 'types'], [('types', [70010])])

# Civitai answers the hash but not the model: the version alone is enough.
LONE = os.path.join(facts['models_dir'], 'Lora', 'lone.safetensors')
io.open(LONE, 'wb').write(b'lonely weights')
lone_hashes = sync.calculate_hashes(LONE)
sync, client = service(by_hash={lone_hashes.sha256: version_payload(70021, 70020)},
                       model=None)
result = sync.sync_model(LONE)
check('a model fetch that fails still syncs the version', result.success, True)
check('and it is not a checkpoint, so nothing takes the missing lock',
      result.error, None)
row = db.get_version(LONE)
check('storing what the version knew', row['id'], 70021)
check('and the model it belongs to', row['model_id'], 70020)
check('no checkpoint question is asked, the type is unknown',
      [a for a in client.asked if a[0] == 'types'], [])

# The sidecar cannot be written, so the sync must not claim success.
sync, client = service(by_hash={lone_hashes.sha256: version_payload(70031, 70030)})
real_write = sys.modules['model_manager.sync_service'].write_civitai_info
sys.modules['model_manager.sync_service'].write_civitai_info = lambda path, data: False
result = sync.sync_model(LONE, force=True)
check('a sidecar that cannot be written is a failure',
      result.error, 'Failed to write civitai.info')
check('and not a success', result.success, False)
sys.modules['model_manager.sync_service'].write_civitai_info = real_write

# the error paths
sync, client = service(raises=CivitaiNotFoundError('gone'))
sync.client.get_model_by_hash = lambda value: (_ for _ in ()).throw(
    CivitaiNotFoundError('gone'))
result = sync.sync_model(LONE, force=True)
check('a lookup that 404s everywhere is not-found', result.not_found, True)
check('and is remembered, so the next run does not re-read the file',
      bool(db.get_version(LONE)['civitai_lookup_failed_at']), True)

sync, client = service(by_hash={lone_hashes.sha256: version_payload(70041, 70040)})
sync.client.get_model = lambda model_id: (_ for _ in ()).throw(
    CivitaiAPIError('rate limited'))
result = sync.sync_model(LONE, force=True)
check('an API error is reported as an error', result.error, 'rate limited')

sync, client = service(by_hash={lone_hashes.sha256: version_payload(70051, 70050)})
sync.client.get_model = lambda model_id: (_ for _ in ()).throw(
    ValueError('something odd'))
result = sync.sync_model(LONE, force=True)
check('and anything else is caught too',
      result.error, 'Unexpected error: something odd')

# a database write that fails must not be reported as a sync
sync, client = service(by_hash={lone_hashes.sha256: version_payload(70061, 70060)},
                       model=model_payload(70060, [70061]))
real_update = sync._update_database
sync._update_database = lambda *a, **k: 'disk is full'
result = sync.sync_model(LONE, force=True)
check('a failed database write is not a successful sync', result.success, False)
check('and says what happened', result.error, 'Database update failed: disk is full')
sync._update_database = real_update

# _update_database's own failure path
broken = sync._update_database(LONE, {'id': 1, 'modelVersions': [{'id': None}]},
                               HashResult())
check('a payload the database rejects yields a message, not an exception',
      isinstance(broken, (str, type(None))), True)

# ---------------------------------------------------------- the version ordering
payload = model_payload(1, [11, 22, 33])
check('the version we hold is moved to the front',
      [v['id'] for v in SyncService._payload_with_version_first(payload, 33)
       ['modelVersions']], [33, 11, 22])
check('a version the model does not list leaves the order alone',
      [v['id'] for v in SyncService._payload_with_version_first(
          model_payload(1, [11, 22]), 99)['modelVersions']], [11, 22])
check('and so does a payload with no versions',
      SyncService._payload_with_version_first({'id': 1}, 11), {'id': 1})
check('or no version to look for',
      [v['id'] for v in SyncService._payload_with_version_first(
          model_payload(1, [11, 22]), None)['modelVersions']], [11, 22])

# ------------------------------------------------------------ what is on disk
sync, client = service()
STRAY = os.path.join(facts['models_dir'], 'Lora', 'stray.safetensors')
io.open(STRAY, 'wb').write(b'stray')
check('a file the database has never seen gets a row',
      sync._record_found_files([STRAY]), 1)
row = db.get_version(STRAY)
check('with its size from disk', row['file_size'], 5)
check('and its name', row['file_name'], 'stray.safetensors')
check('recording it again changes nothing', sync._record_found_files([STRAY]), 0)
check('and a path that is not there is still recorded, at zero bytes',
      sync._record_found_files([os.path.join(WORK, 'imaginary.safetensors')]), 1)

check('a walk that found nothing deletes nothing',
      sync._forget_missing_files([]), 0)
check('and the library is still there', len(db.get_all_version_paths()) > 0, True)

os.remove(STRAY)
everything = [p for p in db.get_all_version_paths() if os.path.exists(p)]
removed = sync._forget_missing_files(everything)
check('a file that is gone is dropped', removed >= 1, True)
check('and it is no longer a row', db.get_version(STRAY), None)

# ------------------------------------------------------- choosing which files
all_paths = facts['linked_paths'] + facts['local_only_paths']
check('the identified ones are the ones with a Civitai model',
      sorted(sync._filter_by_identification(all_paths, 'identified')),
      sorted(facts['linked_paths']))
check('and the rest are unidentified',
      sorted(sync._filter_by_identification(all_paths, 'unidentified')),
      sorted(facts['local_only_paths']))
check('a file nobody has seen counts as unidentified',
      sync._filter_by_identification(['/nowhere/x.safetensors'], 'unidentified'),
      ['/nowhere/x.safetensors'])

# ------------------------------------------------------------------ a full sync
TWO = facts['local_only_paths'][:2]
sync, client = service()
progress = sync.sync_all(model_paths=TWO, force=True, max_workers=2)
check('a sync over two files processes both', progress.processed, 2)
check('finding neither on Civitai', progress.not_found, 2)
check('and finishes', progress.is_complete, True)
check('without walking the disk, so nothing is added',
      (progress.added, progress.removed), (0, 0))

sync, client = service()
progress = sync.sync_all(model_paths=facts['linked_paths'][:3], max_workers=2)
check('files already identified are skipped when not forcing', progress.skipped, 3)

sync, client = service()
progress = sync.sync_all(model_paths=all_paths, targets='unidentified', max_workers=2)
check('a target set narrows the work', progress.total, fixtures.LOCAL_ONLY)

sync, client = service()
progress = sync.sync_all(model_paths=all_paths, targets='identified', max_workers=2)
check('as does the other one', progress.total, len(facts['linked_paths']))

# errors are counted and the last ten kept
sync, client = service()
sync.sync_model = lambda path, force=False, classify_checkpoint=True: (
    _failing_result(path))


def _failing_result(path):
    from model_manager.sync_service import SyncResult
    result = SyncResult()
    result.error = 'broke on %s' % os.path.basename(path)
    return result


progress = sync.sync_all(model_paths=facts['linked_paths'], max_workers=4)
check('every failure is counted', progress.errors, len(facts['linked_paths']))
check('but only the last ten messages are kept',
      len(progress.error_messages), 10)

# Cancelling stops it - but only once it is running: sync_all() clears the flag
# as it starts, so cancelling beforehand is not remembered.
sync, client = service()
sync.cancel()
progress = sync.sync_all(model_paths=facts['linked_paths'], max_workers=2)
check('a sync cancelled before it starts runs anyway',
      progress.processed, len(facts['linked_paths']))

sync, client = service()
real_sync_model = sync.sync_model


def cancel_after_one(path, force=False, classify_checkpoint=True):
    sync.cancel()
    return real_sync_model(path, force=force, classify_checkpoint=classify_checkpoint)


sync.sync_model = cancel_after_one
progress = sync.sync_all(model_paths=facts['linked_paths'], max_workers=1)
check('cancelling partway stops it short',
      progress.processed < len(facts['linked_paths']), True)
check('and it still finishes', progress.is_complete, True)

# ------------------------------------------------------------ metadata refresh
ONE_PATH = facts['linked_paths'][0]
one_row = db.get_version(ONE_PATH)
sync, client = service(models={one_row['model_id']: model_payload(
    one_row['model_id'], [one_row['id']])})
progress = sync.sync_metadata(model_paths=[ONE_PATH])
check('one path refreshes one version', progress.synced, 1)
check('asking Civitai once for the model',
      [a for a in client.asked if a[0] == 'models'], [('models', [one_row['model_id']])])
check('and no images are fetched', [a for a in client.asked if a[0] == 'images'], [])
check('the description Civitai just gave is stored',
      db.get_civitai_model(one_row['model_id'])['description'], '<p>fresh</p>')

sync, client = service(models={})
progress = sync.sync_metadata(model_paths=[ONE_PATH])
check('a model Civitai no longer lists is not-found', progress.not_found, 1)
check('rather than an error', progress.errors, 0)

sync, client = service(models_raises=RuntimeError('Civitai is down'))
progress = sync.sync_metadata(model_paths=[ONE_PATH])
check('a fetch that fails ends the sync', progress.is_complete, True)
check('saying why', progress.error_messages, ['Could not fetch models: Civitai is down'])

sync, client = service()
progress = sync.sync_metadata(model_paths=['/nothing/here.safetensors'])
check('a scope that matches nothing is complete at once', progress.is_complete, True)
check('with nothing to do', progress.total, 0)

# a row whose file has gone is dropped, on the evidence of that one row
GONE = os.path.join(facts['models_dir'], 'Lora', 'vanishing.safetensors')
io.open(GONE, 'wb').write(b'here for now')
db.upsert_version({'id': 70101, 'model_id': 70100, 'file_path': GONE,
                   'file_name': os.path.basename(GONE), 'file_size': 12,
                   'file_extension': '.safetensors', 'has_civitai_data': True,
                   'nsfw_level': 1})
db.upsert_civitai_model({'id': 70100, 'name': 'Vanishing', 'type': 'LORA',
                         'nsfw_level': 1}, from_civitai=True)
os.remove(GONE)
sync, client = service(models={})
progress = sync.sync_metadata(model_paths=[GONE])
check('a row whose file has gone is removed', progress.removed, 1)
check('and it really is gone', db.get_version(GONE), None)
check('with a message saying so', len(progress.error_messages), 1)

# a write failure per version is an error, not the end of the sync
sync, client = service(models={one_row['model_id']: model_payload(
    one_row['model_id'], [one_row['id']])})
real_write = sys.modules['model_manager.sync_service'].write_civitai_info
sys.modules['model_manager.sync_service'].write_civitai_info = lambda path, data: False
progress = sync.sync_metadata(model_paths=[ONE_PATH])
check('a version whose sidecar will not write is an error', progress.errors, 1)
check('naming it', 'could not write civitai.info' in progress.error_messages[0], True)
check('and the sync still finishes', progress.is_complete, True)
sys.modules['model_manager.sync_service'].write_civitai_info = real_write

# ------------------------------------------------------------ with the galleries
TWO_PATHS = facts['linked_paths'][:2]
rows = [db.get_version(p) for p in TWO_PATHS]
sync, client = service(
    models={r['model_id']: model_payload(r['model_id'], [r['id']]) for r in rows},
    images=lambda version_id: {
        'images': [{'id': version_id, 'url': 'u%d' % version_id, 'meta': None}],
        'next_cursor': None},
    generation={r['id']: {'meta': {'prompt': 'fetched'}} for r in rows})
progress = sync.sync_metadata(model_paths=TWO_PATHS, include_images=True)
check('with images, the bar counts both passes', progress.total, 4)
check('a gallery is fetched per version',
      len([a for a in client.asked if a[0] == 'images']), 2)
check('and the prompts behind them in one pooled request',
      len([a for a in client.asked if a[0] == 'generation']), 1)
stored = db.get_images(rows[0]['id'])
check('the gallery replaced what was there', len(stored), 1)
check('with the prompt that was looked up',
      stored[0]['meta']['prompt'], 'fetched')

# Declining the prompts used to replace each gallery with what /images says,
# which is meta: null - every prompt fetched before was lost. These use two
# single-version models no earlier check has synced, so each file keeps its
# own version and its own gallery.
KEEP_PATHS = facts['linked_paths'][4:6]
keep_rows = [db.get_version(p) for p in KEEP_PATHS]
KEEP_MODELS = {r['model_id']: model_payload(r['model_id'], [r['id']]) for r in keep_rows}
first = keep_rows[0]['id']


def gallery(url):
    """Each version's gallery: its own id, and one more new to it."""
    return lambda version_id: {
        'images': [{'id': version_id, 'url': url + str(version_id), 'meta': None},
                   {'id': version_id + 50000, 'url': 'new%d' % version_id, 'meta': None}],
        'next_cursor': None}


# A sync with prompts first, so there are prompts stored to lose.
sync, client = service(models=KEEP_MODELS, images=gallery('u'),
                       generation={r['id']: {'meta': {'prompt': 'fetched'}} for r in keep_rows})
sync.sync_metadata(model_paths=KEEP_PATHS, include_images=True)
check('a sync with prompts stores the prompt looked up',
      {img['id']: (img['meta'] or {}).get('prompt') for img in db.get_images(first)},
      {first: 'fetched', first + 50000: None})

sync, client = service(models=KEEP_MODELS, images=gallery('fresh'))
progress = sync.sync_metadata(model_paths=KEEP_PATHS, include_images=True,
                              include_prompts=False)
check('declining the prompts asks for none',
      [a for a in client.asked if a[0] == 'generation'], [])
stored = {img['id']: img for img in db.get_images(first)}
check('but the prompt already stored stays with its image',
      stored[first]['meta'], {'prompt': 'fetched'})
check('while everything else about the image is replaced by the fresh copy',
      stored[first]['url'], 'fresh%d' % first)
check('and an image with no prompt stored still has none', stored[first + 50000]['meta'], None)

# With the prompts wanted, only what is still missing is looked up.
sync, client = service(models=KEEP_MODELS, images=gallery('again'),
                       generation={r['id'] + 50000: {'meta': {'prompt': 'looked up'}}
                                   for r in keep_rows})
progress = sync.sync_metadata(model_paths=KEEP_PATHS, include_images=True)
asked_for = sorted(i for a in client.asked if a[0] == 'generation' for i in a[1])
check('the lookup asks only about images with no prompt yet',
      asked_for, sorted(r['id'] + 50000 for r in keep_rows))
stored = {img['id']: (img['meta'] or {}).get('prompt') for img in db.get_images(first)}
check('and both end up with theirs',
      (stored[first], stored[first + 50000]), ('fetched', 'looked up'))

sync, client = service(
    models={r['model_id']: model_payload(r['model_id'], [r['id']]) for r in rows},
    images_raises=RuntimeError('gallery gone'))
progress = sync.sync_metadata(model_paths=TWO_PATHS, include_images=True)
check('a gallery that will not load is an error per version', progress.errors, 2)
check('while the metadata half still succeeded', progress.synced, 2)

# a callback sees the work happen
seen = []
sync, client = service(
    models={r['model_id']: model_payload(r['model_id'], [r['id']]) for r in rows})
sync.sync_metadata(model_paths=TWO_PATHS, callback=lambda p: seen.append(p.processed))
# Once before the models are fetched, then once per version.
check('the callback is told before it starts and after each version',
      len(seen), 3)

# cancelling
# As with sync_all, the flag is cleared on entry, so the cancel has to arrive
# while the sync is running - here from the callback, after the first version.
sync, client = service(
    models={r['model_id']: model_payload(r['model_id'], [r['id']]) for r in rows},
    images={'images': [], 'next_cursor': None})
progress = sync.sync_metadata(model_paths=TWO_PATHS, include_images=True,
                              callback=lambda p: sync.cancel())
check('a cancelled metadata sync fetches no galleries',
      [a for a in client.asked if a[0] == 'images'], [])
check('and asks no checkpoint question',
      [a for a in client.asked if a[0] == 'types'], [])
check('while still finishing', progress.is_complete, True)

# --------------------------------------------------------- classifying checkpoints
sync, client = service(types={CHECKPOINT_ID: 'Merge'})
check('the checkpoints among a batch are classified',
      sync._classify_checkpoints({CHECKPOINT_ID: {'type': 'Checkpoint'},
                                  999: {'type': 'LORA'}}), 1)
check('and only they were asked about', client.asked[-1], ('types', [CHECKPOINT_ID]))

sync, client = service()
check('a batch with no checkpoints asks nothing',
      sync._classify_checkpoints({1: {'type': 'LORA'}, 2: None}), 0)
check('really nothing', client.asked, [])

sync, client = service(types_raises=RuntimeError('classify failed'))
check('a classification that fails is not a crash',
      sync._classify_checkpoints({CHECKPOINT_ID: {'type': 'Checkpoint'}}), 0)

# --------------------------------------------------------------- the dials
sync, client = service()
sync.client.rate_limiter = TokenBucketRateLimiter(1.0, 1)
check('a slow rate still gets a floor of threads', sync._workers_for_rate(), 4)
sync.client.rate_limiter = TokenBucketRateLimiter(8.0, 8)
check('a faster one gets a thread per request per second',
      sync._workers_for_rate(), 8)
sync.client.rate_limiter = TokenBucketRateLimiter(100.0, 100)
check('and it is capped', sync._workers_for_rate(), 12)
sync.client.rate_limiter = None
check('a client with no limiter falls back to the default',
      sync._workers_for_rate(), 4)

opts.model_manager_hash_threads = 6
check('the hash thread count comes from the setting', configured_hash_threads(), 6)
opts.model_manager_hash_threads = 0
check('a nonsense setting is brought back into range',
      configured_hash_threads() >= 1, True)
opts.model_manager_hash_threads = 999
check('and so is an absurd one', configured_hash_threads() <= 32, True)
opts.model_manager_hash_threads = 4

# --------------------------------------------------------------- the windows
check('the windows are offered shortest first',
      [days for _, days in SYNC_WINDOWS], sorted(days for _, days in SYNC_WINDOWS))
check('a cutoff is a timestamp in the past', window_cutoff(1) < window_cutoff(0), True)

counts = sync_window_counts()
check('every window is counted', len(counts), len(SYNC_WINDOWS))
check('each with its label and number',
      sorted(counts[0]), ['days', 'label', 'versions'])
check('a longer window selects no more than a shorter one',
      counts[-1]['versions'] <= counts[0]['versions'], True)

downloaded = sync_window_counts(basis='downloaded')
check('the download windows run the other way, and are counted separately',
      len(downloaded), len(SYNC_WINDOWS))
check('narrowing to one path narrows every window',
      all(w['versions'] <= 1 for w in sync_window_counts([ONE_PATH])), True)

# ------------------------------------------------------------- the progress dict
progress = SyncProgress(total=10, processed=4, synced=3, not_found=1)
check('progress reports what the bar needs',
      sorted(progress.to_dict()),
      ['added', 'current_model', 'error_messages', 'errors', 'is_complete',
       'not_found', 'processed', 'removed', 'skipped', 'synced', 'total'])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
