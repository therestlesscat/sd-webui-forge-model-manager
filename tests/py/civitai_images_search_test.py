"""
The Civitai Images tab, searched and grouped by what each image says (#283),
and each image stored once.

A search finds the images whose prompt or negative prompt holds each word -
a "quoted phrase" as one, `%` and `_` as typed - on every page, count and
group, one or two groupings deep. The tab groups by prompt (spacing tidied),
by LoRA combination and by local date, beside the gallery's model, base
model, type and size; each image is in exactly one group of each, and a
group's subgroups add up to it. An image is one record whatever galleries
show it: a fetch without prompts keeps the stored ones, a gallery replaced
or cleared takes only the images no other gallery shows, and a restamp
judges each image once and writes its level to every gallery row.

Through the HTTP endpoints and the database's own methods; what a level joins
is watched on this thread's connection (#434).
"""
import os
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime

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
from model_manager.api import gallery as gallery_api      # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.db.gallery_ops import Scope           # noqa: E402
from model_manager.db.images_ops import IMAGE_PROMPTS    # noqa: E402
from model_manager.civitai.prompt_filter import generation_ids_needing_lookup, keep_generation_data  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def attempt(label, fn, default=None):
    """What `fn` answers, or a failure by `label` and `default` where it raises."""
    try:
        return fn()
    except Exception as error:  # the code before #283 has none of this
        fails.append('%s\n   raised %s: %s' % (label, type(error).__name__, error))
        return default


db, facts = fixtures.build(os.path.join(TESTS, 'work', 'civitai_images_search'))
dbmod._db_instance = db
opts.model_manager_gallery_tab = True
import model_manager.gallery as gallery_module        # noqa: E402
gallery_module.TILE_PART = 50
opts.model_manager_gallery_hide_nsfw = False
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))

V0, V1, V2 = facts['version_ids'][:3]
for version in facts['version_ids']:
    db.clear_version_images(version)


def image(image_id, prompt=None, negative=None, loras=(), when='2026-01-02T12:00:00.000Z', size=(512, 768), level=1):
    meta = None
    if prompt is not None or negative is not None or loras:
        meta = {'civitaiResources': [{'type': 'LORA', 'modelVersionId': v, 'modelId': v // 10, 'name': f'Lora{v}',
                                      'modelVersionName': 'v1', 'weight': 0.8} for v in loras]}
        if prompt is not None:
            meta['prompt'] = prompt
        if negative is not None:
            meta['negativePrompt'] = negative
    return {'id': image_id, 'url': f'https://image.civitai.com/x/{image_id}.jpeg', 'width': size[0],
            'height': size[1], 'browsingLevel': level, 'createdAt': when, 'meta': meta}


IMAGES = {
    1001: image(1001, 'a red fox in snow', 'blurry', [501], '2026-01-02T12:00:00.000Z'),
    1002: image(1002, 'a red fox, sunset', 'lowres', [501, 502], '2026-01-02T13:00:00.000Z'),
    1003: image(1003, 'blue sky over hills', 'red', [], '2026-01-03T12:00:00.000Z', (1024, 1024)),
    1004: image(1004, '100% cotton_shirt', '', [502, 501], '2026-01-03T13:00:00.000Z', (1024, 1024), level=8),
    1005: image(1005, 'a red  fox in   snow', None, [501], '2026-01-04T00:30:00.000Z'),
    1006: image(1006, None, None, [], '2026-01-04T23:30:00.000Z'),
}
db.store_images(V0, 1, [IMAGES[i] for i in (1001, 1002, 1003)])
db.store_images(V1, 1, [IMAGES[i] for i in (1004, 1005, 1002)])
db.store_images(V2, 1, [IMAGES[1006]])
ALL = sorted(IMAGES)


def browse(**params):
    answer = client.get('/model-manager/gallery/browse', params=params)
    return answer.json() if answer.status_code == 200 else {'status': answer.status_code}


def level(**params):
    """Every tile of a level, every part of it."""
    tiles, page = [], 1
    while page < 20:
        data = browse(page=page, **params)
        tiles += data.get('tiles') or []
        if not data.get('more'):
            return tiles, data
        page += 1
    return tiles, {}


def found(**params):
    tiles, data = level(**params)
    return sorted(t['image']['id'] for t in tiles if t.get('kind') == 'image'), data


def local_day(when):
    return datetime.fromisoformat(when.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d')


# ------------------------------------------------------------ search
ids, data = found(search='fox')
check('a word: the images whose prompt holds it, and the banner counts them',
      (ids, data.get('state', {}).get('total')), ([1001, 1002, 1005], 3))
check('a word in a negative prompt alone finds the image too', found(search='red')[0], [1001, 1002, 1003, 1005])
check('two words: an image must hold each', found(search='red sunset')[0], [1002])
check('a "quoted phrase" is one word', found(search='"red fox"')[0], [1001, 1002])
check('% and _ are matched as typed', (found(search='100%')[0], found(search='cotton_shirt')[0],
                                       found(search='cotton%shirt')[0]), ([1004], [1004], []))
check('nothing found: no tiles, a total of 0', (found(search='zebra')[0], found(search='zebra')[1].get('state', {}).get('total')),
      ([], 0))

groups, data = level(group='model', search='fox')
groups = [g for g in groups if g.get('kind') == 'group']
check('a search while grouped: each group counts only what it found, a group with none is not drawn',
      sorted(g['group']['count'] for g in groups), sorted([2, 2]) if len(groups) == 2 else [3])
first = groups[0]['group']['key'] if groups else ''
subgroups, _ = level(group='model>day', in_group=str(first), search='fox')
subgroups = [g for g in subgroups if g.get('kind') == 'group']
check('and inside a group, grouped again: only what the search found',
      sum(g['group']['count'] for g in subgroups), groups[0]['group']['count'] if groups else -1)

# ------------------------------------------------------------ groupings
def grouping(by, **params):
    tiles, _ = level(group=by, **params)
    return {str(t['group']['key']): (t['group']['value'], t['group']['count']) for t in tiles if t.get('kind') == 'group'}


def members(by, key, **params):
    return found(group=by, in_group=str(key), **params)[0]


prompts = grouping('prompt')
check('by prompt: its spacing tidied, so "a red  fox in   snow" joins "a red fox in snow"',
      sorted((name, count) for name, count in prompts.values()),
      sorted([('a red fox in snow', 2), ('a red fox, sunset', 1), ('blue sky over hills', 1),
              ('100% cotton_shirt', 1), ('', 1)]))
loras = grouping('loras')
check('by LoRA combination: the same LoRAs in any order are one group, named by them; none is a group too',
      sorted(loras.values()), sorted([('Lora501 v1', 2), ('Lora501 v1, Lora502 v1', 2), ('', 2)]))
days = grouping('day')
expected = {}
for i, img in IMAGES.items():
    expected.setdefault(local_day(img['createdAt']), []).append(i)
# A group is asked for by its id: its key after a "v", so an empty key is a group too.
check('by day: each image on its local date, near midnight too', {k[1:]: c for k, (_, c) in days.items()},
      {k: len(v) for k, v in expected.items()})
check('a day opened: the images made on that local date', {k[1:]: members('day', k) for k in days},
      {k: sorted(v) for k, v in expected.items()})
check('a group with an empty key - no LoRAs - opens too', sorted(members('loras', 'v')), [1003, 1006])
for by in ('model', 'base_model', 'type', 'size', 'prompt', 'loras', 'day'):
    tiles = grouping(by)
    opened = sorted(i for k in tiles for i in members(by, k))
    check(f'by {by}: each image in exactly one group', opened, ALL)
for a, b in (('prompt', 'loras'), ('loras', 'day'), ('day', 'model'), ('model', 'prompt'), ('size', 'loras')):
    sums = {}
    for key, (_, count) in grouping(a).items():
        sub = grouping(f'{a}>{b}', in_group=key)
        sums[key] = (sum(c for _, c in sub.values()), count)
    check(f'two deep, {a} then {b}: each group\'s subgroups add up to it', all(s == c for s, c in sums.values()) and bool(sums))

# ------------------------------------------------------------ by id (#336)
# The LoRAs' model, 50 (501 // 10), is no model the library holds; each
# gallery's version's is.
GALLERY = {V0: [1001, 1002, 1003], V1: [1002, 1004, 1005], V2: [1006]}
model_of = dict(db._get_connection().execute('SELECT id, model_id FROM versions'))
check('image: those images; again adds; an id not stored finds nothing',
      (found(search='image:1001,1004')[0], found(search='image:1003 image:1006')[0], found(search='image:999')[0]),
      ([1001, 1004], [1003, 1006], []))
check("version: a LoRA's version finds the images whose resources name it", found(search='version:502')[0], [1002, 1004])
check('version: a gallery\'s version finds what its gallery shows, resources or not',
      (found(search=f'version:{V2}')[0], found(search=f'version:{V1}')[0]), (GALLERY[V2], GALLERY[V1]))
check('version: a list is any of them', found(search=f'version:502,{V2}')[0], [1002, 1004, 1006])
check('model: a model the library never synced, by its resources', found(search='model:50')[0], [1001, 1002, 1004, 1005])
check("model: a held model, by its versions' galleries", found(search=f'model:{model_of[V2]}')[0],
      sorted({i for v, shown in GALLERY.items() if model_of[v] == model_of[V2] for i in shown}))
check('a key and a word: both', found(search='version:501 snow')[0], [1001, 1005])
check('a key without whole ids is a word', found(search='image:abc')[0], [])
check('task: is a word here', found(search='task:1')[0], [])
grouping('prompt')
check('a key narrows a grouped level: only the groups holding a match, each counting its matches - '
      'the groups kept for the same grouping unsearched are not reused',
      sorted(grouping('prompt', search=f'version:{V2}').values()), [('', 1)])

# ------------------------------------------------------------ what a level joins (#434)
# On this thread's connection, made anew for each: a request runs on another,
# and Python 3.10 cannot take a watcher back from a connection.
BY = ('model', 'base_model', 'type', 'size', 'prompt', 'loras', 'day')
TABLES = {row[0] for row in db._get_connection().execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def asked(scope, grouping_by=None):
    """The tables SQLite is asked to read for a level - or, given a grouping, for
    its groups - and whether an index is made."""
    reads, indexes = set(), []

    def watch(action, first, second, *_):
        if action == sqlite3.SQLITE_READ and first in TABLES:
            reads.add(first)
        if action == sqlite3.SQLITE_CREATE_TEMP_INDEX:
            indexes.append(first)
        return sqlite3.SQLITE_OK

    with fixtures.own_connection(db) as connection:
        if grouping_by is None:
            connection.set_authorizer(watch)
        with db.gallery_level(1, scope) as read:
            if grouping_by is not None:
                connection.set_authorizer(watch)
                read.groups(grouping_by)
    return sorted(reads), bool(indexes)


def plan_of(scope):
    """The plan of the statement that fills a level."""
    statements = []
    with fixtures.own_connection(db) as connection:
        connection.set_trace_callback(statements.append)
        with db.gallery_level(1, scope):
            pass
        connection.set_trace_callback(None)
        fill = [s for s in statements if s.lstrip().startswith('CREATE TEMP TABLE')]
        return [row[3] for row in connection.execute('EXPLAIN QUERY PLAN ' + fill[0])] if len(fill) == 1 else fill


def prompts_looked_up(scope):
    """Whether each image's prompt is looked up for a level: a search reads the
    prompts besides, so that they are read says nothing."""
    return 'idx_image_prompts_lookup' in ' '.join(plan_of(scope))


def first_key(by):
    return gallery_api.group_key(by, list(grouping(by))[0])


ALWAYS = ['files', 'image_galleries', 'versions']
check('a level with no search reads the galleries, the library\'s files and its versions, and no more; no index is made',
      attempt('plain', lambda: asked(Scope())), (ALWAYS, False))
check('a search by word reads the images and the prompts besides', attempt('words', lambda: asked(Scope(words=['fox']))[0]),
      sorted(ALWAYS + ['images', 'image_prompts']))
check('a search by id reads what it names, and no image\'s row',
      attempt('ids', lambda: [asked(scope)[0] for scope in (Scope(images=[1001]), Scope(versions=[502]), Scope(models=[50]))]),
      [ALWAYS, sorted(ALWAYS + ['image_resources']), sorted(ALWAYS + ['image_resources'])])
check('no level looks each image\'s prompt up: not a plain one, a search, nor an opened prompt group',
      attempt('plans', lambda: [prompts_looked_up(scope) for scope in (
          Scope(), Scope(words=['fox', 'snow']), Scope(opened=[('prompt', first_key('prompt'))]))]), [False] * 3)
OPENED_READS = {'model': [], 'base_model': [], 'type': ['models'], 'size': ['images'], 'prompt': ['images', 'image_prompts'],
                'loras': ['image_resources'], 'day': ['images']}
GROUPS_READ = {'model': ['models', 'versions'], 'base_model': ['versions'], 'type': ['files', 'models', 'versions'],
               'size': ['images'], 'prompt': ['image_prompts', 'images'], 'loras': ['image_resources'], 'day': ['images']}
for by in BY:
    check(f'a {by} group opened: the level reads that besides',
          attempt(by, lambda: asked(Scope(opened=[(by, first_key(by))]))[0]), sorted(ALWAYS + OPENED_READS[by]))
    check(f'the groups by {by} read what they are worked out from', attempt(by, lambda: asked(Scope(), by)[0]),
          GROUPS_READ[by])

# Every grouping inside every other, with a word and without: a group's images
# are those of both its groups, and its subgroups add up to it.
# Through the endpoint's own function: hundreds of requests, each an event
# loop's own sockets, can use up Windows' ports.
def direct(**params):
    return gallery_api.browse_page(db, 1, 'all', 1, **params)['tiles']


found_fox = set(found(search='fox')[0])
member = {by: {key: set(members(by, key)) for key in grouping(by)} for by in BY}
for search, kept in (('', set(ALL)), ('fox', found_fox)):
    wrong = []
    for outer in BY:
        for inner in BY:
            if outer == inner:
                continue
            for key, held in member[outer].items():
                if not held & kept:
                    continue
                sub = {t['group']['key']: t['group']['count']
                       for t in direct(group=f'{outer}>{inner}', in_group=key, search=search)}
                want = {k: len(held & ids & kept) for k, ids in member[inner].items() if held & ids & kept}
                if sub != want:
                    wrong.append((outer, inner, key, sub, want))
                for sub_key in want:
                    got = [t['image']['id'] for t in direct(group=f'{outer}>{inner}', in_group=key, in_subgroup=sub_key,
                                                            search=search)]
                    if set(got) != held & member[inner][sub_key] & kept:
                        wrong.append((outer, inner, key, sub_key, got))
    check(f'every grouping inside every other, searching "{search}": the right groups, counts and images', wrong, [])

parts = []
gallery_module.TILE_PART = 4
for page in (1, 2, 3):
    data = browse(page=page)
    parts.append((len(data.get('tiles') or []), data.get('more')))
gallery_module.TILE_PART = 50
check('the last part of a level, and one past its end', parts, [(4, True), (2, False), (0, False)])

# An image only a version with no row of its own shows - a database fault.
raw = db._get_connection()
columns = ', '.join(row[1] for row in raw.execute('PRAGMA table_info(images)') if row[1] != 'id')
raw.execute(f'INSERT INTO images (id, {columns}) SELECT 7001, {columns} FROM images WHERE id = 1001')
raw.execute("INSERT INTO files (file_path, file_name, version_id) VALUES ('no_version.safetensors', 'no_version', 999999)")
raw.execute('INSERT INTO image_galleries (version_id, image_id, page, position, effective_nsfw_level) VALUES (999999, 7001, 1, 1, 1)')
raw.commit()
check('an image of a version with no row is neither shown nor counted', (found()[0], found()[1].get('state', {}).get('total')),
      (ALL, len(ALL)))
for statement in ('DELETE FROM images WHERE id = 7001', "DELETE FROM files WHERE version_id = 999999",
                  'DELETE FROM image_galleries WHERE version_id = 999999'):
    raw.execute(statement)
raw.commit()


# The store changed between a level and its groups, as a sync or a restamp in
# another thread, or the other WebUI, changes it: what was kept is not answered
# again.
def changed_between(by, change, nsfw='all'):
    """A grouping asked while `change` runs after its level is read; whether it
    then answers as it is worked out afresh, and whether the change told."""
    real = db.gallery_level

    @contextmanager
    def level_then_change(seed, scope):
        with real(seed, scope) as read:
            thread = threading.Thread(target=change)
            thread.start()
            thread.join()
            yield read

    def counts():
        page = gallery_api.browse_page(db, 1, nsfw, 1, group=by)
        return sorted((t['group']['value'], t['group']['count'], t['matching_count']) for t in page['tiles'])

    gallery_api._groups_kept.clear()
    db.gallery_level = level_then_change
    try:
        first = counts()
    finally:
        db.gallery_level = real
    again = counts()
    gallery_api._groups_kept.clear()
    afresh = counts()
    return again == afresh, first != afresh


def judged_explicit():
    with db._cursor() as cursor:
        cursor.execute('UPDATE image_galleries SET effective_nsfw_level = 16 WHERE image_id IN (1001, 1002)')


check('images judged again while a grouping was read: asked again, its groups are as worked out afresh',
      changed_between('day', judged_explicit, 'nsfw'), (True, True))
with db._cursor() as cursor:
    cursor.execute('UPDATE image_galleries SET effective_nsfw_level = 1 WHERE image_id IN (1001, 1002)')
check('images removed while a grouping was read: the same',
      changed_between('loras', lambda: db.replace_first_page(V1, [IMAGES[1004], IMAGES[1002]], None)), (True, True))
check('images added while a grouping was read: the same',
      changed_between('loras', lambda: db.replace_first_page(V1, [IMAGES[1004], IMAGES[1005], IMAGES[1002]], None)), (True, True))

# An image Civitai gave no size and no date: in a group of each with no key.
db.store_images(V2, 2, [dict(image(7500, 'a red fox'), width=None, height=None, createdAt=None)])
check('no size and no date: a group of each, opened, and with a word',
      [[sorted(members(by, 'v')), sorted(members(by, 'v', search='fox')), members(by, 'v', search='snow')]
       for by in ('size', 'day')], [[[7500], [7500], []]] * 2)
db.replace_first_page(V2, [IMAGES[1006]], None)

# ------------------------------------------------------------ how often a search reads the prompts (#434)
check('a first word found nowhere, then two that are: nothing found', found(search='zebra fox snow')[0], [])
check('five words, the last, of the second scan, found nowhere; and all found',
      (found(search='a red fox in zebra')[0], found(search='a red fox in snow')[0]), ([], [1001, 1005]))
# One image more for each word: holding the first none, one, two ... of them,
# so every word is asked of some image's prompt and negative prompt.
LADDER = ['firstword', 'secondword', 'thirdword', 'fourthword', 'fifthword']
db.store_images(V2, 2, [image(8000 + n, ' '.join(LADDER[:n]) or 'none of them') for n in range(len(LADDER) + 1)])
texts = db._get_connection().execute('SELECT COUNT(*) FROM image_prompts').fetchone()[0]


def likes(words):
    with fixtures.likes_counted(db) as count:
        with db.gallery_level(1, Scope(words=words)) as read:
            total = read.counts()['total']
    return count[0], total


for n in (1, 3, 5):
    check(f'{n} words: each is asked of each prompt once, and the images found are those of every word',
          likes(LADDER[:n]), (n * texts, len(LADDER) + 1 - n))
check('five words, the first found nowhere: the first four alone are asked', likes(['zebra'] + LADDER[:4]), (4 * texts, 0))


# The original Forge's SQLite takes AS MATERIALIZED and does not act on it here.
def untold(placeholders, scans=getattr(IMAGE_PROMPTS, 'scans', None)):
    ctes, ids = scans(placeholders)
    return [c.replace('AS MATERIALIZED', 'AS') for c in ctes], ids


IMAGE_PROMPTS.scans = untold
check('three words, the scan not told to be made once: made once all the same', likes(LADDER[:3]),
      (3 * texts, len(LADDER) - 2))
del IMAGE_PROMPTS.scans
check('a scan reads the prompts\' table, not the index of their texts',
      [step for step in plan_of(Scope(words=LADDER)) if 'image_prompts' in step], ['SCAN image_prompts'] * 2)
db.replace_first_page(V2, [IMAGES[1006]], None)

# ------------------------------------------------------------ one record per image
def record(image_id):
    rows = db.stored_records([image_id])
    return rows[0] if rows else {}


def prompts_in(version):
    return {i['id']: (i.get('meta') or {}).get('prompt') for i in db.get_images(version)}


# A sync of gallery V2 without a prompt lookup: 1001, stored with its prompt
# for V0, comes in it too, as Civitai's list gives it - no prompts.
fresh = [dict(IMAGES[1006], meta=None), dict(IMAGES[1001], meta=None)]
carried = attempt('the stored records of a sync\'s images, whatever gallery holds them',
                  lambda: keep_generation_data(fresh, db.stored_records([i['id'] for i in fresh])), 0)
check('a sync carries the prompt over from another gallery\'s image, so no lookup asks for it',
      (carried >= 1, 1001 in generation_ids_needing_lookup(fresh)), (True, False))
attempt('replacing gallery V2', lambda: db.replace_first_page(V2, [dict(IMAGES[1001], meta=None)], None))
check('a fetch without prompts keeps the one record\'s: both galleries show it',
      (attempt('V0', lambda: prompts_in(V0).get(1001)), attempt('V2', lambda: prompts_in(V2).get(1001))),
      ('a red fox in snow', 'a red fox in snow'))
db.store_images(V2, 2, [dict(IMAGES[1003], meta=None)])
check('Load more without the lookup keeps the stored prompt too',
      attempt('1003', lambda: (record(1003).get('meta') or {}).get('prompt')), 'blue sky over hills')

db.store_images(V1, 1, [dict(IMAGES[1002], width=640)])
check('a fetch in one gallery is the record for every gallery showing the image',
      attempt('1002', lambda: [i.get('width') for i in db.get_images(V0) if i['id'] == 1002]), [640])

# Gallery V1 again, without 1005: shown by no other gallery, it goes with
# its record and resources; its spelling of the prompt goes, the tidy one
# 1001 names stays; 1002, which V0 shows, stays.
db.replace_first_page(V1, [IMAGES[1004]], None)
conn = db._get_connection()
gone = attempt('the clean-up', lambda: [conn.execute(sql, (1005,)).fetchone()[0] for sql in (
    'SELECT COUNT(*) FROM images WHERE id = ?', 'SELECT COUNT(*) FROM image_records WHERE image_id = ?',
    'SELECT COUNT(*) FROM image_resources WHERE image_id = ?')], [])
check('a gallery replaced: an image no other gallery shows goes, row, record and resources', gone, [0, 0, 0])
check('its prompt goes with it; the tidy prompt another image names stays',
      attempt('the prompts', lambda: [conn.execute('SELECT COUNT(*) FROM image_prompts WHERE text = ?', (t,)).fetchone()[0]
                                      for t in ('a red  fox in   snow', 'a red fox in snow')], []), [0, 1])
check('an image another gallery shows stays', attempt('1002', lambda: record(1002).get('id')), 1002)
db.clear_version_images(V2)
check('a gallery cleared: its images no other gallery shows go',
      attempt('1006', lambda: conn.execute('SELECT COUNT(*) FROM image_records WHERE image_id = 1006').fetchone()[0]), 0)

# A restamp judges each image once, and writes its level to every gallery row.
db.store_images(V1, 2, [IMAGES[1002]])
attempt('levels set wrong', lambda: conn.execute('UPDATE image_galleries SET effective_nsfw_level = 99 WHERE image_id = 1002'))
conn.commit()
changed, read, _ = db.restamp_image_levels()
records = attempt('records', lambda: conn.execute('SELECT COUNT(*) FROM image_records').fetchone()[0], -1)
check('a restamp reads each image once, not each gallery row', read, records)
check('and writes the image\'s level to both its gallery rows',
      attempt('levels', lambda: sorted(r[0] for r in conn.execute(
          'SELECT effective_nsfw_level FROM image_galleries WHERE image_id = 1002')), []), [1, 1])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
