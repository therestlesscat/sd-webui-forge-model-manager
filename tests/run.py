"""
Run everything, and say what could not be run and why.

    python tests/run.py                 the offline suites and the checks
    python tests/run.py --online        those, plus the ones that call Civitai
    python tests/run.py nsfw hash       only suites whose name contains these

A suite passes by exiting 0. Nothing here imports a framework: each file is a
script that prints its own failures, which keeps a suite readable on its own
and runnable on its own - `python tests/py/hash_test.py` is always valid.
"""
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Suites that reach out to Civitai. They check that our reading of the API still
# matches the API, which is worth knowing and worth not doing by default: they
# need the network, they are slow, and they fail for reasons that are not ours.
ONLINE = {'enums_test.js', 'picker_test.js', 'thumbs_test.js'}

# Suites that compare against a commit, to show a refactor changed nothing.
# They are history rather than a statement about today's code.
HISTORICAL = {'smoke.js', 'primary_file_test.js'}


def discover():
    """Every check, in the order it is worth seeing failures in."""
    out = []
    tools = os.path.join(HERE, 'tools')
    for name in sorted(os.listdir(tools)):
        if name.endswith(('.py', '.mjs')):
            out.append(('check', os.path.join(tools, name), name))
    for folder in ('py', 'js'):
        directory = os.path.join(HERE, folder)
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if name.endswith(('.py', '.js', '.mjs')):
                out.append((folder, os.path.join(directory, name), name))
    return out


def runner_for(path):
    return [sys.executable, path] if path.endswith('.py') else ['node', path]


def have_node():
    return shutil.which('node') is not None


def have_linkedom():
    return os.path.isdir(os.path.join(HERE, 'node_modules', 'linkedom'))


# A setting read once at import cannot be toggled mid-run, so these suites are
# run once per value instead. The label says which run it was.
VARIANTS = {
    'gallery_test.mjs': [('continuous', {'MM_IMAGE_BROWSING': 'continuous'}),
                         ('pages', {'MM_IMAGE_BROWSING': 'pages'})],
}


def main(argv):
    online = '--online' in argv
    wanted = [a for a in argv if not a.startswith('-')]

    node = have_node()
    linkedom = have_linkedom()

    passed = failed = skipped = 0
    failures = []
    started = time.time()

    for kind, path, name in discover():
        if wanted and not any(w.lower() in name.lower() for w in wanted):
            continue

        reason = None
        if name in ONLINE and not online:
            reason = 'needs Civitai; pass --online'
        elif name in HISTORICAL:
            reason = 'compares against a commit; run it by hand'
        elif path.endswith(('.js', '.mjs')) and not node:
            reason = 'node is not installed'
        elif name == 'dialog_test.mjs' and not linkedom:
            reason = 'run: npm install --prefix tests'

        label = '%-6s %s' % (kind, name)
        if reason:
            skipped += 1
            print('  SKIP  %-44s %s' % (label, reason))
            continue

        for suffix, extra in VARIANTS.get(name, [(None, {})]):
            env = dict(os.environ, **extra) if extra else None
            run_label = label if suffix is None else '%s (%s)' % (label, suffix)
            result = subprocess.run(runner_for(path), cwd=ROOT,
                                    capture_output=True, text=True, env=env)
            if result.returncode == 0:
                passed += 1
                print('  ok    %s' % run_label)
            else:
                failed += 1
                failures.append((run_label, result))
                print('  FAIL  %s' % run_label)

    print()
    for label, result in failures:
        print('=' * 72)
        print(label)
        tail = (result.stdout or '').strip().splitlines()[-25:]
        for line in tail:
            print('   %s' % line)
        if result.stderr.strip():
            for line in result.stderr.strip().splitlines()[-8:]:
                print('   ! %s' % line)
        print()

    print('%d passed, %d failed, %d skipped in %.1fs'
          % (passed, failed, skipped, time.time() - started))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
