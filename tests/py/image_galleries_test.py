"""
An image belongs to every gallery that shows it.

A Civitai image appears in the gallery of every resource it used - a
checkpoint's, each LoRA's, the upscaler's. The images table was keyed on the
image id alone, so storing a gallery took each shared image away from any
other gallery holding it: whichever was fetched last kept it. In one library
41,532 of 101,242 stored images named two or more of its galleries, and
images vanished from a gallery "as if they never existed", coming back only
when that gallery happened to be fetched again. They are now keyed by
(version_id, id): one row per gallery an image is in.
"""
import contextlib
import io
import json
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
from model_manager.db.database import ModelsDatabase, SCHEMA_VERSION   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'image_galleries')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


for name in os.listdir(WORK) if os.path.isdir(WORK) else []:
    if '.backup_' in name:
        os.remove(os.path.join(WORK, name))
# (A new database is backed up by v4 already; what v25 must not add is its own.)
said = io.StringIO()
with contextlib.redirect_stdout(said):
    db, facts = fixtures.build(WORK)
check('0. v25 backs up nothing for a new database, which has no images to lose',
      'Backed up the database' in said.getvalue(), False)
first, second = facts['version_ids'][0], facts['version_ids'][1]


def image(image_id, level=1):
    return {'id': image_id, 'url': 'https://example.invalid/%d.jpeg' % image_id,
            'nsfwLevel': level, 'modelVersionIds': [first, second],
            'meta': {'prompt': 'a shared image with a long enough prompt'}}


def ids(version_id):
    return sorted(i['id'] for i in db.get_all_images_for_version(version_id))


db.clear_version_images(first)
db.clear_version_images(second)
db.store_images(first, page=1, images=[image(9001), image(9002)])
db.store_images(second, page=1, images=[image(9001), image(9003)])
check('1. an image two galleries show stays in the first when the second is stored',
      ids(first), [9001, 9002])
check('   and is in the second too', ids(second), [9001, 9003])

db.clear_version_images(second)
check('2. clearing one gallery leaves the image in the other', ids(first), [9001, 9002])
db.store_images(second, page=1, images=[image(9001), image(9003)])

db.store_images(first, page=1, images=[image(9001, level=4)])
levels = {r[0]: r[1] for r in db._get_connection().execute(
    "SELECT version_id, effective_nsfw_level FROM images WHERE id = 9001")}
check('3. storing it again in one gallery changes only that gallery\'s row',
      (levels.get(first) != levels.get(second), len(levels)), (True, 2))

changed = db.restamp_image_levels()
check('4. restamping judges every row, shared ones included, without error',
      isinstance(changed, tuple), True)

# ------------------------------------------------------------ the migration
# A database from before: images keyed on id alone, at schema v24.
OLD = os.path.join(WORK, 'old.db')
for name in os.listdir(WORK):
    if name.startswith('old.db'):
        os.remove(os.path.join(WORK, name))
old = sqlite3.connect(OLD)
old.executescript("""
    CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT);
    INSERT INTO schema_info VALUES ('version', '24');
    CREATE TABLE images (
        id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL, page INTEGER NOT NULL,
        url TEXT, width INTEGER, height INTEGER, effective_nsfw_level INTEGER DEFAULT 1,
        created_at TEXT, data TEXT NOT NULL, position INTEGER);
    CREATE INDEX idx_images_version ON images(version_id);
    CREATE INDEX idx_images_gallery ON images(version_id, page, position, id, effective_nsfw_level);
    CREATE TABLE images_v25 (id INTEGER);   -- left by a migration that crashed
""")
old.executemany("INSERT INTO images (id, version_id, page, url, effective_nsfw_level, data, position)"
                " VALUES (?, ?, 1, ?, 1, ?, ?)",
                [(n, 11 if n % 2 else 12, 'u%d' % n, json.dumps({'id': n}), n) for n in range(1, 101)])
old.commit()
old.close()

migrated = ModelsDatabase(WORK, custom_db_path=OLD)
conn = migrated._get_connection()
key = sorted((r[5], r[1]) for r in conn.execute("PRAGMA table_info(images)") if r[5])
check('5. the migration keys images by gallery and image', key, [(1, 'version_id'), (2, 'id')])
check('   keeping every row, with its data',
      (conn.execute("SELECT COUNT(*) FROM images").fetchone()[0],
       conn.execute("SELECT data FROM images WHERE id = 7").fetchone()[0]), (100, '{"id": 7}'))
check('   and every index it had',
      {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'"
                                  " AND tbl_name = 'images' AND sql IS NOT NULL")}
      >= {'idx_images_version', 'idx_images_gallery'}, True)
backups = [n for n in os.listdir(WORK) if n.startswith('old.db.backup_')]
check('   having backed the database up first, beside it', len(backups), 1)
if backups:
    kept = sqlite3.connect(os.path.join(WORK, backups[0]))
    check('   as it was: keyed on the image id, every row there',
          ([r[1] for r in kept.execute("PRAGMA table_info(images)") if r[5]],
           kept.execute("SELECT COUNT(*) FROM images").fetchone()[0]), (['id'], 100))
    kept.close()
check('   at the current schema version',
      conn.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()[0],
      str(SCHEMA_VERSION))
migrated.close()

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
