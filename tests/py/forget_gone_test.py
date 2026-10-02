"""
Forgetting files gone from disk, in one place (model_dirs.forget_gone, #81).

Scan Disk and a full sync both walk the library and then forget the rows of
files no longer there - each in its own code, with the rule that a walk which
found nothing forgets nothing (an unmounted drive, not an emptied library)
written two ways. What is checked: a walk that found nothing forgets nothing;
a file not found and not on disk is forgotten; one not found but still on
disk - a partial walk, a download filed elsewhere - is kept; and both the
scan and the sync forget through it, with no copy of their own.
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

import fixtures                                          # noqa: E402
from model_manager.model_dirs import forget_gone         # noqa: E402

WORK = os.path.join(TESTS, 'work', 'forget_gone')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
LIB = os.path.join(WORK, 'library')
os.makedirs(LIB, exist_ok=True)
here = os.path.join(LIB, 'still_here.safetensors')
open(here, 'wb').write(b'\0' * 8)
gone = os.path.join(LIB, 'deleted.safetensors')
for path in (here, gone):
    db.upsert_version({'file_path': path, 'file_name': os.path.basename(path)})
stored = set(db.get_all_version_paths())

check('a walk that found nothing forgets nothing', (forget_gone(db, []), set(db.get_all_version_paths())),
      ([], stored))
forgotten = forget_gone(db, [p for p in stored if p not in (here, gone)])
check('a file not found and not on disk is forgotten', gone in forgotten and gone not in db.get_all_version_paths(), True)
check('one not found but still on disk is kept', (here in forgotten, here in db.get_all_version_paths()), (False, True))

# Both walks forget through it.
for name in ('scan_service.py', 'sync_service.py'):
    tree = ast.parse(open(os.path.join(ROOT, 'model_manager', name), encoding='utf-8').read())
    called = {node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', '')
              for node in ast.walk(tree) if isinstance(node, ast.Call)}
    check('%s forgets through forget_gone, with no copy of its own' % name,
          ('forget_gone' in called, 'gone_from_disk' in called), (True, False))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
