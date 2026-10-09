"""
The Python checker (tests/tools/check_python_references.py), run on a copy of
the package with a slip put back. It only ever ran on the real package, which
holds none: R30 moved files_by_name from api/models.py up to resources.py,
its in-function `from ..hashing import names_this_file` now climbing above
model_manager, and the checker passed it - Python refuses it, but only when
the function is called (#110).
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)

WORK = os.path.join(TESTS, 'work', 'check_python_references')
CHECKER = os.path.join(TESTS, 'tools', 'check_python_references.py')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


shutil.rmtree(WORK, ignore_errors=True)
shutil.copytree(os.path.join(ROOT, 'model_manager'), os.path.join(WORK, 'model_manager'),
                ignore=shutil.ignore_patterns('__pycache__'))
resources = os.path.join(WORK, 'model_manager', 'resources.py')
with open(resources, encoding='utf-8') as f:
    lines = f.read().splitlines()
lines += ['', '', 'def _left_from_api():',
          '    from ..hashing import names_this_file',
          '    return names_this_file']
slip = len(lines) - 1                         # the import's line
with open(resources, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')

run = subprocess.run([sys.executable, CHECKER], capture_output=True, text=True, timeout=60,
                     env=dict(os.environ, MM_PY_ROOT=WORK))
said = [line for line in run.stdout.splitlines() if line.startswith('FAIL ')]

check('an import climbing above model_manager fails, naming the file and its line',
      ('model_manager/resources.py:%d: from ..hashing climbs above model_manager - Python refuses it' % slip
       in run.stdout, run.returncode), (True, 1))
check('it is the only failure: the 152 imports of two dots or more from sub-packages pass',
      len(said), 1)

shutil.rmtree(WORK, ignore_errors=True)
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
