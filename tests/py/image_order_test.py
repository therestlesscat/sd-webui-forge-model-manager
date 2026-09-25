"""
A version's images, in the order Civitai gave them.

Civitai returns a version's images in its own ranking - not by date, not by
id. The Model Manager stored them keyed on the image id and read them back
ORDER BY id, so its gallery showed a model's images oldest-first while the
Civitai Browser, which keeps the order it is given, showed Civitai's. The
"first 20" each tab judges a model by disagreed with it.

The order is now kept as `position` (schema v19). Rows stored before that
have none and keep their id order until their version is synced again.
"""
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

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.db.migrations import run_migrations   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'image_order')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))


def image(image_id, level=1):
    return {'id': image_id, 'url': 'https://example.invalid/%d.jpeg' % image_id,
            'browsingLevel': level, 'meta': {'prompt': 'a prompt long enough', 'steps': 20,
                                              'sampler': 'Euler', 'cfgScale': 7}}


def ids(version_id, **kw):
    return [i['id'] for i in db.get_images(version_id, **kw)]


version = facts['version_ids'][5]

# ------------------------------------------------------ Civitai's order, kept
# As Civitai ranks them: nothing to do with their ids.
db.clear_version_images(version)
db.store_images(version, page=1, images=[image(n) for n in (30, 10, 50, 20)])
check('a gallery comes back in the order Civitai gave it, not by id',
      ids(version), [30, 10, 50, 20])
check('one page asked for on its own, too', ids(version, page=1), [30, 10, 50, 20])

db.store_images(version, page=2, images=[image(n) for n in (5, 40)])
check('a page loaded later follows the one before it, in its own order',
      ids(version), [30, 10, 50, 20, 5, 40])

# ------------------------------------- rows stored before positions were kept
with db._cursor() as cursor:
    cursor.execute("UPDATE images SET position = NULL WHERE version_id = ?", (version,))
check('rows stored before v19 have no position, and keep sorting by id',
      ids(version), [10, 20, 30, 50, 5, 40])

# --------------------------------------------------------------- the migration
path = os.path.join(WORK, 'v18.db')
if os.path.exists(path):
    os.remove(path)
conn = sqlite3.connect(path)
cur = conn.cursor()
cur.execute("""CREATE TABLE images (id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL,
               page INTEGER NOT NULL, url TEXT, width INTEGER, height INTEGER,
               effective_nsfw_level INTEGER DEFAULT 64, created_at TEXT, data TEXT NOT NULL)""")
cur.execute("CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT)")
# Later migrations run too - run_migrations applies every step past the
# starting version - and they need the versions table a real v18 has.
cur.execute("CREATE TABLE model_versions (id INTEGER, file_path TEXT PRIMARY KEY)")
cur.execute("INSERT INTO images (id, version_id, page, data) VALUES (1, 1, 1, '{}')")
run_migrations(cur, 18, dbmod.SCHEMA_VERSION, path, WORK)
columns = [row[1] for row in cur.execute("PRAGMA table_info(images)")]
check('a v18 database gains the position column', 'position' in columns)
check('keeping the rows it had, with no position yet',
      cur.execute("SELECT id, position FROM images").fetchall(), [(1, None)])
run_migrations(cur, 18, dbmod.SCHEMA_VERSION, path, WORK)
check('and the migration can run twice', [row[1] for row in cur.execute(
      "PRAGMA table_info(images)")].count('position'), 1)
check('recording the new version', cur.execute(
      "SELECT value FROM schema_info WHERE key = 'version'").fetchone(),
      (str(dbmod.SCHEMA_VERSION),))
conn.close()

# ------------------------------- "Only Show Models with SFW images" judges Civitai's first 20
# An X-rated image with the lowest id, but 25th in Civitai's order: by id it
# would be first, and would rule the model out.
shown = next(m for m in client.get('/model-manager/models', params={'page_size': 100}).json()['models']
             if m.get('model_id') == facts['checkpoint_ids'][4])['id']
db.clear_version_images(shown)
db.store_images(shown, page=1, images=[image(1000 + n) for n in range(24)] + [image(1, level=8)])
kept = {m.get('model_id') for m in client.get(
    '/model-manager/models', params={'page_size': 100, 'sfw_only': 'true'}).json()['models']}
check('the SFW check looks at the first 20 in Civitai\'s order, where the X-rated image is 25th',
      facts['checkpoint_ids'][4] in kept)

db.clear_version_images(shown)
db.store_images(shown, page=1, images=[image(1, level=8)] + [image(1000 + n) for n in range(24)])
kept = {m.get('model_id') for m in client.get(
    '/model-manager/models', params={'page_size': 100, 'sfw_only': 'true'}).json()['models']}
check('and rules the model out when Civitai puts it first', facts['checkpoint_ids'][4] in kept, False)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
