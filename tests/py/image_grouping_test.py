"""
Sync images (#233): images with no generation text, grouped by what their
file names say and when they were saved - model_manager.image_sync and the
name reader in model_manager.image_text.

A group must never hold two models or two sets of settings; its size does
not matter. The gap two images may be apart is learnt from the library's
own images with text - how soon its settings changes come - so a calm
library learns the same gap as a busy one; a folder the images with text
show to be one press is one generation whatever its gaps.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()
PATTERN = '[model_name]-[sampler]-[steps]-[cfg]-[clip_skip]-[width]-[height]-[datetime]'
opts.samples_filename_pattern = PATTERN
opts.directories_filename_pattern = '[date]'
opts.save_images_add_number = True
opts.save_to_dirs = True

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager import generations, image_sync        # noqa: E402
from model_manager.image_sync import _Image, learn_gap   # noqa: E402
from model_manager.image_text import NamePattern         # noqa: E402
from model_manager.nsfw import PG, UNKNOWN               # noqa: E402

from PIL import Image                                    # noqa: E402
from PIL.PngImagePlugin import PngInfo                   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'image_grouping')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def parse(infotext):
    lines = infotext.split('\n')
    parsed = {'Prompt': lines[0]}
    for line in lines[1:]:
        for pair in line.split(', '):
            key, _, value = pair.partition(': ')
            parsed[key] = value
    return parsed


generations.parse_generation_parameters = parse

db, facts = fixtures.build(WORK)
dbmod._db_instance = db
raw = db._get_connection()
CHECKPOINT = facts['linked_paths'][0]
CHECKPOINT_NAME = os.path.splitext(os.path.basename(CHECKPOINT))[0]
raw.execute("UPDATE files SET file_type = 'Checkpoint' WHERE file_path = ?", (CHECKPOINT,))
raw.commit()

OUT = os.path.join(WORK, 'outputs')
BASE = time.mktime((2026, 3, 1, 12, 0, 0, 0, 0, -1))


def name(number, model='modelA', steps=25, at=0.0):
    stamp = time.strftime('%Y%m%d%H%M%S', time.localtime(BASE + at))
    return '%05d-%s-Euler a-%d-7-1-64-64-%s.png' % (number, model, steps, stamp)


def save(folder, file_name, text=None, at=0.0):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, file_name)
    info = PngInfo()
    if text:
        info.add_text('parameters', text)
    Image.new('RGB', (64, 64)).save(path, pnginfo=info)
    stamp = int((BASE + at) * 1e9)
    os.utime(path, ns=(stamp, stamp))
    return path


def text(seed, steps=25, cfg=7):
    return f'a prompt\nSteps: {steps}, Sampler: Euler a, CFG scale: {cfg}, Seed: {seed}, Size: 64x64'


def run(folder, group=True, level=UNKNOWN):
    sync = image_sync.ImageSync([{'path': folder}], level, group)
    sync.run()
    return sync.progress


def groups_in(folder):
    found = {}
    for path, gid in raw.execute("SELECT path, generation_id FROM generation_images WHERE path LIKE ? "
                                 "ORDER BY path", (folder + '%',)).fetchall():
        found.setdefault(gid, []).append(os.path.basename(path)[:5])
    return sorted(found.values())


# ------------------------------------------------------------ reading names
pattern = NamePattern(PATTERN, ['Euler a', 'Euler'], numbered=True)
read = pattern.read(os.path.splitext(name(12, model='my-model-v2', at=61))[0])
check('a name read back by Forge\'s pattern gives its fields and its time',
      (read['fields'], read['time'].strftime('%H:%M:%S')),
      ({'Model': 'my-model-v2', 'Sampler': 'Euler a', 'Steps': '25', 'CFG scale': '7', 'Clip skip': '1',
        'Size': '64x64'}, '12:01:01'))
check('a sampler Forge does not list is still read', (pattern.read('00012-m-DPM++ 2M SDE-30-7-2-64-64-20260301120000')
       or {}).get('fields', {}).get('Sampler'), 'DPM++ 2M SDE')
check('a name that does not fit reads as nothing', pattern.read('00012-holiday photo'), None)
check('a value that fails its check reads as nothing', pattern.read('00012-m-Euler a-x-7-1-64-64-20260301120000'), None)
check('the seed and the time are not what two images must share',
      [k for k, _ in read['same']], ['model_name', 'sampler', 'steps', 'cfg', 'clip_skip', 'width', 'height'])

# ------------------------------------------- names say two models: never joined
TWO = os.path.join(OUT, 'two_models')
save(TWO, name(1, 'modelA', at=0))
save(TWO, name(2, 'modelB', at=1))
save(TWO, name(3, 'modelB', at=2))
save(TWO, '00004-holiday photo.png', at=3)
save(TWO, '00005-holiday photo.png', at=4)
run(TWO)
check('two no-text images a second apart, their names naming two models, stay apart; a name that does not fit '
      'joins nothing', groups_in(TWO), [['00001'], ['00002', '00003'], ['00004'], ['00005']])

# ---------------------------------------------- the name gives the time and model
NAMED = os.path.join(OUT, '2026-03-01')
named = save(NAMED, name(10, CHECKPOINT_NAME, at=3600), at=999999)
run(NAMED)
row = raw.execute("SELECT g.created_at, r.file_path, d.meta, d.infotext FROM generation_images gi "
                  "JOIN generations g ON g.id = gi.generation_id "
                  "JOIN generation_resources r ON r.image_id = gi.id AND r.role = 'checkpoint' "
                  "JOIN generation_image_details d ON d.image_id = gi.id WHERE gi.path = ?", (named,)).fetchone()
check('the image\'s time is its name\'s, not the file\'s', row[0], '2026-03-01T13:00:00')
check('its [model_name] finds the library\'s checkpoint by file name', row[1], CHECKPOINT)
check('its details are what its name says, under Forge\'s names, with no text',
      ('"Steps": "25"' in (row[2] or ''), row[3]), (True, None))

# --------------------------------------------------------- group switched off
OFF = os.path.join(OUT, 'off')
for n in range(3):
    save(OFF, name(20 + n, at=n), at=n)
run(OFF, group=False)
check('with grouping off, each no-text image is a generation of its own', groups_in(OFF), [['00020'], ['00021'], ['00022']])

# ---------------------------------------------------------------- the gap
def image(at, settings, seed, number, text_=True, same=('m',)):
    return _Image(path='x%d.png' % number, root='r', source=1, mode='txt2img', size=1,
                  mtime_ns=int(at * 1e9), number=number, text='t' if text_ else None,
                  settings=settings, seed=seed, name={'same': same, 'fields': {}, 'time': None})


def library(changes, quiet_pairs):
    """Images with text: `changes` settings changes, the i-th 11 + i seconds
    after the image before it, and `quiet_pairs` images of one press, a
    second apart, before each."""
    images, at, number = [], 0.0, 0
    for i in range(changes):
        for _ in range(quiet_pairs):
            images.append(image(at, ('s', i), 100 * i + len(images), number))
            at, number = at + 1, number + 1
        at += 10 + i
        images.append(image(at, ('s', i + 1), 7000 + i, number))
        number += 1
    return {'f': images}


busy, calm = library(40, 2), library(40, 30)
check('the gap is the one below which 20% of the settings changes fall', learn_gap(busy), 18.0)
check('a calm library learns the same gap as a busy one', learn_gap(calm), learn_gap(busy))
check('with fewer than 20 settings changes, nothing is learnt', learn_gap(library(19, 2)), None)
check('a change the name shows is not counted: it never joins anyway',
      learn_gap({'f': [image(i * 50, ('s', i), i, i, same=('m', i)) for i in range(40)]}), None)

# ---------------------------------------- learnt in the sync, kept, used later
LEARN = os.path.join(OUT, 'learn')
at, number = 0.0, 100
for i in range(25):
    save(LEARN, name(number, at=at), text(1000 * i, steps=25, cfg=7 + i), at=at)
    at, number = at + 20 + i, number + 1
for n in range(4):
    save(LEARN, name(number + n, at=at + n * 4), at=at + n * 4)
save(LEARN, name(number + 4, at=at + 200), at=at + 200)
progress = run(LEARN)
check('a sync with at least 20 settings changes learns its gap from them', (progress.gap_from, progress.gap),
      ('learnt', 24.0))
check('no-text images within the gap join; one past it does not',
      [len(g) for g in groups_in(LEARN) if g[0] >= '%05d' % number], [4, 1])
check('the gap is kept for this WebUI', float(db.get_info(image_sync._GAP_KEY)), 24.0)
LATER = os.path.join(OUT, 'later')
save(LATER, name(1, at=0), at=0)
save(LATER, name(2, at=20), at=20)
progress = run(LATER)
check('a sync with too few changes uses the gap last learnt', (progress.gap_from, groups_in(LATER)),
      ('last learnt', [['00001', '00002']]))
db.set_info(image_sync._GAP_KEY, None)
NEVER = os.path.join(OUT, 'never')
save(NEVER, name(1, at=0), at=0)
save(NEVER, name(2, at=5000), at=5000)
progress = run(NEVER)
check('with no gap ever learnt, names alone decide', (progress.gap_from, groups_in(NEVER)),
      ('names alone', [['00001', '00002']]))

# --------------------------------------------------- a folder that is one press
TASKS = os.path.join(OUT, 'tasks')
for t in range(20):
    folder = os.path.join(TASKS, '2026-03-02', 'modelA', '%06d' % (100000 + t))
    for n in range(2):
        save(folder, name(n, at=t * 1000 + n), text(50000 + t * 10 + n), at=t * 1000 + n)
lone = os.path.join(TASKS, '2026-03-02', 'modelA', '235738')
for n in range(5):
    save(lone, name(n, at=90000 + n * 100), at=90000 + n * 100)
db.set_info(image_sync._GAP_KEY, '10.0')
run(TASKS)
check('in a folder of a shape the images with text show to be one press, no-text images join whatever the gap',
      groups_in(lone), [['00000', '00001', '00002', '00003', '00004']])
FEW = os.path.join(OUT, 'few')
for t in range(3):
    folder = os.path.join(FEW, '2026-03-03', 'modelA', '%06d' % (100000 + t))
    save(folder, name(0, at=t * 1000), text(60000 + t), at=t * 1000)
few = os.path.join(FEW, '2026-03-03', 'modelA', '235738')
for n in range(2):
    save(few, name(n, at=90000 + n * 100), at=90000 + n * 100)
run(FEW)
check('a shape with fewer than 20 such folders is not trusted: the gap decides', groups_in(few), [['00000'], ['00001']])

print('image_grouping: %d failure(s)' % len(fails))
for f in fails:
    print('FAIL ' + f)
sys.exit(1 if fails else 0)
