"""
Migration v14 judges images by the rule it was written with (#60).

It imported the live nsfw.image_level, which has since learnt to read the
person's prompt words, detection setting and trained model: what v14 wrote
depended on today's rule and settings, during startup, and renaming that
function would have stopped every pre-v14 database from opening. It carries
a frozen copy now - Civitai's fields only, as at 9120570 - and the prompt
words are prompt_levels' to apply, after startup.
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402
webui_stub.install()

import model_manager.nsfw as nsfw                        # noqa: E402
from model_manager.db import migrations                  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# A word the bundled list calls explicit, taken from it rather than written here.
explicit = sorted(nsfw.prompt_words())[0]

IMAGES = {
    1: {'browsingLevel': 8},
    2: {'nsfwLevel': 16},
    3: {'nsfwLevel': 'Soft'},
    4: {'nsfwLevel': 'Mature'},
    5: {'nsfwLevel': 'X'},
    6: {'nsfwLevel': 'None'},
    7: {'nsfw': True},
    8: {'nsfw': False},
    9: {},
    10: {'browsingLevel': 1, 'meta': {'prompt': 'a %s picture' % explicit}},
}
WANT = {1: 8, 2: 16, 3: 2, 4: 4, 5: 16, 6: 1, 7: 4, 8: 1, 9: 64, 10: 1}


def migrated():
    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE images (id INTEGER, version_id INTEGER, effective_nsfw_level INTEGER, data TEXT)')
    con.executemany('INSERT INTO images VALUES (?, 1, 0, ?)',
                    [(i, json.dumps(payload)) for i, payload in IMAGES.items()])
    migrations._migrate_to_v14(con.cursor())
    return dict(con.execute('SELECT id, effective_nsfw_level FROM images'))


# Today's rules, made to fail: v14 must not reach for them.
def refuse(*a, **k):
    raise RuntimeError('migration v14 reached for the live NSFW rule')

real = nsfw.image_level, nsfw.rated_level
nsfw.image_level = nsfw.rated_level = refuse
try:
    got = migrated()
    check('v14 runs without the live rule', True)
except RuntimeError as e:
    got = {}
    check('v14 runs without the live rule', str(e), None)
finally:
    nsfw.image_level, nsfw.rated_level = real

check('each image judged by Civitai\'s fields, as v14 was written',
      {i: got.get(i) for i in WANT}, WANT)
check('a PG image with an explicit prompt stays PG: prompts are prompt_levels\' to apply',
      got.get(10), 1)
check('and the frozen rule is still today\'s rating of Civitai\'s fields',
      {i: nsfw.rated_level(p) for i, p in IMAGES.items()}, WANT)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
