"""
Records other tools keep beside a model, read for a model Civitai has
deleted (#350, other_records.py).

A sync reads a record only when Civitai knows no hash of the file and has
no model by the id the record names. Its own .civitai.info comes first, as
ever; then any other tool's, by the keys inside, each checked as far as its
contents allow: tier 1 lists the file's SHA-256, tier 2 names the file at
its size, tier 3 has ids alone and is taken only when no record of tiers 1
or 2 sits beside the file. A file already marked "not on Civitai" before
these were read gets one try, asking only about the model.

The records are made up, each in its tool's shape as the tool's source
writes it (the survey linked from #350).
"""
import hashlib
import io
import json
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
import model_manager.sync_service as sync_module         # noqa: E402
from modules import paths                                # noqa: E402  (webui_stub's)
from model_manager import console                        # noqa: E402
from model_manager.architecture import Architecture     # noqa: E402
from model_manager.civitai import CivitaiAPIError, TokenBucketRateLimiter  # noqa: E402
from model_manager.hashing import HashResult, fingerprint  # noqa: E402
from model_manager.sync_service import SyncService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'other_records')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
paths.models_path = facts['models_dir']
LORA = os.path.join(facts['models_dir'], 'Lora')
sync_module.identify = lambda path: Architecture(None, None, False, False, 'LORA', 'read for the test')


class Client:
    """Civitai, with none of these files and no model but those given."""

    def __init__(self, models=None, down=False):
        self.models = models or {}
        self.down = down
        self.asked = []
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def get_model_by_hash(self, value):
        self.asked.append(('by_hash', value))
        return None

    def get_model(self, model_id):
        self.asked.append(('model', model_id))
        if self.down:
            raise CivitaiAPIError('Civitai is down')
        return self.models.get(model_id)


made = [0]

def lora(name):
    """A LoRA no other has the bytes of, with its row, as the walk gives it."""
    made[0] += 1
    path = os.path.join(LORA, name + '.safetensors')
    io.open(path, 'wb').write(('lora %d %s' % (made[0], name)).encode() * 50)
    db.insert_missing_versions([{'file_path': path, 'file_name': os.path.basename(path)}])
    return path


def sha(path):
    return hashlib.sha256(io.open(path, 'rb').read()).hexdigest().upper()


def beside(path, suffix, content):
    target = os.path.splitext(path)[0] + suffix
    os.makedirs(os.path.dirname(target), exist_ok=True)
    io.open(target, 'w', encoding='utf-8').write(content if isinstance(content, str) else json.dumps(content))


def sync(path, **client):
    service = SyncService(client=Client(**client))
    start = console.said()
    service.sync_model(path, look_up=False)
    lines = [l['text'] for l in console.since(start)[0]]
    return service.client, lines


def filed(path):
    """(version id, model id, base model, model name) as the library holds them."""
    row = db.get_version(path) or {}
    model = db.get_civitai_model(row['model_id']) if row.get('model_id') else None
    return (row.get('id'), row.get('model_id'), row.get('base_model'), (model or {}).get('name'))


def version_record(model_id, version_id, path, digest, base='Krea 2', name='Deleted LoRA'):
    """Civitai's answer to /model-versions/by-hash: the model inside."""
    return {'id': version_id, 'modelId': model_id, 'name': 'v1', 'baseModel': base,
            'trainedWords': ['kw'], 'model': {'name': name, 'type': 'LORA', 'nsfw': False},
            'files': [{'id': version_id * 10, 'name': os.path.basename(path),
                       'hashes': {'SHA256': digest}}]}


# ------------------------------------------------------------- tier 1, hashes
p = lora('neo_api_info')
beside(p, '.api_info.json', version_record(9100, 9101, p, sha(p)))
client, lines = sync(p)
check('1. a deleted model\'s LoRA with only .api_info.json is filed: version, model, base model, name',
      filed(p), (9101, 9100, 'Krea 2', 'Deleted LoRA'))
check('   and the console names the record', any('filed as its .api_info.json says' in l for l in lines))

p = lora('plus_api_info')
beside(p, '.api_info.json', {'id': 9200, 'name': 'Two Versions', 'type': 'LORA', 'modelVersions': [
    {'id': 9201, 'name': 'v2', 'baseModel': 'Pony', 'files': [{'name': 'other.safetensors', 'hashes': {'SHA256': 'AB' * 32}}]},
    {'id': 9202, 'name': 'v1', 'baseModel': 'Illustrious', 'files': [{'name': 'x', 'hashes': {'SHA256': sha(p)}}]}]})
sync(p)
check('2. a model record with two versions: the one listing the file\'s hash is filed',
      filed(p), (9202, 9200, 'Illustrious', 'Two Versions'))

p = lora('lora_manager')
inner = version_record(9300, 9301, p, sha(p).lower(), base='Flux.1 D', name=None)
inner['model'] = {'type': 'LORA'}
beside(p, '.metadata.json', {'file_name': 'lora_manager', 'sha256': sha(p).lower(), 'model_name': 'From LM',
                             'base_model': 'Flux.1 D', 'civitai': inner, 'civitai_deleted': True})
sync(p)
check('3. Lora Manager\'s .metadata.json is filed, its name from model_name',
      filed(p), (9301, 9300, 'Flux.1 D', 'From LM'))

p = lora('lora_manager_half')
inner = version_record(9350, 9351, p, 'AB' * 32, name='Wrong Version')
beside(p, '.metadata.json', {'file_name': 'lora_manager_half', 'sha256': sha(p), 'model_name': 'Half',
                             'civitai': inner})
sync(p)
check('3. Lora Manager\'s own SHA-256 matching, its Civitai record listing another file\'s: nothing filed',
      filed(p)[0], None)

for suffix, model_id, names in (('.cm-info.json', 9400, ('ModelName', 'RemoteFileName')),
                                ('.cminfo.json', 9410, ('ModelName', 'PrimaryFileName'))):
    p = lora('pascal' + suffix.replace('.', '_'))
    beside(p, suffix, {'ModelId': model_id, names[0]: 'Pascal', 'ModelType': 'LORA', 'VersionId': model_id + 1,
                       'VersionName': 'v1', 'BaseModel': 'SDXL 1.0', names[1]: os.path.basename(p),
                       'Hashes': {'SHA256': sha(p), 'BLAKE3': 'b3'}, 'TrainedWords': ['a', 'b']})
    sync(p)
    check('4. %s is filed' % suffix, filed(p), (model_id + 1, model_id, 'SDXL 1.0', 'Pascal'))

for label, record, want in (
        ('its baseModel', {'baseModel': 'Krea 2', 'sd version': 'Krea 2'}, 'Krea 2'),
        ('a raw sd version, as Neo wrote it before baseModel', {'sd version': 'NoobAI'}, 'NoobAI'),
        ('never a cut-down sd version', {'sd version': 'SDXL'}, None),
        ('nor "Other"', {'sd version': 'Other'}, None)):
    p = lora('browser_' + str(len(fails)) + str(made[0]))
    model_id = 9500 + made[0]
    beside(p, '.json', dict(record, modelId=model_id, modelVersionId=model_id * 10, sha256=sha(p),
                            **{'activation text': 'one, two', 'description': 'x'}))
    sync(p)
    check('5. a Browser .json is filed, base model from ' + label + '; named as the file, giving no name',
          filed(p), (model_id * 10, model_id, want, os.path.splitext(os.path.basename(p))[0]))

# --------------------------------------------------- guards on the check itself
p = lora('wrong_then_right')
beside(p, '.api_info.json', version_record(9600, 9601, p, 'CD' * 32))
beside(p, '.cm-info.json', {'ModelId': 9610, 'ModelName': 'Right', 'VersionId': 9611, 'BaseModel': 'Pony',
                            'Hashes': {'SHA256': sha(p)}})
sync(p)
check('7. a record not listing the file\'s SHA-256 is skipped, and the next one filed',
      filed(p), (9611, 9610, 'Pony', 'Right'))

p = lora('model_not_found')
beside(p, '.json', {'modelId': 'Model not found', 'modelVersionId': 'Model not found', 'sha256': sha(p)})
client, _ = sync(p)
check('8. "Model not found" as the ids: nothing filed, and no model asked about',
      (filed(p)[0], [a for a in client.asked if a[0] == 'model']), (None, []))
p = lora('empty_ids')
beside(p, '.civitai.info', {'id': '', 'modelId': '', 'baseModel': 'Unknown', 'skeleton_file': True,
                            'model': {'name': '', 'type': ''}, 'files': [{'hashes': {'SHA256': ''}}]})
sync(p)
check('8. a skeleton\'s empty ids: nothing filed', filed(p)[0], None)

p = lora('model_still_there')
beside(p, '.api_info.json', version_record(9700, 9701, p, sha(p)))
client, _ = sync(p, models={9700: {'id': 9700, 'name': 'Alive', 'modelVersions': []}})
check('9. the model is still on Civitai: nothing filed (unchanged rule)',
      (filed(p)[0], ('model', 9700) in client.asked), (None, True))

p = lora('own_info_first')
beside(p, '.civitai.info', {'id': 9800, 'name': 'Own', 'type': 'LORA', 'modelVersions': [
    {'id': 9801, 'name': 'v', 'baseModel': 'SD 1.5', 'files': [{'name': os.path.basename(p)}]}]})
beside(p, '.api_info.json', version_record(9810, 9811, p, sha(p)))
sync(p)
check('10. its own .civitai.info naming a version: used as before, other records not read',
      filed(p), (9801, 9800, 'SD 1.5', 'Own'))

# -------------------------------------------- the rest of tier 1, and tier 2
p = lora('civbrowser')
beside(p, '.civitai.json', {'id': 9900, 'name': 'Civ', 'infoVersion': '2.5', 'versionId': 9901, 'baseModel': 'Pony',
                            'modelVersions': [{'id': 9901, 'baseModel': 'Pony',
                                               'files': [{'name': os.path.basename(p), 'hashes': {'SHA256': sha(p)}}]}]})
sync(p)
check('13. civbrowser\'s .civitai.json is filed', filed(p), (9901, 9900, 'Pony', 'Civ'))

p = lora('freetool')
beside(p, '.civitai.info', {'id': 10000, 'modelId': 10000, 'name': 'Free', 'type': 'LORA', 'versionId': 10001,
                            'baseModel': 'Illustrious', 'version': {'id': 10001, 'name': 'v1'},
                            'files': [{'name': os.path.basename(p), 'hashes': {'SHA256': sha(p)}}]})
sync(p)
check('13. CivitaiFreeTool\'s .civitai.info is filed, its id read as the model\'s, never the version\'s',
      filed(p), (10001, 10000, 'Illustrious', 'Free'))

p = lora('hayden_md')
beside(p, '.md', '---\nwebsite: Civitai\nmodelPage: https://civitai.com/models/10100?modelVersionId=10101\n'
                 'author: someone\nbaseModel: Krea 2\nhashes:\n  SHA256: %s\n---\n\n# Trigger Words\n\nred, blue\n' % sha(p))
sync(p)
check('13. ComfyUI-Model-Manager\'s .md is filed from its front matter', filed(p), (10101, 10100, 'Krea 2', 'hayden_md'))

p = lora('civimeta')
beside(p, '.safetensors.civitai/meta.json', {'name': 'Meta', 'versionName': 'v', 'modelId': 10200, 'versionId': 10201,
                                             'baseModel': 'Wan Video', 'hash': sha(p).lower()})
sync(p)
check('13. CiviMeta\'s folder is filed', filed(p), (10201, 10200, 'Wan Video', 'Meta'))

p = lora('go_downloader')
beside(p, '.json', version_record(10300, 10301, p, sha(p), base='Qwen', name='Go'))
sync(p)
check('13. Civitai\'s version record in a .json (go-civitai-downloader) is filed', filed(p), (10301, 10300, 'Qwen', 'Go'))

size_kb = os.path.getsize(lora('probe_size')) / 1024
for label, kb, want in (('filed when name and size match', size_kb, 10401), ('refused when the size differs', size_kb + 5, None)):
    p = lora('scraper_%d' % made[0])
    beside(p, '.json', {'id': 10401, 'modelId': 10400, 'baseModel': 'Pony', 'name': 'v1',
                        'files': [{'name': os.path.basename(p), 'sizeKb': kb}]})
    sync(p)
    check('14. CivitScraper\'s own record, ' + label, filed(p)[0], want)

# ------------------------------------------------------- tier 3, unchecked
for label, suffix, record, ids in (
        ('CivitaiManager\'s .json', '.json',
         {'source': 'civitai', 'model_id': 10500, 'version_id': 10501, 'name': 'Snake', 'base_model': 'Pony'}, (10501, 10500)),
        ('Forge notes with a model url', '.json',
         {'description': '', 'sd version': 'Pony', 'activation text': 'a', 'preferred weight': 0,
          'model url': 'https://civitai.com/models/10600?modelVersionId=10601'}, (10601, 10600)),
        ('SwarmUI\'s .swarm.json', '.swarm.json',
         {'modelspec.title': 'Swarm - v1', 'modelspec.usage_hint': 'Flux.1 D',
          'modelspec.description': 'From <a href="https://civitai.com/models/10700?modelVersionId=10701">x</a>'}, (10701, 10700))):
    p = lora('tier3_%d' % made[0])
    beside(p, suffix, record)
    _, lines = sync(p)
    check('15. %s is filed' % label, filed(p)[:2], ids)
    check('    and the console says unchecked', any('unchecked: it names no hash of the file' in l for l in lines))

p = lora('failing_beside_unchecked')
beside(p, '.api_info.json', version_record(10800, 10801, p, 'EF' * 32))
beside(p, '.swarm.json', {'modelspec.title': 'S',
                          'modelspec.description': 'https://civitai.com/models/10810?modelVersionId=10811'})
sync(p)
check('16. a tier-1 record failing its check, a tier-3 one beside it: nothing filed', filed(p)[0], None)

p = lora('url_no_version')
beside(p, '.swarm.json', {'modelspec.title': 'S', 'modelspec.description': 'https://civitai.com/models/10900'})
sync(p)
check('17. a URL with no modelVersionId: nothing filed', filed(p)[0], None)
p = lora('md_no_front')
beside(p, '.md', '# A note\n\nmodelPage: https://civitai.com/models/11000?modelVersionId=11001\n')
sync(p)
check('17. a .md with no front matter: nothing filed', filed(p)[0], None)

# ------------------------------- files already marked: one try, the model only
def mark(path, when):
    with db._cursor() as cursor:
        cursor.execute('UPDATE files SET civitai_lookup_failed_at = ? WHERE file_path = ?', (when, path))


p = lora('marked_before')
sync(p)                                     # marked, its hashes kept as its own
check('    (a file Civitai does not know is marked, its hashes its own)',
      (bool(db.get_version(p)['civitai_lookup_failed_at']), db.get_version(p)['hashes_checked']), (True, fingerprint(p)))
mark(p, '2026-10-01T10:00:00')
beside(p, '.api_info.json', version_record(11100, 11101, p, sha(p)))
client, _ = sync(p)
check('6. a file marked before this release, with .api_info.json, is filed at a plain sync',
      filed(p), (11101, 11100, 'Krea 2', 'Deleted LoRA'))
check('   with 1 request, for the model, and no hash lookup', client.asked, [('model', 11100)])
client, _ = sync(p)
check('12. the next sync skips it: no second request', client.asked, [])

for label, when, record in (('marked after this release', '2026-11-01T10:00:00', True),
                            ('marked before, with no record', '2026-10-01T10:00:00', False)):
    p = lora('marked_%d' % made[0])
    sync(p)
    mark(p, when)
    if record:
        beside(p, '.api_info.json', version_record(11200 + made[0], 11201, p, sha(p)))
    client, _ = sync(p)
    check('11. a file %s: skipped with no request' % label, (filed(p)[0], client.asked), (None, []))

p = lora('marked_civitai_down')
sync(p)
mark(p, '2026-10-01T10:00:00')
beside(p, '.api_info.json', version_record(11300, 11301, p, sha(p)))
client, _ = sync(p, down=True)
check('    Civitai down for the try: nothing filed, the mark left for the next sync',
      (filed(p)[0], db.get_version(p)['civitai_lookup_failed_at']), (None, '2026-10-01T10:00:00'))
client, _ = sync(p)
check('    which tries again', filed(p)[0], 11301)

if fails:
    print('%d of the other-records checks failed:' % len(fails))
    for f in fails:
        print(' FAIL', f)
    sys.exit(1)
print('All other-records checks passed.')
