"""
The Model Manager card's image, for each NSFW choice.

NSFW allowed: the version's cover - the first image its creator attached
(the showcase), which is what Civitai shows for it.

NSFW hidden: a safe image, safe meaning PG or PG-13 as everywhere else here.
The cover if it is one; else the first safe image after it in the showcase;
else the first safe image of the version's gallery, in Civitai's order;
else none.

A showcase is only complete from /models/{id}, or /models?ids= with
nsfw=true. by-hash keeps PG only, and so may a .civitai.info: its first
image is still safe, but it cannot say which image is the cover.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.civitai import CivitaiClient          # noqa: E402
from model_manager.hashing import HashResult             # noqa: E402
from model_manager.nsfw import showcase_is_complete, version_covers   # noqa: E402
from model_manager.scan_service import ScanService       # noqa: E402
from model_manager.sync_service import SyncService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'cover')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def shot(name, level):
    return {'url': 'https://example.invalid/%s.jpeg' % name, 'nsfwLevel': level}


# A showcase as Civitai sends it in full: an R cover, then PG-13, then PG.
FULL = [shot('r-cover', 4), shot('pg13', 2), shot('pg-first', 1), shot('pg-second', 1)]
STRIPPED = [shot('pg-first', 1), shot('pg-second', 1)]     # the same, without nsfw=true
U = 'https://example.invalid/%s.jpeg'

# ------------------------------------------------------------------ the rule
check('from a full showcase: the cover, and the first PG or PG-13 image',
      version_covers(FULL, complete=True), (U % 'r-cover', U % 'pg13'))
check('a cover that is PG-13 is safe, so it is both',
      version_covers([shot('c', 2), shot('p', 1)], complete=True), (U % 'c', U % 'c'))
check('with nothing PG or PG-13, the safe cover is known to be none',
      version_covers([shot('r', 4), shot('x', 8)], complete=True), (U % 'r', ''))
check('an unrated image is not known to be safe',
      version_covers([{'url': U % 'unrated'}, shot('p', 1)], complete=True)[1], U % 'p')
check('a stripped showcase: its first image is safe, but the cover is unknown',
      version_covers(STRIPPED, complete=False), (None, U % 'pg-first'))
check('a stripped showcase with nothing left says nothing at all',
      version_covers([], complete=False), (None, None))
check('no showcase at all says nothing', version_covers(None, complete=True), (None, None))
check('an empty full showcase has neither', version_covers([], complete=True), ('', ''))
check('a showcase with a non-PG image is provably unstripped', showcase_is_complete(FULL))
check('one that is all PG might have been stripped', showcase_is_complete(STRIPPED), False)

# ------------------------------------------------------------ the card preview
db, facts = fixtures.build(WORK)
dbmod._db_instance = db
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))


def card(model_id, nsfw_allowed):
    body = client.get('/model-manager/models', params={
        'page_size': 100, 'preview_least_nsfw': 'false' if nsfw_allowed else 'true'}).json()
    return next(m for m in body['models'] if m.get('model_id') == model_id)


def shown_version(model_id):
    return card(model_id, False)['id']


def set_covers(model_id, cover, safe_cover):
    with db._cursor() as cursor:
        cursor.execute("UPDATE model_versions SET cover_url = ?, safe_cover_url = ? WHERE id = ?",
                       (cover, safe_cover, shown_version(model_id)))


def set_gallery(model_id, *levels):
    """The shown version's gallery, in Civitai's order, as g0, g1, ... ."""
    version = shown_version(model_id)
    db.clear_version_images(version)
    db.store_images(version, page=1, images=[
        {'id': version * 1000 + n, 'url': U % ('g%d' % n), 'browsingLevel': level}
        for n, level in enumerate(levels)])


m = facts['checkpoint_ids'][2]
set_gallery(m, 8, 2, 1)
set_covers(m, U % 'r-cover', U % 'pg13')
check('NSFW hidden: the first safe showcase image', card(m, False)['preview_url'], U % 'pg13')
check('NSFW allowed: the cover itself', card(m, True)['preview_url'], U % 'r-cover')

set_covers(m, U % 'safe-cover', U % 'safe-cover')
check('a safe cover is what both show', (card(m, False)['preview_url'], card(m, True)['preview_url']),
      (U % 'safe-cover', U % 'safe-cover'))

# The models this came from: a showcase all R and above, and a gallery that
# has safe images. The card used to go blank.
set_covers(m, U % 'r-cover', '')
check('with no safe showcase image, NSFW hidden takes the first safe gallery image, '
      'in Civitai\'s order', card(m, False)['preview_url'], U % 'g1')
check('while NSFW allowed still shows the cover', card(m, True)['preview_url'], U % 'r-cover')

set_gallery(m, 8, 16)
check('and with nothing safe in the gallery either, no image',
      card(m, False)['preview_url'] in (None, ''))

set_gallery(m, 8, 2, 1)
set_covers(m, None, None)
check('covers not known yet: the gallery - its first safe image with NSFW hidden',
      card(m, False)['preview_url'], U % 'g1')
check('and its first image with NSFW allowed', card(m, True)['preview_url'], U % 'g0')

set_covers(m, None, U % 'from-sidecar')
check('with only a safe cover known, NSFW allowed shows that rather than guess',
      card(m, True)['preview_url'], U % 'from-sidecar')

# ------------------------------------------------------------------- the sync
def covers_of(path):
    """What is stored, read from the row itself."""
    with db._cursor() as cursor:
        cursor.execute("SELECT cover_url, safe_cover_url FROM model_versions WHERE file_path = ?",
                       (path,))
        return tuple(cursor.fetchone())


path = facts['linked_paths'][6]
row = db.get_version(path)
full_model = {'id': row['model_id'], 'name': 'M', 'type': 'Checkpoint',
              'modelVersions': [{'id': row['id'], 'name': 'v', 'images': FULL}]}
sync = SyncService(client=None)
sync._update_database(path, full_model, HashResult.from_stored({}))
row = db.get_version(path)
check('a sync from a full model payload stores both covers',
      covers_of(path), (U % 'r-cover', U % 'pg13'))

by_hash = {'id': row['id'], 'modelId': row['model_id'], 'name': 'v',
           'images': [shot('pg-new', 1)]}
sync._update_database(path, by_hash, HashResult.from_stored({}))
check('a by-hash answer updates the safe cover but leaves the real one alone',
      covers_of(path), (U % 'r-cover', U % 'pg-new'))

# -------------------------------------------------------------------- the scan
scan = ScanService()
for showcase, want, label in (
        (FULL, (U % 'r-cover', U % 'pg13'), 'a sidecar with non-PG images gives both covers'),
        (STRIPPED, (None, U % 'pg-first'), 'an all-PG sidecar may be stripped: the safe cover only')):
    version_data = {'file_path': path, 'file_name': os.path.basename(path),
                    'file_extension': '.safetensors'}
    scan._extract_civitai_metadata(
        {'id': 1, 'modelVersions': [{'id': 9, 'images': showcase}]}, version_data, path)
    check(label, (version_data.get('cover_url'), version_data.get('safe_cover_url')), want)

# ------------------------------------------------------------- migration v21
import sqlite3                                            # noqa: E402
from model_manager.db.migrations import run_migrations    # noqa: E402
path20 = os.path.join(WORK, 'v20.db')
if os.path.exists(path20):
    os.remove(path20)
conn = sqlite3.connect(path20)
cur = conn.cursor()
cur.execute("CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT)")
cur.execute("CREATE TABLE model_versions (id INTEGER, file_path TEXT PRIMARY KEY, "
            "cover_url TEXT, pg_cover_url TEXT)")
cur.executemany("INSERT INTO model_versions VALUES (?, ?, ?, ?)",
                [(1, 'a', 'c1', 'pg1'), (2, 'b', 'c2', ''), (3, 'c', None, None)])
run_migrations(cur, 20, dbmod.SCHEMA_VERSION, path20, WORK)
check('v21 renames the column to what it now holds',
      [row[1] for row in cur.execute("PRAGMA table_info(model_versions)")][-1], 'safe_cover_url')
check('keeping stored first-PG images, which are safe, and clearing "no PG image", '
      'which is not "no safe image"',
      cur.execute("SELECT id, safe_cover_url FROM model_versions ORDER BY id").fetchall(),
      [(1, 'pg1'), (2, None), (3, None)])
run_migrations(cur, 20, dbmod.SCHEMA_VERSION, path20, WORK)
check('and can run twice', [row[1] for row in cur.execute(
      "PRAGMA table_info(model_versions)")].count('safe_cover_url'), 1)
conn.close()

# --------------------------------------------------- the bulk fetch asks for all
asked = []
civitai = CivitaiClient(api_key='k')
civitai._request = lambda method, endpoint, params=None: asked.append(params) or {'items': []}
civitai.get_models_by_ids([1, 2])
check('the bulk metadata fetch asks for the full showcase', asked[0].get('nsfw'), 'true')

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
