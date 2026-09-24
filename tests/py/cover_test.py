"""
The card preview: the same image in both tabs, for the same NSFW choice.

A Civitai search card shows a version's cover - the first image its creator
attached (the showcase). With NSFW not allowed, Civitai leaves every image
but PG out of the showcase, so the card shows the first PG image instead, or
none. Checked against the live API on the 34 most downloaded checkpoints
with a PG image: the first PG image, all 34 times.

The Model Manager picked from the community gallery instead, by rating and
date, so one model had two previews. It now keeps both covers per version
and shows the one for the NSFW choice made; only a version whose covers are
not known yet falls back to the gallery.

A showcase is only complete from /models/{id}, or /models?ids= with
nsfw=true. by-hash is always stripped, so it can give the PG cover but not
the real one - and nor can a .civitai.info that might have been stripped.
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


# A showcase as Civitai sends it in full: R cover, then PG-13, then PG.
FULL = [shot('r-cover', 4), shot('pg13', 2), shot('pg-first', 1), shot('pg-second', 1)]
STRIPPED = [shot('pg-first', 1), shot('pg-second', 1)]     # the same, without nsfw=true

# ------------------------------------------------------------------ the rule
check('from a full showcase: the cover, and the first PG image',
      version_covers(FULL, complete=True),
      ('https://example.invalid/r-cover.jpeg', 'https://example.invalid/pg-first.jpeg'))
check('PG-13 is not PG: Civitai drops it too, and so does the PG cover',
      version_covers([shot('pg13', 2), shot('pg', 1)], complete=True)[1],
      'https://example.invalid/pg.jpeg')
check('with no PG image, the PG cover is known to be none',
      version_covers([shot('r', 4)], complete=True), ('https://example.invalid/r.jpeg', ''))
check('a stripped showcase still gives the PG cover, but cannot say what the cover is',
      version_covers(STRIPPED, complete=False), (None, 'https://example.invalid/pg-first.jpeg'))
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


def set_covers(model_id, cover, pg_cover):
    shown = card(model_id, False)['id']
    with db._cursor() as cursor:
        cursor.execute("UPDATE model_versions SET cover_url = ?, pg_cover_url = ? WHERE id = ?",
                       (cover, pg_cover, shown))


m = facts['checkpoint_ids'][2]
set_covers(m, 'https://example.invalid/r-cover.jpeg', 'https://example.invalid/pg-first.jpeg')
check('NSFW not allowed: the card is the first PG image, as in the Civitai Browser',
      card(m, False)['preview_url'], 'https://example.invalid/pg-first.jpeg')
check('NSFW allowed: the card is the cover itself',
      card(m, True)['preview_url'], 'https://example.invalid/r-cover.jpeg')

set_covers(m, 'https://example.invalid/r-cover.jpeg', '')
check('with no PG image and NSFW not allowed, no image - as the Civitai Browser shows none',
      card(m, False)['preview_url'], '')
check('while NSFW allowed still shows the cover', card(m, True)['preview_url'],
      'https://example.invalid/r-cover.jpeg')

set_covers(m, None, 'https://example.invalid/pg-first.jpeg')
check('with only the PG cover known, NSFW allowed shows that rather than guess',
      card(m, True)['preview_url'], 'https://example.invalid/pg-first.jpeg')

set_covers(m, None, None)
check('with neither known, the card falls back to a pick from the gallery',
      card(m, False)['preview_url'].startswith('https://example.invalid/i/'))

# ------------------------------------------------------------------- the sync
def covers_of(path):
    """What is stored, read from the row itself."""
    with db._cursor() as cursor:
        cursor.execute("SELECT cover_url, pg_cover_url FROM model_versions WHERE file_path = ?",
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
      covers_of(path),
      ('https://example.invalid/r-cover.jpeg', 'https://example.invalid/pg-first.jpeg'))

by_hash = {'id': row['id'], 'modelId': row['model_id'], 'name': 'v',
           'images': [shot('pg-new', 1)]}
sync._update_database(path, by_hash, HashResult.from_stored({}))
check('a by-hash answer updates the PG cover but leaves the real one alone',
      covers_of(path),
      ('https://example.invalid/r-cover.jpeg', 'https://example.invalid/pg-new.jpeg'))

# -------------------------------------------------------------------- the scan
scan = ScanService()
for showcase, want, label in (
        (FULL, ('https://example.invalid/r-cover.jpeg', 'https://example.invalid/pg-first.jpeg'),
         'a sidecar with non-PG images gives both covers'),
        (STRIPPED, (None, 'https://example.invalid/pg-first.jpeg'),
         'an all-PG sidecar may be stripped: the PG cover only')):
    version_data = {'file_path': path, 'file_name': os.path.basename(path),
                    'file_extension': '.safetensors'}
    scan._extract_civitai_metadata(
        {'id': 1, 'modelVersions': [{'id': 9, 'images': showcase}]}, version_data, path)
    check(label, (version_data.get('cover_url'), version_data.get('pg_cover_url')), want)

# --------------------------------------------------- the bulk fetch asks for all
asked = []
civitai = CivitaiClient(api_key='k')
civitai._request = lambda method, endpoint, params=None: asked.append(params) or {'items': []}
civitai.get_models_by_ids([1, 2])
check('the bulk metadata fetch asks for the full showcase', asked[0].get('nsfw'), 'true')

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
