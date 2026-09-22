"""
Starting, watching and cancelling the long jobs.

A scan or a sync runs on a background thread, and there is at most one of each
- so the interesting behaviour is in the module-level state: what a second
request gets while the first is still running, what progress says before
anything has been started, and what a job that raises leaves behind.

The services themselves are stubbed and made to block on an event, so "already
in progress" is tested deterministically rather than by racing a real sync.
The estimate endpoint is not stubbed: it runs against the fixture library,
because its numbers are the point of it.
"""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.api.jobs as jobs                    # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.scan_service import ScanProgress      # noqa: E402
from model_manager.sync_service import SyncProgress      # noqa: E402

WORK = os.path.join(TESTS, 'work', 'jobs_api')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db

app = FastAPI()
setup_api(app)
client = TestClient(app)


def post(url, **data):
    r = client.post(url, data=data)
    return r.status_code, r.json()


def get(url, **params):
    r = client.get(url, params=params)
    return r.status_code, r.json()


# ---------------------------------------------------------------- stub services
class Job:
    """A sync or a scan that does whatever the test told it to."""

    hold = None          # an Event to wait on, so the job stays "running"
    raises = None
    asked = []

    def __init__(self):
        self.progress = SyncProgress()
        self.cancelled = False

    def _run(self, name, kwargs):
        Job.asked.append((name, kwargs))
        if Job.hold is not None:
            Job.hold.wait(5)
        if Job.raises is not None:
            raise Job.raises
        return self.progress

    def sync_all(self, **kwargs):
        return self._run('sync_all', kwargs)

    def sync_metadata(self, **kwargs):
        return self._run('sync_metadata', kwargs)

    def cancel(self):
        self.cancelled = True


class Scan(Job):
    def __init__(self):
        Job.__init__(self)
        self.progress = ScanProgress()

    def scan_models(self, **kwargs):
        return self._run('scan_models', kwargs)


jobs.SyncService = Job
jobs.ScanService = Scan


def reset(hold=False, raises=None):
    """Forget any job, and say how the next one should behave."""
    for name in ('_active_sync', '_sync_thread', '_sync_progress',
                 '_active_scan', '_scan_thread', '_scan_progress'):
        setattr(jobs, name, None)
    Job.asked = []
    Job.raises = raises
    Job.hold = threading.Event() if hold else None
    return Job.hold


def finished():
    """Wait for whichever job is running to end."""
    for thread in (jobs._sync_thread, jobs._scan_thread):
        if thread is not None:
            thread.join(5)


# ------------------------------------------------------- nothing started yet
reset()
status, body = get('/model-manager/sync/progress')
check('progress before any sync is None', (status, body['progress']), (200, None))
check('and says so', body['message'], 'No sync in progress')

status, body = get('/model-manager/scan/progress')
check('the same for a scan', body['progress'], None)
check('with its own message', body['message'], 'No scan in progress')

status, body = post('/model-manager/sync/cancel')
check('cancelling nothing is refused', (status, body['success']), (200, False))
check('saying why', body['error'], 'No sync in progress')

status, body = post('/model-manager/scan/cancel')
check('and cancelling no scan too', body['error'], 'No scan in progress')

# --------------------------------------------------------------- a full sync
reset()
status, body = post('/model-manager/sync')
finished()
check('a sync starts', (status, body['success']), (200, True))
check('and says so', body['message'], 'Sync started')
name, asked = Job.asked[0]
check('it is the hashing sync that runs', name, 'sync_all')
check('over everything by default', asked['model_paths'], None)
check('without forcing', asked['force'], False)
check('and targeting all of them', asked['targets'], 'all')

for spelling in ('true', 'True', '1', 'yes'):
    reset()
    post('/model-manager/sync', force=spelling)
    finished()
    check('%r is a yes' % spelling, Job.asked[0][1]['force'], True)

for spelling in ('false', 'no', '', 'nonsense'):
    reset()
    post('/model-manager/sync', force=spelling)
    finished()
    check('%r is not' % spelling, Job.asked[0][1]['force'], False)

for targets in ('identified', 'unidentified'):
    reset()
    post('/model-manager/sync', targets=targets)
    finished()
    check('choosing %s narrows the set' % targets, Job.asked[0][1]['targets'], targets)
    check('and forces, since choosing a set is the point',
          Job.asked[0][1]['force'], True)

reset()
post('/model-manager/sync', targets='something-else')
finished()
check('a set nobody offers falls back to all', Job.asked[0][1]['targets'], 'all')
check('and does not force', Job.asked[0][1]['force'], False)

reset()
post('/model-manager/sync', paths=' a.safetensors , b.safetensors ,, ')
finished()
check('the path list is split and trimmed',
      Job.asked[0][1]['model_paths'], ['a.safetensors', 'b.safetensors'])

# --------------------------------------------------------- one sync at a time
hold = reset(hold=True)
post('/model-manager/sync')
status, body = post('/model-manager/sync')
check('a second sync is refused while one runs', status, 409)
check('saying which', body['error'], 'Sync already in progress')

status, body = get('/model-manager/sync/progress')
check('progress comes from the running service', body['progress'] is not None, True)

status, body = post('/model-manager/sync/cancel')
check('cancelling reaches it', (status, body['success']), (200, True))
check('and it was asked to stop', jobs._active_sync.cancelled, True)
hold.set()
finished()

status, body = post('/model-manager/sync')
check('and once it has finished, another can start', status, 200)
finished()

# ------------------------------------------------------- a sync that blows up
# The progress endpoint prefers the live service's own record, so what the
# thread leaves behind is checked directly - that is the fallback the UI reads
# once the service is gone.
reset(raises=RuntimeError('sync exploded'))
post('/model-manager/sync')
finished()
check('a sync that raises still finishes', jobs._sync_progress.is_complete, True)
check('carrying the error where the UI will see it',
      jobs._sync_progress.error_messages, ['sync exploded'])

# ------------------------------------------------------------ a metadata sync
reset()
status, body = post('/model-manager/sync/metadata')
finished()
check('the metadata sync starts', (status, body['success']), (200, True))
check('and says so', body['message'], 'Metadata sync started')
name, asked = Job.asked[0]
check('it is the no-hashing sync that runs', name, 'sync_metadata')
check('images are left out by default', asked['include_images'], False)
check('but prompts are looked up', asked['include_prompts'], True)
check('with no staleness window', asked['synced_before'], None)
check('and no download window', asked['downloaded_after'], None)

reset()
status, body = post('/model-manager/sync/metadata', include_images='true',
                    include_prompts='false')
finished()
check('asking for images gets them', Job.asked[0][1]['include_images'], True)
check('and the message says so', body['message'], 'Metadata sync started (with images)')
check('while prompts can be declined', Job.asked[0][1]['include_prompts'], False)

reset()
post('/model-manager/sync/metadata', stale_days=7, downloaded_days=30)
finished()
asked = Job.asked[0][1]
check('a staleness window becomes a cutoff', bool(asked['synced_before']), True)
check('and so does a download window', bool(asked['downloaded_after']), True)
check('the older window is the earlier date',
      asked['downloaded_after'] < asked['synced_before'], True)

reset()
post('/model-manager/sync/metadata', paths='x.safetensors')
finished()
check('paths reach the metadata sync too',
      Job.asked[0][1]['model_paths'], ['x.safetensors'])

hold = reset(hold=True)
post('/model-manager/sync/metadata')
status, body = post('/model-manager/sync/metadata')
check('and only one of those runs at a time', status, 409)
hold.set()
finished()

reset(raises=RuntimeError('metadata exploded'))
post('/model-manager/sync/metadata')
finished()
check('one that raises reports the error',
      jobs._sync_progress.error_messages, ['metadata exploded'])

# ----------------------------------------------------------------- the estimate
reset()
status, body = get('/model-manager/sync/estimate')
check('the estimate answers', (status, body['success']), (200, True))
estimate = body['estimate']
check('counting the versions it would refresh',
      estimate['versions'], fixtures.LINKED_VERSIONS)
check('and the models behind them', estimate['models'], fixtures.MODELS)
check('the requests are broken down by what they are for',
      sorted(estimate['requests']),
      ['checkpoints', 'images', 'metadata', 'prompts', 'total'])
check('metadata is a hundred models a request', estimate['requests']['metadata'], 1)
check('checkpoints cost two more, being inferred from two queries',
      estimate['requests']['checkpoints'], 2)
check('nothing is spent on images unless they are asked for',
      (estimate['requests']['images'], estimate['requests']['prompts']), (0, 0))
check('and the total is the sum', estimate['requests']['total'], 3)
check('what all of them would cost is reported whatever the scope',
      estimate['all_versions'], fixtures.LINKED_VERSIONS)
check('and no seconds, which would be a guess', 'seconds' in estimate, False)

check('the staleness windows are counted', len(body['windows']) > 0, True)
check('and the download windows separately', len(body['download_windows']) > 0, True)
check('with the unidentified files costed in files, not requests',
      body['unidentified']['unidentified'], fixtures.LOCAL_ONLY)
check('beside the ones that do resolve',
      body['unidentified']['identified'], fixtures.LINKED_VERSIONS)
check('and none of them has been asked about yet',
      body['unidentified']['asked_not_found'], 0)

status, with_images = get('/model-manager/sync/estimate', include_images='true')
check('adding images costs a request per version',
      with_images['estimate']['requests']['images'], fixtures.LINKED_VERSIONS)

status, with_prompts = get('/model-manager/sync/estimate', include_images='true',
                           include_prompts='true')
check('and looking up the prompts behind them costs more again',
      with_prompts['estimate']['requests']['prompts'] > 0, True)
check('costed against the images that are actually there',
      with_prompts['estimate']['images'],
      fixtures.LINKED_VERSIONS * fixtures.IMAGES_PER_VERSION)

status, narrow = get('/model-manager/sync/estimate',
                     paths=facts['linked_paths'][0])
check('naming one path costs one version', narrow['estimate']['versions'], 1)

status, stale = get('/model-manager/sync/estimate', stale_days=1)
check('a staleness window can only narrow it',
      stale['estimate']['versions'] <= estimate['versions'], True)

real_estimate = jobs.estimate_metadata_sync
jobs.estimate_metadata_sync = lambda **kwargs: 1 / 0
status, body = get('/model-manager/sync/estimate')
check('an estimate that fails is a 500', status, 500)
check('with the reason', 'division by zero' in body['error'], True)
jobs.estimate_metadata_sync = real_estimate

# ---------------------------------------------------------------------- a scan
reset()
status, body = post('/model-manager/scan')
finished()
check('a scan starts', (status, body['success']), (200, True))
check('and says so', body['message'], 'Scan started')
check('it is the scan that runs', Job.asked[0][0], 'scan_models')

status, body = get('/model-manager/scan/progress')
check('its progress is readable', body['progress'] is not None, True)

hold = reset(hold=True)
post('/model-manager/scan')
status, body = post('/model-manager/scan')
check('a second scan is refused while one runs', status, 409)
check('saying which', body['error'], 'Scan already in progress')
status, body = post('/model-manager/scan/cancel')
check('cancelling reaches it', body['success'], True)
check('and it was asked to stop', jobs._active_scan.cancelled, True)
hold.set()
finished()

reset(raises=RuntimeError('scan exploded'))
post('/model-manager/scan')
finished()
check('a scan that raises still finishes', jobs._scan_progress.is_complete, True)
# The scan keeps what went wrong, but only the count reaches the UI - the
# message goes to the log. A sync sends the messages themselves.
check('carrying what went wrong', jobs._scan_progress.errors, ['scan exploded'])
check('of which the UI is told only the number',
      jobs._scan_progress.to_dict()['error_count'], 1)

# Progress after the service has been forgotten falls back to the last record.
reset()
jobs._scan_progress = ScanProgress(is_complete=True)
status, body = get('/model-manager/scan/progress')
check('the last scan is still reportable once the service is gone',
      body['progress']['is_complete'], True)
jobs._sync_progress = SyncProgress(is_complete=True)
status, body = get('/model-manager/sync/progress')
check('and so is the last sync', body['progress']['is_complete'], True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
