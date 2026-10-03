"""
The endpoints the browser actually calls, exercised through the app.

check_api_contract.py already proves the parameter names match what the tabs
send. This runs them: the filter parsing in models.py alone is nearly three
hundred statements deciding what the grid shows, and none of it had ever been
executed by a test.
"""
import io
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

# By file size, in GB (#40): every fixture file is a few bytes.
code, body = get('/model-manager/models', min_size_gb='1')
check('a file size range reaches the query: from 1 GB, nothing here', body.get('total'), 0)
code, body = get('/model-manager/models', max_size_gb='1')
check('up to 1 GB, everything', body.get('total'), fixtures.MODELS + fixtures.LOCAL_ONLY)
code, body = get('/model-manager/models', min_size_gb='abc', max_size_gb='-2')
check('and what is not a size is no filter', body.get('total'), fixtures.MODELS + fixtures.LOCAL_ONLY)

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

# path: - a file exactly, as a generation's record names its checkpoint.
target = facts['linked_paths'][0]
code, body = get('/model-manager/models', search='path:' + target)
check('a file is found by its full path, exactly', (body.get('total'), body['models'][0]['model_id'] if body.get('models') else None),
      (1, db.get_version(target)['model_id']))
code, body = get('/model-manager/models', search='path:' + target.swapcase())
check('whatever its case, as Windows does not mind it', body.get('total'), 1)
code, body = get('/model-manager/models', search='path:' + target[:-5])
check('and only exactly: part of a path finds nothing', body.get('total'), 0)

code, body = get('/model-manager/models', has_civitai='No')
check('models with no Civitai data are findable', body.get('total') >= 1, True)

code, body = get('/model-manager/models', sort_by='name', sort_order='asc')
names = [m.get('display_name') or m.get('name') for m in body.get('models', [])]
check('sorting by name is ordered', names, sorted(names, key=lambda s: (s or '').lower()))

# A sort the endpoint does not know falls back to the name without a word, so
# each one the dropdown offers has to be let through. The model the name puts
# last is given the most images, so only a sort by image count puts it first.
code, body = get('/model-manager/models', sort_by='name', sort_order='desc', page_size=100)
stored = db.count_images_by_version()
last_by_name = [m['id'] for m in body['models'] if stored.get(m.get('id'))][-1]
db.store_images(last_by_name, 9, [{'id': 94000 + i, 'url': 'n%d' % i, 'browsingLevel': 1}
                                  for i in range(20)])
code, body = get('/model-manager/models', sort_by='image_count', sort_order='desc', page_size=100)
stored = db.count_images_by_version()
counts = [stored.get(m.get('id'), 0) for m in body.get('models', [])]
check('sorting by image count reaches the query', counts, sorted(counts, reverse=True))
check('putting first the model with the most, which the name puts last',
      body['models'][0]['id'], last_by_name)
with db._cursor() as cursor:                            # later checks count its images
    cursor.execute("DELETE FROM images WHERE id BETWEEN 94000 AND 94019")

code, body = get('/model-manager/models', paths_only=True, type='Checkpoint')
check('paths_only answers with paths', code, 200)
check('and nothing but paths', sorted(body), ['models', 'paths', 'success'])
check('covering the checkpoints', len(body['paths']) >= fixtures.CHECKPOINTS, True)

# ---------------------------------------------------------------- the filters
for endpoint in ('/model-manager/filters', '/model-manager/filter-defaults'):
    code, body = get(endpoint)
    check('%s answers' % endpoint, code, 200)
    check('%s succeeds' % endpoint, body.get('success'), True)

stats = db.get_stats()   # the scan's summary line
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
first_version = body['model']['images_state']['version_id']
db.update_version_images_state(first_version, None)      # synced to the end: no Civitai here
code, body = get('/model-manager/images/gallery-page', version_id=first_version,
                 hide_nsfw_images='false', hide_promptless_images='false')
check('its gallery\'s images judged here, for the browser to read',
      bool(body.get('images')) and all('mm_level' in i for i in body['images']), True)

# A file with a .civitai.info and no row: the details come from the sidecar,
# in the shape the database's give - a level as a number, nsfw.py's (#58).
unread = os.path.join(WORK, 'sidecar_only.safetensors')
io.open(unread, 'wb').write(b'\0')
io.open(os.path.splitext(unread)[0] + '.civitai.info', 'w', encoding='utf-8').write(json.dumps({
    'id': 818, 'name': 'Only A Sidecar', 'type': 'LORA', 'nsfw': True, 'nsfwLevel': 28,
    'modelVersions': [{'id': 819, 'name': 'v1', 'nsfwLevel': 4,
                       'files': [{'name': 'sidecar_only.safetensors'}]}]}))
code, body = get('/model-manager/models/details', path=unread)
check('a file known only by its sidecar gives its model\'s level as a number, as the database does',
      (body.get('model') or {}).get('civitai_model', {}).get('nsfw'), 28)

code, body = get('/model-manager/models/details', path=r'Z:\nope\missing.safetensors')
check('details for an unknown file do not pretend', body.get('success'), False)

code, body = get('/model-manager/models/versions', model_id=facts['checkpoint_ids'][0])
check('versions answer', code, 200)
check('with at least one', len(body.get('versions', [])) >= 1, True)

# --- resolving a whole list of resource hashes ------------------------------
# An image names its resources twice and the two lists share no key, so the
# panel merges them by turning AutoV2 hashes into version ids. Answered from
# this library's own rows first, then from what an earlier lookup recorded,
# and only then from Civitai - which has no batch endpoint for hashes, so each
# one costs a request and is worth writing down.
import model_manager.api.models as models_api            # noqa: E402

real_client = models_api.CivitaiClient


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

# Civitai is asked about a bounded number per request; the rest come back
# deferred, to be sent again. Answers already known are never deferred.
from model_manager.resources import MAX_HASH_LOOKUPS             # noqa: E402

many = ['%010x' % (0xf00000 + n) for n in range(MAX_HASH_LOOKUPS + 7)]
_Counter.answers = {}
_Counter.asked = []
status, body = post('/model-manager/resolve-hashes',
                    hashes=','.join(['aaaaaaaaaa'] + many))
check('Civitai is asked about no more than the cap in one request',
      len(_Counter.asked), MAX_HASH_LOOKUPS)
check('the rest are handed back to be asked again',
      len(body['deferred']), 7)
check('a hash already known is answered, not deferred',
      'aaaaaaaaaa' in body['resolved'] and 'aaaaaaaaaa' not in body['deferred'], True)

_Counter.asked = []
status, body = post('/model-manager/resolve-hashes', hashes=','.join(body['deferred']))
check('sending the deferred ones asks about exactly those', len(_Counter.asked), 7)
check('and leaves nothing over', body['deferred'], [])

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
# --------------------------------------------------------------- the WebUI's
code, body = get('/model-manager/ui-options')
check('ui-options answers', code, 200)
check('and reports no key, which the stub has', body.get('has_api_key'), False)

webui_stub.install(model_manager_civitai_api_key='a-key')
code, body = get('/model-manager/ui-options')
check('and reports one when set', body.get('has_api_key'), True)
webui_stub.install()

# The pages note it while a trained model decides what is NSFW.
check('it says a trained model judges prompts, by default', body.get('nsfw_detection'), 'model')
webui_stub.install(model_manager_nsfw_detection='words')
code, body = get('/model-manager/ui-options')
check('and the word list when that is chosen', body.get('nsfw_detection'), 'words')
webui_stub.install(model_manager_nsfw_prompt_model_percent=0)
code, body = get('/model-manager/ui-options')
check('or when the model is turned off', body.get('nsfw_detection'), 'words')
webui_stub.install()

# ------------------------------------------------------------------ deleting
victim = facts['local_only_paths'][0]
check('the file is there to begin with', os.path.exists(victim), True)
# Its side files go with it - the ones Scan Disk moves with it too
# (model_dirs.COMPANIONS). The .cm-info.json was left behind (#64).
victim_sides = [os.path.splitext(victim)[0] + s for s in ('.civitai.info', '.cm-info.json', '.preview.png')]
for side in victim_sides:
    io.open(side, 'w').write('{}')
code, body = post('/model-manager/models/delete', path=victim)
check('its side files go with it, .cm-info.json too', [os.path.exists(side) for side in victim_sides],
      [False, False, False])
check('deleting answers', code, 200)
check('and succeeds', body.get('success'), True)
check('the file is gone', os.path.exists(victim), False)
code, body = get('/model-manager/models/details', path=victim)
check('and so is its row', body.get('success'), False)

code, body = post('/model-manager/models/delete', path=r'Z:\nope\missing.safetensors')
check('a path the library has never seen is refused', code, 403)
check('and says so', body.get('success'), False)

# A real file, sitting beside the library, that the database knows nothing
# about. The endpoint used to delete whatever it was sent, siblings included.
bystander = os.path.join(facts['directory'], 'not_a_model.txt')
bystander_sibling = os.path.join(facts['directory'], 'not_a_model.png')
for path in (bystander, bystander_sibling):
    with open(path, 'w') as f:
        f.write('keep me')
code, body = post('/model-manager/models/delete', path=bystander)
check('a file outside the library is refused', (code, body.get('error')),
      (403, 'Not a model in the library'))
check('and is still there', os.path.exists(bystander), True)
check('as is the picture beside it', os.path.exists(bystander_sibling), True)

# A model the library knows, whose file has already gone.
ghost = facts['local_only_paths'][1]
os.remove(ghost)
code, body = post('/model-manager/models/delete', path=ghost)
check('a known model whose file is gone still answers 404', code, 404)

# --- hiding images with no prompt -------------------------------------------
# Filtered in SQL rather than in the browser, so the counts come from the same
# place the images do. A prompt shorter than MIN_PROMPT_LENGTH is not one:
# measured over a real library, what sits below four characters is "1", ".",
# "???" - never something a person wrote.
from model_manager.prompt_rules import MIN_PROMPT_LENGTH            # noqa: E402

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

# Synced to the end: Civitai has nothing more, so no page asks it for more.
db.update_version_images_state(VERSION, None)
status, body = get('/model-manager/models/details', path=facts['linked_paths'][0],
                   hide_promptless_images='true')
state = body['model']['images_state']
check('the details report what the switches hold back', state['hidden_promptless'], 4)
check('saying which way the switch is set', state['hide_promptless_images'], True)
check('and carry no images: the gallery\'s pages are asked for on their own',
      'images' in body['model'], False)

status, body = get('/model-manager/images/gallery-page', version_id=VERSION,
                   hide_promptless_images='true')
check('a page filters too', len(body['images']), 2)
check('its note says what it held back, of the images it holds',
      {k: body['page'][k] for k in ('number', 'count', 'shown', 'hidden_promptless', 'more')},
      {'number': 1, 'count': 6, 'shown': 2, 'hidden_promptless': 4, 'more': False})
status, body = get('/model-manager/images/gallery-page', version_id=VERSION,
                   hide_promptless_images='false')
check('and it can be turned off', len(body['images']), 6)

# What each gallery switch acts on right now, which is both the number beside
# it and the number its banner states: its own kind, among the images the
# other switch lets through. So it moves when the other switch does, and it is
# not 0 while the switch is showing everything - it is then how many it shows.
from model_manager.nsfw import SFW_MAX                           # noqa: E402

db.store_images(VERSION, page=2, images=[
    {'id': 90007, 'url': 'u7', 'browsingLevel': 8,
     'meta': {'prompt': 'an explicit one with a prompt', 'steps': 20}},
    {'id': 90008, 'url': 'u8', 'browsingLevel': 8, 'meta': None},
])
# Six safe images, four of them without a prompt; two NSFW, one without.
for label, kwargs, want in (
    ('with both switches hiding', {'max_nsfw_level': SFW_MAX, 'require_prompt': True},
     (1, 4)),
    ('with NSFW shown', {'require_prompt': True}, (1, 5)),
    ('with prompts shown', {'max_nsfw_level': SFW_MAX}, (2, 4)),
    ('with both showing', {}, (2, 5)),
):
    counts = db.get_image_counts(VERSION, **kwargs)
    check('%s, NSFW and no-prompt count %s' % (label, want),
          (counts['nsfw_count'], counts['promptless_count']), want)

# An image both filters hide (90008: NSFW, no prompt) is counted apart, not
# credited to either: credited to the NSFW filter, the NSFW switch said 2 while
# hiding and 1 once ticked - it showed one, the other still hidden for its
# prompt (#29: 51, then 49). Each switch's number is what it alone hides.
both_hiding = db.get_image_counts(VERSION, max_nsfw_level=SFW_MAX, require_prompt=True)
nsfw_shown = db.get_image_counts(VERSION, require_prompt=True)
prompts_shown = db.get_image_counts(VERSION, max_nsfw_level=SFW_MAX)
check('both hiding: what each alone hides, and what both do',
      (both_hiding['hidden_nsfw'], both_hiding['hidden_promptless'], both_hiding['hidden_both']), (1, 4, 1))
check('which add up to what is hidden',
      both_hiding['hidden_nsfw'] + both_hiding['hidden_promptless'] + both_hiding['hidden_both'],
      both_hiding['hidden'])
check('the NSFW switch\'s number, hiding, is what it shows once ticked',
      both_hiding['hidden_nsfw'], nsfw_shown['nsfw_count'])
check('and the prompt switch\'s, likewise',
      both_hiding['hidden_promptless'], prompts_shown['promptless_count'])
check('the prompt switch\'s number is every image with an unusable prompt, however they are set',
      [c['promptless_total'] for c in (both_hiding, nsfw_shown, prompts_shown, db.get_image_counts(VERSION))],
      [5, 5, 5, 5])
check('one filter showing, nothing is hidden by both',
      (nsfw_shown['hidden_both'], prompts_shown['hidden_both']), (0, 0))
from model_manager.gallery import filter_images                   # noqa: E402
rows = db.get_all_images_for_version(VERSION)
for label, hide_nsfw, hide_promptless in (('both hiding', True, True), ('NSFW shown', False, True),
                                          ('prompts shown', True, False), ('both showing', False, False)):
    stored = db.get_image_counts(VERSION, max_nsfw_level=SFW_MAX if hide_nsfw else None,
                                 require_prompt=hide_promptless)
    _, paged = filter_images(rows, hide_nsfw, hide_promptless)
    keys = ('filtered', 'hidden_nsfw', 'hidden_promptless', 'hidden_both', 'nsfw_count', 'promptless_count',
            'promptless_total')
    check('%s: a page counts as the database does' % label,
          {k: paged[k] for k in keys}, {k: stored[k] for k in keys})

status, body = get('/model-manager/models/details', path=facts['linked_paths'][0],
                   hide_nsfw_images='false', hide_promptless_images='false')
state = body['model']['images_state']
check('the endpoint reports what each switch is showing when nothing is hidden',
      (state['nsfw_count'], state['promptless_count'], state['hidden_nsfw'],
       state['hidden_promptless']), (2, 5, 0, 0))

# ------------------------------------------------------ a page at a time
# A page is a slice of what is stored, in gallery order - 100 by default -
# before the switches, which only decide which of its images are shown; its
# note counts what they hid. The gallery used to be sent whole, then paged
# 100 matching images at a time, and a download from Civitai added pages
# that lined up with neither.
from model_manager.gallery import filter_images                      # noqa: E402

LARGE = facts['version_ids'][1]
db.clear_version_images(LARGE)
db.store_images(LARGE, page=1, images=[
    {'id': 91000 + n, 'url': 'l%d' % n, 'browsingLevel': 8 if n % 5 == 0 else 1,
     'meta': {'prompt': 'a long enough prompt %d' % n, 'steps': 20}}
    for n in range(250)])
db.update_version_images_state(LARGE, None)          # nothing more on Civitai
ALL = [91000 + n for n in range(250)]


def page(number, **switches):
    return get('/model-manager/images/gallery-page', version_id=LARGE, page=number,
               **{'hide_nsfw_images': 'true', 'hide_promptless_images': 'true', **switches})[1]


body = page(1)
check('page 1 is the first 100 stored, less what the switches hide',
      [i['id'] for i in body['images']], [i for i in ALL[:100] if (i - 91000) % 5])
check('its note: 100 images, 80 shown, 20 hidden as NSFW, and more after it',
      {k: body['page'][k] for k in ('number', 'size', 'count', 'shown', 'hidden_nsfw', 'more')},
      {'number': 1, 'size': 100, 'count': 100, 'shown': 80, 'hidden_nsfw': 20, 'more': True})
check('judged for the browser, as every image it is sent is',
      all('mm_level' in i for i in body['images']), True)
check('with the banner\'s totals over every page',
      (body['images_state']['total_count'], body['images_state']['filtered_count']), (250, 200))
check('a page is the same slice whatever the switches say',
      [i['id'] for i in page(2, hide_nsfw_images='false')['images']], ALL[100:200])
body = page(3)
check('the last page holds what is left, and nothing comes after it',
      (body['page']['count'], body['page']['more']), (50, False))
check('past the end is an empty page, not an error', page(9)['page']['count'], 0)
shared_opts = sys.modules['modules.shared'].opts
shared_opts.model_manager_gallery_page_size = 30
check('the page size is a setting: page 2 at 30 is the 31st to the 60th',
      [i['id'] for i in page(2, hide_nsfw_images='false')['images']], ALL[30:60])
shared_opts.model_manager_gallery_page_size = 100

# The Civitai Browser's cache has no level column, so its pages are filtered
# in Python. The two must mean the same by every count, on the same images.
same = db.get_all_images_for_version(VERSION)
for hide_nsfw in (True, False):
    for hide_promptless in (True, False):
        _, listed = filter_images(same, hide_nsfw, hide_promptless)
        stored = db.get_image_counts(VERSION, max_nsfw_level=SFW_MAX if hide_nsfw else None,
                                     require_prompt=hide_promptless)
        check('paging a list counts as the table does (hide NSFW %s, hide no-prompt %s)'
              % (hide_nsfw, hide_promptless), listed, stored)

# A download from Civitai goes on a page of its own, after the last. Its
# number came from the image count, which lands on the last page's own when
# the count is not a multiple of 100.
import model_manager.api.images as images_api                 # noqa: E402


class MoreImages:
    def __init__(self, ids):
        self.ids = ids

    def get_model_images(self, version_id, cursor=None, limit=100):
        return {'images': [{'id': i, 'url': 'm%d' % i, 'browsingLevel': 1,
                            'meta': {'prompt': 'downloaded', 'steps': 20}} for i in self.ids],
                'next_cursor': None}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def close(self):
        pass


real_client = images_api.CivitaiClient
try:
    images_api.CivitaiClient = type('Stub', (), {'from_settings': staticmethod(
        lambda: MoreImages([92001, 92002]))})
    db.update_version_images_state(LARGE, 'a-cursor')
    before = db.get_cached_page_count(LARGE)
    images_api.download_more(db, db.get_version_by_id(LARGE))
    check('a download is stored on a page after the last',
          db.get_cached_page_count(LARGE), before + 1)
    body = page(3, hide_nsfw_images='false')
    check('so it follows everything stored before it', [i['id'] for i in body['images']][-2:],
          [92001, 92002])
finally:
    images_api.CivitaiClient = real_client


# A version a bulk sync stored had no cursor, so "Download More Images" asked
# for the first page again: the images already stored. They were stored again
# under a new page number, and the click showed nothing new until a second.
class Pages:
    """Civitai's gallery, a batch per cursor."""
    def __init__(self, batches):
        self.batches, self.asked = batches, []

    def get_model_images(self, version_id, cursor=None, limit=100):
        self.asked.append(cursor)
        ids, next_cursor = self.batches[cursor]
        return {'images': [{'id': i, 'url': 'c%d' % i, 'browsingLevel': 1,
                            'meta': {'prompt': 'from civitai', 'steps': 20}} for i in ids],
                'next_cursor': next_cursor}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def close(self):
        pass


SYNCED = facts['version_ids'][2]
FIRST = list(range(93000, 93100))
db.clear_version_images(SYNCED)
db.store_images(SYNCED, page=1, images=[
    {'id': i, 'url': 'f%d' % i, 'browsingLevel': 1, 'meta': {'prompt': 'stored', 'steps': 20}}
    for i in FIRST])
db.update_version_images_state(SYNCED, None)
civitai_pages = Pages({None: (FIRST, 'c1'), 'c1': ([93100, 93101, 93102], 'c2')})
try:
    images_api.CivitaiClient = type('Stub', (), {'from_settings': staticmethod(
        lambda: civitai_pages)})
    body = images_api.download_more(db, db.get_version_by_id(SYNCED))
    check('with no cursor, the first click passes over the batch already stored',
          civitai_pages.asked, [None, 'c1'])
    check('and brings the new ones', body['downloaded_count'], 3)
    check('leaving the stored images on their page',
          [i['id'] for i in db.get_images(SYNCED, page=1)], FIRST)
    check('and filing only the new ones on the next',
          [i['id'] for i in db.get_images(SYNCED, page=2)], [93100, 93101, 93102])
    check('where the next click carries on from',
          db.get_version_by_id(SYNCED)['next_images_cursor'], 'c2')

    # A long run of images already stored is not followed forever.
    db.update_version_images_state(SYNCED, None)
    civitai_pages = Pages({None: (FIRST, 'd1'),
                           **{'d%d' % n: (FIRST, 'd%d' % (n + 1)) for n in range(1, 10)}})
    body = images_api.download_more(db, db.get_version_by_id(SYNCED))
    check('batches of images already stored are followed only so far',
          len(civitai_pages.asked), images_api.LOAD_MORE_BATCHES)
    check('bringing nothing new', (body['downloaded_count'], body['images']), (0, []))
    check('but keeping where it got to, so the next click carries on',
          db.get_version_by_id(SYNCED)['next_images_cursor'],
          'd%d' % images_api.LOAD_MORE_BATCHES)
    check('and saying why', body.get('message'), 'Only images already downloaded so far')

    # A page the library cannot fill is filled from Civitai first: with 250
    # stored and pages of 100, page 3 lacks 50. Civitai's batches are 100.
    FILL = facts['version_ids'][3]
    db.clear_version_images(FILL)
    db.store_images(FILL, page=1, images=[
        {'id': 96000 + n, 'url': 'f%d' % n, 'browsingLevel': 1,
         'meta': {'prompt': 'a long enough prompt', 'steps': 20}} for n in range(250)])
    db.update_version_images_state(FILL, 'after-250')
    civitai_pages = Pages({'after-250': (list(range(97000, 97100)), None)})
    fill = lambda number: get('/model-manager/images/gallery-page', version_id=FILL, page=number,
                              hide_nsfw_images='false', hide_promptless_images='false')[1]
    body = fill(3)
    check('a page the library cannot fill asks Civitai for more first',
          civitai_pages.asked, ['after-250'])
    check('and is whole: the 50 left, then 50 of what came',
          [i['id'] for i in body['images']],
          list(range(96200, 96250)) + list(range(97000, 97050)))
    check('the rest of what came is the next page', body['page']['more'], True)
    body = fill(4)
    check('which the library holds: nothing more is asked of Civitai',
          (civitai_pages.asked, body['page']['count'], body['page']['more']), (['after-250'], 50, False))

    # A model with nothing stored loads its first page from Civitai.
    EMPTY = facts['version_ids'][4]
    db.clear_version_images(EMPTY)
    with db._cursor() as cursor:
        cursor.execute("UPDATE model_versions SET next_images_cursor = NULL, "
                       "images_sync_last_date = NULL WHERE id = ?", (EMPTY,))
    civitai_pages = Pages({None: ([98001, 98002, 98003], None)})
    body = get('/model-manager/images/gallery-page', version_id=EMPTY, page=1,
               hide_nsfw_images='false', hide_promptless_images='false')[1]
    check('a model with no images stored loads page 1 from Civitai',
          ([i['id'] for i in body['images']], body['page']['more']), ([98001, 98002, 98003], False))

    # Civitai failing leaves what is stored, and says why.
    db.update_version_images_state(EMPTY, 'more-please')
    class Down(Pages):
        def get_model_images(self, version_id, cursor=None, limit=100):
            raise RuntimeError('Civitai: overloaded (503)')
    civitai_pages = Down({})
    opts_ = sys.modules['modules.shared'].opts
    opts_.model_manager_gallery_page_size = 10
    body = get('/model-manager/images/gallery-page', version_id=EMPTY, page=1,
               hide_nsfw_images='false', hide_promptless_images='false')[1]
    opts_.model_manager_gallery_page_size = 100
    check('a page Civitai fails to fill shows what is stored, with the error for its note',
          (len(body['images']), body['page']['error']), (3, 'Civitai: overloaded (503)'))
finally:
    images_api.CivitaiClient = real_client

# ------------------------------------------------- resolving hashes, locally
# The gallery labels its Resources buttons from what the server already knows
# - the library, and past lookups - in one request that must never reach
# Civitai: that would be one request per hash, for a label.
import model_manager.api.models as models_api                # noqa: E402


class NoCivitai:
    @classmethod
    def from_settings(cls):
        raise AssertionError('local_only reached Civitai')


real_client = models_api.CivitaiClient
models_api.CivitaiClient = NoCivitai
try:
    with db._cursor() as cursor:
        cursor.execute("SELECT file_hashes FROM model_versions WHERE file_hashes IS NOT NULL LIMIT 1")
        local_hash = json.loads(cursor.fetchone()[0])['autov2'].lower()
    code, body = post('/model-manager/resolve-hashes',
                      hashes=local_hash + ',ffffffffff', local_only='true')
    check('local_only answers what the library knows', local_hash in body.get('resolved', {}), True)
    check('and defers what it does not, without asking Civitai',
          (code, body.get('deferred')), (200, ['ffffffffff']))
finally:
    models_api.CivitaiClient = real_client

# --- what the missing resources will be called -------------------------------
# The chips under the prompts name a missing LoRA as its file will be named
# once downloaded, so a download does not rename (and resize) it: the file a
# download takes - Civitai's primary, not the first listed - from one request
# per hundred models. Asked after a Send, never waited on by it.

class _Missing:
    asked = []
    models = {}
    versions = {}
    hashes = {}
    broken = False

    @classmethod
    def from_settings(cls):
        return cls()

    def get_models_by_ids(self, ids):
        if _Missing.broken:
            raise RuntimeError('Civitai is down')
        _Missing.asked.append(('models', sorted(ids)))
        return {i: _Missing.models[i] for i in ids if i in _Missing.models}

    def get_model_version(self, version_id):
        _Missing.asked.append(('version', version_id))
        return _Missing.versions.get(version_id)

    def get_model_by_hash(self, value):
        _Missing.asked.append(('hash', value))
        return _Missing.hashes.get(value)

    def close(self):
        pass


def _files(*names, primary=None):
    return [{'name': n, 'primary': n == primary} for n in names]


_Missing.models = {
    700: {'id': 700, 'name': 'A Very Different Title', 'type': 'LORA', 'modelVersions': [
        {'id': 7001, 'name': 'v1', 'files': _files('big_fp32.safetensors', 'sharp_eyes.safetensors',
                                                   primary='sharp_eyes.safetensors')}]},
    701: {'id': 701, 'name': 'Moved On', 'type': 'LORA', 'modelVersions': [{'id': 7012, 'name': 'v2', 'files': []}]},
}
_Missing.versions = {7020: {'id': 7020, 'modelId': 702, 'name': 'v1', 'model': {'name': 'No Id Given', 'type': 'TextualInversion'},
                            'files': _files('bad_hands.pt')}}
_Missing.hashes = {'abcdef0123': {'id': 7001, 'modelId': 700, 'name': 'v1', 'model': {'name': 'A Very Different Title'}}}
models_api.CivitaiClient = _Missing
import model_manager.resources as resources              # noqa: E402
resources._MISSING_FILES.clear()
try:
    code, body = post('/model-manager/missing-resources',
                      versions=json.dumps([{'version_id': 7001, 'model_id': 700},
                                           {'version_id': 7011, 'model_id': 701},
                                           {'version_id': 7099, 'model_id': 799},
                                           {'version_id': 7020, 'model_id': None}]),
                      hashes='ABCDEF0123,0000000000')
    got = body.get('versions', {})
    check('a missing version is named as a download names it: its primary file, not the first listed',
          got.get('7001'), {'file_stem': 'sharp_eyes', 'file_type': 'LORA', 'model_id': 700,
                            'name': 'A Very Different Title', 'version_name': 'v1'})
    check('a version its model no longer lists is said so, the model named',
          (got.get('7011') or {}).get('version_gone'), True)
    check('and a model Civitai no longer has, so', got.get('7099'), {'gone': True})
    check('one with no model id is asked for alone',
          (got.get('7020') or {}).get('file_stem'), 'bad_hands')
    check('a hash becomes its version, and one Civitai does not know, null',
          body.get('hashes'), {'abcdef0123': 7001, '0000000000': None})
    check('every model in one request - the hash\'s version among them - and one per unknown',
          sorted(a for a in _Missing.asked if a[0] != 'hash'),
          [('models', [700, 701, 799]), ('version', 7020)])
    _Missing.asked = []
    code, body = post('/model-manager/missing-resources',
                      versions=json.dumps([{'version_id': 7001, 'model_id': 700}]), hashes='abcdef0123')
    check('asked again, answered from what was learned: the hash remembered, the name kept',
          (_Missing.asked, body.get('versions', {}).get('7001', {}).get('file_stem'), body.get('hashes')),
          ([], 'sharp_eyes', {'abcdef0123': 7001}))
    # Civitai is asked about the same number of hashes per request as
    # /resolve-hashes asks (#109); the rest are left out, for the page to ask
    # about through it.
    _Missing.asked = []
    many = ['%010x' % (0xe00000 + n) for n in range(MAX_HASH_LOOKUPS + 7)]
    code, body = post('/model-manager/missing-resources', hashes=','.join(many))
    check('Civitai is asked about no more hashes than the cap in one request',
          len([a for a in _Missing.asked if a[0] == 'hash']), MAX_HASH_LOOKUPS)
    check('a hash not asked about this time is left out of the answer',
          sorted(body.get('hashes', {})), many[:MAX_HASH_LOOKUPS])
    _Missing.broken = True
    code, body = post('/model-manager/missing-resources',
                      versions=json.dumps([{'version_id': 7555, 'model_id': 755}]))
    check('Civitai failing is an error, for the page to fall back', (code, body.get('success')), (500, False))
finally:
    models_api.CivitaiClient = real_client
    resources._MISSING_FILES.clear()

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
