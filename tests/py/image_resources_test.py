"""
Which local file each of an image's resources is - for the chips a send puts
under the prompts, which toggle <lora:...> tags and embedding words.

An image names its resources by Civitai version id (civitaiResources) and by
hash (the infotext's resources). The Resources dialog already turns hashes
into version ids, but not into the file on disk, and it may ask Civitai. The
chips need the file - its stem is what Forge knows it by in a prompt - and
must answer from the library alone, per resource.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                       # noqa: E402

webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'image_resources')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
app = FastAPI()
setup_api(app)
client = TestClient(app)


def ask(**params):
    r = client.get('/model-manager/image-resources', params=params)
    return r.status_code, r.json()


path_a, path_b = facts['linked_paths'][0], facts['linked_paths'][1]
id_a, id_b = facts['version_ids'][0], facts['version_ids'][1]
db.set_architecture(path_b, None, None, False, False, '1', file_type='LoCon')
stem = lambda p: os.path.splitext(os.path.basename(p))[0]

status, body = ask(version_ids='%d' % id_a)
check('1. a version id this library has gives its file, by the name Forge uses',
      (status, body['versions'].get(str(id_a), {}).get('file_stem')), (200, stem(path_a)))
check('   and its version id back', body['versions'][str(id_a)]['version_id'], id_a)

autov2 = ('%010x' % id_b).upper()
status, body = ask(hashes=autov2)
check('2. a hash gives its file, keyed by the hash in lower case',
      body['hashes'].get(autov2.lower(), {}).get('file_stem'), stem(path_b))
check('   with what the file is, read from the file', body['hashes'][autov2.lower()]['file_type'], 'LoCon')
check('   any hash stored for it answers - SHA256 too',
      ask(hashes=('%064x' % id_b))[1]['hashes'].get('%064x' % id_b, {}).get('file_stem'), stem(path_b))

status, body = ask(version_ids='%d,999999' % id_a, hashes='%s,ffffffffff' % autov2)
check('3. each resource is answered separately, and the unknown ones left out',
      (sorted(body['versions']), sorted(body['hashes'])), ([str(id_a)], [autov2.lower()]))

status, body = ask()
check('4. nothing asked, nothing answered', (status, body['versions'], body['hashes']), (200, {}, {}))
check('   junk in the lists is ignored, not an error',
      ask(version_ids='abc, ,%d' % id_a, hashes=' , ')[0], 200)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
