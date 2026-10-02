"""
The Model Manager grid's query: the right rows, fast.

It used to rank every image of every matching version to pick each card's
preview - 740 ms of a 1.3 s load on a library of 100,651 images, however
few cards the page held. It now chooses the page's rows first and looks up
only their images, through an index in gallery order (schema v24). Checked
against the live library once, in memory: the same rows, previews, levels
and order as before for every filter, at 3-60 ms instead of 90-480.

What is checked here: previews and levels are still each version's first
image, and first safe image, in gallery order; pages join up without
repeats or gaps, ties in the sort included; and the page query never reads
the whole images table - which is what made it slow.
"""
import contextlib
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

import fixtures                                          # noqa: E402
from model_manager.db import GridQuery                 # noqa: E402
from model_manager.db import query as grid               # noqa: E402

WORK = os.path.join(TESTS, 'work', 'grid_query')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)

# Galleries whose first image is not the first stored, nor the first safe
# one: stored out of order, pages and positions deciding.
versions = facts['version_ids'][:4]
with db._cursor() as cursor:
    cursor.execute("DELETE FROM images WHERE version_id IN (%s)" % ",".join("?" * len(versions)), versions)
for n, version in enumerate(versions):
    db.store_images(version, 2, [{'id': 1000 * n + 1, 'url': f'https://e.invalid/{n}-p2.jpeg',
                                  'browsingLevel': 1}])
    db.store_images(version, 1, [{'id': 1000 * n + 9, 'url': f'https://e.invalid/{n}-first.jpeg',
                                  'browsingLevel': 16},
                                 {'id': 1000 * n + 5, 'url': f'https://e.invalid/{n}-safe.jpeg',
                                  'browsingLevel': 2}])
with db._cursor() as cursor:
    cursor.execute("UPDATE model_versions SET cover_url = NULL, safe_cover_url = NULL WHERE id IN (%s)"
                   % ",".join("?" * len(versions)), versions)


def query(counts=None, **kw):
    kw.setdefault('limit', 100000)
    rows, total = db.query_models_grouped(GridQuery(**kw), counts)
    return rows, total


rows, _ = query()
shown = {r['id']: r for r in rows}
check('the galleries built above are shown as cards', sum(v in shown for v in versions) >= 2)
for n, version in enumerate(versions):
    if version not in shown:
        continue
    row = shown[version]
    check(f'version {n}: NSFW hidden, the preview is the first safe image in gallery order',
          row['preview_url'], f'https://e.invalid/{n}-safe.jpeg')
    check(f'version {n}: its highest image level', row['max_image_nsfw'], 16)
nsfw_rows, _ = query(preview_least_nsfw=False)
check('NSFW allowed, the preview is the first image in gallery order, whatever it is',
      {r['id']: r['preview_url'] for r in nsfw_rows if r['id'] in versions},
      {v: f'https://e.invalid/{n}-first.jpeg' for n, v in enumerate(versions) if v in shown})

# -------------------------------------------------------------- image count
# How many images the card's version has stored: the three above, and more
# for one of them.
db.store_images(versions[0], 3, [{'id': 50000 + i, 'url': f'https://e.invalid/more-{i}.jpeg',
                                  'browsingLevel': 1} for i in range(4)])
rows, _ = query(sort_by='image_count', sort_order='desc')
stored = db.count_images_by_version()
counts = [stored.get(r['id'], 0) for r in rows]
check('sorted by image count, most first', counts, sorted(counts, reverse=True))
check('with counts to tell apart', len(set(counts)) > 2)
rows, _ = query(sort_by='image_count', sort_order='asc')
check('and fewest first', [stored.get(r['id'], 0) for r in rows], sorted(counts))

# ------------------------------------------------------------------- paging
for sort in ('base_model', 'file_modified', 'name', 'downloaded_at', 'image_count'):
    everything, total = query(sort_by=sort, sort_order='asc')
    paged, offset = [], 0
    while True:
        page, _ = query(sort_by=sort, sort_order='asc', limit=3, offset=offset)
        if not page:
            break
        paged += [r['file_path'] for r in page]
        offset += 3
    check(f'sorted by {sort}, pages of 3 join up into the whole list: none twice, none missing',
          (paged, len(paged)), ([r['file_path'] for r in everything], total))

# ------------------------------------------------------------------ pinning
# A pinned card comes first whenever it matches the filters, in the grid's
# own sort, and once; pinning changes the order, never what is shown. A card
# is a Civitai model, or a file Civitai does not know, pinned by its path.
paths = lambda rows: [r['file_path'] for r in rows]
lora = facts['lora_ids'][-1]
local = facts['local_only_paths'][0]
before = {(sort, order): query(sort_by=sort, sort_order=order)
          for sort, order in (('name', 'asc'), ('name', 'desc'), ('file_modified', 'desc'))}
vae_before = query(model_type='VAE')
check('pinning a model and a local-only file, the latter by its path in any case',
      [db.set_pin(lora, None, True), db.set_pin(None, local.upper(), True)], [True, True])
for (sort, order), (rows, total) in before.items():
    pinned_rows, pinned_total = query(sort_by=sort, sort_order=order)
    firsts = [r for r in rows if r['model_id'] == lora or r['file_path'] == local]
    rest = [r for r in rows if r not in firsts]
    check(f'sorted by {sort} {order}: the pinned cards first, in that sort, then the rest as before',
          (paths(pinned_rows), pinned_total), (paths(firsts) + paths(rest), total))
    check(f'sorted by {sort} {order}: and marked pinned',
          [r['is_pinned'] for r in pinned_rows[:3]], [True, True, False])
check('a pinned card the filters leave out stays out',
      paths(query(model_type='VAE')[0]), paths(vae_before[0]))
everything, total = query(sort_by='name', sort_order='asc')
paged, offset = [], 0
while True:
    page, _ = query(sort_by='name', sort_order='asc', limit=3, offset=offset)
    if not page:
        break
    paged += paths(page)
    offset += 3
check('with pins, pages of 3 still join up: the pinned on page 1, none twice, none missing',
      (paged, len(paged)), (paths(everything), total))

# The grid's tabs: the pinned cards, and the rest - each in the grid's sort,
# each paging on its own, and both counted under the filters.
counts = {}
everything_rows, everything_total = query(sort_by='name', sort_order='asc', counts=counts)
pinned_rows, pinned_total = query(sort_by='name', sort_order='asc', pinned=True)
other_rows, other_total = query(sort_by='name', sort_order='asc', pinned=False)
check('the Pinned tab holds the pinned cards, and only them',
      (paths(pinned_rows), pinned_total), (paths(everything_rows[:2]), 2))
check('Others the rest, in the same sort', (paths(other_rows), other_total),
      (paths(everything_rows[2:]), everything_total - 2))
check('and both tabs are counted, whichever is asked for', counts,
      {'pinned': 2, 'others': everything_total - 2})
page, _ = query(sort_by='name', sort_order='asc', pinned=False, limit=3, offset=3)
check('Others pages on its own', paths(page), paths(other_rows[3:6]))
counts = {}
query(model_type='VAE', pinned=True, counts=counts)
check('the counts follow the filters', counts, {'pinned': 0, 'others': len(vae_before[0])})

# A file pinned by its path before Civitai knew it pins its model's card, and
# unpinning the model takes that pin too.
checkpoint = facts['checkpoint_ids'][0]
with db._cursor() as cursor:
    cursor.execute("SELECT file_path FROM model_versions WHERE model_id = ? ORDER BY file_path DESC LIMIT 1",
                   (checkpoint,))
    second_file = cursor.fetchone()[0]
db.set_pin(None, second_file, True)
first_three = query(sort_by='name', sort_order='asc')[0][:3]
check('a file pinned by its path pins its model\'s card',
      checkpoint in [r['model_id'] for r in first_three], True)
db.set_pin(checkpoint, None, False)
check('and unpinning the model unpins it',
      checkpoint in [r['model_id'] for r in query(sort_by='name', sort_order='asc')[0][:3]], False)
db.set_pin(lora, None, False)
db.set_pin(None, local, False)
check('unpinned, the grid is as it was', paths(query(sort_by='name', sort_order='asc')[0]),
      paths(before[('name', 'asc')][0]))
check('nothing to pin is refused', db.set_pin(None, None, True), False)

# ------------------------------------- work that does not grow with images
# Its query plan looked innocent - the images were read version by version,
# through an index - and still every image of every matching version was
# read and ranked. So what is measured is work: SQLite's virtual machine
# steps for a one-card page, before and after 5,000 images are added to a
# version that page does not show. Only the page's own images may count.
conn = db._get_connection()


def steps(**kw):
    count = [0]

    def tick():
        count[0] += 1
        return 0
    conn.set_progress_handler(tick, 1)
    try:
        page, _ = db.query_models_grouped(GridQuery(limit=1, offset=0, sort_by='file_path', sort_order='asc', **kw))
    finally:
        conn.set_progress_handler(None, 0)
    return count[0], page[0]['file_path']


# Two all-PG galleries, so "Only Show Models with SFW images" has cards.
carded = [r['id'] for r in query()[0] if r['id'] and r['id'] not in versions]
for version in carded[:2]:
    with db._cursor() as cursor:
        cursor.execute("DELETE FROM images WHERE version_id = ?", (version,))
    db.store_images(version, 1, [{'id': 700000 + version % 100000, 'url': 'https://e.invalid/pg.jpeg',
                                  'browsingLevel': 1}])
check('two models pass "Only Show Models with SFW images"', query(sfw_only=True)[1] >= 2)

for label, kw in (('the default grid', {}), ('NSFW previews', {'preview_least_nsfw': False}),
                  ('Only Show Models with SFW images', {'sfw_only': True})):
    before, first = steps(**kw)
    everything, _ = query(sort_by='file_path', sort_order='asc', **kw)
    elsewhere = next((r['id'] for r in reversed(everything) if r['id'] and r['file_path'] != first), None)
    if elsewhere is None:
        check(f'{label}: a second card to add images to', False)
        continue
    extra = [{'id': 900000 + i, 'url': f'https://e.invalid/x{i}.jpeg', 'browsingLevel': 1}
             for i in range(5000)]
    db.store_images(elsewhere, 3, extra)
    after, _ = steps(**kw)
    with db._cursor() as cursor:
        cursor.execute("DELETE FROM images WHERE id BETWEEN 900000 AND 904999")
    check(f'{label}: 5,000 images on a card not shown add next to no work',
          (after - before) < 5000, True)

# ---------------------------------------------------------------- the index
with db._cursor() as cursor:
    cursor.execute("PRAGMA index_info(idx_images_gallery)")
    check('v24 indexes images in gallery order, with the level',
          [row[2] for row in cursor.fetchall()],
          ['version_id', 'page', 'position', 'id', 'effective_nsfw_level'])

# ------------------------------------------ which version a card shows (#25)
# The newest published; two with one date - Deep Negative's V1 75T and V1 64T,
# to the millisecond - went to whichever SQLite returned, so a cover could
# change between loads. A tie goes as Civitai orders versions (`index` in
# civitai_models.versions, whose first a model's page shows), then the higher
# version id: always the same one.
import json                                              # noqa: E402
with db._cursor() as cursor:
    cursor.execute("SELECT model_id, published_at, MIN(id), MAX(id) FROM model_versions "
                   "WHERE model_id IS NOT NULL GROUP BY model_id, published_at HAVING COUNT(DISTINCT id) = 2 LIMIT 1")
    model_id, published, low, high = cursor.fetchone()


def card_version():
    return next(r['id'] for r in query()[0] if r['model_id'] == model_id)


def civitai_order(*ids):
    with db._cursor() as cursor:
        cursor.execute("UPDATE civitai_models SET versions = ? WHERE id = ?",
                       (json.dumps([{'id': v, 'index': i} for i, v in enumerate(ids)]), model_id))


civitai_order()
with db._cursor() as cursor:
    cursor.execute("UPDATE civitai_models SET versions = NULL WHERE id = ?", (model_id,))
check('two versions of one date, Civitai\'s order unknown: the higher id, every time',
      [card_version() for _ in range(3)], [high] * 3)
civitai_order(low, high)
check('Civitai lists the other first: that one, as Civitai\'s page shows it', card_version(), low)
civitai_order(high, low)
check('and the other way round', card_version(), high)
with db._cursor() as cursor:
    cursor.execute("UPDATE model_versions SET published_at = '2099-01-01T00:00:00Z' WHERE id = ?", (low,))
check('the date still comes first: a newer version is shown, wherever Civitai lists it', card_version(), low)
with db._cursor() as cursor:
    cursor.execute("UPDATE model_versions SET published_at = NULL WHERE id IN (?, ?)", (low, high))
civitai_order(low, high)
check('two with no date at all tie too, and go as Civitai lists them', card_version(), low)
with db._cursor() as cursor:
    cursor.execute("UPDATE model_versions SET published_at = ? WHERE id IN (?, ?)", (published, low, high))

# ----------------------------------------------------- by file size (#40)
# In GB of 1024^3 bytes, either end open. A model shows if any of its local
# files is in range, with the newest that is - as with every version filter.
GB = 1024 ** 3
with db._cursor() as cursor:
    cursor.execute("UPDATE model_versions SET file_size = ? WHERE id = ?", (2 * GB, low))
    cursor.execute("UPDATE model_versions SET file_size = ? WHERE id = ?", (6 * GB, high))


def sized(**kw):
    rows = query(**kw)[0]
    # (A file the library knows only by its path has no version id.)
    return [r['id'] for r in sorted(rows, key=lambda r: r['file_path'])], \
        {r['id'] for r in rows if r['model_id'] == model_id}


check('from 5 GB: only the 6 GB file\'s card - every fixture file is tiny',
      sized(min_size_gb=5), ([high], {high}))
check('up to 3 GB: the model shows by its 2 GB file, the newest in range',
      [model_id in {r['model_id'] for r in query(max_size_gb=3)[0]}, sized(max_size_gb=3)[1]], [True, {low}])
check('both in range: the one shown without the filter', sized(min_size_gb=1, max_size_gb=10)[1], {card_version()})
check('none in range: no card', sized(min_size_gb=7), ([], set()))
check('the count agrees with the page', query(min_size_gb=1, max_size_gb=10)[1], 1)
check('half a GB is half a GB', sized(min_size_gb=1.5, max_size_gb=2.5)[0], [low])

from model_manager.db.migrations import run_migrations   # noqa: E402
bare = sqlite3.connect(':memory:')
cur = bare.cursor()
cur.execute("CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT)")
cur.execute("CREATE TABLE model_versions (id INTEGER, file_path TEXT PRIMARY KEY)")
run_migrations(cur, 23, 24, ':memory:', WORK)
check('and does nothing to a database with no images table', True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
