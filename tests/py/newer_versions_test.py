"""
A model with a newer version than any the library holds (#218).

One rule, in two forms: Python for the cards' badge, SQL for the Model
Manager's Newer Version filter. Newer means listed before every held version,
in Civitai's order - a place in the list, so a list with an `index` and one
merged from sidecars without read alike. Each case is put to both forms, and
both must say the same.
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

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


try:
    from model_manager.newer_versions import NEWER_SQL, newer_versions   # noqa: E402
except ImportError as e:
    print('FAIL the rule is importable\n   %s' % e)
    sys.exit(1)


def listed(*ids, index=True):
    """A version list in Civitai's order, as stored and as a search answers it."""
    return [dict({'id': i, 'name': 'v%d' % i, 'baseModel': 'SDXL 1.0'}, **({'index': n} if index else {}))
            for n, i in enumerate(ids)]


CASES = [
    # (what, the list, held version ids, the ids newer)
    ('one held, two listed before it', listed(30, 20, 10), {10}, [30, 20]),
    ('the held one listed first', listed(30, 20, 10), {30}, []),
    ('several held: before the first of them', listed(40, 30, 20, 10), {30, 10}, [40]),
    ('nothing held', listed(30, 20), set(), []),
    ('the held one gone from the list', listed(30, 20), {99}, []),
    ('a list with no index, newest first', listed(30, 20, 10, index=False), {20}, [30]),
    ('an empty list', [], {10}, []),
]

for what, versions, held, want in CASES:
    check('in Python: %s' % what, [v['id'] for v in newer_versions(versions, held)], want)

# The SQL form, over a library of these cases: model n holds case n, its
# version ids moved by n * 100 so no case's files are another's. The grid asks
# it of the version a card shows, which names its model.
db = sqlite3.connect(':memory:')
db.executescript("""
    CREATE TABLE models (id INTEGER PRIMARY KEY, versions TEXT);
    CREATE TABLE versions (id INTEGER PRIMARY KEY, model_id INTEGER);
    CREATE TABLE files (file_path TEXT PRIMARY KEY, version_id INTEGER);
""")
for n, (what, versions, held, want) in enumerate(CASES, start=1):
    moved = [dict(v, id=v['id'] + n * 100) for v in versions]
    db.execute('INSERT INTO models VALUES (?, ?)', (n, json.dumps(moved) if moved else None))
    db.execute('INSERT INTO versions VALUES (?, ?)', (n * 100000, n))
    for vid in held:
        db.execute('INSERT INTO files VALUES (?, ?)', ('m%d/%d' % (n, vid), vid + n * 100))
sql = 'SELECT 1 WHERE ' + NEWER_SQL.format(version_id='?')
for n, (what, versions, held, want) in enumerate(CASES, start=1):
    check('in SQL, the same: %s' % what, db.execute(sql, (n * 100000,)).fetchone() is not None, bool(want))

check('a file Civitai does not know, no version: no badge, in SQL',
      db.execute(sql, (None,)).fetchone() is None)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
