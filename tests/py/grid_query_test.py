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


def query(**kw):
    kw.setdefault('limit', 100000)
    rows, total = db.query_models_grouped(**kw)
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

# ------------------------------------------------------------------- paging
for sort in ('base_model', 'file_modified', 'name', 'downloaded_at'):
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
        page, _ = db.query_models_grouped(limit=1, offset=0, sort_by='file_path', sort_order='asc', **kw)
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

from model_manager.db.migrations import run_migrations   # noqa: E402
bare = sqlite3.connect(':memory:')
cur = bare.cursor()
cur.execute("CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT)")
cur.execute("CREATE TABLE model_versions (id INTEGER, file_path TEXT PRIMARY KEY)")
run_migrations(cur, 23, 24, ':memory:', WORK)
check('and does nothing to a database with no images table', True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
