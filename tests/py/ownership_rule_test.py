"""
Whether the library holds a model: one rule, for search and details (#76).

The Civitai Browser's search cards called a model owned if any file in the
library belongs to it; its details panel only if one of the versions Civitai
lists now is held. A model held through a version Civitai has since deleted
was "Owned" on its card and not in its details, which then hid "Show in
Model Manager" - the file there all along. What is checked: both answer
alike - for that model, for one held through a listed version, and for one
not held - and no endpoint module reads the database with a cursor of its
own; the rule is the database's (owned_by_library).
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

webui_stub.install()

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

WORK = os.path.join(TESTS, 'work', 'ownership_rule')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
LIB = os.path.join(WORK, 'library')
# Model 4242: held through version 42420, which Civitai lists no more.
# Model 4343: held through 43431, which it still lists.
for path, model_id, version_id in ((os.path.join(LIB, 'old_version.safetensors'), 4242, 42420),
                                   (os.path.join(LIB, 'listed.safetensors'), 4343, 43431)):
    db.upsert_version({'file_path': path, 'file_name': os.path.basename(path), 'id': version_id,
                       'model_id': model_id, 'has_civitai_data': True})

PAYLOADS = {
    4242: {'id': 4242, 'name': 'Deleted version held', 'modelVersions': [{'id': 42421}, {'id': 42422}]},
    4343: {'id': 4343, 'name': 'Listed version held', 'modelVersions': [{'id': 43430}, {'id': 43431}]},
    4444: {'id': 4444, 'name': 'Not held', 'modelVersions': [{'id': 44441}]},
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


for model_id, owned, versions in ((4242, True, []), (4343, True, [43431]), (4444, False, [])):
    card, details = searched(model_id), detailed(model_id)
    name = PAYLOADS[model_id]['name']
    check('%s: the search card says %s' % (name, owned), (card['owned_locally'], card['owned_versions']), (owned, versions))
    check('%s: and the details panel the same' % name, (details['owned_locally'], details['owned_versions']),
          (owned, versions))
    check('%s: each version marked alike' % name,
          [v['owned_locally'] for v in details['modelVersions']], [v['owned_locally'] for v in card['modelVersions']])

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
