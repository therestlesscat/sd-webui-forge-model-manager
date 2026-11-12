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

opts = webui_stub.install()

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
# Its file not there - its drive away, Forge still listing it until its next
# refresh (#418): suggested still, as Forge lists it, but not picked to begin
# with - a press with it would fail at Forge's load.
# With a copy held under another model (#304), that copy is picked; and only
# the candidates for the pick are asked about, never the whole list.
real_exists, looked = os.path.exists, []


def counted(path):
    looked.append(os.path.normcase(str(path)))
    return real_exists(path)


os.rename(P1, P1 + '.away')
try:
    away = answer(version_ids=str(V1))
    os.path.exists = counted
    with_copy = answer(version_ids=str(V1), same_file=OTHER_VERSION)
finally:
    os.path.exists = real_exists
    os.rename(P1 + '.away', P1)
check('the image\'s own, its file not there: still suggested, not picked',
      (suggested(away)[0], away.get('picked')), ((TITLES[P1], ["the image's own"]), None))
check('  with the same file held under another model: that copy picked',
      with_copy.get('picked'), TITLES[OTHER])
check('  and of the listed files only the two candidates are asked about',
      sorted(p for p in looked if p in {os.path.normcase(x) for x in TITLES}),
      sorted(os.path.normcase(x) for x in (P1, OTHER)))
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

# ------------------------------------------- what the Sort box orders by (#415)
# Each row carries what the list's Sort box sorts on, from its library row:
# the file's size and when it came, its version's Civitai numbers - a real 0
# kept, none for a file with no version - whether it is pinned as the grid
# shows it, the version's stored Civitai images, and your images made with
# the version. Set here so each one's source shows.
raw.execute("UPDATE files SET file_size = 6000, downloaded_at = '2026-11-02T10:00:00', "
            "file_modified = '2026-11-01T09:00:00' WHERE file_path = ?", (P1,))
raw.execute("UPDATE files SET file_size = 4000, downloaded_at = NULL, file_modified = '2026-10-05T08:00:00' "
            "WHERE file_path = ?", (P2,))
raw.execute("UPDATE versions SET published_at = '2025-03-01T00:00:00.000Z', stats_download_count = 1200, "
            "stats_thumbs_up = 90 WHERE id = ?", (V1,))
raw.execute("UPDATE versions SET stats_download_count = 0, stats_thumbs_up = 0 WHERE id = ?", (V2,))
# Civitai's images stored: three of v1's - both its files' - and one of v2's.
for image, version in ((901, V1), (902, V1), (903, V1), (904, V2)):
    raw.execute("INSERT INTO image_galleries (version_id, image_id, page, position, effective_nsfw_level) "
                "VALUES (?, ?, 1, ?, 1)", (version, image, image))
# Your images: two made with v1's file and one with its fp16, so three for
# each; v2's file used as a LoRA and as Hires fix's checkpoint, which count
# nothing; one made with the file that has no version.
for image, role, path in ((1, 'checkpoint', P1), (2, 'checkpoint', P1), (3, 'checkpoint', P1_FP16),
                          (4, 'lora', P2), (5, 'hr_checkpoint', P2), (6, 'checkpoint', QWEN),
                          (7, 'lora', QWEN), (8, 'refiner', QWEN)):
    raw.execute("INSERT INTO generation_resources (image_id, generation_id, role, position, name, file_path) "
                "VALUES (?, ?, ?, 0, ?, ?)", (image, image, role, os.path.basename(path), path))
# The other model's version has none stored: its count is a real 0, not none.
raw.execute("DELETE FROM image_galleries WHERE version_id = ?", (OTHER_VERSION,))
raw.commit()
# The fixture stores images of its own: each version's count, read straight from the table.
STORED = {v: raw.execute("SELECT COUNT(*) FROM image_galleries WHERE version_id = ?", (v,)).fetchone()[0]
          for v in (V1, V2, OTHER_VERSION)}
# Pinned: the other model by its id, the file with no version by its path.
db.set_pin(OTHER_MODEL, None, True)
db.set_pin(None, QWEN, True)
SORT_KEYS = ('size', 'added', 'published', 'downloads', 'likes', 'pinned', 'civitai_images', 'generated')
values = lambda body, path: [{k: c.get(k) for k in SORT_KEYS} for c in body['checkpoints'] if c['name'] == TITLES[path]][0]
body = answer(version_ids=str(V1), model_id=MODEL)
check('a row carries what the Sort box orders by: its size, its download time, its version\'s Civitai numbers, '
      'v1\'s stored images and your images of either of its files',
      values(body, P1), {'size': 6000, 'added': '2026-11-02T10:00:00', 'published': '2025-03-01T00:00:00.000Z',
                         'downloads': 1200, 'likes': 90, 'pinned': False, 'civitai_images': STORED[V1], 'generated': 3})
check('    the other file of v1: the same counts, the version\'s',
      [values(body, P1_FP16)[k] for k in ('civitai_images', 'generated')], [STORED[V1], 3])
check('    never downloaded: when it came is its modified time; a real 0 stays 0; a LoRA\'s and Hires fix\'s use count nothing',
      [values(body, P2)[k] for k in ('added', 'downloads', 'likes', 'civitai_images', 'generated')],
      ['2026-10-05T08:00:00', 0, 0, STORED[V2], 0])
check('    a file with no version: no publish date, downloads, likes or stored images - none, not 0; '
      'pinned by its path; your image of it counted',
      [values(body, QWEN)[k] for k in ('published', 'downloads', 'likes', 'pinned', 'civitai_images', 'generated')],
      [None, None, None, True, None, 1])
check('    a model pinned by its id: its file pinned; a version with none stored: 0, not none',
      [values(body, OTHER)[k] for k in ('pinned', 'civitai_images')], [True, 0])
check('    a checkpoint the library has no row for: no value at all',
      values(body, UNREAD), {k: (False if k == 'pinned' else None) for k in SORT_KEYS})
check('    and the answer says Your generations is on', body.get('generations'), True)
# Forge spells a path its own way - another case, which Windows ignores - and the
# counts follow the library's spelling, which is what your generations name.
listed_before = host.listed_checkpoints
host.listed_checkpoints = lambda: [(title, path.upper() if path == P1_FP16 else path) for path, title in TITLES.items()]
check('    a path Forge spells in another case: the same counts',
      [values(answer(version_ids=str(V1), model_id=MODEL), P1_FP16)[k] for k in ('civitai_images', 'generated')],
      [STORED[V1], 3])
host.listed_checkpoints = listed_before
db.set_pin(None, P1_FP16, True)
body = answer(version_ids=str(V1), model_id=MODEL)
check('    a file pinned by its path: every file of its model pinned, as the grid shows the card',
      [values(body, path)['pinned'] for path in (P1, P1_FP16, P2)], [True, True, True])
opts.model_manager_record_generations = False
body = answer(version_ids=str(V1), model_id=MODEL)
check('Your generations off: the answer says so, and no row counts your images',
      [body.get('generations'), sorted({str(c.get('generated')) for c in body['checkpoints']})], [False, ['None']])
opts.model_manager_record_generations = True

check('no file opened, by any of it', opened, [])

# ---------------------------------------------------------- with Send off
common.on = lambda area: area != 'send'
check('refused while no tab Send serves is on', client.get('/model-manager/send/checkpoints').status_code, 403)

print('\n'.join('FAIL ' + f for f in fails) if fails else 'All checks passed.')
sys.exit(1 if fails else 0)
