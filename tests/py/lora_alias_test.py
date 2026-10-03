"""
A LoRA found by name the way Forge finds it: by its file's name, or by its
alias, and only in the folders the running WebUI looks in (#11).

Forge indexes every file in its LoRA folders under its name and its alias -
`ss_output_name` from the file's metadata - and both WebUIs here put the
alias in a prompt ("Alias from file"): Civitai's trainer names its output
training_<n>-<n>, so a prompt says <lora:training_6485327-...> where the file
is called something else. With no hash, the chips knew only file names, and
showed such a LoRA as missing. And a library shared by two WebUIs holds files
one of them never walks: the chip said "in library", and Forge loaded nothing.

Forge's rules (extensions-builtin/sd_forge_lora/networks.py, the same in both
WebUIs): an alias is case-sensitive; one two files share is forbidden, and the
name is looked up by file name alone; Neo walks --lora-dir and --lora-dirs,
the original Forge --lora-dir.
"""
import json
import os
import sqlite3
import struct
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
import model_manager.db.migrations as migrations         # noqa: E402
from model_manager import resources                      # noqa: E402
from model_manager.identity_store import record_architecture  # noqa: E402
from modules import shared                               # noqa: E402

WORK = os.path.join(TESTS, 'work', 'lora_alias')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
LORA_DIR = os.path.join(facts['models_dir'], 'Lora')
ELSEWHERE = os.path.join(WORK, 'other_webui', 'models', 'Lora')
os.makedirs(ELSEWHERE, exist_ok=True)


def lora(folder, name, version_id, alias=None, autov2=None):
    """A LoRA as a trainer writes it: one adapter weight, and its metadata."""
    header = {'lora_unet_down_blocks_0_attentions_0_proj_in.lora_down.weight':
              {'dtype': 'F16', 'shape': [4, 8], 'data_offsets': [0, 64]}}
    if alias is not None:
        header['__metadata__'] = {'ss_output_name': alias}
    raw = json.dumps(header).encode('utf-8')
    path = os.path.join(folder, name)
    with open(path, 'wb') as f:
        f.write(struct.pack('<Q', len(raw)) + raw + b'\0' * 64)
    db.upsert_version({'id': version_id, 'model_id': version_id * 10, 'file_path': path,
                       'file_name': name, 'file_size': os.path.getsize(path),
                       'file_extension': '.safetensors', 'has_civitai_data': True, 'nsfw_level': 1,
                       'file_hashes': {'autov2': autov2} if autov2 else None})
    record_architecture(db, path, force=True)          # as Scan Disk reads it
    return path


def by_name(name, image_hash=''):
    found = resources.image_files(db, [], [], [{'name': name, 'hash': image_hash}])['names']
    return found.get(name.lower(), {}).get('version_id')


# ------------------------------------------------------------ the alias, read
TRAINED = lora(LORA_DIR, 'trained_style.safetensors', 501, alias='training_6485327-20260725085836447')
check('a scan keeps the alias the file carries',
      (db.get_version(TRAINED) or {}).get('lora_alias'), 'training_6485327-20260725085836447')
PLAIN = lora(LORA_DIR, 'plain_style.safetensors', 502)
check('and none for a file that carries none', (db.get_version(PLAIN) or {}).get('lora_alias'), None)

# ------------------------------------------------------- found by its alias
check('a LoRA the image names by its alias is found, with no hash',
      by_name('training_6485327-20260725085836447'), 501)
check('the alias as Forge matches it: case and all',
      by_name('TRAINING_6485327-20260725085836447'), None)
check('a file name still finds its file', by_name('trained_style'), 501)

lora(LORA_DIR, 'twin_one.safetensors', 503, alias='twin_alias')
lora(LORA_DIR, 'twin_two.safetensors', 504, alias='twin_alias')
check('an alias two files share finds neither: Forge forbids it', by_name('twin_alias'), None)

lora(LORA_DIR, 'claims_a_name.safetensors', 505, alias='plain_style')
check('a name that is one file\'s name and another\'s alias is the file\'s, as in Forge',
      by_name('plain_style'), 502)

# ------------------------------------------ only where this WebUI looks
# The original Forge sharing Neo's database: Neo's Lora folder is in the
# library, and the original Forge never walks it.
FAR = lora(ELSEWHERE, 'far_style.safetensors', 506, alias='far_alias', autov2='abcdef0123')
shared.cmd_opts.lora_dir = LORA_DIR
try:
    answer = resources.image_files(db, [506], ['abcdef0123'], [{'name': 'far_style', 'hash': ''}])
    check('a LoRA outside the WebUI\'s LoRA folders is not offered by its version',
          answer['versions'], {})
    check('nor by its hash', answer['hashes'], {})
    check('nor by its name', answer['names'], {})
    check('nor by its alias', by_name('far_alias'), None)
    check('one inside them still is', by_name('trained_style'), 501)

    # The same file in both places: a hash finds the copy this WebUI walks.
    NEAR = lora(LORA_DIR, 'near_copy.safetensors', 507, autov2='abcdef0123')
    answer = resources.image_files(db, [], ['abcdef0123'], [])
    check('of two files with one hash, the one this WebUI walks is taken',
          answer['hashes'].get('abcdef0123', {}).get('version_id'), 507)

    # Neo also walks --lora-dirs.
    shared.cmd_opts.lora_dirs = [ELSEWHERE]
    check('a folder --lora-dirs names is walked too', by_name('far_style'), 506)
finally:
    shared.cmd_opts.lora_dir = None
    if hasattr(shared.cmd_opts, 'lora_dirs'):
        del shared.cmd_opts.lora_dirs
check('outside the WebUI, where its folders are not known, nothing is left out',
      by_name('far_style'), 506)

# ------------------------------------------------------- the migration
# v31 adds the column, and marks every LoRA unread, so the next Scan Disk
# reads each one's alias - no box to tick.
migrate = getattr(migrations, '_migrate_to_v31', None)
check('there is a v31 migration', migrate is not None)
if migrate:
    raw = sqlite3.connect(':memory:')
    raw.execute('CREATE TABLE model_versions (file_path TEXT, file_type TEXT, architecture_checked TEXT)')
    raw.executemany('INSERT INTO model_versions VALUES (?, ?, ?)',
                    [('a', 'LORA', '1'), ('b', 'LoCon', '1'), ('c', 'Checkpoint', '1'), ('d', None, None)])
    migrate(raw.cursor())
    columns = [r[1] for r in raw.execute('PRAGMA table_info(model_versions)')]
    check('v31 adds lora_alias', 'lora_alias' in columns)
    check('and marks the LoRA family unread, nothing else',
          [r[0] for r in raw.execute('SELECT architecture_checked FROM model_versions ORDER BY file_path')],
          [None, None, '1', None])
    migrate(raw.cursor())
    check('run twice, it is harmless', [r[1] for r in raw.execute('PRAGMA table_info(model_versions)')].count('lora_alias'), 1)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
