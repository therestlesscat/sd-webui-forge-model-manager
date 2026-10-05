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
named = dict(FULL, name='Café 日本')
storage.write_civitai_info(MODEL, named)
check('a name beyond ASCII reads back as it was - every sidecar is written so now (#64)',
      storage.read_civitai_info(MODEL)['name'], 'Café 日本')
storage.write_civitai_info(MODEL, FULL)

check('reading a model with no sidecar gives nothing',
      storage.read_civitai_info(os.path.join(WORK, 'absent.safetensors')), None)

io.open(info, 'w', encoding='utf-8').write('{ this is not json')
check('unreadable JSON is nothing, not a crash', storage.read_civitai_info(MODEL), None)
storage.write_civitai_info(MODEL, FULL)

# ------------------------------------------------------- writing where it cannot
unwritable = os.path.join(WORK, 'no_such_directory', 'deep', 'model.safetensors')
check('writing into a directory that is not there fails rather than raises',
      storage.write_civitai_info(unwritable, FULL), False)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
