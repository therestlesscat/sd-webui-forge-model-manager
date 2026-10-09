"""
How explicit a model reads in the grid (model_manager/nsfw.py): the rule
written to be read, model_level(), and its SQL copy, model_level_sql(), which
the grid's NSFW filter runs. Nothing held the two together (#146): changed
alone, the SQL would filter by a rule the code no longer says. Every
combination of the three ratings is asked of both, and they must agree.
"""
import itertools
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from model_manager.nsfw import (                         # noqa: E402
    BLOCKED, PG, PG13, R, UNKNOWN, X, XXX, model_level, model_level_sql,
)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# Empty, nothing, each level alone, Unknown, and two that are several levels
# together - a model's own level often is, one bit per level.
VALUES = [None, 0, PG, PG13, R, X, XXX, BLOCKED, UNKNOWN, PG | PG13, PG | PG13 | R | X | XXX]

db = sqlite3.connect(':memory:')
db.execute('CREATE TABLE ratings (m INTEGER, v INTEGER, i INTEGER)')
cases = list(itertools.product(VALUES, repeat=3))
db.executemany('INSERT INTO ratings VALUES (?, ?, ?)', cases)
# The worst image comes from a subquery, as in the grid's own query.
sql = model_level_sql('m', 'v', 'SELECT i')
by_sql = {(m, v, i): level for m, v, i, level in db.execute(f'SELECT m, v, i, {sql} FROM ratings')}

check('every combination of the three ratings is asked', (len(cases), len(by_sql)), (1331, 1331))
differ = [(case, model_level(*case), by_sql[case]) for case in cases if model_level(*case) != by_sql[case]]
check('the SQL gives the level the Python does, in every one (case, Python, SQL)', differ[:5], [])

# A few spelled out, so the rule reads here and not only that the copies agree.
for ratings, want in (((None, None, None), UNKNOWN),
                      ((UNKNOWN, None, 0), UNKNOWN),
                      ((PG, UNKNOWN, None), PG),
                      ((PG, R, X), X),
                      ((UNKNOWN, UNKNOWN, PG13), PG13)):
    check('model, version, worst image %r: %r, in both' % (ratings, want),
          (model_level(*ratings), by_sql[ratings]), (want, want))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
