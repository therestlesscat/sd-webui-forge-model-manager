"""
A file the sync cannot see is not a file deleted (#389).

A sync forgot the row of every file not on disk: the walk's comparison, and
the metadata sync's own check of the rows it was about to refresh. With a
drive unplugged, a share asleep or a junction leading to a drive that is
away, that was every file on it - and the first sync after it came back read
each one again from scratch. Now a missing file is forgotten only where the
sync can see the place it was in (model_dirs.Sight): its own folder, a
library folder around it, or a folder holding one - the drive is up.

What is checked: a library folder away, a junction leading nowhere, the
other WebUI's file on a drive not there, a folder above the library that is
there and holds none of it (a mount point with nothing mounted) - each kept,
counted once, and its library folder named; a file deleted by hand, a
subfolder of the library deleted, a kind's whole folder deleted, the other
WebUI's file deleted from a folder that is there - each forgotten, as
before; a metadata sync with every library folder away, over every scope,
keeps every row; a kept file is not offered to Move.

The headers are stood in for: what a file "is" comes from its folder, or
"vae" in its name.
"""
import io
import os
import shutil
import string
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
from model_manager.civitai.client import CivitaiClient  # noqa: E402
import model_manager.sync_service as sync_module         # noqa: E402
from modules import paths, shared                        # noqa: E402  (webui_stub's)
from model_manager.architecture import Architecture     # noqa: E402
from model_manager.civitai import CivitaiNotFoundError, TokenBucketRateLimiter  # noqa: E402
from model_manager import console                        # noqa: E402
from model_manager import model_dirs                     # noqa: E402
from model_manager.sync_service import SyncService      # noqa: E402

WORK = os.path.join(TESTS, 'work', 'unseen_folder')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
models = facts['models_dir']
paths.models_path = models
base = os.path.basename

FOLDER_TYPE = {'Stable-diffusion': 'Checkpoint', 'VAE': 'VAE'}

def identify(path):
    kind = 'VAE' if 'vae' in base(path).lower() else FOLDER_TYPE.get(base(os.path.dirname(path)), 'LORA')
    return Architecture(None, None, False, False, kind, 'read for the test')

sync_module.identify = identify


class Client:
    """Civitai, knowing none of these files and none of these models."""

    def __init__(self):
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)
        self.asked = []

    def get_model_by_hash(self, value):
        raise CivitaiNotFoundError('no such hash')

    def get_models_by_ids(self, ids):
        self.asked.append(sorted(ids))
        return {}

    def get_model(self, model_id):
        return None

    get_models_or_gone = CivitaiClient.get_models_or_gone

    def get_checkpoint_types(self, ids):
        return {}


def write(path, size=64):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, 'wb').write(b'\0' * size)
    return path


def rows():
    return {os.path.normcase(p) for p in db.get_all_version_paths()}


def has(path):
    return os.path.normcase(path) in rows()


def said_since(mark):
    return '\n'.join(line['text'] for line in console.since(mark)[0])


def unmapped_drive():
    """A drive letter nothing is mapped to, for a drive that is away."""
    for letter in reversed(string.ascii_uppercase):
        if not os.path.isdir(letter + ':\\'):
            return letter + ':\\'
    return None


# ------------------------------------------------------------ the library
# A USB drive with one library folder on it, given as --lora-dirs; the
# folder holding it is there, as a drive letter's root or a mount point is.
DRIVES = os.path.join(WORK, 'drives')
USB = os.path.join(DRIVES, 'usb', 'loras')
ON_USB = [write(os.path.join(USB, 'on_usb_a.safetensors')),
          write(os.path.join(USB, 'on_usb_b.safetensors')),
          write(os.path.join(USB, 'stray_vae.safetensors'))]      # a VAE in a Lora folder
shared.cmd_opts.lora_dirs = [USB]

# A junction inside the library, to a folder on a stick.
STICK = os.path.join(DRIVES, 'stick')
BEHIND = write(os.path.join(STICK, 'behind_link.safetensors'))
LINK = os.path.join(models, 'Lora', 'ext')
try:
    import _winapi
    _winapi.CreateJunction(STICK, LINK)
except (ImportError, OSError) as e:
    fails.append('a junction could not be made, so its checks cannot run: %r' % (e,))
THROUGH_LINK = os.path.join(LINK, base(BEHIND))

# A subfolder of the library, and a file in it.
OLD = write(os.path.join(models, 'Lora', 'old', 'in_old.safetensors'))

# The other WebUI, sharing the database: one of its files on a drive not
# there, one in a folder that is there.
DRIVE = unmapped_drive()
OTHER_AWAY = os.path.join(DRIVE or 'Q:\\', 'webui', 'models', 'Lora', 'other_away.safetensors')
OTHER_HERE_FOLDER = os.path.join(WORK, 'otherwebui', 'models', 'Lora')
OTHER_DELETED = os.path.join(OTHER_HERE_FOLDER, 'other_deleted.safetensors')
write(OTHER_DELETED)
for path in (OTHER_AWAY, OTHER_DELETED):
    db.upsert_version({'file_path': path, 'file_name': base(path)})

check('an unmapped drive letter is there to stand for a drive away', DRIVE is not None)

progress = SyncService(client=Client()).sync_all()
check('the first sync records the files on the USB drive and behind the link',
      [has(p) for p in ON_USB + [THROUGH_LINK, OLD]], [True] * 5)
check('and keeps the other WebUI\'s file on a drive not there, alone',
      (has(OTHER_AWAY), getattr(progress, 'kept_unseen', None)), (True, 1))

# ------------------------------------------------- the drive and stick away
# One linked LoRA of the library moves to the USB drive, so the metadata
# sync below has a row of its own there.
LINKED_LORA = next(p for p in facts['linked_paths'] if os.sep + 'Lora' + os.sep in p)
MOVED_LORA = os.path.join(USB, base(LINKED_LORA))
shutil.move(LINKED_LORA, MOVED_LORA)
db.move_version(LINKED_LORA, MOVED_LORA)

os.rename(os.path.join(DRIVES, 'usb'), os.path.join(DRIVES, 'usb_away'))
shutil.rmtree(STICK)
# And by hand: a file, a subfolder, a kind's whole folder; and the other
# WebUI's file, from a folder that is there.
os.remove(OTHER_DELETED)
DELETED = facts['local_only_paths'][0]
os.remove(DELETED)
shutil.rmtree(os.path.join(models, 'Lora', 'old'))
VAES = [p for p in db.get_all_version_paths() if os.sep + 'VAE' + os.sep in p and p.startswith(models)]
shutil.rmtree(os.path.join(models, 'VAE'))
# A row in another spelling of a file deleted by hand.
OTHER_CASE = os.path.join(models, 'Lora', 'Other_Case.safetensors')
db.upsert_version({'file_path': OTHER_CASE.upper(), 'file_name': base(OTHER_CASE)})

# A VAE new in a Lora folder, its own folder deleted above: Move makes the
# folder, and the sync goes on to identify it there.
LOOSE = write(os.path.join(models, 'Lora', 'loose_vae.safetensors'))
LOOSE_MOVED = os.path.join(models, 'VAE', base(LOOSE))

check('Move would offer the VAE on the USB drive while it is there - not now',
      [f['path'] for f in model_dirs.misplaced_files(db) if f['path'] == ON_USB[2]], [])

mark = console.said()
progress = SyncService(client=Client()).sync_all(move_misplaced=True)
log = said_since(mark)

check('a library folder away: its files are kept', [has(p) for p in ON_USB + [MOVED_LORA]], [True] * 4)
check('a junction leading nowhere: its file is kept', has(THROUGH_LINK), True)
check('the other WebUI\'s file on a drive not there is kept', has(OTHER_AWAY), True)
check('each kept file counted once', getattr(progress, 'kept_unseen', None), 6)
check('the folder away is named, with what it holds',
      'Not there: %s - its 4 file(s) in the library are kept until it is back' % USB in log, True)
check('a kind\'s folder never made, holding nothing, is not named',
      [line for line in log.splitlines() if 'Not there:' in line and USB not in line], [])
check('the kept VAE is not moved, and no move failed; the loose one is',
      (progress.moved, progress.errors), (1, 0))
check('moved into a folder the move made, it is identified in the same sync',
      bool((db.get_version(LOOSE_MOVED) or {}).get('civitai_lookup_failed_at')), True)

check('a file deleted by hand is forgotten, as before', has(DELETED), False)
check('a subfolder of the library deleted: its file is forgotten', has(OLD), False)
check('a kind\'s whole folder deleted: its files are forgotten', [has(p) for p in VAES], [False] * len(VAES))
VAES = [p for p in VAES if os.path.normcase(p) != os.path.normcase(LOOSE_MOVED)]
check('a row in another spelling, its file deleted: forgotten', has(OTHER_CASE), False)
check('the other WebUI\'s file deleted from a folder that is there: forgotten', has(OTHER_DELETED), False)
check('and counted as gone from disk', progress.removed,
      len({os.path.normcase(p) for p in [DELETED, OLD, OTHER_CASE, OTHER_DELETED] + VAES}))

# A metadata sync with the drive away: its own check meets the linked row on
# the drive again, which the walk kept already.
progress = SyncService(client=Client()).sync_metadata()
check('a metadata sync counts each kept row once, the walk\'s and its own check\'s',
      getattr(progress, 'kept_unseen', None), 6)
check('and keeps the linked row on the drive', has(MOVED_LORA), True)

# ------------------------------------------------------- the rule, alone
Sight = getattr(model_dirs, 'Sight', None)
if Sight is None:
    fails.append('model_dirs has no Sight: the rule alone cannot be asked')
else:
    drive_root = os.path.splitdrive(WORK)[0] + os.sep
    check('a library folder at a drive\'s root: a folder deleted on it is seen',
          Sight([drive_root]).can_see(os.path.join(WORK, 'nowhere', 'x.safetensors')), True)
    check('nothing up to an unmapped drive\'s root: not seen',
          Sight([models]).can_see(os.path.join(DRIVE or 'Q:\\', 'Loras', 'x.safetensors')), False)
    check('a folder there that holds no library folder - a mount point, nothing mounted: not seen',
          Sight([os.path.join(models, 'Lora')]).can_see(
              os.path.join(DRIVES, 'usb', 'loras', 'x.safetensors')), False)

# ------------------------------------------ a metadata sync, everything away
# Every library folder away: the walk finds nothing, and the metadata sync's
# own check meets every identified row missing. A row outside the library,
# in a folder that is there, is still a file deleted.
OUTSIDE_FILE = os.path.join(WORK, 'outside', 'outside.safetensors')
os.makedirs(os.path.dirname(OUTSIDE_FILE))
first = next(v['file_path'] for v in db.get_linked_versions() if v['file_path'].startswith(models))
os.remove(first)
db.move_version(first, OUTSIDE_FILE)
os.rename(models, models + '_away')
linked_away = [v['file_path'] for v in db.get_linked_versions() if v['file_path'] != OUTSIDE_FILE]
check('the library has identified rows away to refresh', len(linked_away) > 3, True)
away = [p for p in db.get_all_version_paths() if not os.path.exists(p) and p != OUTSIDE_FILE]

# A full sync first: its walk finds nothing and forgets nothing, and says
# what it keeps all the same.
mark = console.said()
progress = SyncService(client=Client()).sync_all()
check('a full sync with everything away forgets nothing', [has(p) for p in away + [OUTSIDE_FILE]],
      [True] * (len(away) + 1))
check('and counts every row kept', getattr(progress, 'kept_unseen', None), len(away))
check('and names the library folders away', 'Not there: %s - its ' % os.path.join(models, 'Lora') in said_since(mark),
      True)

progress = SyncService(client=Client()).sync_metadata(model_paths=linked_away[:2])
check('scope: the grid\'s results - the rows away are kept', [has(p) for p in linked_away[:2]], [True, True])
progress = SyncService(client=Client()).sync_metadata(synced_before='2999-01-01T00:00:00')
check('scope: by age - kept', [has(p) for p in linked_away], [True] * len(linked_away))
client = Client()
progress = SyncService(client=client).sync_metadata()
check('scope: all - every identified row away is kept', [has(p) for p in linked_away], [True] * len(linked_away))
check('and nothing refreshed: Civitai is not asked about their models - no file to write a record beside',
      client.asked, [])
check('a row outside the library, its folder there: forgotten', has(OUTSIDE_FILE), False)
check('the metadata sync counts each kept row once, its walk\'s and its check\'s',
      getattr(progress, 'kept_unseen', None), len(away))
os.rename(models + '_away', models)

# The folder back: nothing is read again from scratch, nothing forgotten.
os.rename(os.path.join(DRIVES, 'usb_away'), os.path.join(DRIVES, 'usb'))
progress = SyncService(client=Client()).sync_all()
# Still away: the stick behind the junction, and the other WebUI's drive.
check('the drive back: its files are where they were, nothing new; the rest still kept',
      (progress.added, getattr(progress, 'kept_unseen', None)), (0, 2))

try:
    os.rmdir(LINK)
except OSError:
    pass

if fails:
    print('FAIL: %d check(s)' % len(fails))
    for f in fails:
        print(' - ' + f)
    sys.exit(1)
print('ok: a file the sync cannot see is kept, one deleted where it can see is forgotten')
