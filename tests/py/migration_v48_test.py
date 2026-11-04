"""
Migration v48 (#378): a settings row per stored Civitai image and per
generation, read from each record and text as the writers read them, in one
transaction, every row compared both ways before it ends. It adds two tables
and changes nothing else; it runs twice without harm, and on a database
missing what it reads; and its work grows with the library, not faster.
"""
import contextlib
import io
import json
import os
import re
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

from model_manager.db import migrations                  # noqa: E402
from model_manager.db import params_table as pt          # noqa: E402

WORK = os.path.join(TESTS, 'work', 'migration_v48')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def raises(call):
    try:
        call()
    except Exception as e:                               # noqa: BLE001 - which one is the point
        return type(e).__name__
    return None


def v47(name):
    """A database at v47, nothing in it."""
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, name + '.db')
    for other in os.listdir(WORK):
        if other.startswith(name + '.db'):
            os.remove(os.path.join(WORK, other))
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT)")
    with contextlib.redirect_stdout(io.StringIO()):
        migrations.run_migrations(conn.cursor(), 0, 47, path, WORK)
    conn.commit()
    return conn, path


# Records of every kind the readings tell apart, made up.
RECORDS = {
    1: {'meta': {'prompt': 'a cat', 'sampler': 'DPM++ 2M Karras', 'steps': 30, 'cfgScale': 7, 'seed': 0,
                 'Size': '832x1216', 'clipSkip': 2, 'Hires upscale': 1.5, 'Hires upscaler': '4x-UltraSharp',
                 'Denoising strength': 0.4}},
    2: {'meta': {'prompt': 'a dog', 'sampler': 'Euler a', 'Schedule type': 'Karras', 'steps': '25',
                 'cfgScale': '7.0', 'Distilled CFG Scale': 3.5}},
    3: {'meta': {'prompt': 'flux', 'sampler': 'euler', 'scheduler': 'simple', 'steps': 20, 'cfgScale': 1,
                 'shift': 3}},
    4: {'meta': {'prompt': 'no settings'}},
    5: {'meta': None},
    6: {'meta': {'prompt': 'a list', 'steps': [20], 'cfgScale': {'v': 7}, 'sampler': ['Euler'], 'seed': True}},
    7: {'meta': {'prompt': 'zeros', 'steps': 0, 'cfgScale': 0, 'seed': 12}},
    8: {'meta': {'prompt': 'kept line', 'negativePrompt': 'blurry\nSteps: 28, Sampler: Euler a, CFG scale: 6, Seed: 9'}},
    9: {'meta': {'prompt': 'half steps', 'steps': 20.5, 'cfgScale': 4.5}},
}
LINE = ('a cat\nNegative prompt: blurry\nSteps: 20, Sampler: DPM++ 2M, Schedule type: Karras, CFG scale: 7, '
        'Seed: 1, Size: 512x768, Clip skip: 2, Hires upscaler: "4x-UltraSharp", Shift: 3')
NAME = {'Model': 'a_model', 'Sampler': 'Euler a', 'Steps': '28', 'CFG scale': '5', 'Size': '512x768'}
# Each generation: its own text, then each image's text and meta, in order.
GENERATIONS = {
    1: (LINE, [(LINE, {}), (LINE, {})]),
    2: (None, [(None, {}), ('x\nSteps: 9, Sampler: Euler, CFG scale: 1', {})]),
    3: (None, [(None, NAME)]),
    4: ('just a prompt', [('just a prompt', {})]),
    5: (None, [(None, {})]),
}


def fill(conn, records=RECORDS, generations=GENERATIONS):
    conn.executemany("INSERT INTO image_records (image_id, url, data) VALUES (?, ?, ?)",
                     [(i, 'u%d' % i, json.dumps(r)) for i, r in records.items()])
    image_id = 0
    for g, (own, images) in generations.items():
        conn.execute("INSERT INTO generations (id, created_at, mode, image_count) VALUES (?, '2026-01-01', 'txt2img', ?)",
                     (g, len(images)))
        conn.execute("INSERT INTO generation_details (generation_id, infotext) VALUES (?, ?)", (g, own))
        for position, (text, meta) in enumerate(images):
            image_id += 1
            conn.execute("INSERT INTO generation_images (id, generation_id, position, path) VALUES (?, ?, ?, ?)",
                         (image_id, g, position, 'out/%d.png' % image_id))
            conn.execute("INSERT INTO generation_image_details (image_id, infotext, meta) VALUES (?, ?, ?)",
                         (image_id, text, json.dumps(meta)))
    conn.commit()


def dump(conn):
    """Every table but the two v48 adds, row by row."""
    out = {}
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT IN "
                                 "('image_params', 'generation_params', 'schema_info') ORDER BY name").fetchall():
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
        out[table] = (sql, sorted(conn.execute('SELECT * FROM "%s"' % table).fetchall(), key=repr))
    return out


def stored(conn, table, key, columns):
    names = list(columns)
    return {row[0]: (dict(zip(names, row[1:1 + len(names)])), row[1 + len(names):])
            for row in conn.execute("SELECT %s, %s, %s FROM %s" % (key, ', '.join(names),
                                                                   ', '.join('typeof(%s)' % n for n in names), table))}


def value(rows, key, column):
    """One stored value; None where the row is missing, so a break fails a check rather than the suite."""
    return rows.get(key, ({},))[0].get(column)


def stored_as(rows, key, column, columns):
    """The type SQLite stored one value as; None where the row is missing."""
    return rows[key][1][list(columns).index(column)] if key in rows else None


def migrate(conn, progress=None):
    with contextlib.redirect_stdout(io.StringIO()):
        migrations._migrate_to_v48(conn.cursor(), progress)
    conn.commit()


from model_manager.db.database import ModelsDatabase   # noqa: E402

RECORDS[10] = {'meta': {'prompt': 'a seed past 64 bits', 'seed': 18446744073709551615, 'steps': 20}}
RECORDS[11] = {'meta': 'not an object'}
# A generation whose own text is empty, its first image's too, its second's not.
GENERATIONS[6] = ('', [('', {}), ('x\nSteps: 12, Sampler: Euler, CFG scale: 2', {})])


def as_written(own, images):
    """A generation as the recorder and Sync images hand it to the writer."""
    generation = {'created_at': '2026-01-01T00:00:00', 'mode': 'txt2img', 'image_count': len(images)}
    if own is not None:
        generation['infotext'] = own
    rows = [{'position': n, 'path': os.path.join(WORK, 'out', '%d-%d.png' % (id(images), n)), 'meta': meta,
             'prompt_nsfw_level': 1, **({'infotext': text} if text is not None else {})}
            for n, (text, meta) in enumerate(images)]
    return generation, rows, [[] for _ in rows]


# 22. Written by the real writers - a gallery's fetch, the recorder - then
# both tables emptied and v48 run over the same records and texts: what it
# writes is what they wrote.
path = os.path.join(WORK, 'library.db')
for other in os.listdir(WORK) if os.path.isdir(WORK) else []:
    if other.startswith('library.db'):
        os.remove(os.path.join(WORK, other))
os.makedirs(WORK, exist_ok=True)
with contextlib.redirect_stdout(io.StringIO()):
    db = ModelsDatabase(WORK, custom_db_path=path)
fetched = raises(lambda: db.store_images(1, page=1, images=[
    {'id': i, 'url': 'https://example.invalid/%d.jpeg' % i, 'nsfwLevel': 1, 'modelVersionIds': [1], 'meta': r['meta']}
    for i, r in RECORDS.items()]))
check('a gallery\'s fetch goes through, a seed past 64 bits and a meta that is not an object among its images',
      fetched, None)
made = db.record_generations([as_written(*GENERATIONS[g]) for g in sorted(GENERATIONS)])
ids = dict(zip(sorted(GENERATIONS), made))
db.close()
conn = sqlite3.connect(path)
by_writers = (stored(conn, 'image_params', 'image_id', pt.IMAGE_COLUMNS),
              stored(conn, 'generation_params', 'generation_id', pt.GENERATION_COLUMNS))
conn.execute("DELETE FROM image_params")
conn.execute("DELETE FROM generation_params")
conn.commit()
before = dump(conn)
told = []
every = migrations.V48_REPORT_EVERY
migrations.V48_REPORT_EVERY = 4
try:
    check('v48 runs over them', raises(lambda: migrate(conn, told.append)), None)
finally:
    migrations.V48_REPORT_EVERY = every
images = stored(conn, 'image_params', 'image_id', pt.IMAGE_COLUMNS)
generations = stored(conn, 'generation_params', 'generation_id', pt.GENERATION_COLUMNS)
check('v48 writes every row the writers wrote, and no other: each value, and the type it is stored as',
      (images, generations), by_writers)

check('    a record giving none, no meta, only lists and objects, or a meta that is not an object: no row',
      sorted(set(RECORDS) - set(images)), [4, 5, 6, 11])
check('    a seed past 64 bits is no value; the rest of its row kept',
      (value(images, 10, 'seed'), value(images, 10, 'steps')), (None, 20))
check('    a 0 for steps or CFG is no value; a seed kept', (value(images, 7, 'steps'), value(images, 7, 'seed')),
      (None, 12))
TYPES = {'text': 'text', 'whole': 'integer', 'number': 'real'}
wrong = [(i, name) for i, (values, types) in images.items()
         for (name, kind), as_stored in zip(pt.IMAGE_COLUMNS.items(), types)
         if as_stored != ('null' if values[name] is None else TYPES[kind])
         and not (kind == 'whole' and as_stored == 'real' and isinstance(values[name], float))]
check('    each value stored as its column holds it: text, integer, real', wrong, [])
check('    a whole count that is not whole (20.5 steps) stays a real',
      (value(images, 9, 'steps'), stored_as(images, 9, 'steps', pt.IMAGE_COLUMNS)), (20.5, 'real'))
check('    7 and 7.0 both stored as the real 7.0',
      (value(images, 2, 'cfg'), stored_as(images, 2, 'cfg', pt.IMAGE_COLUMNS)), (7.0, 'real'))
def reading(record):
    """Today's reading of a record; its error's name where it raises, so a break fails a check."""
    try:
        return pt.image_params_row(record)
    except Exception as e:                               # noqa: BLE001
        return type(e).__name__


check('    a record\'s row is the reading\'s', {i: v for i, (v, _) in images.items()},
      {i: reading(r) for i, r in RECORDS.items() if reading(r)})

check('a generation by its own text', value(generations, ids[1], 'steps'), 20)
check('    by its first image\'s text with one where its own is empty or missing',
      (value(generations, ids[2], 'steps'), value(generations, ids[6], 'steps')), (9, 12))
check('    by its file name where no text gives one',
      (value(generations, ids[3], 'sampler'), value(generations, ids[3], 'steps')), ('Euler a', 28))
check('    a generation whose text gives no setting, and one with nothing: no row',
      sorted(g for g in GENERATIONS if ids[g] not in generations), [4, 5])

check('every other table as it was', dump(conn), before)
check('it said how far it had got, as it went and before its check',
      (any(re.fullmatch(r'\d+ of \d+ images', t) for t in told), any('checking' in t for t in told)), (True, True))
check('the tables have their columns, in order',
      ([r[1] for r in conn.execute("PRAGMA table_info(image_params)")],
       [r[1] for r in conn.execute("PRAGMA table_info(generation_params)")]),
      (['image_id', *pt.IMAGE_COLUMNS], ['generation_id', *pt.GENERATION_COLUMNS]))

# ---------------------------------------------- twice, and a partial database
check('run a second time: it runs, and writes the same rows',
      (raises(lambda: migrate(conn)), stored(conn, 'image_params', 'image_id', pt.IMAGE_COLUMNS),
       stored(conn, 'generation_params', 'generation_id', pt.GENERATION_COLUMNS)),
      (None, images, generations))
conn.close()

bare = sqlite3.connect(os.path.join(WORK, 'bare.db'))
bare.execute("DROP TABLE IF EXISTS image_params")
bare.execute("DROP TABLE IF EXISTS generation_params")
bare.execute("CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT)")
bare.commit()
check('a database with none of the tables it reads: it runs, and makes its two tables, empty',
      (raises(lambda: migrate(bare)),
       [bare.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in ('image_params', 'generation_params')]),
      (None, [0, 0]))
bare.close()

# --------------------------------------------- the proof can fail
conn, _ = v47('proof')
fill(conn, {1: RECORDS[1]}, {1: GENERATIONS[1]})
check('the proof\'s own library migrates', raises(lambda: migrate(conn)), None)
row = pt.image_params_row(RECORDS[1])
row = tuple(row[n] for n in pt.IMAGE_COLUMNS)
changed = tuple(31 if n == 'steps' else v for n, v in zip(pt.IMAGE_COLUMNS, row))
check('the proof fails a row that differs from the one expected',
      raises(lambda: migrations._v48_check(conn.cursor(), 'image_params', 'image_id', migrations._V48_IMAGE_COLUMNS,
                                           {1: changed})), 'RuntimeError')
check('    a row written but not expected',
      raises(lambda: migrations._v48_check(conn.cursor(), 'image_params', 'image_id', migrations._V48_IMAGE_COLUMNS, {})),
      'RuntimeError')
check('    a value stored as another type',
      raises(lambda: (conn.execute("UPDATE image_params SET hires_upscale = '1.5x' WHERE image_id = 1"),
                      migrations._v48_check(conn.cursor(), 'image_params', 'image_id', migrations._V48_IMAGE_COLUMNS,
                                            {1: row}))), 'RuntimeError')
conn.rollback()
check('    and as it stands, passes',
      raises(lambda: migrations._v48_check(conn.cursor(), 'image_params', 'image_id', migrations._V48_IMAGE_COLUMNS,
                                           {1: row})), None)
conn.close()

# ------------------------------------------------ 23. its work, at scale
# v42's lesson: a check that reads the whole table per row never finished at
# 127,000 images. SQLite's virtual machine steps, at four times the library.


def steps(n):
    conn, _ = v47('scale%d' % n)
    fill(conn, {i: RECORDS[1 + i % 9] for i in range(1, n + 1)},
         {g: GENERATIONS[1 + g % 5] for g in range(1, n // 4 + 1)})
    counted = [0]

    def count():
        counted[0] += 1
        return 0
    conn.set_progress_handler(count, 100)
    check('a library of %d images migrates' % n, raises(lambda: migrate(conn)), None)
    conn.close()
    return counted[0]


small, large = steps(200), steps(800)
check('four times the images: under six times the work (%d against %d)' % (large, small), large < 6 * small, True)

print('\n'.join('FAIL ' + f for f in fails) if fails else 'All checks passed.')
sys.exit(1 if fails else 0)
