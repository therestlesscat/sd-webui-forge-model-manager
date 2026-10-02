"""
What a prompt is worth (model_manager/prompt_rules.py, #61): worth reading,
and enough to make the image again - and the SQL forms the database filters
and counts with, which must answer as the Python does. They did not: Python
trimmed any whitespace, SQL spaces only.
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from model_manager.prompt_rules import (                 # noqa: E402
    MIN_PROMPT_LENGTH, image_readable, readable, readable_sql, trimmed_sql, unreadable_sql, usable,
)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ------------------------------------------------------- worth reading
check('four characters is a prompt', readable('a cat'), True)
check('three is not', readable('cat'), False)
check('nor nothing', [readable(''), readable(None)], [False, False])
check('trimmed of spaces, tabs and line breaks first',
      [readable(' \t\tab\n'), readable('\r\n four \t')], [False, True])
check('an image\'s, from its meta', [image_readable({'meta': {'prompt': 'a cat'}}),
                                      image_readable({'meta': None}), image_readable({})],
      [True, False, False])
check('the floor is four', MIN_PROMPT_LENGTH, 4)

# ------------------------------------------------------- the SQL answers alike
SAMPLES = ['a cat', 'cat', '', None, '    ', ' \t\tab\n', '\r\n four \t', '\n\n\n\n\n', 'ab cd']
con = sqlite3.connect(':memory:')
for prompt in SAMPLES:
    row = con.execute('SELECT %s, %s, LENGTH(%s)' % (readable_sql('?'), unreadable_sql('?'), trimmed_sql('?')),
                      (prompt, prompt, prompt)).fetchone()
    check('SQL reads %r as Python does' % (prompt,), (bool(row[0]), bool(row[1]), row[2]),
          (readable(prompt), not readable(prompt), len((prompt or '').strip(' \t\r\n'))))

# ------------------------------------------------------- what counts as usable
# A prompt on its own is not enough: "Send to txt2img" needs the settings too.
FULL = {'prompt': 'a cat', 'steps': 20, 'sampler': 'Euler a', 'cfgScale': 7}
check('a prompt with its settings is usable', usable({'meta': FULL}), True)
check('the capitalised spellings count too',
      usable({'meta': {'prompt': 'a cat', 'steps': 20,
                       'Sampler': 'Euler a', 'CFG scale': 7}}), True)
check('but a prompt with no steps is not',
      usable({'meta': dict(FULL, steps=0)}), False)
check('nor one with no sampler',
      usable({'meta': dict(FULL, sampler=None)}), False)
check('nor one with no guidance scale',
      usable({'meta': dict(FULL, cfgScale=None)}), False)
check('no meta at all is not', usable({'meta': None}), False)
check('nor an empty meta', usable({'meta': {}}), False)
check('nor a blank prompt', usable({'meta': {'prompt': '   '}}), False)
check('nor a missing key', usable({}), False)
# It takes an image out of a list Civitai returned, so None is not a case it
# has to handle - and it does not: passing one raises.
try:
    usable(None)
    check('None is handled', False)
except AttributeError:
    pass

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
