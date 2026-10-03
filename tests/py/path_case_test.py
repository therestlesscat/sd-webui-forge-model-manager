"""
One file, however its path is spelt - for every read and write by path (#120).

Windows ignores the case of a path; the database does not. 0.44.8 made the
upserts find a stored file whatever case a walk spells it in (#99), so it
stays one row. Every other read and write by path still matched the spelling
exactly, and found nothing for a walk's other spelling: a sync never saw such
a file as synced, hashing it and asking Civitai again each time, and "not on
Civitai" never stuck; Scan Disk read its header on every scan and stored
nothing; a download's date was lost.

Here, on a throwaway database with case-blind matching on (as on Windows):
each of them, given the path in another case, reaches the stored row. With
it off (a disk where case matters), the other spelling is another file.
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
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.db.models_ops as models_ops        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'path_case')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
blind = models_ops._CASE_BLIND

STORED = r'F:\Models\Lora\One.safetensors'
WALKED = r'F:\models\lora\one.safetensors'


def store(path):
    db.upsert_version({'file_path': path, 'file_name': os.path.basename(path), 'file_extension': '.safetensors',
                       'has_civitai_data': False})


def row(path=STORED):
    return db.get_version(path) or {}


models_ops._CASE_BLIND = True
store(STORED)
check('given another spelling, the stored file is found', row(WALKED).get('file_path'), STORED)

db.set_lookup_failed(WALKED)
check('"not on Civitai" is marked on it', bool(row().get('civitai_lookup_failed_at')), True)
db.set_lookup_failed(WALKED, failed=False)
check('and cleared', row().get('civitai_lookup_failed_at'), None)

db.set_architecture(WALKED, 'xl', 'SDXL', False, False, '2026-01-01T00:00:00', file_type='LORA', note='read')
check('what its header says is stored on it',
      [row().get(k) for k in ('architecture', 'file_type', 'architecture_checked')], ['xl', 'LORA', '2026-01-01T00:00:00'])

db.set_downloaded_at(WALKED)
check('when it was downloaded too', bool(row().get('downloaded_at')), True)

MOVED = r'F:\Models\VAE\One.safetensors'
db.move_version(WALKED, MOVED)
check('moved by another spelling, its row goes with it', [row(STORED).get('file_path'), row(MOVED).get('file_path')],
      [None, MOVED])

db.delete_version(MOVED.lower())
check('and deleted by another spelling, it is gone', row(MOVED), {})
check('still one file, never two', db.get_version(WALKED), None)

# Where case matters, two spellings are two files.
models_ops._CASE_BLIND = False
store(STORED)
check('on a disk where case matters, another spelling is another file', row(WALKED), {})
db.set_lookup_failed(WALKED)
check('and marking it leaves the stored one alone', row().get('civitai_lookup_failed_at'), None)

models_ops._CASE_BLIND = blind
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
