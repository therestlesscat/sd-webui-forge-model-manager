"""
A file's hashes are read from it once, and trusted while it is as it was
(`hashes_checked`, hashing.fingerprint): Civitai is asked with them rather
than gigabytes read again - but a force sync reads every file again, and a
file changed since is read again by any sync. A sidecar's hashes are never
trusted.

Civitai does not know a file only when it says so - a 404. An outage is no
answer. And a sidecar is read only when Civitai knows neither the file nor
the model the sidecar names.
"""
import io
import json
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
from model_manager.civitai import CivitaiAPIError, TokenBucketRateLimiter  # noqa: E402
from model_manager.db.database import ModelsDatabase, SCHEMA_VERSION    # noqa: E402
from model_manager.hashing import HashResult, fingerprint, read_hashes  # noqa: E402
from model_manager.sync_service import SyncService, files_to_identify  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'hash_trust')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
models = facts['models_dir']
paths.models_path = models
sync_module.identify = lambda path: Architecture(None, None, False, False, 'LORA', 'read for the test')


# --------------------------------------------------------------- the stand-ins
class Client:
    """Civitai, answering what the test set."""

    def __init__(self, by_hash=None, models=None, down=False, model_down=False):
        self.by_hash = by_hash or {}      # sha256 (upper) -> version payload
        self.models = models or {}        # model id -> model payload; absent is a 404
        self.down = down
        self.model_down = model_down
        self.asked = []
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def get_model_by_hash(self, value):
        self.asked.append(('by_hash', value))
        if self.down:
            raise CivitaiAPIError('Civitai is down')
        return self.by_hash.get(value.upper())

    def get_model(self, model_id):
        self.asked.append(('model', model_id))
        if self.model_down:
            raise CivitaiAPIError('Civitai is down')
        return self.models.get(model_id)

    def get_models_by_ids(self, ids):
        self.asked.append(('models', list(ids)))
        return {i: self.models[i] for i in ids if i in self.models}

    def get_model_images(self, version_id, cursor=None, limit=None):
        return {'items': [], 'metadata': {}}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def get_checkpoint_types(self, ids):
        return {}


hashed = []

def service(**answers):
    sync = SyncService(client=Client(**answers))
    real = sync.calculate_hashes
    sync.calculate_hashes = lambda path: (hashed.append(path), real(path))[1]
    return sync


def write(folder, name, size=64, fill=b'\0'):
    path = os.path.join(models, folder, name)
    io.open(path, 'wb').write(fill * size)
    return path


def row(path):
    return db.get_version(path) or {}


def sha(path):
    return HashResult.from_stored(row(path).get('file_hashes')).sha256


def model_payload(model_id, version_id, name, file_name, level=1, images=()):
    return {'id': model_id, 'name': name, 'type': 'LORA', 'nsfwLevel': level,
            'modelVersions': [{'id': version_id, 'name': 'v1', 'nsfwLevel': level,
                               'baseModel': 'SDXL 1.0', 'images': list(images),
                               'files': [{'id': version_id * 10, 'name': file_name}]}]}


# ------------------------------------------------------------- the column, v33
with sqlite3.connect(facts['db_path']) as c:
    columns = {r[1] for r in c.execute('PRAGMA table_info(files)')}
    version = c.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()[0]
check('a database made now has the column', ('hashes_checked' in columns, version), (True, str(SCHEMA_VERSION)))

OLD = os.path.join(WORK, 'v32.db')
with sqlite3.connect(facts['db_path']) as c:
    c.execute('VACUUM INTO ?', (OLD,))
with sqlite3.connect(OLD) as c:
    c.execute('ALTER TABLE files DROP COLUMN hashes_checked')
    c.execute("UPDATE schema_info SET value = '32' WHERE key = 'version'")
    held = c.execute('SELECT COUNT(*) FROM files WHERE file_hashes IS NOT NULL').fetchone()[0]
ModelsDatabase(extension_dir=ROOT, custom_db_path=OLD).close()
with sqlite3.connect(OLD) as c:
    after = c.execute('SELECT COUNT(*), COUNT(hashes_checked) FROM files WHERE file_hashes IS NOT NULL').fetchone()
check('v33 adds it to a v32 database, and trusts none of the hashes already there',
      (after[0], after[1]), (held, 0))

# ------------------------------------------- hashed, and kept as the file's own
UNKNOWN = write('Lora', 'unknown.safetensors', fill=b'u')
db.insert_missing_versions([{'file_path': UNKNOWN, 'file_name': 'unknown.safetensors'}])
progress = service().sync_metadata()
check('a file Civitai does not know is hashed', UNKNOWN in hashed, True)
check('and its hashes kept - they used to be dropped', bool(sha(UNKNOWN)), True)
check('marked as read from the file as it is', row(UNKNOWN).get('hashes_checked'), fingerprint(UNKNOWN))
check('and noted not on Civitai', bool(row(UNKNOWN).get('civitai_lookup_failed_at')), True)

KNOWN = write('Lora', 'known.safetensors', fill=b'k')
db.insert_missing_versions([{'file_path': KNOWN, 'file_name': 'known.safetensors'}])
known_sha = HashResult.from_stored(None)
probe = SyncService(client=Client()).calculate_hashes(KNOWN)
payload = model_payload(5100, 5101, 'Known', 'known.safetensors')
version_payload = dict(payload['modelVersions'][0], modelId=5100)
hashed.clear()
progress = service(by_hash={probe.sha256: version_payload}, models={5100: payload}).sync_metadata()
check('a file Civitai knows is identified', row(KNOWN).get('id'), 5101)
check('with its hashes marked as its own', row(KNOWN).get('hashes_checked'), fingerprint(KNOWN))

# ------------------------------------------------- trusted, and not read again
hashed.clear()
sync = service(by_hash={probe.sha256: version_payload}, models={5100: payload})
result = sync.sync_model(KNOWN, force=True)
check('a model\'s Sync asks Civitai with the hashes read before: the file is not read',
      (result.success, hashed), (True, []))
check('asking with its SHA-256', sync.client.asked[0], ('by_hash', probe.sha256))
check('and the mark stays', row(KNOWN).get('hashes_checked'), fingerprint(KNOWN))

hashed.clear()
service(by_hash={probe.sha256: version_payload}, models={5100: payload}).sync_model(KNOWN, force=True, rehash=True)
check('rehash reads it again, whatever is stored', hashed, [KNOWN])
hashed.clear()
service(by_hash={probe.sha256: version_payload}, models={5100: payload}).sync_all(
    model_paths=[KNOWN], force=True)
check('and a force sync always does', hashed, [KNOWN])

# ---------------------------------------------- a metadata sync keeps the mark
mark = row(KNOWN).get('hashes_checked')
service(models={5100: payload}).sync_metadata()
check('a metadata sync leaves the hashes and their mark as they were',
      (sha(KNOWN), row(KNOWN).get('hashes_checked')), (probe.sha256, mark))

# ------------------------------------------------ a sidecar's are not trusted
db.upsert_version({'file_path': KNOWN, 'file_name': 'known.safetensors', 'id': 5101, 'model_id': 5100,
                   'file_hashes': {'sha256': 'FROM A SIDECAR'}})
check('hashes written without a mark - a sidecar\'s, as Scan Disk writes them - drop it',
      row(KNOWN).get('hashes_checked'), None)
hashed.clear()
service(by_hash={probe.sha256: version_payload}, models={5100: payload}).sync_model(KNOWN, force=True)
check('so they are not asked with: the file is read', hashed, [KNOWN])
check('and its own are kept, marked', (sha(KNOWN), row(KNOWN).get('hashes_checked')),
      (probe.sha256, fingerprint(KNOWN)))

# ------------------------------------------------------ a file changed since
io.open(KNOWN, 'ab').write(b'more')
new, changed = files_to_identify([KNOWN, UNKNOWN])
check('a file changed since its hashes were read is one to identify again', (new, changed), ([], [KNOWN]))
hashed.clear()
sync = service(models={5100: payload})
progress = sync.sync_metadata()
check('and any sync reads it again, and asks about it', KNOWN in hashed, True)
check('with its new hashes, marked', (sha(KNOWN) != probe.sha256, row(KNOWN).get('hashes_checked')),
      (True, fingerprint(KNOWN)))

LEGACY = facts['local_only_paths'][0]
db.upsert_version({'file_path': LEGACY, 'file_name': os.path.basename(LEGACY),
                   'file_hashes': {'sha256': 'STORED BEFORE THE MARK'}})
io.open(LEGACY, 'ab').write(b'touched')
check('a file whose hashes carry no mark is never taken as changed: no library has to be synced again',
      LEGACY in files_to_identify([LEGACY])[1], False)

# --------------------------------------------------- a download's are its own
ARRIVED = write('Lora', 'arrived.safetensors', fill=b'a')
db.insert_missing_versions([{'file_path': ARRIVED, 'file_name': 'arrived.safetensors'}])
arrived = SyncService(client=Client()).calculate_hashes(ARRIVED)
apayload = model_payload(5200, 5201, 'Arrived', 'arrived.safetensors')
service(models={5200: apayload}).sync_model(ARRIVED, force=True, known={
    'hashes': arrived, 'version': dict(apayload['modelVersions'][0], modelId=5200), 'model': apayload})
check('a download\'s hashes, checked against its bytes, are marked as the file\'s own',
      (sha(ARRIVED), row(ARRIVED).get('hashes_checked')), (arrived.sha256, fingerprint(ARRIVED)))

# ------------------------------------------------------ an outage is no answer
OUTAGE = write('Lora', 'outage.safetensors', fill=b'o')
db.insert_missing_versions([{'file_path': OUTAGE, 'file_name': 'outage.safetensors'}])
hashed.clear()
result = service(down=True).sync_model(OUTAGE)
check('Civitai not answering is an error', (result.success, result.not_found, bool(result.error)),
      (False, False, True))
check('not "not on Civitai" - every sync after would have skipped the file',
      row(OUTAGE).get('civitai_lookup_failed_at'), None)
check('its hashes are kept', row(OUTAGE).get('hashes_checked'), fingerprint(OUTAGE))
hashed.clear()
service().sync_model(OUTAGE)
check('so asking again reads nothing', hashed, [])

# -------------------------------------------- a sidecar, when Civitai lacks both
SHOWCASE = [{'url': 'https://image.civitai.com/x/a.jpeg', 'nsfwLevel': 1},
            {'url': 'https://image.civitai.com/x/b.jpeg', 'nsfwLevel': 16}]
DELETED = write('Lora', 'deleted.safetensors', fill=b'd')
db.insert_missing_versions([{'file_path': DELETED, 'file_name': 'deleted.safetensors'}])
fixtures.sidecar(DELETED, model_payload(6100, 6101, 'Deleted On Civitai', 'deleted.safetensors',
                                        level=2, images=SHOWCASE))
sync = service()
result = sync.sync_model(DELETED)
check('no file and no model on Civitai: the sidecar is read', ('model', 6100) in sync.client.asked, True)
check('and the file filed as it says', (row(DELETED).get('id'), row(DELETED).get('model_id')), (6101, 6100))
check('its model too, named by it', (db.get_civitai_model(6100) or {}).get('name'), 'Deleted On Civitai')
check('not as if Civitai had said it', (db.get_civitai_model(6100) or {}).get('civitai_synced_at'), None)
check('its level the version\'s own, not raised by its showcase (#104)', row(DELETED).get('nsfw_level'), 2)
check('its hashes the file\'s own, not the sidecar\'s', row(DELETED).get('hashes_checked'), fingerprint(DELETED))
check('and still noted not on Civitai', bool(row(DELETED).get('civitai_lookup_failed_at')), True)

LIVE = write('Lora', 'renamed_or_edited.safetensors', fill=b'l')
db.insert_missing_versions([{'file_path': LIVE, 'file_name': 'renamed_or_edited.safetensors'}])
fixtures.sidecar(LIVE, model_payload(6200, 6201, 'From The Sidecar', 'renamed_or_edited.safetensors'))
sync = service(models={6200: model_payload(6200, 6201, 'On Civitai', 'other.safetensors')})
sync.sync_model(LIVE)
check('a model Civitai has leaves the file unidentified, its sidecar unread',
      (row(LIVE).get('id'), db.get_civitai_model(6200)), (None, None))
check('noted not on Civitai: it has no file with these bytes', bool(row(LIVE).get('civitai_lookup_failed_at')), True)

ASKING = write('Lora', 'asking.safetensors', fill=b's')
db.insert_missing_versions([{'file_path': ASKING, 'file_name': 'asking.safetensors'}])
fixtures.sidecar(ASKING, model_payload(6300, 6301, 'Unknown Yet', 'asking.safetensors'))
result = service(model_down=True).sync_model(ASKING)
check('Civitai not answering about the model reads no sidecar, and says nothing yet',
      (row(ASKING).get('id'), row(ASKING).get('civitai_lookup_failed_at'), bool(result.error)), (None, None, True))

STUB = write('Lora', 'stub.safetensors', fill=b't')
db.insert_missing_versions([{'file_path': STUB, 'file_name': 'stub.safetensors'}])
fixtures.sidecar(STUB, {'id': 6400, 'name': 'A stub, naming no version'})
sync = service()
sync.sync_model(STUB)
check('a sidecar naming no version is no identification (#131), and Civitai is not asked about it',
      (row(STUB).get('id'), ('model', 6400) in sync.client.asked), (None, False))

# Other tools write the by-hash payload: the version at the root, the model
# under "model". Read as the model format it gave the model the version's id
# and name and no type.
FORMAT = write('Stable-diffusion', 'from_another_tool.gguf', fill=b'f')
db.insert_missing_versions([{'file_path': FORMAT, 'file_name': 'from_another_tool.gguf'}])
io.open(os.path.splitext(FORMAT)[0] + '.civitai.info', 'w', encoding='utf-8').write(json.dumps({
    "id": 2434385, "modelId": 2053259, "name": "Lightning Q6", "baseModel": "Wan Video 2.2 I2V-A14B",
    "trainedWords": [], "files": [{"name": "from_another_tool.gguf", "primary": True}],
    "creator": {"username": "maker"},
    "model": {"name": "WAN 2.2 Enhanced", "type": "Checkpoint", "nsfw": False}}))
service().sync_model(FORMAT)
stored = db.get_civitai_model(2053259) or {}
check('a sidecar in Civitai\'s version format is read as the model it belongs to',
      (stored.get('name'), stored.get('type'), stored.get('creator_username')),
      ('WAN 2.2 Enhanced', 'Checkpoint', 'maker'))
check('and the version as the version', (row(FORMAT).get('id'), row(FORMAT).get('model_id'), row(FORMAT).get('base_model')),
      (2434385, 2053259, 'Wan Video 2.2 I2V-A14B'))

TYPELESS = write('Lora', 'no_type_anywhere.safetensors', fill=b'n')
db.insert_missing_versions([{'file_path': TYPELESS, 'file_name': 'no_type_anywhere.safetensors'}])
fixtures.sidecar(TYPELESS, {"id": 31337, "name": "Typeless", "modelVersions": [
    {"id": 31338, "name": "v1", "files": [{"name": "no_type_anywhere.safetensors"}]}]})
result = service().sync_model(TYPELESS)
check('a sidecar with no type anywhere is stored, its Civitai type Unknown',
      (bool(result.error), (db.get_civitai_model(31337) or {}).get('type')), (False, 'Unknown'))
db.upsert_civitai_model({'id': 31337, 'name': 'Typeless', 'type': 'LORA'})
db.upsert_civitai_model({'id': 31337, 'name': 'Typeless', 'type': None})
check('and a typeless one never overwrites a type already known', db.get_civitai_model(31337)['type'], 'LORA')

# ------------------------------------------------- SHA-256 first, the rest if needed
# A file is read for SHA-256 first, with AutoV1 and AutoV2, which come free;
# AutoV3, BLAKE3 and CRC32 - each about as costly - only when none of those is
# known, or Civitai's list for the file does not say them. Hashing every kind
# up front ran at half the speed the disk could read.
from model_manager.hashing import ModelHasher            # noqa: E402

def safetensors(name, seed):
    """A real safetensors file, past a megabyte: it has an AutoV1 and an AutoV3."""
    header = json.dumps({'__metadata__': {'seed': seed}}).encode()
    path = os.path.join(models, 'Lora', name)
    with io.open(path, 'wb') as f:
        f.write(len(header).to_bytes(8, 'little') + header + bytes([seed]) * (1300 * 1024))
    db.insert_missing_versions([{'file_path': path, 'file_name': name}])
    return path, ModelHasher.calculate_all(path)

reads = []
real_read = ModelHasher._read.__func__

def counted_read(cls, file_path, result, full, tensor, blake, crc):
    reads.append(os.path.basename(file_path))
    return real_read(cls, file_path, result, full, tensor, blake, crc)

def listed(full, *kinds):
    names = {'sha256': 'SHA256', 'autov1': 'AutoV1', 'autov2': 'AutoV2', 'autov3': 'AutoV3',
             'blake3': 'BLAKE3', 'crc32': 'CRC32'}
    return {names[k]: getattr(full, k) for k in kinds}

def civitai(model_id, name, hashes):
    version = {'id': model_id + 1, 'modelId': model_id, 'name': 'v1', 'baseModel': 'SDXL 1.0',
               'files': [{'id': model_id * 10, 'name': name, 'hashes': hashes}]}
    return version, {'id': model_id, 'name': name, 'type': 'LORA', 'modelVersions': [dict(version)]}

ALL = ('sha256', 'autov1', 'autov2', 'autov3', 'blake3', 'crc32')
ModelHasher._read = classmethod(counted_read)
try:
    # Found by its SHA-256, Civitai's list saying the rest: one read.
    A, full_a = safetensors('order_a.safetensors', 1)
    version, model = civitai(7100, 'order_a.safetensors', listed(full_a, *ALL))
    reads.clear()
    sync = service(by_hash={full_a.sha256: version}, models={7100: model})
    sync.sync_model(A)
    stored = read_hashes(row(A).get('file_hashes'))
    check('found by its SHA-256, the file is read once', reads, ['order_a.safetensors'])
    check('asked about by its SHA-256 alone', [a for a in sync.client.asked if a[0] == 'by_hash'],
          [('by_hash', full_a.sha256)])
    check('the rest taken from Civitai\'s list for the file - the same bytes, so the same hashes',
          [stored.get(k) for k in ('autov3', 'blake3', 'crc32')],
          [full_a.autov3.lower(), full_a.blake3.lower(), full_a.crc32.lower()])
    check('and marked as the file\'s own', row(A).get('hashes_checked'), fingerprint(A))

    # Found by its SHA-256, the list silent on AutoV3: read again, for it alone.
    B, full_b = safetensors('order_b.safetensors', 2)
    version, model = civitai(7200, 'order_b.safetensors', listed(full_b, 'sha256', 'autov2', 'blake3', 'crc32'))
    reads.clear()
    service(by_hash={full_b.sha256: version}, models={7200: model}).sync_model(B)
    check('a list without AutoV3 has it read from the file: images name LoRAs by it',
          (reads, read_hashes(row(B).get('file_hashes')).get('autov3')),
          (['order_b.safetensors'] * 2, full_b.autov3.lower()))

    # Found by AutoV1 - part of the file - its list is not taken.
    C, full_c = safetensors('order_c.safetensors', 3)
    version, model = civitai(7300, 'order_c.safetensors', dict(listed(full_c, 'autov1'), BLAKE3='NOT THIS FILE\'S'))
    reads.clear()
    sync = service(by_hash={full_c.autov1: version}, models={7300: model})
    sync.sync_model(C)
    check('found by AutoV1, after the SHA-256', [a[1] for a in sync.client.asked if a[0] == 'by_hash'],
          [full_c.sha256, full_c.autov1])
    check('a match on part of the file takes nothing from the list: the rest are read',
          (reads, read_hashes(row(C).get('file_hashes')).get('blake3')),
          (['order_c.safetensors'] * 2, full_c.blake3.lower()))

    # Known by nothing: every kind, the costly ones only after the free ones.
    D, full_d = safetensors('order_d.safetensors', 4)
    reads.clear()
    sync = service()
    sync.sync_model(D)
    check('a file nothing finds is asked about by the free kinds first, then the rest',
          [a[1] for a in sync.client.asked if a[0] == 'by_hash'],
          [full_d.sha256, full_d.autov1, full_d.autov2, full_d.autov3, full_d.blake3, full_d.crc32])
    check('read twice: the second time only once the first kinds found nothing', reads, ['order_d.safetensors'] * 2)
    check('and every kind kept, marked',
          ([read_hashes(row(D).get('file_hashes')).get(k) for k in ALL], row(D).get('hashes_checked')),
          ([getattr(full_d, k).lower() for k in ALL], fingerprint(D)))
finally:
    ModelHasher._read = classmethod(real_read)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
