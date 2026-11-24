"""
Searching your generations: api/generations.search_terms() and the
Generations tab's endpoints with a search, on the fixture library.

Every word must be in an image's prompt or negative prompt - as generated or
as typed - ignoring case; a quoted phrase is one word; % and _ are matched as
themselves. task:<id> keeps the images a task of the Queue made. The search
narrows a grouped level as an ungrouped one, and rating a batch rates only
what the search shows.
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

WORK = os.path.join(TESTS, 'work', 'generations_search')
opts = webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager import tile_reading                   # noqa: E402
from model_manager.api import generations as api         # noqa: E402
from model_manager.api import levels as levels_module    # noqa: E402
from model_manager.db.generations_ops import Scope       # noqa: E402
from model_manager.install import INSTALL_KEY            # noqa: E402
from model_manager.nsfw import PG                        # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
app = FastAPI()
api.register(app)
client = TestClient(app)


def record(typed, images, negative='', created='2026-10-05T12:00:00'):
    """A generation as typed, with images each (prompt, negative) as generated."""
    rows = [{'position': i, 'path': os.path.join(WORK, f'{typed[:12]}-{i}.png'), 'prompt': p, 'negative_prompt': n,
             'prompt_nsfw_level': PG} for i, (p, n) in enumerate(images)]
    return db.record_generation({'created_at': created, 'mode': 'txt2img', 'prompt': typed,
                                 'negative_prompt': negative, 'image_count': len(rows)}, rows, [[] for _ in rows])


lighthouse = record('a lighthouse at dusk', [('a lighthouse at dusk, Golden Hour', 'blurry'),
                                             ('a lighthouse at dusk, storm', 'blurry, 100% noise')])
fox = record('{red|white} fox in snow', [('red fox in snow', 'watermark'), ('white fox in snow', 'snake_case')],
             created='2026-10-05T12:05:00')
cat = record('a sleeping cat', [('a sleeping cat', '')], negative='lighthouse', created='2026-10-05T12:10:00')
task = db.add_task({'install': INSTALL_KEY, 'mode': 'txt2img', 'inputs': {'fixed': {}}})
db.link_task_generation(task, fox)


def found(search, **params):
    """The image ids the Generations tab shows, ungrouped, for a search."""
    answer = client.get('/model-manager/generations/browse',
                        params={'search': search, 'nsfw_images': 'all', **params}).json()
    assert answer['success'], answer
    return sorted(i['id'] for t in answer['tiles'] for i in t['images'])


def images_of(*generations):
    rows = db.generation_scope_rows(Scope(generations=list(generations)))
    return sorted(r['id'] for r in rows)


everything = images_of(lighthouse, fox, cat)

# ------------------------------------------------------------ the terms
def terms(text):
    """What a search asks for, as plain values: words, task, images, versions, models."""
    found = api.search_terms(text)
    return tuple(getattr(found, k, None) for k in ('words', 'task', 'images', 'versions', 'models'))


check('words, a quoted phrase as one, and a task',
      terms('lighthouse "at dusk" task:12')[:2], (['lighthouse', 'at dusk'], 12))
check('task: in any case', terms('TASK:3')[:2], ([], 3))
check("a prompt's own colon is a word", terms('(red:1.2) task:x')[:2], (['(red:1.2)', 'task:x'], None))
check('nothing, for an empty search', terms('   '), ([], None, [], [], []))
# The ids (#336).
check('image:, version: and model: take a list, in any case',
      terms('IMAGE:5,7 version:300 Model:11,12'), ([], None, [5, 7], [300], [11, 12]))
check('a key again adds to its list', terms('version:1 version:2,3')[3], [1, 2, 3])
check('a key without whole ids is a word', terms('image:abc version:1,,2 model: image:5')[:3],
      (['image:abc', 'version:1,,2', 'model:'], None, [5]))
check('task: takes one id: a list is a word', terms('task:1,2')[:2], (['task:1,2'], None))

# generation: (#241): the review of generations recorded twice shows its early
# copies and the generations kept beside them with it.
check('generation: takes a list, in the Generations tab',
      getattr(api.search_terms('generation:4,9 Generation:12'), 'generations', None), [4, 9, 12])
check('and is a word in the Civitai Images tab, as task: is',
      levels_module.search_terms('generation:4', tasks=False).words, ['generation:4'])

# ------------------------------------------------------------ searching
check('no search shows every image', found(''), everything)
check('generation: shows those generations whole',
      found(f'generation:{fox},{cat}'), sorted(images_of(fox) + images_of(cat)))
check('narrowed by the words beside it', found(f'generation:{fox},{cat} sleeping'), images_of(cat))
check('generation:abc is searched for as typed: no prompt holds it', found('generation:abc'), [])
check('a word in the prompt as generated', found('storm'), images_of(lighthouse)[1:])
check('ignoring case', found('golden HOUR'), images_of(lighthouse)[:1])
check('or as typed: a dynamic prompt\'s words', found('{red|white}'), images_of(fox))
check('a word in the negative prompt, as generated or typed',
      (found('watermark'), found('lighthouse')), (images_of(fox)[:1], images_of(lighthouse, cat)))
check('every word must be there', found('lighthouse storm'), images_of(lighthouse)[1:])
check('a quoted phrase as one', (found('"fox in snow"'), found('"snow fox"')), (images_of(fox), []))
check('% and _ are matched as themselves', (found('100%'), found('snake_case'), found('snake%case')),
      (images_of(lighthouse)[1:], images_of(fox)[1:], []))
check("task: keeps the images the task's run made", found(f'task:{task}'), images_of(fox))
check('and with words, those of them that match', found(f'task:{task} snake_case'), images_of(fox)[1:])
check('a task that made nothing finds nothing', found('task:999999'), [])

grouped = client.get('/model-manager/generations/browse', params={
    'search': 'lighthouse', 'group': 'prompt_written', 'nsfw_images': 'all'}).json()
check('a grouped level is narrowed too',
      sorted(t['group']['value'] for t in grouped['tiles']), ['a lighthouse at dusk', 'a sleeping cat'])
check('and counted as narrowed', grouped['state']['total'], 3)

# --------------------------------------------------------------- rating
answer = client.post('/model-manager/generations/rate', data={
    'level': '4', 'generation': str(lighthouse), 'search': 'storm', 'nsfw_images': 'all'}).json()
check('rating a batch rates only what the search shows', answer['rated'], 1)
levels = {r['id']: r['user_level'] for r in db.generation_scope_rows(Scope(generation=lighthouse))}
check('the image the search found', [levels[i] for i in images_of(lighthouse)], [None, 4])

# ------------------------------------------------------------ by id (#336)
# A model with two versions the library holds: one file each.
conn = db._get_connection()
version_file = dict(zip(facts['version_ids'], facts['linked_paths']))
model_of = dict(conn.execute('SELECT id, model_id FROM versions'))
by_model = {}
for version in facts['version_ids']:
    by_model.setdefault(model_of[version], []).append(version)
twin = next(vs for vs in by_model.values() if len(vs) >= 2)
CK, CK2 = twin[:2]
LORA, OTHER = [v for v in facts['version_ids'] if v not in twin][:2]


def made_with(typed, checkpoint, images, created):
    """A generation with a checkpoint, its images each (prompt, LoRA version or None)."""
    rows = [{'position': i, 'path': os.path.join(WORK, f'{typed[:12]}-{i}.png'), 'prompt': p, 'negative_prompt': '',
             'prompt_nsfw_level': PG,
             'loras': [{'name': 'x', 'path': version_file[lora]}] if lora else []} for i, (p, lora) in enumerate(images)]
    used = [[version_file[checkpoint]] + ([version_file[lora]] if lora else []) for _, lora in images]
    return db.record_generation({'created_at': created, 'mode': 'txt2img', 'prompt': typed, 'negative_prompt': '',
                                 'image_count': len(rows), 'checkpoint_path': version_file[checkpoint]}, rows, used)


barn = made_with('a red barn', CK, [('a red barn', LORA), ('a red barn, hay', None)], '2026-10-05T12:20:00')
mill = made_with('an old mill', CK2, [('an old mill', None)], '2026-10-05T12:30:00')
# Made with another model's checkpoint: no key below names it.
made_with('a stone bridge', OTHER, [('a stone bridge', None)], '2026-10-05T12:40:00')
check('image: those images, from any generation', found(f'image:{images_of(barn)[1]},{images_of(fox)[0]}'),
      sorted([images_of(barn)[1], images_of(fox)[0]]))
check('image: again adds; an id nothing has finds nothing',
      (found(f'image:{images_of(cat)[0]} image:{images_of(mill)[0]}'), found('image:99999999')),
      (sorted(images_of(cat) + images_of(mill)), []))
check("version: a LoRA's version finds the images that used it, not the batch",
      found(f'version:{LORA}'), images_of(barn)[:1])
check("version: a checkpoint's finds every image made with it", found(f'version:{CK}'), images_of(barn))
check('version: a list is any of them', found(f'version:{LORA},{CK2}'), sorted(images_of(barn)[:1] + images_of(mill)))
check('model: any version of the model', found(f'model:{model_of[CK]}'), sorted(images_of(barn) + images_of(mill)))
check('a key and a word: both', found(f'version:{CK} hay'), images_of(barn)[1:])
check('two keys: both', found(f'model:{model_of[CK]} version:{LORA}'), images_of(barn)[:1])
check('a version nothing used finds nothing', found('version:99999999'), [])
by_id = client.get('/model-manager/generations/browse', params={
    'search': f'model:{model_of[CK]}', 'group': 'prompt_written', 'nsfw_images': 'all'}).json()
check('a key narrows a grouped level: only the groups holding a match, each counting its matches',
      sorted((t['group']['value'], t['matching_count']) for t in by_id['tiles']),
      [('a red barn', 2), ('an old mill', 1)])

# A queued task of several checkpoints (#401): a search narrows its tile to
# the runs it finds, and narrows the task's own level with the task opened.
import generation_fixture                                # noqa: E402
tdb, gid = generation_fixture.several_library(os.path.join(WORK, 'several'), ROOT)
place = {g: i for i, g in enumerate(gid)}
two = api.browse_page(tdb, 'all', tasks=True, search=f'generation:{gid[0]},{gid[6]}')['tiles']
check('a search finding runs of two of task 100\'s three checkpoints: one tile of those two',
      [(t['kind'], t.get('task', {}).get('id'), sorted(place[g] for g in t.get('task', {}).get('generations', [])))
       for t in two], [('task', 100, [0, 6])])
one = api.browse_page(tdb, 'all', tasks=True, search=f'generation:{gid[0]}')['tiles']
check('finding one: a batch', [t['kind'] for t in one], ['generation'])
by_task = api.browse_page(tdb, 'all', tasks=True, search='task:103')['tiles']
check('task:103: its one tile', [(t['kind'], t.get('task', {}).get('id')) for t in by_task], [('task', 103)])
opened = api.browse_page(tdb, 'all', tasks=True, search='task:103', task=103)['tiles']
narrowed = api.browse_page(tdb, 'all', tasks=True, search='task:103 cat', task=103)['tiles']
check('task:103 with the task opened: its runs; and a word too: those its prompt holds',
      [sorted(place[t['generation']['id']] for t in opened), sorted(place[t['generation']['id']] for t in narrowed)],
      [[8, 11, 16, 18], [11]])

# How often a search reads the prompts (#434): each word is asked of each
# prompt once, though four of an image's checks read what it finds - and the
# view of tasks reads the images twice. One batch more for each word, holding
# the first none, one, two ... of them, so every check of every word is made.
LADDER = ['firstword', 'secondword', 'thirdword', 'fourthword', 'fifthword']


def ladder(to):
    for n in range(len(LADDER) + 1):
        text = ' '.join(LADDER[:n]) or 'none of them'
        to.record_generation({'created_at': '2026-10-06T12:00:00', 'mode': 'txt2img', 'prompt': f'typed {n}',
                              'negative_prompt': '', 'image_count': 1},
                             [{'position': 0, 'path': os.path.join(WORK, f'ladder-{n}.png'), 'prompt': text,
                               'negative_prompt': 'none', 'prompt_nsfw_level': PG}], [[]])
    return to._get_connection().execute('SELECT COUNT(*) FROM generation_prompts').fetchone()[0]


def likes(of, words, single_pass, tasks=False):
    """How many times LIKE runs in one read of a level, and the batches it finds."""
    scope = Scope(words=words, task_key=tasks)
    with fixtures.likes_counted(of) as count:
        with of.generation_scope_level(scope, 'run' if tasks else 'generation', None, 'all', single_pass) as level:
            units = len(level.units(0, 50))
    return count[0], units


for reading in (True, False):
    way = 'One pass' if reading else 'Classic'
    if reading:
        texts, task_texts = ladder(db), ladder(tdb)
    for n in (1, 3, 5):
        check(f'{way}, {n} words: each is asked of each prompt once', likes(db, LADDER[:n], reading),
              (n * texts, len(LADDER) + 1 - n))
        check(f'{way}, {n} words, in the view of tasks: the same', likes(tdb, LADDER[:n], reading, tasks=True),
              (n * task_texts, len(LADDER) + 1 - n))
    check(f'{way}, five words, the first found nowhere: the first four alone are asked, in the view of tasks too',
          [likes(db, ['zebra'] + LADDER[:4], reading), likes(tdb, ['zebra'] + LADDER[:4], reading, tasks=True)],
          [(4 * texts, 0), (4 * task_texts, 0)])
check('five words, the last, of the second scan, found nowhere; and all found',
      (found(' '.join(LADDER[:4]) + ' zebra'), len(found(' '.join(LADDER)))), ([], 1))

# A search against a plain match of the texts, wherever it is asked: inside a
# group, a batch, beside keys, in each NSFW mode, both ways of reading.
TEXTS = {row[0]: [t or '' for t in row[1:]] for row in db._get_connection().execute(
    'SELECT gi.id, a.text, b.text, c.text, d.text FROM generation_images gi JOIN generations g ON g.id = gi.generation_id '
    'LEFT JOIN generation_prompts a ON a.id = gi.prompt_id LEFT JOIN generation_prompts b ON b.id = gi.negative_id '
    'LEFT JOIN generation_prompts c ON c.id = g.prompt_id LEFT JOIN generation_prompts d ON d.id = g.negative_id')}


def matching(ids, words):
    return sorted(i for i in ids if all(any(w.lower() in t.lower() for t in TEXTS[i]) for w in words))


level_of = db._get_connection()
level_of.execute('UPDATE generation_images SET prompt_nsfw_level = 16 WHERE id % 3 = 0')
level_of.commit()
KEYS = f'model:{model_of[CK]} version:{CK}'
WHERE = [{}, {'generation': barn}, {'generation': lighthouse}]
for by in ('prompt', 'prompt_written'):
    tiles = client.get('/model-manager/generations/browse', params={'group': by, 'nsfw_images': 'all'}).json()['tiles']
    WHERE += [{'group': by, 'in_group': t['group']['id']} for t in tiles if t['kind'] == 'group'][:4]
check('a level, two batches and four groups of each prompt grouping to search in', len(WHERE), 11)


def direct(search, nsfw_images, **params):
    """As found, through the endpoint's own function: hundreds of requests, each
    an event loop's own sockets, can use up Windows' ports."""
    tiles = api.browse_page(db, nsfw_images, search=search, **params)['tiles']
    return sorted(i['id'] for t in tiles for i in t['images'])


wrong, hits = [], 0
for reading in (tile_reading.SINGLE_PASS, tile_reading.CLASSIC):
    setattr(opts, tile_reading.SETTING, reading)
    for nsfw in ('safe', 'all', 'nsfw'):
        for where in WHERE:
            for keys in ('', KEYS):
                params = dict(where, nsfw_images=nsfw, expand=True)
                held = direct(keys, **params)
                for words in (['a'], ['red', 'barn'], ['fox', 'watermark'], ['cat', 'lighthouse'], LADDER, ['zebra', 'a'], ['lighthouse', 'storm']):
                    got = direct((keys + ' ' + ' '.join(words)).strip(), **params)
                    hits += bool(got)
                    if got != matching(held, words):
                        wrong.append((reading, params, keys, words, got, matching(held, words)))
delattr(opts, tile_reading.SETTING)
check('a search finds what a plain match of the texts does, in every view - and finds something in 60 and more of them',
      (wrong, hits >= 60), ([], True))
tdb.close()

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
