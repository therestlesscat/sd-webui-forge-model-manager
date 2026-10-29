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
webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
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
                        params={'search': search, 'hide_nsfw_images': 'false', **params}).json()
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
    'search': 'lighthouse', 'group': 'prompt_written', 'hide_nsfw_images': 'false'}).json()
check('a grouped level is narrowed too',
      sorted(t['group']['value'] for t in grouped['tiles']), ['a lighthouse at dusk', 'a sleeping cat'])
check('and counted as narrowed', grouped['state']['total'], 3)

# --------------------------------------------------------------- rating
answer = client.post('/model-manager/generations/rate', data={
    'level': '4', 'generation': str(lighthouse), 'search': 'storm', 'hide_nsfw_images': 'false'}).json()
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
    'search': f'model:{model_of[CK]}', 'group': 'prompt_written', 'hide_nsfw_images': 'false'}).json()
check('a key narrows a grouped level: only the groups holding a match, each counting its matches',
      sorted((t['group']['value'], t['matching_count']) for t in by_id['tiles']),
      [('a red barn', 2), ('an old mill', 1)])

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
