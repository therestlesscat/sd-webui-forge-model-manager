"""
Expand generations (#252): the Generations tab's browse route with `expand`,
on the fixture library.

With it, a level that would list generations lists their images, a tile
each, newest first: the top, a group opened, a section's group opened, a
search. A level of groups, and a batch opened, are as they were. The NSFW
switch and the parts work on images as they do on generations.
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

WORK = os.path.join(TESTS, 'work', 'generations_expand')
opts = webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.api import generations as api         # noqa: E402
from model_manager.db.generations_ops import Scope       # noqa: E402
import model_manager.gallery as gallery_module        # noqa: E402
from model_manager.install import INSTALL_KEY            # noqa: E402
from model_manager.nsfw import PG, X                     # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
app = FastAPI()
api.register(app)
client = TestClient(app)


def record(typed, prompts, created, level=PG):
    """A generation as typed, with an image per prompt as generated."""
    rows = [{'position': i, 'path': os.path.join(WORK, f'{typed[:12]}-{created[11:16]}-{i}.png'), 'prompt': p,
             'negative_prompt': '', 'prompt_nsfw_level': level} for i, p in enumerate(prompts)]
    return db.record_generation({'created_at': created, 'mode': 'txt2img', 'prompt': typed, 'negative_prompt': '',
                                 'image_count': len(rows)}, rows, [[] for _ in rows])


# Two days; batches of three, one and two images; one prompt typed twice.
lighthouse = record('a lighthouse at dusk', ['a lighthouse, golden hour', 'a lighthouse, storm', 'a lighthouse, fog'],
                    '2026-10-04T10:00:00')
cat = record('a sleeping cat', ['a sleeping cat'], '2026-10-05T09:00:00')
again = record('a lighthouse at dusk', ['a lighthouse, night', 'a lighthouse, rain'], '2026-10-05T11:00:00')
task = db.add_task({'install': INSTALL_KEY, 'mode': 'txt2img', 'inputs': {'fixed': {}}})
db.link_task_generation(task, again)


def ids(*generations):
    """The image ids of these generations, newest first, as the tab orders them."""
    return [r['id'] for r in db.generation_scope_rows(Scope(generations=list(generations)))]


def browse(**params):
    answer = client.get('/model-manager/generations/browse', params={'hide_nsfw_images': 'false', **params}).json()
    assert answer['success'], answer
    return answer


def shape(answer):
    """Each tile as (kind, its image ids)."""
    return [(t['kind'], [i['id'] for i in t['images']]) for t in answer['tiles']]


def kinds(answer):
    return sorted({t['kind'] for t in answer['tiles']})


everything = sorted(ids(lighthouse, cat, again))
newest_first = [i for g in (again, cat, lighthouse) for i in ids(g)]

# ------------------------------------------------------------- the top level
top = browse(expand='true')
check('expanded, the top is a tile per image, each its one image, newest first',
      shape(top), [('image', [i]) for i in newest_first])
check('as many tiles as images', len(top['tiles']), 6)
check('not expanded, a tile per generation, as before',
      (kinds(browse()), len(browse()['tiles']), kinds(browse(expand='false'))), (['generation'], 3, ['generation']))

# -------------------------------------------------------------- a grouping
plain_groups = browse(group='prompt_written')
expanded_groups = browse(group='prompt_written', expand='true')
check('grouped, the groups are as they were',
      [(t['kind'], t['group']['value'], t['matching_count']) for t in expanded_groups['tiles']],
      [(t['kind'], t['group']['value'], t['matching_count']) for t in plain_groups['tiles']])
dusk = next(t['group']['id'] for t in plain_groups['tiles'] if t['group']['value'] == 'a lighthouse at dusk')
check('a group opened, not expanded: its generations',
      kinds(browse(group='prompt_written', in_group=dusk)), ['generation'])
check('expanded: its images, a tile each, newest first',
      shape(browse(group='prompt_written', in_group=dusk, expand='true')),
      [('image', [i]) for i in ids(again) + ids(lighthouse)])

# ------------------------------------------------------------ grouped twice
chain = 'day>prompt_written'
sections = browse(group=chain, expand='true')
check('grouped twice, the top stays groups in sections',
      [(t['kind'], t['section']['value'], t['group']['value']) for t in sections['tiles']],
      [(t['kind'], t['section']['value'], t['group']['value']) for t in browse(group=chain)['tiles']])
day = next(t['section']['id'] for t in sections['tiles'] if t['group']['value'] == 'a sleeping cat')
check('a section opened stays groups', kinds(browse(group=chain, in_group=day, expand='true')), ['group'])
sub = next(t['group']['id'] for t in browse(group=chain, in_group=day)['tiles']
           if t['group']['value'] == 'a lighthouse at dusk')
check("a section's group opened, expanded: its images",
      shape(browse(group=chain, in_group=day, in_subgroup=sub, expand='true')),
      [('image', [i]) for i in ids(again)])
check('not expanded: its generations', kinds(browse(group=chain, in_group=day, in_subgroup=sub)), ['generation'])

# ------------------------------------------------------------ a batch opened
check('a batch opened shows its images, expanded or not',
      shape(browse(generation=lighthouse, expand='true')), shape(browse(generation=lighthouse)))

# ---------------------------------------------------------------- NSFW
explicit = record('a red dress', ['a red dress, explicit'], '2026-10-06T08:00:00', level=X)
hidden = client.get('/model-manager/generations/browse', params={'hide_nsfw_images': 'true', 'expand': 'true'}).json()
check('NSFW hidden, expanded: the explicit image is no tile, and the banner counts the tiles shown',
      (ids(explicit)[0] in [i for _, imgs in shape(hidden) for i in imgs], len(hidden['tiles']),
       hidden['state']['filtered']), (False, 6, 6))

# --------------------------------------------------------------- a search
check('a search, expanded: the matching images, a tile each',
      shape(browse(search='storm', expand='true')), [('image', [ids(lighthouse)[1]])])
check('task:, expanded: the images its run made',
      shape(browse(search=f'task:{task}', expand='true')), [('image', [i]) for i in ids(again)])

# ----------------------------------------------------------------- parts
# The tab loads a part at a time as you scroll, not a setting (#230).
gallery_module.TILE_PART = 3
parts = [browse(expand='true', page=n) for n in (1, 2, 3)]
check('in parts of TILE_PART, more until the last',
      [(len(p['tiles']), p['more']) for p in parts], [(3, True), (3, True), (1, False)])
seen = [i for p in parts for _, imgs in shape(p) for i in imgs]
check('every image once across the parts', (sorted(seen), len(seen)), (sorted(everything + ids(explicit)), 7))

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
