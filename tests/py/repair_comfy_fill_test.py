"""
Civitai images filled from their ComfyUI workflows (#232): the Fill notice's
job and routes (model_manager/repairs/comfy_fill.py) on a library from before
0.81.5 - stored images' derived rows made from Civitai's fields alone - and
what Fill writes: only the derived rows that differ, never the record, never
an image a gallery took out. Its window and note are the page's (commit 3).
"""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'repair_comfy_fill')
opts = webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager import comfy_graph, prompt_levels     # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.jobs import jobs                      # noqa: E402
from model_manager.repairs import comfy_fill             # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
V = facts['version_ids'][0]
comfy_graph.SWITCH_SECONDS = 0.05     # the wait Fill gives the other WebUI


def node(kind, **inputs):
    return {'class_type': kind, 'inputs': inputs}


def graph(prompt='a fox at dusk'):
    return {'prompt': {
        '5': node('EmptyLatentImage', width=512, height=768, batch_size=1),
        '4': node('CheckpointLoaderSimple', ckpt_name='SD\\graph_ck.safetensors'),
        '10': node('ModelSamplingSD3', shift=3.0, model=['4', 0]),
        '6': node('CLIPTextEncode', text=prompt, clip=['4', 1]),
        '7': node('CLIPTextEncode', text='blurry', clip=['4', 1]),
        '3': node('KSampler', seed=7, steps=25, cfg=6.5, sampler_name='euler', scheduler='normal', denoise=1.0,
                  model=['10', 0], positive=['6', 0], negative=['7', 0], latent_image=['5', 0]),
        '8': node('VAEDecode', samples=['3', 0], vae=['4', 2]),
        '9': node('SaveImage', images=['8', 0])}}


def image(image_id, meta, level=1):
    return {'id': image_id, 'url': 'https://image.civitai.com/x/%d.jpeg' % image_id, 'width': 512, 'height': 768,
            'browsingLevel': level, 'meta': meta}


def turn(on, filled=None):
    """The switch's two values as stored, and this process's copy read again."""
    with db._cursor() as cursor:
        cursor.execute("DELETE FROM schema_info WHERE key IN ('comfy_judged', 'comfy_fill')")
        if on:
            cursor.execute("INSERT INTO schema_info (key, value) VALUES ('comfy_judged', '1')")
        if filled is not None:
            cursor.execute("INSERT INTO schema_info (key, value) VALUES ('comfy_fill', ?)", (str(filled),))
    comfy_graph.set_switch_reader(db._read_comfy_switch)


def one(sql, *args):
    with db._cursor() as cursor:
        cursor.execute(sql, args)
        row = cursor.fetchone()
        return tuple(row) if row is not None else None


def rows(sql, *args):
    with db._cursor() as cursor:
        cursor.execute(sql, args)
        return [tuple(r) for r in cursor.fetchall()]


def prompt_of(image_id):
    row = one('SELECT p.text FROM images i LEFT JOIN image_prompts p ON p.id = i.prompt_id WHERE i.id = ?',
              image_id)
    return row[0] if row else 'no image row'


def records(ids):
    return dict(rows(f"SELECT image_id, data FROM image_records WHERE image_id IN ({','.join('?' * len(ids))})",
                     *ids))


def fill_now():
    """One run of Fill on this thread: its progress."""
    fill = comfy_fill.Fill()
    comfy_fill.run(fill, db)
    return fill.progress


# A library from before 0.81.5: neither value, every image stored from
# Civitai's fields alone.
turn(False)
ONLY = image(9101, {'comfy': graph(), 'steps': 20})                         # its prompt only in the graph
EXPLICIT = image(9102, {'comfy': graph('a nude figure')})                     # an explicit graph prompt
OWN = image(9103, {'comfy': graph(), 'prompt': 'a civitai prompt', 'sampler': 'Euler', 'steps': 30,
                   'cfgScale': 7, 'seed': 1, 'Shift': 3.0})                   # Civitai's own kept; gains its negative
PLAIN = image(9104, {'prompt': 'no workflow here at all'})
GONE = image(9105, {'comfy': graph('one a gallery removes')})
STORED = [ONLY, EXPLICIT, OWN, PLAIN, GONE]
db.store_images(V, page=1, images=json.loads(json.dumps(STORED)))
IDS = [i['id'] for i in STORED]
before = records(IDS)
check('a library from before: each graph image stored from Civitai\'s fields',
      ([prompt_of(9101), prompt_of(9102)], one('SELECT COUNT(*) FROM image_params WHERE image_id = 9102')[0],
       one('SELECT effective_nsfw_level FROM image_galleries WHERE image_id = 9102')[0]), ([None, None], 0, 1))

# --------------------------------------------------------- the check, the state
check('the check: work while the library is not filled with this reader', comfy_fill.needed(db), 1)
turn(True, comfy_graph.READER)
check('none once filled with it', (comfy_fill.needed(db), comfy_fill.newer_copy(db)), (0, False))
turn(True, comfy_graph.READER + 1)
check('a newer copy\'s reader: no work, Fill refused, the switch on',
      (comfy_fill.needed(db), comfy_fill.newer_copy(db), comfy_graph.switch()[0]), (0, True, True))
refused = None
try:
    fill_now()
except RuntimeError as e:
    refused = 'newer copy' in str(e)
check('Fill run on a newer copy\'s database raises, writing nothing',
      (refused, one("SELECT value FROM schema_info WHERE key = 'comfy_fill'")[0]),
      (True, str(comfy_graph.READER + 1)))
turn(True, comfy_graph.READER - 1)
check('an older reader\'s: work again', comfy_fill.needed(db), 1)
turn(False)

# -------------------------------------------------- what Fill writes, and not
# A gallery removes 9105 while Fill runs: its rows go, and Fill, reading each
# record again inside its transaction, must not bring them back.
with db._cursor() as cursor:
    cursor.execute('DELETE FROM image_galleries WHERE image_id = 9105')
    cursor.execute('DELETE FROM images WHERE id = 9105')
    cursor.execute('DELETE FROM image_params WHERE image_id = 9105')

# Every write Fill makes to the derived rows, logged by triggers of this
# connection's own (Fill runs here, on this thread).
with db._cursor() as cursor:
    cursor.execute('CREATE TEMP TABLE writes (what TEXT, image_id INTEGER)')
    for table, key in (('images', 'id'), ('image_params', 'image_id'), ('image_galleries', 'image_id'),
                       ('image_records', 'image_id')):
        for event, row in (('INSERT', 'NEW'), ('UPDATE', 'NEW'), ('DELETE', 'OLD')):
            cursor.execute(f'CREATE TEMP TRIGGER log_{table}_{event} AFTER {event} ON main.{table} '
                           f"BEGIN INSERT INTO writes VALUES ('{table} {event}', {row}.{key}); END")

# A version's safe cover on the image whose graph prompt is explicit: Fill,
# judging it X, clears it as the restamp would.
with db._cursor() as cursor:
    cursor.execute("UPDATE versions SET safe_cover_url = ? WHERE id = ?", (EXPLICIT['url'], V))

# The copy in memory stays off through the run: Fill must judge filled anyway.
set_switch = comfy_graph.set_switch
comfy_graph.set_switch_reader(None)
comfy_graph.set_switch = lambda judged, filled=None: None
try:
    progress = fill_now()
finally:
    comfy_graph.set_switch = set_switch
first_writes = sorted(set(r[0] for r in rows('SELECT what FROM writes')))
check('Fill judges filled whatever the copy in memory says',
      (prompt_of(9101), comfy_graph.judging_filled()), ('a fox at dusk', False))
comfy_graph.set_switch_reader(db._read_comfy_switch)

check('an image whose prompt is only in its graph: its prompt row, found by search and kept by "no prompt"',
      prompt_of(9101), 'a fox at dusk')
check('its negative and its settings row, inserted where it had none',
      ((one('SELECT n.text FROM images i JOIN image_prompts n ON n.id = i.negative_id WHERE i.id = 9101')
        or (None,))[0],
       one('SELECT shift, cfg, sampler FROM image_params WHERE image_id = 9101')),
      ('blurry', (3.0, 6.5, 'euler')))
check('an explicit graph prompt: its level on every gallery row judged from it',
      rows('SELECT effective_nsfw_level FROM image_galleries WHERE image_id = 9102'), [(8,)])
check('Civitai\'s own prompt and settings kept where it gives them',
      (prompt_of(9103), one('SELECT sampler, steps FROM image_params WHERE image_id = 9103')),
      ('a civitai prompt', ('Euler', 30)))
check('an image a gallery removed while Fill ran: not brought back',
      (one('SELECT COUNT(*) FROM images WHERE id = 9105')[0],
       one('SELECT COUNT(*) FROM image_galleries WHERE image_id = 9105')[0],
       one('SELECT COUNT(*) FROM image_params WHERE image_id = 9105')[0]), (0, 0, 0))
check('every record byte for byte as stored', records(IDS), before)
check('nothing deleted from the derived rows, no record written',
      [w for w in first_writes if w.endswith('DELETE') or w.startswith('image_records')], [])
check('the switch on and this reader stored',
      rows("SELECT key, value FROM schema_info WHERE key IN ('comfy_judged', 'comfy_fill') ORDER BY key"),
      [('comfy_fill', str(comfy_graph.READER)), ('comfy_judged', '1')])
check('its progress: what it read and changed',
      {k: progress.to_dict()[k] for k in ('state', 'total', 'done', 'read', 'gained', 'prompts', 'levels')},
      {'state': 'done', 'total': 4, 'done': 4, 'read': 3, 'gained': 3, 'prompts': 2, 'levels': 1})
check('the check: no work left', comfy_fill.needed(db), 0)
check('an image with no settings row until filled: its row inserted',
      one('SELECT shift, cfg, sampler FROM image_params WHERE image_id = 9102'), (3.0, 6.5, 'euler'))
check('a version\'s safe cover now above PG-13: cleared, and counted',
      (one('SELECT safe_cover_url FROM versions WHERE id = ?', V)[0], progress.covers), ('', 1))

# Run again: everything already as filled, nothing written.
with db._cursor() as cursor:
    cursor.execute('DELETE FROM writes')
again = fill_now()
check('a second run writes nothing that already holds, and counts nothing',
      (rows('SELECT what FROM writes'), again.gained, again.prompts, again.levels, again.read), ([], 0, 0, 0, 3))

# A prompt Civitai gives as empty text, or spaces, is one it does not give:
# filled, and counted as gained. A record nested too deep for the original
# Forge's Python is passed over, not the batch failed.
turn(False)
db.store_images(V, page=2, images=[image(9201, {'comfy': graph('an otter asleep'), 'prompt': '   '})])
deep = '[' * 1500 + ']' * 1500
with db._cursor() as cursor:
    cursor.execute("INSERT INTO image_records (image_id, url, data) VALUES (9202, 'u', ?)",
                   (json.dumps(image(9202, {'comfy': graph('too deep')}))[:-1] + ', "deep": ' + deep + '}',))
    cursor.execute("INSERT INTO images (id) VALUES (9202)")
import model_manager.db.images_ops as images_ops   # noqa: E402
loads_before = images_ops.json.loads


def deep_refused(text, *a, **k):
    if isinstance(text, str) and '[' * 1000 in text:
        raise RecursionError('maximum recursion depth exceeded')   # as the original Forge's Python does
    return loads_before(text, *a, **k)


images_ops.json.loads = deep_refused
try:
    spaces = db.fill_stored([9201, 9202])
except Exception as e:                           # a failure fails the check, not the suite
    spaces = {'prompts': repr(e), 'read': None}
finally:
    images_ops.json.loads = loads_before
check('a prompt of spaces is no prompt: filled and counted; a record too deep passed over, not the batch failed',
      (prompt_of(9201), spaces['prompts'], spaces['read']), ('an otter asleep', 1, 1))
with db._cursor() as cursor:
    cursor.execute('DELETE FROM image_records WHERE image_id IN (9201, 9202)')
    cursor.execute('DELETE FROM images WHERE id IN (9201, 9202)')
    cursor.execute('DELETE FROM image_galleries WHERE image_id IN (9201, 9202)')

# ------------------------------------------- a record stored again meanwhile
# Stored again by a store that judged it the old way (an older copy sharing
# the database): Fill reads it as it is now.
turn(False)
db.store_images(V, page=1, images=[image(9101, {'comfy': graph('a heron at dawn'), 'steps': 20})])
check('stored again by Civitai\'s fields: no prompt row', prompt_of(9101), None)
db.fill_stored([9101])
check('Fill reads it as it is now: the new graph\'s prompt', prompt_of(9101), 'a heron at dawn')

# ----------------------------------------- a run stopped half-way, run again
turn(False)
db.store_images(V, page=1, images=json.loads(json.dumps([ONLY, EXPLICIT])))
batch_before, fill_stored = comfy_fill.BATCH, db.fill_stored
done_once = []


def stops_after_one(ids):
    if done_once:
        raise RuntimeError('the WebUI stopped')
    done_once.append(list(ids))
    return fill_stored(ids)


comfy_fill.BATCH = 1
db.fill_stored = stops_after_one
stopped = None
try:
    fill_now()
except RuntimeError as e:
    stopped = str(e)
finally:
    db.fill_stored = fill_stored
    comfy_fill.BATCH = batch_before
check('a run stopped half-way: no reader stored, the switch on, the work still there',
      (stopped, one("SELECT value FROM schema_info WHERE key = 'comfy_fill'"), comfy_fill.needed(db),
       (one("SELECT value FROM schema_info WHERE key = 'comfy_judged'") or (None,))[0]),
      ('the WebUI stopped', None, 1, '1'))
with db._cursor() as cursor:
    cursor.execute('DELETE FROM writes')
fill_now()
check('run again: the rest filled, the batch done before not written again',
      (prompt_of(9101), rows('SELECT effective_nsfw_level FROM image_galleries WHERE image_id = 9102'),
       comfy_fill.needed(db), [r for r in rows('SELECT what, image_id FROM writes') if r[1] in done_once[0]]),
      ('a fox at dusk', [(8,)], 0, []))

# ------------------------------------------------- a restamp running at the press
turn(False)
release = threading.Event()


class HeldRestamp:
    progress = type('P', (), {'fail': lambda self, m: None})()

    def again(self):
        return False

    def cancel(self):
        pass


db.store_images(V, page=1, images=json.loads(json.dumps([ONLY, EXPLICIT])))


def held_restamp(service):
    """A restamp that judged before the switch turned: on release it writes
    the level Civitai's data alone gives 9102, as it would."""
    release.wait(10)
    with db._cursor() as cursor:
        cursor.execute('UPDATE image_galleries SET effective_nsfw_level = 1 WHERE image_id = 9102')


jobs.start(prompt_levels.KIND, HeldRestamp, held_restamp)
pressed = comfy_fill.start(db)
time.sleep(0.3)
waiting = (comfy_fill.progress()['step'], one("SELECT value FROM schema_info WHERE key = 'comfy_judged'"))
joined = comfy_fill.start(db)
same_job = jobs.service(comfy_fill.KIND)
release.set()
jobs.join(10)
check('a restamp running at the press: Fill waits for it, the switch not yet turned',
      (pressed['state'], waiting), ('running', ('waiting', None)))
check('a second press while it runs joins it', (joined['started'] == pressed['started'],
                                                  jobs.service(comfy_fill.KIND) is same_job), (True, True))
check('then it runs to the end, its levels the filled ones over the held restamp\'s',
      (comfy_fill.progress()['state'], rows('SELECT effective_nsfw_level FROM image_galleries WHERE image_id = 9102')),
      ('done', [(8,)]))

# A restamp the other WebUI started before the switch turned, whose write
# comes after Fill's: a level changed between its read and its write is kept.
turn(False)
db.store_images(V, page=1, images=json.loads(json.dumps([ONLY])))
with db._cursor() as cursor:
    cursor.execute('UPDATE image_galleries SET effective_nsfw_level = 4 WHERE image_id = 9101')   # read as 4


def fill_meanwhile(judged, total):
    if judged == 0:            # once the restamp has read every record, before it writes
        with db._cursor() as cursor:
            cursor.execute('UPDATE image_galleries SET effective_nsfw_level = 8 WHERE image_id = 9101')


db.restamp_image_levels(progress=fill_meanwhile)
check('a restamp keeps a level another writer changed between its read and its write',
      rows('SELECT effective_nsfw_level FROM image_galleries WHERE image_id = 9101'), [(8,)])
with db._cursor() as cursor:
    cursor.execute('UPDATE image_galleries SET effective_nsfw_level = 4 WHERE image_id = 9101')
db.restamp_image_levels()
check('and still writes its own where none did', rows('SELECT effective_nsfw_level FROM image_galleries WHERE image_id = 9101'),
      [(1,)])

# A newer copy that fills the database while this one runs keeps its version.
turn(False)
newer_meanwhile = db.fill_stored


def newer_fills_meanwhile(ids):
    answer = newer_meanwhile(ids)
    with db._cursor() as cursor:
        cursor.execute("INSERT OR REPLACE INTO schema_info (key, value) VALUES ('comfy_fill', ?)",
                       (str(comfy_graph.READER + 1),))
    return answer


db.fill_stored = newer_fills_meanwhile
try:
    fill_now()
finally:
    db.fill_stored = newer_meanwhile
check('a newer copy that filled it meanwhile keeps its version',
      one("SELECT value FROM schema_info WHERE key = 'comfy_fill'")[0], str(comfy_graph.READER + 1))

# ------------------------------------------------- two Fills on one database
turn(False)
db.store_images(V, page=1, images=json.loads(json.dumps([ONLY, EXPLICIT])))
ended = []
two = [threading.Thread(target=lambda: ended.append(fill_now().state)) for _ in range(2)]
for t in two:
    t.start()
for t in two:
    t.join(30)
check('two Fills at once, as two WebUIs would run: both end, the rows as one Fill leaves them',
      (sorted(ended), prompt_of(9101), rows('SELECT effective_nsfw_level FROM image_galleries WHERE image_id = 9102'),
       records([9101, 9102]) == {k: before[k] for k in (9101, 9102)}), (['done', 'done'], 'a fox at dusk', [(8,)], True))

# ------------------------------------------------------------- the routes
app = FastAPI()
setup_api(app)
client = TestClient(app)
turn(False)
for key in ('model_manager_model_manager_enabled', 'model_manager_gallery_tab'):
    setattr(opts, key, False)
off = client.get('/model-manager/repairs/comfy-fill')
off_post = client.post('/model-manager/repairs/comfy-fill/start')
check('both tabs off: its routes refused', (off.status_code, off_post.status_code), (403, 403))
setattr(opts, 'model_manager_gallery_tab', True)
answer = client.get('/model-manager/repairs/comfy-fill')
check('the Civitai Images tab alone on: answered, with work to do',
      (answer.status_code, answer.json().get('needed'), answer.json().get('newer')), (200, True, False))
setattr(opts, 'model_manager_gallery_tab', False)
setattr(opts, 'model_manager_model_manager_enabled', True)
check('the Model Manager alone on: answered', client.get('/model-manager/repairs/comfy-fill').status_code, 200)
turn(True, comfy_graph.READER + 1)
newer = client.post('/model-manager/repairs/comfy-fill/start')
check('Fill pressed on a newer copy\'s database: refused, saying why',
      (newer.status_code, newer.json().get('success'), 'Update this copy' in newer.json().get('error', '')),
      (409, False, True))
turn(False)
started = client.post('/model-manager/repairs/comfy-fill/start')
jobs.join(10)
before_press = comfy_fill.progress()['started']
idle = client.post('/model-manager/repairs/comfy-fill/start')
check('Fill pressed once filled (a stale page): nothing run, the last run answered',
      (idle.json().get('needed'), idle.json()['fill']['started'] == before_press), (False, True))
check('Fill pressed: started, and done', (started.status_code, started.json().get('success'),
                                          client.get('/model-manager/repairs/comfy-fill').json()['fill']['state']),
      (200, True, 'done'))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
