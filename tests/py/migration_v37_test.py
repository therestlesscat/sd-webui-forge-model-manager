"""
Migration v37 (#231): the generation tables redesigned, losing nothing.

A v36 library of every kind (tests/generation_fixture.py) is migrated, and
every value of every row is read back from the new tables - the same value
and the same type. The files each image used are the same set as before; the
queue's links hold; a deleted id is never given again; a file moved before the
migration is named where it is now; a failure leaves v36 as it was. And the
checks are shown to fail on a migration that drops something.
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

import generation_fixture                                # noqa: E402
import v36_generations as v36                            # noqa: E402
from model_manager.db import migrations                  # noqa: E402
from model_manager.db.database import ModelsDatabase     # noqa: E402
from model_manager.db.generations_ops import tidy        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'migration_v37')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


_GENERATION = migrations._V37_GENERATION + migrations._V37_GENERATION_DETAILS + ('prompt', 'negative_prompt')
_IMAGE = migrations._V37_IMAGE + migrations._V37_IMAGE_DETAILS + ('prompt', 'negative_prompt')


def library(name, moved=False):
    """A v36 library of every kind, and what it held: every row, as stored."""
    path, connection = generation_fixture.v36_database(os.path.join(WORK, name))
    facts = generation_fixture.varied(connection, WORK)
    # A generation recorded with no images' worth of prompt, and deleted ids
    # at the top: the sequence is above the highest id left.
    connection.execute("DELETE FROM generations WHERE id = (SELECT MAX(id) FROM generations)")
    connection.execute("DELETE FROM generation_images WHERE generation_id NOT IN (SELECT id FROM generations)")
    connection.execute("DELETE FROM generation_files WHERE generation_id NOT IN (SELECT id FROM generations)")
    if moved:
        # The sync moved checkpoint b into another folder: generation_files
        # followed it, the recorded paths did not (#234).
        to = os.path.join(WORK, 'lib', 'Moved', 'b.safetensors')
        connection.execute("UPDATE generation_files SET file_path = ? WHERE file_path = ?",
                           (to, facts['paths']['b']))
        facts['moved_to'] = to
    connection.commit()
    before = {
        'generations': {r['id']: dict(r) for r in connection.execute('SELECT * FROM generations')},
        'images': {r['id']: dict(r) for r in connection.execute('SELECT * FROM generation_images')},
        'files': sorted(tuple(r) for r in connection.execute(
            'SELECT file_path, image_id, generation_id FROM generation_files')),
        'tasks': sorted(tuple(r) for r in connection.execute('SELECT task_id, generation_id FROM task_generations')),
        'sequence': dict(connection.execute(
            "SELECT name, seq FROM sqlite_sequence WHERE name IN ('generations', 'generation_images')").fetchall()),
        'whole': {g: v36.V36(connection).ops.get_generation(g)
                  for g in [r[0] for r in connection.execute('SELECT id FROM generations')]},
    }
    connection.close()
    return path, facts, before


def rebuilt(connection):
    """Every generation and image as v36 held it, rebuilt from v37's tables."""
    connection.row_factory = sqlite3.Row
    generations = {r['id']: dict(r) for r in connection.execute(f"""
        SELECT {', '.join('g.' + c for c in migrations._V37_GENERATION)},
               {', '.join('d.' + c for c in migrations._V37_GENERATION_DETAILS)},
               p.text AS prompt, q.text AS negative_prompt
        FROM generations g JOIN generation_details d ON d.generation_id = g.id
        LEFT JOIN prompts p ON p.id = g.prompt_id LEFT JOIN prompts q ON q.id = g.negative_id""")}
    images = {r['id']: dict(r) for r in connection.execute(f"""
        SELECT {', '.join('gi.' + c for c in migrations._V37_IMAGE)},
               {', '.join('d.' + c for c in migrations._V37_IMAGE_DETAILS)},
               p.text AS prompt, q.text AS negative_prompt
        FROM generation_images gi JOIN image_details d ON d.image_id = gi.id
        LEFT JOIN prompts p ON p.id = gi.prompt_id LEFT JOIN prompts q ON q.id = gi.negative_id""")}
    return generations, images


def differences(old, new, columns):
    """Every (id, column) whose value or type differs."""
    found = []
    for key in sorted(set(old) | set(new)):
        if key not in old or key not in new:
            found.append((key, 'row'))
            continue
        for column in columns:
            a, b = old[key].get(column), new[key].get(column)
            if a != b or type(a) is not type(b):
                found.append((key, column))
    return found


# ------------------------------------------------------------ the migration
path, facts, before = library('every_kind')
db = ModelsDatabase(extension_dir=ROOT, custom_db_path=path)
raw = sqlite3.connect(path)
check('the database is at v37', raw.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone(),
      ('37',))
check('the old tables are gone, and nothing temporary is left',
      sorted(r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND "
                                       "(name LIKE 'generation%' OR name LIKE '%v37' OR name = 'prompts' "
                                       "OR name = 'image_details')")),
      ['generation_details', 'generation_images', 'generation_resources', 'generations', 'image_details',
       'prompts'])
check('backed up first, beside it', any(f.startswith('models.db.backup_') for f in os.listdir(os.path.dirname(path))))

# 8: every column of every row, the same value and type.
generations, images = rebuilt(raw)
check('every generation keeps every column, value and type',
      differences(before['generations'], generations, _GENERATION), [])
check('every image keeps every column, value and type', differences(before['images'], images, _IMAGE), [])
loras = [json.loads(r['loras']) for r in before['images'].values()]
check('the fixture holds what could be lost: a LoRA twice, module order, hires modules NULL, [] and listed, '
      'prompts NULL and empty, weight in place of te_multiplier',
      (any(len({l['name'] for l in ls}) < len(ls) for ls in loras),
       any(json.loads(g['modules'] or '[]') == [facts['paths']['te'], facts['paths']['vae']]
           for g in before['generations'].values()),
       {g['hr_modules'] for g in before['generations'].values()} >= {None, '[]', json.dumps([facts['paths']['vae']])},
       {g['prompt'] for g in before['generations'].values()} >= {None, ''},
       any('weight' in l and 'te_multiplier' not in l for ls in loras for l in ls)),
      (True, True, True, True, True))

# 9: the files each image used, and the queue's links.
check('the files each image used are the same set as before',
      sorted(set(tuple(r) for r in raw.execute('SELECT file_path, image_id, generation_id FROM generation_resources '
                                               'WHERE file_path IS NOT NULL'))), before['files'])
check('every queue link still finds its generation',
      [tuple(r) for r in raw.execute('SELECT tg.task_id, tg.generation_id FROM task_generations tg '
                                     'JOIN generations g ON g.id = tg.generation_id ORDER BY 1, 2')],
      before['tasks'])
roles = dict(raw.execute("SELECT role, COUNT(*) FROM generation_resources GROUP BY role").fetchall())
check('each file has its role: the library\'s file type names a VAE and a text encoder, '
      'a module the library lacks is a module',
      {r for r in roles if roles[r]} >= {'checkpoint', 'lora', 'vae', 'text_encoder', 'module', 'hr_checkpoint',
                                         'hr_module', 'refiner'}, True)

# 7: each generation reads back whole, as before.
whole = {g: db.get_generation(g) for g in before['whole']}
check('each generation reads back whole, as v36 read it', {g: w == before['whole'][g] for g, w in whole.items()},
      {g: True for g in before['whole']})

# 11: a deleted id is never given again.
generation_id = db.record_generation({'created_at': '2026-02-01T00:00:00', 'mode': 'txt2img', 'image_count': 1},
                                     [{'position': 0, 'path': os.path.join(WORK, 'new.png')}], [[]])
check('a new generation\'s id is above every id ever given', generation_id > before['sequence']['generations'],
      True)
check('as is a new image\'s', db.get_generation(generation_id)['images'][0]['id']
      > before['sequence']['generation_images'], True)
raw.close()

# ------------------------------------------------------------ 12: a file moved before the migration
path, facts, before = library('moved', moved=True)
db = ModelsDatabase(extension_dir=ROOT, custom_db_path=path)
moved = [g for g, row in before['generations'].items() if row['checkpoint_path'] == facts['paths']['b']]
check('a file moved before the migration: its generations name it where it is now',
      {db.get_generation(g)['checkpoint_path'] for g in moved}, {facts['moved_to']})
raw = sqlite3.connect(path)
check('as recorded, they still say where it was', {r[0] for r in raw.execute(
    f"SELECT checkpoint_path FROM generation_details WHERE generation_id IN ({', '.join(map(str, moved))})")},
      {facts['paths']['b']})
raw.close()

# ------------------------------------------------------------ 10: a failure leaves v36 as it was
path, facts, before = library('fails')


def broken(cursor):
    raise RuntimeError('forced at the drop')


real_check = migrations._v37_check
migrations._v37_check = broken
try:
    ModelsDatabase(extension_dir=ROOT, custom_db_path=path)
    raised = False
except RuntimeError:
    raised = True
finally:
    migrations._v37_check = real_check
raw = sqlite3.connect(path)
raw.row_factory = sqlite3.Row
check('a failure raises', raised)
check('and the database is still at v36', raw.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()[0],
      '36')
check('with the v36 tables, and nothing of v37',
      sorted(r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND "
                                       "(name LIKE 'generation%' OR name LIKE '%v37' OR name = 'prompts')")),
      ['generation_files', 'generation_images', 'generations'])
check('every row as it was',
      ({r['id']: dict(r) for r in raw.execute('SELECT * FROM generations')} == before['generations'],
       {r['id']: dict(r) for r in raw.execute('SELECT * FROM generation_images')} == before['images']),
      (True, True))
raw.close()

# ------------------------------------------------------------ 13: the frozen tidying rule
awkward = ['a cat', 'a  cat', ' a cat ', 'a\tcat', 'a\ncat\n', 'a cat', 'a　cat', '', '   ', None,
           'mixed \t \n spacing ', 'unicode   em space']
check('the migration tidies a prompt as the recorder and the v36 groupings do',
      [migrations._v37_tidy(t) for t in awkward], [tidy(t) for t in awkward])
check('as v36 grouped prompts', [migrations._v37_tidy(t) for t in awkward], [v36._one_line(t) for t in awkward])

# ------------------------------------------------------------ the checks can fail
# A migration that drops a LoRA's `pass`: its own check stops it, and with
# that check off, the comparison above finds the loss.
real_row = migrations._v37_row


def drops_pass(cursor, row):
    row = real_row(cursor, row)
    if row.get('loras'):
        row['loras'] = json.dumps([{k: v for k, v in l.items() if k != 'pass'} for l in json.loads(row['loras'])])
    return row


path, facts, before = library('drops')
migrations._v37_row = drops_pass
try:
    try:
        ModelsDatabase(extension_dir=ROOT, custom_db_path=path)
        stopped = False
    except RuntimeError as e:
        stopped = 'would lose data' in str(e)
    check('a migration that drops a LoRA\'s pass is stopped by its own check', stopped)
    migrations._v37_check = lambda cursor: None
    ModelsDatabase(extension_dir=ROOT, custom_db_path=path)
finally:
    migrations._v37_row = real_row
    migrations._v37_check = real_check
raw = sqlite3.connect(path)
_, images = rebuilt(raw)
raw.close()
check('and, past that check, the comparison finds what it lost',
      bool([d for d in differences(before['images'], images, _IMAGE) if d[1] == 'loras']), True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
