"""
Starting, watching and cancelling the long jobs.

A sync runs on a background thread, and there is at most one
(model_manager.jobs) - so the interesting behaviour is what a second request
gets while the first is still running, what progress says before anything has
been started, and what a job that raises leaves behind.

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
from model_manager.jobs import jobs as registry          # noqa: E402
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
    """A sync that does whatever the test told it to."""

    hold = None          # an Event to wait on, so the job stays "running"
    raises = None
    processed = 0
    asked = []

    def __init__(self):
        self.progress = SyncProgress()
        self.cancelled = False

    def _run(self, name, kwargs):
        Job.asked.append((name, kwargs))
        if Job.hold is not None:
            Job.hold.wait(5)
        self.progress.processed = Job.processed
        if Job.raises is not None:
            raise Job.raises
        self.progress.is_complete = True     # as a service's own run does
        return self.progress

    def sync_all(self, **kwargs):
        return self._run('sync_all', kwargs)

    def sync_metadata(self, **kwargs):
        return self._run('sync_metadata', kwargs)

    def cancel(self):
        self.cancelled = True


jobs.SyncService = Job


def reset(hold=False, raises=None, processed=0):
    """Forget any job, and say how the next one should behave."""
    registry.reset()
    Job.asked = []
    Job.raises = raises
    Job.processed = processed
    Job.hold = threading.Event() if hold else None
    return Job.hold


def finished():
    """Wait for whichever job is running to end."""
    registry.join(5)


# ------------------------------------------------------- nothing started yet
reset()
status, body = get('/model-manager/sync/progress')
check('progress before any sync is None', (status, body['progress']), (200, None))
check('and says so', body['message'], 'No sync in progress')

status, body = post('/model-manager/sync/cancel')
check('cancelling nothing is refused', (status, body['success']), (200, False))
check('saying why', body['error'], 'No sync in progress')


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
check('its walk reading headers only for new or changed files, and moving nothing',
      (asked['reread_headers'], asked['move_misplaced']), (False, False))

reset()
post('/model-manager/sync', reread_headers='true', move_misplaced='true')
finished()
check('the Files section\'s boxes reach the sync',
      (Job.asked[0][1]['reread_headers'], Job.asked[0][1]['move_misplaced']), (True, True))

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
check('and it was asked to stop', registry.service('sync').cancelled, True)
hold.set()
finished()

status, body = post('/model-manager/sync')
check('and once it has finished, another can start', status, 200)
finished()

# ------------------------------------------------------- a sync that blows up
# Asked of the endpoint, as the page asks it. The error used to go into a
# record the endpoint never read: the page showed the sync running for ever.
reset(raises=RuntimeError('sync exploded'), processed=3)
post('/model-manager/sync')
finished()
p = get('/model-manager/sync/progress')[1]['progress']
check('a sync that raises is reported finished', p['is_complete'], True)
check('carrying the error where the page shows it - a count, and the message',
      (p['errors'], p['error_messages']), (1, ['sync exploded']))
check('and what it had done before', p['processed'], 3)

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
check('its walk reading headers only for new or changed files, and moving nothing',
      (asked['reread_headers'], asked['move_misplaced']), (False, False))

reset()
post('/model-manager/sync/metadata', reread_headers='true', move_misplaced='true')
finished()
check('the Files section\'s boxes reach the metadata sync too',
      (Job.asked[0][1]['reread_headers'], Job.asked[0][1]['move_misplaced']), (True, True))

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
p = get('/model-manager/sync/progress')[1]['progress']
check('one that raises reports the error',
      (p['is_complete'], p['error_messages']), (True, ['metadata exploded']))

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

# ------------------------------------------------- what the Files section reads
from modules import paths                                # noqa: E402  (webui_stub's)
paths.models_path = facts['models_dir']
status, body = get('/model-manager/sync/new-files')
check('the files every sync will hash are counted: here, the ones never asked about',
      (status, body['success'], body['files']), (200, True, fixtures.LOCAL_ONLY))
check('with their size', body['bytes'],
      sum(os.path.getsize(path) for path in facts['local_only_paths']))
paths.models_path = ''
status, body = get('/model-manager/sync/misplaced')
check('the sync dialog can list the files in another type\'s folder: none here',
      (status, body['success'], body['files']), (200, True, []))

# A finished job stays reportable: the page's last poll reads it.
reset()
post('/model-manager/sync')
finished()
status, body = get('/model-manager/sync/progress')
check('the last sync is still reportable once it has finished',
      body['progress']['is_complete'] if body['progress'] else None, True)

# ------------------------------------------------------------- no Scan Disk
# Every sync walks the library (0.48); Scan Disk and its endpoints are gone.
for method, url in ((post, '/model-manager/scan'), (get, '/model-manager/scan/progress'),
                    (get, '/model-manager/scan/misplaced'), (post, '/model-manager/scan/cancel')):
    check('%s is gone' % url, method(url)[0], 404)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
