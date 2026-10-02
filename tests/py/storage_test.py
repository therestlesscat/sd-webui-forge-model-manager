"""
The sidecars: reading them, writing them, and telling a thin one from a full one.

These files are the interchange format with every other Civitai extension, so
what counts as "partial" decides whether a sync re-fetches a model or trusts
what is already on disk.
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

from model_manager import storage                        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'storage')
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


MODEL = os.path.join(WORK, 'subject.safetensors')
io.open(MODEL, 'wb').write(b'\0' * 64)

# ------------------------------------------------------------------- the paths
info, images = storage.get_metadata_paths(MODEL)
check('the info file sits beside the model', info, os.path.join(WORK, 'subject.civitai.info'))
check('and so does the image file', images, os.path.join(WORK, 'subject.images.json'))
check('an extension is replaced, not appended', info.endswith('.safetensors.civitai.info'), False)

# --------------------------------------------------------- full and partial
FULL = {
    "id": 42, "name": "Subject", "type": "Checkpoint",
    "description": "<p>words</p>", "tags": ["a"], "nsfw": False, "nsfwLevel": 1,
    "creator": {"username": "someone"},
    "stats": {"downloadCount": 5},
    "modelVersions": [{
        "id": 4242, "name": "v1", "baseModel": "SDXL 1.0", "nsfwLevel": 1,
        "publishedAt": "2026-01-01T00:00:00Z", "trainedWords": ["trigger"],
        "files": [{"name": "subject.safetensors", "primary": True,
                   "sizeKB": 1024, "type": "Model",
                   "hashes": {"SHA256": "A" * 64, "AutoV2": "B" * 10}}],
        "images": [{"id": 1, "url": "https://example.invalid/1.png"}],
    }],
}

# ----------------------------------------------------------- round tripping
check('writing succeeds', storage.write_civitai_info(MODEL, FULL), True)
check('the file is where it said', os.path.exists(info), True)
check('reading gives it back', storage.read_civitai_info(MODEL), FULL)

check('reading a model with no sidecar gives nothing',
      storage.read_civitai_info(os.path.join(WORK, 'absent.safetensors')), None)

io.open(info, 'w', encoding='utf-8').write('{ this is not json')
check('unreadable JSON is nothing, not a crash', storage.read_civitai_info(MODEL), None)
storage.write_civitai_info(MODEL, FULL)

# ------------------------------------------------------------------- images
IMAGES = [{"id": 1, "url": "https://example.invalid/1.png",
           "meta": {"prompt": "a prompt"}},
          {"id": 2, "url": "https://example.invalid/2.png", "meta": None}]
# Written by older versions only; read still, for the details panel's fallback.
io.open(os.path.splitext(MODEL)[0] + '.images.json', 'w', encoding='utf-8').write(json.dumps({'images': IMAGES}))
back = storage.read_images_json(MODEL)
check('and they come back', bool(back), True)
check('with both of them', len(back.get('images', back) if isinstance(back, dict) else back), 2)

check('a model with no image file reads as nothing',
      storage.read_images_json(os.path.join(WORK, 'absent.safetensors')), None)

# ------------------------------------------------------------------ parsing
model_info, version = storage.parse_civitai_info(FULL, 'subject.safetensors')
check('parsing finds the model', model_info is not None, True)
check('and its name', getattr(model_info, 'name', None), 'Subject')
check('and the version', version is not None, True)
check('with its base model', getattr(version, 'base_model', None), 'SDXL 1.0')

empty_model, empty_version = storage.parse_civitai_info({}, 'subject.safetensors')
check('parsing nothing yields nothing', (empty_model, empty_version), (None, None))

# --------------------------------------------------------------- everything
model_info, version, images = storage.load_model_metadata(MODEL)
check('loading gathers the model', model_info is not None, True)
check('and the version', version is not None, True)
check('and the images', len(images), 2)

absent = storage.load_model_metadata(os.path.join(WORK, 'absent.safetensors'))
check('loading an absent model yields empties', (absent[0], absent[1], list(absent[2])),
      (None, None, []))

# ------------------------------------------------------- writing where it cannot
unwritable = os.path.join(WORK, 'no_such_directory', 'deep', 'model.safetensors')
check('writing into a directory that is not there fails rather than raises',
      storage.write_civitai_info(unwritable, FULL), False)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
