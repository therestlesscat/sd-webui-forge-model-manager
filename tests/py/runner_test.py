"""
Which suites `run.py --changed` picks for a change.

Every run of everything records which of the extension's files each suite
uses; --changed runs the suites that use what changed. It must not skip a
suite a change needs - so a changed suite runs, a file every suite of a kind
depends on runs them all, and code no suite was seen using runs everything
that could - and must say why it chose each.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
sys.path.insert(0, TESTS)

import run                                               # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


SUITES = [('check', 'x', 'check_js_references.mjs'), ('py', 'x', 'hash_test.py'),
          ('py', 'x', 'sync_test.py'), ('js', 'x', 'gallery_test.mjs'), ('js', 'x', 'dialog_test.mjs')]
MAP = {'hash_test.py': ['model_manager/hashing.py'],
       'sync_test.py': ['model_manager/hashing.py', 'model_manager/sync_service.py', 'changelog.md'],
       'gallery_test.mjs': ['javascript/model_manager.mjs', 'model_manager/ui/tab_model_manager.py'],
       'dialog_test.mjs': ['javascript/model_manager.mjs']}


def pick(*changed, known=MAP):
    run.changed_files = lambda: list(changed)
    chosen, _, everything = run.choose(SUITES, known)
    return sorted(n for n in chosen if not n.startswith('check')), everything, chosen


check('code a suite was seen using runs that suite, and only that',
      pick('model_manager/sync_service.py')[0], ['sync_test.py'])
check('code several use runs them all', pick('model_manager/hashing.py')[0], ['hash_test.py', 'sync_test.py'])
check('the reason says what it uses', pick('model_manager/sync_service.py')[2]['sync_test.py'],
      'uses model_manager/sync_service.py')
check('a file read, not run, counts - the markup, whatever the case git gives it',
      [pick('model_manager/ui/tab_model_manager.py')[0], pick('CHANGELOG.md')[0]],
      [['gallery_test.mjs'], ['sync_test.py']])
check('a changed suite runs itself', pick('tests/py/hash_test.py')[0], ['hash_test.py'])
check('a file every suite of a kind needs runs every one of them',
      [pick('tests/harness.mjs')[0], pick('tests/fixtures.py')[0]],
      [['dialog_test.mjs', 'gallery_test.mjs'], ['hash_test.py', 'sync_test.py']])
check('code no suite was seen using runs everything that could use it',
      pick('model_manager/new_module.py')[0], ['dialog_test.mjs', 'gallery_test.mjs', 'hash_test.py', 'sync_test.py'])
check('a file no suite uses and that is not code runs none', pick('README.md')[0], [])
check('the static checks always run', 'check_js_references.mjs' in pick('README.md')[2], True)
check('a suite the map does not know yet runs', pick('README.md', known={'hash_test.py': []})[0],
      ['dialog_test.mjs', 'gallery_test.mjs', 'sync_test.py'])
check('with no map at all, everything runs, and records one',
      pick('README.md', known=None)[:2], (['dialog_test.mjs', 'gallery_test.mjs', 'hash_test.py', 'sync_test.py'], True))
check('the runner itself is not something a suite uses',
      [run.relative(os.path.join(run.ROOT, 'tests', 'trace_run.py')) in run.RUNNER], [True])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
