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
raw.execute("INSERT INTO generation_resources (image_id, generation_id, role, position, name, file_path) "
            "VALUES (1, 1, 'vae', 0, 'ae', ?)", (vae,))
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
      raw.execute('SELECT file_path FROM generation_resources').fetchall(), [(belongs,)])
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
linked = iter(range(1, 1000))


def link(path, *images):
    raw = sqlite3.connect(facts['db_path'])
    raw.executemany("INSERT INTO generation_resources (image_id, generation_id, role, position, name, file_path) "
                    "VALUES (?, 1, 'other', ?, 'x', ?)", [(image, next(linked), path) for image in images])
    raw.commit()
    raw.close()


def under(path):
    """What names `path`, in any case: rows, pins, generations' images."""
    raw = sqlite3.connect(facts['db_path'])
    found = [[r[0] for r in raw.execute(f'SELECT DISTINCT {column} FROM {table} WHERE file_path = ? '
                                        f'COLLATE NOCASE ORDER BY 1', (path,))]
             for table, column in (('files', 'file_path'), ('pins', 'file_path'),
                                   ('generation_resources', 'image_id'))]
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

# ------------------------------------------------------------ side files another file shares (#388)
# demo.pt (a VAE) and demo.safetensors (a LoRA) in the LoRA folder share
# demo.civitai.info and demo.preview.png: moving the VAE leaves them with
# the LoRA that stays.
pair_lora = place('Lora', 'demo.safetensors', 'LORA', sidecars=('.civitai.info', '.preview.png'))
pair_vae = place('Lora', 'demo.pt', 'VAE')
pair_to = os.path.join(models, 'VAE', 'demo.pt')
progress = walk(move_misplaced=True)
check('the VAE is moved', (os.path.exists(pair_to), os.path.exists(pair_vae)), (True, False))
check('and the side files it shares stay beside the LoRA',
      [os.path.exists(os.path.splitext(pair_lora)[0] + s) for s in ('.civitai.info', '.preview.png')]
      + [os.path.exists(os.path.splitext(pair_to)[0] + s) for s in ('.civitai.info', '.preview.png')],
      [True, True, False, False])

# A file moved beside another file of its name, whose row cannot follow:
# the put-back takes back exactly what it moved. Worked out again, its side
# files would read as the other file's, and stay there beside it.
back_from = place('Stable-diffusion', 'back.pt', 'VAE', sidecars=('.preview.png',))
io.open(os.path.join(models, 'VAE', 'back.safetensors'), 'wb').write(b'another file of that name')
back_to = os.path.join(models, 'VAE', 'back.pt')


def refuse_back(old_path, new_path):
    if old_path == back_from:
        raise sqlite3.OperationalError('database is locked')
    return type(db).move_version(db, old_path, new_path)


db.move_version = refuse_back
try:
    progress = walk(move_misplaced=True)
finally:
    del db.move_version
check('the put-back brings its preview back with it, from beside the file of its name',
      [os.path.exists(back_from), os.path.exists(os.path.splitext(back_from)[0] + '.preview.png'),
       os.path.exists(back_to), os.path.exists(os.path.splitext(back_to)[0] + '.preview.png')],
      [True, True, False, False])

# A move refused because a side file's name is taken where it would go: the
# line says which file is in the way, not the model file's place.
from model_manager import console                         # noqa: E402
taken_from = place('Stable-diffusion', 'taken.pt', 'VAE', sidecars=('.preview.png',))
taken_preview = os.path.join(models, 'VAE', 'taken.preview.png')
io.open(taken_preview, 'w').write('a stray preview')
mark = console.said()
progress = walk(move_misplaced=True)
lines = [line['text'] for line in console.since(mark)[0] if 'Not moved' in line['text'] and 'taken.pt' in line['text']]
check('a side file in the way is named as what is in the way',
      [os.path.exists(taken_from), len(lines), lines and lines[0].endswith(f'{taken_preview} is already there')],
      [True, 1, True])

# A move that fails partway - here a rename refused with nothing copied -
# takes back what it had moved: the file and its other side files are where
# they were, its row still names them, and the walk says it could not move it.
partway = place('Stable-diffusion', 'partway.pt', 'VAE', sidecars=('.civitai.info', '.preview.png'))
partway_to = os.path.join(models, 'VAE', 'partway.pt')
real_move = model_dirs.shutil.move


def held_preview(source, destination):
    if source.endswith('partway.preview.png'):
        raise PermissionError(32, 'The process cannot access the file because it is being used by another process')
    return real_move(source, destination)


model_dirs.shutil.move = held_preview
try:
    progress = walk(move_misplaced=True)
finally:
    model_dirs.shutil.move = real_move
check('the file and its side files are back where they were, none left in the new folder',
      [os.path.exists(partway)] + [os.path.exists(os.path.splitext(partway)[0] + s) for s in ('.civitai.info', '.preview.png')]
      + [os.path.exists(partway_to), os.path.exists(os.path.splitext(partway_to)[0] + '.civitai.info')],
      [True, True, True, False, False])
check('its row still names it', (bool(db.get_version(partway)), db.get_version(partway_to)), (True, None))
check('and the walk says it could not move it',
      [e.startswith('partway.pt: could not move it:') for e in progress.error_messages if 'partway' in e], [True])

import shutil                                             # noqa: E402

# A side file another program holds, as Windows does it: the rename is
# refused, shutil.move copies the file, then cannot remove the original. The
# copy left in the new folder was in the way of every later move.
held = place('Stable-diffusion', 'held.pt', 'VAE', sidecars=('.civitai.info', '.preview.png'))
held_to = os.path.join(models, 'VAE', 'held.pt')


def copied_then_held(source, destination):
    if source.endswith('held.preview.png'):
        shutil.copy2(source, destination)
        raise PermissionError(32, 'The process cannot access the file because it is being used by another process')
    return real_move(source, destination)


model_dirs.shutil.move = copied_then_held
try:
    progress = walk(move_misplaced=True)
finally:
    model_dirs.shutil.move = real_move
check('a held side file: everything is back, and no copy of it is left in the new folder',
      [os.path.exists(held), os.path.exists(os.path.splitext(held)[0] + '.preview.png'), os.path.exists(held_to),
       os.path.exists(os.path.splitext(held_to)[0] + '.civitai.info'),
       os.path.exists(os.path.splitext(held_to)[0] + '.preview.png')],
      [True, True, False, False, False])

# A put-back that fails partway - the row could not follow, and one side
# file cannot go back - takes the model file back first and leaves only that
# side file, named: rolled back as a whole, the model file went to where no
# row names it.
pb = place('Stable-diffusion', 'pb.pt', 'VAE', sidecars=('.civitai.info', '.preview.png'))
pb_to = os.path.join(models, 'VAE', 'pb.pt')
pb_to_preview = os.path.splitext(pb_to)[0] + '.preview.png'


def refuse_pb(old_path, new_path):
    if old_path == pb:
        raise sqlite3.OperationalError('database is locked')
    return type(db).move_version(db, old_path, new_path)


def preview_stuck(source, destination):
    if source == pb_to_preview:
        raise PermissionError(32, 'in use')
    return real_move(source, destination)


db.move_version = refuse_pb
model_dirs.shutil.move = preview_stuck
try:
    progress = walk(move_misplaced=True)
finally:
    model_dirs.shutil.move = real_move
    del db.move_version
check('the model file is back where its row names it, the stuck preview left and named',
      [os.path.exists(pb), os.path.exists(os.path.splitext(pb)[0] + '.civitai.info'), os.path.exists(pb_to),
       os.path.exists(pb_to_preview), bool(db.get_version(pb)),
       [e.endswith(f'left at {pb_to_preview}') for e in progress.error_messages if e.startswith('pb.pt')]],
      [True, True, False, True, True, [True]])

# A move that fails partway and cannot take one file back says where it is.
mb = place('Stable-diffusion', 'mb.pt', 'VAE', sidecars=('.preview.png',))
mb_to = os.path.join(models, 'VAE', 'mb.pt')


def nothing_back(source, destination):
    if source.endswith('mb.preview.png') or source == mb_to:
        raise PermissionError(32, 'in use')
    return real_move(source, destination)


model_dirs.shutil.move = nothing_back
try:
    progress = walk(move_misplaced=True)
finally:
    model_dirs.shutil.move = real_move
check('a file it cannot take back is named in the walk\'s error',
      [os.path.exists(mb_to), [e.endswith(f'left at {mb_to}') for e in progress.error_messages if e.startswith('mb.pt')]],
      [True, [True]])

# A move into folders it had to make, failing partway, removes them again.
deep = place(os.path.join('Stable-diffusion', '_gone'), 'deep.pt', 'VAE', sidecars=('.preview.png',))
deep_folder = os.path.join(models, 'VAE', '_gone')


def deep_preview_refused(source, destination):
    if source.endswith('deep.preview.png'):
        raise PermissionError(32, 'in use')
    return real_move(source, destination)


model_dirs.shutil.move = deep_preview_refused
try:
    progress = walk(move_misplaced=True)
finally:
    model_dirs.shutil.move = real_move
check('a failed move removes the folders it made', [os.path.exists(deep), os.path.isdir(deep_folder)], [True, False])

# The model file itself held: copied, its removal refused - the copy goes,
# and nothing is left in the new folder.
held_model = place('Stable-diffusion', 'heldmodel.pt', 'VAE', sidecars=('.preview.png',))
held_model_to = os.path.join(models, 'VAE', 'heldmodel.pt')


def model_copied_then_held(source, destination):
    if source == held_model:
        shutil.copy2(source, destination)
        raise PermissionError(32, 'in use')
    return real_move(source, destination)


model_dirs.shutil.move = model_copied_then_held
try:
    progress = walk(move_misplaced=True)
finally:
    model_dirs.shutil.move = real_move
check('a held model file: no copy of it is left in the new folder',
      [os.path.exists(held_model), os.path.exists(held_model_to)], [True, False])

# The model file's old place taken before the put-back: it stays at the new
# place, and its side files stay with it rather than go back beside the file
# that now holds its old name.
taken_old = place('Stable-diffusion', 'takenold.pt', 'VAE', sidecars=('.civitai.info',))
taken_old_to = os.path.join(models, 'VAE', 'takenold.pt')


def refuse_and_take(old_path, new_path):
    if old_path == taken_old:
        io.open(taken_old, 'wb').write(b'another file, put there meanwhile')
        raise sqlite3.OperationalError('database is locked')
    return type(db).move_version(db, old_path, new_path)


db.move_version = refuse_and_take
try:
    progress = walk(move_misplaced=True)
finally:
    del db.move_version
taken_old_info = os.path.splitext(taken_old_to)[0] + '.civitai.info'
check('the model file stays at the new place with its side file, both named',
      [os.path.exists(taken_old_to), os.path.exists(taken_old_info),
       os.path.exists(os.path.splitext(taken_old)[0] + '.civitai.info'),
       [e.endswith(f'left at {taken_old_to}, {taken_old_info}') for e in progress.error_messages
        if e.startswith('takenold.pt')]],
      [True, True, False, [True]])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
