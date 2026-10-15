"""
Which suites `run.py --changed` picks for a change.

Every run of everything records which of the extension's files each suite
uses; --changed runs the suites that use what changed. It must not skip a
suite a change needs - so a changed suite runs, a file every suite of a kind
depends on runs them all, and code no suite was seen using runs everything
that could - and must say why it chose each.
"""
import contextlib
import io
import json
import os
import subprocess
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
      pick('tests/fixtures.py')[0], ['hash_test.py', 'sync_test.py'])
# The harness sits beside the browser suites, and was taken for a changed
# suite: none ran, and the runner named it by a path it does not have (#137).
check('a change to the harness runs every browser suite',
      pick('tests/js/harness.mjs')[0], ['dialog_test.mjs', 'gallery_test.mjs'])
check('a helper beside the suites runs the suites the map has using it',
      pick('tests/js/shared_script.cjs',
           known=dict(MAP, **{'gallery_test.mjs': MAP['gallery_test.mjs'] + ['tests/js/shared_script.cjs']}))[0],
      ['gallery_test.mjs'])
check('the harness is no suite', 'harness.mjs' in [name for _, _, name in run.discover()], False)
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

# A tool's suite (TOOLS) - the NSFW model's trainer: a full run skips it, so
# it is never traced, and the map cannot say what it uses. It runs when a
# file it covers changes, and for nothing else.
TOOL_SUITES = SUITES + [('py', 'x', 'nsfw_trainer_test.py')]


def runs_trainer(*changed):
    run.changed_files = lambda: list(changed)
    return 'nsfw_trainer_test.py' in run.choose(TOOL_SUITES, MAP)[0]


check('a tool\'s suite runs when the tool changes', runs_trainer('tools/train_nsfw_model.py'), True)
check('   or nsfw.py, whose features the trainer writes', runs_trainer('model_manager/nsfw.py'), True)
check('   and not otherwise, though the map does not know it', runs_trainer('README.md'), False)
check('   not even for code no suite was seen using', runs_trainer('model_manager/brand_new.py'), False)
runs, skips = run.plan(['nsfw_trainer'], False, True, True)
check('a full run skips it, saying how to run it',
      ([label.split()[-1] for label, _ in skips], [reason for _, reason in skips], runs),
      (['nsfw_trainer_test.py'], ['a tool run by hand; pass --tools'], []))
check('   and --tools runs it',
      [label.split()[-1] for label, *_ in run.plan(['nsfw_trainer'], False, True, True, tools=True)[0]],
      ['nsfw_trainer_test.py'])

# The slowest suites of the last run start first, so a run does not end
# waiting on one that started late (#270). The static checks start before
# them all the same, as they fail fastest, and a suite with no time yet is
# taken for a slow one. Printed, the results keep the list's order.
WORK = os.path.join(TESTS, 'work', 'runner')
os.makedirs(WORK, exist_ok=True)
run.TIMES = os.path.join(WORK, 'test_times.json')
run.FAILURES = os.path.join(WORK, 'last_failures.log')
RUNS = [('check  a.py', ['a'], None, ('check', 'x', 'a.py')),
        ('py     quick_test.py', ['q'], None, ('py', 'x', 'quick_test.py')),
        ('py     new_test.py', ['n'], None, ('py', 'x', 'new_test.py')),
        ('js     slow_test.mjs', ['s'], None, ('js', 'x', 'slow_test.mjs'))]
LAST = {'a.py': 0.1, 'quick_test.py': 0.2, 'slow_test.mjs': 9.0, 'other_test.py': 3.0}
TOOK = {'a.py': 0.3, 'quick_test.py': 0.4, 'new_test.py': 5.0, 'slow_test.mjs': 8.0}
started = []


def fake_run(command, env, suite=None, record=False):
    started.append(suite[2])
    return subprocess.CompletedProcess(command, 0, '', ''), TOOK[suite[2]], None


def one_at_a_time(last):
    """A run of RUNS, one suite at a time: the order they started in, and
    the order they were printed in."""
    if last is None:
        if os.path.exists(run.TIMES):
            os.remove(run.TIMES)
    else:
        with open(run.TIMES, 'w', encoding='utf-8') as f:
            json.dump(last, f)
    del started[:]
    run.plan = lambda *args, **kwargs: (list(RUNS), [])
    run.run_one = fake_run
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        run.main(['x', '-j', '1'])
    printed = [line.split()[2] for line in out.getvalue().splitlines() if line.startswith('  ok')]
    return list(started), printed


order, printed = one_at_a_time(LAST)
check('the checks start first, then a suite with no time yet, then the slowest',
      order, ['a.py', 'new_test.py', 'slow_test.mjs', 'quick_test.py'])
check('   and the results are printed in the list\'s order', printed, [r[3][2] for r in RUNS])
check('each run keeps the times it measured; a suite it did not run keeps its own',
      json.load(open(run.TIMES, encoding='utf-8')), dict(LAST, **TOOK))
check('with no times kept, they start in the list\'s order', one_at_a_time(None)[0], [r[3][2] for r in RUNS])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
