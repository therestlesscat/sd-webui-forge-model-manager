"""
Trained or merged: a value Civitai will filter on but never returns.

get_checkpoint_types() infers it from which of two filtered queries an id
comes back in, so most of this is about the inference failing safely - an
answer about models nobody asked for, or one that claims a model is both.
"""

import os
import sys

# The extension and the test helpers, found from this file rather than from a
# working directory, so a suite runs from anywhere.
HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fixtures                                       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'checkpoint_type_test')
import os
import shutil
import sqlite3
import sys



fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# A library built for this test, so every number below is one this file
# decided rather than one that happened to be true of somebody's models.
db, facts = fixtures.build(WORK)
DB = facts['db_path']
from model_manager.db import ModelsDatabase
import model_manager.db.database as dbmod
import model_manager.sync_service as ss
from model_manager.civitai import CivitaiClient

dbmod._db_instance = db

# ------------------------------------------------- the inference, and its guards
class Server(CivitaiClient):
    """A Civitai that answers however the test wants it to."""

    def __init__(self, answers, stray=None, both=False):
        self.answers = answers        # kind -> ids to return
        self.stray = stray or []      # ids to return that were never asked for
        self.both = both
        self.calls = 0

    def _request(self, method, endpoint, params=None, absolute_url=None):
        self.calls += 1
        kind = params['checkpointType']
        ids = list(self.answers.get(kind, []))
        if self.both:
            ids = list(self.answers.get('Trained', []))
        return {"items": [{"id": i} for i in ids + self.stray]}


ASKED = [1, 2, 3, 4]
good = Server({'Trained': [1, 2], 'Merge': [3]})
check('the two queries answer for the batch',
      good.get_checkpoint_types(ASKED), {1: 'Trained', 2: 'Trained', 3: 'Merge'})
check('and it took two requests', good.calls, 2)
check('an id in neither is simply absent', 4 in good.get_checkpoint_types(ASKED), False)

check('no ids, no requests', CivitaiClient.get_checkpoint_types(
    Server({}), []), {})

# If `ids` stopped being honoured we would be told about other people's models.
stray = Server({'Trained': [1]}, stray=[999999])
check('an answer about models we did not ask for is discarded',
      stray.get_checkpoint_types(ASKED), {})

# If both queries claim the same model, the semantics are not what we assume.
both = Server({'Trained': [1, 2], 'Merge': [1]}, both=True)
check('a model that is both is discarded', both.get_checkpoint_types(ASKED), {})

# A failure returns what it can rather than raising into the sync.
class Broken(Server):
    def _request(self, *a, **k):
        from model_manager.civitai import CivitaiAPIError
        raise CivitaiAPIError('nope')

check('an API failure yields nothing rather than raising',
      Broken({}).get_checkpoint_types(ASKED), {})

# ------------------------------------------------------------------- storage
ids = db.checkpoint_model_ids()
check('every checkpoint in the fixture is there', len(ids), fixtures.CHECKPOINTS)

# How many are already classified is a fact about someone's library, and it
# grows every time they sync. Count from where this test starts.
def count(**kw):
    return db.query_models_grouped(limit=1, offset=0, **kw)[1]

# Two with no answer yet, so setting one is a change rather than a no-op. The
# fixture leaves one unclassified; clear a second to work with.
db.set_checkpoint_types({})          # a no-op, and proof that it is one
spare = [i for i in ids if i != facts['unclassified_checkpoint_id']][0]
import sqlite3 as _s
_raw = _s.connect(DB)
_raw.execute('UPDATE civitai_models SET checkpoint_type = NULL WHERE id = ?', (spare,))
_raw.commit(); _raw.close()

blank = [i for i in ids if not (db.get_civitai_model(i) or {}).get('checkpoint_type')]
check('two unclassified checkpoints to work with', len(blank), 2)
ids = blank + [i for i in ids if i not in blank]

# Counted after the adjustment above, so what follows is a change this test
# makes rather than one it inherited.
base_trained = count(checkpoint_type='Trained')
base_merge = count(checkpoint_type='Merge')
db.set_checkpoint_types({ids[0]: 'Trained', ids[1]: 'Merge'})
check('it reads back', (db.get_civitai_model(ids[0])['checkpoint_type'],
                        db.get_civitai_model(ids[1])['checkpoint_type']),
      ('Trained', 'Merge'))

# and a later sync that says nothing must not erase it
row = db.get_civitai_model(ids[0])
db.upsert_civitai_model({'id': ids[0], 'name': row['name'], 'type': 'Checkpoint'})
check('a sync that says nothing about it leaves it alone',
      db.get_civitai_model(ids[0])['checkpoint_type'], 'Trained')

# ------------------------------------------------------------------ filtering
everything = count()
trained = count(checkpoint_type='Trained')
merge = count(checkpoint_type='Merge')
unknown = count(checkpoint_type='unknown')
check('Trained gains the one just set', trained - base_trained, 1)
check('Merge gains the one just set', merge - base_merge, 1)
check('the three add up to the library', trained + merge + unknown, everything)
check('no filter is not the same as a filter', everything > trained + merge)

# ------------------------------------------------------------- the estimate
e = ss.estimate_metadata_sync()
check('the estimate counts the extra requests', e['requests']['checkpoints'] > 0)
check('and includes them in the total',
      e['requests']['total'],
      e['requests']['metadata'] + e['requests']['checkpoints']
      + e['requests']['images'] + e['requests']['prompts'])
check('two per hundred checkpoints',
      e['requests']['checkpoints'] % 2, 0)

# ------------------------------------------- a download classifies its own
class OneShot:
    def __init__(self): self.asked = []
    def get_checkpoint_types(self, ids):
        self.asked.append(list(ids))
        return {i: 'Trained' for i in ids}
    def close(self): pass

svc = ss.SyncService.__new__(ss.SyncService)
svc.client = OneShot()
svc._progress = ss.SyncProgress()
import threading
svc._progress_lock = threading.Lock()
svc._classify_checkpoints({ids[2]: {'type': 'Checkpoint'}})
check('one model is asked about on its own', svc.client.asked, [[ids[2]]])
check('and recorded', db.get_civitai_model(ids[2])['checkpoint_type'], 'Trained')

svc.client = OneShot()
svc._classify_checkpoints({ids[3]: {'type': 'LORA'}})
check('a LORA is not asked about at all', svc.client.asked, [])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
