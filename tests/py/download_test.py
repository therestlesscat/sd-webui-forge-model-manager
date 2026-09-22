"""
Downloading a model: where it lands, what goes wrong, and what is written beside it.

Nothing here reaches Civitai. `requests` is swapped for a fake whose sessions
hand back scripted responses, so the retry rules, the cancel check and the
HTTP error cases can all be driven without a network - including the ones that
only happen when a download fails halfway through.
"""
import io
import json
import os
import shutil
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'download')
shutil.rmtree(WORK, ignore_errors=True)
MODELS = os.path.join(WORK, 'models')
CKPT_DIR = os.path.join(MODELS, 'Stable-diffusion')
os.makedirs(CKPT_DIR)

opts = webui_stub.install(models_path=MODELS)
cmd_opts = sys.modules['modules'].shared.cmd_opts

import requests as real_requests                         # noqa: E402
from model_manager import download_service as ds         # noqa: E402
from model_manager.download_service import (             # noqa: E402
    DownloadProgress, DownloadService, get_download_service,
)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# Retries sleep for three seconds each; the test does not need to.
ds.time = types.SimpleNamespace(sleep=lambda seconds: None)


# --------------------------------------------------------------- the progress
p = DownloadProgress(version_id=1)
check('nothing downloaded yet is nought percent', p.percent, 0)
check('and not complete', p.is_complete, False)

p.total_bytes, p.downloaded_bytes = 1000, 333
check('percent is the ratio', round(p.percent, 1), 33.3)
check('and it is rounded on the way out', p.to_dict()['percent'], 33.3)

for status, complete in (('pending', False), ('downloading', False),
                         ('complete', True), ('error', True), ('cancelled', True)):
    p.status = status
    check('%s means complete=%s' % (status, complete), p.is_complete, complete)

p = DownloadProgress(version_id=7, file_name='f.safetensors')
check('the dict carries what the UI polls for',
      sorted(p.to_dict()), ['downloaded_bytes', 'error', 'file_name', 'file_path',
                            'percent', 'status', 'sync_error', 'synced',
                            'total_bytes', 'version_id'])

# ------------------------------------------------------------ which file to take
FILES = [{'id': 11, 'name': 'full.safetensors'},
         {'id': 22, 'name': 'pruned.safetensors', 'primary': True},
         {'id': 33, 'name': 'other.safetensors'}]
pick = DownloadService.pick_file_index
check('an id wins, wherever it sits in the list', pick(FILES, file_id=33), 2)
check('an id beats an index too', pick(FILES, file_index=0, file_id=33), 2)
check('an id nobody has falls back to the index', pick(FILES, file_index=0, file_id=99), 0)
check('an index is honoured', pick(FILES, file_index=2), 2)
check('an index off the end falls back to the primary', pick(FILES, file_index=9), 1)
check('and with neither, the primary', pick(FILES), 1)
check('with no primary marked, the first',
      pick([{'id': 1}, {'id': 2}]), 0)
check('and an empty list is still an index', pick([]), 0)

# ---------------------------------------------------------- the folder template
service = DownloadService(max_concurrent=2)
MODEL = {'id': 42, 'name': 'A Model: Mk/2', 'creator': {'username': 'some one'}}
VERSION = {'baseModel': 'SDXL 1.0'}

check('no template, no subfolder', service.apply_folder_template('', MODEL, VERSION), '')
check('the placeholders are filled and made safe',
      service.apply_folder_template('{baseModel}/{modelName}', MODEL, VERSION),
      os.path.join('SDXL_1.0', 'A_Model_Mk_2'))
check('the creator too',
      service.apply_folder_template('{creator}', MODEL, VERSION), 'some_one')
check('and the id, which needs no sanitising',
      service.apply_folder_template('{modelId}', MODEL, VERSION), '42')
check('a model with no creator still lands somewhere',
      service.apply_folder_template('{creator}', {'id': 1, 'name': 'n'}, VERSION),
      'Unknown')
check('and one with no base model',
      service.apply_folder_template('{baseModel}', MODEL, {}), 'Unknown')
check('backslashes and doubled slashes collapse',
      service.apply_folder_template('a\\\\b//c/', MODEL, VERSION),
      os.path.join('a', 'b', 'c'))
long_name = service.apply_folder_template('{modelName}', {'name': 'x' * 300}, VERSION)
check('an absurd name is cut to something a filesystem will take',
      len(long_name), 100)

# ------------------------------------------------------------- where it lands
check('a known type has a folder', service.get_model_type_folder('LORA'), 'Lora')
check('an unknown type goes to Other', service.get_model_type_folder('Nonsense'), 'Other')
check('embeddings are the special case',
      service.get_model_type_folder('TextualInversion'), None)

check('embeddings land under the models path',
      service.get_base_path('TextualInversion'),
      os.path.join(MODELS, 'embeddings'))

check('a type with no override falls back to the models path',
      service.get_base_path('Upscaler'), os.path.join(MODELS, 'ESRGAN'))

cmd_opts.ckpt_dir = CKPT_DIR
check('a command-line directory that exists wins',
      service.get_base_path('Checkpoint'), CKPT_DIR)

cmd_opts.ckpt_dir = os.path.join(WORK, 'not-there')
check('but one that does not is ignored',
      service.get_base_path('Checkpoint'), os.path.join(MODELS, 'Stable-diffusion'))
cmd_opts.ckpt_dir = CKPT_DIR

# Text encoders are scanned beside VAEs but are never a download target.
ENCODERS = os.path.join(WORK, 'text_encoder')
os.makedirs(ENCODERS)
cmd_opts.text_encoder_dirs = [ENCODERS]
cmd_opts.vae_dir = None
check('a VAE is never written into the text encoder directory',
      service.get_base_path('VAE'), os.path.join(MODELS, 'VAE'))

LORA_DIR = os.path.join(WORK, 'loras')
os.makedirs(LORA_DIR)
cmd_opts.lora_dirs = [LORA_DIR]
check('the LoRA variants share one directory',
      (service.get_base_path('LoCon'), service.get_base_path('DoRA')),
      (LORA_DIR, LORA_DIR))

# ------------------------------------------------------------ the progress bars
first = service._allocate_tqdm_position(1)
second = service._allocate_tqdm_position(2)
check('each download gets its own line', (first, second), (0, 1))
service._release_tqdm_position(1)
check('and a freed line is reused', service._allocate_tqdm_position(3), 0)
service._release_tqdm_position(2)
service._release_tqdm_position(3)
check('releasing one nobody holds is harmless',
      service._release_tqdm_position(99), None)

# ---------------------------------------------------------------- cancelling
check('nothing is cancelled to start with', service._is_cancelled(5), False)
service.cancel(5)
check('until it is', service._is_cancelled(5), True)

service._active_downloads = {6: DownloadProgress(version_id=6),
                             7: DownloadProgress(version_id=7)}
service.cancel_all()
check('cancel all reaches every active download',
      (service._is_cancelled(6), service._is_cancelled(7)), (True, True))
check('progress is readable by id', service.get_progress(6).version_id, 6)
check('one nobody is downloading is None', service.get_progress(404), None)
check('and all of it at once', len(service.get_all_progress()), 2)
service._active_downloads = {}
service._cancel_flags = {}


# --------------------------------------------------------------- a fake Civitai
class FakeResponse:
    def __init__(self, chunks=(), total=None, error=None):
        self.chunks = list(chunks)
        self.error = error
        size = total if total is not None else sum(len(c) for c in self.chunks)
        self.headers = {'content-length': str(size)}

    def raise_for_status(self):
        if self.error:
            raise self.error

    def iter_content(self, chunk_size=None):
        for chunk in self.chunks:
            yield chunk


class FakeSession:
    def get(self, url, headers=None, stream=False, timeout=None):
        FakeSession.asked.append((url, headers))
        reply = FakeSession.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def civitai_says(*replies):
    """Script the next N session.get() calls."""
    FakeSession.replies = list(replies)
    FakeSession.asked = []


ds.requests = types.SimpleNamespace(Session=FakeSession,
                                    exceptions=real_requests.exceptions)


def http_error(status, body=''):
    response = types.SimpleNamespace(status_code=status, text=body)
    return real_requests.exceptions.HTTPError('http %s' % status, response=response)


TARGET = os.path.join(WORK, 'out.safetensors')


def download(*replies, **kwargs):
    """Run one _download_file against a scripted Civitai, and report."""
    civitai_says(*replies)
    progress = DownloadProgress(version_id=kwargs.pop('version_id', 100))
    ok = service._download_file('https://example.invalid/f', TARGET, {}, progress)
    return ok, progress


# ------------------------------------------------------------------- happy path
ok, progress = download(FakeResponse([b'abc', b'def']))
check('a clean download succeeds', ok, True)
check('the file is on disk', io.open(TARGET, 'rb').read(), b'abcdef')
check('and the byte count is reported', progress.downloaded_bytes, 6)
check('against the total the server gave', progress.total_bytes, 6)
os.remove(TARGET)

# A server that does not say how long the file is still works.
ok, progress = download(FakeResponse([b'abc'], total=0))
check('an unknown length is not an error', ok, True)
check('and no size check is made', progress.total_bytes, 0)
os.remove(TARGET)

# -------------------------------------------------------------------- truncated
ok, progress = download(FakeResponse([b'abc'], total=99),
                        FakeResponse([b'abc'], total=99),
                        FakeResponse([b'abc'], total=99))
check('a short file is a failure', ok, False)
check('named as such', 'Incomplete download' in (progress.error or ''), True)
# NOTE: a truncated file is raised as a bare Exception, which the catch-all
# handler answers with `return False` - so unlike a connection error it is
# never retried, though a truncated download is exactly the case a retry
# would fix. Recorded as it behaves so that changing it fails here.
check('but it is not retried', len(FakeSession.asked), 1)

# ------------------------------------------------------------------- cancelled
civitai_says(FakeResponse([b'a' * 10] * 5))
progress = DownloadProgress(version_id=200)
service.cancel(200)
ok = service._download_file('https://example.invalid/f', TARGET, {}, progress)
check('a cancelled download stops', ok, False)
check('and says so', progress.status, 'cancelled')
check('taking the half-written file with it', os.path.exists(TARGET), False)
service._cancel_flags.pop(200, None)

# ---------------------------------------------------------------- refused
ok, progress = download(FakeResponse(error=http_error(401, 'no key')))
check('a 401 fails', ok, False)
check('asking for an API key', 'API key' in (progress.error or ''), True)
check('without retrying - the answer will not change', len(FakeSession.asked), 1)

ok, progress = download(FakeResponse(error=http_error(403)))
check('a 403 fails too', ok, False)
check('blaming permissions', 'Access denied' in (progress.error or ''), True)
check('and does not retry either', len(FakeSession.asked), 1)

ok, progress = download(*[FakeResponse(error=http_error(500))] * 3)
check('a server error fails after retrying', ok, False)
check('reporting the status', 'HTTP 500' in (progress.error or ''), True)
check('having tried three times', len(FakeSession.asked), 3)

ok, progress = download(FakeResponse(error=http_error(500)),
                        FakeResponse([b'ok']))
check('and a retry that succeeds is a success', ok, True)
os.remove(TARGET)

# -------------------------------------------------------------- the network
timeout = real_requests.exceptions.ConnectionError('no route')
ok, progress = download(timeout, timeout, timeout)
check('a connection that never opens fails', ok, False)
check('after the attempts it promised',
      'after 3 attempts' in (progress.error or ''), True)

ok, progress = download(timeout, FakeResponse([b'second time lucky']))
check('but one that opens on the retry succeeds', ok, True)
os.remove(TARGET)

ok, progress = download(RuntimeError('something else entirely'))
check('anything else fails at once', ok, False)
check('carrying the message', 'something else entirely' in (progress.error or ''), True)
check('with no retry', len(FakeSession.asked), 1)

check('and every position it took was given back', service._tqdm_positions, {})


# ------------------------------------------------------- a whole version
def version(**extra):
    data = {'id': 500, 'baseModel': 'SDXL 1.0',
            'files': [{'id': 1, 'name': 'model.safetensors', 'primary': True,
                       'downloadUrl': 'https://example.invalid/model'}]}
    data.update(extra)
    return data


CHECKPOINT = {'id': 42, 'name': 'Subject', 'type': 'Checkpoint',
              'description': '<p>d</p>', 'tags': ['t'], 'nsfw': False,
              'nsfwLevel': 1, 'creator': {'username': 'someone'},
              'stats': {'downloadCount': 3}}

synced = []
service._sync_downloaded_file = lambda path, progress=None: synced.append(path)

civitai_says(FakeResponse([b'weights']))
progress = service.download_version(500, CHECKPOINT, version())
check('the download completes', progress.status, 'complete')
check('landing in the checkpoint directory',
      os.path.dirname(progress.file_path), CKPT_DIR)
check('under the name Civitai gave it',
      os.path.basename(progress.file_path), 'model.safetensors')
check('and it was handed to the database', synced, [progress.file_path])

info = os.path.splitext(progress.file_path)[0] + '.civitai.info'
written = json.loads(io.open(info, encoding='utf-8').read())
check('a sidecar is written beside it', written['id'], 42)
check('with the model id repeated where other extensions look',
      written['modelId'], 42)
check('the type', written['type'], 'Checkpoint')
check('and the one version that was fetched',
      [v['id'] for v in written['modelVersions']], [500])

# the same file again
civitai_says(FakeResponse([b'weights']))
again = service.download_version(500, CHECKPOINT, version())
check('downloading it twice is refused', again.status, 'error')
check('saying why', 'already exists' in (again.error or ''), True)
check('and points at what is already there', again.file_path, progress.file_path)
os.remove(progress.file_path)
os.remove(info)

# a template that puts it in a subfolder
opts.model_manager_civitai_folder_template = '{baseModel}/{modelName}'
civitai_says(FakeResponse([b'weights']))
nested = service.download_version(501, CHECKPOINT, version(id=501))
check('the template makes the subfolder',
      os.path.relpath(os.path.dirname(nested.file_path), CKPT_DIR),
      os.path.join('SDXL_1.0', 'Subject'))
shutil.rmtree(os.path.join(CKPT_DIR, 'SDXL_1.0'))
opts.model_manager_civitai_folder_template = ''

# --------------------------------------------------------------- refused early
civitai_says()
paid = service.download_version(502, CHECKPOINT,
                                version(paidAccess={'permanent': True}))
check('a permanently paid version is refused', paid.status, 'error')
check('telling the user to buy it', 'buy it there first' in (paid.error or ''), True)

early = service.download_version(503, CHECKPOINT,
                                 version(earlyAccessDeadline='2026-12-01T00:00:00Z'))
check('and an early-access one is refused with its date',
      '2026-12-01T00:00:00Z' in (early.error or ''), True)

check('neither of them asked Civitai for anything', len(FakeSession.asked), 0)

empty = service.download_version(504, CHECKPOINT, version(files=[]))
check('a version with no files is an error', empty.error, 'No files available for download')

no_url = service.download_version(505, CHECKPOINT,
                                  version(files=[{'id': 1, 'name': 'x.safetensors'}]))
check('and one with no URL to fetch', no_url.error, 'No download URL available')

# a failure inside the download is reported, not raised
del synced[:]
civitai_says(*[FakeResponse(error=http_error(500))] * 3)
failed = service.download_version(506, CHECKPOINT, version(id=506))
check('a download that fails comes back as an error', failed.status, 'error')
check('and nothing was synced', synced, [])

# anything unexpected is caught rather than escaping to the queue
broken = service.download_version(507, CHECKPOINT, None)
check('a malformed version is an error, not a crash', broken.status, 'error')

check('no download leaves its cancel flag behind', service._cancel_flags, {})

# ------------------------------------------------------------- the API key
opts.model_manager_civitai_api_key = 'secret-key'
civitai_says(FakeResponse([b'weights']))
authorised = service.download_version(508, CHECKPOINT, version(id=508))
check('the key is sent as a bearer token',
      FakeSession.asked[0][1].get('Authorization'), 'Bearer secret-key')
os.remove(authorised.file_path)
os.remove(os.path.splitext(authorised.file_path)[0] + '.civitai.info')

opts.model_manager_civitai_api_key = ''
civitai_says(FakeResponse([b'weights']))
anonymous = service.download_version(509, CHECKPOINT, version(id=509))
check('and without one, no header at all',
      'Authorization' in FakeSession.asked[0][1], False)
os.remove(anonymous.file_path)
os.remove(os.path.splitext(anonymous.file_path)[0] + '.civitai.info')

# ------------------------------------------------------------------ the queue
queued = []


class Queueing(DownloadService):
    def download_version(self, version_id, model_data, version_data,
                         file_index=None, file_id=None):
        queued.append((version_id, file_index, file_id))
        return DownloadProgress(version_id=version_id, status='complete')


queue = Queueing(max_concurrent=1)
handle = queue.queue_download(600, CHECKPOINT, version(id=600), file_id=1)
check('the queued download is named before it starts',
      handle.file_name, 'model.safetensors')
check('and is visible to the poller straight away',
      queue.get_progress(600) is handle, True)
nameless = queue.queue_download(601, CHECKPOINT, version(id=601, files=[]))
check('a version with no files is still queued', nameless.file_name, 'Unknown')
queue._executor.shutdown(wait=True)
check('the work reached the executor', queued, [(600, None, 1), (601, None, None)])
queue._executor = None

queue.queue_download(602, CHECKPOINT, version(id=602))
check('a second executor is made when the first is gone',
      queue._executor is not None, True)
queue.shutdown()
check('shutting down drops the executor', queue._executor, None)
check('and cancels what was in flight', queue._is_cancelled(600), True)
queue.shutdown()
check('shutting down twice is harmless', queue._executor, None)


# ------------------------------------------------- syncing what was downloaded
class Result:
    def __init__(self, success, error=None):
        self.success = success
        self.error = error


class FakeSync:
    result = Result(True)

    def sync_model(self, file_path, force=False):
        FakeSync.asked = (file_path, force)
        if isinstance(FakeSync.result, Exception):
            raise FakeSync.result
        return FakeSync.result


import model_manager.sync_service as sync_module          # noqa: E402
import model_manager.db as db_module                      # noqa: E402

sync_module.SyncService = FakeSync
stamped = []
db_module.get_models_db = lambda: types.SimpleNamespace(
    set_downloaded_at=lambda path: stamped.append(path))

real = DownloadService()


def sync_and_wait(path):
    progress = DownloadProgress(version_id=1)
    real._sync_downloaded_file(path, progress)
    for _ in range(200):
        if progress.synced:
            break
        time.sleep(0.01)
    return progress


done = sync_and_wait('/models/x.safetensors')
check('a downloaded file is synced', FakeSync.asked, ('/models/x.safetensors', True))
check('the UI is told it is queryable', done.synced, True)
check('with no complaint', done.sync_error, None)
check('and the download is dated', stamped, ['/models/x.safetensors'])

FakeSync.result = Result(False, 'not on Civitai')
done = sync_and_wait('/models/y.safetensors')
check('a sync that fails still unblocks the UI', done.synced, True)
check('carrying the reason', done.sync_error, 'not on Civitai')

FakeSync.result = RuntimeError('database is locked')
done = sync_and_wait('/models/z.safetensors')
check('and so does one that raises', done.synced, True)
check('with the exception as the reason', done.sync_error, 'database is locked')

FakeSync.result = Result(True)
real._sync_downloaded_file('/models/w.safetensors')
time.sleep(0.2)
check('syncing without a progress record works too',
      FakeSync.asked[0], '/models/w.safetensors')

# -------------------------------------------------- with no progress bars
# tqdm ships with the WebUI, but the download must work without it.
sys.modules['tqdm'] = None
ok, bare = download(FakeResponse([b'no bar here']))
check('a download with no tqdm still succeeds', ok, True)
check('and still counts the bytes', bare.downloaded_bytes, 11)
os.remove(TARGET)
del sys.modules['tqdm']

# ------------------------------------------------------------- the singleton
check('the service is made once', get_download_service() is get_download_service(), True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
