"""
The scan: what it finds on disk, what it reads beside it, and what it forgets.

This is the offline half of keeping the library true. It never calls Civitai -
it walks the model folders and reads the `.civitai.info` another tool may have
left - so everything here runs without a network.
"""
import io
import json
import os
import shutil
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
from model_manager.scan_service import ScanService       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'scan')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
models_dir = facts['models_dir']
scan = ScanService()

# --------------------------------------------------------------- what it finds
found = scan.find_model_files([models_dir])
check('it finds every model the fixture wrote', len(found), fixtures.VERSIONS)
check('and nothing that is not a model',
      all(f.lower().endswith(('.safetensors', '.ckpt', '.pt', '.pth', '.bin'))
          for f in found), True)

io.open(os.path.join(models_dir, 'VAE', 'notes.txt'), 'w').write('not a model')
check('a text file beside them is ignored', len(scan.find_model_files([models_dir])),
      fixtures.VERSIONS)

check('a directory that does not exist yields nothing',
      scan.find_model_files([os.path.join(WORK, 'nowhere')]), [])
check('and no directories at all yields nothing', scan.find_model_files([]), [])

# ------------------------------------------------ Civitai's type is Civitai's
# What a file is comes from the file itself (file_identity_test.py). The
# type column holds only what Civitai said: a sidecar without one leaves it
# empty, where a guess from the folder used to call anything under Lora a
# LORA - VAEs and text encoders kept there included.
untyped = os.path.join('models', 'Lora', 'x.safetensors')
civitai_model = scan._extract_civitai_metadata({'id': 1, 'modelVersions': [{'id': 2}]},
                                               {'file_path': untyped, 'file_name': 'x.safetensors',
                                                'file_extension': '.safetensors'}, untyped)
check('a sidecar with no type gives no type, not a guess from the folder',
      civitai_model['type'], None)

# ------------------------------------------------- a file with nothing beside it
plain = os.path.join(models_dir, 'Lora', 'no_sidecar.safetensors')
io.open(plain, 'wb').write(b'\0' * 128)
civitai_model, version = scan.extract_metadata(plain)
check('a bare file yields no Civitai model', civitai_model, None)
check('but still a version row', version['file_path'], plain)
check('marked as having no Civitai data', version['has_civitai_data'], False)
check('with its size from disk', version['file_size'], 128)
check('and a level that keeps it visible', version['nsfw_level'], 1)

# ---------------------------------------------------- a file with a full sidecar
rich = os.path.join(models_dir, 'Stable-diffusion', 'with_sidecar.safetensors')
io.open(rich, 'wb').write(b'\0' * 256)
PAYLOAD = {
    "id": 7777, "name": "From A Sidecar", "type": "Checkpoint",
    "description": "<p>d</p>", "tags": ["t"], "nsfw": True, "nsfwLevel": 4,
    "creator": {"username": "someone", "image": "https://example.invalid/a.png"},
    "stats": {"downloadCount": 12, "thumbsUpCount": 3, "thumbsDownCount": 1},
    "allowNoCredit": False, "allowCommercialUse": ["Rent"],
    "allowDerivatives": False, "allowDifferentLicense": False,
    "supportsGeneration": True,
    "modelVersions": [{
        "id": 8888, "name": "v9", "baseModel": "Pony", "nsfwLevel": 4,
        "publishedAt": "2026-02-02T00:00:00Z", "createdAt": "2026-02-01T00:00:00Z",
        "description": "version words", "trainedWords": ["boop"],
        "stats": {"downloadCount": 9, "thumbsUpCount": 2},
        "files": [{"name": "with_sidecar.safetensors", "primary": True,
                   "hashes": {"SHA256": "C" * 64, "AutoV2": "D" * 10}}],
        "images": [{"id": 5, "url": "https://example.invalid/5.png",
                    "browsingLevel": 4}],
    }],
}
fixtures.sidecar(rich, PAYLOAD)

civitai_model, version = scan.extract_metadata(rich)
check('the sidecar gives a model', civitai_model is not None, True)
check('with its id', civitai_model['id'], 7777)
check('its licence terms', (civitai_model['allow_derivatives'],
                            civitai_model['allow_different_license']), (False, False))
check('and its vote counts', (civitai_model['stats_thumbs_up'],
                              civitai_model['stats_thumbs_down']), (3, 1))
check('the version is matched by filename', version['id'], 8888)
check('with its trigger words', version['trained_words'], ['boop'])
check('its publish date', version['published_at'], '2026-02-02T00:00:00Z')
check('the hashes Civitai recorded',
      json.loads(json.dumps(version['file_hashes']))['sha256'], 'C' * 64)
check('and is marked as identified', version['has_civitai_data'], True)

# ------------------------------------------------------------------ the whole run
before = len(db.get_all_version_paths())
progress = scan.scan_models(directories=[models_dir])
check('the scan completes', progress.is_complete, True)
check('having looked at everything it found', progress.processed, fixtures.VERSIONS + 2)
after = db.get_all_version_paths()
check('the two new files are now rows', len(after), before + 2)
check('including the bare one', plain in after, True)
check('and the one with a sidecar', rich in after, True)

stored = db.get_version(rich)
check('the sidecar reached the database', stored['id'], 8888)
check('with its trigger words', stored['trained_words'], ['boop'])

# ---------------------------------------------------------- and what is gone
os.remove(plain)
progress = scan.scan_models(directories=[models_dir])
check('a deleted file is dropped', plain in db.get_all_version_paths(), False)
check('and nothing else goes with it',
      len(db.get_all_version_paths()), fixtures.VERSIONS + 1)

# ------------------------------------------- a sidecar in Civitai's version format
# Other tools write the by-hash payload: the version at the root, the model
# under "model". Read as the model format it gave the model the version's id
# and name and no type - and with no type, the insert failed and took the
# whole scan down with it.
import json as _json                                     # noqa: E402
hashed = os.path.join(models_dir, 'Stable-diffusion', 'from_another_tool.gguf')
io.open(hashed, 'wb').write(b'\0' * 64)
io.open(os.path.splitext(hashed)[0] + '.civitai.info', 'w', encoding='utf-8').write(_json.dumps({
    "id": 2434385, "modelId": 2053259, "name": "Lightning Q6", "baseModel": "Wan Video 2.2 I2V-A14B",
    "trainedWords": [], "files": [{"name": "from_another_tool.gguf", "primary": True}],
    "creator": {"username": "maker"},
    "model": {"name": "WAN 2.2 Enhanced", "type": "Checkpoint", "nsfw": False}}))
civitai_model, version = scan.extract_metadata(hashed)
check('a version-format sidecar is read as the model it belongs to',
      (civitai_model['id'], civitai_model['name'], civitai_model['type'], civitai_model['creator_username']),
      (2053259, 'WAN 2.2 Enhanced', 'Checkpoint', 'maker'))
check('and the version as the version', (version['id'], version['model_id'], version['base_model']),
      (2434385, 2053259, 'Wan Video 2.2 I2V-A14B'))

untyped_file = os.path.join(models_dir, 'Lora', 'no_type_anywhere.safetensors')
io.open(untyped_file, 'wb').write(b'\0' * 64)
io.open(os.path.splitext(untyped_file)[0] + '.civitai.info', 'w', encoding='utf-8').write(_json.dumps({
    "id": 31337, "name": "Typeless", "modelVersions": [{"id": 31338, "name": "v1",
                                                        "files": [{"name": "no_type_anywhere.safetensors"}]}]}))
progress = scan.scan_models(directories=[models_dir])
check('a sidecar with no type anywhere no longer stops the scan', (progress.is_complete, progress.errors),
      (True, []))
check('its model is stored, its Civitai type Unknown', db.get_civitai_model(31337)['type'], 'Unknown')
check('and the version-format one under its real model id',
      db.get_version(hashed)['model_id'], 2053259)
db.upsert_civitai_model({'id': 31337, 'name': 'Typeless', 'type': 'LORA'})
db.upsert_civitai_model({'id': 31337, 'name': 'Typeless', 'type': None})
check('a typeless sidecar never overwrites a type already known', db.get_civitai_model(31337)['type'], 'LORA')

# One file the database refuses is that file's error, and the scan goes on.
real_upsert = db.upsert_version
def refuse(data):
    if data['file_path'] == untyped_file:
        raise ValueError('refused')
    return real_upsert(data)
db.upsert_version = refuse
db.delete_version(hashed)
try:
    progress = scan.scan_models(directories=[models_dir])
finally:
    db.upsert_version = real_upsert
check('a file the database refuses is reported, and the rest are still stored',
      (progress.is_complete, [e for e in progress.errors if 'refused' in e] != [],
       db.get_version(hashed) is not None), (True, True, True))

# ------------------------------------------------------------------ cancelling
scan.cancel()
check('cancelling is remembered', scan._cancel_requested, True)
check('and progress is readable', isinstance(scan.progress.to_dict(), dict), True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
