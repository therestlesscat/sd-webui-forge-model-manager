"""
How the Generations tab reads a level (#238, #259). Single pass, the default,
reads the level's images once per request into a temporary table and builds
every tile from it; Classic reads them again for each tile's previews,
checkpoint and LoRAs. The tiles must come out the same, every level; the work
must stop growing with the groups; no table may outlive its request, a failed
one included; two requests at once must not meet; and the setting must choose.
"""
import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()
opts.model_manager_gallery_page_size = 4

import generation_fixture                                # noqa: E402
from model_manager import tile_reading                   # noqa: E402
from model_manager.api import generations as api         # noqa: E402
from model_manager.db.database import ModelsDatabase     # noqa: E402

WORK = os.path.join(TESTS, 'work', 'tile_reading')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def read_as(reading, fn, *args, **kwargs):
    """`fn` with the setting at `reading` - None for nothing saved."""
    if reading is None:
        opts.__dict__.pop(tile_reading.SETTING, None)
    else:
        setattr(opts, tile_reading.SETTING, reading)
    try:
        return fn(*args, **kwargs)
    finally:
        opts.__dict__.pop(tile_reading.SETTING, None)


def temp_state(db):
    """The connection's temporary tables, and its temporary storage."""
    connection = db._get_connection()
    return ([r[0] for r in connection.execute("SELECT name FROM sqlite_temp_master")],
            connection.execute("PRAGMA temp_store").fetchone()[0])


# ------------------------------------------------------------ the tiles, both ways
path, connection = generation_fixture.v36_database(os.path.join(WORK, 'varied'))
facts = generation_fixture.varied(connection, WORK)
connection.close()
db = ModelsDatabase(extension_dir=ROOT, custom_db_path=path)


def every_part(**params):
    """Every part of a level, each way: (Single pass's, Classic's)."""
    out = []
    for reading in (tile_reading.SINGLE_PASS, tile_reading.CLASSIC):
        parts = []
        for page in range(1, 40):
            parts.append(read_as(reading, api.browse_page, db, page=page, **params))
            if not parts[-1]['more']:
                break
        out.append(parts)
    return out


compared = 0


def same(label, **params):
    """Both ways alike, part by part; Single pass's first part, to open more from."""
    global compared
    single, classic = every_part(**params)
    compared += 1
    check(f'{label}: as many parts', len(single), len(classic))
    for index, (s, c) in enumerate(zip(single, classic)):
        check(f'{label}: part {index + 1}', s, c)
    return single[0]


chains = [''] + list(api.GROUPINGS) + [f'{a}>{b}' for a in api.GROUPINGS for b in api.GROUPINGS if a != b]
for hide in (False, True):
    for group in chains:
        label = f'grouped by {group or "nothing"}, NSFW {"hidden" if hide else "shown"}'
        first = same(label, hide_nsfw=hide, group=group)
        if not group:
            same(f'{label}, expanded', hide_nsfw=hide, group=group, expand=True)
        for tile in first['tiles'][:2]:
            if tile['kind'] == 'generation':
                same(f'{label}, inside a batch', hide_nsfw=hide, group=group, generation=tile['generation']['id'])
            elif 'section' in tile:
                same(f'{label}, a section', hide_nsfw=hide, group=group, in_group=tile['section']['id'])
                same(f'{label}, a group in a section', hide_nsfw=hide, group=group,
                     in_group=tile['section']['id'], in_subgroup=tile['group']['id'])
            else:
                inner = same(f'{label}, a group', hide_nsfw=hide, group=group, in_group=tile['group']['id'])
                same(f'{label}, a group, expanded', hide_nsfw=hide, group=group, in_group=tile['group']['id'],
                     expand=True)
                for batch in inner['tiles'][:1]:
                    if batch['kind'] == 'generation':
                        same(f'{label}, a batch in a group', hide_nsfw=hide, group=group,
                             in_group=tile['group']['id'], generation=batch['generation']['id'])
for search in ('cat', '"red fox"', 'nothing-matches', f'task:{facts["task"]}'):
    for group in ('', 'prompt', 'base_model', 'model>prompt_written'):
        same(f'search {search!r}, grouped by {group or "nothing"}', hide_nsfw=False, group=group, search=search)
check('every grouping and pair was compared both ways, with what lies inside', compared >= 2 * len(chains) * 2,
      True)
# The comparison can fail: Single pass's tiles drawn from another level differ.
check('a level differs from another: this comparison can fail',
      read_as(tile_reading.SINGLE_PASS, api.browse_page, db, False, group='model')
      != read_as(tile_reading.CLASSIC, api.browse_page, db, False, group='size'), True)


# ------------------------------------------------------------ the setting
check('nothing saved reads Single pass', read_as(None, tile_reading.reading), tile_reading.SINGLE_PASS)
check('"Classic" reads Classic', read_as('Classic', tile_reading.reading), tile_reading.CLASSIC)
check('a word it does not know reads Single pass', read_as('Fast', tile_reading.reading), tile_reading.SINGLE_PASS)

asked = []
level = db.generation_scope_level


def spy(*args, **kwargs):
    asked.append(kwargs.get('single_pass', args[4] if len(args) > 4 else True))
    return level(*args, **kwargs)


batch = read_as(None, api.browse_page, db, False)['tiles'][0]['generation']['id']
db.generation_scope_level = spy
for reading in (None, 'Classic', 'Fast'):
    read_as(reading, api.browse_page, db, False, group='base_model')
read_as(None, api.rated_batch, db, False, batch)
del db.generation_scope_level
check('the setting picks the way: nothing saved, Classic, an unknown word; then rating a batch, Classic always',
      asked, [True, False, True, False])


# ------------------------------------------------------------ nothing left behind
read_as(None, api.browse_page, db, False, group='size')
check('after a request: no temporary table left, the storage back to the default', temp_state(db), ([], 0))

tiles = api._tiles


def failing(*args, **kwargs):
    raise RuntimeError('a request failing with its table made')


api._tiles = failing
try:
    read_as(None, api.browse_page, db, False, group='size')
    check('the failing request failed', False, True)
except RuntimeError:
    pass
api._tiles = tiles
check('after a request that failed: no table left, the storage back to the default', temp_state(db), ([], 0))
answer = read_as(None, api.browse_page, db, False, group='size')
check('the request after a failed one answers', answer, read_as('Classic', api.browse_page, db, False, group='size'))

# A table a failed drop left: the next request drops it first, and answers.
db._get_connection().execute("PRAGMA temp_store = MEMORY")
db._get_connection().execute("CREATE TEMP TABLE IF NOT EXISTS mm_level (id INTEGER)")
try:
    after_leftover = read_as(None, api.browse_page, db, False, group='size')
except Exception as error:
    after_leftover = repr(error)
check('a table left behind is answered round', after_leftover,
      read_as('Classic', api.browse_page, db, False, group='size'))
check('and none is left after', temp_state(db), ([], 0))


# ------------------------------------------------------------ two requests at once
# Each thread has its own connection, so its own table: both made before
# either is read, then each answer compared with its own Classic one.
wanted = {g: read_as('Classic', api.browse_page, db, False, group=g) for g in ('base_model', 'size')}
gate = threading.Barrier(2, timeout=30)
got = {}


def held(*args, **kwargs):
    gate.wait()
    return tiles(*args, **kwargs)


def request(group):
    try:
        got[group] = read_as(None, api.browse_page, db, False, group=group)
    except Exception as error:
        got[group] = repr(error)


api._tiles = held
threads = [threading.Thread(target=request, args=(g,)) for g in wanted]
for t in threads:
    t.start()
for t in threads:
    t.join(60)
api._tiles = tiles
for group in wanted:
    check(f'two requests at once: grouped by {group}, as Classic answers it alone', got.get(group), wanted[group])


# ------------------------------------------------------------ the work
def library(name, bases):
    """2,000 images in 200 batches of 10, one checkpoint for each of `bases` base models."""
    root = os.path.join(WORK, name)
    path, connection = generation_fixture.v36_database(root)
    checkpoints = []
    for b in range(bases):
        checkpoint = os.path.join(root, 'models', f'ck{b}.safetensors')
        generation_fixture.library_file(connection, checkpoint, version_id=b + 1, base_model=f'Base {b}')
        checkpoints.append(checkpoint)
    rows, images, files = [], [], []
    for number in range(1, 201):
        checkpoint = checkpoints[number % bases]
        rows.append((number, f"2026-01-01T00:{number // 60 % 60:02d}:{number % 60:02d}", "txt2img", f"p{number}",
                     checkpoint, 10))
        for position in range(10):
            image_id = len(images) + 1
            lora = os.path.join(root, 'Lora', f'l{image_id % 5}.safetensors')
            images.append((image_id, number, position, os.path.join(root, f"{image_id}.png"), f"p{number}",
                           json.dumps([{"name": f"l{image_id % 5}", "path": lora}]), 832, 1216, 1))
            files.extend([(checkpoint, image_id, number), (lora, image_id, number)])
    connection.executemany("INSERT INTO generations (id, created_at, mode, prompt, checkpoint_path, image_count) "
                           "VALUES (?, ?, ?, ?, ?, ?)", rows)
    connection.executemany("INSERT INTO generation_images (id, generation_id, position, path, prompt, loras, "
                           "width, height, prompt_nsfw_level) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", images)
    connection.executemany("INSERT INTO generation_files (file_path, image_id, generation_id) VALUES (?, ?, ?)",
                           files)
    connection.commit()
    connection.close()
    return ModelsDatabase(extension_dir=ROOT, custom_db_path=path)


def steps(database):
    """SQLite's steps for the first part grouped by base model, as the setting reads it."""
    connection = database._get_connection()
    count = [0]

    def tick():
        count[0] += 1
    connection.set_progress_handler(tick, 1)
    try:
        api.browse_page(database, False, group='base_model')
    finally:
        connection.set_progress_handler(None, 1)
    return count[0]


# A part holds every group, as the tab's page of 100 tiles does.
opts.model_manager_gallery_page_size = 100
two, fourteen = library('two_bases', 2), library('fourteen_bases', 14)
growth = (steps(fourteen) - steps(two)) / (2000 * 12)
# Classic joined the part before each image's base model was known, and
# looked it up again for every group, in each of three reads: 87.8 more steps
# for each image and each group added. Single pass works the key out once: 0.7.
check('7 times the groups, the same images: work added per image and group, under 5',
      (growth < 5, f'{growth:.1f} steps'), (True, f'{growth:.1f} steps'))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
