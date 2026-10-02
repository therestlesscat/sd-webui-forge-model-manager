"""
The registry of long jobs (model_manager.jobs), on its own.

One job of a kind at a time, kinds independent of each other, and a job that
raises reported finished with its error on the progress the poll reads - with
the counts it had reached. The endpoints over it are jobs_api_test.py's.
"""
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402
webui_stub.install()

from model_manager.jobs import Jobs                      # noqa: E402
from model_manager.scan_service import ScanProgress      # noqa: E402
from model_manager.sync_service import SyncProgress      # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


class Service(object):
    made = 0

    def __init__(self, progress=None):
        Service.made += 1
        self.progress = progress or SyncProgress()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


jobs = Jobs()
check('nothing ran: no progress', jobs.progress('sync'), None)
check('and nothing to cancel', jobs.cancel('sync'), False)
check('nor running', jobs.running('sync'), False)

# ------------------------------------------------------------ one at a time
hold = threading.Event()
check('a job starts', jobs.start('sync', Service, lambda s: hold.wait(5)), True)
made = Service.made
check('a second of the kind is refused while it runs', jobs.start('sync', Service, lambda s: None), False)
check('and no service is made for it', Service.made, made)
check('a job of another kind starts beside it', jobs.start('scan', Service, lambda s: None), True)
check('cancelling reaches the running one', (jobs.cancel('sync'), jobs.service('sync').cancelled), (True, True))
hold.set()
jobs.join(5)
check('once it ends, another can start', jobs.start('sync', Service, lambda s: None), True)
jobs.join(5)

# ------------------------------------------------------------- a job that raises
def explode_after(n):
    def run(service):
        service.progress.processed = n
        raise RuntimeError('exploded')
    return run

jobs.start('sync', Service, explode_after(3))
jobs.join(5)
p = jobs.progress('sync')
check('a sync that raises is finished', p.is_complete, True)
check('with its error counted and said', (p.errors, p.error_messages), (1, ['exploded']))
check('and what it had done', p.processed, 3)

jobs.start('scan', lambda: Service(ScanProgress()), explode_after(2))
jobs.join(5)
p = jobs.progress('scan')
check('a scan that raises is finished, with its error', (p.is_complete, p.errors, p.processed),
      (True, ['exploded'], 2))

# ------------------------------------------------ asked again while it runs
# A restamp asked for while one runs must not be lost (#98): with `again`, the
# running service is asked again(), and runs once more when it is done.
class Again(Service):
    def __init__(self):
        super().__init__()
        self.asked, self.finished = 0, False

    def again(self):
        if self.finished:
            return False
        self.asked += 1
        return True


hold.clear()
jobs.start('restamp', Again, lambda s: hold.wait(5))
made, first = Service.made, jobs.service('restamp')
check('asked again while it runs, the ask is taken',
      jobs.start('restamp', Again, lambda s: None, again=True), True)
check('by the running one: nothing new is made', (Service.made, first.asked), (made, 1))
check('without again, the same ask is refused as ever', jobs.start('restamp', Again, lambda s: None), False)
hold.set()
jobs.join(5)

# One that has finished, its thread not yet gone, says so: a new job starts.
hold.clear()
jobs.start('restamp', Again, lambda s: hold.wait(5))
closing = jobs.service('restamp')
closing.finished = True
check('one that has finished, asked again, gives way to a new job',
      jobs.start('restamp', Again, lambda s: None, again=True), True)
check('with a service of its own', jobs.service('restamp') is not closing, True)
hold.set()
jobs.join(5)

jobs.reset()
check('reset forgets every job', (jobs.progress('sync'), jobs.progress('scan')), (None, None))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
