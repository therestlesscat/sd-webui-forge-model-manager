"""
LoRA weights saved as 1 (#392): the repair that lists the generations whose
LoRAs the recorder saved at weight 1 before 0.78.9, whatever their tags said,
and corrects only those the person ticks (model_manager/repairs/lora_weights.py),
through its routes.

Its rows are built here, as the recorder wrote them before 0.78.9 - every
base-pass LoRA at 1.0 - not from the shared generation fixture, whose weights
the recorder never wrote. The right weight is the tag's in the prompt of the
batch's first image.
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

import webui_stub                                        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'repair_lora_weights')
opts = webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.api import common, setup_api          # noqa: E402
from model_manager.nsfw import PG, X                     # noqa: E402
from model_manager.repairs import lora_weights           # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
OUT = os.path.join(WORK, 'outputs')
os.makedirs(OUT, exist_ok=True)
made = [0]


def base(name, te=1.0, unet=1.0):
    """A base-pass entry as the recorder wrote it before 0.78.9: at 1.0."""
    return {'name': name, 'path': None, 'te_multiplier': te, 'unet_multiplier': unet, 'pass': 'base'}


def record(images, batch_size=1, typed='typed', synced=False, positions=None, level=PG, n_iter=1):
    """One recorded generation: each image (its prompt, its LoRA entries),
    at its place in the batches - or at `positions`, for an image not kept."""
    rows = []
    for i, (prompt, loras) in enumerate(images):
        made[0] += 1
        path = os.path.join(OUT, '%05d.png' % made[0])
        with open(path, 'wb') as f:
            f.write(b'an image')
        position = positions[i] if positions else i
        rows.append({'position': position, 'iteration': position // batch_size, 'path': path, 'prompt': prompt,
                     'prompt_nsfw_level': level, 'loras': loras})
    generation = {'created_at': '2026-11-%02dT10:00:00' % (1 + made[0] % 28), 'mode': 'txt2img', 'prompt': typed,
                  'image_count': len(rows), 'prompt_nsfw_level': PG, 'n_iter': n_iter, 'batch_size': batch_size}
    if synced:
        generation['source_id'] = 1
    return db.record_generation(generation, rows, [[] for _ in rows])


def details(generation_id):
    """Each image's record and index weights, by position: (loras, {place: weight})."""
    conn = db._get_connection()
    out = {}
    for image_id, position, loras in conn.execute(
            'SELECT gi.id, gi.position, d.loras FROM generation_images gi '
            'JOIN generation_image_details d ON d.image_id = gi.id WHERE gi.generation_id = ? ORDER BY position',
            (generation_id,)):
        weights = dict(conn.execute("SELECT position, weight FROM generation_resources "
                                    "WHERE image_id = ? AND role = 'lora'", (image_id,)).fetchall())
        out[position] = (json.loads(loras), weights)
    return out


def weights_of(generation_id):
    return {position: [(l['name'], l.get('te_multiplier', l.get('weight')), l.get('unet_multiplier'))
                       for l in loras] for position, (loras, _) in details(generation_id).items()}


# Each situation of the plan, as the recorder wrote it before 0.78.9.
plain = record([('a fox <lora:a:0.7>', [base('a')])])
says_one = record([('a fox <lora:a:1> <lora:b>', [base('a'), base('b')])])
synced = record([('a fox <lora:a:0.7>', [base('a')])], synced=True)
# A LoRA in both passes, its tag twice in the prompt (as "Add network to
# prompt" writes it): only the base pass's entry is corrected.
hires = record([('a fox <lora:a:0.6> <lora:h:0.5> <lora:h:0.5>',
                 [base('a'), base('h'), {'name': 'h', 'path': None, 'weight': 1.0, 'pass': 'hires'}])])
batch = record([('a fox <lora:a:0.4>', [base('a')]), ('a cat <lora:a:0.9>', [base('a')])], batch_size=2)
styled = record([('a fox, <lora:a:0.6> cinematic', [base('a')])], typed='a fox')
added = record([('a fox <lora:extra:0.6> <lora:extra:0.6> <lora:extra:0.6>', [base('extra')])])
not_kept = record([('a cat <lora:a:0.9>', [base('a')])], batch_size=2, positions=[1])
not_bug = record([('a fox <lora:a:0.7>', [base('a', 0.5, 0.5)])])
# Beside an entry the bug wrote, one it did not: only the first is corrected.
mixed = record([('a fox <lora:a:0.7> <lora:c:0.3>', [base('a'), base('c', 0.5, 0.5)])])
stale = record([('a fox <lora:a:0.7>', [base('stale'), base('a')])])
two = record([('a fox <lora:a:0.7:0.4>', [base('a')])], level=X)
# Two batches of two: each batch's own first prompt decides its images.
batches = record([('a fox <lora:a:0.4>', [base('a')]), ('a cat <lora:a:0.9>', [base('a')]),
                  ('a fox <lora:a:0.9>', [base('a')]), ('a cat <lora:a:0.4>', [base('a')])], batch_size=2, n_iter=2)
# Its second batch's first image not kept: only the first batch is read.
second_gone = record([('a fox <lora:a:0.4>', [base('a')]), ('a cat <lora:a:0.4>', [base('a')]),
                      ('a cat <lora:a:0.9>', [base('a')])], batch_size=2, n_iter=2, positions=[0, 1, 3])
schedule = record([('a fox <lora:a:1.25@0,0@0.5>', [base('a')])])
unet_only = record([('a fox <lora:a:1:0.4>', [base('a')])])
accented = record([('a fox <lora:été_style:0.7>', [base('été_style')])])
TO_CORRECT = [plain, hires, batch, styled, added, stale, two, mixed, batches, second_gone, schedule, unet_only, accented]

app = FastAPI()
setup_api(app)
lora_weights.register(app, common)
client = TestClient(app)

# ------------------------------------------------------------------ the check
check('the check counts the generations whose weights differ from their prompts\'',
      lora_weights.needed(db), len(TO_CORRECT))

# -------------------------------------------------------------------- the list
opts.model_manager_generations_hide_nsfw = False
listed = client.get('/model-manager/repairs/lora-weights').json()
rows = {row['id']: row for row in listed.get('generations') or []}
check('each listed, newest first: not one whose tag says 1, nor a synced one, nor one whose batch\'s first '
      'image was not kept, nor an entry the bug did not write',
      [row['id'] for row in listed.get('generations') or []], sorted(TO_CORRECT, reverse=True))
check('with each LoRA\'s change, from 1 to its tag\'s two weights',
      [rows[i]['changes'] for i in (plain, two)],
      [[{'name': 'a', 'from': 1.0, 'te': 0.7, 'unet': 0.7}], [{'name': 'a', 'from': 1.0, 'te': 0.7, 'unet': 0.4}]])
check('a LoRA no tag names is not among the changes', rows[stale]['changes'],
      [{'name': 'a', 'from': 1.0, 'te': 0.7, 'unet': 0.7}])
check('the batch\'s first prompt decides, for both its images', (rows[batch]['images'], rows[batch]['changes']),
      (2, [{'name': 'a', 'from': 1.0, 'te': 0.4, 'unet': 0.4}]))
check('a style\'s tag, in the image\'s prompt but not the typed one, is read',
      rows[styled]['changes'], [{'name': 'a', 'from': 1.0, 'te': 0.6, 'unet': 0.6}])
check('an image counted once, whatever number of its LoRAs are at 1',
      (rows[hires]['images'], rows[stale]['images'], rows[mixed]['images']), (1, 1, 1))
check('each batch read from its own first prompt', (rows[batches]['images'], rows[batches]['changes']),
      (4, [{'name': 'a', 'from': 1.0, 'te': 0.4, 'unet': 0.4}, {'name': 'a', 'from': 1.0, 'te': 0.9, 'unet': 0.9}]))
check('a batch whose first image was not kept is left out, the other read',
      (rows[second_gone]['images'], rows[second_gone]['changes']),
      (2, [{'name': 'a', 'from': 1.0, 'te': 0.4, 'unet': 0.4}]))
check('a weight schedule: no fixed weight, as the recorder stores since 0.78.9',
      rows.get(schedule, {}).get('changes'), [{'name': 'a', 'from': 1.0, 'te': None, 'unet': None}])
check('the UNet\'s weight alone differing', rows.get(unet_only, {}).get('changes'),
      [{'name': 'a', 'from': 1.0, 'te': 1.0, 'unet': 0.4}])
check('the "Add network to prompt" tag three times over: its one weight',
      rows[added]['changes'], [{'name': 'extra', 'from': 1.0, 'te': 0.6, 'unet': 0.6}])
check('the hide setting off: every preview and prompt shown',
      (rows[two]['image_id'] is not None, rows[two]['prompt'], rows[two]['hidden_level']), (True, 'typed', None))
opts.model_manager_generations_hide_nsfw = True
rows = {row['id']: row for row in client.get('/model-manager/repairs/lora-weights').json().get('generations') or []}
check('on: an image rated above PG-13 is hidden as the Generations tab hides it, its prompt too',
      (rows[two]['image_id'], rows[two]['prompt'], rows[two]['hidden_level']), (None, None, 'X'))
opts.model_manager_generations_hide_nsfw = False

# ------------------------------------------------------------------ correcting
untouched = {g: details(g) for g in (says_one, synced, not_kept, not_bug, styled)}
before = {g: details(g) for g in TO_CORRECT}
conn = db._get_connection()
records_before = dict(conn.execute('SELECT image_id, loras FROM generation_image_details'))
index_before = {(i, r, n): w for i, r, n, w in conn.execute(
    'SELECT image_id, role, position, weight FROM generation_resources')}
image_generation = dict(conn.execute('SELECT id, generation_id FROM generation_images'))
ticked = [g for g in TO_CORRECT if g != styled]
answer = client.post('/model-manager/repairs/lora-weights/correct',
                     data={'ids': ','.join(str(g) for g in ticked) + ',99999999'}).json()
check('Correct takes the ticked ones, and says what it skipped',
      (answer.get('corrected'), answer.get('skipped')),
      (sorted(ticked), [{'id': 99999999, 'why': 'already gone'}]))
check('each LoRA now holds its tag\'s weights',
      [weights_of(g) for g in (plain, batch, two)],
      [{0: [('a', 0.7, 0.7)]}, {0: [('a', 0.4, 0.4)], 1: [('a', 0.4, 0.4)]}, {0: [('a', 0.7, 0.4)]}])
check('and the index the text encoder\'s', [details(g)[0][1] for g in (plain, two)], [{0: 0.7}, {0: 0.7}])
check('a LoRA no tag names is left at 1', weights_of(stale), {0: [('stale', 1.0, 1.0), ('a', 0.7, 0.7)]})
check('a hires entry is left as it was, in the record and the index, its base pass\'s corrected',
      (weights_of(hires)[0][1:], details(hires)[0][1][2]), ([('h', 0.5, 0.5), ('h', 1.0, None)], 1.0))
check('an entry the bug did not write is left as it was', weights_of(mixed),
      {0: [('a', 0.7, 0.7), ('c', 0.5, 0.5)]})


def without_weights(record_of):
    return {p: ([{k: v for k, v in l.items() if k not in ('te_multiplier', 'unet_multiplier')} for l in loras],
                {k: v for k, v in index.items()}) for p, (loras, index) in record_of.items()}


check('every other key of each record as before',
      {g: {p: loras for p, (loras, _) in without_weights(details(g)).items()} for g in TO_CORRECT if g != styled},
      {g: {p: loras for p, (loras, _) in without_weights(before[g]).items()} for g in TO_CORRECT if g != styled})
check('every generation not ticked, or not to correct, as it was', {g: details(g) for g in untouched}, untouched)
check('two batches, each its own', weights_of(batches),
      {0: [('a', 0.4, 0.4)], 1: [('a', 0.4, 0.4)], 2: [('a', 0.9, 0.9)], 3: [('a', 0.9, 0.9)]})
check('the batch whose first image was not kept, left', weights_of(second_gone),
      {0: [('a', 0.4, 0.4)], 1: [('a', 0.4, 0.4)], 3: [('a', 1.0, 1.0)]})
check('a schedule: no weight, in the record and the index', (weights_of(schedule), details(schedule)[0][1]),
      ({0: [('a', None, None)]}, {0: None}))
check('the UNet\'s alone: the record set, the index keeping the text encoder\'s 1',
      (weights_of(unet_only), details(unet_only)[0][1]), ({0: [('a', 1.0, 0.4)]}, {0: 1.0}))
accented_image = conn.execute('SELECT id FROM generation_images WHERE generation_id = ?', (accented,)).fetchone()[0]
check('the record written as the recorder writes it, byte for byte but the weights',
      conn.execute('SELECT loras FROM generation_image_details WHERE image_id = ?', (accented_image,)).fetchone()[0],
      json.dumps([base('été_style', 0.7, 0.7)], ensure_ascii=False))
corrected_images = {i for i, g in image_generation.items() if g in ticked}
index_after = {(i, r, n): w for i, r, n, w in conn.execute(
    'SELECT image_id, role, position, weight FROM generation_resources')}
check('every other image\'s record as before, in every generation of the library',
      {i: t for i, t in conn.execute('SELECT image_id, loras FROM generation_image_details')
       if i not in corrected_images},
      {i: t for i, t in records_before.items() if i not in corrected_images})
check('and every index row but a LoRA at 1 in a corrected image',
      sorted(k for k in index_before if index_after.get(k) != index_before[k]
             and not (k[0] in corrected_images and k[1] == 'lora' and index_before[k] == 1.0)), [])
check('the check now counts the one not ticked', lora_weights.needed(db), 1)
NOTHING_LEFT = ('nothing left to correct: its LoRA weights match its prompt, '
                'or the image its batch\'s weights are read from is gone')
check('a second Correct changes nothing, saying why - the UNet\'s alone too',
      client.post('/model-manager/repairs/lora-weights/correct', data={'ids': '%d,%d' % (plain, unet_only)}).json(),
      {'success': True, 'corrected': [],
       'skipped': [{'id': plain, 'why': NOTHING_LEFT}, {'id': unet_only, 'why': NOTHING_LEFT}]})
check('nothing ticked: nothing corrected',
      client.post('/model-manager/repairs/lora-weights/correct', data={'ids': ''}).json(),
      {'success': True, 'corrected': [], 'skipped': []})

# ------------------------------------------ one deleted between list and Correct
db.delete_generation(styled)
check('a generation deleted since: the count drops', lora_weights.needed(db), 0)
check('and Correct skips it, saying why',
      client.post('/model-manager/repairs/lora-weights/correct', data={'ids': str(styled)}).json()['skipped'],
      [{'id': styled, 'why': 'already gone'}])

# ----------------------------------------- asked again: only newer generations
# Many generations the check reads at its first ask, none to correct...
for n in range(60):
    record([('a fox %d <lora:a:1>' % n, [base('a')])])
conn = db._get_connection()
steps = [0]


def counted(ask):
    steps[0] = 0
    conn.set_progress_handler(lambda: steps.__setitem__(0, steps[0] + 1) or 0, 1)
    try:
        return ask(), steps[0]
    finally:
        conn.set_progress_handler(None, 1)


lora_weights._KNOWN.update(db=None)
first, first_steps = counted(lambda: lora_weights.needed(db))
# ...then one more, as an older copy sharing the database records it.
newer = record([('a fox <lora:a:0.8>', [base('a')])])
again, again_steps = counted(lambda: lora_weights.needed(db))
check('a new generation saved at 1 is found at the next ask', (first, again), (0, 1))
check('which reads only it: a small part of the first ask\'s work',
      again_steps * 5 < first_steps, True)
check('the list names it', [row['id'] for row in client.get('/model-manager/repairs/lora-weights').json()['generations']],
      [newer])
# Deleting the newest generation - a result just made - keeps the answer.
newest = record([('a fox <lora:a:1>', [base('a')])])
lora_weights.needed(db)
db.delete_generation(newest)
after_delete, delete_steps = counted(lambda: lora_weights.needed(db))
check('the newest generation deleted: the answer kept, read again only for what is new',
      (after_delete, delete_steps * 5 < first_steps), (1, True))
# The other WebUI sharing the database corrects one: seen once the list is read afresh.
other = record([('a fox <lora:a:0.3>', [base('a')])])
check('another to correct', lora_weights.needed(db), 2)
other_image = conn.execute('SELECT id FROM generation_images WHERE generation_id = ?', (other,)).fetchone()[0]
conn.execute('UPDATE generation_image_details SET loras = ? WHERE image_id = ?',
             (json.dumps([base('a', 0.3, 0.3)], ensure_ascii=False), other_image))
conn.execute("UPDATE generation_resources SET weight = 0.3 WHERE image_id = ? AND role = 'lora'", (other_image,))
conn.commit()
check('corrected elsewhere: the list no longer names it',
      [row['id'] for row in client.get('/model-manager/repairs/lora-weights').json()['generations']], [newer])
check('and the check, read afresh by the list, counts one', lora_weights.needed(db), 1)

# ------------------------------------------------- the Generations tab off
opts.model_manager_record_generations = False
check('with the Generations tab off, its routes refuse',
      [client.get('/model-manager/repairs/lora-weights').status_code,
       client.post('/model-manager/repairs/lora-weights/correct', data={'ids': '1'}).status_code], [403, 403])
opts.model_manager_record_generations = True

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
