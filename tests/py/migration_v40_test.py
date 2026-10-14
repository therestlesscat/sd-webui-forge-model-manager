"""
Migration v40 (#248): three indexes, so a delete finds the prompts it leaves
unnamed without reading every row - and nothing else.

A library of every kind, brought to v39 and given prompts no row names any
more - one alone, one heading another - is migrated. The indexes are there,
on the columns the delete looks up, and every row of every table is as it was:
the prompts left behind by earlier versions stay.
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

import generation_fixture                                # noqa: E402
from model_manager.db import migrations                  # noqa: E402
from model_manager.db.database import SCHEMA_VERSION     # noqa: E402

WORK = os.path.join(TESTS, 'work', 'migration_v40')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def everything(connection):
    """Every row of every table, as stored, in a fixed order."""
    tables = [r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    rows = {t: sorted((tuple(r) for r in connection.execute(f'SELECT * FROM "{t}"')), key=repr) for t in tables}
    # Which version the database is at is the one row a migration has to change.
    rows['schema_info'] = [r for r in rows.get('schema_info', []) if r[0] != 'version']
    return rows


def indexed(connection, table):
    """Each index on `table`, by name: its columns."""
    return {name: [c[2] for c in connection.execute(f'PRAGMA index_info("{name}")')]
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL", (table,))}


path, connection = generation_fixture.v36_database(WORK)
generation_fixture.varied(connection, WORK)
cursor = connection.cursor()
migrations.run_migrations(cursor, 36, 39, path, WORK)
connection.commit()

# What 0.58.0 to 0.58.8 left behind: a prompt nothing names, and a member and
# its head, neither named by any row.
cursor.execute("INSERT INTO prompts (text, grouped_as, length) VALUES ('left behind', 0, 11)")
cursor.execute("UPDATE prompts SET grouped_as = id WHERE text = 'left behind'")
cursor.execute("INSERT INTO prompts (text, grouped_as, length) VALUES ('a head', 0, 6)")
head = cursor.lastrowid
cursor.execute("UPDATE prompts SET grouped_as = id WHERE id = ?", (head,))
cursor.execute("INSERT INTO prompts (text, grouped_as, length) VALUES ('a  head', ?, 7)", (head,))
connection.commit()
before = everything(connection)
check('the library has generations, images and prompts to keep',
      all(len(before[t]) > 3 for t in ('generations', 'generation_images', 'prompts')))

migrations.run_migrations(cursor, 39, 40, path, WORK)
connection.commit()
check('v40 is the schema this copy writes', SCHEMA_VERSION, 40)
check('an index on each image\'s negative prompt',
      indexed(connection, 'generation_images').get('idx_images_negative'), ['negative_id'])
check('an index on each generation\'s prompt and negative prompt',
      {k: v for k, v in indexed(connection, 'generations').items() if k in ('idx_generations_prompt',
                                                                            'idx_generations_negative')},
      {'idx_generations_prompt': ['prompt_id'], 'idx_generations_negative': ['negative_id']})
check('the indexes v37 made for the other two questions are still there',
      (indexed(connection, 'generation_images').get('idx_images_prompt'),
       indexed(connection, 'prompts').get('idx_prompts_grouped')), (['prompt_id'], ['grouped_as']))
after = everything(connection)
check('every row of every table is as it was, the prompts left behind included',
      [t for t in sorted(set(before) | set(after)) if before.get(t) != after.get(t)], [])

migrations.run_migrations(cursor, 39, 40, path, WORK)
connection.commit()
check('run twice, it changes nothing', everything(connection), after)

connection.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
