"""
How the Generations tab reads a level (#238, #259). Single pass, the default,
reads the level's images once per request into a temporary table and builds
every tile from it; Classic reads them again for each tile's previews,
checkpoint and LoRAs. The tiles must come out the same, every level; the work
must stop growing with the groups; no table may outlive its request, a failed
one included; two requests at once must not meet; and the setting must choose.
A queued task of several checkpoints (#401) is one tile on a level of
generations that shows its runs of two or more checkpoints, keyed by the task
in both ways alike; a library with none reads as it did.
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
# The tab loads a part at a time as you scroll, not a setting (#230).
import model_manager.gallery as gallery_module        # noqa: E402
gallery_module.TILE_PART = 4

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
        first = same(label, nsfw=hide, group=group)
        if not group:
            same(f'{label}, expanded', nsfw=hide, group=group, expand=True)
        for tile in first['tiles'][:2]:
            if tile['kind'] == 'generation':
                same(f'{label}, inside a batch', nsfw=hide, group=group, generation=tile['generation']['id'])
            elif 'section' in tile:
                same(f'{label}, a section', nsfw=hide, group=group, in_group=tile['section']['id'])
                same(f'{label}, a group in a section', nsfw=hide, group=group,
                     in_group=tile['section']['id'], in_subgroup=tile['group']['id'])
            else:
                inner = same(f'{label}, a group', nsfw=hide, group=group, in_group=tile['group']['id'])
                same(f'{label}, a group, expanded', nsfw=hide, group=group, in_group=tile['group']['id'],
                     expand=True)
                for batch in inner['tiles'][:1]:
                    if batch['kind'] == 'generation':
                        same(f'{label}, a batch in a group', nsfw=hide, group=group,
                             in_group=tile['group']['id'], generation=batch['generation']['id'])
# The ids (#336): a checkpoint's version, LoRAs' with a word, a model, images.
for search in ('cat', '"red fox"', 'nothing-matches', f'task:{facts["task"]}',
               'version:1', 'version:10,11 cat', 'model:2', 'image:1,2,3,40'):
    for group in ('', 'prompt', 'base_model', 'model>prompt_written'):
        same(f'search {search!r}, grouped by {group or "nothing"}', nsfw=False, group=group, search=search)
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


# ------------------------------------------------------------ a task of several checkpoints (#401)
# Tasks of the Queue over the fixture's generations (generation_fixture.SEVERAL):
# a task whose runs of two or more of its checkpoints a level shows is one
# tile there, keyed by the task; both ways alike, every level.
tdb, gid = generation_fixture.several_library(os.path.join(WORK, 'several'), ROOT)
place = {generation: g for g, generation in enumerate(gid)}


def every_part_of(database, **params):
    """Every part of a level of `database`, each way: (Single pass's, Classic's)."""
    out = []
    for reading in (tile_reading.SINGLE_PASS, tile_reading.CLASSIC):
        parts = []
        for page in range(1, 40):
            parts.append(read_as(reading, api.browse_page, database, page=page, **params))
            if not parts[-1]['more']:
                break
        out.append(parts)
    return out


def same_with_tasks(label, **params):
    """Both ways alike on the tasks' library, part by part; every tile of Single pass's."""
    single, classic = every_part_of(tdb, **params)
    check(f'{label}: as many parts', len(single), len(classic))
    for index, (s, c) in enumerate(zip(single, classic)):
        check(f'{label}: part {index + 1}', s, c)
    return [tile for part in single for tile in part['tiles']]


def task_tiles(tiles):
    """Each task tile: its task, and its generations by place."""
    return {t['task']['id']: [place[g] for g in t['task']['generations']] for t in tiles if t['kind'] == 'task'}


top = same_with_tasks('the tasks\' library, no grouping, every image', nsfw='all', tasks=True)
check('no grouping: a tile for each task whose runs of two or more checkpoints are shown, its runs newest first',
      task_tiles(top), {109: [36, 32], 106: [28, 26], 111: [22, 4], 103: [18, 16, 11, 8], 110: [14, 3],
                        100: [9, 6, 0]})
facts = {t['task']['id']: (t['task']['checkpoints'], t['task']['images'], t['matching_count'])
         for t in top if t['kind'] == 'task'}
check('each named by the checkpoints it holds, counting every image of its runs and those shown',
      facts, {109: (2, 2, 2), 106: (2, 4, 4), 111: (2, 4, 4), 103: (2, 9, 9), 110: (2, 7, 7), 100: (3, 6, 6)})
batches = [place[t['generation']['id']] for t in top if t['kind'] == 'generation']
check('the rest are batches: one checkpoint\'s cells, one run that made images, two files of one name, '
      'a generation the lower of two tasks owns',
      all(g in batches for g in (10, 15, 20, 30, 5, 2, 12, 35, 21, 23, 17, 38)), True)
safe = same_with_tasks('the tasks\' library, no grouping, NSFW hidden', nsfw=True, tasks=True)
check('counted among what the NSFW switch shows: task 109\'s X-rated run hidden, its other run is a batch',
      [109 in task_tiles(safe), 36 in [place[t['generation']['id']] for t in safe if t['kind'] == 'generation']],
      [False, True])
task_images = [i for t in top if t['kind'] == 'task' for i in t['images']]
check('a task tile\'s images carry their own generation\'s date and mode; a batch\'s do not',
      [all('created_at' in i and 'mode' in i for i in task_images),
       any('mode' in i for t in top if t['kind'] != 'task' for i in t['images'])], [True, False])
own = tdb.get_generations([i['generation_id'] for i in task_images])
check('each its own run\'s, not the tile\'s newest',
      [(i['created_at'], i['mode']) for i in task_images],
      [(own[i['generation_id']]['created_at'], own[i['generation_id']]['mode']) for i in task_images])
check('which differ from the tile\'s own somewhere: the check can tell',
      any(i['created_at'] != t['generation']['created_at'] for t in top if t['kind'] == 'task' for i in t['images']),
      True)
check('a page that does not ask for task tiles gets none: each run a batch, as today',
      [t['kind'] for t in same_with_tasks('the tasks\' library, not asked', nsfw='all')].count('task'), 0)
for group in chains:
    for hide in (False, True):
        tiles_here = same_with_tasks(f'the tasks\' library, grouped by {group or "nothing"}, '
                                     f'NSFW {"hidden" if hide else "shown"}', nsfw=hide, group=group, tasks=True)
        for tile in tiles_here[:3]:
            if 'section' in tile:
                # Grouped twice: a section's groups, and a group inside it.
                same_with_tasks(f'the tasks\' library, grouped by {group}, a section', nsfw=hide, group=group,
                                in_group=tile['section']['id'], tasks=True)
                same_with_tasks(f'the tasks\' library, grouped by {group}, a group in a section', nsfw=hide,
                                group=group, in_group=tile['section']['id'], in_subgroup=tile['group']['id'],
                                tasks=True)
            if tile['kind'] == 'group' and 'section' not in tile:
                inner = same_with_tasks(f'the tasks\' library, grouped by {group}, a group', nsfw=hide,
                                        group=group, in_group=tile['group']['id'], tasks=True)
                if group == 'model':
                    check(f'grouped by Model, the group {tile["group"]["value"]!r}: one checkpoint\'s runs, '
                          f'no task tile', [t['kind'] for t in inner].count('task'), 0)
prompts = same_with_tasks('the tasks\' library, by Prompt as written', nsfw='all', group='prompt_written', tasks=True)
in_prompts = {}
for tile in prompts:
    in_prompts.update(task_tiles(same_with_tasks(f'the Prompt group {tile["group"]["value"]!r}', nsfw='all',
                                                 group='prompt_written', in_group=tile['group']['id'], tasks=True)))
check('a Prompt group holding two of task 110\'s runs, opened: one task tile of them; no other Prompt group holds one',
      in_prompts, {110: [14, 3]})
day = same_with_tasks('the tasks\' library, by Day', nsfw='all', group='day', tasks=True)
day_inner = same_with_tasks('the tasks\' library, the Day group', nsfw='all', group='day',
                            in_group=day[0]['group']['id'], tasks=True)
check('a group\'s level of generations shows the tasks\' tiles too: the one Day holds them all',
      task_tiles(day_inner), task_tiles(top))
for task_id, runs in task_tiles(top).items():
    inside = same_with_tasks(f'the tasks\' library, task {task_id} opened', nsfw='all', task=task_id, tasks=True)
    check(f'task {task_id} opened: its runs, a batch each, newest first',
          [(t['kind'], place[t['generation']['id']]) for t in inside], [('generation', g) for g in runs])
inside = same_with_tasks('the tasks\' library, task 100 opened, again', nsfw='all', task=100, tasks=True)
check('inside a task, each run named: its checkpoint\'s file, or - one the library lacks - its name',
      [(place[t['generation']['id']], (t['checkpoint'] or {}).get('name'), t['checkpoint_name']) for t in inside],
      [(9, None, 'synced_ck'), (6, 'b', 'b'), (0, 'a', 'a')])
check('the header names the task opened', read_as(None, api.browse_page, tdb, 'all', task=100)['scope']['task'],
      {'id': 100, 'checkpoints': 3})
check('a generation two tasks link is the lower one\'s: task 105 opened shows its other run alone',
      [place[t['generation']['id']] for t in same_with_tasks('task 105', nsfw='all', task=105)], [23])
check('and task 104, the lower, shows it',
      [place[t['generation']['id']] for t in same_with_tasks('task 104', nsfw='all', task=104)], [21])
same_with_tasks('the tasks\' library, expanded', nsfw='all', tasks=True, expand=True)
same_with_tasks('task 103 opened, expanded', nsfw='all', task=103, tasks=True, expand=True)
# The shape the page's stand-ins hand it (#401, commit 1): what it reads of a
# task tile, of its images, and of a run's tile inside a task.
task_tile = next((t for t in top if t['kind'] == 'task'), {'task': {}, 'images': [{}]})
check('the answer\'s shape: a task tile as the page reads it',
      [sorted(task_tile['task']), sorted(set(task_tile['images'][0]) & {'generation_id', 'created_at', 'mode',
                                                                        'checkpoint_path', 'checkpoint'}),
       'generation' in task_tile, 'matching_count' in task_tile],
      [['checkpoints', 'generations', 'id', 'images'],
       ['checkpoint', 'checkpoint_path', 'created_at', 'generation_id', 'mode'], True, True])
check('and a run\'s tile inside a task: its checkpoint, and its checkpoint\'s name',
      all('checkpoint' in t and 'checkpoint_name' in t for t in inside), True)


# The shared library has no task of two checkpoints: every level reads as
# before, the task tables named only by the first read and a task: search.
def statements(database, **params):
    """The SQL a request ran, statement by statement."""
    ran = []
    connection = database._get_connection()
    connection.set_trace_callback(ran.append)
    try:
        api.browse_page(database, **params)
    finally:
        connection.set_trace_callback(None)
    return ran


def task_reads(ran):
    return [s for s in ran if 'task_generations' in s and 'GROUP BY task_id HAVING COUNT(*) > 1) g' not in s]


plain = [statements(db, nsfw='all', tasks=True, group=g) for g in ('', 'model', 'day')]
check('no task of two checkpoints: no level reads the task tables but the first read',
      [len(task_reads(ran)) for ran in plain], [0, 0, 0])
check('and the first read runs only for a level of generations: not for a level of groups',
      [any('task_checkpoints' in s for s in ran) for ran in plain], [True, False, False])
several = db.generation_several_runs
db.generation_several_runs = lambda: True
forced = task_reads(statements(db, nsfw='all', tasks=True))
db.generation_several_runs = several
check('the check can fail: the join forced on is seen', len(forced) > 0, True)


# ------------------------------------------------------------ the work
def library(name, bases, batches=200):
    """`batches` batches of 10 images, 200 by default, one checkpoint for each of `bases` base models."""
    root = os.path.join(WORK, name)
    path, connection = generation_fixture.v36_database(root)
    checkpoints = []
    for b in range(bases):
        checkpoint = os.path.join(root, 'models', f'ck{b}.safetensors')
        generation_fixture.library_file(connection, checkpoint, version_id=b + 1, base_model=f'Base {b}')
        checkpoints.append(checkpoint)
    rows, images, files = [], [], []
    for number in range(1, batches + 1):
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


def steps_of(database, **params):
    """SQLite's steps for a first part of the level `params` names."""
    connection = database._get_connection()
    count = [0]

    def tick():
        count[0] += 1
    connection.set_progress_handler(tick, 1)
    try:
        api.browse_page(database, 'all', **params)
    finally:
        connection.set_progress_handler(None, 1)
    return count[0]


def with_tasks(database, batches):
    """A task of two checkpoints for each two batches (#401), its runs those batches: one tile each."""
    with database._cursor() as cursor:
        for task_id in range(1, batches // 2 + 1):
            cursor.execute("INSERT INTO tasks (id, install, mode, status, inputs, created_at) "
                           "VALUES (?, 'test', 'txt2img', 'completed', '{}', '2026-01-02')", (task_id,))
            cursor.executemany("INSERT INTO task_checkpoints (task_id, place, checkpoint) VALUES (?, ?, ?)",
                               [(task_id, 0, 'ck0'), (task_id, 1, 'ck1')])
            cursor.executemany("INSERT INTO task_generations (task_id, generation_id) VALUES (?, ?)",
                               [(task_id, 2 * task_id - 1), (task_id, 2 * task_id)])
    return database


# A part holds every group, as the tab's page of 100 tiles does.
gallery_module.TILE_PART = 100
two, fourteen = library('two_bases', 2), library('fourteen_bases', 14)
growth = (steps(fourteen) - steps(two)) / (2000 * 12)
# Classic joined the part before each image's base model was known, and
# looked it up again for every group, in each of three reads: 87.8 more steps
# for each image and each group added. Single pass works the key out once: 0.7.
check('7 times the groups, the same images: work added per image and group, under 5',
      (growth < 5, f'{growth:.1f} steps'), (True, f'{growth:.1f} steps'))

# The task key (#401): a task of two checkpoints for every two batches, 100
# tasks at 2,000 images and 400 at 8,000. The work per image keyed by task
# stays the work per image of today's read, at either size.
small, large = with_tasks(library('tasks_small', 2), 200), with_tasks(library('tasks_large', 2, 800), 800)
for reading in (tile_reading.SINGLE_PASS, tile_reading.CLASSIC):
    keyed = [read_as(reading, steps_of, d, tasks=True) / n for d, n in ((small, 2000), (large, 8000))]
    plain = [read_as(reading, steps_of, d) / n for d, n in ((small, 2000), (large, 8000))]
    tiles = read_as(reading, api.browse_page, large, 'all', tasks=True)['tiles']
    check(f'{reading}: keyed by task, every tile of the part a task\'s', {t['kind'] for t in tiles}, {'task'})
    check(f'{reading}: four times the images and tasks, the work per image keyed by task grows under 1.5 times',
          (keyed[1] / keyed[0] < 1.5, f'{keyed[0]:.0f} to {keyed[1]:.0f} steps'),
          (True, f'{keyed[0]:.0f} to {keyed[1]:.0f} steps'))
    check(f'{reading}: and under three times today\'s read per image, at four times the images',
          (keyed[1] / plain[1] < 3, f'{keyed[1]:.0f} against {plain[1]:.0f}'),
          (True, f'{keyed[1]:.0f} against {plain[1]:.0f}'))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
