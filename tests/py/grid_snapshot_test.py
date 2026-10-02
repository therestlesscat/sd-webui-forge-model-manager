"""
The grid's count and its page read one snapshot (db/query.py, #72).

The grid asks how many cards match - and how many in each tab - then reads
the page: two statements, and each used to read the database as it was at
that moment. A sync, a scan, a download or the other WebUI writing in between
left the total and the page disagreeing - a card missing or shown twice
across pages, "has more" off by one. What is checked: a new file written
through another connection between the two reads, as a sync would, is in
neither or both; and with nothing written, the answer is as it was.
"""
import contextlib
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

import fixtures                                          # noqa: E402
from model_manager.db import GridQuery                   # noqa: E402
from model_manager.db import query as query_module       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'grid_snapshot')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
written = []


class Hooked(object):
    """A cursor that, before the page is read, has another connection write."""
    def __init__(self, cursor, write):
        self._cursor, self._write = cursor, write

    def execute(self, sql, *args):
        if self._write and 'LIMIT ? OFFSET ?' in sql:
            self._write()
        return self._cursor.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def grid(write=None, **options):
    @contextlib.contextmanager
    def cursors():
        with db._cursor() as cursor:
            yield Hooked(cursor, write)
    counts = {}
    rows, total = query_module.query_models_grouped(cursors, GridQuery(limit=100000, **options), counts)
    return rows, total, counts


def a_sync_adds_a_file():
    path = os.path.join(WORK, 'arrived', 'new_%d.safetensors' % len(written))
    other = sqlite3.connect(db.db_path, timeout=5)
    other.execute("INSERT INTO model_versions (file_path, file_name, has_civitai_data) VALUES (?, ?, 0)",
                  (path, os.path.basename(path)))
    other.commit()
    other.close()
    written.append(path)


rows, total, counts = grid()
check('nothing written between: every card the count counts', (len(rows), total), (total, len(rows)))
check('and the tabs add up to it', counts['pinned'] + counts['others'], total)

rows, total, counts = grid(write=a_sync_adds_a_file)
check('a file written between the count and the page is in neither or both',
      len(rows), total)
check('the tabs too', counts['pinned'] + counts['others'], total)

rows, total, _ = grid()
check('and the next ask has it', ([r for r in rows if r['file_path'] == written[0]] != [], len(rows)),
      (True, total))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
