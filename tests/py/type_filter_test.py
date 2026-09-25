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

WORK = os.path.join(TESTS, 'work', 'type_filter')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)


def model_ids(model_type):
    rows, _ = db.query_models_grouped(model_type=model_type, limit=500)
    return {r['model_id'] for r in rows}


def row_for(model_id):
    rows, _ = db.query_models_grouped(limit=500)
    return next(r for r in rows if r['model_id'] == model_id)


def set_type(model_id, file_type):
    with db._cursor() as cursor:
        cursor.execute("UPDATE model_versions SET file_type = ?, identified_by = ? WHERE model_id = ?",
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
    cursor.execute("UPDATE model_versions SET file_type = 'LoCon' WHERE file_path = ?", (local,))
rows, _ = db.query_models_grouped(model_type='LoCon', limit=500)
check('a file Civitai does not know gets its own type',
      [(r['file_path'], r['model_type'], r['civitai_type']) for r in rows], [(local, 'LoCon', None)])
rows, _ = db.query_models_grouped(model_type='Unknown', limit=500)
check('and is no longer Unknown', local in [r['file_path'] for r in rows], False)

# The dropdown offers exactly the types a file can be, in their order.
import re                                                  # noqa: E402
from model_manager.file_identity import FILE_TYPES         # noqa: E402
markup = open(os.path.join(ROOT, 'model_manager', 'ui', 'tab_model_manager.py'), encoding='utf-8').read()
select = re.search(r'<select id="mm_type".*?</select>', markup, re.S).group(0)
check('the Type filter lists every file type, and nothing else',
      re.findall(r'<option value="([^"]+)"', select), list(FILE_TYPES))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
