"""
Run one Python suite, noting which of the extension's files it used.

    python tests/trace_run.py <suite.py> <out.json>

Used by run.py when it records which suites a change needs (see --changed).
A file is used if a function in it was called, or if the suite opened it -
style.css, the changelog, the NSFW model. Importing alone does not count:
nearly every suite imports the whole package through the API. The suite
runs as __main__, exactly as it would on its own, and exits with its code.
"""
import json
import os
import runpy
import sys
import threading

ROOT = os.path.normcase(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
suite, out = sys.argv[1], sys.argv[2]
used = set()


def ours(path):
    if not path or path.startswith('<'):
        return None                     # Python's own: <frozen os>, <string>
    try:
        path = os.path.normcase(os.path.abspath(path))
    except (TypeError, ValueError):
        return None
    return path if path.startswith(ROOT + os.sep) else None


CO_OPTIMIZED = 0x1          # a function's code; a module's or a class body's is not

# Called for every suite that builds the app: it attaches the endpoints, and
# running it uses none of them.
SETUP = {'register', 'setup_api', 'on_app_started'}


def profile(frame, event, arg):
    code = frame.f_code
    if event == 'call' and code.co_flags & CO_OPTIMIZED and code.co_name not in SETUP:
        # A generator expression or comprehension run by module-level code -
        # a table built at import - is part of importing, not of using.
        if code.co_name.startswith('<') and frame.f_back and frame.f_back.f_code.co_name == '<module>':
            return
        path = ours(code.co_filename)
        if path:
            used.add(path)


def audit(event, args):
    if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path = ours(os.fsdecode(args[0]))
        if path:
            used.add(path)


def write():
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(sorted(used), f)


sys.addaudithook(audit)
sys.setprofile(profile)
threading.setprofile(profile)
sys.argv = [suite]
code = 0
try:
    runpy.run_path(suite, run_name='__main__')
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
finally:
    sys.setprofile(None)
    threading.setprofile(None)
    write()
sys.exit(code)
