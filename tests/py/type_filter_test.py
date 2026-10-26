"""
The Type filter goes by what a file is, not by what Civitai filed it under.

Civitai's type is the uploader's choice for the whole model: VAEs shared as
"Checkpoint", text encoders as "LORA", and files Civitai does not know have
none. A scan now reads each file's own type (file_identity_test.py); the
filter and the rows use it, and Civitai's type only for a file not read yet.
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

import fixtures                                          # noqa: E402
from model_manager.db import GridQuery                 # noqa: E402

WORK = os.path.join(TESTS, 'work', 'type_filter')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)


def model_ids(model_type):
    rows, _ = db.query_models_grouped(GridQuery(model_types=(model_type,), limit=500))
    return {r['model_id'] for r in rows}


def row_for(model_id):
    rows, _ = db.query_models_grouped(GridQuery(limit=500))
    return next(r for r in rows if r['model_id'] == model_id)


def set_type(model_id, file_type):
    with db._cursor() as cursor:
        cursor.execute("UPDATE files SET file_type = ?, identified_by = ? WHERE version_id IN "
                       "(SELECT id FROM versions WHERE model_id = ?)",
                       (file_type, 'a vae_sd by its shapes', model_id))


a_lora, a_checkpoint = facts['lora_ids'][0], facts['checkpoint_ids'][0]
check('before anything is read, the filter goes by Civitai\'s type',
      (a_lora in model_ids('LORA'), a_checkpoint in model_ids('Checkpoint')), (True, True))

set_type(a_lora, 'VAE')
check('a "LORA" whose file is a VAE is found under VAE',
      (a_lora in model_ids('VAE'), a_lora in model_ids('LORA')), (True, False))
row = row_for(a_lora)
check('and its row says so, keeping what Civitai listed it as',
      (row['model_type'], row['file_type'], row['civitai_type'], row['identified_by']),
      ('VAE', 'VAE', 'LORA', 'a vae_sd by its shapes'))
check('a file not read yet still shows Civitai\'s type', row_for(a_checkpoint)['model_type'], 'Checkpoint')

# A file Civitai does not know had no type at all - every one was Unknown.
local = facts['local_only_paths'][0]
with db._cursor() as cursor:
    cursor.execute("UPDATE files SET file_type = 'LoCon' WHERE file_path = ?", (local,))
rows, _ = db.query_models_grouped(GridQuery(model_types=('LoCon',), limit=500))
check('a file Civitai does not know gets its own type',
      [(r['file_path'], r['model_type'], r['civitai_type']) for r in rows], [(local, 'LoCon', None)])
rows, _ = db.query_models_grouped(GridQuery(model_types=('Unknown',), limit=500))
check('and is no longer Unknown', local in [r['file_path'] for r in rows], False)

# The list offers exactly the types a file can be, in their order, and a
# LoRA row standing for every kind of LoRA (#341).
import re                                                  # noqa: E402
from model_manager.file_identity import FILE_TYPES, LORA_FAMILY  # noqa: E402
markup = open(os.path.join(ROOT, 'model_manager', 'ui', 'tab_model_manager.py'), encoding='utf-8').read()
panel = re.search(r'<div class="mm-multiselect-panel" id="mm_type_panel">.*?</div>\s*</div>', markup, re.S).group(0)
rows = re.findall(r'<label class="mm-multiselect-item"([^>]*)><input type="checkbox" value="([^"]*)"', panel)
check('the Type filter lists every file type, and nothing else',
      [value for attrs, value in rows if value and 'data-lora-row' not in attrs], list(FILE_TYPES))
check('its LoRA row stands for every kind of LoRA, and is hidden until the setting shows it',
      [(attrs.strip(), value) for attrs, value in rows if 'data-lora-row' in attrs],
      [('data-lora-row hidden', ','.join(LORA_FAMILY))])
check('each kind it stands for is marked as one',
      [value for attrs, value in rows if 'data-lora-kind' in attrs], list(LORA_FAMILY))

# One list of what a file is (#66): what is built from it names only its types.
from model_manager.file_identity import NAMED_IN_PROMPTS   # noqa: E402
from model_manager.model_dirs import FOLDER_FOR_FILE_TYPE  # noqa: E402
check('every type a file can be has a folder, but Unknown - and no folder names another type',
      sorted(FOLDER_FOR_FILE_TYPE), sorted(t for t in FILE_TYPES if t != 'Unknown'))
check('the types a prompt names by file name are file types',
      [t for t in NAMED_IN_PROMPTS if t not in FILE_TYPES], [])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
