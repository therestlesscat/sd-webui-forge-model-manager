"""
The counts beside a gallery's switches, and in its banner, mean the same
whoever counts them (#74).

A page counts its images in Python (gallery.switch_counts, through
filter_images for Civitai images); the banner counts every stored image in
SQL (ImagesOps.get_image_counts). A switch's number holds when it is flipped
(model_manager/AGENTS.md, "A gallery switch's number holds") - which needs
the two to agree, for every combination of the switches. They were written
apart, and nothing held them to each other.

Prompts padded with tabs and newlines are among them: Python's strip() and
SQL's TRIM disagreed on those (#61) - "\t\tab\n" was unreadable to one and
readable to the other - until both trimmed by prompt_rules.
"""
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

from model_manager.db import ModelsDatabase              # noqa: E402
from model_manager.gallery import filter_images, switch_counts, switch_counts_sql   # noqa: E402
from model_manager.nsfw import SFW_MAX                   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'switch_counts')
os.makedirs(WORK, exist_ok=True)
for name in os.listdir(WORK):
    os.remove(os.path.join(WORK, name))

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# Every kind there is: safe and explicit, each with a prompt worth reading,
# a short one, an empty one, and none - so no count is zero by accident.
PROMPTS = ['a prompt long enough to read', 'ok', '', None, '\t\tab\n', ' \r\nfour\n\t']
IMAGES = []
for level in (1, 2, 4, 8, 16):
    for prompt in PROMPTS:
        meta = None if prompt is None else {'prompt': prompt}
        IMAGES.append({'id': len(IMAGES) + 1, 'url': 'u%d' % len(IMAGES), 'browsingLevel': level,
                       'meta': meta})

db = ModelsDatabase(WORK, custom_db_path=os.path.join(WORK, 'counts.db'))
VERSION = 4242
db.store_images(VERSION, 1, IMAGES)
KEYS = ('total', 'filtered', 'hidden_nsfw', 'hidden_promptless', 'hidden_both', 'hidden',
        'nsfw_count', 'promptless_count', 'promptless_total')

for hide_nsfw in (False, True):
    for hide_promptless in (False, True):
        shown, py = filter_images(IMAGES, hide_nsfw, hide_promptless)
        sql = db.get_image_counts(VERSION, max_nsfw_level=SFW_MAX if hide_nsfw else None,
                                  require_prompt=hide_promptless)
        check('hide NSFW %s, hide unusable prompts %s: the page counts as the banner does'
              % (hide_nsfw, hide_promptless),
              {k: py[k] for k in KEYS}, {k: sql[k] for k in KEYS})
        check('and shows the images it counts as shown (%s, %s)' % (hide_nsfw, hide_promptless),
              len(shown), py['filtered'])

_, both = filter_images(IMAGES, True, True)
check('none of the counts is zero by accident', all(both[k] for k in KEYS), True)

# Every gallery counts through one function; how it tells safe and readable
# is the only part its own. The same answers from the same verdicts:
safe = [img['browsingLevel'] <= SFW_MAX for img in IMAGES]
readable = [bool(img['meta'] and len((img['meta'].get('prompt') or '').strip(' \t\r\n')) >= 4)
            for img in IMAGES]
check('switch_counts, given the verdicts, counts as filter_images does',
      switch_counts(IMAGES, safe, readable, True, True)[1], both)

# The same counts in SQL, for a read that counts in the database (#231): every
# mix of verdicts, through every combination of the switches.
import itertools                                         # noqa: E402
import sqlite3                                           # noqa: E402
verdicts = list(itertools.product((0, 1), repeat=2)) * 2 + [(1, 0), (0, 0), (0, 1)]
memory = sqlite3.connect(':memory:')
memory.execute('CREATE TABLE rows (safe INTEGER, readable INTEGER)')
memory.executemany('INSERT INTO rows VALUES (?, ?)', verdicts)
memory.row_factory = sqlite3.Row
for hide_nsfw, hide_promptless in itertools.product((False, True), repeat=2):
    sql = dict(memory.execute(f'SELECT {switch_counts_sql(hide_nsfw, hide_promptless)} FROM rows').fetchone())
    python = switch_counts(verdicts, [bool(v[0]) for v in verdicts], [bool(v[1]) for v in verdicts],
                           hide_nsfw, hide_promptless)[1]
    check(f'switch_counts_sql counts as switch_counts, switches {hide_nsfw}/{hide_promptless}',
          {k: int(v) for k, v in sql.items()}, python)
memory.close()

# NSFW only (#363): the switch's third mode keeps the explicit images alone,
# and counts the safe ones it hides apart - as hidden_safe, not hidden_nsfw -
# with the safe images' number beside the explicit ones', for the Safe button.
# The page counts as the banner does in every mode, as for the other two.
from model_manager.gallery import NSFW_MODES, nsfw_kept_sql, nsfw_mode   # noqa: E402
MODE_KEYS = KEYS + ('hidden_safe', 'safe_count')
for mode in NSFW_MODES:
    for hide_promptless in (False, True):
        shown, py = filter_images(IMAGES, mode, hide_promptless)
        sql = db.get_image_counts(VERSION, max_nsfw_level=SFW_MAX if mode == 'safe' else None,
                                  require_prompt=hide_promptless,
                                  min_nsfw_level=SFW_MAX if mode == 'nsfw' else None)
        check(f'{mode}, hide unusable prompts {hide_promptless}: the page counts as the banner does',
              {k: py.get(k) for k in MODE_KEYS}, {k: sql.get(k) for k in MODE_KEYS})
        check(f'and shows the images it counts as shown ({mode}, {hide_promptless})', len(shown), py['filtered'])

explicit = [img['id'] for img in IMAGES if img['browsingLevel'] > SFW_MAX]
check('NSFW only shows the explicit images, every one, in order',
      [img['id'] for img in filter_images(IMAGES, 'nsfw', False)[0]], explicit)
# 12 safe images, 4 of them with an unusable prompt each level: with both
# filters on, 8 are hidden by both, 4 as safe alone.
_, only = filter_images(IMAGES, 'nsfw', True)
check('with both filters on, the safe images hidden: as safe alone, and by both',
      {k: only[k] for k in ('filtered', 'hidden_nsfw', 'hidden_safe', 'hidden_both', 'hidden_promptless',
                            'nsfw_count', 'safe_count')},
      {'filtered': 6, 'hidden_nsfw': 0, 'hidden_safe': 4, 'hidden_both': 8, 'hidden_promptless': 12,
       'nsfw_count': 6, 'safe_count': 4})
check('the hidden add up to what is not shown',
      only['hidden_safe'] + only['hidden_both'] + only['hidden_promptless'], only['hidden'])
check('each kind\'s number is the same in every mode: a press changes none',
      {mode: (filter_images(IMAGES, mode, True)[1]['safe_count'], filter_images(IMAGES, mode, True)[1]['nsfw_count'])
       for mode in NSFW_MODES}, {mode: (4, 6) for mode in NSFW_MODES})
check('a yes or no to hiding explicit images is read as Safe or All, as the switch sent before',
      (nsfw_mode(True), nsfw_mode(False), nsfw_mode('NSFW')), ('safe', 'all', 'nsfw'))
try:
    nsfw_mode('everything')
    check('a word that is no mode is refused', 'taken', 'refused')
except ValueError:
    pass

memory = sqlite3.connect(':memory:')
memory.execute('CREATE TABLE rows (safe INTEGER, readable INTEGER)')
memory.executemany('INSERT INTO rows VALUES (?, ?)', verdicts)
memory.row_factory = sqlite3.Row
for mode, hide_promptless in itertools.product(NSFW_MODES, (False, True)):
    sql = dict(memory.execute(f'SELECT {switch_counts_sql(mode, hide_promptless)} FROM rows').fetchone())
    python = switch_counts(verdicts, [bool(v[0]) for v in verdicts], [bool(v[1]) for v in verdicts],
                           mode, hide_promptless)[1]
    check(f'switch_counts_sql counts as switch_counts, {mode}/{hide_promptless}',
          {k: int(v) for k, v in sql.items()}, python)
    kept = [tuple(r) for r in memory.execute(f'SELECT safe, readable FROM rows WHERE {nsfw_kept_sql(mode)}')]
    check(f'nsfw_kept_sql keeps what switch_counts keeps, {mode}',
          kept, [v for v in verdicts if mode == 'all' or bool(v[0]) == (mode == 'safe')])
memory.close()

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
