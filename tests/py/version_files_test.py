"""
A version is one row, its files rows of their own (#133).

model_versions held one row per file, each with its own copy of the
version's data, so a version with two files was two versions to everything
that counted, fetched or read one: its gallery fetched once per file by every
sync, its card counting two versions, and its gallery's cursor read from
whichever copy came first - copies a sync had left disagreeing.

Here: one version, two files, through the paths that went wrong; the
migration that merges what a library already holds; and an older copy of the
extension refusing a database newer than it knows.
"""
import hashlib
import json
import os
import shutil
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

import model_manager.db.database as dbmod                # noqa: E402
from model_manager.civitai.client import CivitaiClient  # noqa: E402
from model_manager.civitai import TokenBucketRateLimiter  # noqa: E402
from model_manager.db import ModelsDatabase, GridQuery   # noqa: E402
from model_manager.db import migrations                  # noqa: E402
from model_manager.sync_estimates import gallery_refresh_options  # noqa: E402
from model_manager.sync_service import SyncService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'version_files_test')
os.makedirs(WORK, exist_ok=True)
for name in os.listdir(WORK):
    if os.path.isdir(os.path.join(WORK, name)):
        shutil.rmtree(os.path.join(WORK, name))
    else:
        os.remove(os.path.join(WORK, name))

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


MODEL, VERSION = 50, 5001
# fp16 is listed under another name than it has on disk, and found by its
# hash; fp32 by its name.
VERSION_PAYLOAD = {'id': VERSION, 'modelId': MODEL, 'name': 'v1', 'baseModel': 'SDXL 1.0', 'files': [
    {'id': 71, 'name': 'model_fp16.safetensors', 'type': 'Model', 'primary': True,
     'metadata': {'fp': 'fp16', 'size': 'pruned', 'format': 'SafeTensor'},
     'hashes': {'SHA256': hashlib.sha256(b'fp16.safetensors').hexdigest().upper()}},
    {'id': 72, 'name': 'FP32.safetensors', 'type': 'Pruned Model',
     'metadata': {'fp': 'fp32', 'size': 'full', 'format': 'SafeTensor'}, 'hashes': {}}]}
MODEL_PAYLOAD = {'id': MODEL, 'name': 'M', 'type': 'LORA', 'modelVersions': [VERSION_PAYLOAD]}


class Civitai:
    """Civitai, knowing both files as the one version, and counting galleries asked for."""
    galleries = []

    def __init__(self):
        self.api_key = None
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def get_model_by_hash(self, value):
        return VERSION_PAYLOAD

    def get_model(self, model_id):
        return MODEL_PAYLOAD

    def get_models_by_ids(self, ids):
        return {MODEL: MODEL_PAYLOAD}

    # The client's own, over the answers above (#262).
    get_models_or_gone = CivitaiClient.get_models_or_gone

    def get_model_images(self, version_id, cursor=None, limit=100):
        if cursor is None:
            Civitai.galleries.append(version_id)
        return {'images': [{'id': 7, 'url': 'u7', 'browsingLevel': 1}], 'next_cursor': 'next'}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def get_checkpoint_types(self, ids):
        return {}

    def close(self):
        pass


def write(name):
    path = os.path.join(WORK, name)
    with open(path, 'wb') as f:
        f.write(name.encode())
    return path


db = ModelsDatabase(WORK, custom_db_path=os.path.join(WORK, 'library.db'))
dbmod._db_instance = db
FP32 = write('fp32.safetensors')
FP16 = write('fp16.safetensors')

# fp32 is found by a walk first, and so comes first in the table; fp16 is
# identified, and its gallery has been fetched.
db.insert_missing_versions([{'file_path': FP32, 'file_name': 'fp32.safetensors',
                             'file_extension': '.safetensors', 'file_size': 4}])
db.upsert_civitai_model({'id': MODEL, 'name': 'M', 'type': 'LORA'})
db.upsert_version({'file_path': FP16, 'file_name': 'fp16.safetensors', 'file_extension': '.safetensors',
                   'id': VERSION, 'model_id': MODEL, 'has_civitai_data': True})
db.replace_first_page(VERSION, [{'id': 1, 'url': 'u1', 'browsingLevel': 1}], 'old')

# A sync identifies fp32: the gallery is stored, with its cursor, before the
# file is written as the version's - and must still be the version's.
check('fp32 syncs', SyncService(client=Civitai()).sync_model(FP32, force=True).success)
check("the version's cursor is the one its gallery was stored with, whichever file is read",
      db.get_version_by_id(VERSION)['next_images_cursor'], 'next')
check('read by either file, the same',
      [db.get_version(p)['next_images_cursor'] for p in (FP16, FP32)], ['next', 'next'])

cards, _ = db.query_models_grouped(GridQuery(search='model:%d' % MODEL))
check('one card', len(cards), 1)
check('of one version, though it has two files', cards[0]['local_version_count'] if cards else None, 1)

Civitai.galleries = []
SyncService(client=Civitai()).sync_all(model_paths=[FP16, FP32], force=True, max_workers=2)
check("a full sync of both files fetches the version's gallery once", Civitai.galleries, [VERSION])

Civitai.galleries = []
SyncService(client=Civitai()).sync_metadata(include_images=True, max_workers=2)
check("so does a metadata sync with images", Civitai.galleries, [VERSION])

# Civitai's id for each file, missing - as from before the column - and a
# metadata sync fills it: by the hash it stored, else by name.
with db._cursor() as cursor:
    cursor.execute("UPDATE files SET civitai_file_id = NULL, fp = NULL")
SyncService(client=Civitai()).sync_metadata(include_images=False, max_workers=2)
check("a metadata sync fills each file's Civitai id and facts, by hash, else by name",
      [(r['civitai_file_id'], r['civitai_file_type'], r['fp'], r['size'], r['format'], r['civitai_primary'])
       for r in (db.get_version(FP16), db.get_version(FP32))],
      [(71, 'Model', 'fp16', 'pruned', 'SafeTensor', True), (72, 'Pruned Model', 'fp32', 'full', 'SafeTensor', None)])

one = gallery_refresh_options(db, [VERSION])
check('the estimate costs a version named twice once',
      gallery_refresh_options(db, [VERSION, VERSION]), one)
db.close()


# ------------------------------------------------------------- twin files
# A version listing the same bytes twice, under two names (#375): both files
# match by hash, and the first always won - the second file on disk was
# recorded under the first's id, read as not held, and offered again.
from model_manager.payload_rows import file_row          # noqa: E402
from model_manager.hashing import HashResult             # noqa: E402
from model_manager.api.annotations import ownership      # noqa: E402
from modules import paths                                # noqa: E402  (webui_stub's)

TWIN_MODEL, TWIN_VERSION = 60, 6001
TWIN_BYTES = b'the same bytes twice'
TWIN_SHA = hashlib.sha256(TWIN_BYTES).hexdigest().upper()
OTHER_SHA = hashlib.sha256(b'other bytes').hexdigest().upper()
TWIN_VERSION_PAYLOAD = {'id': TWIN_VERSION, 'modelId': TWIN_MODEL, 'name': 'v1', 'baseModel': 'SDXL 1.0', 'files': [
    {'id': 81, 'name': 'twin_a.safetensors', 'type': 'Model', 'primary': True, 'hashes': {'SHA256': TWIN_SHA}},
    {'id': 82, 'name': 'twin_b.safetensors', 'type': 'Model', 'hashes': {'SHA256': TWIN_SHA}},
    {'id': 83, 'name': 'other.safetensors', 'type': 'Model', 'hashes': {'SHA256': OTHER_SHA}}]}
TWIN_MODEL_PAYLOAD = {'id': TWIN_MODEL, 'name': 'Twins', 'type': 'LORA', 'modelVersions': [TWIN_VERSION_PAYLOAD]}
picked = lambda name, hashes: file_row(TWIN_VERSION_PAYLOAD, name, hashes).get('civitai_file_id')
twin_hashes = {'sha256': TWIN_SHA}

check("twins: the second's name picks the second's id", picked('twin_b.safetensors', twin_hashes), 82)
check("twins: the first's name, the first's id", picked('twin_a.safetensors', twin_hashes), 81)
check("twins: the name's case aside", picked('TWIN_B.safetensors', twin_hashes), 82)
check('a renamed copy, a name the list does not have, keeps the first hash match',
      picked('renamed.safetensors', twin_hashes), 81)
check("a name never beats a hash: named as a twin, the bytes of another file, that file's id",
      picked('twin_b.safetensors', {'sha256': OTHER_SHA}), 83)
check('no hashes known: by name, as before', picked('twin_b.safetensors', None), 82)


class TwinCivitai(Civitai):
    """Civitai, knowing the twins' version, its lookup by hash included."""

    def get_model_by_hash(self, value):
        return TWIN_VERSION_PAYLOAD

    def get_model(self, model_id):
        return TWIN_MODEL_PAYLOAD

    def get_models_by_ids(self, ids):
        return {TWIN_MODEL: TWIN_MODEL_PAYLOAD}

    def get_model_images(self, version_id, cursor=None, limit=100):
        return {'images': [], 'next_cursor': None}

    def get_versions_by_hashes(self, hashes):
        return [TWIN_VERSION_PAYLOAD]


paths.models_path = os.path.join(WORK, 'models')
os.makedirs(os.path.join(paths.models_path, 'Lora'), exist_ok=True)
twin_db = ModelsDatabase(WORK, custom_db_path=os.path.join(WORK, 'twins.db'))
dbmod._db_instance = twin_db
TWINS = {}
for name in ('twin_a.safetensors', 'twin_b.safetensors'):
    TWINS[name] = os.path.join(paths.models_path, 'Lora', name)
    with open(TWINS[name], 'wb') as f:
        f.write(TWIN_BYTES)
    # As a download's sync is handed them: its file's hashes from Civitai's list.
    SyncService(client=TwinCivitai()).sync_model(TWINS[name], force=True, known={
        'hashes': HashResult.from_stored(twin_hashes), 'version': TWIN_VERSION_PAYLOAD,
        'model': TWIN_MODEL_PAYLOAD})
file_ids = lambda: [twin_db.get_version(TWINS[n])['civitai_file_id'] for n in sorted(TWINS)]
check('both twins downloaded: each under its own id', file_ids(), [81, 82])
check('and the Civitai Browser holds both',
      ownership(twin_db, [TWIN_MODEL], [TWIN_VERSION])['versions'][TWIN_VERSION]['files'], [81, 82])

# A row an earlier version wrote: the second twin under the first's id.
import model_manager.release_notes as release_notes     # noqa: E402
check('nothing recorded wrong: no note', release_notes._holds('twin_files'), False)
with twin_db._cursor() as cursor:
    cursor.execute("UPDATE files SET civitai_file_id = 81 WHERE file_path = ?", (TWINS['twin_b.safetensors'],))
check('a twin under the other twin\'s id: the note is for this library', release_notes._holds('twin_files'), True)
check('the files it names', getattr(twin_db, 'files_under_twin_ids', lambda: None)(),
      [TWINS['twin_b.safetensors']])
SyncService(client=TwinCivitai()).sync_metadata(include_images=False, max_workers=2)
check('a metadata sync writes each twin its own id', file_ids(), [81, 82])
check('and the note is no longer for this library', release_notes._holds('twin_files'), False)


# Civitai's answer for many models at once - the metadata sync's - can name a
# file otherwise than its answer for one version, and the lookup by hash,
# which every sync stores; the file on disk has the latter's name (#375,
# round 3: 717 of 5,653 listed files on one library).
BATCH_VERSION = dict(TWIN_VERSION_PAYLOAD, files=[
    dict(f, name='twin_b_bf16.safetensors') if f['id'] == 82 else f for f in TWIN_VERSION_PAYLOAD['files']])
BATCH_MODEL = dict(TWIN_MODEL_PAYLOAD, modelVersions=[BATCH_VERSION])


class BatchNamesCivitai(TwinCivitai):
    def get_models_by_ids(self, ids):
        return {TWIN_MODEL: BATCH_MODEL}


check("the lookup's name breaks the tie the batch's cannot",
      file_row(BATCH_VERSION, 'twin_b.safetensors', twin_hashes, names={82: 'twin_b.safetensors'})
      .get('civitai_file_id') if 'names' in file_row.__code__.co_varnames else None, 82)
check('no name decides: the id the file holds',
      file_row(BATCH_VERSION, 'renamed.safetensors', twin_hashes, held=82).get('civitai_file_id')
      if 'held' in file_row.__code__.co_varnames else None, 82)
check('no name decides, no matching id held: the first',
      file_row(BATCH_VERSION, 'renamed.safetensors', twin_hashes, held=99).get('civitai_file_id')
      if 'held' in file_row.__code__.co_varnames else None, 81)

with twin_db._cursor() as cursor:
    cursor.execute("UPDATE files SET civitai_file_id = 81 WHERE file_path = ?", (TWINS['twin_b.safetensors'],))
SyncService(client=BatchNamesCivitai()).sync_metadata(include_images=False, max_workers=2)
check("a metadata sync whose list names the twin otherwise: the stored lookup's name puts it right",
      file_ids(), [81, 82])

# No lookup stored to name it: a right id is kept, not written back to the first.
with twin_db._cursor() as cursor:
    cursor.execute("UPDATE version_records SET looked_up = NULL WHERE version_id = ?", (TWIN_VERSION,))
SyncService(client=BatchNamesCivitai()).sync_metadata(include_images=False, max_workers=2)
check('no lookup stored: each twin keeps the right id it holds', file_ids(), [81, 82])
twin_db.close()
paths.models_path = ''


# ----------------------------------------------------- the file Send uses
# Of a version's files, the one its Files list marks and Send uses: of a type
# Send uses, in this WebUI's folders, the first by path. A copy in the other
# WebUI's folders is not one this Forge lists; an upscaler Send never uses.
from model_manager.send_plan import send_files          # noqa: E402
here = lambda path: path.startswith('N:')
check('the first, by path, of the files this WebUI has', send_files([
    {'id': 1, 'file_path': r'N:\Lora\b_fp32.safetensors', 'file_type': 'LORA'},
    {'id': 1, 'file_path': r'N:\Lora\a_fp16.safetensors', 'file_type': 'LORA'},
    {'id': 2, 'file_path': r'F:\other\Lora\c.safetensors', 'file_type': 'LORA'},
    {'id': 2, 'file_path': r'N:\Lora\c.safetensors', 'file_type': 'LORA'},
    {'id': 3, 'file_path': r'N:\ESRGAN\x.pth', 'file_type': 'Upscaler'},
    {'id': 4, 'file_path': r'N:\VAE\v.safetensors', 'file_type': 'VAE'},
    {'id': None, 'file_path': r'N:\Stable-diffusion\own.safetensors', 'file_type': 'Checkpoint'},
], here), {r'N:\Lora\a_fp16.safetensors', r'N:\Lora\c.safetensors', r'N:\VAE\v.safetensors',
           r'N:\Stable-diffusion\own.safetensors'})
check('none for a version only the other WebUI has',
      send_files([{'id': 5, 'file_path': r'F:\other\x.safetensors', 'file_type': 'Checkpoint'}], here), set())


# ------------------------------------------------------------ the migration
# A library at v31, as one is: two files of a version, their copies of it
# disagreeing as a sync and a scan left them, beside a file of a version of
# its own and one Civitai does not know.
OLD = os.path.join(WORK, 'v31.db')
raw = sqlite3.connect(OLD)
raw.row_factory = sqlite3.Row
cur = raw.cursor()
cur.execute("CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT)")
migrations.run_migrations(cur, 0, 31, OLD, WORK)
raw.commit()
check('built at v31', cur.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()[0], '31')

ROWS = [
    # file, id, model, base model, created, stats, cursor, synced, cover, downloaded
    ('a.pt',  9, 90, 'Upscaler', '2023-07-25', 262, None,  None,         'cover-a', None),
    ('a.pth', 9, 90, 'Other',    None,         203, 'c-9', '2026-10-01', None,      '2026-09-27'),
    ('b.pt', 10, 90, 'SD 1.5',   '2024-01-01',  10, 'c-10', '2026-09-01', 'cover-b', None),
]
for path, vid, mid, base, created, stats, cursor_, synced, cover, downloaded in ROWS:
    cur.execute("""INSERT INTO model_versions (id, model_id, version_name, base_model, created_at,
                       stats_download_count, file_path, file_name, file_size, file_type, file_hashes,
                       has_civitai_data, next_images_cursor, images_sync_last_date, cover_url,
                       downloaded_at, trained_words, nsfw_level)
                   VALUES (?, ?, 'v', ?, ?, ?, ?, ?, ?, 'Upscaler', ?, 1, ?, ?, ?, ?, '["w"]', 2)""",
                (vid, mid, base, created, stats, path, path, len(path), json.dumps({'sha256': path}),
                 cursor_, synced, cover, downloaded))
cur.execute("""INSERT INTO model_versions (file_path, file_name, file_size, has_civitai_data, nsfw_level)
               VALUES ('unknown.pt', 'unknown.pt', 3, 0, 1)""")
# A version of one file, Civitai's level for it Unknown, no stats.
cur.execute("""INSERT INTO model_versions (id, model_id, file_path, file_name, has_civitai_data, nsfw_level,
                   stats_download_count)
               VALUES (11, 90, 'c.pt', 'c.pt', 1, 64, NULL)""")
# As a scan before #131 left a stub sidecar's file: flagged, and tied to the
# stub's model, with no version.
cur.execute("""INSERT INTO model_versions (file_path, file_name, model_id, has_civitai_data)
               VALUES ('stub.pt', 'stub.pt', 90, 1)""")
cur.execute("INSERT INTO pins (model_id, file_path, pinned_at) VALUES (NULL, 'a.pth', 'now')")
cur.execute("INSERT INTO civitai_models (id, name, type, is_bookmarked, versions) VALUES "
            "(90, 'Upscalers', 'Upscaler', 1, ?)", (json.dumps([
                {'id': 9, 'files': [{'id': 901, 'name': 'A.PT', 'type': 'Model', 'primary': True,
                                     'metadata': {'fp': 'fp16', 'size': 'pruned', 'format': 'PickleTensor'}}]},
                {'id': 10, 'files': [{'id': 1001, 'name': 'other.pt'}]}]),))
raw.commit()

migrations.run_migrations(cur, 31, 32, OLD, WORK)
raw.commit()
tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
check('model_versions is gone, so an older copy writes nothing in its shape', 'model_versions' in tables, False)
check('and no table is named for Civitai: civitai_models is models, its rows kept',
      ('civitai_models' in tables, [tuple(r) for r in cur.execute("SELECT id, name, is_bookmarked FROM models")]),
      (False, [(90, 'Upscalers', 1)]))
files = {r['file_path']: dict(r) for r in cur.execute("SELECT * FROM files")}
check('every file kept', sorted(files), ['a.pt', 'a.pth', 'b.pt', 'c.pt', 'stub.pt', 'unknown.pt'])
check('each with its version; a stub tied to a model without one, with none',
      {p: f['version_id'] for p, f in files.items()},
      {'a.pt': 9, 'a.pth': 9, 'b.pt': 10, 'c.pt': 11, 'stub.pt': None, 'unknown.pt': None})
check("a file's own columns stay its own",
      (files['a.pth']['downloaded_at'], json.loads(files['a.pt']['file_hashes'])),
      ('2026-09-27', {'sha256': 'a.pt'}))
versions = {r['id']: dict(r) for r in cur.execute("SELECT * FROM versions")}
check('one row per version', sorted(versions), [9, 10, 11])
nine = versions.get(9, {})
check('the synced copy first: its base model, cursor and date together',
      (nine.get('base_model'), nine.get('next_images_cursor'), nine.get('images_sync_last_date')),
      ('Other', 'c-9', '2026-10-01'))
check('what it lacks, from the other copy', (nine.get('created_at'), nine.get('cover_url')),
      ('2023-07-25', 'cover-a'))
check('the stats, the highest', nine.get('stats_download_count'), 262)
check('nothing else changed', (versions.get(10, {}).get('next_images_cursor'),
                               versions.get(10, {}).get('trained_words')), ('c-10', '["w"]'))
check('a level of Unknown stays Unknown, and stats nobody gave stay unsaid',
      (versions.get(11, {}).get('nsfw_level'), versions.get(11, {}).get('stats_download_count')), (64, None))
check('pins stay', cur.execute("SELECT file_path FROM pins").fetchall()[0][0], 'a.pth')
check("each file's Civitai id and facts, from its version's list on the model, by name",
      {p: (f['civitai_file_id'], f['civitai_file_type'], f['fp'], f['size'], f['format'], f['civitai_primary'])
       for p, f in files.items() if p in ('a.pt', 'a.pth', 'b.pt')},
      {'a.pt': (901, 'Model', 'fp16', 'pruned', 'PickleTensor', 1),
       'a.pth': (None,) * 6, 'b.pt': (None,) * 6})
check('the database was backed up first',
      any(n.startswith('v31.db.backup_') for n in os.listdir(WORK)))
migrations.run_migrations(cur, 31, 32, OLD, WORK)
check('run twice, harmless',
      cur.execute("SELECT COUNT(*) FROM files").fetchone()[0], 6)
cur.execute("INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', '99')")
raw.commit()
raw.close()


# --------------------------------------------- a database newer than the code
try:
    ModelsDatabase(WORK, custom_db_path=OLD)
    refused = False
except RuntimeError as e:
    refused = 'newer' in str(e)
check('a copy older than the database refuses it, rather than write the old shape', refused)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
