"""
Civitai's record of each version, and whether its creator allows downloads (#229).

Only Civitai's lookup by file hash (`POST /model-versions/by-hash`, 100 a
request) says a version's `usageControl`; the search and a model's answer do
not. A sync keeps every version of the models it reads in `version_records`
(v43): what the model's answer says, and what the lookup says, each without
the showcase images. The Model Manager's panel reads it and asks Civitai
nothing; the Civitai Browser asks through a route of its own.

What is checked, on a throwaway library under tests/work, with Civitai a
stand-in: the client's POST and its limit; the rule for a word; v43 and the
fence it makes; what a sync writes and keeps, and how many lookups it makes;
a model's Sync asking once; the panel's answer; the estimate; the Civitai
Browser's route; the notice asking for a sync.
"""
import io
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

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.sync_service as sync_module         # noqa: E402
import model_manager.api.models as models_api            # noqa: E402
import model_manager.api.civitai as civitai_api          # noqa: E402
from modules import paths                                # noqa: E402  (webui_stub's)
from model_manager import release_notes                  # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.architecture import Architecture     # noqa: E402
from model_manager.civitai import CivitaiClient, TokenBucketRateLimiter  # noqa: E402
from model_manager.civitai.licensing import on_site_only, versions_on_site_only  # noqa: E402
from model_manager.db import migrations                  # noqa: E402
from model_manager.sync_estimates import estimate_metadata_sync  # noqa: E402
from model_manager.sync_service import SyncService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'version_records')
shutil.rmtree(WORK, ignore_errors=True)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def sha(n):
    return ('%064X' % n)


class Answer:
    def __init__(self, status, body=None):
        self.status_code, self._body, self.headers, self.text = status, body, {}, json.dumps(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError('HTTP %d' % self.status_code)


# ------------------------------------------------------------ the client
client = CivitaiClient()
client.rate_limiter = TokenBucketRateLimiter(1000.0, 100)
sent = []
client.session.request = lambda method, url, **kw: sent.append((method, url, kw)) or Answer(
    200, [{'id': 1, 'usageControl': 'Download'}, 'not a version'])
hashes = [sha(n) for n in range(20)]
got = client.get_versions_by_hashes(hashes)
check("a page's 20 hashes go to the lookup in one POST, as JSON",
      [(m, u.endswith('/model-versions/by-hash'), kw.get('json')) for m, u, kw in sent],
      [('POST', True, hashes)])
check('and its versions come back, what is not one left out', got, [{'id': 1, 'usageControl': 'Download'}])

sent.clear()
client.session.request = lambda method, url, **kw: sent.append((method, url, kw)) or Answer(200, {'id': 5})
client.get_model(5)
check('a GET is sent as before: its parameters, and no body',
      [(m, 'json' in kw, 'params' in kw) for m, u, kw in sent], [('GET', False, True)])
try:
    client.get_versions_by_hashes([sha(n) for n in range(101)])
    refused = False
except ValueError:
    refused = True
check("more than Civitai's 100 a call is refused before asking", refused, True)

# ------------------------------------------------------------ the word
check('"Download" allows downloads', on_site_only('Download'), False)
check('"Generation" is on-site only', on_site_only('Generation'), True)
check("and so is either word only Civitai's staff set", (on_site_only('InternalGeneration'),
                                                         on_site_only('ExternalGeneration')), (True, True))
check('no word is unknown, never either', (on_site_only(None), on_site_only('')), (None, None))


class Lookup:
    """Civitai's lookup by hash, answering what the test set, and counting its requests."""
    VERSIONS_BY_HASH_BATCH = 100

    def __init__(self, words=None, fail=False):
        self.words, self.fail, self.asked = words or {}, fail, []

    def get_versions_by_hashes(self, hashes):
        self.asked.append(list(hashes))
        if self.fail:
            raise RuntimeError('Civitai is down')
        return [dict(self.words[h], images=[{'url': 'x', 'meta': {'prompt': 'p' * 100}}])
                for h in hashes if h in self.words]


words = {sha(1): {'id': 1, 'usageControl': 'Download'}, sha(2): {'id': 2, 'usageControl': 'Generation'},
         sha(3): {'id': 3, 'usageControl': 'InternalGeneration'}, sha(4): {'id': 999, 'usageControl': 'Generation'}}
asked = {n: sha(n) for n in range(1, 151)}
asked[4] = sha(4)
lookup = Lookup(words)
check('150 versions are asked in two requests, 100 and 50, and answered by version: '
      'false, true, true; one Civitai answers for another version is left out, and so is one unanswered',
      (versions_on_site_only(lookup, asked), [len(a) for a in lookup.asked]),
      ({1: False, 2: True, 3: True}, [100, 50]))

# ------------------------------------------------------------ v43
old = os.path.join(WORK, 'v42', 'models.db')
os.makedirs(os.path.dirname(old))
conn = sqlite3.connect(old)
conn.execute("CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT)")
migrations.run_migrations(conn.cursor(), 0, 42, old, os.path.dirname(old))
conn.commit()
conn.close()
check('a v42 database has no version_records', 'version_records' in
      [r[0] for r in sqlite3.connect(old).execute("SELECT name FROM sqlite_master WHERE type = 'table'")], False)
dbmod.ModelsDatabase(os.path.dirname(old), custom_db_path=old)
with sqlite3.connect(old) as c:
    columns = [r[1] for r in c.execute('PRAGMA table_info(version_records)')]
    version = c.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()[0]
check('v43 adds it: a version, its model, each source and when', (columns, version),
      (['version_id', 'model_id', 'listed', 'listed_at', 'looked_up', 'looked_up_at'], str(dbmod.SCHEMA_VERSION)))
real_schema = dbmod.SCHEMA_VERSION
dbmod.SCHEMA_VERSION = 42
try:
    dbmod.ModelsDatabase(os.path.dirname(old), custom_db_path=old)
    fenced = False
except RuntimeError:
    fenced = True
dbmod.SCHEMA_VERSION = real_schema
check('and a copy at v42 refuses the v43 database', fenced, True)

# ------------------------------------------------------------ a sync writes records
db, facts = fixtures.build(os.path.join(WORK, 'library'))
dbmod._db_instance = db
models = facts['models_dir']
paths.models_path = models
sync_module.identify = lambda path: Architecture(None, None, False, False, 'LORA', 'read for the test')

KNOWN, MODELS = {}, {}      # file sha256 -> version payload; model id -> model payload


class Client(Lookup):
    """Civitai: the model's answer and the lookup, as the test set them."""

    def __init__(self, words=None, fail=False):
        super().__init__(words, fail)
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def get_model_by_hash(self, value):
        return KNOWN.get(value.upper())

    def get_model(self, model_id):
        return json.loads(json.dumps(MODELS.get(model_id))) if model_id in MODELS else None

    def get_models_by_ids(self, ids):
        return {i: self.get_model(i) for i in ids if i in MODELS}

    def get_model_images(self, version_id, cursor=None, limit=None):
        return {'items': [], 'metadata': {}}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def get_checkpoint_types(self, ids):
        return {}


def version(vid, file_sha, held_name=None):
    return {'id': vid, 'name': 'v%d' % vid, 'nsfwLevel': 1, 'baseModel': 'SDXL 1.0', 'stats': {'downloadCount': 3},
            'images': [{'url': 'https://image/%d' % vid, 'nsfwLevel': 1, 'meta': {'prompt': 'long ' * 50}}],
            'files': [{'id': vid * 10, 'name': held_name or 'v%d.safetensors' % vid, 'primary': True,
                       'hashes': {'SHA256': file_sha}}]}


def write(name, fill, size=64):
    path = os.path.join(models, 'Lora', name)
    io.open(path, 'wb').write(fill * size)
    return path


def file_sha(path):
    return SyncService(client=Client()).calculate_hashes(path).sha256.upper()


def model(model_id, versions):
    MODELS[model_id] = {'id': model_id, 'name': 'Model %d' % model_id, 'type': 'LORA', 'nsfwLevel': 1,
                        'modelVersions': versions}
    for v in versions:
        KNOWN[v['files'][0]['hashes']['SHA256']] = dict(v, modelId=model_id)


def records(model_id):
    with sqlite3.connect(facts['db_path']) as c:
        return {r[0]: (json.loads(r[1]) if r[1] else None, json.loads(r[2]) if r[2] else None)
                for r in c.execute('SELECT version_id, listed, looked_up FROM version_records WHERE model_id = ? '
                                   'ORDER BY version_id', (model_id,))}


ONE = write('one.safetensors', b'a')
model(8100, [version(8101, file_sha(ONE), 'one.safetensors'), version(8102, sha(8102))])
db.insert_missing_versions([{'file_path': ONE, 'file_name': 'one.safetensors'}])
civitai = Client({file_sha(ONE): {'id': 8101, 'usageControl': 'Download'},
                  sha(8102): {'id': 8102, 'usageControl': 'Generation'}})
SyncService(client=civitai).sync_model(ONE, force=True)
held = records(8100)
check('a sync records every version the model lists, held and not', sorted(held), [8101, 8102])
check("each as the model's answer said it, without its images",
      [(r[0]['id'], 'images' in r[0], r[0]['stats']) for r in held.values()],
      [(8101, False, {'downloadCount': 3}), (8102, False, {'downloadCount': 3})])
check('then asks the lookup once, about both', civitai.asked, [sorted([file_sha(ONE), sha(8102)])])
check("and keeps what it said beside each, without its images",
      {v: (r[1]['usageControl'], 'images' in r[1]) for v, r in held.items()},
      {8101: ('Download', False), 8102: ('Generation', False)})
check('read back as words', db.version_usage_controls([8101, 8102, 8199]), {8101: 'Download', 8102: 'Generation'})

# The model's answer written again keeps what the lookup said.
MODELS[8100]['modelVersions'][1]['stats'] = {'downloadCount': 9}
SyncService(client=Client(fail=True)).sync_model(ONE, force=True)
again = records(8100)
check("a sync whose lookup fails writes the model's answer, and keeps the lookup's",
      (again[8102][0]['stats'], (again[8102][1] or {}).get('usageControl')), ({'downloadCount': 9}, 'Generation'))

# A version gone from Civitai's list loses its record.
MODELS[8100]['modelVersions'] = MODELS[8100]['modelVersions'][:1]
SyncService(client=Client()).sync_model(ONE, force=True)
check('a version the list no longer names loses its record', sorted(records(8100)), [8101])

# ---------------------------------------- one lookup per 100 versions, once
MANY = write('many.safetensors', b'b')
model(8200, [version(8201, file_sha(MANY), 'many.safetensors')] + [version(8201 + n, sha(8201 + n)) for n in range(1, 150)])
db.insert_missing_versions([{'file_path': MANY, 'file_name': 'many.safetensors'}])
civitai = Client()
SyncService(client=civitai).sync_model(MANY, force=True)
check('150 versions of a model: two lookups, 100 and 50', [len(a) for a in civitai.asked], [100, 50])

# ---------------------------------------- the estimate
estimate = estimate_metadata_sync(model_paths=[MANY])
check('the sync estimate counts a lookup per hundred versions listed',
      (estimate['requests']['lookups'], estimate['requests']['total'] - estimate['requests']['metadata']
       - estimate['requests']['checkpoints']), (2, 2))

# A model forgotten takes its records with it.
db.delete_version(MANY)
db.prune_orphans()
check("a model forgotten, its file gone, takes its 150 records with it", records(8200), {})

# Two files no sync has read: a sync from the dialog skips one it has.
TWO = write('two.safetensors', b'c')
model(8300, [version(8301, file_sha(TWO), 'two.safetensors')])
THREE = write('three.safetensors', b'f')
model(8500, [version(8501, file_sha(THREE), 'three.safetensors'), version(8502, sha(8502))])
db.insert_missing_versions([{'file_path': p, 'file_name': os.path.basename(p)} for p in (TWO, THREE)])
civitai = Client()
service = SyncService(client=civitai)
service.sync_all(model_paths=[TWO, THREE], max_workers=1)
check("a sync of two models' files asks once at its end, about every version of both",
      [sorted(a) for a in civitai.asked], [sorted([file_sha(TWO), file_sha(THREE), sha(8502)])])

# The bar counts the lookups: below 100% while they run, saying so, and full once done.
WIDE = write('wide.safetensors', b'g')
model(8600, [version(8601, file_sha(WIDE), 'wide.safetensors')] + [version(8601 + n, sha(8601 + n)) for n in range(1, 150)])
db.insert_missing_versions([{'file_path': WIDE, 'file_name': 'wide.safetensors'}])
during = []
watched = Client()
service = SyncService(client=watched)
real_lookup = watched.get_versions_by_hashes
def watching(hashes):
    p = service._progress
    during.append((p.processed, p.total, 'allow downloads' in (p.current_model or '')))
    return real_lookup(hashes)
watched.get_versions_by_hashes = watching
# Synced once already, so its list is stored: the sync knows its lookups from the start.
SyncService(client=Client()).sync_model(WIDE, force=True)
totals = []
real_model = watched.get_model
def model_seen(model_id):
    totals.append((service._progress.processed, service._progress.total))
    return real_model(model_id)
watched.get_model = model_seen
progress = service.sync_all(model_paths=[WIDE], max_workers=1, force=True)
check('the total counts the lookups from the start: 1 file and 2 lookups, before the file is synced',
      totals[:1], [(0, 3)])
check('during each of the two lookups the bar is below full, and says what it is doing',
      during, [(1, 3, True), (2, 3, True)])
check('and full once they are done', (progress.processed, progress.total), (3, 3))

# Civitai answers a version once per file of it a hash matches: counted once.
twice = Client({file_sha(TWO): {'id': 8301, 'usageControl': 'Download'}})
twice.get_versions_by_hashes = lambda hashes: [{'id': 8301, 'usageControl': 'Download'}] * 2
service = SyncService(client=twice)
with service._listed_lock:
    service._listed_models = {8300}
check('a version Civitai answers twice is counted once', service.look_up_listed_versions(), 1)

# And across requests: a version comes back in a later one too, for a file another version shares.
across = Client()
across.get_versions_by_hashes = lambda hashes: [{'id': 8601 + n, 'usageControl': 'Download'} for n in range(150)]
service = SyncService(client=across)
with service._listed_lock:
    service._listed_models = {8600}
check('a version answered in two requests is counted once: 150 of 150', service.look_up_listed_versions(), 150)

# A model's Sync: every file, then the lookup once.
SECOND = write('second.safetensors', b'd')
MODELS[8300]['modelVersions'].append(version(8302, file_sha(SECOND), 'second.safetensors'))
KNOWN[file_sha(SECOND)] = dict(MODELS[8300]['modelVersions'][1], modelId=8300)
db.insert_missing_versions([{'file_path': SECOND, 'file_name': 'second.safetensors'}])
SyncService(client=Client()).sync_model(SECOND, force=True)
civitai = Client()
sync_module.CivitaiClient = type('Stub', (), {'from_settings': staticmethod(lambda: civitai),
                                             'VERSIONS_BY_HASH_BATCH': 100})
app = FastAPI()
setup_api(app)
http = TestClient(app)
answer = http.post('/model-manager/models/force-sync', data={'model_id': 8300}).json()
check("a model's Sync of its two files asks the lookup once, after both",
      (answer.get('synced_count'), len(civitai.asked)), (2, 1))

# ---------------------------------------- the panel reads what was stored
called = []


class NotAsked:
    @staticmethod
    def from_settings():
        called.append(True)
        raise AssertionError('Civitai was asked')


real_models_client = models_api.CivitaiClient
models_api.CivitaiClient = NotAsked
listed = http.get('/model-manager/models/versions', params={'model_id': 8100}).json()
check("the Model Manager's versions say on-site only from the records, and Civitai is not asked",
      ([(v['id'], v['on_site_only']) for v in listed['civitai_versions']], called), ([(8101, False)], []))
# A list stored before v43 - or from a sidecar - has no records.
with sqlite3.connect(facts['db_path']) as c:
    c.execute("INSERT INTO models (id, name, versions) VALUES (8400, 'Model 8400', ?)",
              (json.dumps([{'id': 8401, 'name': 'v8401', 'files': []}]),))
listed = http.get('/model-manager/models/versions', params={'model_id': 8400}).json()
check('a model with no record: unknown, and still no call',
      ([(v['id'], v['on_site_only']) for v in listed['civitai_versions']], called), ([(8401, None)], []))
models_api.CivitaiClient = real_models_client

# ---------------------------------------- the Civitai Browser's route
browser = Client({sha(1): {'id': 1, 'usageControl': 'Generation'}, sha(2): {'id': 2, 'usageControl': 'Download'}})
real_browser_client = civitai_api.CivitaiClient
civitai_api.CivitaiClient = type('Stub', (), {'from_settings': staticmethod(lambda: browser)})
browser.close = lambda: None
said = http.get('/model-manager/civitai/usage',
                params={'versions': '1:%s,2:%s,3:%s,bad,4:short' % (sha(1), sha(2), sha(3))}).json()
check('the route answers each version Civitai answered; one unanswered, and the malformed, left out',
      (said, browser.asked), ({'success': True, 'versions': {'1': True, '2': False}}, [[sha(1), sha(2), sha(3)]]))
browser.fail = True
said = http.get('/model-manager/civitai/usage', params={'versions': '1:%s' % sha(1)})
check('Civitai failing: success false, and why', (said.json().get('success'), bool(said.json().get('error'))),
      (False, True))
civitai_api.CivitaiClient = real_browser_client

# ---------------------------------------- the notice
note = next(n for n in release_notes.load_notes() if n['id'] == 'on-site-only-sync')
check('the notice asking for a sync shows to an install updating, and opens the sync dialog',
      (release_notes.applies(note, '0.60.2'), note['action']['id'], note['tabs']), (True, 'sync', ['model_manager']))
check('not to a fresh install, whose first sync stores it all', release_notes.applies(note, '0.61.0'), False)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
