"""
Line coverage of the extension's code by the offline suites. A measurement,
run by hand - not a suite, and not part of a full run:

    python tests/coverage.py            every suite a full run runs, 4 at a time

Writes tests/work/coverage/report.txt - each file's lines, lines run, and its
longest stretches not run, least covered first - and coverage.csv. About as
long as a full run. Nothing to install:

- Python: each suite through this file's --suite mode, which records lines
  with sys.monitoring LINE events - each line reported once, then DISABLEd.
  A line is one Python can run (its code objects' co_lines), import-time
  lines (import, def, a class body) included, as coverage.py counts them.
- JavaScript: NODE_V8_COVERAGE, V8's block counts mapped to lines. A line
  counts when it has code (not blank, not only a comment), and is run when
  no part of it lies in a block counted 0, in some suite.

What it cannot see: code a suite copies out of its module into a vm sandbox
(vae_test, vae_meta_test, progress_test, three_js_test) is credited to the
sandbox, not the file; a subprocess a suite starts (the trainer) is not
followed.
"""
import csv
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlparse

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
OUT = os.path.join(TESTS, 'work', 'coverage')


def load_runner():
    """The runner, for the suites a full run runs (its plan())."""
    spec = importlib.util.spec_from_file_location('runner', os.path.join(TESTS, 'ru' + 'n.py'))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


# ------------------------------------------------------- one Python suite
def run_one_suite(suite, out):
    """Run a suite as __main__, recording which of the repository's lines ran."""
    import runpy
    root = os.path.normcase(ROOT)
    monitoring, ran, known = sys.monitoring, {}, {}
    tool = monitoring.COVERAGE_ID

    def ours(filename):
        if filename not in known:
            path = None
            if filename and not filename.startswith('<'):
                path = os.path.normcase(os.path.abspath(filename))
                if not path.startswith(root + os.sep):
                    path = None
            known[filename] = path
        return known[filename]

    def line(code, number):
        path = ours(code.co_filename)
        if path:
            ran.setdefault(path, set()).add(number)
        return monitoring.DISABLE

    monitoring.use_tool_id(tool, 'coverage')
    monitoring.register_callback(tool, monitoring.events.LINE, line)
    monitoring.set_events(tool, monitoring.events.LINE)
    sys.argv = [suite]
    code = 0
    try:
        runpy.run_path(suite, run_name='__main__')
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        monitoring.set_events(tool, 0)
        with open(out, 'w', encoding='utf-8') as f:
            json.dump({p: sorted(lines) for p, lines in ran.items()}, f)
    return code


# ---------------------------------------------------------------- the run
def code_files():
    listed = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True).stdout.split()
    return [f for f in listed
            if (f.startswith(('model_manager/', 'scripts/')) and f.endswith('.py'))
            or (f.startswith('javascript/') and f.endswith(('.mjs', '.js')))]


def key(path):
    return os.path.normcase(os.path.abspath(path))


# ------------------------------------------------------------------ running
def run_suite(item):
    label, command, env, (kind, path, name) = item
    env = dict(env or os.environ)
    if kind == 'py':
        out = os.path.join(OUT, 'py', name + '.json')
        command = [sys.executable, os.path.abspath(__file__), '--suite', path, out]
    else:
        env['NODE_V8_COVERAGE'] = os.path.join(OUT, 'js', name)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=env)
    return name, result.returncode


# ------------------------------------------------------------------- python
def python_lines(path):
    """Every line Python can run in a file: its code objects' lines."""
    source = open(path, encoding='utf-8').read()
    lines, todo = set(), [compile(source, path, 'exec')]
    while todo:
        code = todo.pop()
        lines.update(n for _, _, n in code.co_lines() if n)
        todo.extend(c for c in code.co_consts if hasattr(c, 'co_lines'))
    return lines


def python_ran():
    ran = {}
    folder = os.path.join(OUT, 'py')
    for name in os.listdir(folder):
        for path, lines in json.load(open(os.path.join(folder, name))).items():
            ran.setdefault(path, set()).update(lines)
    return ran


# --------------------------------------------------------------- javascript
COMMENT = re.compile(r'^\s*(//|/\*|\*|\*/)')


def js_code_lines(text):
    """Lines with code, and where each starts and ends in the text."""
    code, at = {}, 0
    for n, line in enumerate(text.split('\n'), 1):
        if line.strip() and not COMMENT.match(line):
            code[n] = (at + len(line) - len(line.lstrip()), at + len(line))
        at += len(line) + 1
    return code


def js_run():
    """file key -> lines run in some suite: no part of the line in a block counted 0."""
    texts, run = {}, {}
    folder = os.path.join(OUT, 'js')
    for suite in os.listdir(folder):
        for report in os.listdir(os.path.join(folder, suite)):
            data = json.load(open(os.path.join(folder, suite, report), encoding='utf-8'))
            for script in data.get('result', []):
                url = script.get('url', '')
                if not url.startswith('file:') or '/javascript/' not in url:
                    continue
                path = unquote(urlparse(url).path).lstrip('/') if os.name == 'nt' else unquote(urlparse(url).path)
                k = key(path)
                if k not in texts:
                    text = open(path, encoding='utf-8').read()
                    texts[k] = (len(text), js_code_lines(text))
                size, code = texts[k]
                counts = bytearray(size + 1)        # 0 never ran, 1 ran; ranges outermost first
                for function in script['functions']:
                    for r in function['ranges']:
                        start, end = r['startOffset'], min(r['endOffset'], size)
                        counts[start:end] = (b'\x01' if r['count'] else b'\x00') * (end - start)
                lines = run.setdefault(k, set())
                lines.update(n for n, (a, b) in code.items() if b > a and 0 not in counts[a:b])
    return run


# ------------------------------------------------------------------- report
def gaps(code, run, most=3):
    """The longest stretches of code lines not run: (first, last, how many)."""
    out, start, size, last = [], None, 0, None
    for n in sorted(code):
        if n in run:
            if start is not None:
                out.append((start, last, size))
            start, size = None, 0
        else:
            if start is None:
                start = n
            size += 1
        last = n
    if start is not None:
        out.append((start, last, size))
    return sorted(out, key=lambda g: -g[2])[:most]


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, 'py'))
    os.makedirs(os.path.join(OUT, 'js'))
    runner = load_runner()
    runs, _ = runner.plan([], False, runner.have_node(), runner.have_linkedom())
    runs = [r for r in runs if r[3][0] in ('py', 'js')]
    started = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run_suite, runs))
    failed = [name for name, code in results if code]
    print('%d suites in %.1fs%s' % (len(results), time.time() - started,
                                    ', failed: ' + ', '.join(failed) if failed else ''))

    py_ran, js = python_ran(), js_run()
    rows = []
    for f in code_files():
        path = os.path.join(ROOT, f)
        if f.endswith('.py'):
            code = python_lines(path)
            run = py_ran.get(key(path), set()) & code
        else:
            code = set(js_code_lines(open(path, encoding='utf-8').read()))
            run = js.get(key(path), set()) & code
        rows.append((f, len(code), len(run), gaps(code, run)))

    with open(os.path.join(OUT, 'coverage.csv'), 'w', newline='', encoding='utf-8') as out:
        w = csv.writer(out)
        w.writerow(['file', 'lines', 'run', 'percent'])
        for f, n, r, _ in rows:
            w.writerow([f, n, r, '%.1f' % (100 * r / n) if n else ''])

    lines = []
    for kind, ends in (('Python', ('.py',)), ('JavaScript', ('.mjs', '.js'))):
        part = [r for r in rows if r[0].endswith(ends)]
        n, r = sum(x[1] for x in part), sum(x[2] for x in part)
        lines.append('%-10s %5d of %5d lines run: %.1f%%' % (kind, r, n, 100 * r / n if n else 0))
    lines.append('')
    lines.append('%-46s %6s %6s %6s  longest stretches not run' % ('file', 'lines', 'run', '%'))
    for f, n, r, g in sorted(rows, key=lambda x: (x[2] / x[1] if x[1] else 1)):
        lines.append('%-46s %6d %6d %5.1f%%  %s' % (f, n, r, 100 * r / n if n else 100,
                     ', '.join('%d-%d (%d)' % s for s in g)))
    report = '\n'.join(lines)
    open(os.path.join(OUT, 'report.txt'), 'w', encoding='utf-8').write(report + '\n')
    print(report)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--suite':
        sys.exit(run_one_suite(sys.argv[2], sys.argv[3]))
    main()
