"""
Stored hashes are read through hashing.read_hashes() and hash_key() (#62).

They are stored in either case - the hasher writes values upper case, Civitai
lists and older rows lower, a key may be "AutoV2" or "autov2" - and each
reader used to fold them itself. Here every reader is asked, in one case,
about a file stored in the other. They all coped before, each its own way;
this holds them to it now they share one. tests/tools/check_hash_access.py
keeps new readers on it.
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

from model_manager.db import ModelsDatabase              # noqa: E402
from model_manager.hashing import hash_key, names_this_file, read_hashes   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'hash_read')
os.makedirs(WORK, exist_ok=True)
for name in os.listdir(WORK):
    os.remove(os.path.join(WORK, name))

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


SHA = 'ABCDEF0123456789' * 4
# ------------------------------------------------------------ the reader
check('a dict in any case reads as kinds and values in lower case',
      read_hashes({'SHA256': SHA, 'AutoV2': 'AbCdEf0123', 'crc32': ''}),
      {'sha256': SHA.lower(), 'autov2': 'abcdef0123'})
check('so does the JSON text a row holds', read_hashes('{"SHA256": "%s"}' % SHA), {'sha256': SHA.lower()})
check('and nothing, or something unreadable, is no hashes',
      [read_hashes(None), read_hashes(''), read_hashes('not json'), read_hashes([1])], [{}, {}, {}, {}])
check('a single hash is kept as it is compared', hash_key('  AbCdEf0123 '), 'abcdef0123')

# ------------------------------------------------------------ every reader, the other case
path = os.path.join(WORK, 'upper.safetensors')
open(path, 'wb').write(b'\0')
check('names_this_file: an image\'s lower-case AutoV2 names a file stored upper case',
      names_this_file({'SHA256': SHA}, path, SHA[:10].lower()), True)

db = ModelsDatabase(WORK, custom_db_path=os.path.join(WORK, 'hashes.db'))
db.upsert_version({'file_path': path, 'file_name': 'upper.safetensors', 'file_extension': '.safetensors',
                   'id': 7001, 'model_id': 7000, 'has_civitai_data': True,
                   'file_hashes': {'SHA256': SHA, 'AutoV2': SHA[:10]}})
check('hashes_from_local_models finds it by a lower-case AutoV2, under an upper-case key',
      list(db.hashes_from_local_models([SHA[:10].lower()])), [SHA[:10].lower()])
check('versions_named_by finds it by a lower-case SHA-256',
      [v['id'] for v in db.versions_named_by([], [SHA.lower()])], [7001])
check('local_versions_by_key too, keyed by the hash as compared',
      list(db.local_versions_by_key([], [SHA[:10]])[1]), [SHA[:10].lower()])

db.remember_hash('AbCdEf9999', {'id': 42, 'modelId': 41, 'name': 'v', 'model': {'name': 'm'}})
check('a resource hash remembered in one case is found asked in another',
      db.resolved_hashes(['ABCDEF9999']).get('abcdef9999', {}).get('version_id'), 42)

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
