"""
Files in another type's folder (#54): which they are, and a sync's walk
moving them into their own when - and only when - its box is ticked.

A VAE or a text encoder Civitai lists as a "Checkpoint" sat in
Stable-diffusion, where Forge offers it as a checkpoint. What a file is comes
from its header; here the headers are stood in for by storing the type a
walk would have read. A download filed by what it is: download_test.py.
"""
import io
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
import model_manager.db.database as dbmod                # noqa: E402
from modules import paths                                # noqa: E402  (webui_stub's)
from model_manager import model_dirs                     # noqa: E402
from model_manager.architecture import Architecture     # noqa: E402
from model_manager.hashing import read_hashes           # noqa: E402
from model_manager.identity_store import store_architecture  # noqa: E402
from model_manager.model_dirs import file_modified, misplaced_files  # noqa: E402
from model_manager.sync_service import SyncService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'misplaced')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
models = facts['models_dir']
paths.models_path = models


def place(folder, name, file_type, sha=None, sidecars=()):
    """A file in a folder, read by a walk as `file_type`."""
    path = os.path.join(models, folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, 'wb').write(b'\0' * 32)
    for suffix in sidecars:
        io.open(os.path.splitext(path)[0] + suffix, 'w').write('beside it')
    db.upsert_version({'file_path': path, 'file_name': name, 'file_extension': os.path.splitext(name)[1],
                       'has_civitai_data': bool(sha), 'file_hashes': {'sha256': sha} if sha else None})
    store_architecture(db, path, Architecture(None, None, False, False, file_type, 'read for the test'),
                       file_modified(path))
    return path


# ------------------------------------------------------------ where it belongs
vae = place(os.path.join('Stable-diffusion', '_Flux', 'x'), 'ae.safetensors', 'VAE', sha='A' * 64,
            sidecars=('.civitai.info', '.preview.png'))
belongs = os.path.join(models, 'VAE', '_Flux', 'x', 'ae.safetensors')
check('a VAE in Stable-diffusion belongs in VAE, its subfolders kept',
      model_dirs.proper_place(vae, 'VAE'), belongs)
check('a file in its own folder is in its place', model_dirs.proper_place(belongs, 'VAE'), None)
check('a file whose type is unknown belongs nowhere in particular', model_dirs.proper_place(vae, 'Unknown'), None)
check('nor does one outside the library\'s folders',
      model_dirs.proper_place(os.path.join(WORK, 'elsewhere', 'ae.safetensors'), 'VAE'), None)

unknown = place('Lora', 'mystery.safetensors', 'Unknown')
db.set_downloaded_at(vae)
db.set_pin(None, vae, True)
raw = sqlite3.connect(facts['db_path'])
raw.execute('INSERT INTO generation_files (file_path, image_id, generation_id) VALUES (?, 1, 1)', (vae,))
raw.commit()
raw.close()

listed = misplaced_files(db)
check('the sync dialog lists the VAE, where it goes, and what said so',
      [(f['path'], f['to'], f['file_type'], f['identified_by'], f['clash']) for f in listed],
      [(vae, belongs, 'VAE', 'read for the test', None)])

# ------------------------------------------------------------ not unasked
def walk(move_misplaced=False):
    """The walk every sync starts with; Civitai is never asked in it."""
    sync = SyncService(client=object())
    sync.walk_library(move_misplaced=move_misplaced)
    return sync.progress


progress = walk()
check('a walk without the box moves nothing', (os.path.exists(vae), progress.moved), (True, 0))

# ------------------------------------------------------------ asked
progress = walk(move_misplaced=True)
check('with the box, it moves the file into its type\'s folder', (os.path.exists(belongs), os.path.exists(vae)),
      (True, False))
check('with its .civitai.info and preview',
      [os.path.exists(os.path.splitext(belongs)[0] + s) for s in ('.civitai.info', '.preview.png')], [True, True])
check('counted', progress.moved, 1)
row = db.get_version(belongs)
check('its row goes with it - when it was downloaded, and what it is',
      (bool(row and row.get('downloaded_at')), (row or {}).get('file_type')), (True, 'VAE'))
check('and nothing is left under the old path', db.get_version(vae), None)
raw = sqlite3.connect(facts['db_path'])
check('its pin goes with it', raw.execute('SELECT file_path FROM pins WHERE file_path IS NOT NULL').fetchall(),
      [(belongs,)])
check('and the generations that used it',
      raw.execute('SELECT file_path FROM generation_files').fetchall(), [(belongs,)])
raw.close()
check('a file of unknown type stays where it is', os.path.exists(unknown), True)
check('and once moved, nothing is left to move', misplaced_files(db), [])

# ------------------------------------------------------------ never over a file
same = place('Stable-diffusion', 'twin.safetensors', 'VAE', sha='B' * 64)
place('VAE', 'twin.safetensors', 'VAE', sha='B' * 64)
different = place('Stable-diffusion', 'namesake.safetensors', 'VAE', sha='C' * 64)
place('VAE', 'namesake.safetensors', 'VAE', sha='D' * 64)
loose = place('Stable-diffusion', 'loose.safetensors', 'VAE')
io.open(os.path.join(models, 'VAE', 'loose.safetensors'), 'wb').write(b'not in the library')
check('a name already taken is said before anything is moved: the same file, a different one, or a file it cannot compare',
      sorted((os.path.basename(f['path']), f['clash']) for f in misplaced_files(db)),
      [('loose.safetensors', 'exists'), ('namesake.safetensors', 'different'), ('twin.safetensors', 'same')])
progress = walk(move_misplaced=True)
check('none of them is moved, or written over', [os.path.exists(p) for p in (same, different, loose)],
      [True, True, True])
check('and the walk says so', (progress.moved, progress.not_moved), (0, 3))
check('the count reaches the page', progress.to_dict()['not_moved'], 3)

# ------------------------------------------------------------ a row left for a file gone since (#126)
# A file deleted outside the app keeps its row until a walk's diff - which
# runs after the move. Moving onto its path is no clash, as nothing is there;
# its row once stopped the moved file's row following it, the file moved and
# its row, pin and generations left under the old path.
def link(path, *images):
    raw = sqlite3.connect(facts['db_path'])
    raw.executemany('INSERT INTO generation_files (file_path, image_id, generation_id) VALUES (?, ?, 1)',
                    [(path, image) for image in images])
    raw.commit()
    raw.close()


def under(path):
    """What names `path`, in any case: rows, pins, generations' images."""
    raw = sqlite3.connect(facts['db_path'])
    found = [[r[0] for r in raw.execute(f'SELECT {column} FROM {table} WHERE file_path = ? COLLATE NOCASE '
                                        f'ORDER BY 1', (path,))]
             for table, column in (('files', 'file_path'), ('pins', 'file_path'),
                                   ('generation_files', 'image_id'))]
    raw.close()
    return found


gone = place('VAE', 'hand_moved.safetensors', 'VAE', sha='F' * 64)
os.remove(gone)
db.set_pin(None, gone, True)
link(gone, 2, 3)
moving = place('Stable-diffusion', 'hand_moved.safetensors', 'VAE', sha='E' * 64)
db.set_pin(None, moving, True)
link(moving, 3, 4)
check('a row whose file is gone is no clash', [f['clash'] for f in misplaced_files(db) if f['path'] == moving],
      [None])
progress = walk(move_misplaced=True)
check('the file is moved onto it', (os.path.exists(gone), os.path.exists(moving)), (True, False))
check('counted, and nothing failed', (progress.moved, [e for e in progress.error_messages if 'could not move' in e]),
      (1, []))
check('one row, one pin, and the generations of both - the image both used, once',
      under(gone), [[gone], [gone], [2, 3, 4]])
check('the row is the moved file\'s', read_hashes((db.get_version(gone) or {}).get('file_hashes')).get('sha256'),
      'e' * 64)
check('nothing is left under the old path', under(moving), [[], [], []])

if model_dirs.os.path.normcase('A') == model_dirs.os.path.normcase('a'):
    other_case = place('VAE', 'Spelt.safetensors', 'VAE', sha='G' * 64)
    os.remove(other_case)
    link(other_case, 5)
    moving = place('Stable-diffusion', 'spelt.safetensors', 'VAE', sha='H' * 64)
    to = os.path.join(models, 'VAE', 'spelt.safetensors')
    progress = walk(move_misplaced=True)
    check('where case is ignored, a row spelt another way is the same path: one row is left, the moved file\'s',
          [under(to)[0], under(to)[2], read_hashes((db.get_version(to) or {}).get('file_hashes')).get('sha256')],
          [[to], [5], 'h' * 64])

# ------------------------------------------------------------ a row that cannot follow
# The file moves first, then its row. When the database refuses - locked by
# the other WebUI sharing it - the file goes back, rather than sit where no
# row names it.
locked = place('Stable-diffusion', 'locked.safetensors', 'VAE', sidecars=('.preview.png',))
locked_to = os.path.join(models, 'VAE', 'locked.safetensors')


def refuse(old_path, new_path):
    if old_path == locked:
        raise sqlite3.OperationalError('database is locked')
    return type(db).move_version(db, old_path, new_path)


db.move_version = refuse
try:
    progress = walk(move_misplaced=True)
finally:
    del db.move_version
check('the file and its preview are back where they were',
      [os.path.exists(p) for p in (locked, os.path.splitext(locked)[0] + '.preview.png', locked_to,
                                   os.path.splitext(locked_to)[0] + '.preview.png')],
      [True, True, False, False])
check('its row never left', (bool(db.get_version(locked)), db.get_version(locked_to)), (True, None))
check('and the walk says it could not move it',
      [e for e in progress.error_messages if 'could not move' in e], ['locked.safetensors: could not move it: database is locked'])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
