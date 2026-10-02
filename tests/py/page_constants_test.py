"""
What the page and the server both write down, held equal (#86).

The page draws NSFW badges, the NSFW filter and the settings window before
any answer of the server's could come, so it keeps its own copy of the NSFW
levels and of the setting keys it reads; the server has the originals
(nsfw.py, forge_host.DEFAULTS). The copies were by hand, and in three places
for the level names - nsfw.mjs's ratings, its badge's own Blocked, and the
Model Manager's two tables. Now the page has one table of levels, in
nsfw.mjs, and what is checked: it is nsfw.py's, name for name; Unknown, the
work-safe ceiling and the levels one can rate are nsfw.py's; no other file of
the page names a level; and every setting key the page writes is one the
server has.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

from model_manager import nsfw                           # noqa: E402
from model_manager.forge_host import DEFAULTS           # noqa: E402

# The page's files: from MM_ROOT when a check is shown failing on other code.
PAGE = os.path.join(os.environ.get('MM_ROOT') or ROOT, 'javascript')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def read(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    return re.sub(r'/\*[\s\S]*?\*/', '', re.sub(r'(^|[^:])//[^\n]*', r'\1', text))


files = {}
for folder in (PAGE, os.path.join(PAGE, 'shared')):
    for name in sorted(os.listdir(folder)):
        if name.endswith('.mjs'):
            files[os.path.relpath(os.path.join(folder, name), PAGE).replace('\\', '/')] = read(os.path.join(folder, name))

# ------------------------------------------------------------- the levels
page = files['shared/nsfw.mjs']
table = re.search(r'export const NSFW_LEVELS = \[([\s\S]*?)\];', page)
levels = [(int(v), n) for v, n in re.findall(r"\[(\d+), '([^']+)'\]", table.group(1))] if table else []
check('the page has one table of levels: nsfw.py\'s, name for name', levels, sorted(nsfw.LEVEL_TO_NAME.items()))

def number(name):
    m = re.search(r'export const %s = (\d+);' % name, page)
    return int(m.group(1)) if m else None

check('Unknown is nsfw.py\'s', number('NSFW_UNKNOWN'), nsfw.UNKNOWN)
check('and the work-safe ceiling', number('NSFW_SFW_MAX'), nsfw.SFW_MAX)
rated = re.search(r'const USER_LEVELS = \[([\d, ]*)\];', page)
check('and the levels one can rate', [int(v) for v in rated.group(1).split(',')] if rated else None,
      list(nsfw.USER_LEVELS))

names = '|'.join(re.escape(n) for n in nsfw.LEVEL_TO_NAME.values() if n not in ('R', 'X', 'Unknown'))
check('no other file of the page names a level',
      sorted(f for f, text in files.items() if f != 'shared/nsfw.mjs' and re.search(r"'(%s)'" % names, text)), [])

# ------------------------------------------------------------ setting keys
# A DOM id shares the prefix; so does the start of the modules' keys, which
# the settings window adds a preset's name to.
NOT_KEYS = {'model_manager_app', 'model_manager_modules_'}
written = {m for text in files.values() for m in re.findall(r"['\"`](model_manager_[a-z0-9_]+)['\"`]", text)}
check('the page writes setting keys', len(written - NOT_KEYS) > 10, True)
check('and every one is a setting the server has', sorted(written - NOT_KEYS - set(DEFAULTS)), [])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
