"""
Run everything, and say what could not be run and why.

    python tests/run.py                 the offline suites and the checks
    python tests/run.py --online        those, plus the ones that call Civitai
    python tests/run.py nsfw hash       only suites whose name contains these
    python tests/run.py -j 4            at most 4 suites at a time (default: one per CPU)
    python tests/run.py --changed       only the suites the uncommitted changes need
    python tests/run.py --all           everything, said outright (what a bare run does)

A run of everything also records which of the extension's files each suite
uses, in tests/work/test_map.json; --changed reads it to pick the suites a
change needs. While working, run --changed; run everything before a commit.

A suite passes by exiting 0. Nothing here imports a framework: each file is a
script that prints its own failures, which keeps a suite readable on its own
and runnable on its own - `python tests/py/hash_test.py` is always valid.
"""
import os
import shutil
import subprocess
import sys
import json
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Suites that reach out to Civitai. They check that our reading of the API still
# matches the API, which is worth knowing and worth not doing by default: they
# need the network, they are slow, and they fail for reasons that are not ours.
ONLINE = {'enums_test.js', 'picker_test.js', 'thumbs_test.js'}

# Suites that compare against a commit, to show a refactor changed nothing.
# They are history rather than a statement about today's code.
HISTORICAL = {'smoke.js', 'primary_file_test.js', 'card_parity_test.mjs'}


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
VARIANTS = {}


# ---------------------------------------------------------------- the map
# Which of the extension's files each suite uses: recorded by every run of
# everything, read by --changed. Per machine, so under tests/work.
MAP = os.path.join(HERE, 'work', 'test_map.json')
TRACE = os.path.join(HERE, 'work', 'trace')

# Files every suite of a kind depends on: a change to one needs them all.
SHARED = {
    'tests/harness.mjs': 'js',
    'tests/fixtures.py': 'py',
    'tests/webui_stub.py': 'py',
    'tests/package.json': 'js',
}
CODE = ('model_manager/', 'javascript/', 'scripts/', 'style.css', 'install.py')
# The runner and its tracing: every suite runs through them when recording.
RUNNER = {'tests/run.py', 'tests/trace_run.py', 'tests/trace_node.cjs'}


def relative(path):
    """A path as the map keeps it: from the repository root, with /, in the
    case the OS compares by - lower on Windows, where git's may differ."""
    rel = os.path.relpath(os.path.normcase(os.path.abspath(path)), os.path.normcase(ROOT))
    return rel.replace(os.sep, '/')


def traced(kind, path, name, command, env):
    """The same run, noting which files the suite uses."""
    os.makedirs(TRACE, exist_ok=True)
    out = os.path.join(TRACE, name + '.json')
    env = dict(env or os.environ)
    if kind == 'py':
        return [sys.executable, os.path.join(HERE, 'trace_run.py'), path, out], env, out
    env['NODE_V8_COVERAGE'] = os.path.join(TRACE, name + '.cov')
    env['MM_TRACE_OUT'] = out
    return [command[0], '--require', os.path.join(HERE, 'trace_node.cjs')] + command[1:], env, out


def files_used(kind, name, out):
    """What a traced run used: functions called, and files read."""
    used = set()
    try:
        used.update(json.load(open(out, encoding='utf-8')))
    except (OSError, ValueError):
        pass
    coverage = os.path.join(TRACE, name + '.cov')
    for report in (os.listdir(coverage) if os.path.isdir(coverage) else []):
        try:
            data = json.load(open(os.path.join(coverage, report), encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for script in data.get('result', []):
            url = script.get('url', '')
            if not url.startswith('file:'):
                continue
            # The first function is the module itself, run by importing it;
            # any other that ran means the suite used the file.
            if any(f['ranges'][0]['count'] > 0 for f in script['functions'][1:]):
                from urllib.parse import unquote, urlparse
                used.add(unquote(urlparse(url).path).lstrip('/') if os.name == 'nt'
                         else unquote(urlparse(url).path))
    kept = set()
    for path in used:
        rel = relative(path)
        if rel.startswith('<') or '__pycache__' in rel or rel in RUNNER:
            continue                    # Python's own, compiled copies, and this runner
        if not rel.startswith('..') and not rel.startswith(('tests/work/', 'tests/node_modules/')):
            kept.add(rel)
    return sorted(kept)


def changed_files():
    """What differs from the last commit, new files included."""
    def git(*args):
        result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    files = set(git('diff', '--name-only', 'HEAD')) | set(git('ls-files', '--others', '--exclude-standard'))
    return sorted(f for f in files if not f.startswith('tests/work/'))


def choose(suites, known):
    """
    The suites a change needs, each with why: (name -> reason). `suites` is
    every suite that could run, `known` the recorded map; None when there is
    no map, and everything has to run.
    """
    changed = changed_files()
    chosen = {}
    if known is None:
        return {name: 'no map yet: this run records it' for _, _, name in suites}, changed, True
    for kind, path, name in suites:
        if name not in known and kind != 'check':
            chosen[name] = 'not in the map yet'
    for f in changed:
        base = os.path.basename(f)
        if f.startswith(('tests/py/', 'tests/js/')):
            if any(name == base for _, _, name in suites):
                chosen[base] = 'the suite itself changed'
        elif f in SHARED:
            for kind, _, name in suites:
                if kind == SHARED[f]:
                    chosen.setdefault(name, 'shared by every %s suite: %s' % (kind, f))
        else:
            key = relative(os.path.join(ROOT, f))
            users = [name for name, used in known.items() if key in used]
            if not users and f.startswith(CODE):
                # Code no recorded run used: new, or reached only in a way
                # the trace does not see. Everything that could use it runs.
                for kind, _, name in suites:
                    if kind != 'check':
                        chosen.setdefault(name, 'no suite recorded as using %s' % f)
            for name in users:
                if any(name == n for _, _, n in suites):
                    chosen.setdefault(name, 'uses %s' % f)
    # The static checks read the whole tree, and take two seconds.
    for kind, _, name in suites:
        if kind == 'check':
            chosen.setdefault(name, 'static check, always run')
    return chosen, changed, False


def plan(wanted, online, node, linkedom):
    """
    What to run, in the order failures are worth reading: (label, command,
    environment) for each run, or (label, reason) for each suite skipped.
    """
    runs, skips = [], []
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
            skips.append((label, reason))
            continue
        for suffix, extra in VARIANTS.get(name, [(None, {})]):
            env = dict(os.environ, **extra) if extra else None
            runs.append((label if suffix is None else '%s (%s)' % (label, suffix),
                         runner_for(path), env, (kind, path, name)))
    return runs, skips


def run_one(command, env, suite=None, record=False):
    """One suite, in its own process: its result, how long it took, and -
    when recording - the files it used."""
    out = None
    if record and suite and suite[0] in ('py', 'js'):
        command, env, out = traced(suite[0], suite[1], suite[2], command, env)
    started = time.time()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=env)
    took = time.time() - started
    return result, took, (files_used(suite[0], suite[2], out) if out else None)


def main(argv):
    online = '--online' in argv
    jobs = os.cpu_count() or 4
    for i, arg in enumerate(argv):
        if arg in ('-j', '--jobs') and i + 1 < len(argv):
            jobs = max(1, int(argv[i + 1]))
    wanted = [a for i, a in enumerate(argv)
              if not a.startswith('-') and not (i and argv[i - 1] in ('-j', '--jobs'))]
    changed_only = '--changed' in argv

    runs, skips = plan(wanted, online, have_node(), have_linkedom())
    started = time.time()

    known = None
    if os.path.exists(MAP):
        try:
            known = json.load(open(MAP, encoding='utf-8'))['suites']
        except (OSError, ValueError, KeyError):
            known = None
    record = not wanted and not changed_only
    if changed_only:
        chosen, changed, everything = choose([r[3] for r in runs], known)
        record = everything
        print('%d file(s) changed since the last commit%s' % (
            len(changed), ': ' + ', '.join(changed[:8]) + (' ...' if len(changed) > 8 else '') if changed else ''))
        runs = [r for r in runs if r[3][2] in chosen]
        skips = []
        for label, command, env, suite in runs:
            print('  run   %-44s %s' % (label, chosen[suite[2]]))
        print()
    for label, reason in skips:
        print('  SKIP  %-44s %s' % (label, reason))

    # Every suite is its own process with its own tests/work folder, so they
    # run side by side; the results are printed in order all the same.
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [(label, suite, pool.submit(run_one, command, env, suite, record))
                   for label, command, env, suite in runs]
        failures, timings, used = [], [], {}
        for label, suite, future in futures:
            result, took, files = future.result()
            if files is not None:
                used.setdefault(suite[2], set()).update(files)
            timings.append((took, label))
            if result.returncode == 0:
                print('  ok    %-44s %5.1fs' % (label, took))
            else:
                failures.append((label, result))
                print('  FAIL  %-44s %5.1fs' % (label, took))

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

    if record and used:
        recorded = dict(known or {}) if not record else {}
        recorded.update({name: sorted(files) for name, files in used.items()})
        os.makedirs(os.path.dirname(MAP), exist_ok=True)
        with open(MAP, 'w', encoding='utf-8') as f:
            json.dump({'recorded': time.strftime('%Y-%m-%d %H:%M'), 'suites': recorded}, f, indent=1)
        print('Recorded which files each of %d suites uses, for --changed.' % len(recorded))

    passed = len(runs) - len(failures)
    print('%d passed, %d failed, %d skipped in %.1fs (%d at a time; slowest: %s %.1fs)'
          % (passed, len(failures), len(skips), time.time() - started, jobs,
             max(timings)[1].split()[-1] if timings else '-', max(timings)[0] if timings else 0))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
