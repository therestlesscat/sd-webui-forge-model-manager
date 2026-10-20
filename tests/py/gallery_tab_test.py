"""
The Civitai Images tab (#209): the Civitai images stored for the models in the
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
# The tab loads a part at a time as you scroll, not a setting (#230).
import model_manager.gallery as gallery_module        # noqa: E402
gallery_module.TILE_PART = 10
opts.model_manager_gallery_hide_nsfw = False
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))

# ------------------------------------------------------------ the images
# Three versions of the library, of two models or more; a few images each,
# every third explicit; one image stored under two of them; and images of a
# version with no file, which the library does not have.
with db._cursor() as cursor:
    for table in ('image_galleries', 'images', 'image_records', 'image_resources', 'image_prompts'):
        cursor.execute(f'DELETE FROM {table}')
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
check('and its card\'s sampler and schedule type, read there too (#302)',
      all('mm_sampler' in t['image'] and 'mm_scheduler' in t['image'] for t in tiles) and bool(tiles), True)
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
# A group is named by its id in a request: its key after a "v" (#283).
check('grouped by model: a tile per model, each group placed by the seed and itself',
      [t.get('group', {}).get('key') for t in groups], ['v%d' % m for m in by_rank(seed)])
inside = {}
for tile in groups:
    key = tile.get('group', {}).get('key')
    inside[key] = ids_of(every_page(group='model', in_group=str(key))[0])
check('inside a group, its images by their scores',
      inside, {'v%d' % m: sorted(ids, key=lambda i: (score(i, seed), i)) for m, ids in model_images.items()})
check('a group\'s tile shows its first four images, and counts them all',
      [([img['id'] for img in t['images']], t['matching_count']) for t in groups],
      [(inside[t['group']['key']][:4], len(inside[t['group']['key']])) for t in groups])

# ------------------------------------------------------------ what a page reads
# Picked by its keys, then only its rows read: the reading of a page's rows
# does not grow with the library. SQLite's steps counted, as the grid's
# query was (tests/AGENTS.md, "A new check has to fail on the old code").
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

# ------------------------------------------------------------ the ⋯ menu
# An image's checkpoints and LoRAs, asked for when ⋯ is pressed (#298): the
# tile says only whether it has a menu. Its own version is left out - the
# tile's Model button opens it - and so is any other kind of resource.
OWN, HELD, OTHER = versions[0], versions[1], versions[2]
UNHELD = 987654


def resource(kind, version, model=55, name='r'):
    return {'type': kind, 'modelVersionId': version, 'modelId': model, 'name': name, 'modelVersionName': 'v' + name}


rich = image(9001, 1)
rich['meta']['civitaiResources'] = [
    resource('lora', OWN, name='own'),
    resource('checkpoint', HELD, model_of[HELD], 'ckpt'),
    resource('textualinversion', OTHER, name='embedding'),
    resource('LORA', UNHELD, 56, 'unheld'),
    resource('lora', HELD, name='again'),
    {'type': 'lora', 'modelId': 57, 'name': 'no version'},
    resource('LoCon', OTHER, model_of[OTHER], 'locon'),
]
plain = image(9002, 1)
plain['meta']['civitaiResources'] = [resource('checkpoint', OWN, name='own'), resource('vae', HELD, name='vae')]
db.store_images(OWN, page=4, images=[rich, plain])


def menu(image_id, version_id):
    answer = client.get('/model-manager/gallery/menu', params={'image_id': image_id, 'version_id': version_id})
    return answer.json() if answer.status_code == 200 else {'status': answer.status_code}


from model_manager.api import gallery as gallery_api      # noqa: E402
keyed = gallery_api.image_tiles(db, [(9001, OWN), (9002, OWN), (stored[OWN][0], OWN),
                                     (stored[HELD][0], HELD), (stored[OTHER][0], OTHER)])
flags = {t['image']['id']: t.get('menu') for t in keyed}
check('a tile says whether it has a menu: one naming a checkpoint or LoRA besides its own version',
      (flags.get(9001), flags.get(9002), flags.get(stored[OWN][0])), (True, False, False))
send_file = {t['version']['id']: t['version']['file_path'] for t in keyed}
items = menu(9001, OWN).get('items') or []
check('pressed: each checkpoint and LoRA of the record, in its order, each version once, '
      'its own version and other kinds left out',
      [(i.get('role'), i.get('type'), i.get('version_id'), i.get('model_id'), i.get('name'), i.get('version_name'))
       for i in items],
      [('checkpoint', 'checkpoint', HELD, model_of[HELD], 'ckpt', 'vckpt'),
       ('lora', 'LORA', UNHELD, 56, 'unheld', 'vunheld'),
       ('lora', 'LoCon', OTHER, model_of[OTHER], 'locon', 'vlocon')])
check('each with the file the library holds, as Send takes it - none for a version it does not hold',
      [i.get('file_path') for i in items], [send_file.get(HELD), None, send_file.get(OTHER)])
check('the held files are there to take', all(send_file.get(v) for v in (HELD, OTHER)), True)
check('an image no longer stored: said so', menu(424242, OWN).get('success'), False)

# Hundreds of LoRAs in one image: asked of the library 500 ids at a time -
# the older SQLite takes 999 values a statement.
crowded = image(9003, 1)
crowded['meta']['civitaiResources'] = ([resource('lora', 300000 + i, name='l%d' % i) for i in range(1200)]
                                       + [resource('lora', HELD, name='held')])
db.store_images(OWN, page=5, images=[crowded])
asked = []
real_library_files = db.library_files
def counting_library_files(**kwargs):
    asked.append(len(kwargs.get('version_ids') or []))
    return real_library_files(**kwargs)
db.library_files = counting_library_files
try:
    items = menu(9003, OWN).get('items') or []
finally:
    db.library_files = real_library_files
check('1,201 LoRAs: every one answered, the held one with its file',
      (len(items), [i['file_path'] for i in items if i['version_id'] == HELD]), (1201, [send_file.get(HELD)]))
check('asked of the library at most 500 ids at a time', (bool(asked), max(asked or [0]) <= 500), (True, True))

# The choice of a version's file, split out for the menu, gives Send what it
# gave before: HEAD's _library_entries, frozen here.
from model_manager.model_dirs import held_here           # noqa: E402


def entries_before(versions_asked):
    chosen = {}
    for row in db.library_files(version_ids=list(versions_asked)):
        version_id, path = row.get('version_id'), row.get('file_path')
        if version_id is None or not path:
            continue
        if version_id not in chosen or (held_here(path) and not held_here(chosen[version_id])):
            chosen[version_id] = path
    return {version_id: db.get_version(path) or {'file_path': path} for version_id, path in chosen.items()}


# A version with a second file the other WebUI holds - in no folder this one
# loads from - listed after its own: the rule takes the one held here.
with db._cursor() as cursor:
    cursor.execute('SELECT * FROM files WHERE version_id = ? LIMIT 1', (HELD,))
    columns = [d[0] for d in cursor.description]
    row = dict(zip(columns, cursor.fetchone()))
    row['file_path'] = os.path.join(TESTS, 'work', 'gallery_tab_elsewhere', 'other_webui.safetensors')
    cursor.execute('INSERT INTO files (%s) VALUES (%s)' % (', '.join(row), ', '.join('?' * len(row))),
                   list(row.values()))
check('a version with a file held here and one elsewhere: the menu gives the one held here',
      [i['file_path'] for i in (menu(9001, OWN).get('items') or []) if i['version_id'] == HELD],
      [send_file.get(HELD)])
every_version = set(facts['version_ids']) | {UNHELD}
check('Send\'s file of each version is as it was', gallery_api._library_entries(db, every_version),
      entries_before(every_version))

# ------------------------------------------------------------ off
opts.model_manager_gallery_tab = False
check('off: its page and its seed refused', (client.get('/model-manager/gallery/browse').status_code,
      client.post('/model-manager/gallery/seed', data={}).status_code), (403, 403))
check('off: its menu refused', menu(9001, OWN).get('status'), 403)

if fails:
    print('FAIL ' + '\nFAIL '.join(fails))
    sys.exit(1)
print('ok')
