"""
The Resources dialog's list of your checkpoints (#377): every checkpoint
Forge lists, each with its family, model, version, base model and file from
the library's row, and which of them suit the image - each with why: the
image's own, the same file under another model (#304), another file of its
version, another version of its model (#278), Forge's checkpoint now. The
image's base model is not a suggestion - one library holds 116 Illustrious
checkpoints - but its checkpoints come first in their family's tab
(`same_base`). A family this WebUI has no UI preset for is marked; a file no
sync has read says so. The route reads the library and Forge's list alone:
no file opened, Civitai not asked.
"""
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
import model_manager.identity_store as store             # noqa: E402
import model_manager.file_identity as identity           # noqa: E402
import model_manager.api.common as common                # noqa: E402
import model_manager.model_dirs as dirs                  # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'send_checkpoints')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
raw = db._get_connection()

# Two checkpoint models: the image's (v1 and v2 held), and another.
MODEL, OTHER_MODEL = facts['checkpoint_ids'][0], facts['checkpoint_ids'][1]
V1, V2 = facts['version_ids'][0], facts['version_ids'][1]
P1, P2 = facts['linked_paths'][0], facts['linked_paths'][1]
OTHER = next(r['file_path'] for r in db.library_files(model_ids=[OTHER_MODEL]))
OTHER_VERSION = next(r['version_id'] for r in db.library_files(model_ids=[OTHER_MODEL]))
# A second file of v1 - an fp16 beside the fp32 - and one of a family no
# preset here runs, and one no sync has read.
P1_FP16 = os.path.join(facts['models_dir'], 'Stable-diffusion', 'v1_fp16.safetensors')
QWEN = os.path.join(facts['models_dir'], 'Stable-diffusion', 'qwen_image.safetensors')
UNREAD = os.path.join(facts['models_dir'], 'Stable-diffusion', 'merged_by_hand.safetensors')
raw.execute("INSERT INTO files (file_path, file_name, version_id) VALUES (?, ?, ?)",
            (P1_FP16, os.path.basename(P1_FP16), V1))
raw.execute("INSERT INTO files (file_path, file_name) VALUES (?, ?)", (QWEN, os.path.basename(QWEN)))
raw.execute("UPDATE versions SET base_model = 'Illustrious' WHERE id IN (?, ?, ?)", (V1, V2, OTHER_VERSION))
raw.commit()
for path in (P1, P2, P1_FP16, OTHER):
    db.set_architecture(path, 'xl', 'SDXL', False, False, '1', file_type='Checkpoint')
db.set_architecture(QWEN, 'qwen', 'QwenImage', False, False, '1', file_type='Checkpoint')

TITLES = {P1: 'Illus\\v1.safetensors [1111]', P2: 'Illus\\v2.safetensors [2222]',
          P1_FP16: 'Illus\\v1_fp16.safetensors [3333]', OTHER: 'other.safetensors [4444]',
          QWEN: 'qwen_image.safetensors [5555]', UNREAD: 'merged_by_hand.safetensors [6666]'}
loaded = {'checkpoint': TITLES[OTHER]}
host.listed_checkpoints = lambda: [(title, path) for path, title in TITLES.items()]
host.available_presets = lambda: ['sd', 'xl', 'flux']
host.selected_models = lambda: dict(loaded)
host.checkpoint_file = lambda name: next((p for p, t in TITLES.items() if t == name), None)
# Nothing is read: a file opened here fails the check below.
opened = []
store.record_architecture = lambda *a, **k: opened.append(a[1])
identity.identify = lambda path, *a, **k: opened.append(path)

# The fixture's folders are this WebUI's: every file held here.
dirs.loads_here = lambda path, *a, **k: True
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))


def answer(**params):
    body = client.get('/model-manager/send/checkpoints', params=params).json()
    return body


def suggested(body):
    return [(s['name'], s['why']) for s in body.get('suggested') or []]


# ---------------------------------------------- every checkpoint Forge lists
body = answer(version_ids=str(V1), model_id=MODEL)
rows = {c['name']: c for c in body.get('checkpoints') or []}
check('every checkpoint Forge lists, in its order', [c['name'] for c in body.get('checkpoints') or []],
      list(TITLES.values()))
check('each with its family, model, version, base model and file, from the library\'s row',
      {k: rows[TITLES[P2]].get(k) for k in ('family', 'read', 'supported', 'version', 'base_model', 'file')},
      {'family': 'xl', 'read': True, 'supported': True, 'version': db.get_version(P2)['version_name'],
       'base_model': 'Illustrious', 'file': os.path.basename(P2)})
check('its model\'s name', rows[TITLES[P2]].get('model'), db.get_civitai_model(MODEL)['name'])
check('a family this WebUI has no UI preset for: marked', (rows[TITLES[QWEN]]['family'], rows[TITLES[QWEN]]['supported']),
      ('qwen', False))
check('a file no sync has read: not read yet, no family',
      (rows[TITLES[UNREAD]]['read'], rows[TITLES[UNREAD]]['family'], rows[TITLES[UNREAD]]['model']), (False, None, None))

# ---------------------------------------------------------- the suggestions
check('what suits the image, closest first, each with why',
      suggested(body),
      [(TITLES[P1], ["the image's own"]), (TITLES[P1_FP16], ['same version, other file']),
       (TITLES[P2], ['same model']), (TITLES[OTHER], ['loaded now'])])
check('the image\'s own picked first', body.get('picked'), TITLES[P1])
check('Forge\'s checkpoint now, named', body.get('loaded'), TITLES[OTHER])
check('the image\'s family, which the list opens on', body.get('family'), 'xl')
check('the same base model: not suggested, but named for its family\'s tab, in Forge\'s order',
      body.get('same_base'), {'base_model': 'Illustrious', 'names': []})
loaded['checkpoint'] = None
check('  the other model\'s Illustrious checkpoint, once nothing else suggests it',
      answer(version_ids=str(V1), model_id=MODEL).get('same_base'),
      {'base_model': 'Illustrious', 'names': [TITLES[OTHER]]})

# The image's checkpoint is a version the library lacks: what the dialog's
# missing-resources lookup said of it is handed in.
check('the image\'s version not held: its model\'s versions, by the model id handed in; none picked',
      [suggested(answer(version_ids='2999', model_id=MODEL)), answer(version_ids='2999', model_id=MODEL).get('picked')],
      [[(TITLES[P1], ['same model']), (TITLES[P1_FP16], ['same model']), (TITLES[P2], ['same model'])], None])
body = answer(version_ids='2999', model_id=MODEL, same_file=OTHER_VERSION)
check('the same file held under another model (#304): suggested, and picked first',
      (suggested(body)[0], body.get('picked')), ((TITLES[OTHER], ['same file']), TITLES[OTHER]))
check('the model not known: nothing is "same model"', suggested(answer(version_ids='2999')), [])
check('the base model handed in, where the library has no row of the image\'s',
      answer(version_ids='2999', base_model='Illustrious').get('same_base')['names'],
      sorted([TITLES[P1], TITLES[P1_FP16], TITLES[P2], TITLES[OTHER]], key=str.lower))
body = answer(gallery_file=P2, version_ids='2999')
check('in a checkpoint\'s gallery: its own file first, "this gallery\'s", picked',
      (suggested(body)[:1], body.get('picked')), ([(TITLES[P2], ["this gallery's"])], TITLES[P2]))

# Named by a hash alone - A1111's Model hash, a generation kept by name: the
# image's own by the file's stored hash, its version by Civitai's stored
# answer for the hash, so its other file is "same version, other file".
db.store_file_hashes(P1, {'SHA256': 'AB' * 32, 'AutoV2': 'ABABABABAB'}, None)
db.remember_hash('ababababab', {'id': V1, 'modelId': MODEL, 'name': 'v1', 'model': {'name': 'm', 'type': 'Checkpoint'}})
loaded['checkpoint'] = None
check('named by a hash alone: its own, its version\'s other file, its model\'s other version',
      suggested(answer(hashes='ABABABABAB')),
      [(TITLES[P1], ["the image's own"]), (TITLES[P1_FP16], ['same version, other file']), (TITLES[P2], ['same model'])])

check('no file opened, by any of it', opened, [])

# ---------------------------------------------------------- with Send off
common.on = lambda area: area != 'send'
check('refused while no tab Send serves is on', client.get('/model-manager/send/checkpoints').status_code, 403)

print('\n'.join('FAIL ' + f for f in fails) if fails else 'All checks passed.')
sys.exit(1 if fails else 0)
