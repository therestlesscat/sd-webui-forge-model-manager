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


def noted(code, caller):
    """
    Note the file of a function that has started, if it is ours. False while
    undecided: a generator expression or comprehension run by module-level
    code - a table built at import - is part of importing, not of using, and
    may yet be called from elsewhere.
    """
    if not code.co_flags & CO_OPTIMIZED or code.co_name in SETUP:
        return True
    if code.co_name.startswith('<') and caller is not None and caller.f_code.co_name == '<module>':
        return False
    path = ours(code.co_filename)
    if path:
        used.add(path)
    return True


# Python 3.12 and later: each function is reported once, then turned off for
# it (DISABLE). A profile hook was called on every call, Python's and C's
# alike, for the whole run: it doubled --all, 36 s to 72 s, and one suite
# from 1.5 s to 10.5 s.
MONITORING = getattr(sys, 'monitoring', None)
TOOL = MONITORING.PROFILER_ID if MONITORING else None


def started(code, offset):
    # Frame 1 is the function starting; what called it is its f_back.
    return MONITORING.DISABLE if noted(code, sys._getframe(1).f_back) else None


def profile(frame, event, arg):
    if event == 'call':
        noted(frame.f_code, frame.f_back)


def audit(event, args):
    if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path = ours(os.fsdecode(args[0]))
        if path:
            used.add(path)


def write():
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(sorted(used), f)


sys.addaudithook(audit)
if MONITORING:
    MONITORING.use_tool_id(TOOL, 'trace_run')
    MONITORING.register_callback(TOOL, MONITORING.events.PY_START, started)
    MONITORING.set_events(TOOL, MONITORING.events.PY_START)
else:
    sys.setprofile(profile)
    threading.setprofile(profile)
sys.argv = [suite]
code = 0
try:
    runpy.run_path(suite, run_name='__main__')
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
finally:
    if MONITORING:
        MONITORING.set_events(TOOL, 0)
    else:
        sys.setprofile(None)
        threading.setprofile(None)
    write()
sys.exit(code)
