"""
A Civitai image's data filled from its ComfyUI graph (#232): where it is
shown and sent always - the gallery page, the Civitai Images tab, the Civitai
Browser's showcase images, Send and the usual settings - and where it is
judged, stored and searched by the switch (comfy_graph.judged): off on a
library from before, every judgement Civitai's data alone; on in a new one,
or once Fill has run, its rows and levels from the filled data. A field
Civitai gives is never changed, and the stored record stays Civitai's.
(The Browser's image page is browser_api_test's.)
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

import subprocess                                        # noqa: E402

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager import comfy_graph, send, usual_settings  # noqa: E402
from model_manager.nsfw import generated_level, prompt_words_fingerprint, stamp_levels, version_covers  # noqa: E402
from model_manager.prompt_rules import usable           # noqa: E402
from model_manager.api.prompts import has_nsfw_image     # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(os.path.join(TESTS, 'work', 'comfy_fill'))
dbmod._db_instance = db
V = facts['version_ids'][0]
comfy_graph.set_switch_reader(db._read_comfy_switch)   # as get_models_db hands it

with db._cursor() as cursor:
    cursor.execute("SELECT key, value FROM schema_info WHERE key IN ('comfy_judged', 'comfy_fill')")
    made = dict(cursor.fetchall())
check('232. a new database is judged filled from the start, Fill counted as run with this reader',
      (made, comfy_graph.switch()), ({'comfy_judged': '1', 'comfy_fill': str(comfy_graph.READER)},
                                     (True, comfy_graph.READER)))


def turn(on, filled=None):
    """The switch as a library from before has it (off: neither value), or on."""
    with db._cursor() as cursor:
        cursor.execute("DELETE FROM schema_info WHERE key IN ('comfy_judged', 'comfy_fill')")
        if on:
            cursor.execute("INSERT INTO schema_info (key, value) VALUES ('comfy_judged', '1')")
        if filled is not None:
            cursor.execute("INSERT INTO schema_info (key, value) VALUES ('comfy_fill', ?)", (str(filled),))
    comfy_graph.set_switch_reader(db._read_comfy_switch)


turn(False)
check('232. a library from before: neither value, judged by Civitai\'s data', comfy_graph.switch(), (False, None))
dbmod.ModelsDatabase(os.path.dirname(db.db_path), db.db_path)
with db._cursor() as cursor:
    cursor.execute("SELECT COUNT(*) FROM schema_info WHERE key IN ('comfy_judged', 'comfy_fill')")
    reopened = cursor.fetchone()[0]
check('232. a library from before, opened again by this version: still neither value, the switch as it was',
      (reopened, comfy_graph.switch()), (0, (False, None)))
dbmod.ModelsDatabase(os.path.dirname(db.db_path), os.path.join(os.path.dirname(db.db_path), 'another.db'))
check('232. another database made in the same process (switched on, being new) leaves this one\'s switch',
      comfy_graph.switch(), (False, None))

# A database on a share: read by its path as given, which SQLite opens where
# a file: address of it is refused. Checked where this computer's own admin
# share reaches the suite's file.
drive, rest = os.path.splitdrive(os.path.abspath(db.db_path))
shared = '\\\\localhost\\%s$%s' % (drive[:1], rest)
if drive and os.path.isfile(shared):
    on_share = dbmod.ModelsDatabase.__new__(dbmod.ModelsDatabase)
    on_share.db_path = shared
    try:
        read_on_share = on_share._read_comfy_switch()
    except Exception as e:                       # a failure fails the check, not the suite
        read_on_share = repr(e)
    check('232. a database on a share: its switch read', read_on_share, (False, None))


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

# --------------------------------- switch off: nothing stored or judged changes
check('232. the stored records\' data are Civitai\'s, as given',
      sorted((r['id'], json.dumps(r['meta'], sort_keys=True)) for r in db.stored_records([9101, 9102, 9103, 9104])),
      sorted((r['id'], json.dumps(r['meta'], sort_keys=True)) for r in given))
with db._cursor() as cursor:
    cursor.execute('SELECT COUNT(*) FROM images WHERE id IN (9101, 9103) AND prompt_id IS NOT NULL')
    prompt_rows = cursor.fetchone()[0]
check('232. switch off: no prompt row for an image whose prompt is only in its graph',
      prompt_rows, 0)
with db._cursor() as cursor:
    cursor.execute('SELECT image_id, effective_nsfw_level FROM image_galleries WHERE image_id IN (9101, 9103)')
    stored_levels = dict(cursor.fetchall())
    cursor.execute('SELECT shift, cfg, sampler FROM image_params WHERE image_id = 9101')
    stored_settings = cursor.fetchone()
check('232. switch off: the level stored for each, and its settings row, from Civitai\'s data alone',
      (stored_levels, tuple(stored_settings) if stored_settings else None), ({9101: 1, 9103: 1}, (None, None, None)))
db.restamp_image_levels()
with db._cursor() as cursor:
    cursor.execute('SELECT image_id, effective_nsfw_level FROM image_galleries WHERE image_id IN (9101, 9103)')
    restamped = dict(cursor.fetchall())
check('232. switch off: judged again (the restamp), from Civitai\'s data', restamped, stored_levels)
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
check('232. switch off: each image\'s level as Civitai\'s data judges it, the explicit graph prompt not read',
      {i: shown.get(i, {}).get('mm_level') for i in judged}, judged)
check('232. its card\'s sampler read from the fill', bool(shown.get(9101, {}).get('mm_sampler')), True)
hiding = gallery_page(db, V, 1, ALL, True, fetch=False)
check('232. switch off: with images with no prompt hidden, those Civitai gives none',
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
check('232. switch off: the Civitai Images tab filled, judged as Civitai\'s data',
      [tiles.get(9101, {}).get('meta', {}).get('prompt'), {i: tiles.get(i, {}).get('mm_level') for i in (9101, 9103)}],
      ['a fox at dusk', {9101: judged[9101], 9103: judged[9103]}])

from model_manager.api.annotations import annotate_image_levels   # noqa: E402
models = [{'modelVersions': [{'images': copy.deepcopy([ONLY_GRAPH, EXPLICIT_GRAPH])}]}]
annotate_image_levels(models)
showcase = {i['id']: i for i in models[0]['modelVersions'][0]['images']}
check('232. switch off: the Browser\'s showcase images filled, their card\'s sampler from it, and judged filled - '
      'never stored, nothing about them waits for Fill',
      [showcase[9101]['meta'].get('prompt'), bool(showcase[9101].get('mm_sampler')),
       {i: showcase[i]['mm_level'] for i in (9101, 9103)}],
      ['a fox at dusk', True, {9101: 1, 9103: 8}])

from model_manager.api.prompts import inspect_models   # noqa: E402


class GraphOnly:
    """Civitai's answer for a model whose images hold prompts only in their graphs."""

    def get_model_images(self, version_id, cursor=None, limit=None):
        return {'images': [copy.deepcopy(ONLY_GRAPH), copy.deepcopy(EXPLICIT_GRAPH)]}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}


check('232. switch off: the Browser\'s check for models with too few prompts counts the graph\'s, judged filled',
      inspect_models(GraphOnly(), [{'id': 1, 'modelVersions': [{'id': 77}]}], want_prompts=True, want_sfw=False),
      [None])
check('232. a record whose prompt and settings are only in its graph: usable once judged filled, not before',
      [usable(ONLY_GRAPH), usable(ONLY_GRAPH, filled=True)], [False, True])
covers_off = version_covers(copy.deepcopy([EXPLICIT_GRAPH, ONLY_GRAPH]), complete=True)
check('232. a version\'s covers at sync, switch off: the image whose graph prompt is explicit counts as safe',
      covers_off[1], EXPLICIT_GRAPH['url'])
fingerprint_off = prompt_words_fingerprint()
check('232. switch off: the Browser\'s safe-for-work check reads a live image\'s explicit graph prompt',
      has_nsfw_image([copy.deepcopy(EXPLICIT_GRAPH)]), True)
with db._cursor() as cursor:
    cursor.execute('SELECT image_id, data FROM image_records WHERE image_id IN (9101, 9102, 9103, 9104)')
    records_off = dict(cursor.fetchall())

# A prompt changed when an image is stored again: the old one's row goes
# (the drop inside storing, whose steps derived_rows now works out).
db.store_images(V, page=7, images=[image(9301, {'prompt': 'the first prompt of it'})])
db.store_images(V, page=7, images=[image(9301, {'prompt': 'the second prompt of it'})])
with db._cursor() as cursor:
    cursor.execute("SELECT text FROM image_prompts WHERE text LIKE 'the % prompt of it'")
    left = sorted(row[0] for row in cursor.fetchall())
check('232. an image stored again with another prompt: the old prompt\'s row dropped', left, ['the second prompt of it'])

# ------------------------------- switch on: judged, stored and searched filled
turn(True, comfy_graph.READER)
check('232. switch on: usable reads the graph\'s prompt and settings, the switch alone deciding', usable(ONLY_GRAPH), True)
check('232. turning the switch on leaves the restamp\'s fingerprint as it was: an older copy sharing the database '
      'would otherwise judge every image again at each start, undoing this one\'s levels',
      prompt_words_fingerprint(), fingerprint_off)
reads_in_pass = []
reader_kept, seconds_kept = db._read_comfy_switch, comfy_graph.SWITCH_SECONDS


def counted_reader():
    reads_in_pass.append(1)
    return reader_kept()


comfy_graph.set_switch_reader(counted_reader)
comfy_graph.SWITCH_SECONDS = 0
reads_in_pass.clear()
try:
    db.restamp_image_levels()
finally:
    comfy_graph.SWITCH_SECONDS = seconds_kept
    comfy_graph.set_switch_reader(reader_kept)
check('232. the restamp reads the switch once a pass, every image judged one way', len(reads_in_pass), 1)
with db._cursor() as cursor:
    cursor.execute('SELECT image_id, effective_nsfw_level FROM image_galleries WHERE image_id IN (9101, 9103)')
    restamped_on = dict(cursor.fetchall())
check('232. switch on: the restamp judges the explicit graph prompt', restamped_on, {9101: 1, 9103: 8})

# Storing reads the switch on its own transaction's cursor, under the write
# lock - never through the copy's reader, whose read it would not need.
# Every read of the copy is made due here, so one would show.
in_transaction = []
reader_before, seconds_before = db._read_comfy_switch, comfy_graph.SWITCH_SECONDS


def watched_reader():
    in_transaction.append(db._get_connection().in_transaction)
    return reader_before()


comfy_graph.set_switch_reader(watched_reader)
comfy_graph.SWITCH_SECONDS = 0
in_transaction.clear()
try:
    db.replace_first_page(V, copy.deepcopy(STORED), None)
finally:
    comfy_graph.SWITCH_SECONDS = seconds_before
    comfy_graph.set_switch_reader(reader_before)
check('232. a gallery replaced whole: the switch read on its own transaction, the copy\'s reader never asked',
      in_transaction, [])

# A store held at the write lock while the other WebUI turns the switch on:
# its rows follow the switch as it stands when they are written.
import sqlite3                                          # noqa: E402
import threading                                        # noqa: E402
turn(False)
other = sqlite3.connect(db.db_path, timeout=30)
other.execute('BEGIN IMMEDIATE')
other.execute("INSERT OR REPLACE INTO schema_info (key, value) VALUES ('comfy_judged', '1')")
storing = threading.Thread(target=db.store_images,
                           kwargs={'version_id': V, 'page': 9, 'images': [image(9501, {'comfy': graph()})]})
storing.start()
storing.join(1.0)
held_at_lock = storing.is_alive()
other.commit()
other.close()
storing.join(30)
with db._cursor() as cursor:
    cursor.execute('SELECT p.text FROM images i LEFT JOIN image_prompts p ON p.id = i.prompt_id WHERE i.id = 9501')
    raced = (cursor.fetchone() or (None,))[0]
check('232. a store that waited for the lock while the switch turned on: its rows filled',
      (held_at_lock, comfy_graph.switch()[0], raced), (True, False, 'a fox at dusk'))
turn(True, comfy_graph.READER)

with db._cursor() as cursor:
    cursor.execute('SELECT i.id, p.text FROM images i LEFT JOIN image_prompts p ON p.id = i.prompt_id '
                   'WHERE i.id IN (9101, 9103)')
    prompts_on = dict(cursor.fetchall())
    cursor.execute('SELECT image_id, effective_nsfw_level FROM image_galleries WHERE image_id IN (9101, 9103)')
    levels_on = dict(cursor.fetchall())
    cursor.execute('SELECT shift, cfg, sampler FROM image_params WHERE image_id = 9101')
    settings_on = tuple(cursor.fetchone() or ())
check('232. switch on: stored with the graph\'s prompt, level and settings',
      (prompts_on, levels_on, settings_on),
      ({9101: 'a fox at dusk', 9103: 'a %s figure' % EXPLICIT}, {9101: 1, 9103: 8}, (3.0, 6.5, 'euler')))
with db._cursor() as cursor:
    cursor.execute('SELECT image_id, data FROM image_records WHERE image_id IN (9101, 9102, 9103, 9104)')
    records_on = dict(cursor.fetchall())
check('232. switch on: each stored record the same text, byte for byte, as stored with the switch off',
      records_on, records_off)
comfy_graph.reads = 0
with comfy_graph._answers_lock:
    comfy_graph._answers.clear()
db.store_images(V, page=8, images=[image(9401, {'comfy': graph('a crane in the reeds')})])
check('232. switch on: storing an image reads its graph once', comfy_graph.reads, 1)
check('232. switch on: the stored records still Civitai\'s, as given',
      sorted((r['id'], json.dumps(r['meta'], sort_keys=True)) for r in db.stored_records([9101, 9102, 9103, 9104])),
      sorted((r['id'], json.dumps(r['meta'], sort_keys=True)) for r in given))
fresh = [image(9101, {'comfy': graph(), 'steps': 20})]
keep_generation_data(fresh, db.stored_records([9101]))
check('232. switch on: a sync\'s fresh copy still has no prompt, still looked up for Civitai\'s',
      ('prompt' in fresh[0]['meta'], generation_ids_needing_lookup(fresh)), (False, [9101]))

comfy_graph.reads = 0
with comfy_graph._answers_lock:
    comfy_graph._answers.clear()
hiding_on = gallery_page(db, V, 1, ALL, True, fetch=False)
with_graph = sorted(i['id'] for i in hiding_on['images'] if comfy_graph.has_graph(i['meta']))
check('232. one page request reads each graph on it once', (comfy_graph.reads, len(with_graph) >= 3),
      (len(with_graph), True))
check('232. switch on: with images with no prompt hidden, the graph\'s prompt keeps the image',
      (sorted(i['id'] for i in hiding_on['images'] if 9101 <= i['id'] <= 9104),
       hiding_on['page'].get('hidden_promptless')), ([9101, 9102, 9103, 9104], 0))
check('232. switch on: the page\'s hidden counts equal the banner\'s',
      {k: hiding_on['page'].get(k) for k in ('hidden_promptless', 'hidden_nsfw', 'hidden_both')},
      {k: hiding_on['images_state'].get(k) for k in ('hidden_promptless', 'hidden_nsfw', 'hidden_both')})
check('232. switch on: each image judged by its filled data, the explicit graph prompt read',
      {i['id']: i['mm_level'] for i in hiding_on['images'] if i['id'] in (9101, 9103)}, {9101: 1, 9103: 8})
tiles_on = {t['image']['id']: t['image'] for t in gallery_api.image_tiles(db, [(9101, V), (9103, V)])}
check('232. switch on: the Civitai Images tab judged filled',
      {i: tiles_on.get(i, {}).get('mm_level') for i in (9101, 9103)}, {9101: 1, 9103: 8})
check('232. switch on: a version\'s covers at sync pass over the image whose graph prompt is explicit',
      version_covers(copy.deepcopy([EXPLICIT_GRAPH, ONLY_GRAPH]), complete=True)[1], ONLY_GRAPH['url'])
check('232. switch on: your own generation is judged as before, its graph never read (generated_level)',
      generated_level({'comfy': graph('a %s figure' % EXPLICIT)}), 1)

# The other WebUI sharing the database turns the switch: followed at the
# next read, every SWITCH_SECONDS; a read that fails keeps what was held.
with db._cursor() as cursor:
    cursor.execute("DELETE FROM schema_info WHERE key = 'comfy_judged'")
held = comfy_graph.judging_filled()
comfy_graph._switch['read_at'] -= comfy_graph.SWITCH_SECONDS
check('232. the other WebUI turns it: held until the next read, followed at it',
      (held, comfy_graph.judging_filled()), (True, False))
comfy_graph.set_switch(True, comfy_graph.READER)


def unreadable():
    raise OSError('unreadable')


comfy_graph._switch['reader'] = unreadable
comfy_graph._switch['read_at'] -= comfy_graph.SWITCH_SECONDS
check('232. a read that fails keeps what was held, and does not raise', comfy_graph.judging_filled(), True)
turn(True, comfy_graph.READER)

# The rules read nothing of the database: a rule suite opens none.
imported = subprocess.run(
    [sys.executable, '-c', 'import sys; sys.path.insert(0, %r); import model_manager.nsfw, '
     'model_manager.prompt_rules, model_manager.comfy_graph; print("model_manager.db" in sys.modules)' % ROOT],
    capture_output=True, text=True, timeout=60)
check('232. the level and prompt rules import nothing of the database', imported.stdout.strip(), 'False')

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
