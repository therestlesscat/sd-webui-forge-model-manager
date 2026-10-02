"""
Files in another type's folder (#54): which they are, and Scan Disk moving
them into their own when - and only when - its box is ticked.

A VAE or a text encoder Civitai lists as a "Checkpoint" sat in
Stable-diffusion, where Forge offers it as a checkpoint. What a file is comes
from its header; here the headers are stood in for by storing the type a
scan would have read. A download filed by what it is: download_test.py.
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
from model_manager.identity_store import store_architecture  # noqa: E402
from model_manager.model_dirs import file_modified      # noqa: E402
from model_manager.scan_service import ScanService, misplaced_files  # noqa: E402

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
    """A file in a folder, read by a scan as `file_type`."""
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
check('Scan Disk\'s dialog lists the VAE, where it goes, and what said so',
      [(f['path'], f['to'], f['file_type'], f['identified_by'], f['clash']) for f in listed],
      [(vae, belongs, 'VAE', 'read for the test', None)])

# ------------------------------------------------------------ not unasked
scan = ScanService()
progress = scan.scan_models()
check('a scan without the box moves nothing', (os.path.exists(vae), progress.moved), (True, 0))

# ------------------------------------------------------------ asked
progress = scan.scan_models(move_misplaced=True)
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
progress = scan.scan_models(move_misplaced=True)
check('none of them is moved, or written over', [os.path.exists(p) for p in (same, different, loose)],
      [True, True, True])
check('and the scan says so', (progress.moved, sorted(os.path.basename(p) for p in progress.not_moved)),
      (0, ['loose.safetensors', 'namesake.safetensors', 'twin.safetensors']))
check('the count reaches the page', progress.to_dict()['not_moved'], 3)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
