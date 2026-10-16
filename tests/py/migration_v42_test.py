"""
Migration v42 (#283): each Civitai image stored once.

A v41 library whose `images` table holds every kind of row - an image in one
gallery, one in two whose newest copy lacks the prompt an older one has, one
in two whose copies differ only in what Civitai said later, prompts with
untidy spacing, resources of every type and a list with a stray entry, a
record that is not JSON, a level never judged - is migrated. Every gallery
row comes through, each image is one row and one record, its prompts and
resources made from its record, the generation images' indexes renamed for
their table, and the v41 database backed up beside it. Run again, nothing
changes. Breaks inside the migration - a gallery row dropped, a record, a
level, an address, a size or a date changed, a resource dropped or its weight
or name changed, an older copy's date kept where Civitai dated the image again
- each raise, and the database stays at v41.
"""
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

import generation_fixture                                # noqa: E402
from model_manager.db import migrations                  # noqa: E402
from model_manager.db.database import ModelsDatabase, SCHEMA_VERSION  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'migration_v42')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def record(image_id, prompt=None, negative=None, resources=None, likes=0):
    meta = None
    if prompt is not None or negative is not None or resources is not None:
        meta = {}
        if prompt is not None:
            meta['prompt'] = prompt
        if negative is not None:
            meta['negativePrompt'] = negative
        if resources is not None:
            meta['civitaiResources'] = resources
    return json.dumps({'id': image_id, 'url': f'https://e.invalid/{image_id}.jpeg', 'type': 'image',
                       'stats': {'likeCount': likes}, 'meta': meta})


LORA = {'type': 'LORA', 'modelVersionId': 501, 'modelId': 50, 'name': 'A', 'modelVersionName': 'v1', 'weight': 0.7}
# A weight Civitai sent as text: stored as the column converts it, and not a difference.
TEXT_WEIGHT = {'type': 'LORA', 'modelVersionId': 505, 'modelId': 51, 'weight': '0.8'}
# (id, version, page, position, level, created_at, data): in write order, each later write the newer copy.
ROWS = [
    (1, 10, 1, 0, 1, '2026-01-01T00:00:00.000Z', record(1, 'a  cat ', 'blurry', [LORA, 'stray', {'type': 'LoCon', 'modelVersionId': 502},
                                                                               {'type': 'TextualInversion', 'modelVersionId': 503},
                                                                               {'type': 'Wildcards', 'modelVersionId': 504}])),
    (2, 10, 1, 1, 8, '2026-01-02T00:00:00.000Z', record(2, 'a dog', None, [LORA], likes=1)),
    (2, 11, 1, 0, 8, '2026-01-02T00:00:00.000Z', record(2)),          # newer copy, no prompt: the older's kept
    (3, 10, 2, 0, 4, '2026-01-03T00:00:00.000Z', record(3, 'a bird', 'x', [], likes=1)),
    (3, 12, 1, 0, 4, '2026-01-03T00:00:00.000Z', record(3, 'a bird', 'x', [], likes=9)),  # newer: it wins whole
    (4, 11, 1, 1, None, None, 'not json'),
    (5, 12, 1, 1, 2, '2026-01-05T00:00:00.000Z', record(5, 'a cat', None, [TEXT_WEIGHT])),
    (6, 10, 3, 0, 1, '2026-01-06T00:00:00.000Z', record(6, 'a fish')),
    (6, 11, 2, 0, 1, '2026-01-06T05:00:00.000Z', record(6, 'a fish')),  # Civitai dated it again: newest's date
]


def v41_library(directory, extra=0):
    """The library above, and `extra` more images, every tenth in a second gallery."""
    path, connection = generation_fixture.v36_database(directory)
    generation_fixture.varied(connection, directory)
    cursor = connection.cursor()
    migrations.run_migrations(cursor, 36, 41, path, directory)
    connection.commit()
    cursor.executemany("INSERT INTO images (id, version_id, page, position, effective_nsfw_level, created_at, url, "
                       "width, height, data) VALUES (?, ?, ?, ?, ?, ?, ?, 512, 768, ?)",
                       [(i, v, p, pos, lv, when, f'https://e.invalid/{i}.jpeg', data)
                        for i, v, p, pos, lv, when, data in ROWS])
    more = [(1000 + n, 20 + n % 7, 1, n, 1, '2026-01-01T00:00:00.000Z', f'https://e.invalid/{1000 + n}.jpeg',
             record(1000 + n, f'prompt {n % 50}', None, [LORA])) for n in range(extra)]
    more += [(i, v + 100, p, pos, lv, when, url, data) for i, v, p, pos, lv, when, url, data in more[::10]]
    cursor.executemany("INSERT INTO images (id, version_id, page, position, effective_nsfw_level, created_at, url, "
                       "width, height, data) VALUES (?, ?, ?, ?, ?, ?, ?, 512, 768, ?)", more)
    connection.commit()
    return path, connection


def names(connection, kind='table'):
    return {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))}


def version(connection):
    row = connection.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()
    return row[0] if row else None


def old_rows(connection):
    return sorted(tuple(r) for r in connection.execute(
        "SELECT id, version_id, page, position, effective_nsfw_level, created_at, data FROM images"))


def backups(directory):
    return sorted(n for n in os.listdir(directory) if n.endswith('_v42'))


# ------------------------------------------------------------ the migration
check('v42 is a schema this copy has passed', SCHEMA_VERSION >= 42)
path, connection = v41_library(os.path.join(WORK, 'library'))
before = old_rows(connection)
generation_rows = connection.execute("SELECT COUNT(*) FROM generation_images").fetchone()[0]
cursor = connection.cursor()
try:
    migrations.run_migrations(cursor, 41, 42, path, os.path.dirname(path))
    connection.commit()
    raised = None
except Exception as error:  # a raise is a failure of its own, so the checks below still say what is wrong
    connection.rollback()
    raised = str(error)
check('the migration runs without raising', raised, None)
tables = names(connection)
check('the five tables, and today\'s images table gone',
      ({'images', 'image_galleries', 'image_records', 'image_resources', 'image_prompts'} <= tables,
       'data' in {r[1] for r in connection.execute('PRAGMA table_info(images)')}), (True, False))

q = lambda sql, *args: [tuple(r) for r in connection.execute(sql, args).fetchall()]
try:
    check('every gallery row: its version, page, place and level',
          sorted(q("SELECT image_id, version_id, page, position, effective_nsfw_level FROM image_galleries")),
          sorted((i, v, p, pos, lv) for i, v, p, pos, lv, _, _ in before))
    check('each image one row and one record', (q("SELECT COUNT(*) FROM images")[0][0],
                                                 q("SELECT COUNT(*) FROM image_records")[0][0]), (6, 6))
    check('copies Civitai dated differently: the newest copy\'s date',
          q("SELECT created_at FROM images WHERE id = 6"), [('2026-01-06T05:00:00.000Z',)])
    data = {i: d for i, d in q("SELECT image_id, data FROM image_records")}
    check('an image with one copy: its record byte for byte', (data.get(1), data.get(4), data.get(5)),
          (ROWS[0][6], 'not json', ROWS[6][6]))
    kept = json.loads(data.get(2) or '{}')
    check('a newer copy without a prompt: the older copy\'s generation data, carried over',
          ((kept.get('meta') or {}).get('prompt'), kept.get('stats')), ('a dog', {'likeCount': 0}))
    check('copies that differ otherwise: the newest wins, byte for byte', data.get(3), ROWS[4][6])
    prompts = dict(q("SELECT i.id, p.text FROM images i LEFT JOIN image_prompts p ON p.id = i.prompt_id"))
    negatives = dict(q("SELECT i.id, p.text FROM images i LEFT JOIN image_prompts p ON p.id = i.negative_id"))
    check('each image\'s prompts are its record\'s',
          (prompts, negatives), ({1: 'a  cat ', 2: 'a dog', 3: 'a bird', 4: None, 5: 'a cat', 6: 'a fish'},
                                 {1: 'blurry', 2: None, 3: 'x', 4: None, 5: None, 6: None}))
    tidy = q("SELECT a.grouped_as = b.id, b.grouped_as = b.id, a.length FROM image_prompts a, image_prompts b "
             "WHERE a.text = 'a  cat ' AND b.text = 'a cat'")
    check('untidy spacing groups with the tidy text, and its length is trimmed', tidy, [(1, 1, 6)])
    check('each resource the record lists, at its place, by role',
          q("SELECT position, role, type, version_id FROM image_resources WHERE image_id = 1 ORDER BY position"),
          [(0, 'lora', 'LORA', 501), (2, 'lora', 'LoCon', 502), (3, 'embedding', 'TextualInversion', 503),
           (4, 'other', 'Wildcards', 504)])
    check('a level never judged stays so', q("SELECT effective_nsfw_level FROM image_galleries WHERE image_id = 4"),
          [(None,)])
    check('the image\'s size, date and kind on its row',
          q("SELECT width, height, created_at, media_type FROM images WHERE id = 1"),
          [(512, 768, '2026-01-01T00:00:00.000Z', 'image')])
    gen_indexes = {n: [c[2] for c in connection.execute(f'PRAGMA index_info("{n}")')] for n in
                   ('idx_generation_images_generation', 'idx_generation_images_prompt',
                    'idx_generation_images_negative', 'idx_generation_images_path')}
    check('the generation images\' indexes named for their table',
          gen_indexes, {'idx_generation_images_generation': ['generation_id', 'position', 'prompt_nsfw_level',
                                                             'user_nsfw_level'],
                        'idx_generation_images_prompt': ['prompt_id'], 'idx_generation_images_negative': ['negative_id'],
                        'idx_generation_images_path': ['path']})
    check('and idx_images_* are Civitai\'s images\'',
          q("SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name IN ('idx_images_prompt', 'idx_images_negative')"),
          [('images',), ('images',)])
    check('your generations untouched', q("SELECT COUNT(*) FROM generation_images")[0][0], generation_rows)
except sqlite3.Error as error:
    check('the new tables can be read', str(error), None)

made = backups(os.path.dirname(path))
check('a backup beside the database, named for v42', len(made), 1)
if made:
    saved = sqlite3.connect(os.path.join(os.path.dirname(path), made[0]))
    check('the backup is the v41 database, every row there', (version(saved), old_rows(saved)), ('41', before))
    saved.close()

after = q("SELECT * FROM image_records ORDER BY image_id") if 'image_records' in tables else []
try:
    migrations.run_migrations(cursor, 41, 42, path, os.path.dirname(path))
    connection.commit()
except Exception as error:
    connection.rollback()
    check('run twice, it does not raise', str(error), None)
check('run twice, it changes nothing and backs up nothing more',
      (q("SELECT * FROM image_records ORDER BY image_id") if 'image_records' in tables else [],
       backups(os.path.dirname(path))), (after, made))
connection.close()

# ------------------------------------------------------------ a new database
NEW = os.path.join(WORK, 'new')
os.makedirs(NEW, exist_ok=True)
for name in os.listdir(NEW):
    os.remove(os.path.join(NEW, name))
try:
    ModelsDatabase(extension_dir=ROOT, custom_db_path=os.path.join(NEW, 'models.db'))
except Exception as error:
    check('a new database is made without raising', str(error), None)
raw = sqlite3.connect(os.path.join(NEW, 'models.db'))
check('a new database is made at v42, with nothing to back up for it',
      (version(raw), 'image_records' in names(raw), backups(NEW)), (str(SCHEMA_VERSION), True, []))
raw.close()


# ------------------------------------------------------------ breaks
class Breaking:
    """A cursor that does one thing wrong once the tables are built, before they are checked."""

    def __init__(self, cursor, then):
        self._cursor, self._then = cursor, then
        self.connection = cursor.connection

    def execute(self, sql, *args):
        result = self._cursor.execute(sql, *args)
        if self._then and sql.startswith("UPDATE image_prompts SET length"):
            self._cursor.execute(self._then)
            self._then = None
        return result

    def executemany(self, sql, *args):
        return self._cursor.executemany(sql, *args)


def broken(label, then):
    path, connection = v41_library(os.path.join(WORK, label))
    before = old_rows(connection)
    raised = None
    try:
        migrations._migrate_to_v42(Breaking(connection.cursor(), then), path)
    except RuntimeError as error:
        raised = str(error)
    except Exception as error:  # no v42 to run: a failure by name, not the suite stopped
        check(f'{label}: the migration runs to its checks', repr(error), None)
    connection.rollback()
    check(f'{label}: it raises', raised is not None)
    check(f'{label}: the database is still at v41, its rows as they were, nothing of v42',
          (version(connection), old_rows(connection), 'image_records' in names(connection)), ('41', before, False))
    connection.close()


broken('a gallery row dropped', "DELETE FROM image_galleries WHERE image_id = 3 AND version_id = 10")
broken('a record changed', "UPDATE image_records SET data = data || ' ' WHERE image_id = 1")
broken('a level changed', "UPDATE image_galleries SET effective_nsfw_level = 16 WHERE image_id = 5")
broken('a resource dropped', "DELETE FROM image_resources WHERE image_id = 1 AND position = 3")
broken('a resource\'s weight changed', "UPDATE image_resources SET weight = 0.9 WHERE image_id = 1 AND position = 0")
broken('a resource\'s name changed', "UPDATE image_resources SET name = 'B' WHERE image_id = 1 AND position = 0")
broken('an address changed', "UPDATE image_records SET url = 'https://e.invalid/other.jpeg' WHERE image_id = 3")
broken('a size changed', "UPDATE images_v42 SET width = 513 WHERE id = 2")
broken('a date changed where the copies agree', "UPDATE images_v42 SET created_at = '2026-02-01' WHERE id = 3")
broken('the older copy\'s date kept', "UPDATE images_v42 SET created_at = '2026-01-06T00:00:00.000Z' WHERE id = 6")

# ------------------------------------------------------------ work, and room
# A check that asked each row about its image's other copies read the whole
# table again per row: at 127,000 rows the migration never finished. Its work
# has to grow with the library, not with its square.
def steps(extra):
    path, connection = v41_library(os.path.join(WORK, f'work_{extra}'), extra)
    count = [0]
    connection.set_progress_handler(lambda: count.__setitem__(0, count[0] + 1) or 0, 1000)
    try:
        migrations._migrate_to_v42(connection.cursor(), path)
        connection.commit()
    except Exception as error:
        check(f'{extra} more images migrate', repr(error), None)
    connection.close()
    return count[0]


small, large = steps(1000), steps(4000)
check('four times the images, about four times the work - not sixteen', (small > 0, large < small * 6),
      (True, True))

# Not room for a backup and the new tables: refused before anything is written.
path, connection = v41_library(os.path.join(WORK, 'room'))
before = old_rows(connection)
real = migrations.shutil.disk_usage
migrations.shutil.disk_usage = lambda where: type('usage', (), {'free': 1000})()
try:
    migrations._migrate_to_v42(connection.cursor(), path)
    said = None
except RuntimeError as error:
    said = str(error)
finally:
    migrations.shutil.disk_usage = real
connection.rollback()
check('no room: refused, saying how much it needs and that nothing changed',
      (bool(said) and 'GB free' in said and 'unchanged' in said, version(connection), old_rows(connection),
       backups(os.path.dirname(path))), (True, '41', before, []))
connection.close()

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
