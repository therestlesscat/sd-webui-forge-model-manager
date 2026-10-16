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

Through the HTTP endpoints and the database's own methods, so that on the
code before #283 each check fails by name rather than the suite stopping.
"""
import os
import sys
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
from model_manager.api import setup_api                  # noqa: E402
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
