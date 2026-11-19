"""
A Civitai image's data filled from its ComfyUI graph (#232, part 3): only
where it is shown and sent - the gallery page, the Civitai Images tab, the
Civitai Browser's showcase images, Send and the usual settings - after every
filter and level has judged Civitai's data alone. A field Civitai gives is
never changed; nothing stored, searched, filtered or judged changes. (The
Browser's image page is browser_api_test's.)
"""
import copy
import json
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
    import fastapi                                       # noqa: F401
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager import comfy_graph, send, usual_settings  # noqa: E402
from model_manager.nsfw import stamp_levels              # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(os.path.join(TESTS, 'work', 'comfy_fill'))
dbmod._db_instance = db
V = facts['version_ids'][0]


def node(kind, **inputs):
    return {'class_type': kind, 'inputs': inputs}


def graph(prompt='a fox at dusk'):
    """A Flux-shaped run graph: its shift on the model's way, its guidance on
    the positive's, a schedule type unlike Civitai's Karras. An object, as
    Civitai's records hold `comfy` (5,048 of 5,048 in one library)."""
    return ({'prompt': {
        '5': node('EmptyLatentImage', width=512, height=768, batch_size=1),
        '4': node('CheckpointLoaderSimple', ckpt_name='FLUX\\graph_ck_1.0.safetensors'),
        '10': node('ModelSamplingSD3', shift=3.0, model=['4', 0]),
        '6': node('CLIPTextEncode', text=prompt, clip=['4', 1]),
        '11': node('FluxGuidance', guidance=3.5, conditioning=['6', 0]),
        '7': node('CLIPTextEncode', text='blurry', clip=['4', 1]),
        '3': node('KSampler', seed=7, steps=25, cfg=6.5, sampler_name='euler', scheduler='normal', denoise=1.0,
                  model=['10', 0], positive=['11', 0], negative=['7', 0], latent_image=['5', 0]),
        '8': node('VAEDecode', samples=['3', 0], vae=['4', 2]),
        '9': node('SaveImage', images=['8', 0])}})


def image(image_id, meta, level=1):
    return {'id': image_id, 'url': 'https://image.civitai.com/x/%d.jpeg' % image_id, 'width': 512, 'height': 768,
            'browsingLevel': level, 'meta': meta}


EXPLICIT = 'nude'
ONLY_GRAPH = image(9101, {'comfy': graph(), 'steps': 20, 'seed': 0})
CIVITAI_OWN = image(9102, {'comfy': graph(), 'prompt': 'a civitai prompt', 'sampler': 'DPM++ 2M Karras',
                           'Model': 'civitai_model'})
EXPLICIT_GRAPH = image(9103, {'comfy': graph('a %s figure' % EXPLICIT)})
EMPTY_GRAPH = image(9104, {'comfy': {}, 'prompt': 'a plain one'})
STORED = [ONLY_GRAPH, CIVITAI_OWN, EXPLICIT_GRAPH, EMPTY_GRAPH]
given = copy.deepcopy(STORED)
db.store_images(V, page=1, images=copy.deepcopy(STORED))

# ------------------------------------------------------------ the fill's rules
filled = comfy_graph.fill(ONLY_GRAPH['meta'])
check('232. a missing prompt, negative, CFG, sampler and schedule type, shift, Distilled CFG and checkpoint filled; '
      'Civitai\'s steps and its seed of 0 kept; said where from',
      {k: filled.get(k) for k in ('prompt', 'negativePrompt', 'steps', 'cfgScale', 'seed', 'sampler', 'scheduler',
                                  'Shift', 'Distilled CFG Scale', 'Model', 'Read from')},
      {'prompt': 'a fox at dusk', 'negativePrompt': 'blurry', 'steps': 20, 'cfgScale': 6.5, 'seed': 0,
       'sampler': 'euler', 'scheduler': 'normal', 'Shift': 3.0, 'Distilled CFG Scale': 3.5, 'Model': 'graph_ck_1.0',
       'Read from': 'Civitai, workflow'})
check('232. the data handed is left as it was', ONLY_GRAPH['meta'], given[0]['meta'])
own = comfy_graph.fill(CIVITAI_OWN['meta'])
check('232. Civitai\'s prompt, sampler and checkpoint kept: no schedule type beside a sampler that folds one in',
      {k: own.get(k) for k in ('prompt', 'sampler', 'scheduler', 'Model')},
      {'prompt': 'a civitai prompt', 'sampler': 'DPM++ 2M Karras', 'scheduler': None, 'Model': 'civitai_model'})
check('232. a checkpoint named only by a resource with a hash, or civitaiResources\' version: no Model filled',
      [comfy_graph.fill({**ONLY_GRAPH['meta'], 'resources': [{'type': 'model', 'hash': 'abc'}]}).get('Model'),
       comfy_graph.fill({**ONLY_GRAPH['meta'],
                         'civitaiResources': [{'type': 'checkpoint', 'modelVersionId': 5}]}).get('Model')],
      [None, None])
check('232. Civitai\'s steps of 0 and CFG of 0 kept, as numbers it gives are never missing',
      {k: comfy_graph.fill({**ONLY_GRAPH['meta'], 'steps': 0, 'cfgScale': 0}).get(k) for k in ('steps', 'cfgScale')},
      {'steps': 0, 'cfgScale': 0})
check('232. a checkpoint named only by its Model hash: no Model filled, as the page finds one by it',
      comfy_graph.fill({**ONLY_GRAPH['meta'], 'Model hash': 'abc123'}).get('Model'), None)
check('232. a prompt of spaces is missing', comfy_graph.fill({**ONLY_GRAPH['meta'], 'prompt': '  '})['prompt'],
      'a fox at dusk')
check('232. an empty comfy is no graph; data without one handed back as it is',
      [comfy_graph.has_graph(EMPTY_GRAPH['meta']), comfy_graph.has_graph(ONLY_GRAPH['meta']),
       comfy_graph.fill(EMPTY_GRAPH['meta']) is EMPTY_GRAPH['meta']], [False, True, True])

# ------------------------------------------------------- nothing stored changes
check('232. the stored records\' data are Civitai\'s, as given',
      sorted((r['id'], json.dumps(r['meta'], sort_keys=True)) for r in db.stored_records([9101, 9102, 9103, 9104])),
      sorted((r['id'], json.dumps(r['meta'], sort_keys=True)) for r in given))
with db._cursor() as cursor:
    cursor.execute('SELECT COUNT(*) FROM images WHERE id IN (9101, 9103) AND prompt_id IS NOT NULL')
    prompt_rows = cursor.fetchone()[0]
check('232. no prompt row for an image whose prompt is only in its graph: search and the switches read Civitai\'s',
      prompt_rows, 0)
with db._cursor() as cursor:
    cursor.execute('SELECT image_id, effective_nsfw_level FROM image_galleries WHERE image_id IN (9101, 9103)')
    stored_levels = dict(cursor.fetchall())
    cursor.execute('SELECT shift, cfg, sampler FROM image_params WHERE image_id = 9101')
    stored_settings = cursor.fetchone()
check('232. the level stored for each, and its settings row, from Civitai\'s data alone: no graph prompt judged, no '
      'shift, CFG or sampler from the graph',
      (stored_levels, tuple(stored_settings) if stored_settings else None), ({9101: 1, 9103: 1}, (None, None, None)))
db.restamp_image_levels()
with db._cursor() as cursor:
    cursor.execute('SELECT image_id, effective_nsfw_level FROM image_galleries WHERE image_id IN (9101, 9103)')
    restamped = dict(cursor.fetchall())
check('232. judged again (the restamp): from Civitai\'s data, as before', restamped, stored_levels)
from model_manager.civitai.prompt_filter import generation_ids_needing_lookup, keep_generation_data  # noqa: E402
fresh = [image(9101, {'comfy': graph(), 'steps': 20})]
keep_generation_data(fresh, db.stored_records([9101]))
check('232. a sync\'s fresh copy, carried over from the stored record: no prompt, still looked up for Civitai\'s',
      ('prompt' in fresh[0]['meta'], generation_ids_needing_lookup(fresh)), (False, [9101]))

# ------------------------------------------------------- where it is shown
from model_manager.api.images import gallery_page   # noqa: E402
from model_manager.gallery import ALL                # noqa: E402
page = gallery_page(db, V, 1, ALL, False, fetch=False)
shown = {i['id']: i for i in page['images']}
judged = {i['id']: i['mm_level'] for i in stamp_levels(copy.deepcopy(db.stored_records([9101, 9102, 9103, 9104])))}
check('232. the gallery page: the graph\'s prompt and checkpoint on the image Civitai gave none, Civitai\'s kept',
      [shown.get(9101, {}).get('meta', {}).get('prompt'), shown.get(9101, {}).get('meta', {}).get('Model'),
       shown.get(9102, {}).get('meta', {}).get('prompt')],
      ['a fox at dusk', 'graph_ck_1.0', 'a civitai prompt'])
check('232. each image\'s level as Civitai\'s data judges it, the explicit graph prompt not read',
      {i: shown.get(i, {}).get('mm_level') for i in judged}, judged)
check('232. its card\'s sampler read from the fill', bool(shown.get(9101, {}).get('mm_sampler')), True)
hiding = gallery_page(db, V, 1, ALL, True, fetch=False)
check('232. with images with no prompt hidden: those Civitai gives none, as before',
      (sorted(i['id'] for i in hiding['images'] if 9101 <= i['id'] <= 9104), hiding['page'].get('hidden_promptless')),
      ([9102, 9104], 2))
check('232. the page\'s hidden counts equal the banner\'s, the page holding the whole gallery',
      {k: hiding['page'].get(k) for k in ('hidden_promptless', 'hidden_nsfw', 'hidden_both')},
      {k: hiding['images_state'].get(k) for k in ('hidden_promptless', 'hidden_nsfw', 'hidden_both')})

# A gallery page that fetches more from Civitai first: what Civitai sends is
# stored as it came, and the page, read again from the database, filled.
import model_manager.api.images as images_api      # noqa: E402


class MoreImages:
    def get_model_images(self, version_id=None, cursor=None, limit=None):
        return {'images': [image(9201, {'comfy': graph('a heron at dawn'), 'steps': 30})], 'next_cursor': None}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def close(self):
        pass


client_before = images_api.CivitaiClient
images_api.CivitaiClient = type('Client', (), {'from_settings': staticmethod(lambda: MoreImages())})
try:
    fetched = gallery_page(db, V, 1, ALL, False, fetch=True)
finally:
    images_api.CivitaiClient = client_before
check('232. a gallery page that fetched more: the new image shown filled, its record stored as Civitai sent it',
      ([i['meta'].get('prompt') for i in fetched['images'] if i['id'] == 9201],
       [r['meta'].get('prompt') for r in db.stored_records([9201])]), (['a heron at dawn'], [None]))

from model_manager.api import gallery as gallery_api   # noqa: E402
tiles = {t['image']['id']: t['image'] for t in gallery_api.image_tiles(db, [(9101, V), (9103, V)])}
check('232. the Civitai Images tab: filled, judged as Civitai\'s data',
      [tiles.get(9101, {}).get('meta', {}).get('prompt'), {i: tiles.get(i, {}).get('mm_level') for i in (9101, 9103)}],
      ['a fox at dusk', {9101: judged[9101], 9103: judged[9103]}])

from model_manager.api.annotations import annotate_image_levels   # noqa: E402
models = [{'modelVersions': [{'images': copy.deepcopy([ONLY_GRAPH, EXPLICIT_GRAPH])}]}]
annotate_image_levels(models)
showcase = {i['id']: i for i in models[0]['modelVersions'][0]['images']}
check('232. the Browser\'s showcase images: filled, their card\'s sampler from it, judged as Civitai\'s data',
      [showcase[9101]['meta'].get('prompt'), bool(showcase[9101].get('mm_sampler')),
       {i: showcase[i]['mm_level'] for i in (9101, 9103)}],
      ['a fox at dusk', True, {9101: judged[9101], 9103: judged[9103]}])

from model_manager.api.prompts import inspect_models   # noqa: E402


class GraphOnly:
    """Civitai's answer for a model whose images hold prompts only in their graphs."""

    def get_model_images(self, version_id, cursor=None, limit=None):
        return {'images': [copy.deepcopy(ONLY_GRAPH), copy.deepcopy(EXPLICIT_GRAPH)]}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}


check('232. the Browser\'s check for models with too few prompts: as before, the graph\'s not counted',
      inspect_models(GraphOnly(), [{'id': 1, 'modelVersions': [{'id': 77}]}], want_prompts=True, want_sfw=False),
      ['prompt'])

# ------------------------------------------------------- where it is sent
SAMPLERS, SCHEDULERS = ['Euler', 'DPM++ 2M'], ['Automatic', 'Karras', 'Normal']
lists_before = send.forge_lists
send.forge_lists = lambda: (SAMPLERS, SCHEDULERS)
try:
    sent = send.civitai_settings(db, {'image': 9101})
    sent_own = send.civitai_settings(db, {'image': 9102})
finally:
    send.forge_lists = lists_before
text = (sent or {}).get('text') or ''
check('232. Send\'s text: the graph\'s prompt, Civitai\'s seed of 0, the shift and Distilled CFG, no Read from',
      ['a fox at dusk' in text, 'Seed: 0' in text, 'Shift: 3' in text, 'Distilled CFG Scale: 3.5' in text,
       'Read from' in text, 'comfy' in text], [True, True, True, True, False, False])
check('232. Civitai\'s "DPM++ 2M Karras" sent as written, the graph\'s schedule type not over it',
      ['Sampler: DPM++ 2M' in (sent_own or {}).get('text', ''), (sent_own or {}).get('scheduler')],
      [True, 'Karras'])
own_settings = usual_settings._image_own(db, {'kind': 'civitai', 'image': 9101}, SAMPLERS, SCHEDULERS)
check('232. the usual settings\' column for the image itself reads the fill too: its shift, its CFG',
      (own_settings.get('shift'), own_settings.get('cfg')), (3, 6.5))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
