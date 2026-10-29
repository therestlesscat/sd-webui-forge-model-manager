"""
Generations recorded twice (#241, #364): the repair that lists the early
copies a press left before 0.70.5, and removes only those the person ticks
(model_manager/repairs/recorded_twice.py), through its routes and the list
of repairs the page asks at load, and the note that points to it.

An early copy: a recorded generation when a later recorded one has the same
creation time and holds all its images. Built here: a pair, a chain of three,
two presses holding one file at two times (Forge's Override), and a synced
generation sharing a recorded one's time and file - only the first two list.
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

WORK = os.path.join(TESTS, 'work', 'generations_review')
opts = webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.release_notes as rn                 # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.install import INSTALL_KEY            # noqa: E402
from model_manager.nsfw import PG, PG13, R, X            # noqa: E402
from model_manager.repairs import recorded_twice         # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
OUT = os.path.join(WORK, 'outputs')
os.makedirs(OUT, exist_ok=True)


def record(created, names, prompt='a lighthouse', levels=None, rated=None, synced=False, n_iter=None):
    """One generation of these files, each written to disk; `levels` rates
    images by name, `rated` the generation."""
    rows = []
    for i, name in enumerate(names):
        path = os.path.join(OUT, name)
        with open(path, 'wb') as f:
            f.write(b'an image: ' + name.encode())
        rows.append({'position': i, 'path': path, 'prompt': prompt, 'prompt_nsfw_level': PG,
                     'user_nsfw_level': (levels or {}).get(name)})
    generation = {'created_at': created, 'mode': 'txt2img', 'prompt': prompt, 'image_count': len(rows),
                  'prompt_nsfw_level': PG, 'user_nsfw_level': rated, 'n_iter': n_iter}
    if synced:
        generation['source_id'] = 1
    return db.record_generation(generation, rows, [[] for _ in rows])


def count(table, where='1'):
    return db._get_connection().execute(f'SELECT COUNT(*) FROM {table} WHERE {where}').fetchone()[0]


# A press at batch count 2: its first batch written early, then all of it.
pair_early = record('2026-10-22T12:24:09', ['p0.png', 'p1.png'], levels={'p0.png': X, 'p1.png': R}, rated=R,
                    n_iter=2)
pair_kept = record('2026-10-22T12:24:09', ['p0.png', 'p1.png', 'p2.png', 'p3.png'], levels={'p1.png': PG13},
                   n_iter=2)
task = db.add_task({'install': INSTALL_KEY, 'mode': 'txt2img', 'inputs': {'fixed': {}}})
db.link_task_generation(task, pair_early)
# Batch count 3: two early copies, the last holds all.
chain = [record('2026-10-22T12:26:37', ['c%d.png' % i for i in range(n)], prompt='a fox', n_iter=3)
         for n in (2, 4, 6)]
# Forge's Override: a later press saved over an earlier one's file.
override = [record('2026-10-22T13:00:00', ['o0.png']), record('2026-10-22T13:05:00', ['o0.png'])]
# A synced generation sharing a recorded one's time and a file.
synced = record('2026-10-22T14:00:00', ['s0.png'], synced=True)
beside_synced = record('2026-10-22T14:00:00', ['s0.png', 's1.png'])

app = FastAPI()
setup_api(app)
client = TestClient(app)


def repairs():
    """Each repair named, with its count, checked to name its tab."""
    named = client.get('/model-manager/repairs').json().get('repairs')
    check('a repair named says its tab', all(r.get('tab') == 'generations' for r in (named or {}).values()))
    return {name: r.get('count') for name, r in (named or {}).items()}


# ------------------------------------------------------------------ the list
opts.model_manager_generations_hide_nsfw = False
check('the list of repairs names this one, with how many early copies: the pair\'s and the chain\'s first two',
      repairs(), {'recorded_twice': 3})
listed = client.get('/model-manager/repairs/recorded-twice').json()
early = {row['id']: row for row in listed.get('early') or []}
check('each early copy listed, newest first - not the Override pair, not the synced one',
      [row['id'] for row in listed.get('early') or []], [chain[1], chain[0], pair_early])
check('each beside the generation kept: the last of its press',
      {i: (row['kept'], row['images'], row['kept_images']) for i, row in early.items()},
      {pair_early: (pair_kept, 2, 4), chain[0]: (chain[2], 2, 6), chain[1]: (chain[2], 4, 6)})
check('with how many early copies its press left, and its batch count',
      [(early[i]['same_press'], early[i]['batch_count']) for i in (pair_early, chain[0])], [(1, 2), (2, 3)])
check('the hide setting off: every preview and prompt shown',
      [(early[i]['image_id'] is not None, early[i]['prompt'], early[i]['hidden_level']) for i in (pair_early, chain[0])],
      [(True, 'a lighthouse', None), (True, 'a fox', None)])
opts.model_manager_generations_hide_nsfw = True
early = {row['id']: row for row in client.get('/model-manager/repairs/recorded-twice').json().get('early') or []}
check('on: an image rated above PG-13 is hidden as the Generations tab hides it, its prompt too',
      [(early[i]['image_id'], early[i]['prompt'], early[i]['hidden_level']) for i in (pair_early,)],
      [(None, None, 'X')])
check('and one rated PG shown', (early[chain[0]]['image_id'] is not None, early[chain[0]]['prompt']), (True, 'a fox'))
opts.model_manager_generations_hide_nsfw = False

# ---------------------------------------------------------------- the note
db.set_info(rn.CREATED_BY, '0.70.0')
check('the Generations tab\'s note shows while there are early copies',
      'recorded-twice-0-70-5' in [n['id'] for n in rn.notes_for(db, 'generations')], True)

# ---------------------------------------------------------------- removing
files = sorted(os.listdir(OUT))
answer = client.post('/model-manager/repairs/recorded-twice/remove',
                     data={'ids': '%d,%d,99999999' % (pair_early, chain[0])}).json()
check('Remove takes the ticked ones, and says what it skipped',
      (answer.get('removed'), answer.get('skipped')),
      ([pair_early, chain[0]], [{'id': 99999999, 'why': 'already gone'}]))
check('their rows gone from every table',
      [count(t, 'generation_id IN (%d, %d)' % (pair_early, chain[0]))
       for t in ('generation_images', 'generation_details', 'task_generations')]
      + [count('generations', 'id IN (%d, %d)' % (pair_early, chain[0]))], [0, 0, 0, 0])
check('the generations kept whole', [db.get_generation(i)['image_count'] for i in (pair_kept, chain[2])], [4, 6])
check('no image file deleted', sorted(os.listdir(OUT)), files)
kept = {os.path.basename(i['path']): i['id'] for i in db.get_generation(pair_kept)['images']}
levels = dict(db._get_connection().execute(
    'SELECT id, user_nsfw_level FROM generation_images WHERE generation_id = ?', (pair_kept,)).fetchall())
check('an image\'s rating moves to the kept generation\'s image of the same file',
      levels[kept['p0.png']], X)
check('unless that one has a rating of its own', levels[kept['p1.png']], PG13)
check('the generation\'s rating moves too',
      db._get_connection().execute('SELECT user_nsfw_level FROM generations WHERE id = ?',
                                   (pair_kept,)).fetchone()[0], R)
check('and the link to the queued task that made it',
      count('task_generations', 'task_id = %d AND generation_id = %d' % (task, pair_kept)), 1)

# ---------------------------------------------- one no longer recorded twice
db.delete_generation(chain[2])
answer = client.post('/model-manager/repairs/recorded-twice/remove', data={'ids': str(chain[1])}).json()
check('its kept generation deleted meanwhile: skipped, said why, nothing of it deleted',
      (answer.get('removed'), answer.get('skipped'), count('generations', 'id = %d' % chain[1])),
      ([], [{'id': chain[1], 'why': 'no longer recorded twice: the generation kept was deleted'}], 1))
check('nothing ticked: nothing removed',
      client.post('/model-manager/repairs/recorded-twice/remove', data={'ids': ''}).json(),
      {'success': True, 'removed': [], 'skipped': []})
check('none left: the list of repairs names nothing', repairs(), {})
check('and the note is gone', 'recorded-twice-0-70-5' in [n['id'] for n in rn.notes_for(db, 'generations')], False)
check('the Override pair and the synced one untouched',
      [count('generations', 'id = %d' % i) for i in override + [synced, beside_synced]], [1, 1, 1, 1])

# ------------------------------------------------- the Generations tab off
record('2026-10-22T15:00:00', ['t0.png'])
record('2026-10-22T15:00:00', ['t0.png', 't1.png'])
check('a new early copy is named', repairs(), {'recorded_twice': 1})
opts.model_manager_record_generations = False
check('with the Generations tab off, the repair is not named', repairs(), {})
check('and its routes refuse',
      [client.get('/model-manager/repairs/recorded-twice').status_code,
       client.post('/model-manager/repairs/recorded-twice/remove', data={'ids': '1'}).status_code], [403, 403])
opts.model_manager_record_generations = True
check('needed() counts what the list names', recorded_twice.needed(db), 1)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
