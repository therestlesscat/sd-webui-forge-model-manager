"""
The Civitai Browser's endpoints, with Civitai replaced by a stub.

Every one of these calls out to Civitai, so `CivitaiClient` is swapped for a
class whose `from_settings()` hands back scripted answers. That reaches the
paths that only happen when Civitai fails, the gallery's pages, read live
from Civitai, and the ownership marks that make a search result say "you
already have this".
"""
import json
import os
import sys
import types

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
import model_manager.api.civitai as endpoints            # noqa: E402
import model_manager.download_service as ds              # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.api.annotations import (              # noqa: E402
    annotate_local_ownership, annotate_paid_access,
)

WORK = os.path.join(TESTS, 'work', 'browser_api')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db

app = FastAPI()
setup_api(app)
client = TestClient(app)

OWNED_MODEL = facts['checkpoint_ids'][0]
OWNED_VERSION = facts['version_ids'][0]
USABLE = {'prompt': 'a cat', 'steps': 20, 'sampler': 'Euler a', 'cfgScale': 7}


# ------------------------------------------------------------- a stub Civitai
class Stub:
    """Stands in for CivitaiClient. What it answers is set per test."""

    models = {'items': [], 'nextCursor': None}
    model = None
    version = None
    images = {'images': [], 'next_cursor': None}
    tags = {'items': []}
    enums = {}
    generation = {}
    raises = None
    calls = []

    @classmethod
    def from_settings(cls):
        return cls()

    def close(self):
        Stub.calls.append(('close',))

    def _maybe_fail(self):
        if Stub.raises is not None:
            raise Stub.raises

    def search_models(self, **kwargs):
        Stub.calls.append(('search_models', kwargs))
        self._maybe_fail()
        return Stub.models

    def get_model(self, model_id):
        Stub.calls.append(('get_model', model_id))
        self._maybe_fail()
        return Stub.model

    def get_model_version(self, version_id):
        Stub.calls.append(('get_model_version', version_id))
        self._maybe_fail()
        return Stub.version

    def get_model_images(self, version_id, cursor=None, limit=None):
        Stub.calls.append(('get_model_images', version_id, cursor, limit))
        self._maybe_fail()
        return Stub.images

    def get_generation_data(self, ids, workers=1, errors=None):
        Stub.calls.append(('get_generation_data', list(ids)))
        return Stub.generation

    def search_tags(self, query=None, limit=None):
        Stub.calls.append(('search_tags', query, limit))
        self._maybe_fail()
        return Stub.tags

    def get_enums(self):
        Stub.calls.append(('get_enums',))
        self._maybe_fail()
        return Stub.enums


def civitai(**answers):
    """Set what the stub answers, and forget what it was asked before."""
    Stub.raises = answers.pop('raises', None)
    for name in ('models', 'model', 'version', 'images', 'tags', 'enums', 'generation'):
        if name in answers:
            setattr(Stub, name, answers[name])
    Stub.calls = []


def forget():
    """Forget what Civitai was asked, without changing what it answers."""
    Stub.calls = []


endpoints.CivitaiClient = Stub


def get(url, **params):
    r = client.get(url, params=params)
    return r.status_code, r.json()


def post(url, **data):
    r = client.post(url, data=data)
    return r.status_code, r.json()


def remote(model_id, version_id, images=(), **version_extra):
    """A model as Civitai returns it, with one version."""
    version = {'id': version_id, 'name': 'v1', 'baseModel': 'SDXL 1.0',
               'images': list(images),
               'files': [{'id': version_id * 7, 'name': 'm.safetensors',
                          'primary': True, 'downloadUrl': 'https://example.invalid/m'}]}
    version.update(version_extra)
    return {'id': model_id, 'name': 'Remote %d' % model_id, 'type': 'Checkpoint',
            'modelVersions': [version]}


# ------------------------------------------------------------------ searching
civitai(models={'items': [remote(90001, 90002), remote(OWNED_MODEL, OWNED_VERSION)],
                'nextCursor': 'page-2'})
status, body = get('/model-manager/civitai/models', query='cat')
check('a search answers', (status, body['success']), (200, True))
check('with what Civitai listed', len(body['models']), 2)
check('carrying the cursor onwards', body['nextCursor'], 'page-2')
check('the page size comes from the setting', body['pageSize'],
      opts.model_manager_civitai_page_size)
check('and the card size is parsed', (body['cardWidth'], body['cardHeight']), (200, 280))
check('a model that is not local is marked so', body['models'][0]['owned_locally'], False)
check('and one that is, is', body['models'][1]['owned_locally'], True)
check('naming which version', body['models'][1]['owned_versions'], [OWNED_VERSION])
check('nothing was filtered, so there are no filter stats', body['filterStats'], None)
check('the client was closed', ('close',) in Stub.calls, True)

status, body = get('/model-manager/civitai/models', types='Checkpoint,LORA',
                   base_models='SDXL 1.0, Pony', tag='anime', nsfw='true',
                   checkpoint_type='Trained', sort='Newest', period='Month',
                   limit=5)
asked = [c[1] for c in Stub.calls if c[0] == 'search_models'][-1]
check('the comma-separated lists are split', asked['types'], ['Checkpoint', 'LORA'])
check('and trimmed', asked['base_models'], ['SDXL 1.0', 'Pony'])
check('the single-valued filters are passed straight through',
      (asked['tag'], asked['nsfw'], asked['checkpoint_type'], asked['sort'],
       asked['period']), ('anime', True, 'Trained', 'Newest', 'Month'))
check('and an explicit limit beats the setting', body['pageSize'], 5)

# a card size the settings page cannot produce, but a hand-edited config can
opts.model_manager_civitai_card_size = 'nonsense'
status, body = get('/model-manager/civitai/models')
check('an unparseable card size falls back to the default',
      (body['cardWidth'], body['cardHeight']), (200, 280))
opts.model_manager_civitai_card_size = '150x210'
status, body = get('/model-manager/civitai/models')
check('and a good one is used', (body['cardWidth'], body['cardHeight']), (150, 210))
opts.model_manager_civitai_card_size = '200x280'

# a filter token left over from the prompt filter must not reach Civitai
from model_manager.civitai import encode_filter_token         # noqa: E402

civitai(models={'items': [], 'nextCursor': None})
get('/model-manager/civitai/models', cursor=encode_filter_token('real-cursor', 4))
asked = [c[1] for c in Stub.calls if c[0] == 'search_models'][-1]
check('a filter token is unwrapped before Civitai sees it',
      asked['cursor'], 'real-cursor')

civitai(raises=RuntimeError('Civitai is down'))
status, body = get('/model-manager/civitai/models')
check('a search that fails is a 500', status, 500)
check('with the reason', body['error'], 'Civitai is down')

# ------------------------------------------------- searching with the prompt filter
WITH_PROMPTS = remote(90010, 90011, images=[{'id': 1, 'meta': USABLE}])
WITHOUT = remote(90020, 90021, images=[{'id': 2, 'meta': None}])
civitai(models={'items': [WITH_PROMPTS, WITHOUT], 'nextCursor': None},
        images={'images': [], 'next_cursor': None})

# Each candidate's images are fetched to be checked; answer per version.
def images_for(version_id, cursor=None, limit=None):
    known = {90011: [{'id': 1, 'meta': USABLE}]}
    return {'images': known.get(version_id, [{'id': 9, 'meta': None}]),
            'next_cursor': None}


_scripted_images = Stub.get_model_images
Stub.get_model_images = lambda self, version_id, cursor=None, limit=None: (
    images_for(version_id, cursor, limit))

status, body = get('/model-manager/civitai/models', require_prompt='true', limit=2)
check('the prompt filter keeps only what it can reproduce',
      [m['id'] for m in body['models']], [90010])
check('and reports what it dropped', body['filterStats']['dropped'], 1)
check('having checked both', body['filterStats']['checked'], 2)
check('and says the bar it used', body['filterStats']['minUsable'], 1)

# ------------------------------------------------------------- the stream
civitai(models={'items': [WITH_PROMPTS, WITHOUT], 'nextCursor': None})
with client.stream('GET', '/model-manager/civitai/models/stream',
                   params={'limit': 2}) as response:
    lines = [json.loads(line) for line in response.iter_lines() if line.strip()]

kinds = [line['type'] for line in lines]
check('the stream opens with its metadata', kinds[0], 'meta')
check('announcing the page size', lines[0]['pageSize'], 2)
check('and the card size', (lines[0]['cardWidth'], lines[0]['cardHeight']), (200, 280))
check('progress is reported as it goes', 'progress' in kinds, True)
check('each qualifying model is sent as it is found', kinds.count('model'), 1)
check('marked up with local ownership',
      'owned_locally' in [m for m in lines if m['type'] == 'model'][0]['model'], True)
check('and it closes with the summary', kinds[-1], 'done')
check('carrying what was dropped', lines[-1]['filterStats']['dropped'], 1)

civitai(raises=RuntimeError('stream broke'))
with client.stream('GET', '/model-manager/civitai/models/stream') as response:
    lines = [json.loads(line) for line in response.iter_lines() if line.strip()]
check('a stream that fails says so in the stream', lines[-1]['type'], 'error')
check('rather than as a status code', response.status_code, 200)
check('with the reason', lines[-1]['error'], 'stream broke')

# ------------------------------------------------- searching by file size
# Civitai cannot filter on size, so the endpoint checks each result's
# latest version's primary file and fills the page from what fits.
def sized(model_id, size_gb):
    m = remote(model_id, model_id + 1)
    m['modelVersions'][0]['files'][0]['sizeKB'] = size_gb * 1024 * 1024
    return m

civitai(models={'items': [sized(90050, 0.1), sized(90060, 6.5), sized(90070, 2.0)],
                'nextCursor': None})
status, body = get('/model-manager/civitai/models', min_size_gb='1', max_size_gb='7', limit=5)
check('a size range keeps what is inside it', [m['id'] for m in body['models']], [90060, 90070])
check('and reports what it passed over', body['filterStats']['rejected'], 1)
check('saying the size filter was on and the prompt filter was not',
      (body['filterStats']['sizeFilter'], body['filterStats']['promptFilter']), (True, False))
check('without a single image lookup',
      [c for c in Stub.calls if c[0] == 'get_model_images'], [])
asked = [c[1] for c in Stub.calls if c[0] == 'search_models'][-1]
check('asking Civitai for as much as it gives per call', asked['limit'], 100)
check('and never asking it about size, which it would not understand',
      [k for k in asked if 'size' in k], [])

civitai(models={'items': [sized(90050, 0.1)], 'nextCursor': None})
status, body = get('/model-manager/civitai/models', min_size_gb='0', max_size_gb='0')
check('zero on both sides is no filter', body['filterStats'], None)

# The model with prompts, now with a size to judge it by; without one it is
# in no range at all.
import copy                                                   # noqa: E402
SMALL_WITH_PROMPTS = copy.deepcopy(WITH_PROMPTS)
SMALL_WITH_PROMPTS['modelVersions'][0]['files'][0]['sizeKB'] = 0.1 * 1024 * 1024

civitai(models={'items': [SMALL_WITH_PROMPTS, WITHOUT, sized(90080, 6.5)], 'nextCursor': None})
status, body = get('/model-manager/civitai/models', require_prompt='true',
                   max_size_gb='1', limit=5)
check('with both filters, both apply', [m['id'] for m in body['models']], [90010])
check('the size filter goes first, so the big one is never prompt-checked',
      [c[1] for c in Stub.calls if c[0] == 'get_model_images' and c[1] == 90081], [])

civitai(models={'items': [SMALL_WITH_PROMPTS, sized(90080, 6.5)], 'nextCursor': None})
with client.stream('GET', '/model-manager/civitai/models/stream',
                   params={'limit': 5, 'max_size_gb': 1}) as response:
    lines = [json.loads(line) for line in response.iter_lines() if line.strip()]
check('the stream takes the range too',
      [line['model']['id'] for line in lines if line['type'] == 'model'], [90010])
check('and reports it', lines[-1]['filterStats']['rejected'], 1)

# Size alone streams too, since a narrow range can take several searches.
civitai(models={'items': [sized(90050, 0.1), sized(90060, 6.5)], 'nextCursor': None})
with client.stream('GET', '/model-manager/civitai/models/stream',
                   params={'limit': 5, 'max_size_gb': 1, 'require_prompt': 'false'}) as response:
    lines = [json.loads(line) for line in response.iter_lines() if line.strip()]
check('told not to check prompts, the stream filters on size alone',
      [line['model']['id'] for line in lines if line['type'] == 'model'], [90050])
check('without looking at a single image',
      [c for c in Stub.calls if c[0] == 'get_model_images'], [])
check('saying so in its summary',
      (lines[-1]['filterStats']['promptFilter'], lines[-1]['filterStats']['sizeFilter']),
      (False, True))
check('asking Civitai for as much as it gives per call',
      [c[1] for c in Stub.calls if c[0] == 'search_models'][-1]['limit'], 100)

# ------------------------------------------------- Only Show Models with SFW images
# Each candidate's first images are looked at; one above PG-13 rules it out.
from model_manager.api import prompts as prompt_checks          # noqa: E402

def gallery_for(version_id, cursor=None, limit=None):
    levels = {90091: [1, 2], 90093: [1, 8]}.get(version_id, [1])
    return {'images': [{'id': version_id * 10 + n, 'browsingLevel': level, 'meta': None}
                       for n, level in enumerate(levels)], 'next_cursor': None}

Stub.get_model_images = lambda self, version_id, cursor=None, limit=None: (
    Stub.calls.append(('get_model_images', version_id)) or gallery_for(version_id))

SAFE, RACY = remote(90090, 90091), remote(90092, 90093)

prompt_checks.forget_sfw_verdicts()
civitai(models={'items': [SAFE, RACY], 'nextCursor': None})
status, body = get('/model-manager/civitai/models', sfw_only='true', limit=5)
check('Only Show Models with SFW images keeps the model whose examples are all safe',
      [m['id'] for m in body['models']], [90090])
check('reporting what it left out', (body['filterStats']['unsafe'],
                                      body['filterStats']['sfwFilter']), (1, True))

prompt_checks.forget_sfw_verdicts()
civitai(models={'items': [SAFE, RACY], 'nextCursor': None})
status, body = get('/model-manager/civitai/models', sfw_only='true', nsfw='true', limit=5)
check('with NSFW models included it means nothing, and is ignored',
      [m['id'] for m in body['models']], [90090, 90092])
check('without a single image being fetched for it',
      [c for c in Stub.calls if c[0] == 'get_model_images'], [])

prompt_checks.forget_sfw_verdicts()
civitai(models={'items': [SAFE, RACY], 'nextCursor': None})
with client.stream('GET', '/model-manager/civitai/models/stream',
                   params={'limit': 5, 'sfw_only': 'true', 'require_prompt': 'false'}) as response:
    lines = [json.loads(line) for line in response.iter_lines() if line.strip()]
check('the stream takes it too',
      [line['model']['id'] for line in lines if line['type'] == 'model'], [90090])
check('and says so', (lines[-1]['filterStats']['sfwFilter'],
                      lines[-1]['filterStats']['unsafe'],
                      lines[-1]['filterStats']['promptFilter']), (True, 1, False))

# ------------------------------------------- filling every page, if asked
# Most models fail the SFW check, so a page normally stops after its checks
# (20 here, for a page of 2) and comes back short. The setting lifts that.
# Twenty-five models with an NSFW image, then two without.
MANY = [remote(91000 + 2 * n, 91001 + 2 * n) for n in range(25)] + \
       [remote(91100, 91101), remote(91102, 91103)]
Stub.get_model_images = lambda self, version_id, cursor=None, limit=None: (
    Stub.calls.append(('get_model_images', version_id)) or
    {'images': [{'id': version_id, 'browsingLevel': 1 if version_id > 91100 else 8,
                 'meta': None}], 'next_cursor': None})

prompt_checks.forget_sfw_verdicts()
civitai(models={'items': MANY, 'nextCursor': None})
status, body = get('/model-manager/civitai/models', sfw_only='true', limit=2)
check('by default an SFW page stops after its checks and comes back short',
      (body['models'], body['filterStats']['budgetReached'], body['filterStats']['checked']),
      ([], True, 20))

opts.model_manager_civitai_sfw_fill_page = True
try:
    prompt_checks.forget_sfw_verdicts()
    civitai(models={'items': MANY, 'nextCursor': None})
    status, body = get('/model-manager/civitai/models', sfw_only='true', limit=2)
    check('with the setting on, it keeps going until the page is full',
          ([m['id'] for m in body['models']], body['filterStats']['budgetReached']),
          ([91100, 91102], False))

    prompt_checks.forget_sfw_verdicts()
    civitai(models={'items': MANY, 'nextCursor': None})
    with client.stream('GET', '/model-manager/civitai/models/stream',
                       params={'limit': 2, 'sfw_only': 'true', 'require_prompt': 'false'}) as response:
        lines = [json.loads(line) for line in response.iter_lines() if line.strip()]
    check('the stream as well',
          [line['model']['id'] for line in lines if line['type'] == 'model'], [91100, 91102])

    # Only in SFW mode. Everything else keeps its limits.
    from model_manager.api.civitai import (                 # noqa: E402
        MAX_FILTER_SEARCHES, _filter_options, size_range_check)

    class Quiet:
        wait_on_rate_limit = True

    def limits(**kw):
        base = dict(require_prompt=False, sfw_only=False, nsfw=False, size_check=None,
                    limit=20, min_usable=1, fill_page=True)
        base.update(kw)
        _, o = _filter_options(Quiet(), **base)
        return o['max_checks'], o['max_searches']

    check('the setting lifts both limits in SFW mode', limits(sfw_only=True), (None, None))
    check('but not for the prompt filter alone', limits(require_prompt=True),
          (80, MAX_FILTER_SEARCHES))
    check('nor for a size range alone', limits(size_check=size_range_check(0, 1)),
          (80, MAX_FILTER_SEARCHES))
    check('nor when NSFW models are included, where SFW mode does not apply',
          limits(sfw_only=True, nsfw=True), (80, MAX_FILTER_SEARCHES))
    check('and with the setting off, SFW mode keeps them',
          limits(sfw_only=True, fill_page=False), (80, MAX_FILTER_SEARCHES))
finally:
    opts.model_manager_civitai_sfw_fill_page = False

Stub.get_model_images = _scripted_images

# ---------------------------------------------------------------- one model
civitai(model=remote(OWNED_MODEL, OWNED_VERSION))
status, body = get('/model-manager/civitai/models/%d' % OWNED_MODEL)
check('a model answers', (status, body['success']), (200, True))
check('and knows it is already here', body['model']['owned_locally'], True)
check('naming the version', body['model']['owned_versions'], [OWNED_VERSION])
check('and marking it on the version too',
      body['model']['modelVersions'][0]['owned_locally'], True)
check('free versions are marked free',
      body['model']['modelVersions'][0]['paid_access'], None)

civitai(model=remote(90030, 90031))
status, body = get('/model-manager/civitai/models/90030')
check('a model nobody here owns says so', body['model']['owned_locally'], False)
check('with no owned versions', body['model']['owned_versions'], [])

civitai(model=remote(90040, 90041, paidAccess={'permanent': True}))
status, body = get('/model-manager/civitai/models/90040')
check('a paid version is flagged before the user clicks download',
      body['model']['modelVersions'][0]['paid_access'], {'permanent': True,
                                                         'ends_at': None})

civitai(model={'id': 90050, 'name': 'No versions'})
status, body = get('/model-manager/civitai/models/90050')
check('a model with no versions is still served', status, 200)
check('owning none of it', body['model']['owned_locally'], False)

civitai(model=None)
status, body = get('/model-manager/civitai/models/90060')
check('a model Civitai does not have is a 404', status, 404)
check('saying so', body['error'], 'Model not found')

civitai(raises=RuntimeError('lookup failed'))
status, body = get('/model-manager/civitai/models/90070')
check('and a lookup that fails is a 500', status, 500)

# A search result's showcase images - a card picks its cover from them - come
# judged too.
civitai(models={'items': [remote(90201, 90202, images=[
    {'id': 5, 'url': 'u5', 'browsingLevel': 1, 'meta': USABLE},
    {'id': 6, 'url': 'u6', 'browsingLevel': 16, 'meta': USABLE}])], 'nextCursor': None})
status, body = get('/model-manager/civitai/models', query='judged')
check('a search result\'s showcase images carry the server\'s verdict',
      [i.get('mm_level') for i in body['models'][0]['modelVersions'][0]['images']], [1, 16])
civitai(model=remote(90203, 90204, images=[{'id': 8, 'url': 'u8', 'browsingLevel': 4}]))
status, body = get('/model-manager/civitai/models/90203')
check('so does a model looked up by id',
      body['model']['modelVersions'][0]['images'][0].get('mm_level'), 4)

# ----------------------------------------------------------------- the gallery
# A page is the next page-size images of Civitai's, after the cursor the last
# page ended at, before the switches - which only decide which are shown. Nothing
# is kept: it used to page a cache of every image ever fetched, never cleared.
shared_opts = sys.modules['modules.shared'].opts


def cache_rows():
    with db._cursor() as cursor:
        return cursor.execute('SELECT COUNT(*) FROM civitai_browser_cache').fetchone()[0]


class Gallery:
    """Civitai's gallery for a version: the cursor is an offset, and at offset
    `short` it gives one image whatever it is asked, with more to come - as
    Civitai does, 80 where 100 were asked for."""

    def __init__(self, images, short=None, fail_at=None):
        self.images, self.short, self.fail_at = images, short, fail_at
        self.asked = []

    def __call__(self, version_id, cursor=None, limit=None):
        Stub.calls.append(('get_model_images', version_id, cursor, limit))
        start = int(cursor or 0)
        self.asked.append((cursor, limit))
        if self.fail_at is not None and start == self.fail_at:
            raise RuntimeError('Civitai: overloaded (503)')
        batch = self.images[start:start + (1 if start == self.short else limit)]
        end = start + len(batch)
        return {'images': [dict(i) for i in batch],
                'next_cursor': str(end) if end < len(self.images) else None}


def image(n, level=1, meta=USABLE):
    return {'id': 95000 + n, 'url': 'p%d' % n, 'browsingLevel': level, 'meta': meta}


rows_before = cache_rows()
shared_opts.model_manager_gallery_page_size = 2
gallery = Gallery([image(n) for n in range(5)], short=2)
Stub.get_model_images = staticmethod(gallery)
civitai(generation={})
status, body = get('/model-manager/civitai/versions/90080/images')
check('page 1 is Civitai\'s first page-size images, from the start',
      ([i['id'] for i in body['images']], gallery.asked), ([95000, 95001], [(None, 2)]))
check('with the cursor to the page after it', (body['next_cursor'], body['page']['more']), ('2', True))
check('each judged here, for the browser to read - it does not judge',
      [('mm_level' in i, 'mm_level_from_prompt' in i) for i in body['images']], [(True, True)] * 2)

gallery.asked = []
status, body = get('/model-manager/civitai/versions/90080/images', page=2, cursor='2')
check('the next page starts at that cursor, and a short batch is followed by another',
      ([i['id'] for i in body['images']], gallery.asked), ([95002, 95003], [('2', 2), ('3', 1)]))
check('numbered as asked', body['page']['number'], 2)

gallery.asked = []
status, body = get('/model-manager/civitai/versions/90080/images', page=3, cursor='4')
check('the last page says Civitai has no more',
      ([i['id'] for i in body['images']], body['next_cursor'], body['page']['more']),
      ([95004], None, False))

# Civitai gives at most 100 images a request, whatever it is asked: 150, 200
# and 201 all came back as 100. A larger page is asked for in parts.
shared_opts.model_manager_gallery_page_size = 150
gallery = Gallery([image(n, meta=None) for n in range(300)])
Stub.get_model_images = staticmethod(gallery)
forget()
status, body = get('/model-manager/civitai/versions/90081/images')
check('a page larger than Civitai gives is asked for 100, then the rest',
      (gallery.asked, body['page']['count']), ([(None, 100), ('100', 50)], 150))
check('and its prompts looked up in one go, not one request per part',
      [c[0] for c in Stub.calls].count('get_generation_data'), 1)
shared_opts.model_manager_gallery_page_size = 100

# The switches: which of the page's images are shown, and its counts.
gallery = Gallery([image(n, level=8 if n % 4 == 0 else 1, meta=USABLE if n % 3 else None)
                   for n in range(150)])
Stub.get_model_images = staticmethod(gallery)
status, body = get('/model-manager/civitai/versions/90140/images')
check('with no switch sent, nothing is hidden',
      ([i['id'] for i in body['images']], body['page']['count'], body['page']['more']),
      ([95000 + n for n in range(100)], 100, True))
status, body = get('/model-manager/civitai/versions/90140/images', page=2, cursor='100',
                   hide_nsfw_images='true', hide_promptless_images='true')
kept = [95000 + n for n in range(100, 150) if n % 4 and n % 3]
check('page 2 is the rest, through the switches', [i['id'] for i in body['images']], kept)
check('its note counts what each switch hid, and each kind it holds, for the banner to add up',
      {k: body['page'][k] for k in ('number', 'count', 'shown', 'hidden_nsfw',
                                    'hidden_promptless', 'nsfw_count', 'promptless_count', 'more')},
      {'number': 2, 'count': 50, 'shown': len(kept), 'hidden_nsfw': 13,
       'hidden_promptless': 50 - 13 - len(kept), 'nsfw_count': 9,
       'promptless_count': 50 - 13 - len(kept), 'more': False})

# Failures: the first request is the whole page; a later one leaves a part.
shared_opts.model_manager_gallery_page_size = 2
Stub.get_model_images = staticmethod(Gallery([image(n) for n in range(5)], fail_at=0))
status, body = get('/model-manager/civitai/versions/90110/images')
check('a page Civitai will not give is a 500, saying why',
      (status, body['error']), (500, 'Civitai: overloaded (503)'))
Stub.get_model_images = staticmethod(Gallery([image(n) for n in range(5)], short=2, fail_at=3))
status, body = get('/model-manager/civitai/versions/90110/images', page=2, cursor='2')
check('one that fails part-way is what came, with the error, and where to go on from',
      ([i['id'] for i in body['images']], body['page']['error'], body['next_cursor']),
      ([95002], 'Civitai: overloaded (503)', '3'))
shared_opts.model_manager_gallery_page_size = 100

Stub.get_model_images = staticmethod(Gallery([]))
status, body = get('/model-manager/civitai/versions/90100/images')
check('a version with no images at all is not an error',
      (status, body['page']['count'], body['page']['more']), (200, 0, False))

check('and none of it is written down', cache_rows(), rows_before)
check('nor is there an endpoint to load more from a stored cursor, or read what was stored',
      [client.post('/model-manager/civitai/versions/90080/images/load-more',
                   data={'model_id': 1}).status_code,
       client.get('/model-manager/civitai/versions/90080/images/cached').status_code],
      [404, 404])
Stub.get_model_images = _scripted_images

# ------------------------------------------------------------------ downloads
class FakeDownloads:
    def __init__(self):
        self.queued = []
        self.cancelled = []
        self.all_cancelled = 0
        self.progress = {}

    def queue_download(self, version_id, model_data, version_data,
                       file_index=None, file_id=None):
        self.queued.append((version_id, version_data.get('id'), file_index, file_id))
        record = ds.DownloadProgress(version_id=version_id, file_name='m.safetensors')
        self.progress[version_id] = record
        return record

    def get_progress(self, version_id):
        return self.progress.get(version_id)

    def get_all_progress(self):
        return [p.to_dict() for p in self.progress.values()]

    def cancel(self, version_id):
        self.cancelled.append(version_id)

    def cancel_all(self):
        self.all_cancelled += 1


downloads = FakeDownloads()
ds.get_download_service = lambda: downloads

civitai(model=remote(90140, 90141))
status, body = post('/model-manager/civitai/download', version_id=90141, model_id=90140)
check('a download is queued', (status, body['success']), (200, True))
check('for the version that was asked for', downloads.queued[-1][:2], (90141, 90141))
check('and the UI is handed something to poll', body['progress']['version_id'], 90141)

post('/model-manager/civitai/download', version_id=90141, model_id=90140, file_id=7)
check('the file the picker chose is passed along', downloads.queued[-1][3], 7)
post('/model-manager/civitai/download', version_id=90141, model_id=90140, file_index=1)
check('and so is a file position', downloads.queued[-1][2], 1)

status, body = post('/model-manager/civitai/download', version_id=99999, model_id=90140)
check('a version the model does not have is a 404', status, 404)
check('saying which half was missing', body['error'], 'Version not found')

civitai(model=None)
status, body = post('/model-manager/civitai/download', version_id=1, model_id=90150)
check('a model Civitai does not have is a 404 too', status, 404)
check('and says so', body['error'], 'Model not found on Civitai')

civitai(raises=RuntimeError('download setup failed'))
status, body = post('/model-manager/civitai/download', version_id=1, model_id=90160)
check('anything else is a 500', status, 500)

status, body = get('/model-manager/civitai/download/progress', version_id=90141)
check('progress for one download answers', body['progress']['version_id'], 90141)
status, body = get('/model-manager/civitai/download/progress', version_id=404404)
check('one nobody started is None, not an error', body['progress'], None)
check('with an explanation', 'No download found' in body['message'], True)
status, body = get('/model-manager/civitai/download/progress')
check('and all of them at once', len(body['downloads']), 1)

status, body = post('/model-manager/civitai/download/cancel', version_id=90141)
check('a cancel reaches the service', downloads.cancelled, [90141])
check('and is acknowledged', body['success'], True)
status, body = post('/model-manager/civitai/download/cancel')
check('and no id cancels everything', downloads.all_cancelled, 1)


def broken_service():
    raise RuntimeError('no download service')


ds.get_download_service = broken_service
check('progress with no service is a 500',
      get('/model-manager/civitai/download/progress')[0], 500)
check('and so is a cancel',
      post('/model-manager/civitai/download/cancel', version_id=1)[0], 500)
ds.get_download_service = lambda: downloads

# ------------------------------------------------- downloads from an image
# The Resources dialog downloads the version an image names. Its resources
# do not always carry the model id, and uploaders delete versions: the image's
# version is then gone for good, and the model's newest is downloaded instead.
def two_versions(model_id, newest, older):
    model = remote(model_id, newest)
    model['modelVersions'].append(dict(remote(model_id, older)['modelVersions'][0], name='v0'))
    model['modelVersions'][0]['name'] = 'v2'
    return model

civitai(model=two_versions(90170, 90172, 90171), version={'id': 90171, 'modelId': 90170})
status, body = post('/model-manager/civitai/download', version_id=90171)
check('with no model id, Civitai is asked whose version it is',
      [c for c in Stub.calls if c[0] in ('get_model_version', 'get_model')],
      [('get_model_version', 90171), ('get_model', 90170)])
check('and that very version is downloaded', (downloads.queued[-1][:2], body['version_id'],
      body['substituted']), ((90171, 90171), 90171, False))

civitai(version=None)
status, body = post('/model-manager/civitai/download', version_id=90179)
check('a version Civitai does not know, with no model id, is a 404',
      (status, body['error']), (404, 'Version not found on Civitai'))

civitai(model=two_versions(90170, 90172, 90171))
status, body = post('/model-manager/civitai/download', version_id=90175, model_id=90170,
                    newer_if_gone='true')
check('a version gone from its model: the model\'s newest is downloaded instead',
      (downloads.queued[-1][:2], body['version_id'], body['version_name'], body['substituted']),
      ((90172, 90172), 90172, 'v2', True))
check('and progress is for that one', body['progress']['version_id'], 90172)
status, body = post('/model-manager/civitai/download', version_id=90175, model_id=90170)
check('only when asked: the Civitai Browser still gets a 404', status, 404)

before = len(downloads.queued)
civitai(model=remote(OWNED_MODEL, OWNED_VERSION))
status, body = post('/model-manager/civitai/download', version_id=OWNED_VERSION,
                    model_id=OWNED_MODEL, newer_if_gone='true')
check('a version this library has is not downloaded again',
      (body['success'], body.get('already_installed'), len(downloads.queued)), (True, True, before))

# ---------------------------------------------------------------------- tags
civitai(tags={'items': [{'name': 'anime'}, {'name': 'realistic'}, {'no': 'name'}]})
status, body = get('/model-manager/civitai/tags', query='ani')
check('tags answer with just their names', body['tags'], ['anime', 'realistic'])

forget()
status, body = get('/model-manager/civitai/tags', query='an')
check('a query too short to be useful asks nothing', body['tags'], [])
check('and really asks nothing', [c for c in Stub.calls if c[0] == 'search_tags'], [])

civitai(raises=RuntimeError('tags failed'))
status, body = get('/model-manager/civitai/tags', query='anime')
check('a tag search that fails is a 500 with an empty list',
      (status, body['tags']), (500, []))

# --------------------------------------------------------------------- enums
endpoints._enums_cache = None
endpoints._enums_cached_at = 0.0
civitai(enums={'ModelType': ['Checkpoint', 'LORA'],
               'ActiveBaseModel': ['SDXL 1.0'],
               'BaseModel': ['SDXL 1.0', 'SD 1.4']})
status, body = get('/model-manager/civitai/enums')
check('the enums answer', body['model_types'], ['Checkpoint', 'LORA'])
check('preferring the base models Civitai has not retired',
      body['base_models'], ['SDXL 1.0'])

forget()
status, body = get('/model-manager/civitai/enums')
check('and are cached, so the second ask costs nothing',
      [c for c in Stub.calls if c[0] == 'get_enums'], [])

endpoints._enums_cache = None
civitai(enums={'ModelType': [], 'BaseModel': ['SD 1.5']})
status, body = get('/model-manager/civitai/enums')
check('with no active list, the full one is used', body['base_models'], ['SD 1.5'])

endpoints._enums_cache = None
civitai(enums=None)
status, body = get('/model-manager/civitai/enums')
check('and an answer with nothing in it is empty, not broken',
      (body['model_types'], body['base_models']), ([], []))

endpoints._enums_cache = None
civitai(raises=RuntimeError('enums failed'))
status, body = get('/model-manager/civitai/enums')
check('enums that fail leave the dropdowns to their static options',
      (status, body['model_types'], body['base_models']), (500, [], []))
endpoints._enums_cache = None

# ------------------------------------------------------ the annotations alone
check('annotating nothing does nothing', annotate_local_ownership(db, []), None)

no_ids = [{'name': 'anonymous'}]
annotate_local_ownership(db, no_ids)
check('a model with no id owns nothing', no_ids[0]['owned_locally'], False)
check('and no versions', no_ids[0]['owned_versions'], [])

versionless = [{'id': OWNED_MODEL}]
annotate_local_ownership(db, versionless)
check('a model known locally is owned even with no versions listed',
      versionless[0]['owned_locally'], True)

deadline = [{'id': 1, 'modelVersions': [
    {'id': 2, 'earlyAccessDeadline': '2026-11-01T00:00:00Z'},
    {'id': 3, 'paidAccess': {'permanent': False, 'endsAt': '2026-12-01T00:00:00Z'}},
    {'id': 4}]}]
annotate_paid_access(deadline)
paid = [v['paid_access'] for v in deadline[0]['modelVersions']]
check('a bare deadline is early access', paid[0],
      {'permanent': False, 'ends_at': '2026-11-01T00:00:00Z'})
check('so is one inside paidAccess', paid[1],
      {'permanent': False, 'ends_at': '2026-12-01T00:00:00Z'})
check('and a version with neither is free', paid[2], None)
check('a model with no versions is left alone',
      annotate_paid_access([{'id': 1}]), None)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
