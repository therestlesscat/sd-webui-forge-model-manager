"""
Thumbnails of your generations (#5): model_manager.thumbnails, Sync images'
pass that makes them, the recorder's, the routes that serve and forget them
- over images this suite writes, into the fixture library.

Each situation is one the plan names: made only when asked, 450 pixels tall,
as WebP; where each place puts them; a changed image shows its full file
until made again; Force sync keeps them; every removal the app makes takes
them with it; the page is told a thumbnail only while it serves the file.
"""
import json
import os
import sqlite3
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

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager import generations, image_sync, thumbnails  # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.db.database import SCHEMA_VERSION     # noqa: E402

from PIL import Image                                    # noqa: E402
from PIL.PngImagePlugin import PngInfo                   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'thumbnails')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
raw = db._get_connection()
# The database the settings name: the default folder is beside it, never
# beside the repository's own.
opts.model_manager_database_path = facts['db_path']

# Settings saved through Forge's own way, as Start saves the dialog's.
def _set(key, value, *args, **kwargs):
    if getattr(opts, key, None) == value:
        return False
    setattr(opts, key, value)
    return True
opts.set = _set
opts.save = lambda filename: None
sys.modules['modules.shared'].config_filename = os.path.join(WORK, 'config.json')

app = FastAPI()
setup_api(app)
client = TestClient(app)

OUT = os.path.join(WORK, 'outputs')
DEFAULT = os.path.join(WORK, 'thumbnails')


def save(folder, name, size=(640, 960), mode='RGB', text=None):
    """An image file, with no generation text: Forge's parser is not here."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    color = (200, 30, 30, 128) if mode == 'RGBA' else (200, 30, 30)
    info = PngInfo()
    if text:
        info.add_text('parameters', text)
    Image.new(mode, size, color).save(path, pnginfo=info)
    return path


def record(paths):
    """One generation the recorder wrote, of these images."""
    return db.record_generation({'created_at': '2026-01-01T00:00:00', 'mode': 'txt2img',
                                 'image_count': len(paths)},
                                [{'position': n, 'path': p, 'infotext': 'x'} for n, p in enumerate(paths)],
                                [[] for _ in paths])


def run(folders=(), make=True, force=False):
    sync = image_sync.ImageSync([{'path': f, 'key': None} for f in folders], force=force,
                                make_thumbnails=make)
    sync.run()
    return sync.progress


def row(path):
    return db.thumbnail_rows([path]).get(path.lower())


def made_for(path):
    """The thumbnail file made for an image, or '' - so a break fails a
    check here rather than ending the suite."""
    return (row(path) or {}).get('thumbnail') or ''


def image_id(path):
    return raw.execute("SELECT id FROM generation_images WHERE path = ? COLLATE NOCASE", (path,)).fetchone()[0]


def page_image(path):
    """The image as the page gets it, through the route that reads one."""
    found = db.get_generation_images([image_id(path)])
    from model_manager.api.generations import _image
    return _image(next(iter(found.values())))


# --------------------------------------------------------------- v39's table
columns = [r[1] for r in raw.execute("PRAGMA table_info(image_thumbnails)").fetchall()]
check('v39 adds image_thumbnails: the image\'s path, its thumbnail, its size and time',
      columns, ['path', 'thumbnail', 'size', 'mtime_ns'])

# A v38 database comes up to v39, its rows untouched.
OLD = os.path.join(WORK, 'v38.db')
old = fixtures.ModelsDatabase(extension_dir=ROOT, custom_db_path=OLD)
old.record_generation({'created_at': '2026-01-01T00:00:00', 'mode': 'txt2img', 'image_count': 1},
                      [{'position': 0, 'path': 'C:\\x.png', 'infotext': 'x'}], [[]])
old._get_connection().close()
with sqlite3.connect(OLD) as c:
    c.execute("DROP TABLE image_thumbnails")
    c.execute("UPDATE schema_info SET value = '38' WHERE key = 'version'")
migrated = fixtures.ModelsDatabase(extension_dir=ROOT, custom_db_path=OLD)
mc = migrated._get_connection()
check('v38 migrates on: the table is there, the version says the latest, the image is kept',
      (bool(mc.execute("SELECT name FROM sqlite_master WHERE name = 'image_thumbnails'").fetchone()),
       mc.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()[0],
       mc.execute("SELECT COUNT(*) FROM generation_images").fetchone()[0]),
      (True, str(SCHEMA_VERSION), 1))
mc.close()

# ------------------------------------------------------------ the settings
check('on unless turned off, kept in a folder, every processor',
      (thumbnails.enabled(), thumbnails.place(), thumbnails.threads()),
      (True, thumbnails.IN_FOLDER, os.cpu_count() or 1))
check('the default folder is beside the database the settings name', thumbnails.folder(), DEFAULT)
opts.model_manager_thumbnail_threads = 3
check('a number set is the number made at once', thumbnails.threads(), 3)
opts.model_manager_thumbnail_threads = 0

# --------------------------------------------------- a sync makes them, asked
A = os.path.join(OUT, 'a')
held = save(A, '00001-held.png')
record([held])
new = save(A, '00002-new.png')
progress = run([A], make=False)
check('a sync without the box makes none', (progress.state, row(held), row(new)), ('done', None, None))

progress = run([A])
made = row(held) or {'thumbnail': '', 'size': None, 'mtime_ns': None}
check('a sync with the box makes one for an image it already held',
      bool(made['thumbnail'] and os.path.isfile(made['thumbnail'])), True)
check('... and for the image it just brought', bool(row(new) and row(new)['thumbnail']), True)
check('the progress counts them', (progress.state, progress.thumbs_total, progress.thumbs_made), ('done', 2, 2))
if made['thumbnail']:
    with Image.open(made['thumbnail']) as t:
        check('450 pixels tall, its shape kept, WebP', (t.height, t.width, t.format), (450, 300, 'WEBP'))
check('in the folder, under its first two letters, named by a hash of the path and the height',
      (os.path.dirname(os.path.dirname(made['thumbnail'])) == DEFAULT,
       os.path.basename(made['thumbnail']).endswith('_450.webp')), (True, True))
stat = os.stat(held)
check('the record holds the image\'s size and time', (made['size'], made['mtime_ns']),
      (stat.st_size, stat.st_mtime_ns))

progress = run([A])
check('a second sync makes none: each is current', (progress.thumbs_total, progress.thumbs_made), (0, 0))

# -------------------------------------------- what the page and the route get
image = page_image(held)
check('the page gets the thumbnail\'s address, with the file\'s size and time',
      image['thumb'], f"/model-manager/generations/images/{image_id(held)}/thumb?v={stat.st_size}-{stat.st_mtime_ns}")
answer = client.get(image['thumb'] or f'/model-manager/generations/images/{image_id(held)}/thumb')
check('the route serves the thumbnail, for a year',
      (answer.status_code, answer.headers.get('content-type'), answer.headers.get('cache-control')),
      (200, 'image/webp', 'public, max-age=31536000, immutable'))
check('... the file the record names', answer.content,
      open(made['thumbnail'], 'rb').read() if made['thumbnail'] else 'no thumbnail')
check('an unknown image is a 404', client.get('/model-manager/generations/images/999999/thumb').status_code, 404)

# A changed image: its full file until a sync makes it again.
time.sleep(0.01)
save(A, '00001-held.png', size=(640, 900))
image = page_image(held)
check('a changed image is not given its old thumbnail', image['thumb'], None)
answer = client.get(f'/model-manager/generations/images/{image_id(held)}/thumb')
check('the route sends the full file instead', answer.content, open(held, 'rb').read())
progress = run([A])
check('the next sync with the box makes it again', (progress.thumbs_made, (row(held) or {}).get('size')),
      (1, os.path.getsize(held)))

# A thumbnail deleted by hand: made again, and meanwhile the full file.
if made_for(new):
    os.remove(made_for(new))
check('a thumbnail gone from disk is not offered', page_image(new)['thumb'], None)
check('... and a sync makes it again', run([A]).thumbs_made, 1)

# --------------------------------------------- what needs none, what fails
B = os.path.join(OUT, 'b')
small = save(B, '00003-small.png', size=(300, 450))
alpha = save(B, '00004-alpha.png', mode='RGBA')
broken = os.path.join(B, '00005-broken.png')
open(broken, 'wb').write(b'not an image at all')
record([small, alpha, broken])
progress = run([])
check('an image no taller than 450 gets none, and is not tried again',
      (bool(row(small)), made_for(small), page_image(small)['thumb']), (True, '', None))
check('one Pillow cannot read gets no record, and is reported',
      (row(broken), any('00005-broken.png' in e for e in progress.errors)), (None, True))
if made_for(alpha):
    with Image.open(made_for(alpha)) as t:
        check('transparency is kept', (t.mode, t.getpixel((0, 0))[3]), ('RGBA', 128))
else:
    check('transparency is kept', 'no thumbnail', 'a thumbnail')
check('a sync with no folder ticked still makes them', progress.thumbs_made, 1)
progress = run([])
check('the next sync tries the unreadable one again, and the small one not',
      (progress.thumbs_total, progress.error_count), (1, 1))
# Out of the library, so the counts below are the situations' own.
db.delete_generation_image(image_id(broken))

# ----------------------------------------------------- beside each image
opts.model_manager_thumbnails_place = thumbnails.BESIDE
C = os.path.join(OUT, 'c')
beside = save(C, '00006-beside.png')
run([C])
check('beside each image: in .thumbnails, by its file name and the height',
      made_for(beside), os.path.join(C, '.thumbnails', '00006-beside.png_450.webp'))
check('the old place\'s thumbnails still serve', page_image(new)['thumb'] is not None)
check('Sync images\' walk skips .thumbnails',
      [os.path.basename(p) for p, _, _ in image_sync.walk(C)], ['00006-beside.png'])
check('... and the thumbnail folder, wherever it is',
      thumbnails.is_thumbnail_folder(DEFAULT) and not thumbnails.is_thumbnail_folder(C), True)
opts.model_manager_thumbnails_place = thumbnails.IN_FOLDER

# ------------------------------------------------------------- Force sync
before = {p: made_for(p) for p in (held, new, beside)}
ids_before = {p: image_id(p) for p in (held, new, beside)}
progress = run([A, C], force=True)
check('Force sync writes the synced rows anew, with new ids',
      any(image_id(p) != ids_before[p] for p in (new, beside)), True)
check('... and keeps every thumbnail, made none again',
      ({p: made_for(p) for p in before}, all(before.values()), progress.thumbs_made), (before, True, 0))

# ---------------------------------------------------------------- the recorder
D = os.path.join(OUT, 'd')
fresh = save(D, '00007-fresh.png')
opts.model_manager_thumbnails = False
thumbnails.for_recorded(db, [fresh])
check('the recorder makes none with the setting off', row(fresh), None)
opts.model_manager_thumbnails = True
thumbnails.for_recorded(db, [fresh])
check('with it on, one for the image it recorded', bool(made_for(fresh)), True)
opts.model_manager_thumbnails = False

# ------------------------------------------------------------ removing images
E = os.path.join(OUT, 'e')
one = save(E, '00008-one.png')
two = save(E, '00009-two.png')
three = save(E, '00010-three.png')
gid = record([one, two])
record([three])
run([])
files = {p: made_for(p) for p in (one, two, three)}
check('the three to remove have thumbnails', all(files.values()), True)
answer = client.post(f'/model-manager/generations/images/{image_id(one)}/delete', data={'delete_files': 'false'})
check('deleting an image removes its thumbnail and record',
      (answer.status_code, row(one), bool(files[one]) and os.path.exists(files[one])), (200, None, False))
client.post(f'/model-manager/generations/{gid}/delete', data={'delete_files': 'false'})
check('deleting a batch, keeping its files, removes theirs',
      (row(two), bool(files[two]) and os.path.exists(files[two])), (None, False))
client.post('/model-manager/generations/delete-many', data={'image_ids': str(image_id(three))})
check('Select\'s Delete removes theirs',
      (row(three), bool(files[three]) and os.path.exists(files[three])), (None, False))

# An image two rows name keeps its thumbnail until the last goes.
twice = save(E, '00011-twice.png')
first_gid = record([twice])
record([twice])
run([])
client.post(f'/model-manager/generations/{first_gid}/delete', data={'delete_files': 'false'})
check('a thumbnail another row still names stays', bool(made_for(twice) and os.path.exists(made_for(twice))))

# Remove folder: the folder's synced images go, and their thumbnails.
F = os.path.join(OUT, 'f')
synced = save(F, '00012-synced.png')
opts.model_manager_image_folders = F
run([F])
made_file = made_for(synced)
removed, why = image_sync.remove_folder(db, F)
check('Remove folder removes its images\' thumbnails and records',
      (why, removed, row(synced), bool(made_file), os.path.exists(made_file)), (None, 1, None, True, False))

# The folders thumbnails were made into go with the last of them, once empty;
# the image's own folder, and a folder the user named, stay.
opts.model_manager_thumbnails_place = thumbnails.BESIDE
I, J = os.path.join(OUT, 'i'), os.path.join(OUT, 'j')
alone = save(I, '00014-alone.png')
kept, gone = save(J, '00015-kept.png'), save(J, '00016-gone.png')
for each in (alone, kept, gone):
    record([each])
run([])
client.post(f'/model-manager/generations/images/{image_id(alone)}/delete', data={'delete_files': 'false'})
client.post(f'/model-manager/generations/images/{image_id(gone)}/delete', data={'delete_files': 'false'})
check('beside each image, an emptied .thumbnails goes, the image\'s folder stays; one still holding one stays',
      (os.path.isdir(os.path.join(I, '.thumbnails')), os.path.isdir(I), os.path.isdir(os.path.join(J, '.thumbnails'))),
      (False, True, True))

NAMED = os.path.join(WORK, 'named thumbnails')
opts.model_manager_thumbnails_place = thumbnails.IN_FOLDER
opts.model_manager_thumbnails_folder = NAMED
K = os.path.join(OUT, 'k')
named = save(K, '00017-named.png')
record([named])
run([])
shard = os.path.dirname(made_for(named))
client.post(f'/model-manager/generations/images/{image_id(named)}/delete', data={'delete_files': 'false'})
check('in a folder named, its emptied two-letter folder goes, the named folder stays',
      (os.path.dirname(shard) == NAMED, os.path.isdir(shard), os.path.isdir(NAMED)), (True, False, True))

# The default folder too, made for this alone: beside another database.
opts.model_manager_thumbnails_folder = ''
opts.model_manager_database_path = os.path.join(WORK, 'other', 'models.db')
L = os.path.join(OUT, 'l')
lone = save(L, '00018-lone.png')
record([lone])
opts.model_manager_thumbnails = True
thumbnails.for_recorded(db, [lone])
opts.model_manager_thumbnails = False
lone_made = made_for(lone)
db.delete_generation_image(image_id(lone))
thumbnails.forget(db, [lone])
other_default = os.path.join(WORK, 'other', 'thumbnails')
check('the default folder, emptied, goes with its two-letter folder',
      (lone_made.startswith(other_default), os.path.exists(lone_made), os.path.isdir(other_default)),
      (True, False, False))
opts.model_manager_database_path = facts['db_path']

# ---------------------------------------------------------- the dialog's routes
answer = client.get('/model-manager/generations/sync/folders').json()
check('the dialog is told the box, the place, the folder named and the default',
      (answer['thumbnails'], answer['thumbnails_place'], answer['thumbnails_folder'],
       answer['thumbnails_default_folder']), (False, thumbnails.IN_FOLDER, '', DEFAULT))
G = os.path.join(OUT, 'g')
waiting = save(G, '00013-waiting.png')
record([waiting])
answer = client.get('/model-manager/generations/sync/estimate').json()
check('the estimate counts the images without a thumbnail', answer['thumbnails'], 1)

OWN = os.path.join(WORK, 'own thumbnails')
opts.model_manager_thumbnails_place = thumbnails.BESIDE
answer = client.post('/model-manager/generations/sync', data={
    'folders': '[]', 'make_thumbnails': 'true', 'place': thumbnails.IN_FOLDER, 'folder': OWN})
check('Start with the box and no folder ticked runs', answer.status_code, 200)
for _ in range(200):
    state = client.get('/model-manager/generations/sync/progress').json().get('progress') or {}
    if state.get('is_complete'):
        break
    time.sleep(0.05)
check('Start saves the box, the place and the folder to the settings',
      {k: getattr(opts, k, None) for k in (thumbnails.ENABLED_SETTING, thumbnails.PLACE_SETTING,
                                           thumbnails.FOLDER_SETTING)},
      {thumbnails.ENABLED_SETTING: True, thumbnails.PLACE_SETTING: thumbnails.IN_FOLDER,
       thumbnails.FOLDER_SETTING: OWN})
check('... and makes them in the folder named', made_for(waiting).startswith(OWN), True)
answer = client.post('/model-manager/generations/sync', data={'folders': '[]', 'make_thumbnails': 'true',
                                                              'folder': 'not\\a\\full\\path'})
check('a folder that is no full path is refused, saying why',
      (answer.status_code, 'full path' in answer.json().get('error', '')), (400, True))

# -------------------------------------------------------------- cancelling
H = os.path.join(OUT, 'h')
many = [save(H, '%05d-m.png' % (100 + n)) for n in range(40)]
record(many)
opts.model_manager_thumbnail_threads = 1
sync = image_sync.ImageSync([], make_thumbnails=True)
original = thumbnails.CHUNK
thumbnails.CHUNK = 5
seen = []
real_record = db.record_thumbnails
def counting(entries):
    real_record(entries)
    seen.append(len(entries))
    if len(seen) == 2:
        sync.cancel()
db.record_thumbnails = counting
sync.run()
db.record_thumbnails = real_record
thumbnails.CHUNK = original
opts.model_manager_thumbnail_threads = 0
kept = [p for p in many if made_for(p)]
check('Cancel stops between chunks, keeping those made with their records',
      (sync.progress.state, len(kept), all(os.path.isfile(made_for(p)) for p in kept)),
      ('cancelled', 10, True))

if fails:
    print('FAILED %d check(s):' % len(fails))
    for f in fails:
        print(' - ' + f)
    sys.exit(1)
print('thumbnails_test: all checks passed')
