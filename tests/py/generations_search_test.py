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
    rows = db.generation_gallery_images(None)
    return sorted(r['id'] for r in rows if r['generation_id'] in generations)


everything = images_of(lighthouse, fox, cat)

# ------------------------------------------------------------ the terms
check('words, a quoted phrase as one, and a task',
      api.search_terms('lighthouse "at dusk" task:12'), (['lighthouse', 'at dusk'], 12))
check('task: in any case', api.search_terms('TASK:3'), ([], 3))
check("a prompt's own colon is a word", api.search_terms('(red:1.2) task:x'), (['(red:1.2)', 'task:x'], None))
check('nothing, for an empty search', api.search_terms('   '), ([], None))

# ------------------------------------------------------------ searching
check('no search shows every image', found(''), everything)
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
levels = {r['id']: r['user_level'] for r in db.generation_gallery_images(None) if r['generation_id'] == lighthouse}
check('the image the search found', [levels[i] for i in images_of(lighthouse)], [None, 4])

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
