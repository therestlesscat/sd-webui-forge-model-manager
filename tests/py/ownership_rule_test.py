"""
Whether the library holds a model: one rule, for search and details (#76).

The Civitai Browser's search cards called a model owned if any file in the
library belongs to it; its details panel only if one of the versions Civitai
lists now is held. A model held through a version Civitai has since deleted
was "Owned" on its card and not in its details, which then hid "Show in
Model Manager" - the file there all along. What is checked: both answer
alike - for that model, for one held through a listed version, and for one
not held - and no endpoint module reads the database with a cursor of its
own.

Held means one thing everywhere (#188, #189): a library row whose file is on
disk, in a folder this WebUI loads from (model_dirs.held_here). A row whose
file is gone, or the other WebUI's file, is not held - but is listed, and
"Show in MM" goes by that, as the Model Manager lists it. And a version is
held file by file: having its fp16 is not having its fp32.
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'ownership_rule')
webui_stub.install(models_path=os.path.join(WORK, 'models'))

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.api.civitai as civitai_api          # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.api.annotations import annotate_local_ownership  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
LIB = os.path.join(WORK, 'models', 'Lora')            # a folder this WebUI loads from
AWAY = os.path.join(WORK, 'elsewhere')                # the other WebUI's, say
os.makedirs(AWAY, exist_ok=True)


def library_file(folder, name, model_id, version_id, file_id=None, on_disk=True):
    path = os.path.join(folder, name)
    if on_disk:
        open(path, 'wb').write(b'weights')
    db.upsert_version({'file_path': path, 'file_name': name, 'id': version_id, 'model_id': model_id,
                       'civitai_file_id': file_id, 'has_civitai_data': True})


# Model 4242: held through version 42420, which Civitai lists no more.
# Model 4343: held through 43431, which it still lists.
library_file(LIB, 'old_version.safetensors', 4242, 42420)
library_file(LIB, 'listed.safetensors', 4343, 43431, file_id=434311)
# Model 4545: its row stays, its file is gone - deleted by hand (#188).
library_file(LIB, 'gone.safetensors', 4545, 45451, on_disk=False)
# Model 4646: on disk, in a folder this WebUI does not load from.
library_file(AWAY, 'away.safetensors', 4646, 46461)
# Model 4747: version 47471's fp16 is held, its fp32 not (#189).
library_file(LIB, 'two_files_fp16.safetensors', 4747, 47471, file_id=474711)

PAYLOADS = {
    4242: {'id': 4242, 'name': 'Deleted version held', 'modelVersions': [{'id': 42421}, {'id': 42422}]},
    4343: {'id': 4343, 'name': 'Listed version held', 'modelVersions': [{'id': 43430}, {'id': 43431}]},
    4444: {'id': 4444, 'name': 'Not held', 'modelVersions': [{'id': 44441}]},
    4545: {'id': 4545, 'name': 'File gone', 'modelVersions': [{'id': 45451}]},
    4646: {'id': 4646, 'name': 'Other WebUI\'s file', 'modelVersions': [{'id': 46461}]},
    4747: {'id': 4747, 'name': 'One file of two held',
           'modelVersions': [{'id': 47471, 'files': [{'id': 474711}, {'id': 474712}]}]},
}


class Civitai(object):
    @classmethod
    def from_settings(cls):
        return cls()

    def get_model(self, model_id):
        import copy
        return copy.deepcopy(PAYLOADS.get(model_id))

    def close(self):
        pass


civitai_api.CivitaiClient = Civitai
app = FastAPI()
setup_api(app)
http = TestClient(app)


def searched(model_id):
    import copy
    model = copy.deepcopy(PAYLOADS[model_id])
    annotate_local_ownership(db, [model])
    return model


def detailed(model_id):
    return http.get('/model-manager/civitai/models/%d' % model_id).json()['model']


# (model, owned, owned versions, listed - Show in MM - and each version's held files)
CASES = ((4242, True, [], True, {42421: [], 42422: []}),
         (4343, True, [43431], True, {43430: [], 43431: [434311]}),
         (4444, False, [], False, {44441: []}),
         (4545, False, [], True, {45451: []}),
         (4646, False, [], True, {46461: []}),
         (4747, True, [47471], True, {47471: [474711]}))
for model_id, owned, versions, listed, files in CASES:
    card, details = searched(model_id), detailed(model_id)
    name = PAYLOADS[model_id]['name']
    check('%s: the search card says %s' % (name, owned), (card['owned_locally'], card['owned_versions']), (owned, versions))
    check('%s: and the details panel the same' % name, (details['owned_locally'], details['owned_versions']),
          (owned, versions))
    check('%s: each version marked alike' % name,
          [v['owned_locally'] for v in details['modelVersions']], [v['owned_locally'] for v in card['modelVersions']])
    check('%s: listed, for Show in MM: %s' % (name, listed), (card.get('listed_locally'), details.get('listed_locally')),
          (listed, listed))
    check('%s: each version\'s held files' % name,
          {v['id']: v.get('owned_files') for v in card['modelVersions']}, files)

# Model 4848: its one file is in Neo's own ESRGAN folder, which
# --esrgan-models-path replaces in Neo (#195): not held, but ignored, saying why.
import model_manager.model_dirs as model_dirs            # noqa: E402
import modules.shared as forge_shared                    # noqa: E402
model_dirs.is_neo = lambda: True
forge_shared.cmd_opts.esrgan_models_path = os.path.join(WORK, 'shared_esrgan')
os.makedirs(os.path.join(WORK, 'models', 'ESRGAN'), exist_ok=True)
library_file(os.path.join(WORK, 'models', 'ESRGAN'), '4x_ignored.pth', 4848, 48481)
PAYLOADS[4848] = {'id': 4848, 'name': 'Only an ignored copy', 'modelVersions': [{'id': 48481}]}
card, details = searched(4848), detailed(4848)
check('a model whose only copy Neo ignores is not owned', (card['owned_locally'], details['owned_locally']),
      (False, False))
check('its card says which option made Neo ignore it',
      (card.get('ignored_because'), details.get('ignored_because')), ('--esrgan-models-path',) * 2)
check('and so does its version', card['modelVersions'][0].get('ignored_because'), '--esrgan-models-path')
check('an owned model is not ignored', searched(4343).get('ignored_because'), None)
check('nor is the other WebUI\'s file', searched(4646).get('ignored_because'), None)
grid = http.get('/model-manager/models', params={'search': 'model:4848', 'type': ''}).json()
check('the Model Manager\'s grid row says why its file is ignored',
      [m.get('ignored_because') for m in grid.get('models', [])], ['--esrgan-models-path'])
files = http.get('/model-manager/models/versions', params={'model_id': 4848}).json()
check('and so does the model\'s list of its files',
      [v.get('ignored_because') for v in files.get('versions', [])], ['--esrgan-models-path'])
check('the page is told which WebUI ignores it',
      http.get('/model-manager/ui-options').json().get('webui_short_name') in ('Neo', 'Forge'), True)

# Asked again by the page (#190): the same answer, by the same rule.
answer = http.get('/model-manager/civitai/owned', params={'model_ids': '4343,4545,4747',
                                                          'version_ids': '43431,45451,47471'})
got = answer.json() if answer.status_code == 200 else {}
check('the page can ask again which models are held, and is answered by the rule',
      (got.get('models'), got.get('versions')),
      ({'4343': {'owned': True, 'listed': True, 'ignored': None},
        '4545': {'owned': False, 'listed': True, 'ignored': None},
        '4747': {'owned': True, 'listed': True, 'ignored': None}},
       {'43431': {'owned': True, 'files': [434311], 'ignored': None},
        '45451': {'owned': False, 'files': [], 'ignored': None},
        '47471': {'owned': True, 'files': [474711], 'ignored': None}}))
answer = http.get('/model-manager/civitai/owned', params={'model_ids': '4848', 'version_ids': '48481'})
got = answer.json() if answer.status_code == 200 else {}
check('and says why a copy is ignored (#195)',
      (got.get('models', {}).get('4848', {}).get('ignored'), got.get('versions', {}).get('48481', {}).get('ignored')),
      ('--esrgan-models-path', '--esrgan-models-path'))

# No endpoint module reads the database itself.
API = os.path.join(ROOT, 'model_manager', 'api')
raw = []
for name in sorted(os.listdir(API)):
    if name.endswith('.py'):
        tree = ast.parse(open(os.path.join(API, name), encoding='utf-8').read())
        raw += ['%s:%d' % (name, node.lineno) for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and node.attr == '_cursor']
check('no endpoint module opens a database cursor of its own', raw, [])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
