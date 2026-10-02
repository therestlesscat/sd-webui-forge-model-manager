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


# What can be resumed is kept here, never in a database (DownloadService.store).
kept = {'value': None}
DownloadService.store = (lambda: kept['value'], lambda value: kept.__setitem__('value', value))

# Retries sleep for three seconds each; the test does not need to.
ds.time = types.SimpleNamespace(sleep=lambda seconds: None)


# --------------------------------------------------------------- the progress
p = DownloadProgress(version_id=1)
check('nothing downloaded yet is nought percent', p.percent, 0)
check('and not complete', p.is_complete, False)

p.total_bytes, p.downloaded_bytes = 1000, 333
check('percent is the ratio', round(p.percent, 1), 33.3)
check('and it is rounded on the way out', p.to_dict()['percent'], 33.3)

for status, complete in (('pending', False), ('downloading', False), ('finishing', False),
                         ('complete', True), ('error', True), ('cancelled', True)):
    p.status = status
    check('%s means complete=%s' % (status, complete), p.is_complete, complete)

p = DownloadProgress(version_id=7, file_name='f.safetensors')
check('the dict carries what the UI polls for',
      sorted(p.to_dict()), ['downloaded_bytes', 'error', 'eta_seconds', 'file_name', 'file_path',
                            'filed', 'page_url', 'percent', 'speed_bps', 'stalled', 'started_over', 'status', 'sync_error', 'synced',
                            'total_bytes', 'version_id'])

# ------------------------------------------------------ how fast, how long (#36)
# Measured where every chunk is seen, over the last 5 seconds, so it does not
# jump with each chunk; nothing said before a second's worth, and nothing for
# 5 seconds is "stalled", not 0 B/s. The clock is the caller's here.
MB = 1024 * 1024
p = DownloadProgress(version_id=8, total_bytes=100 * MB, status='downloading')
p.record(now=0.0)
check('before a second\'s worth, no speed yet', p.rate(now=0.5), (None, None, False))
for t in range(1, 21):                       # 10 MB/s for 2 s, a chunk each 0.1 s
    p.downloaded_bytes = t * MB
    p.record(now=t / 10)
speed, left, stalled = p.rate(now=2.0)
check('a steady 10 MB/s reads as that, with the time left from it',
      [round(speed / MB, 1), round(left), stalled], [10.0, 8, False])
for t in range(21, 71):                      # then 2 MB/s for 25 s: a chunk each 0.5 s
    p.downloaded_bytes = 20 * MB + (t - 20) * MB
    p.record(now=2.0 + (t - 20) * 0.5)
check('after a slowdown, the last 5 seconds decide - not the start',
      round(p.rate(now=27.0)[0] / MB, 1), 2.0)
real_clock, ds._clock = ds._clock, (lambda: 27.0)
sent = p.to_dict()
ds._clock = real_clock
check('and the page is sent it, in whole bytes a second and seconds',
      [sent['speed_bps'], sent['eta_seconds'], sent['stalled']], [2 * MB, round(30 * MB / (2 * MB)), False])
check('nothing for 5 seconds is stalled: no speed, no time left', p.rate(now=32.5), (None, None, True))
p.restart_rate()
p.downloaded_bytes = 0
p.record(now=40.0)
check('a retry starts the measure afresh', p.rate(now=40.5), (None, None, False))
check('and no data at all for 5 seconds is stalled too', p.rate(now=45.0), (None, None, True))
for status in ('pending', 'finishing', 'complete', 'error', 'cancelled'):
    p.status = status
    check(f'{status}: no speed at all', p.rate(now=40.5), (None, None, False))


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
check('a known type has a folder', service.get_base_path('LORA'), os.path.join(MODELS, 'Lora'))
check('an unknown type goes to Other', service.get_base_path('Nonsense'), os.path.join(MODELS, 'Other'))

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

# The WebUIs name these folders too; a download used to ignore both options.
UPSCALERS = os.path.join(WORK, 'upscalers')
CONTROLNETS = os.path.join(WORK, 'controlnets')
os.makedirs(UPSCALERS)
os.makedirs(CONTROLNETS)
cmd_opts.esrgan_models_path = UPSCALERS
cmd_opts.controlnet_dirs = [CONTROLNETS]
check('an upscaler goes where --esrgan-models-path says',
      service.get_base_path('Upscaler'), UPSCALERS)
check('a ControlNet where Neo\'s --controlnet-dirs says',
      service.get_base_path('Controlnet'), CONTROLNETS)
cmd_opts.esrgan_models_path = None
cmd_opts.controlnet_dirs = None

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
    """A reply: its chunks - a callable among them runs between two, say to pause - and its status."""
    def __init__(self, chunks=(), total=None, error=None, status_code=200):
        self.chunks = list(chunks)
        self.error = error
        self.status_code = status_code
        size = total if total is not None else sum(len(c) for c in self.chunks if not callable(c))
        self.headers = {'content-length': str(size)}

    def raise_for_status(self):
        if self.error:
            raise self.error

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size=None):
        for chunk in self.chunks:
            if callable(chunk):
                chunk()
            else:
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
handed = []


def fake_sync(path, progress=None, known=None):
    synced.append(path)
    handed.append((known, progress.status if progress else None, progress.synced if progress else None))


service._sync_downloaded_file = fake_sync

civitai_says(FakeResponse([b'weights']))
progress = service.download_version(500, CHECKPOINT, version())
check('the download completes', progress.status, 'complete')
check('landing in the checkpoint directory',
      os.path.dirname(progress.file_path), CKPT_DIR)
check('under the name Civitai gave it',
      os.path.basename(progress.file_path), 'model.safetensors')
check('and it was handed to the database', synced, [progress.file_path])
check('while it was, the download said finishing, not complete',
      handed[-1][1:], ('finishing', False))
check('and complete and synced arrive together, after it', (progress.status, progress.synced),
      ('complete', True))
check('with no Civitai hash to trust, the sync is told nothing: it hashes the file itself',
      handed[-1][0], None)

info = os.path.splitext(progress.file_path)[0] + '.civitai.info'
written = json.loads(io.open(info, encoding='utf-8').read())
check('a sidecar is written beside it', written['id'], 42)
check('with the model id repeated where other extensions look',
      written['modelId'], 42)
check('the type', written['type'], 'Checkpoint')
check('and the one version that was fetched',
      [v['id'] for v in written['modelVersions']], [500])
# Written through storage.py now (#64): the same sidecar, byte for byte.
check('the sidecar is exactly as it was written before',
      io.open(info, encoding='utf-8').read(),
      json.dumps({'id': 42, 'modelId': 42, 'name': 'Subject', 'description': '<p>d</p>',
                  'type': 'Checkpoint', 'nsfw': False, 'nsfwLevel': 1, 'tags': ['t'],
                  'creator': {'username': 'someone'}, 'stats': {'downloadCount': 3},
                  'modelVersions': [version()]}, indent=2))

# the same file again
civitai_says(FakeResponse([b'weights']))

# ------------------------------------------------ hashed while downloading
# After a download, the library sync read the whole file again to hash it -
# 10 s for a 7 GB checkpoint - while the Civitai Browser showed the download
# as finished but without its "Show in MM". Civitai lists the file's hashes;
# the download hashes the bytes as they arrive and, when its SHA-256 is
# Civitai's, hands Civitai's list to the sync with the version and model.
import hashlib                                           # noqa: E402
BODY = b'hashed weights'
SHA = hashlib.sha256(BODY).hexdigest().upper()


def hashed(version_id, sha256):
    return version(id=version_id, files=[{
        'id': 9, 'name': 'hashed_%d.safetensors' % version_id, 'primary': True,
        'downloadUrl': 'https://example.invalid/h',
        'hashes': {'SHA256': sha256, 'AutoV2': sha256[:10], 'BLAKE3': 'B' * 64, 'CRC32': 'C' * 8}}])


civitai_says(FakeResponse([BODY[:6], BODY[6:]]))
del synced[:]
good = service.download_version(510, CHECKPOINT, hashed(510, SHA))
known = handed[-1][0] or {}
check('the file is hashed as it is written, in pieces', good.sha256, SHA)
check('and matching Civitai, its list is what the sync is given',
      [getattr(known.get('hashes'), 'sha256', None), getattr(known.get('hashes'), 'blake3', None),
       getattr(known.get('hashes'), 'crc32', None)], [SHA, 'B' * 64, 'C' * 8])
check('with the version and the model the download had',
      [(known.get('version') or {}).get('id'), (known.get('model') or {}).get('id')], [510, 42])
check('and it completes', (good.status, good.synced), ('complete', True))

civitai_says(FakeResponse([BODY]))
del synced[:]
bad = service.download_version(511, CHECKPOINT, hashed(511, 'F' * 64))
check('a file whose SHA-256 is not Civitai\'s is corrupt: an error, not a model',
      (bad.status, 'SHA-256' in (bad.error or '')), ('error', True))
check('removed', os.path.exists(os.path.join(CKPT_DIR, 'hashed_511.safetensors')), False)
check('and never added to the library', synced, [])
again = service.download_version(500, CHECKPOINT, version())
check('downloading it twice is refused', again.status, 'error')
check('saying why', 'already exists' in (again.error or ''), True)
check('and points at what is already there', again.file_path, progress.file_path)
os.remove(progress.file_path)
os.remove(info)

# ------------------------------------------------ already on disk
# A file already where the download would put it - downloaded before, and
# forgotten by a scan that never looked in its folder - is the one Civitai
# lists if its SHA-256 is Civitai's: added to the library, not fetched again.
# One with other bytes under that name is refused, and said to be another.
import contextlib                                        # noqa: E402
fetched = []
civitai_says(FakeResponse([b'never sent']))
real_download_file = service._download_file
service._download_file = lambda *a, **k: fetched.append(a) or real_download_file(*a, **k)
del synced[:]
there = service.download_version(510, CHECKPOINT, hashed(510, SHA))
check('a file already there with Civitai\'s SHA-256 is added to the library',
      (there.status, there.synced, synced), ('complete', True, [good.file_path]))
check('without downloading it again', fetched, [])
check('the sync is given Civitai\'s hashes, as after a download',
      getattr((handed[-1][0] or {}).get('hashes'), 'sha256', None), SHA)

other = os.path.join(CKPT_DIR, 'hashed_512.safetensors')
io.open(other, 'wb').write(b'some other weights')
said = io.StringIO()
with contextlib.redirect_stdout(said):
    clash = service.download_version(512, CHECKPOINT, hashed(512, SHA))
check('one with other bytes under that name is refused, and said to be a different file',
      (clash.status, (clash.error or '').startswith('A different file named hashed_512.safetensors')),
      ('error', True))
check('and left alone', io.open(other, 'rb').read(), b'some other weights')
check('a failed download is said in the console, with why',
      'Download of hashed_512.safetensors failed: A different file named' in said.getvalue(), True)
service._download_file = real_download_file
os.remove(other)

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
# A paid version (#43) downloads when the API key's account bought it - which
# only Civitai's permissions check says (civitai/ownership.py, faked here).
civitai_says()
paid = service.download_version(502, CHECKPOINT,
                                version(paidAccess={'permanent': True}))
check('with no API key, a paid version is refused, saying a key is what lets a bought one download',
      [paid.status, 'With an API key set' in (paid.error or '')], ['error', True])
check('and where it is on Civitai', paid.page_url, 'https://civitai.com/models/42?modelVersionId=502')

opts.model_manager_civitai_api_key = 'test-key'
asked_owned = []
real_owned = ds.owned_versions
def owned_says(answer):
    def owned(ids):
        asked_owned.append(list(ids))
        return answer
    ds.owned_versions = owned
owned_says({503: False})
early = service.download_version(503, CHECKPOINT,
                                 version(earlyAccessDeadline='2026-12-01T00:00:00Z'))
check('with a key, one the account has not bought is refused, with its date, before downloading',
      ['2026-12-01T00:00:00Z' in (early.error or ''), 'has not bought it' in (early.error or ''), asked_owned],
      [True, True, [[503]]])
check('neither of them asked Civitai for the file', len(FakeSession.asked), 0)

owned_says({509: True})
civitai_says(FakeResponse([b'bought weights']))
bought = service.download_version(509, CHECKPOINT, version(id=509, paidAccess={'permanent': True}))
check('one the account bought downloads like any other', [bought.status, len(FakeSession.asked)], ['complete', 1])
os.remove(bought.file_path)
os.remove(os.path.splitext(bought.file_path)[0] + '.civitai.info')

owned_says(None)
civitai_says(FakeResponse(error=http_error(403, '{"error":"Early Access","message":"This asset is in Early Access."}')))
unknown = service.download_version(513, CHECKPOINT, version(id=513, paidAccess={'permanent': True}))
check('one Civitai could not say of is tried; refused, Civitai\'s own reason is said, and its page given',
      [unknown.status, unknown.error, unknown.page_url],
      ['error', 'Civitai refused the download: This asset is in Early Access.',
       'https://civitai.com/models/42?modelVersionId=513'])
ds.owned_versions = real_owned
opts.model_manager_civitai_api_key = ''

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

# A key pasted with a space or a newline worked for the API, which trims it,
# and went into the download's header as pasted.
opts.model_manager_civitai_api_key = '  secret-key \n'
civitai_says(FakeResponse([b'weights']))
padded = service.download_version(510, CHECKPOINT, version(id=510))
check('a key pasted with spaces around it is sent trimmed',
      FakeSession.asked[0][1].get('Authorization'), 'Bearer secret-key')
os.remove(padded.file_path)
os.remove(os.path.splitext(padded.file_path)[0] + '.civitai.info')

opts.model_manager_civitai_api_key = '   '
civitai_says(FakeResponse([b'weights']))
blank = service.download_version(511, CHECKPOINT, version(id=511))
check('and a key of spaces alone is no key',
      'Authorization' in FakeSession.asked[0][1], False)
os.remove(blank.file_path)
os.remove(os.path.splitext(blank.file_path)[0] + '.civitai.info')

opts.model_manager_civitai_api_key = ''
civitai_says(FakeResponse([b'weights']))
anonymous = service.download_version(509, CHECKPOINT, version(id=509))
check('and without one, no header at all',
      'Authorization' in FakeSession.asked[0][1], False)
os.remove(anonymous.file_path)
os.remove(os.path.splitext(anonymous.file_path)[0] + '.civitai.info')

# ------------------------------------------------------------------ the queue (#37)
# The service's own: up to max_concurrent running, the rest waiting in order.
# A waiting one can be started at once - over the limit, which only paces the
# queue - moved up or down, paused, or cancelled before it starts.
import threading                                         # noqa: E402
queued = []
gates = {}


class Queueing(DownloadService):
    """Each download runs until its gate opens."""
    def download_version(self, version_id, model_data, version_data,
                         file_index=None, file_id=None, resume=False):
        queued.append((version_id, file_index, file_id, resume))
        progress = self._active_downloads[version_id]
        progress.status = 'downloading'
        gates.setdefault(version_id, threading.Event()).wait(5)
        # As the chunk loop does: asked to pause, it stops paused.
        progress.status = 'paused' if self._is_paused(version_id) else 'complete'
        return progress


def release(*ids):
    for version_id in ids:
        gates.setdefault(version_id, threading.Event()).set()


def settle():
    time.sleep(0.05)


def states(q):
    return {p['version_id']: (p['status'], p.get('queue_position')) for p in q.get_all_progress()}


queue = Queueing(max_concurrent=2)
handle = queue.queue_download(600, CHECKPOINT, version(id=600), file_id=1)
check('the queued download is named before it starts', handle.file_name, 'model.safetensors')
check('and is visible to the poller straight away', queue.get_progress(600) is handle, True)
nameless = queue.queue_download(601, CHECKPOINT, version(id=601, files=[]))
check('a version with no files is still queued', nameless.file_name, 'Unknown')
queue.queue_download(602, CHECKPOINT, version(id=602))
queue.queue_download(603, CHECKPOINT, version(id=603))
settle()
check('two run, the rest wait, each with its place', states(queue),
      {600: ('downloading', None), 601: ('downloading', None), 602: ('pending', 1), 603: ('pending', 2)})
order = lambda q: [p['version_id'] for p in q.get_all_progress()]         # noqa: E731
check('moved up, a waiting one changes places, in the list too',
      [queue.move(603, -1), states(queue)[603], states(queue)[602], order(queue)],
      [True, ('pending', 1), ('pending', 2), [600, 601, 603, 602]])
check('not past the top', queue.move(603, -1), False)
check('a running one is not in the queue to move', queue.move(600, 1), False)
check('started now, it runs at once, over the limit - and keeps its row',
      [queue.start_now(602), settle(), states(queue)[602], order(queue)],
      [True, None, ('downloading', None), [600, 601, 603, 602]])
queue.cancel(603)
check('a waiting one cancelled never starts, and keeps its row until dismissed',
      [states(queue)[603], queue._waiting(), order(queue)], [('cancelled', None), [], [600, 601, 603, 602]])
queue.queue_download(604, CHECKPOINT, version(id=604))
queue.queue_download(605, CHECKPOINT, version(id=605))
check('paused while waiting, it is not waiting, and keeps its row',
      [queue.pause(605), states(queue)[605], queue._waiting(), order(queue)[-2:]],
      [True, ('paused', None), [604], [604, 605]])
check('resumed, it waits where its row is - behind one above it, not at the front',
      [queue.resume(605), states(queue)[604], states(queue)[605], order(queue)[-2:]],
      [True, ('pending', 1), ('pending', 2), [604, 605]])
release(600, 601, 602)
for _ in range(100):
    if states(queue)[605][0] == 'downloading':
        break
    settle()
# Two places free at once, so both start; which thread records itself first
# is the scheduler's (it failed 1 run in 20 when this asserted 605 last).
check('when places free up, they start from the top - the resumed one told it is resuming',
      [states(queue)[604], states(queue)[605], [q[3] for q in queued if q[0] == 605]],
      [('downloading', None), ('downloading', None), [True]])
release(605)
release(604)
queue.wait()
check('each ran with its own file', sorted(q[:3] for q in queued),
      [(600, None, 1), (601, None, None), (602, None, None), (604, None, None), (605, None, None)])

# Pause all holds the waiting ones too, so none starts in the places it frees.
queue.queue_download(610, CHECKPOINT, version(id=610))
queue.queue_download(611, CHECKPOINT, version(id=611))
queue.queue_download(612, CHECKPOINT, version(id=612))
settle()
queue.pause_all()
check('Pause all: the running ones asked to pause, the waiting one paused',
      [queue._is_paused(610), queue._is_paused(611), states(queue)[612]], [True, True, ('paused', None)])
release(610, 611)
queue.wait()
gates.update({610: threading.Event(), 611: threading.Event()})     # to run again, until let go
queue.resume_all()
settle()
check('Resume all: the top two run, the third waits - and no row moved',
      [states(queue)[610][0], states(queue)[611][0], states(queue)[612]], ['downloading', 'downloading', ('pending', 1)])
release(610, 611, 612)
queue.wait()



# ------------------------------------------------- syncing what was downloaded
class Result:
    def __init__(self, success, error=None):
        self.success = success
        self.error = error


class FakeSync:
    result = Result(True)

    def sync_model(self, file_path, force=False, known=None):
        FakeSync.asked = (file_path, force)
        FakeSync.known = known
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


def sync_now(path, known=None):
    # It runs in the download's own thread now, and is done when it returns.
    progress = DownloadProgress(version_id=1)
    real._sync_downloaded_file(path, progress, known)
    return progress


done = sync_now('/models/x.safetensors', known={'hashes': 'h', 'version': {}})
check('a downloaded file is synced', FakeSync.asked, ('/models/x.safetensors', True))
check('with what the download knew', FakeSync.known, {'hashes': 'h', 'version': {}})
check('with no complaint', done.sync_error, None)
check('and the download is dated', stamped, ['/models/x.safetensors'])

FakeSync.result = Result(False, 'not on Civitai')
done = sync_now('/models/y.safetensors')
check('a sync that fails says why', done.sync_error, 'not on Civitai')

FakeSync.result = RuntimeError('database is locked')
done = sync_now('/models/z.safetensors')
check('and one that raises does not escape', done.sync_error, 'database is locked')

FakeSync.result = Result(True)
real._sync_downloaded_file('/models/w.safetensors')
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

# ---------------------------------------------------------------- .partial
# A download is written as <name>.partial and renamed once whole and its
# SHA-256 checked: a download that fails never leaves a file under the
# model's own name, and what it removes is only ever its own .partial.
del synced[:]
written_to = []
real_download_file = service._download_file
def watched_download_file(url, path, *rest):
    written_to.append(path)
    return real_download_file(url, path, *rest)
service._download_file = watched_download_file

name = 'partial_%d.safetensors'
def partial_version(version_id, sha=SHA):
    return version(id=version_id, files=[{'id': 9, 'name': name % version_id, 'primary': True,
                                          'downloadUrl': 'https://example.invalid/p',
                                          'hashes': {'SHA256': sha}}])

civitai_says(FakeResponse([BODY]))
done_ = service.download_version(520, CHECKPOINT, partial_version(520))
final = os.path.join(CKPT_DIR, name % 520)
check('the download is written as .partial', written_to[-1], final + '.partial')
check('and ends under its own name, with no .partial left',
      [done_.status, os.path.exists(final), os.path.exists(final + '.partial')], ['complete', True, False])

left = os.path.join(CKPT_DIR, name % 521) + '.partial'
io.open(left, 'wb').write(b'the start of a download the WebUI was closed in the middle of')
civitai_says(FakeResponse([BODY]))
again_ = service.download_version(521, CHECKPOINT, partial_version(521))
check('a .partial left by a download cut short is written over, and the download finishes',
      [again_.status, io.open(os.path.join(CKPT_DIR, name % 521), 'rb').read(), os.path.exists(left)],
      ['complete', BODY, False])

arrived = os.path.join(CKPT_DIR, name % 522)
def arriving(url, path, *rest):
    ok = real_download_file(url, path, *rest)
    io.open(arrived, 'wb').write(b'put there by someone else meanwhile')
    return ok
service._download_file = arriving
civitai_says(FakeResponse([BODY]))
raced = service.download_version(522, CHECKPOINT, partial_version(522))
check('a file that appears under the name meanwhile is not replaced',
      [raced.status, (raced.error or '').startswith('A file named %s appeared' % (name % 522)),
       io.open(arrived, 'rb').read()], ['error', True, b'put there by someone else meanwhile'])
check('and the download\'s own .partial is removed', os.path.exists(arrived + '.partial'), False)

service._download_file = watched_download_file
civitai_says(FakeResponse([BODY]))
wrong = service.download_version(523, CHECKPOINT, partial_version(523, 'F' * 64))
check('a download whose SHA-256 is not Civitai\'s leaves nothing: no file, no .partial',
      [wrong.status, os.path.exists(os.path.join(CKPT_DIR, name % 523)),
       os.path.exists(os.path.join(CKPT_DIR, name % 523) + '.partial')], ['error', False, False])
service._download_file = real_download_file

# ---------------------------------------------------- pause and resume (#38)
# Paused, a download keeps its .partial and is kept in the database (here,
# `kept`) to be resumed after a restart. Resumed, the rest is asked for with a
# Range request - Civitai answers 206 - and added to the file, the hash
# continued from what was there. A server that sends the whole file instead
# is taken from the start.
FULL = b'first part|second part|third part'
FULL_SHA = hashlib.sha256(FULL).hexdigest().upper()


def pause_it(version_id):
    return lambda: service._pause_flags.__setitem__(version_id, True)


kept['value'] = None
civitai_says(FakeResponse([FULL[:11], pause_it(530), FULL[11:]], total=len(FULL)))
paused = service.download_version(530, CHECKPOINT, hashed(530, FULL_SHA))
partial = os.path.join(CKPT_DIR, 'hashed_530.safetensors.partial')
saved = json.loads(kept['value'] or '[]')
check('paused mid-download, it stops, says so, and keeps what it had',
      [paused.status, io.open(partial, 'rb').read(), os.path.exists(partial[:-len('.partial')])],
      ['paused', FULL[:11], False])
check('kept to resume after a restart: which version, model and file, and where its .partial is',
      [(e['version_id'], e['model_id'], e['partial_path'], e['total_bytes']) for e in saved],
      [(530, 42, partial, len(FULL))])
civitai_says(FakeResponse([FULL[11:]], status_code=206))
resumed = service.download_version(530, CHECKPOINT, hashed(530, FULL_SHA), resume=True)
check('resumed, only the rest is asked for', FakeSession.asked[0][1].get('Range'), 'bytes=11-')
check('and added on: the whole file, its hash Civitai\'s, complete',
      [resumed.status, io.open(resumed.file_path, 'rb').read(), resumed.sha256, resumed.started_over],
      ['complete', FULL, FULL_SHA, False])
check('and no longer kept to resume', kept['value'], None)
check('the progress the page followed is the same one throughout', resumed is paused, True)

# Civitai's storage now and then ignores the range - with an API key, 1 of 8
# resumes in one measurement - and a fresh request is answered: asked again,
# up to three times, before starting over.
civitai_says(FakeResponse([FULL[:11], pause_it(532), FULL[11:]], total=len(FULL)))
service.download_version(532, CHECKPOINT, hashed(532, FULL_SHA))
ignored = FakeResponse([FULL], status_code=200)
civitai_says(ignored, FakeResponse([FULL[11:]], status_code=206))
again = service.download_version(532, CHECKPOINT, hashed(532, FULL_SHA), resume=True)
check('a whole file once, then the rest: asked again for the rest, and resumed - not started over',
      [[a[1].get('Range') for a in FakeSession.asked], getattr(ignored, 'closed', False), again.started_over,
       io.open(again.file_path, 'rb').read()], [['bytes=11-', 'bytes=11-'], True, False, FULL])

civitai_says(FakeResponse([FULL[:11], pause_it(531), FULL[11:]], total=len(FULL)))
service.download_version(531, CHECKPOINT, hashed(531, FULL_SHA))
civitai_says(*[FakeResponse([FULL], status_code=200) for _ in range(3)])
over = service.download_version(531, CHECKPOINT, hashed(531, FULL_SHA), resume=True)
check('a server that sends the whole file every time: taken from the start, and said so',
      [len(FakeSession.asked), over.status, io.open(over.file_path, 'rb').read(), over.started_over],
      [3, 'complete', FULL, True])

# After a restart: what was kept comes back paused - one that was running
# when the WebUI stopped too - and one whose .partial is gone is forgotten.
left = os.path.join(CKPT_DIR, 'left_behind.safetensors.partial')
io.open(left, 'wb').write(b'12345')
kept['value'] = json.dumps([
    {'version_id': 540, 'model_id': 42, 'file_id': 9, 'file_index': None, 'file_name': 'left_behind.safetensors',
     'partial_path': left, 'total_bytes': 50},
    {'version_id': 541, 'model_id': 42, 'file_id': 9, 'file_index': None, 'file_name': 'gone.safetensors',
     'partial_path': os.path.join(CKPT_DIR, 'gone.safetensors.partial'), 'total_bytes': 50}])
restarted = DownloadService(max_concurrent=2)
restarted.restore()
check('after a restart, a kept download is back, paused, as far as its .partial got',
      [(p['version_id'], p['status'], p['downloaded_bytes'], p['total_bytes']) for p in restarted.get_all_progress()],
      [(540, 'paused', 5, 50)])
check('and one whose .partial is gone is forgotten', [e['version_id'] for e in json.loads(kept['value'])], [540])
check('it knows its ids only, to fetch from Civitai when resumed',
      {k: restarted._jobs[540].get(k) for k in ('model_id', 'file_id', 'version_data')},
      {'model_id': 42, 'file_id': 9, 'version_data': None})
restarted.cancel(540)
check('cancelled while paused, it goes, its .partial with it',
      [restarted.get_progress(540).status, os.path.exists(left), kept['value']], ['cancelled', False, None])

leftovers = [os.path.join(root, f) for root, _, files in os.walk(MODELS) for f in files if f.endswith('.partial')]
check('after every download here, failed ones included, no .partial is left anywhere', leftovers, [])

# ------------------------------------------------- filed by what it is (#54)
# The folder is chosen before the file exists, from Civitai's type - the
# uploader's: a VAE shared as a "Checkpoint" landed in Stable-diffusion, where
# Forge offers it as a checkpoint. Read once it has arrived, it goes where a
# VAE goes. The header is stood in for: the bytes here are no model.
import model_manager.file_identity as file_identity      # noqa: E402
from model_manager.architecture import Architecture      # noqa: E402
real_identify = file_identity.identify
file_identity.identify = lambda path, *a, **k: Architecture(None, None, False, False, 'VAE', 'the test')
VAE_DIR = os.path.join(MODELS, 'VAE')
in_vae = os.path.join(VAE_DIR, 'model.safetensors')
in_ckpt = os.path.join(CKPT_DIR, 'model.safetensors')


def clear():
    for path in (in_vae, in_ckpt):
        for p in [path] + [os.path.splitext(path)[0] + '.civitai.info']:
            if os.path.exists(p):
                os.remove(p)


clear()
civitai_says(FakeResponse([b'weights']))
filed = service.download_version(530, CHECKPOINT, version(id=530))
check('a VAE listed under a Checkpoint model is filed in VAE',
      (filed.status, filed.file_path, os.path.exists(in_vae), os.path.exists(in_ckpt)),
      ('complete', in_vae, True, False))
check('with its .civitai.info beside it', os.path.exists(os.path.splitext(in_vae)[0] + '.civitai.info'), True)
check('added to the library where it is', synced[-1], in_vae)
check('and the download says where it went, and why', (getattr(filed, 'filed', None) or '').startswith('Filed in'), True)

# The same file already in its folder: this copy - made moments ago - goes,
# and the one there is the one the library adds.
clear()
os.makedirs(VAE_DIR, exist_ok=True)
io.open(in_vae, 'wb').write(b'weights')
civitai_says(FakeResponse([b'weights']))
twin = service.download_version(531, CHECKPOINT, version(id=531))
check('the same file already in VAE: this copy goes, that one is added',
      (twin.status, twin.file_path, os.path.exists(in_ckpt), open(in_vae, 'rb').read()),
      ('complete', in_vae, False, b'weights'))
check('saying so', (getattr(twin, 'filed', None) or '').startswith('Already in'), True)

# A different file of that name: nothing is written over; this one stays
# where it landed, and says why.
clear()
io.open(in_vae, 'wb').write(b'someone else')
civitai_says(FakeResponse([b'weights']))
namesake = service.download_version(532, CHECKPOINT, version(id=532))
check('a different file of that name in VAE: left alone, and the download stays where it landed',
      (namesake.status, namesake.file_path, open(in_vae, 'rb').read()),
      ('complete', in_ckpt, b'someone else'))
check('saying why', (getattr(namesake, 'filed', None) or '').startswith('Left in'), True)

# What the file cannot say about itself keeps Civitai's folder.
clear()
file_identity.identify = lambda path, *a, **k: Architecture(None, None, False, False, 'Unknown', '')
civitai_says(FakeResponse([b'weights']))
unread = service.download_version(533, CHECKPOINT, version(id=533))
check('a file of unknown type stays in Civitai\'s folder', (unread.file_path, getattr(unread, 'filed', None)), (in_ckpt, None))
clear()
file_identity.identify = real_identify

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
