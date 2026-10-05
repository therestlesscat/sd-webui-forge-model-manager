"""
Every sync starts with a walk of the library (SyncService.walk_library) -
what Scan Disk did, but for reading the sidecars: a new file gets a row and
its header read, a changed one its size and date and its header again, the
rows of files gone from disk are forgotten with what only they kept, a file
in another type's folder moves when its box is ticked - and the files
Civitai has never been asked about are hashed and looked up, whatever the
sync's scope.

The headers are stood in for: what a file "is" comes from its name.
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
import model_manager.sync_service as sync_module         # noqa: E402
from modules import paths                                # noqa: E402  (webui_stub's)
from model_manager.architecture import Architecture     # noqa: E402
from model_manager.civitai import CivitaiNotFoundError, TokenBucketRateLimiter  # noqa: E402
from model_manager.sync_estimates import files_to_hash  # noqa: E402
from model_manager.sync_service import SyncService      # noqa: E402

WORK = os.path.join(TESTS, 'work', 'sync_walk')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
models = facts['models_dir']
paths.models_path = models
base = os.path.basename


# ------------------------------------------------------------ the stand-ins
read = []        # whose header was read

# Each file is what its folder is for - a Checkpoint not taken by Forge's
# detector, which is never moved - but one named for a VAE is a VAE.
FOLDER_TYPE = {'Stable-diffusion': 'Checkpoint', 'Lora': 'LORA', 'VAE': 'VAE'}

def identify(path):
    name = base(path).lower()
    read.append(base(path))
    if 'broken' in name:
        raise OSError('a header that cannot be read')
    kind = 'VAE' if 'vae' in name else FOLDER_TYPE[base(os.path.dirname(path))]
    return Architecture(None, None, False, False, kind, 'read for the test')

sync_module.identify = identify


class Client:
    """Civitai, knowing none of these files and none of these models."""

    def __init__(self):
        self.asked = []
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def get_model_by_hash(self, value):
        self.asked.append(('by_hash', value))
        raise CivitaiNotFoundError('no such hash')

    def get_models_by_ids(self, ids):
        self.asked.append(('models', list(ids)))
        return {}

    def get_checkpoint_types(self, ids):
        return {}


hashed = []      # whose bytes were read, by path

def service():
    sync = SyncService(client=Client())
    real = sync.calculate_hashes
    sync.calculate_hashes = lambda path: (hashed.append(path), real(path))[1]
    return sync


def write(folder, name, size=64):
    path = os.path.join(models, folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, 'wb').write(b'\0' * size)
    return path


def raw():
    connection = sqlite3.connect(facts['db_path'])
    connection.row_factory = sqlite3.Row
    return connection


def orphans():
    """Versions no file names, and models no version is of: what a prune forgets."""
    with raw() as c:
        return (c.execute("SELECT COUNT(*) FROM versions WHERE id NOT IN "
                          "(SELECT version_id FROM files WHERE version_id IS NOT NULL)").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM models WHERE COALESCE(is_bookmarked, 0) = 0 AND id NOT IN "
                          "(SELECT model_id FROM versions WHERE model_id IS NOT NULL)").fetchone()[0])


LINKED = facts['linked_paths']
LOCAL = facts['local_only_paths']
NEW = write('Lora', 'new_one.safetensors')
GONE = LINKED[-1]
os.remove(GONE)
CHANGED = LOCAL[0]
io.open(CHANGED, 'wb').write(b'\0' * 4096)

# --------------------------------------------------- what every sync will hash
before = files_to_hash()
check('the dialog is told what every sync will read in full: the new file and the never-asked ones',
      before['files'], 1 + len(LOCAL))
check('with their size', before['bytes'],
      sum(os.path.getsize(p) for p in [NEW] + LOCAL))

# -------------------------------------------------------- a metadata sync walks
sync = service()
progress = sync.sync_metadata(model_paths=[LINKED[0]])
check('a metadata sync of one model still walks the whole library: the new file has a row',
      db.get_version(NEW) is not None)
check('and is counted', progress.added, 1)
check('the file gone from disk is forgotten', db.get_version(GONE), None)
check('and counted', progress.removed, 1)
check('with what only it kept', orphans(), (0, 0))
check('a changed file has its new size', db.get_version(CHANGED)['file_size'], 4096)
check('every header not read yet is read, the new file\'s among them',
      'new_one.safetensors' in read and len(read) == len(LINKED) - 1 + len(LOCAL) + 1, True)
check('and stored', db.get_version(NEW)['file_type'], 'LORA')
check('the new file and the never-asked ones are hashed, whatever the scope',
      sorted(map(base, hashed)), sorted(base(p) for p in [NEW] + LOCAL))
# ...as is the one model refreshed, which this Civitai does not know either.
check('and looked up', progress.not_found, 1 + len(LOCAL) + 1)
check('no identified file is hashed', set(hashed) & set(LINKED), set())
check('and nothing went wrong', (progress.errors, progress.is_complete), (0, True))
check('after it, nothing is left to hash', files_to_hash()['files'], 0)

# ------------------------------------------------------------ and again: quiet
read.clear()
hashed.clear()
sync = service()
progress = sync.sync_metadata()
check('a second sync reads no header: nothing changed', read, [])
check('and hashes nothing: every file has been asked about', hashed, [])
check('and adds and removes nothing', (progress.added, progress.removed), (0, 0))
# The panel's last line: the summary is said before the sync is complete, so
# the page's last poll, which sees it complete, reads it too.
from model_manager import console                        # noqa: E402
lines, _ = console.since(progress.log_from)
check('a sync\'s log, from where it began, ends with its summary',
      bool(lines) and lines[-1]['text'].startswith('Metadata sync complete'), True)
sync = service()
walked = sync.walk_library()
# Said before the sync has a total of its own: the page shows it alone.
check('the walk says how far it has looked, of every file it found',
      sync.progress.current_model, 'Reading your model folders: %d/%d' % (len(walked), len(walked)))

# ------------------------------------------------------- every header, if asked
sync = service()
progress = sync.sync_metadata(reread_headers=True)
check('"Read every file\'s header again" reads every one', len(read), len(LINKED) - 1 + len(LOCAL) + 1)

# ------------------------------------------- a header that cannot be read
read.clear()
BROKEN = write('Lora', 'broken_header.safetensors')
progress = service().sync_metadata()
check('a header that cannot be read fails that file, not the sync',
      (read, progress.is_complete, progress.errors), (['broken_header.safetensors'], True, 0))
check('which keeps its row', db.get_version(BROKEN) is not None)

# --------------------------------------------- a file in another type's folder
VAE = write('Stable-diffusion', 'some_vae.safetensors')
OWN = os.path.join(models, 'VAE', 'some_vae.safetensors')
progress = service().sync_metadata()
check('a VAE in Stable-diffusion stays where it is unless asked', (os.path.exists(VAE), progress.moved), (True, 0))
# One that arrives now is moved by the walk before it is hashed.
FRESH_VAE = write('Stable-diffusion', 'fresh_vae.safetensors')
hashed.clear()
progress = service().sync_metadata(move_misplaced=True)
check('with the box, it is moved into its type\'s folder', (os.path.exists(OWN), os.path.exists(VAE)), (True, False))
check('both are counted', progress.moved, 2)
check('its row goes with it', (db.get_version(OWN) is not None, db.get_version(VAE)), (True, None))
check('a new one is hashed where it now is, not where it was',
      hashed, [os.path.join(models, 'VAE', 'fresh_vae.safetensors')])
check('without an error', progress.errors, 0)

# ------------------------------------------------- a force sync walks and prunes
GONE_TOO = LINKED[-2]
os.remove(GONE_TOO)
ARRIVED = write('Lora', 'arrived.safetensors')
hashed.clear()
progress = service().sync_all(force=True, targets='identified')
check('a force sync forgets a file gone from disk', db.get_version(GONE_TOO), None)
check('with what only it kept', orphans(), (0, 0))
check('a force sync of the identified files hashes them, and the new one too',
      (ARRIVED in hashed, set(LINKED[:-2]) <= set(hashed)), (True, True))

# ------------------------------------------------------------ a walk of nothing
os.remove(LINKED[0])
paths.models_path = ''
held = len(db.get_all_version_paths())
progress = service().sync_metadata(model_paths=[LINKED[0]])
check('a walk that finds nothing forgets nothing - an unmounted drive, not an emptied library',
      len(db.get_all_version_paths()), held - 1)
check('but the row it was about to refresh is proven gone, and only that', db.get_version(LINKED[0]), None)
paths.models_path = models

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
