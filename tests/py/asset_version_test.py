"""
/model-manager/asset-version: the version the tabs import javascript/shared/
with (#53) - the newest mtime among those files, so it moves when only a
shared file changes, and never cached. The page's side is
shared_version_test.mjs.
"""
import io
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

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import model_manager.api.webui as webui                  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


check('it looks in the extension\'s javascript/shared',
      os.path.isfile(os.path.join(webui.SHARED_SCRIPTS, 'core.mjs')), True)

WORK = os.path.join(TESTS, 'work', 'asset_version')
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(os.path.join(WORK, 'nested'))
for name, when in (('core.mjs', 1_700_000_000), ('viewer.mjs', 1_700_000_500),
                   (os.path.join('nested', 'part.mjs'), 1_700_000_200), ('notes.txt', 1_800_000_000)):
    path = os.path.join(WORK, name)
    io.open(path, 'w').write('x')
    os.utime(path, (when, when))
webui.SHARED_SCRIPTS = WORK

app = FastAPI()
webui.register(app)
client = TestClient(app)

r = client.get('/model-manager/asset-version')
check('the newest script\'s mtime, whole seconds - not a text file\'s',
      (r.status_code, r.json()['version']), (200, '1700000500'))
check('never cached', r.headers.get('cache-control'), 'no-store')

later = os.path.join(WORK, 'nested', 'part.mjs')
os.utime(later, (1_700_009_999, 1_700_009_999))
check('a change to one shared file alone moves it',
      client.get('/model-manager/asset-version').json()['version'], '1700009999')

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
