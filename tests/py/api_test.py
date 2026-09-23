"""
The endpoints the browser actually calls, exercised through the app.

check_api_contract.py already proves the parameter names match what the tabs
send. This runs them: the filter parsing in models.py alone is nearly three
hundred statements deciding what the grid shows, and none of it had ever been
executed by a test.
"""
import json
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

WORK = os.path.join(TESTS, 'work', 'api')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db

app = FastAPI()
setup_api(app)
client = TestClient(app)


def get(url, **params):
    # `url`, not `path`: several endpoints take a query parameter called path.
    r = client.get(url, params=params)
    return r.status_code, (r.json() if r.headers.get('content-type', '').startswith('application/json') else {})


def post(url, **data):
    r = client.post(url, data=data)
    return r.status_code, (r.json() if r.headers.get('content-type', '').startswith('application/json') else {})


# ------------------------------------------------------------------- the grid
code, body = get('/model-manager/models')
check('the grid answers', code, 200)
check('and succeeds', body.get('success'), True)
check('with every model in the fixture, plus the ungrouped local files',
      body.get('total'), fixtures.MODELS + fixtures.LOCAL_ONLY)
check('paged', body.get('page'), 1)
check('and says whether there is more', 'has_more' in body, True)

code, body = get('/model-manager/models', page_size=2, page=2)
check('paging returns a page', len(body.get('models', [])), 2)
check('and keeps the total', body.get('total'),
      fixtures.MODELS + fixtures.LOCAL_ONLY)

code, body = get('/model-manager/models', type='Checkpoint')
check('filtering by type', body.get('total'), fixtures.CHECKPOINTS)

code, body = get('/model-manager/models', type='LORA')
check('and by another type', body.get('total'), fixtures.LORAS)

code, body = get('/model-manager/models', checkpoint_type='Trained')
check('by trained checkpoints', body.get('total'), fixtures.TRAINED)
code, body = get('/model-manager/models', checkpoint_type='Merge')
check('by merged ones', body.get('total'), fixtures.MERGED)

code, body = get('/model-manager/models', nsfw_levels='PG', nsfw_mode='max')
pg_only = body.get('total')
code, body = get('/model-manager/models', nsfw_levels='XXX', nsfw_mode='max')
check('a wider NSFW ceiling admits at least as much', body.get('total') >= pg_only, True)

code, body = get('/model-manager/models', search='Model %d' % facts['checkpoint_ids'][0])
check('searching by name finds one', body.get('total'), 1)

code, body = get('/model-manager/models', has_civitai='No')
check('models with no Civitai data are findable', body.get('total') >= 1, True)

code, body = get('/model-manager/models', sort_by='name', sort_order='asc')
names = [m.get('display_name') or m.get('name') for m in body.get('models', [])]
check('sorting by name is ordered', names, sorted(names, key=lambda s: (s or '').lower()))

code, body = get('/model-manager/models', paths_only=True, type='Checkpoint')
check('paths_only answers with paths', code, 200)
check('and nothing but paths', sorted(body), ['models', 'paths', 'success'])
check('covering the checkpoints', len(body['paths']) >= fixtures.CHECKPOINTS, True)

# ---------------------------------------------------------------- the filters
for endpoint in ('/model-manager/filters', '/model-manager/filter-defaults',
                 '/model-manager/stats'):
    code, body = get(endpoint)
    check('%s answers' % endpoint, code, 200)
    check('%s succeeds' % endpoint, body.get('success'), True)

code, body = get('/model-manager/stats')
stats = body.get('stats', {})
check('the stats count every version', stats.get('total_versions'), fixtures.VERSIONS)
check('and the models behind them', stats.get('total_civitai_models'), fixtures.MODELS)
check('and split identified from not',
      (stats.get('with_civitai_data'), stats.get('without_civitai_data')),
      (fixtures.LINKED_VERSIONS, fixtures.LOCAL_ONLY))

# ----------------------------------------------------------------- one model
first_path = facts['linked_paths'][0]
code, body = get('/model-manager/models/details', path=first_path)
check('details answer', code, 200)
check('and succeed', body.get('success'), True)
check('with the file it was asked about',
      body.get('model', {}).get('file_path'), first_path)

code, body = get('/model-manager/models/details', path=r'Z:\nope\missing.safetensors')
check('details for an unknown file do not pretend', body.get('success'), False)

code, body = get('/model-manager/models/versions', model_id=facts['checkpoint_ids'][0])
check('versions answer', code, 200)
check('with at least one', len(body.get('versions', [])) >= 1, True)

# resolve-hash asks Civitai rather than the database, so stand in for it.
import model_manager.api.models as models_api

class _Resolver:
    def __init__(self, answer):
        self.answer = answer
    @classmethod
    def from_settings(cls):
        return cls(_Resolver.answer_for_next)
    def get_model_by_hash(self, value):
        return self.answer
    def close(self):
        pass

real_client = models_api.CivitaiClient
models_api.CivitaiClient = _Resolver

_Resolver.answer_for_next = {'id': 55, 'modelId': 66, 'name': 'v2',
                             'model': {'name': 'Something'}}
code, body = get('/model-manager/resolve-hash', hash='A' * 64)
check('a hash Civitai knows resolves', body.get('success'), True)
check('to its version', body.get('version_id'), 55)
check('and its model', (body.get('model_id'), body.get('model_name')), (66, 'Something'))

_Resolver.answer_for_next = None
code, body = get('/model-manager/resolve-hash', hash='0' * 64)
check('one it does not know says so', body.get('success'), False)
check('with a 404', code, 404)

code, body = get('/model-manager/resolve-hash', hash='short')
check('and too short a hash is refused before asking', body.get('success'), False)

models_api.CivitaiClient = real_client

# --- resolving a whole list of resource hashes ------------------------------
# An image names its resources twice and the two lists share no key, so the
# panel merges them by turning AutoV2 hashes into version ids. Answered from
# this library's own rows first, then from what an earlier lookup recorded,
# and only then from Civitai - which has no batch endpoint for hashes, so each
# one costs a request and is worth writing down.

class _Counter:
    """Civitai, counting how many times it was actually asked."""
    answers = {}
    asked = []

    @classmethod
    def from_settings(cls):
        return cls()

    def get_model_by_hash(self, value):
        _Counter.asked.append(value)
        return _Counter.answers.get(value.lower())

    def close(self):
        pass


models_api.CivitaiClient = _Counter

# A hash this library already owns: the version row carries both the id and the
# AutoV2, so nothing needs to be asked.
owned_version = facts['version_ids'][0]
owned_hash = ('%010x' % owned_version).upper()

_Counter.answers = {}
_Counter.asked = []
status, body = post('/model-manager/resolve-hashes', hashes=owned_hash)
check('a hash we own resolves', body['success'], True)
check('to the version it belongs to',
      body['resolved'][owned_hash.lower()]['version_id'], owned_version)
check('without asking Civitai at all', _Counter.asked, [])

# One Civitai knows, and one it does not.
_Counter.answers = {'aaaaaaaaaa': {'id': 700, 'modelId': 800, 'name': 'v1',
                                   'model': {'name': 'Fetched', 'type': 'LORA'}}}
_Counter.asked = []
status, body = post('/model-manager/resolve-hashes', hashes='AAAAAAAAAA,bbbbbbbbbb')
resolved = body['resolved']
check('an unknown hash is fetched', resolved['aaaaaaaaaa']['version_id'], 700)
check('carrying the model name', resolved['aaaaaaaaaa']['name'], 'Fetched')
check('and a link to download it',
      resolved['aaaaaaaaaa']['download_url'].endswith('/700'), True)
check('one Civitai does not know is present, with nothing behind it',
      resolved['bbbbbbbbbb']['version_id'], None)
check('both were asked about once', sorted(_Counter.asked), ['aaaaaaaaaa', 'bbbbbbbbbb'])

# Asked again, neither costs anything - including the one that found nothing,
# which is the whole point of recording a negative answer.
_Counter.asked = []
status, body = post('/model-manager/resolve-hashes', hashes='aaaaaaaaaa,bbbbbbbbbb')
check('the answers were remembered', body['resolved']['aaaaaaaaaa']['version_id'], 700)
check('and the dead hash too', body['resolved']['bbbbbbbbbb']['version_id'], None)
check('so Civitai is not asked twice', _Counter.asked, [])

# Case and duplicates in one request.
_Counter.asked = []
status, body = post('/model-manager/resolve-hashes', hashes='AAAAAAAAAA,aaaaaaaaaa, ')
check('a hash is asked about once however it is written', len(body['resolved']), 1)
check('and nothing was fetched again', _Counter.asked, [])

# An empty field is dropped by the client altogether, so asking about nothing
# has to be an answer rather than a 422.
status, body = post('/model-manager/resolve-hashes', hashes='')
check('no hashes, no work', (status, body.get('resolved')), (200, {}))


class _Broken(_Counter):
    def get_model_by_hash(self, value):
        raise RuntimeError('Civitai is down')


models_api.CivitaiClient = _Broken
status, body = post('/model-manager/resolve-hashes', hashes='cccccccccc')
check('a lookup that fails leaves the hash unresolved rather than wrong',
      'cccccccccc' in body['resolved'], False)
check('and still answers', body['success'], True)

models_api.CivitaiClient = _Counter
_Counter.asked = []
status, body = post('/model-manager/resolve-hashes', hashes='cccccccccc')
check('a failure is not remembered as an answer', _Counter.asked, ['cccccccccc'])

models_api.CivitaiClient = real_client

# ---------------------------------------------------------------- bookmarking
model_id = facts['checkpoint_ids'][0]
code, body = post('/model-manager/bookmark', model_id=model_id, bookmarked='true')
check('bookmarking answers', code, 200)
check('and takes', body.get('success'), True)
code, body = get('/model-manager/models', is_bookmarked=True)
check('the bookmark filters', body.get('total'), 1)
post('/model-manager/bookmark', model_id=model_id, bookmarked='false')
code, body = get('/model-manager/models', is_bookmarked=True)
check('and unbookmarking undoes it', body.get('total'), 0)

# -------------------------------------------------------------------- images
version_id = facts['version_ids'][0]
code, body = get('/model-manager/images/cached', version_id=version_id)
check('cached images answer', code, 200)
check('with what the fixture stored',
      len(body.get('images', [])), fixtures.IMAGES_PER_VERSION)

code, body = get('/model-manager/images/cached', version_id=999999)
check('a version with none answers empty', body.get('images'), [])

# --------------------------------------------------------------- the WebUI's
code, body = get('/model-manager/ui-options')
check('ui-options answers', code, 200)
check('and reports no key, which the stub has', body.get('has_api_key'), False)

webui_stub.install(model_manager_civitai_api_key='a-key')
code, body = get('/model-manager/ui-options')
check('and reports one when set', body.get('has_api_key'), True)
webui_stub.install()

# ------------------------------------------------------------------ deleting
victim = facts['local_only_paths'][0]
check('the file is there to begin with', os.path.exists(victim), True)
code, body = post('/model-manager/models/delete', path=victim)
check('deleting answers', code, 200)
check('and succeeds', body.get('success'), True)
check('the file is gone', os.path.exists(victim), False)
code, body = get('/model-manager/models/details', path=victim)
check('and so is its row', body.get('success'), False)

code, body = post('/model-manager/models/delete', path=r'Z:\nope\missing.safetensors')
check('deleting nothing answers 404 rather than crashing', code, 404)
check('and says so', body.get('success'), False)

# --- hiding images with no prompt -------------------------------------------
# Filtered in SQL rather than in the browser, so the counts come from the same
# place the images do. A prompt shorter than MIN_PROMPT_LENGTH is not one:
# measured over a real library, what sits below four characters is "1", ".",
# "???" - never something a person wrote.
from model_manager.civitai.prompt_filter import MIN_PROMPT_LENGTH   # noqa: E402

VERSION = facts['version_ids'][0]
db.clear_version_images(VERSION)
db.store_images(VERSION, page=1, images=[
    {'id': 90001, 'url': 'u1', 'browsingLevel': 1,
     'meta': {'prompt': 'a long enough prompt', 'steps': 20}},
    {'id': 90002, 'url': 'u2', 'browsingLevel': 1, 'meta': {'prompt': '   '}},
    {'id': 90003, 'url': 'u3', 'browsingLevel': 1, 'meta': None},
    {'id': 90004, 'url': 'u4', 'browsingLevel': 1, 'meta': {'prompt': '1'}},
    {'id': 90005, 'url': 'u5', 'browsingLevel': 1,
     'meta': {'prompt': ' ' * 5 + 'cat'}},
    {'id': 90006, 'url': 'u6', 'browsingLevel': 1, 'meta': {'prompt': 'tree'}},
])

kept = [i['id'] for i in db.get_all_images_for_version(VERSION, require_prompt=True)]
check('a prompt worth reading is kept', 90001 in kept)
check('one exactly at the floor is kept', 90006 in kept)
check('whitespace is trimmed before measuring, so a padded short one is not',
      90005 in kept, False)
check('nor a blank prompt', 90002 in kept, False)
check('nor no meta at all', 90003 in kept, False)
check('nor a single character', 90004 in kept, False)
check('the floor is what the browser uses', MIN_PROMPT_LENGTH, 4)

check('without the filter they all come back',
      len(db.get_all_images_for_version(VERSION)), 6)

counts = db.get_image_counts(VERSION, require_prompt=True)
check('the counts say how many each filter hides',
      (counts['total'], counts['filtered'], counts['hidden_promptless'],
       counts['hidden_nsfw']), (6, 2, 4, 0))

status, body = get('/model-manager/models/details', path=facts['linked_paths'][0],
                   hide_promptless_images='true')
state = body['model']['images_state']
check('the endpoint filters too', len(body['model']['images']), 2)
check('and reports what it held back', state['hidden_promptless'], 4)
check('saying which way the switch is set', state['hide_promptless_images'], True)

status, body = get('/model-manager/models/details', path=facts['linked_paths'][0],
                   hide_promptless_images='false')
check('and it can be turned off', len(body['model']['images']), 6)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
