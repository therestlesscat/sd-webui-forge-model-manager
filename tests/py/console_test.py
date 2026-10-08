"""
What the extension writes to the console (model_manager/console.py): every
"[ModelManager]" line goes through say(), which prints it and keeps the last
of them for the sync's log panel - so a print of its own, anywhere in the
extension, would reach the console and never the panel.
"""
import io
import os
import re
import sys
import threading
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from model_manager import console                        # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# --------------------------------------------------------------- said and kept
start = console.said()
out = io.StringIO()
with redirect_stdout(out):
    console.say('Found Crystal ball via SHA256')
    console.say('Error calculating hashes for broken.safetensors')
check('a line reaches the console as it always did', out.getvalue().splitlines(),
      ['[ModelManager] Found Crystal ball via SHA256',
       '[ModelManager] Error calculating hashes for broken.safetensors'])
lines, after = console.since(start)
check('and is kept, without the prefix, numbered', [(l['n'] - start, l['text']) for l in lines],
      [(1, 'Found Crystal ball via SHA256'), (2, 'Error calculating hashes for broken.safetensors')])
check('with the time it was said', all(re.fullmatch(r'\d\d:\d\d:\d\d', l['time']) for l in lines), True)
check('and the number to ask from next', (after, console.said()), (start + 2, start + 2))
check('asked from there, nothing new', console.since(after), ([], after))

# ------------------------------------------------------------- only the latest
with redirect_stdout(io.StringIO()):
    for i in range(console.KEPT + 25):
        console.say('line %d' % i)
lines, after = console.since(0)
check('only the last lines are kept', len(lines), console.KEPT)
check('the latest of them', lines[-1]['text'], 'line %d' % (console.KEPT + 24))
check('a reader far behind gets the latest, not a gap it cannot see', lines[0]['n'], after - console.KEPT + 1)

# ---------------------------------------------------------- from many threads
start = console.said()
with redirect_stdout(io.StringIO()):
    threads = [threading.Thread(target=lambda: [console.say('from a worker') for _ in range(100)])
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
lines, after = console.since(start)
check('lines said at once from many threads are each counted once',
      (after - start, len({l['n'] for l in lines})), (800, 800))

# ------------------------------------------------------------- a failure (#143)
# What went wrong, and where: the trace went to stderr alone, which the sync's
# log panel never sees. One kept line, so a trace is one entry of the KEPT.
say_failure = getattr(console, 'say_failure', None)
check('the console can say a failure', callable(say_failure), True)
if callable(say_failure):
    start = console.said()
    out = io.StringIO()
    with redirect_stdout(out):
        try:
            {}['missing']
        except KeyError:
            say_failure('Tags search error')
    lines, after = console.since(start)
    text = lines[0]['text'] if lines else ''
    check('as one kept line', after - start, 1)
    check('its message first, then the trace and the exception',
          [text.startswith('Tags search error'), 'Traceback (most recent call last)' in text,
           "KeyError: 'missing'" in text], [True, True, True])
    check('and the same on the console', out.getvalue(), '[ModelManager] ' + text + '\n')

# -------------------------------------------------- nothing prints on its own
# The migrations are left as they shipped (AGENTS.md: never edited), and run
# at startup, not during a sync.
OWN = re.compile(r'''print\(\s*f?["']\[ModelManager\]''')
found = []
for base in ('model_manager', 'scripts'):
    for folder, _, names in os.walk(os.path.join(ROOT, base)):
        for name in names:
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
            if not name.endswith('.py') or rel in ('model_manager/console.py', 'model_manager/db/migrations.py'):
                continue
            if OWN.search(io.open(path, encoding='utf-8').read()):
                found.append(rel)
check('every "[ModelManager]" line goes through console.say', found, [])

# Nor a trace: console.say_failure says it. The migrations keep theirs.
TRACE = re.compile(r'\bprint_exc\(')
traced = []
for base in ('model_manager', 'scripts'):
    for folder, _, names in os.walk(os.path.join(ROOT, base)):
        for name in names:
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
            if not name.endswith('.py') or rel in ('model_manager/console.py', 'model_manager/db/migrations.py'):
                continue
            traced += [rel] * len(TRACE.findall(io.open(path, encoding='utf-8').read()))
check('every trace goes through console.say_failure', sorted(traced), [])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
