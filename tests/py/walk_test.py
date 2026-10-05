"""
The walk every sync starts with (SyncService.walk_library): what it finds on
disk, and what it forgets.

It never calls Civitai, and reads no sidecar - so everything here runs without
a network. Scan Disk did this until 0.48, beside reading the `.civitai.info`
another tool may have left; what a sync identifies, and the one case it reads
a sidecar, are sync_test.py's and hash_trust_test.py's.
"""
import io
import os
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
from modules import paths as _paths                      # noqa: E402  (webui_stub's)
from modules import shared as _shared                    # noqa: E402
from model_manager.model_dirs import file_modified, find_model_files, library_dirs  # noqa: E402
from model_manager.sync_service import SyncService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'walk')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
models_dir = facts['models_dir']
_paths.models_path = models_dir
sync = SyncService(client=object())      # Civitai is never asked in a walk


def walk():
    sync.walk_library()
    return set(db.get_all_version_paths())


# --------------------------------------------------------------- what it finds
found = find_model_files([models_dir])
check('it finds every model the fixture wrote', len(found), fixtures.VERSIONS)
check('and nothing that is not a model',
      all(f.lower().endswith(('.safetensors', '.ckpt', '.pt', '.pth', '.bin'))
          for f in found), True)

io.open(os.path.join(models_dir, 'VAE', 'notes.txt'), 'w').write('not a model')
check('a text file beside them is ignored', len(find_model_files([models_dir])),
      fixtures.VERSIONS)

check('a directory that does not exist yields nothing',
      find_model_files([os.path.join(WORK, 'nowhere')]), [])
check('and no directories at all yields nothing', find_model_files([]), [])

# ------------------------------------------------- a file with nothing beside it
plain = os.path.join(models_dir, 'Lora', 'no_sidecar.safetensors')
io.open(plain, 'wb').write(b'\0' * 128)
before = len(db.get_all_version_paths())
after = walk()
check('a new file is a row after a walk', (plain in after, len(after)), (True, before + 1))
stored = db.get_version(plain)
check('marked as having no Civitai data', stored['has_civitai_data'], False)
check('with its size from disk', stored['file_size'], 128)
check('and a level that keeps it visible', stored['nsfw_level'], 1)
# One way a modified time is written (#65): needs_check compares a stored one
# with a fresh one to decide whether a header is read again.
check('its modified time stored as file_modified() writes it', stored['file_modified'], file_modified(plain))

# ------------------------------------------------------------- embeddings
# The downloader files embeddings in --embeddings-dir; the scan never walked
# it, so it never saw them - and forgot each one a download had added, as a
# file gone from disk. Such a row was also stored under the folder as given,
# "models\\..\\embeddings", which is not how a walk finds it.
embeddings = os.path.join(models_dir, 'embeddings')
os.makedirs(embeddings, exist_ok=True)
_shared.cmd_opts.embeddings_dir = embeddings
check('the walk takes in the embeddings folder, as the WebUI names it',
      os.path.normcase(embeddings) in [os.path.normcase(d) for d in library_dirs()], True)

negative = os.path.join(embeddings, 'easy_negative.pt')
io.open(negative, 'wb').write(b'embedding')
as_given = os.path.join(models_dir, 'Lora', '..', 'embeddings', 'easy_negative.pt')
db.upsert_version({'file_path': as_given, 'file_name': 'easy_negative.pt', 'file_extension': '.pt'})
db.set_downloaded_at(as_given)
paths = walk()
check('a downloaded file stored under "..": still in the library after a walk, under its plain path',
      [as_given in paths, negative in paths], [False, True])
check('once, not twice', sum(1 for p in paths if p.endswith('easy_negative.pt')), 1)
check('and keeping what it had - when it was downloaded', bool((db.get_version(negative) or {}).get('downloaded_at')), True)
os.remove(negative)                  # the next walk forgets it, as a file gone

# ---------------------------------------------------------- and what is gone
os.remove(plain)
held = len(db.get_all_version_paths())
paths = walk()
check('a deleted file is dropped', (plain in paths, negative in paths), (False, False))
check('and nothing else goes with it', len(paths), held - 2)

# -------------------------------------------- only files gone from disk go
# Scan Disk once forgot every file it had not stored this pass: a cancelled
# scan dropped all the files it had not reached.
gone_while_cancelled = facts['local_only_paths'][0]
os.remove(gone_while_cancelled)
count = len(db.get_all_version_paths())
sync._cancel_requested = True
sync.walk_library()
sync._cancel_requested = False
check('a cancelled walk forgets nothing - it has not looked everywhere', len(db.get_all_version_paths()), count)
check('the next one does', gone_while_cancelled in walk(), False)

# ------------------------------------------ and what only they kept goes too
# A model row and its gallery outlive their last file otherwise: nothing
# shows them, and they pile up. A bookmark is the person's, and is kept.
def one_file_model(model_id, name):
    path = os.path.join(models_dir, 'Lora', name)
    io.open(path, 'wb').write(b'\0' * 64)
    db.upsert_civitai_model({'id': model_id, 'name': name, 'type': 'LORA'})
    db.upsert_version({'file_path': path, 'file_name': name, 'id': model_id + 1, 'model_id': model_id})
    return path


gone = one_file_model(71000, 'last_file.safetensors')
kept = one_file_model(72000, 'bookmarked_last_file.safetensors')
db.store_images(71001, 1, [{'id': 1, 'url': 'https://example.invalid/1.jpeg'}])
db.store_images(72001, 1, [{'id': 2, 'url': 'https://example.invalid/2.jpeg'}])
db.set_bookmark(72000, True)
os.remove(gone)
os.remove(kept)
walk()
check('a model whose last file is gone is forgotten, with its images',
      (db.get_civitai_model(71000), db.get_all_images_for_version(71001)), (None, []))
check('a bookmarked one keeps its model row, not the images of a file that is gone',
      (db.get_civitai_model(72000) is not None, db.get_all_images_for_version(72001)), (True, []))
check('and every other model still has its row',
      all(db.get_civitai_model(i) for i in facts['lora_ids'] + facts['checkpoint_ids']), True)

# --------------------------------------------- a walk knows nothing of Civitai
# A walk never touches what a sync stored: a synced X version stays X and
# identified, whatever is or is not beside the file.
X = 16
synced = os.path.join(models_dir, 'Lora', 'synced_x.safetensors')
io.open(synced, 'wb').write(b'\0' * 64)
db.upsert_version({'file_path': synced, 'file_name': 'synced_x.safetensors', 'file_extension': '.safetensors',
                   'id': 81001, 'nsfw_level': X})
walk()
check('a synced version walked over keeps its level', db.get_version(synced)['nsfw_level'], X)
check('and stays identified - the library still knows it on Civitai (#97)',
      db.get_version(synced)['has_civitai_data'], True)
fixtures.sidecar(synced, {"id": 81000, "name": "No Versions", "type": "LORA", "modelVersions": []})
walk()
check('a sidecar beside it changes nothing', (db.get_version(synced)['nsfw_level'], db.get_civitai_model(81000)),
      (X, None))

# ---------------------------------------------- one file, spelt two ways (#99)
# file_path is unique as SQL compares it - case and all - and Windows is not:
# a walk spelling a stored file in other case made a second row for it.
if os.path.normcase('A') == os.path.normcase('a'):
    spelt = os.path.join(models_dir, 'Lora', 'Spelt_Once.safetensors')
    io.open(spelt, 'wb').write(b'\0' * 64)
    db.upsert_version({'file_path': spelt, 'file_name': 'Spelt_Once.safetensors',
                       'file_extension': '.safetensors', 'id': 82001})
    other = os.path.join(os.path.dirname(spelt), 'SPELT_ONCE.safetensors')
    db.insert_missing_versions([{'file_path': other, 'file_name': 'SPELT_ONCE.safetensors'}])
    db.upsert_version({'file_path': other, 'file_name': 'SPELT_ONCE.safetensors',
                       'file_extension': '.safetensors'})
    rows = [p for p in db.get_all_version_paths() if p.lower() == spelt.lower()]
    check('a file stored, then met spelt in other case, is still one row, in its first spelling',
          rows, [spelt])
    check('and the second meeting landed on it', db.get_version(spelt)['id'], 82001)
    with db._cursor() as cursor:
        plan = ' '.join(str(row[-1]) for row in cursor.execute(
            "EXPLAIN QUERY PLAN SELECT file_path FROM files WHERE file_path = ? COLLATE NOCASE",
            (spelt,)).fetchall())
    check('looked up through an index, not a scan of every row', 'idx_files_path_nocase' in plan, True)

# ------------------------------------------------- every folder a download uses
# Downloads are filed into ESRGAN, ControlNet, Poses, Wildcards and more; the
# scan walked only Stable-diffusion, Lora and VAE, and its diff forgot each
# downloaded upscaler as a file gone from disk.
for name in ('ESRGAN', 'ControlNet', 'Wildcards'):
    os.makedirs(os.path.join(models_dir, name), exist_ok=True)
walked = [os.path.normcase(d) for d in library_dirs()]
check('the walk takes in every folder a download files into',
      [os.path.normcase(os.path.join(models_dir, n)) in walked for n in ('ESRGAN', 'ControlNet', 'Wildcards')],
      [True, True, True])

upscaler = os.path.join(models_dir, 'ESRGAN', '4x_upscaler.pth')
io.open(upscaler, 'wb').write(b'\0' * 64)
check('an upscaler in its folder is in the library after a walk', upscaler in walk(), True)

# A wildcard pack is a .zip, no model file a walk looks for; a folder template
# can point a download anywhere. A row whose file is still there stays.
pack = os.path.join(models_dir, 'Wildcards', 'pack.zip')
io.open(pack, 'wb').write(b'zip')
db.upsert_version({'file_path': pack, 'file_name': 'pack.zip', 'file_extension': '.zip'})
check('a downloaded file a walk does not look for keeps its row while it is on disk', pack in walk(), True)
os.remove(pack)
check('and loses it once the file is gone', pack in walk(), False)

# ------------------------------------------------------------------ cancelling
sync.cancel()
check('cancelling is remembered', sync._cancel_requested, True)
check('and progress is readable', isinstance(sync.progress.to_dict(), dict), True)

# ------------------------------------------------- what a path is shown from
# The pages show a path from the folder Forge was given for it on the command
# line, by its option, else from Forge's own folder (#133). Neo here is given
# the original Forge's folders; its embeddings' default is inside it.
import types                                              # noqa: E402
from model_manager.model_dirs import shown_roots          # noqa: E402
OTHER = os.path.join(WORK, 'other', 'webui')
NEO = os.path.join(WORK, 'neo')
given = types.SimpleNamespace(ckpt_dir=os.path.join(OTHER, 'models', 'Stable-diffusion'),
                              lora_dir=os.path.join(OTHER, 'models', 'Lora'),
                              lora_dirs=[os.path.join(OTHER, 'models', 'Lora', 'more')],
                              embeddings_dir=os.path.join(NEO, 'embeddings'))
check('each folder Forge was given, by its option, the longest first - an inner before its outer - then its own, unnamed',
      shown_roots(given, NEO),
      [('--ckpt-dir', os.path.abspath(os.path.join(OTHER, 'models', 'Stable-diffusion'))),
       ('--lora-dirs', os.path.abspath(os.path.join(OTHER, 'models', 'Lora', 'more'))),
       ('--lora-dir', os.path.abspath(os.path.join(OTHER, 'models', 'Lora'))),
       ('', os.path.abspath(NEO))])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
