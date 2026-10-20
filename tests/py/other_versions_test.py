"""
The versions of an image's checkpoint's model the library holds (#278): what
a stopped Send's Resources dialog offers to send with when the image's own
checkpoint is missing - and sending a Civitai image with one, through the
route its Send asks (forge-modules, `use_version`).

Any version of the model, whatever its base model, each naming its own;
newest first by Civitai's stored order, one Civitai no longer lists last;
only checkpoint files held here.
"""
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

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.forge_host as host                  # noqa: E402
import model_manager.model_dirs as dirs                  # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'other_versions')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
raw = db._get_connection()

# The fixture's first checkpoint model holds two versions, v1 and v2.
MODEL = facts['checkpoint_ids'][0]
V1, V2 = facts['version_ids'][0], facts['version_ids'][1]
P1, P2 = facts['linked_paths'][0], facts['linked_paths'][1]
IMAGE_VERSION = 2999                     # the image's, which the library lacks
raw.execute("UPDATE files SET file_type = 'Checkpoint' WHERE file_path IN (?, ?)", (P1, P2))
raw.commit()
not_here = set()
dirs.loads_here = lambda path, *a, **k: path not in not_here
db.store_civitai_versions(MODEL, [{'id': IMAGE_VERSION, 'name': 'v3'}, {'id': V2, 'name': 'v2'},
                                  {'id': V1, 'name': 'v1'}], from_civitai=True)

from model_manager import resources                      # noqa: E402

# Looked up, not imported: on the code before #278 its checks fail, rather than the suite.
other_versions = getattr(resources, 'other_versions', lambda *args: [])


def ids(found):
    return [v['version_id'] for v in found]


found = other_versions(db, IMAGE_VERSION, MODEL)
check('the image used v3, the library holds v1 and v2: both offered, newest first by Civitai\'s order',
      ids(found), [V2, V1])
check('each with its name, base model and file',
      found[:1], [{'version_id': V2, 'version_name': 'v2', 'base_model': 'SDXL 1.0', 'file_name': os.path.basename(P2)}])
check('the image\'s own version is never offered', ids(other_versions(db, V2, MODEL)), [V1])

db.store_civitai_versions(MODEL, [{'id': V1, 'name': 'v1'}, {'id': V2, 'name': 'v2'}], from_civitai=True)
check('Civitai\'s order, not the library\'s', ids(other_versions(db, IMAGE_VERSION, MODEL)), [V1, V2])
db.store_civitai_versions(MODEL, [{'id': IMAGE_VERSION, 'name': 'v3'}, {'id': V1, 'name': 'v1'}], from_civitai=True)
check('a version Civitai no longer lists comes last', ids(other_versions(db, IMAGE_VERSION, MODEL)), [V1, V2])

raw.execute("UPDATE versions SET base_model = 'SD 1.5' WHERE id = ?", (V1,))
raw.commit()
check('a version made for another base model is offered too, naming its own',
      [(v['version_id'], v['base_model']) for v in other_versions(db, IMAGE_VERSION, MODEL)],
      [(V1, 'SD 1.5'), (V2, 'SDXL 1.0')])

not_here.add(P1)
check('a file in a folder only the other WebUI loads is not offered', ids(other_versions(db, IMAGE_VERSION, MODEL)), [V2])
not_here.clear()

raw.execute("UPDATE files SET file_type = 'VAE' WHERE file_path = ?", (P1,))
raw.commit()
check('a VAE filed under the model is not offered', ids(other_versions(db, IMAGE_VERSION, MODEL)), [V2])
raw.execute("UPDATE files SET file_type = 'Checkpoint' WHERE file_path = ?", (P1,))
raw.commit()

check('a model the library holds nothing of: nothing', other_versions(db, IMAGE_VERSION, 999999), [])

# ------------------------------------------------------------- the routes
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))
body = client.get('/model-manager/other-versions', params={'version_id': IMAGE_VERSION, 'model_id': MODEL}).json()
check('the route answers the same list', (body.get('success'), ids(body.get('versions') or [])), (True, [V1, V2]))

# A Civitai image's Send, from a LoRA's gallery: the image names v3, which
# the library lacks; asked with use_version, the checkpoint is the file of
# the version picked, and the answer names it.
import model_manager.identity_store as store             # noqa: E402
import model_manager.send_plan as sp                       # noqa: E402
sp._ask_civitai = lambda kind, value: None                 # a suite asks Civitai nothing
store.needs_check = lambda db_, path: None                 # read already, as stored
for path in (P1, P2):
    db.set_architecture(path, 'sd', 'SD1', False, False, '1234', file_type='Checkpoint')
host.installed_modules = lambda: {}
host.saved_modules = lambda preset: []
host.checkpoint_name = lambda path: {P1: 'model_v0.safetensors [1111]'}.get(path)
LORA = [p for p in facts['linked_paths'] if os.sep + 'Lora' + os.sep in p][0]
image = {'file_path': LORA, 'version_ids': str(IMAGE_VERSION), 'model_name': 'v3_checkpoint'}


def plan(**params):
    """A Civitai image's plan as its own route answered it until #302 removed the route."""
    from model_manager import send
    p = {**image, **params}
    return json.loads(json.dumps(send.civitai_plan(
        db, p.get('file_path', ''), p.get('base_model', ''), p.get('version_ids', ''), p.get('hashes', ''),
        p.get('model_name', ''), p.get('vae', ''), list(p.get('module') or []), int(p.get('use_version') or 0))))


body = plan(use_version=V1)
check('use_version: the checkpoint is the library\'s file of that version, and the answer names it',
      (body.get('checkpoint'), body.get('instead'), body.get('checkpoint_problem')),
      ('model_v0.safetensors [1111]', os.path.basename(P1), None))
body = plan()
check('without it: the image\'s own checkpoint, missing, as before, and nothing said instead',
      (body.get('checkpoint_problem'), 'instead' in body), ({'reason': 'missing', 'name': 'v3_checkpoint'}, False))
check('and use_version=0 answers exactly as no use_version', plan(use_version=0), plan())

# The image's checkpoint, missing, may be a file the library holds under
# another Civitai model - one checkpoint uploaded twice (#304). The Resources
# dialog's answer about the missing version names it, matched by the file's
# own hash, never its name.
SHA = 'AB' * 32
raw.execute("UPDATE files SET file_hashes = ? WHERE file_path = ?", (json.dumps({'sha256': SHA, 'autov2': SHA[:10]}), P1))
raw.commit()
REUPLOAD, ITS_VERSION = 777001, 777002


class Civitai(object):
    def __init__(self, hashes, name='reupload.safetensors'):
        self.hashes, self.name = hashes, name

    def get_models_by_ids(self, ids, nsfw=True):
        return {REUPLOAD: {'type': 'Checkpoint', 'name': 'A re-upload', 'modelVersions': [
            {'id': ITS_VERSION, 'name': 'v1.0', 'files': [{'name': self.name, 'primary': True, 'type': 'Model',
                                                          'hashes': self.hashes}]}]}}

    def get_model(self, model_id):
        return None


def missing(hashes, name='reupload.safetensors'):
    resources._MISSING_FILES.clear()
    answer = resources.missing_files(db, [{'version_id': ITS_VERSION, 'model_id': REUPLOAD}], [],
                                     lambda: Civitai(hashes, name))
    return (answer['versions'].get(str(ITS_VERSION)) or {}).get('same_file')


same = missing({'SHA256': SHA})
check('the same SHA-256: the library\'s version and file named, as the dialog\'s Send uses it',
      [(same or {}).get('version_id'), (same or {}).get('file_name')], [V1, os.path.basename(P1)])
check('Civitai giving no SHA-256: its AutoV2', (missing({'AutoV2': SHA[:10]}) or {}).get('version_id'), V1)
check('another hash, the same file name: not the same file', missing({'SHA256': 'CD' * 32}, os.path.basename(P1)), None)
held = dirs.held_here
dirs.held_here = lambda path: False
check('the same file, but not held here: nothing to send with', missing({'SHA256': SHA}), None)
dirs.held_here = held

print('\n'.join('FAIL ' + f for f in fails) if fails else 'All checks passed.')
sys.exit(1 if fails else 0)
