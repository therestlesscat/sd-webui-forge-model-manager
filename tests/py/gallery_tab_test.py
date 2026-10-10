"""
The Gallery tab (#209): the Civitai images stored for the models in the
library, in an order a sorting seed picks.

The seed is made the first time it is asked for, and kept: the same seed, the
same order; another seed, another order of the same images. An image stored
under two versions is shown once. Grouped, each group has a place of its own
from the seed - placed by its lowest-scoring image, the biggest groups came
first for almost every seed - and its images follow their scores inside it.
A page is picked by its keys, then only its rows are read.

Through the HTTP endpoints, so that on the code before the tab every check
fails rather than the suite stopping at an import.
"""
import hashlib
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
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(os.path.join(TESTS, 'work', 'gallery_tab'))
dbmod._db_instance = db
opts.model_manager_gallery_tab = True
opts.model_manager_gallery_page_size = 10
opts.model_manager_gallery_hide_nsfw = False
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))

# ------------------------------------------------------------ the images
# Three versions of the library, of two models or more; a few images each,
# every third explicit; one image stored under two of them; and images of a
# version with no file, which the library does not have.
with db._cursor() as cursor:
    cursor.execute('DELETE FROM images')
    versions = facts['version_ids'][:3]
    cursor.execute('SELECT id, model_id FROM versions WHERE id IN (%s)' % ','.join('?' * len(versions)), versions)
    model_of = dict(cursor.fetchall())


def image(image_id, level):
    return {'id': image_id, 'url': 'https://image.civitai.com/x/%d.jpeg' % image_id, 'width': 512, 'height': 768,
            'browsingLevel': level, 'meta': {'prompt': 'a cat %d' % image_id, 'Model': 'm'}}


stored = {}
for index, version in enumerate(versions):
    ids = list(range(1000 * (index + 1), 1000 * (index + 1) + (12, 8, 5)[index]))
    db.store_images(version, page=1, images=[image(i, 8 if i % 3 == 0 else 1) for i in ids])
    stored[version] = ids
# Under two versions of two different models: inside the other model's group
# it must not show again - gathered from a group's versions alone, it did.
SHARED = 777
TWO = next((a, b) for a in versions for b in versions if a < b and model_of[a] != model_of[b])
db.store_images(TWO[1], page=2, images=[image(SHARED, 1)])
db.store_images(TWO[0], page=2, images=[image(SHARED, 1)])
db.store_images(987654, page=1, images=[image(5000 + i, 1) for i in range(4)])
library = sorted({i for ids in stored.values() for i in ids} | {SHARED})
explicit = [i for i in library if i % 3 == 0 and i != SHARED]


def score(image_id, seed):
    return (((image_id | seed) - (image_id & seed)) * 2654435761) % 4294967296


def browse(**params):
    answer = client.get('/model-manager/gallery/browse', params=params)
    return answer.json() if answer.status_code == 200 else {'status': answer.status_code}


def every_page(**params):
    """Every part of a level, in order, as the tab scrolls through them."""
    tiles, page = [], 1
    while page < 50:
        data = browse(page=page, **params)
        tiles += data.get('tiles') or []
        if not data.get('more'):
            return tiles, data
        page += 1
    return tiles, {}


ids_of = lambda tiles: [t['image']['id'] for t in tiles if t.get('kind') == 'image']

# ------------------------------------------------------------ the seed
check('no seed before the tab asks', db.get_info('gallery_seed'), None)
first = browse(page=1)
seed = first.get('seed')
check('the first page makes a seed, from 1 to 2,147,483,647, and keeps it',
      (isinstance(seed, int) and 1 <= seed <= 2 ** 31 - 1, db.get_info('gallery_seed')), (True, str(seed)))
# No seed - the code before the tab - each check below fails, rather than the suite stopping here.
seed = seed if isinstance(seed, int) else 0
check('the next page uses it', browse(page=1).get('seed'), seed)

# ------------------------------------------------------------ the order
tiles, last = every_page()
order = ids_of(tiles)
check('every image of the library, each once, in the seed\'s order, page after page',
      order, sorted(library, key=lambda i: (score(i, seed), i)))
check('the last page says there is no more', last.get('more'), False)
check('the same seed, the same order', ids_of(every_page()[0]), order)
check('an image of a version with no file is not shown', [i for i in order if i >= 5000], [])
shared = [t for t in tiles if t.get('image', {}).get('id') == SHARED]
check('an image stored under two versions shows once, under the lower version',
      [t['version']['id'] for t in shared], [TWO[0]])
check('every image carries its level, judged on the server',
      all('mm_level' in t['image'] for t in tiles) and bool(tiles), True)
check('and what Send needs: its model, and its version\'s file',
      all(t['model']['id'] == model_of[t['version']['id']] and t['version']['file_path'] for t in tiles)
      and bool(tiles), True)
check('the banner counts every image, and the explicit ones',
      {k: first.get('state', {}).get(k) for k in ('total', 'nsfw_count', 'hidden_nsfw')},
      {'total': len(library), 'nsfw_count': len(explicit), 'hidden_nsfw': 0})

# ------------------------------------------------------------ another seed
answer = client.post('/model-manager/gallery/seed', data={'seed': str(seed + 1)})
check('a seed typed is kept', (answer.json().get('seed'), db.get_info('gallery_seed')),
      (seed + 1, str(seed + 1)))
other = ids_of(every_page()[0])
check('another seed: the same images', sorted(other), library)
check('in another order', other != order and bool(other), True)
answer = client.post('/model-manager/gallery/seed', data={})
fresh = answer.json().get('seed')
check('New seed: another, kept', (isinstance(fresh, int) and 1 <= fresh <= 2 ** 31 - 1,
                                  db.get_info('gallery_seed') == str(fresh)), (True, True))
client.post('/model-manager/gallery/seed', data={'seed': str(seed)})

# ------------------------------------------------------------ NSFW hidden
hidden, data = every_page(hide_nsfw_images='true')
check('NSFW hidden: no explicit image on any page', [i for i in ids_of(hidden) if i in explicit], [])
check('and every other image still there', sorted(ids_of(hidden)), sorted(set(library) - set(explicit)))
check('what it hides is counted in the banner', data.get('state', {}).get('hidden_nsfw'), len(explicit))

# ------------------------------------------------------------ grouped
model_images = {}
for version, model in model_of.items():
    model_images.setdefault(model, set()).update(stored[version])
model_images.setdefault(model_of[TWO[0]], set()).add(SHARED)
want_models = sorted(set(model_of.values()))
rank = lambda key, s: hashlib.blake2b(f"{s}:model:{key}".encode(), digest_size=8).digest()
# A seed under which a group placed by its own score and one placed by its
# lowest-scoring image come out in different orders: so the check below
# tells them apart, whatever seed the run began with (#209).
by_rank = lambda s: sorted(want_models, key=lambda k: (rank(k, s), str(k)))
by_lowest = lambda s: sorted(want_models, key=lambda k: min(score(i, s) for i in model_images[k]))
seed = next(s for s in range(1, 10000) if by_rank(s) != by_lowest(s))
client.post('/model-manager/gallery/seed', data={'seed': str(seed)})
groups, data = every_page(group='model')
check('grouped by model: a tile per model, each group placed by the seed and itself',
      [t.get('group', {}).get('key') for t in groups], by_rank(seed))
inside = {}
for tile in groups:
    key = tile.get('group', {}).get('key')
    inside[key] = ids_of(every_page(group='model', in_group=str(key))[0])
check('inside a group, its images by their scores',
      inside, {m: sorted(ids, key=lambda i: (score(i, seed), i)) for m, ids in model_images.items()})
check('a group\'s tile shows its first four images, and counts them all',
      [([img['id'] for img in t['images']], t['matching_count']) for t in groups],
      [(inside[t['group']['key']][:4], len(inside[t['group']['key']])) for t in groups])

# ------------------------------------------------------------ what a page reads
# Picked by its keys, then only its rows read: the reading of a page's rows
# does not grow with the library. SQLite's steps counted, as the grid's
# query was (AGENTS.md).
def steps(fn):
    with db._cursor() as cursor:
        connection = cursor.connection
    count = [0]
    def tick():
        count[0] += 1
    connection.set_progress_handler(tick, 1)
    try:
        fn()
    finally:
        connection.set_progress_handler(None, 1)
    return count[0]


page_keys = [(t['image']['id'], t['version']['id']) for t in tiles[:10]]
read = getattr(db, 'gallery_images', None)
small = steps(lambda: read(page_keys)) if read else -1
db.store_images(versions[2], page=3, images=[image(20000 + i, 1) for i in range(2000)])
large = steps(lambda: read(page_keys)) if read else -1
check('a page\'s rows read the same with 2,000 more images stored', (small > 0, large <= small * 1.5), (True, True))

# ------------------------------------------------------------ off
opts.model_manager_gallery_tab = False
check('off: its page and its seed refused', (client.get('/model-manager/gallery/browse').status_code,
      client.post('/model-manager/gallery/seed', data={}).status_code), (403, 403))

if fails:
    print('FAIL ' + '\nFAIL '.join(fails))
    sys.exit(1)
print('ok')
