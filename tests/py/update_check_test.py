"""
Whether a newer version is out (model_manager/update_check.py).

The repository's version.json is read - data, never run - from the branch this
copy pulls from, or the default branch when GitHub has no such branch. Here
GitHub is a fake: nothing is asked of the network. What is checked: versions
compare as numbers; the branch asked, and the fallback on a 404; that with
"Check for a new version" off nothing is asked at all; that a file holding no
version, or no answer, says nothing; and what the page is sent.
"""
import io
import json
import os
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()

import model_manager.update_check as uc                  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ------------------------------------------------------------------ comparing
check('versions compare as numbers, not text',
      [uc.is_newer('0.41.10', '0.41.9'), uc.is_newer('0.42.0', '0.41.10'), uc.is_newer('1.0.0', '0.99.99')],
      [True, True, True])
check('the same version, or an older one, is not newer',
      [uc.is_newer('0.41.10', '0.41.10'), uc.is_newer('0.41.9', '0.41.10')], [False, False])
check('what is not MAJOR.MINOR.PATCH is never newer',
      [uc.is_newer(None, '0.41.10'), uc.is_newer('0.42', '0.41.10'), uc.is_newer('v0.42.0', '0.41.10'),
       uc.is_newer('0.42.0-rc', '0.41.10')], [False, False, False, False])

# ------------------------------------------------------------- a fake GitHub
asked = []


def github(files):
    """An opener serving {ref: body}; a ref it does not have is a 404."""
    def opener(url, timeout=None):
        asked.append(url)
        ref = url[len(uc.REPOSITORY + '/raw/'):-len('/version.json')]
        if ref not in files:
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)
        body = files[ref]
        if isinstance(body, Exception):
            raise body
        return io.BytesIO(body.encode('utf-8'))
    return opener


def reset():
    asked.clear()
    uc._latest.update(version=None, note='', ref=None)


def on_branch(upstream, local='HEAD'):
    """This copy's git, as rev-parse would answer."""
    def git(*args):
        if '@{u}' in args:
            return upstream
        if args[:2] == ('rev-parse', '--abbrev-ref'):
            return local
        return None
    uc._git = git


newer = json.dumps({'version': '99.0.0', 'build': 1234, 'note': 'for later'})
same = json.dumps({'version': uc.VERSION, 'note': ''})

# ---------------------------------------------------------- which branch
reset()
on_branch('origin/rc')
found = uc.check_once(github({'rc': newer, 'HEAD': same}))
check('a copy pulling rc asks rc\'s version.json', [asked, found and found['version']],
      [[uc.REPOSITORY + '/raw/rc/version.json'], '99.0.0'])
check('and the page is told it is newer, with its note',
      uc.status(), {'current': uc.VERSION, 'latest': '99.0.0', 'build': 1234, 'newer': True, 'note': 'for later'})

reset()
on_branch('origin/my-branch')
uc.check_once(github({'HEAD': same}))
check('a branch GitHub does not have: the default branch, after its 404',
      asked, [uc.REPOSITORY + '/raw/my-branch/version.json', uc.REPOSITORY + '/raw/HEAD/version.json'])
check('which holds this version: nothing to say', [uc.status()['latest'], uc.status()['newer']],
      [uc.VERSION, False])

reset()
on_branch(None, local=None)
uc.check_once(github({'HEAD': newer}))
check('a copy without git asks the default branch alone', asked, [uc.REPOSITORY + '/raw/HEAD/version.json'])

reset()
on_branch(None, local='dev')
uc.check_once(github({'dev': same}))
check('a branch with no upstream is asked by its own name', asked, [uc.REPOSITORY + '/raw/dev/version.json'])

# ---------------------------------------------------------- the build
for label, build in (('none', None), ('not a number', '"254"'), ('zero', '0'), ('true', 'true')):
    reset()
    body = '{"version": "99.0.0"%s}' % ('' if build is None else ', "build": %s' % build)
    check(f'a build that is {label}: the version alone, still newer',
          [uc.check_once(github({'dev': body})) is not None, uc.status()['build'], uc.status()['newer']],
          [True, None, True])
reset()
uc.check_once(github({'dev': json.dumps({'version': uc.VERSION, 'build': 999999})}))
check('versions are compared without the build: the same version, a later build, is not newer',
      uc.status()['newer'], False)

# ---------------------------------------------------------- nothing to say
on_branch('origin/dev')
for label, body in (('not JSON', 'not json'), ('JSON with no version', '{"note": "x"}'),
                    ('a version that is not one', '{"version": "latest"}'),
                    ('no answer', urllib.error.URLError('offline'))):
    reset()
    check(f'{label}: nothing is said', [uc.check_once(github({'dev': body, 'HEAD': newer})), uc.status()['newer']],
          [None, False])
    check(f'{label}: and the default branch is not asked instead', len(asked), 1)

# ---------------------------------------------------------- the setting off
reset()
opts.model_manager_check_updates = False
check('off: GitHub is asked nothing', [uc.check_once(github({'dev': newer})), asked], [None, []])
opts.model_manager_check_updates = True
uc.check_once(github({'dev': newer}))
opts.model_manager_check_updates = False
check('and turned off after a check found one, the page is told nothing',
      uc.status(), {'current': uc.VERSION, 'latest': None, 'build': None, 'newer': False, 'note': ''})
opts.model_manager_check_updates = True

# ---------------------------------------------------------- the endpoint
try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None
if TestClient:
    from model_manager.api import notes as notes_api
    app = FastAPI()
    notes_api.register(app)
    reset()
    uc.check_once(github({'dev': newer}))
    answer = TestClient(app).get('/model-manager/update').json()
    check('the page asks /model-manager/update', [answer.get('success'), answer.get('newer'), answer.get('latest')],
          [True, True, '99.0.0'])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
