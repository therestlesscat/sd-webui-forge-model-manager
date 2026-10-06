"""
The generation queue's storage (#150): db/tasks_ops.py through the
ModelsDatabase facade, on the fixture library - and migration v34, on a
database at v33.

A task is queued pending, run once, and ends completed, stopped or failed;
a restart stops what it left running. Lists are one install's, Active in
run order and History newest first, without hidden tasks. A delete takes
the generations a task made only when asked to, in one transaction, and a
generation deleted elsewhere leaves its task.
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

import webui_stub                                        # noqa: E402

webui_stub.install()

import fixtures                                          # noqa: E402
from model_manager.db.database import ModelsDatabase, SCHEMA_VERSION   # noqa: E402
from model_manager.db.migrations import _migrate_to_v34  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'tasks')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def raises(call, kind=ValueError):
    try:
        call()
    except kind:
        return True
    return False


db, facts = fixtures.build(WORK)

# ------------------------------------------------------------------ v34
def table_names(connection):
    return {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


with sqlite3.connect(facts['db_path']) as c:
    check('a database made now has both tables',
          {'tasks', 'task_generations'} <= table_names(c), True)

OLD = os.path.join(WORK, 'v33.db')
with sqlite3.connect(facts['db_path']) as c:
    c.execute('VACUUM INTO ?', (OLD,))
with sqlite3.connect(OLD) as c:
    c.execute('DROP TABLE tasks')
    c.execute('DROP TABLE task_generations')
    c.execute("UPDATE schema_info SET value = '33' WHERE key = 'version'")
    kept = sorted(table_names(c) - {'sqlite_sequence'})
    before = {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in kept}
ModelsDatabase(extension_dir=ROOT, custom_db_path=OLD).close()
with sqlite3.connect(OLD) as c:
    check('v34 adds both tables to a v33 database',
          {'tasks', 'task_generations'} <= table_names(c), True)
    check('and brings it to the schema this code expects',
          c.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()[0],
          str(SCHEMA_VERSION))
    check('and leaves every other table as it was',
          {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in kept}, before)
    check('v34 runs twice without harm', raises(lambda: _migrate_to_v34(c.cursor()), Exception), False)

# ------------------------------------------------------------- queueing
HERE_INSTALL, OTHER_INSTALL = 'install-here', 'install-other'


def queue(n, install=HERE_INSTALL, **more):
    task = {'install': install, 'forge': 'neo', 'mode': 'txt2img',
            'inputs': {'prompt': f'task {n}', 'steps': n},
            'checkpoint': 'model.safetensors', 'modules': ['vae.safetensors']}
    task.update(more)
    return db.add_task(task)


a, b, c = queue(1), queue(2), queue(3)
x = queue(9, install=OTHER_INSTALL)
got = db.get_task(a)
check('a task is queued pending', got['status'], 'pending')
check('its inputs come back as written', got['inputs'], {'prompt': 'task 1', 'steps': 1})
check('its modules too', got['modules'], ['vae.safetensors'])
check('it has no generations yet, and no copy', (got['generations'], got['retried_as']), ([], None))
check('it is dated when queued', bool(got['created_at']), True)
check('a task that does not exist is None', db.get_task(10 ** 9), None)

# --------------------------------------------------------------- running
check("the next task is this install's oldest pending", db.next_pending_task(HERE_INSTALL)['id'], a)
check("another install's queue is its own", db.next_pending_task(OTHER_INSTALL)['id'], x)
check('a pending task starts', db.start_task(a), True)
check('only once', db.start_task(a), False)
check('it is dated when started', bool(db.get_task(a)['started_at']), True)
check('the next task is then the one after it', db.next_pending_task(HERE_INSTALL)['id'], b)

db.finish_task(a, 'completed', first_seed=111)
check('a finished task keeps its first seed', db.get_task(a)['first_seed'], 111)
check('and is dated when it ended', bool(db.get_task(a)['finished_at']), True)
db.finish_task(a, 'completed', first_seed=222)
check('the first seed is never replaced', db.get_task(a)['first_seed'], 111)
check('a task cannot finish as pending', raises(lambda: db.finish_task(b, 'pending')), True)

db.start_task(b)
db.finish_task(b, 'failed', error='boom')
failed = db.get_task(b)
check("a failed task keeps Forge's error", (failed['status'], failed['error']), ('failed', 'boom'))

# -------------------------------------------------------------- restart
db.start_task(c)
db.start_task(x)
check("at startup, this install's running task is stopped", db.stop_running_tasks(HERE_INSTALL), 1)
check('it is then stopped', db.get_task(c)['status'], 'stopped')
check("another install's running task is left alone", db.get_task(x)['status'], 'running')

# ----------------------------------------------------------------- lists
d, e = queue(4), queue(5)
active, total = db.list_tasks(HERE_INSTALL, 'active')
check('Active is in run order', [t['id'] for t in active], [d, e])
check('with its size', total, 2)
with db._cursor() as cursor:
    cursor.execute("UPDATE tasks SET finished_at = '2026-01-01T00:00:00' WHERE id IN (?, ?, ?)", (a, b, c))
history, total = db.list_tasks(HERE_INSTALL, 'history')
check('History is newest first, by id when two ended together', [t['id'] for t in history], [c, b, a])
page, total = db.list_tasks(HERE_INSTALL, 'history', offset=1, limit=1)
check('a page of History, with the whole list size', ([t['id'] for t in page], total), ([b], 3))
check('there is no third list', raises(lambda: db.list_tasks(HERE_INSTALL, 'hidden')), True)
listed = {t['id'] for which in ('active', 'history') for t in db.list_tasks(HERE_INSTALL, which)[0]}
check("another install's tasks are in neither list", x in listed, False)
check('the counts, by status', db.count_tasks(HERE_INSTALL),
      {'pending': 2, 'running': 0, 'completed': 1, 'stopped': 1, 'failed': 1, 'cancelled': 0})

# ------------------------------------------------- generations and copies
OUT = os.path.join(WORK, 'outputs')


def generation(name):
    path = os.path.join(OUT, f'{name}.png')
    return db.record_generation({'created_at': '2026-01-01T00:00:00', 'mode': 'txt2img', 'image_count': 1},
                                [{'position': 0, 'path': path}], [[facts['linked_paths'][0]]]), path


g1, p1 = generation('one')
g2, p2 = generation('two')
db.link_task_generation(a, g1)
db.link_task_generation(a, g2)
db.link_task_generation(a, g1)
check('a task names the generations its run made, once each', db.get_task(a)['generations'], [g1, g2])
copy = queue(1, retry_of=a)
check('a retried task names its copy', db.get_task(a)['retried_as'], copy)
check('and the copy names its original', db.get_task(copy)['retry_of'], a)
listed = {t['id']: t for t in db.list_tasks(HERE_INSTALL, 'history')[0]}
check('the lists carry both', (listed[a]['generations'], listed[a]['retried_as']), ([g1, g2], copy))

# ------------------------------------------------------- Clear history
db.finish_task(x, 'completed')
check('Clear history hides every ended task', db.hide_task_history(HERE_INSTALL), 3)
check('History is then empty', db.list_tasks(HERE_INSTALL, 'history'), ([], 0))
check('Active is untouched', [t['id'] for t in db.list_tasks(HERE_INSTALL, 'active')[0]], [d, e, copy])
check('nothing is deleted: the task is only hidden', db.get_task(a)['hidden'], 1)
check('its generations stay', db.get_generation(g1) is not None, True)
check('the counts leave hidden tasks out', db.count_tasks(HERE_INSTALL)['completed'], 0)
check("another install's History is its own", db.list_tasks(OTHER_INSTALL, 'history')[1], 1)


def links(task_id):
    with db._cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM task_generations WHERE task_id = ?', (task_id,))
        return cursor.fetchone()[0]


# ---------------------------------------------------------------- delete
db.start_task(d)
check('a running task is not deleted', db.delete_task(d, with_data=True), (None, []))
check('it is still there', db.get_task(d)['status'], 'running')

f = queue(6)
g3, p3 = generation('three')
db.link_task_generation(f, g3)
gone, paths = db.delete_task(f, with_data=False)
check('without its data, the task goes', (gone['id'], db.get_task(f)), (f, None))
check('and its links', links(f), 0)
check('its generation stays', db.get_generation(g3) is not None, True)
check('and no image path comes back', paths, [])

gone, paths = db.delete_task(a, with_data=True)
check('with its data, the task goes', (gone['id'], db.get_task(a)), (a, None))
check('and its links', links(a), 0)
check('its generations go too', (db.get_generation(g1), db.get_generation(g2)), (None, None))
check("their images' paths come back, for the files", sorted(paths), sorted([p1, p2]))
check('the task as it was comes back, for its own files', gone['inputs'], {'prompt': 'task 1', 'steps': 1})
check('a task that does not exist deletes nothing', db.delete_task(10 ** 9, with_data=True), (None, []))

# ------------------------------------- deleted in the Generations tab
h = queue(7)
g4, _ = generation('four')
db.link_task_generation(h, g4)
db.delete_generation(g4)
check('a generation deleted in the Generations tab leaves its task', db.get_task(h)['generations'], [])

k = queue(8)
g5, _ = generation('five')
db.link_task_generation(k, g5)
image_id = db.get_generation(g5)['images'][0]['id']
db.delete_generation_image(image_id)
check('so does a generation whose last image is deleted', db.get_task(k)['generations'], [])

# ----------------------------------------------------------------- Cancel
m, n, y = queue(9), queue(10), queue(11, OTHER_INSTALL)
check('a pending task is cancelled', db.cancel_task(HERE_INSTALL, m), True)
cancelled = db.get_task(m)
check('it ends, never having started', (cancelled['status'], bool(cancelled['finished_at']), cancelled['started_at']),
      ('cancelled', True, None))
check('it is in History, counted', (m in [t['id'] for t in db.list_tasks(HERE_INSTALL, 'history')[0]],
                                    db.count_tasks(HERE_INSTALL)['cancelled']), (True, 1))
check('it leaves Active', m in [t['id'] for t in db.list_tasks(HERE_INSTALL, 'active')[0]], False)
check('and cannot start it', db.start_task(m), False)
db.start_task(n)
check('a task the queue has started is not cancelled', (db.cancel_task(HERE_INSTALL, n), db.get_task(n)['status']),
      (False, 'running'))
check("nor another install's", (db.cancel_task(HERE_INSTALL, y), db.get_task(y)['status']), (False, 'pending'))

# ---------------------------------------------------------------- Run next
q, r, s = queue(12), queue(13), queue(14)
# d and n are running.
order = [t['id'] for t in db.list_tasks(HERE_INSTALL, 'active', first=[s, r])[0]]
check('Active: the running tasks, then Run next\'s in the order asked, then the rest as queued',
      (order[:4], order.index(q) > 3), ([d, n, s, r], True))
check('a page of it keeps that order',
      [t['id'] for t in db.list_tasks(HERE_INSTALL, 'active', 2, 2, first=[s, r])[0]], [s, r])
check('History has no such order', db.list_tasks(HERE_INSTALL, 'history', first=[m])[0][0]['id'],
      db.list_tasks(HERE_INSTALL, 'history')[0][0]['id'])

db.close()

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
