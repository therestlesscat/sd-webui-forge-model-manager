"""
Every column of civitai_models and model_versions is accounted for (#69).

The upserts are generated from a list of columns per table, each with how an
update treats it (models_ops.MODEL_COLUMNS, VERSION_COLUMNS). A column the
upsert does not write is named, with what does (MODEL_COLUMNS_ELSEWHERE,
VERSION_COLUMNS_ELSEWHERE). What is checked, on a database migrated to the
newest schema: every column is in exactly one of the two, so a migration's
new column cannot be left out of both - written on insert and never again,
or never written at all, and nobody deciding which.
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

import fixtures                                          # noqa: E402
from model_manager.db import models_ops                  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'upsert_columns')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
tables = {
    'civitai_models': (models_ops.MODEL_COLUMNS, models_ops.MODEL_COLUMNS_ELSEWHERE),
    'model_versions': (models_ops.VERSION_COLUMNS, models_ops.VERSION_COLUMNS_ELSEWHERE),
}
with db._cursor() as cursor:
    for table, (written, elsewhere) in tables.items():
        cursor.execute('PRAGMA table_info(%s)' % table)
        columns = {row[1] for row in cursor.fetchall()}
        upserted = [column.name for column in written]
        check('%s: every column is written by the upsert or named as written elsewhere' % table,
              sorted(columns - set(upserted) - set(elsewhere)), [])
        check('%s: and nothing named that the table does not have' % table,
              sorted((set(upserted) | set(elsewhere)) - columns), [])
        check('%s: no column in both' % table, sorted(set(upserted) & set(elsewhere)), [])
        check('%s: none listed twice' % table, len(upserted), len(set(upserted)))
        check('%s: one key, the row is found by' % table,
              [column.name for column in written if column.update is models_ops.KEY],
              [{'civitai_models': 'id', 'model_versions': 'file_path'}[table]])
        check('%s: each written elsewhere says by what' % table,
              [name for name, what in elsewhere.items() if not what], [])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
