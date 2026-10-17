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

# A failure naming the settings' ⚙ crashed the report on Windows' console
# (cp1252), and hid which check had failed.
sys.stdout.reconfigure(errors='backslashreplace')

import webui_stub                                       # noqa: E402

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


# What comes back after a restart is kept here, never in a database
# (DownloadService.store): this install's rows, in the list's order.
kept = {'rows': []}
DownloadService.store = (lambda: [dict(row) for row in kept['rows']],
                         lambda rows: kept.__setitem__('rows', [dict(row) for row in rows]))
# The library's files of a Civitai file, by its id - none unless a check puts
# some here (DownloadService.library).
in_library = {}
DownloadService.library = lambda file_id: list(in_library.get(file_id, []))

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
pick = ds.pick_file_index
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

check('no template, no subfolder', ds.apply_folder_template('', MODEL, VERSION), '')
check('the placeholders are filled and made safe',
      ds.apply_folder_template('{baseModel}/{modelName}', MODEL, VERSION),
      os.path.join('SDXL_1.0', 'A_Model_Mk_2'))
check('the creator too',
      ds.apply_folder_template('{creator}', MODEL, VERSION), 'some_one')
check('and the id, which needs no sanitising',
      ds.apply_folder_template('{modelId}', MODEL, VERSION), '42')
check('a model with no creator still lands somewhere',
      ds.apply_folder_template('{creator}', {'id': 1, 'name': 'n'}, VERSION),
      'Unknown')
check('and one with no base model',
      ds.apply_folder_template('{baseModel}', MODEL, {}), 'Unknown')
check('backslashes and doubled slashes collapse',
      ds.apply_folder_template('a\\\\b//c/', MODEL, VERSION),
      os.path.join('a', 'b', 'c'))
long_name = ds.apply_folder_template('{modelName}', {'name': 'x' * 300}, VERSION)
check('an absurd name is cut to something a filesystem will take',
      len(long_name), 100)

# ------------------------------------------------- the folders a download made
# What a delete may remove once they are empty (#196): the template's folders
# for this model, and only while the file sits in them. A name-match against
# the file's own name never matched a folder the template made.
DEFAULT_TEMPLATE = '_{baseModel}/{modelName}'
TYPE_DIR = os.path.join(WORK, 'Lora')
STORED_MODEL = {'id': 42, 'name': 'A Model: Mk/2', 'creator_username': 'some one'}
STORED_VERSION = {'model_id': 42, 'base_model': 'SDXL 1.0'}
MADE = os.path.join(TYPE_DIR, '_SDXL_1.0', 'A_Model_Mk_2')


def made_folders(path, root=TYPE_DIR, model=STORED_MODEL, version=STORED_VERSION,
                 template=DEFAULT_TEMPLATE):
    find = getattr(ds, 'template_folders', None)
    return find(path, root, model, version, template) if find else 'no template_folders'


check('a download by the template made both its folders, deepest first',
      made_folders(os.path.join(MADE, 'x.safetensors')),
      [MADE, os.path.join(TYPE_DIR, '_SDXL_1.0')])
check('spelt another way on disk, they are still its own, as spelt there',
      made_folders(os.path.join(TYPE_DIR, '_sdxl_1.0', 'a_model_mk_2', 'x.safetensors')),
      [os.path.join(TYPE_DIR, '_sdxl_1.0', 'a_model_mk_2'), os.path.join(TYPE_DIR, '_sdxl_1.0')])
check('another template would have put it elsewhere: none are ours',
      made_folders(os.path.join(MADE, 'x.safetensors'), template='{creator}'), [])
check('with no template, a download makes no folder',
      made_folders(os.path.join(MADE, 'x.safetensors'), template=''), [])
check('a file with no model cannot be matched',
      made_folders(os.path.join(MADE, 'x.safetensors'), model=None), [])
check('a file in the type\'s own folder has none',
      made_folders(os.path.join(TYPE_DIR, 'x.safetensors')), [])
check('the template\'s folders under another folder are not the template\'s',
      made_folders(os.path.join(TYPE_DIR, 'mine', '_SDXL_1.0', 'A_Model_Mk_2', 'x.safetensors')), [])
check('a file outside every type\'s folder has none',
      made_folders(os.path.join(MADE, 'x.safetensors'), root=None), [])
check('a model renamed since is no longer matched',
      made_folders(os.path.join(MADE, 'x.safetensors'), model=dict(STORED_MODEL, name='Renamed')), [])
check('the creator and the id fill in as a download fills them',
      made_folders(os.path.join(TYPE_DIR, 'some_one', '42', 'x.safetensors'),
                   template='{creator}/{modelId}'),
      [os.path.join(TYPE_DIR, 'some_one', '42'), os.path.join(TYPE_DIR, 'some_one')])
check('a base model never stored reads as a download without one did',
      made_folders(os.path.join(TYPE_DIR, '_Unknown', 'A_Model_Mk_2', 'x.safetensors'),
                   version={'model_id': 42, 'base_model': None}),
      [os.path.join(TYPE_DIR, '_Unknown', 'A_Model_Mk_2'), os.path.join(TYPE_DIR, '_Unknown')])

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

# Civitai says why it refused (#224): a creator who turned downloads off, a
# login it asks for. Only the login is a key's to fix, and only with none set.
DISABLED = '{"error":"Unauthorized","message":"The creator of this asset has disabled downloads on this file"}'
LOGIN = '{"error":"Unauthorized","message":"The creator of this asset requires you to be logged in to download it"}'
ok, progress = download(FakeResponse(error=http_error(401, DISABLED)))
check("a 401 for downloads turned off says Civitai's words, and nothing of a key", progress.error,
      'Civitai refused the download: The creator of this asset has disabled downloads on this file')
check('without retrying', len(FakeSession.asked), 1)

ok, progress = download(FakeResponse(error=http_error(401, LOGIN)))
check('one asking for a login, with no key set, says so, and where a key goes', progress.error,
      'Civitai refused the download: The creator of this asset requires you to be logged in to download it. '
      'An API key logs you in. Add one in the settings (⚙ at the top right of the Model Manager or '
      'Civitai Browser tab), under Civitai connection.')

opts.model_manager_civitai_api_key = 'test-key'
ok, progress = download(FakeResponse(error=http_error(401, LOGIN)))
check("with a key set, Civitai's words alone: the key was sent", progress.error,
      'Civitai refused the download: The creator of this asset requires you to be logged in to download it')
ok, progress = download(FakeResponse(error=http_error(401)))
check('and one that says nothing, with a key set, does not blame a missing key', progress.error,
      'Civitai refused the download (HTTP 401) without saying why.')
opts.model_manager_civitai_api_key = ''

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
# Each by the id of the file chosen when it was queued - Civitai's primary,
# unless one was asked for - so a list fetched again after a restart, in
# another order, picks the same file (#187). A version with no files has none.
check('each ran with its own file', sorted(q[:3] for q in queued),
      [(600, None, 1), (601, None, None), (602, None, 1), (604, None, 1), (605, None, 1)])

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

# Asked again for a version on its way - the Resources dialog asking for one
# the Civitai Browser started, or for a gone version whose newest is already
# coming - the queue answers what it has (#119). It used to drop the row and
# queue it afresh, so a running download started over.
again = Queueing(max_concurrent=1)
running = again.queue_download(620, CHECKPOINT, version(id=620))
waiting = again.queue_download(621, CHECKPOINT, version(id=621))
held = again.queue_download(622, CHECKPOINT, version(id=622))
settle()
again.pause(622)
check('asked again for one running, waiting or paused, the queue answers the download it has',
      [again.queue_download(620, CHECKPOINT, version(id=620)) is running,
       again.queue_download(621, CHECKPOINT, version(id=621)) is waiting,
       again.queue_download(622, CHECKPOINT, version(id=622)) is held],
      [True, True, True])
check('nothing started over or moved: one run of the running one, the rows in their order, the paused one paused',
      [[q[0] for q in queued].count(620), order(again), states(again)[621], states(again)[622]],
      [1, [620, 621, 622], ('pending', 1), ('paused', None)])
release(620, 621)
again.wait()
afresh = again.queue_download(620, CHECKPOINT, version(id=620))
again.cancel(622)
again.wait()
check('a finished one asked again is queued afresh, and runs again',
      [afresh is running, [q[0] for q in queued].count(620)], [False, 2])



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
pruned = []
db_module.get_models_db = lambda: types.SimpleNamespace(
    set_downloaded_at=lambda path: stamped.append(path),
    prune_orphans=lambda: (pruned.append(True), (0, 0))[1])

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
check('and what no file names any more is cleared, once (#200)', pruned, [True])

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

# Asked for by two requests at once - the page's first poll on the event loop,
# a Download on a worker thread - it could be made twice, each with its own
# queue; and it was handed out before it had restored what was paused (#68).
made_once = ds._download_service
real_init, real_restore = DownloadService.__init__, DownloadService.restore
restored, built = set(), []


def slow_init(self, *args, **kwargs):
    built.append(1)
    time.sleep(0.05)
    real_init(self, *args, **kwargs)


def slow_restore(self):
    time.sleep(0.1)
    real_restore(self)
    restored.add(id(self))


got, ready = [], threading.Barrier(8)


def ask_for_it():
    ready.wait(5)
    asked = get_download_service()
    got.append((id(asked), id(asked) in restored))


DownloadService.__init__, DownloadService.restore = slow_init, slow_restore
ds._download_service = None
try:
    askers = [threading.Thread(target=ask_for_it) for _ in range(8)]
    for asker in askers:
        asker.start()
    for asker in askers:
        asker.join(5)
finally:
    DownloadService.__init__, DownloadService.restore = real_init, real_restore
    ds._download_service = made_once
check('asked for by eight requests at once, it is made once', (len(built), len({made for made, _ in got})), (1, 1))
check('and handed to none of them before it has restored what was paused',
      [r for _, r in got], [True] * 8)

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


kept['rows'] = []
civitai_says(FakeResponse([FULL[:11], pause_it(530), FULL[11:]], total=len(FULL)))
paused = service.download_version(530, CHECKPOINT, hashed(530, FULL_SHA))
partial = os.path.join(CKPT_DIR, 'hashed_530.safetensors.partial')
saved = kept['rows']
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
check('and no longer kept to resume', kept['rows'], [])
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
kept['rows'] = ([
    {'version_id': 540, 'model_id': 42, 'file_id': 9, 'file_index': None, 'file_name': 'left_behind.safetensors',
     'partial_path': left, 'total_bytes': 50},
    {'version_id': 541, 'model_id': 42, 'file_id': 9, 'file_index': None, 'file_name': 'gone.safetensors',
     'partial_path': os.path.join(CKPT_DIR, 'gone.safetensors.partial'), 'total_bytes': 50}])
restarted = DownloadService(max_concurrent=2)
restarted.restore()
check('after a restart, a kept download is back, paused, as far as its .partial got',
      [(p['version_id'], p['status'], p['downloaded_bytes'], p['total_bytes']) for p in restarted.get_all_progress()],
      [(540, 'paused', 5, 50)])
check('and one whose .partial is gone is forgotten', [e['version_id'] for e in kept['rows']], [540])
check('it knows its ids only, to fetch from Civitai when resumed',
      {k: (restarted._jobs.get(540) or {}).get(k) for k in ('model_id', 'file_id', 'version_data')},
      {'model_id': 42, 'file_id': 9, 'version_data': None})
restarted.cancel(540)
check('cancelled while paused, it goes, its .partial with it',
      [getattr(restarted.get_progress(540), 'status', None), os.path.exists(left), kept['rows']], ['cancelled', False, []])

# --------------------------------------------- the queue across a restart (#187)
# Every download not over is kept - waiting ones too - in the list's order, and
# comes back paused. Only one with a .partial was, and one is named only once
# its thread begins: queue ten, two running, and a restart forgot the other eight.
import model_manager.console as console                  # noqa: E402


def kept_ids():
    return [row['version_id'] for row in kept['rows']]


one_place = Queueing(max_concurrent=1)
one_place.queue_download(660, CHECKPOINT, version(id=660))
one_place.queue_download(661, CHECKPOINT, version(id=661))
check('kept the moment it is queued, before any download has begun', kept_ids(), [660, 661])
release(660, 661)
one_place.wait()


class Begun(DownloadService):
    """As download_version does: running, its .partial named, kept and begun - until let go."""
    def download_version(self, version_id, model_data, version_data,
                         file_index=None, file_id=None, resume=False):
        progress = self._active_downloads[version_id]
        progress.status = 'downloading'
        path = os.path.join(CKPT_DIR, 'begun_%d.safetensors.partial' % version_id)
        io.open(path, 'wb').write(b'123')
        self._jobs[version_id]['partial_path'] = path
        self._save()
        gates.setdefault(version_id, threading.Event()).wait(5)
        progress.status = 'paused'
        return progress


def sized(version_id, file_id, size_kb):
    """A version whose one file Civitai sizes, and names by its own id."""
    return version(id=version_id, files=[{'id': file_id, 'name': 'sized_%d.safetensors' % version_id,
                                          'primary': True, 'sizeKB': size_kb,
                                          'downloadUrl': 'https://example.invalid/s'}])


kept['rows'] = []
before = Begun(max_concurrent=2)
for version_id in (650, 651, 652):
    before.queue_download(version_id, CHECKPOINT, version(id=version_id))
before.queue_download(653, CHECKPOINT, sized(653, 77, 2.0))
settle()
before.move(653, -1)
restarted = DownloadService(max_concurrent=2)
restarted.restore()
check('after a restart, the running ones and the queued ones are back, paused, in their order',
      [(p['version_id'], p['status'], p['downloaded_bytes']) for p in restarted.get_all_progress()],
      [(650, 'paused', 3), (651, 'paused', 3), (653, 'paused', 0), (652, 'paused', 0)])
check('a queued one knows its model, the file chosen and its size, to fetch from Civitai when resumed',
      [{k: (restarted._jobs.get(653) or {}).get(k) for k in ('model_id', 'file_id', 'version_data', 'partial_path')},
       getattr(restarted.get_progress(653), 'total_bytes', None)],
      [{'model_id': 42, 'file_id': 77, 'version_data': None, 'partial_path': None}, 2048])
check('and the restart starts none of them by itself', [restarted._running, restarted._threads], [set(), []])
restarted.cancel(652)
check('cancelled while queued, it is kept no longer', kept_ids(), [650, 651, 653])


def gone_from_civitai(version_id, job):
    restarted._active_downloads[version_id].status = 'error'


restarted._fetch_job = gone_from_civitai
restarted.resume(653)
restarted.wait()
check('resumed, and Civitai no longer listing it, it fails and is kept no longer',
      [getattr(restarted.get_progress(653), 'status', None), kept_ids()], ['error', [650, 651]])
before.cancel(652)
before.cancel(653)
release(650, 651)
before.wait()
for version_id in (650, 651):
    restarted.cancel(version_id)

# Already downloaded - since, by hand, or in the other tab - it is not brought
# back: the library has the very file, on disk, in this WebUI's folders. A row
# whose file is gone, or a file in a folder this WebUI does not load from,
# does not count. Nor does anything for a download with no file id - one
# 0.51.8 kept from the Resources dialog: the version's other file is not it.
ELSEWHERE = os.path.join(WORK, 'elsewhere')
os.makedirs(ELSEWHERE, exist_ok=True)


def on_disk(folder, name):
    path = os.path.join(folder, name)
    io.open(path, 'wb').write(b'weights')
    return path


def row(version_id, file_id, partial=None):
    return {'version_id': version_id, 'model_id': 42, 'file_id': file_id, 'file_index': None,
            'file_name': 'kept_%d.safetensors' % version_id, 'partial_path': partial, 'total_bytes': 0}


here = on_disk(CKPT_DIR, 'held_670.safetensors')
away = on_disk(ELSEWHERE, 'held_672.safetensors')
dropped_partial = on_disk(CKPT_DIR, 'kept_670.safetensors.partial')
kept_partial = on_disk(CKPT_DIR, 'kept_674.safetensors.partial')
no_id_partial = on_disk(CKPT_DIR, 'kept_675.safetensors.partial')
in_library.update({70: [here], 71: [os.path.join(CKPT_DIR, 'deleted.safetensors')], 72: [away], None: [here]})
kept['rows'] = [row(670, 70, dropped_partial), row(671, 71), row(672, 72), row(674, 74, kept_partial),
                row(675, None, no_id_partial)]
said_from = console.said()
restarted = DownloadService(max_concurrent=2)
restarted.restore()
check('at a restart, one whose file the library has is not brought back, and its .partial goes',
      [[p['version_id'] for p in restarted.get_all_progress()], kept_ids(), os.path.exists(dropped_partial)],
      [[671, 672, 674, 675], [671, 672, 674, 675], False])
check('one with no file id comes back, its .partial kept', os.path.exists(no_id_partial), True)
check('the console says which', any('kept_670.safetensors' in line['text'] and 'Already in your library' in line['text']
                                    for line in console.since(said_from)[0]), True)

# Resumed, it is asked again: it may have arrived since the restart.
fetched = []
restarted._fetch_job = lambda version_id, job: fetched.append(version_id)
in_library[74] = [here]
restarted.resume(674)
restarted.wait()
found = restarted.get_progress(674)
check('resumed when the library has it now: complete, that file, nothing fetched, its .partial gone',
      [getattr(found, 'status', None), getattr(found, 'file_path', None), getattr(found, 'filed', None),
       fetched, os.path.exists(kept_partial), kept_ids()],
      ['complete', here, 'Already in your library', [], False, [671, 672, 675]])
# The page follows a complete download until it is synced: in the library.
check('and synced, so the page stops following it', getattr(found, 'synced', None), True)
for version_id in (671, 672, 675):
    restarted.cancel(version_id)
in_library.clear()
for path in (here, away):
    os.remove(path)

# ------------------------------------------------- the library first (#276)
# A download looked only at the path it would file to: a copy moved into a
# subfolder of one's own, or filed by an older template, was fetched again
# beside it, and a file deleted by hand came back somewhere else, a second
# row. The library is asked first, by the Civitai file id, at the download's
# turn - the file may have arrived while it waited.
fetched = []
service._download_file = lambda *a, **k: fetched.append(a[1]) or real_download_file(*a, **k)
templated = os.path.join(CKPT_DIR, 'model.safetensors')


def tidy(*paths):
    for path in paths:
        for p in (path, os.path.splitext(path)[0] + '.civitai.info'):
            if os.path.exists(p):
                os.remove(p)


mine = os.path.join(CKPT_DIR, 'mine')
os.makedirs(mine, exist_ok=True)
moved = on_disk(mine, 'model.safetensors')
in_library[1] = [moved]
del synced[:]
tidy(templated)
civitai_says(FakeResponse([b'weights']))
held =service.download_version(540, CHECKPOINT, version(id=540))
check('a file the library holds in a subfolder of its own is not fetched again: already there',
      (held.status, held.file_path, getattr(held, 'filed', None), held.synced, fetched,
       os.path.exists(templated)),
      ('complete', moved, 'Already in your library', True, [], False))
check('nothing is added to the library: it is there', synced, [])

gone = os.path.join(CKPT_DIR, 'deleted by hand', 'renamed.safetensors')
in_library[1] = [os.path.join(ELSEWHERE, 'model.safetensors'), gone]
tidy(templated)
civitai_says(FakeResponse([b'weights']))
back =service.download_version(541, CHECKPOINT, version(id=541))
check('one the library lists, gone from disk, comes back where it was, under its name there',
      (back.status, back.file_path, open(gone, 'rb').read() if os.path.exists(gone) else None,
       synced[-1] if synced else None, os.path.exists(templated)),
      ('complete', gone, b'weights', gone, False))
check('its folder made again; another WebUI\'s row, not on disk, gives no path',
      (os.path.isdir(os.path.dirname(gone)), fetched[-1] if fetched else None), (True, gone + '.partial'))
tidy(gone)
shutil.rmtree(os.path.dirname(gone), ignore_errors=True)

in_library[1] = [gone, moved]
fetched = []
service._download_file = lambda *a, **k: fetched.append(a[1]) or real_download_file(*a, **k)
tidy(templated)
civitai_says(FakeResponse([b'weights']))
both =service.download_version(542, CHECKPOINT, version(id=542))
check('one file on two rows, one held here, one gone: held, not fetched',
      (both.status, both.file_path, fetched), ('complete', moved, []))
os.remove(moved)

theirs = on_disk(ELSEWHERE, 'model.safetensors')
in_library[1] = [theirs]
tidy(templated)
civitai_says(FakeResponse([b'weights']))
other_webui =service.download_version(543, CHECKPOINT, version(id=543))
check('a copy only in a folder this WebUI does not load is fetched here, as before (#188)',
      (other_webui.status, other_webui.file_path), ('complete', templated))
tidy(templated, theirs)

# Paused while fetched back, and a sync forgot its row meanwhile - or the
# folder template changed: the resume carries on where its .partial is. It
# started over at the template's path, its .partial left behind.
os.makedirs(os.path.dirname(gone), exist_ok=True)
kept_part = on_disk(os.path.dirname(gone), 'renamed.safetensors.partial')
in_library.clear()
service._jobs[544] = {'partial_path': kept_part}
resumed_at = []
service._download_file = lambda url, path, headers, progress, resume_from=0: resumed_at.append((path, resume_from)) or False
service.download_version(544, CHECKPOINT, version(id=544), resume=True)
check('a resume carries on where its .partial is, from its size, not at the template\'s path',
      resumed_at, [(kept_part, len(b'weights'))])
os.remove(kept_part)
shutil.rmtree(os.path.dirname(gone), ignore_errors=True)
service._jobs.pop(544, None)

# Resumed when the library holds it now: nothing fetched, its .partial gone.
moved = on_disk(mine, 'model.safetensors')
held_part = on_disk(CKPT_DIR, 'model.safetensors.partial')
in_library[1] = [moved]
service._jobs[545] = {'partial_path': held_part}
resumed = service.download_version(545, CHECKPOINT, version(id=545), resume=True)
check('resumed when the library holds it: complete, that file, its .partial gone',
      (resumed.status, resumed.file_path, os.path.exists(held_part)), ('complete', moved, False))
os.remove(moved)
in_library.clear()
service._download_file = real_download_file

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

# ------------------------------------------- queued by its ids, retried (#223)
# Named by model and version, a press joins the queue at once, by its ids:
# Civitai is asked at its turn, as for a download brought back after a
# restart. Asking first cost each press about 0.4 s. A failure there is the
# row's, and Retry puts it back at the end of the queue, asking afresh.
import model_manager.civitai as civitai_pkg               # noqa: E402


class TurnClient:
    """Civitai as a download's turn asks it: the model, or a failure."""
    model = None
    fails = None
    asked = []

    @classmethod
    def from_settings(cls):
        return cls()

    def get_model(self, model_id):
        TurnClient.asked.append(model_id)
        if TurnClient.fails:
            raise TurnClient.fails
        return TurnClient.model

    def close(self):
        pass


def queue_by_ids(q, version_id, **extra):
    try:
        return q.queue_download(version_id, None, None, file_id=1, model_id=42, **extra)
    except TypeError:               # a queue that takes no ids: the checks below say so
        return None


def job_of(q, version_id):
    return {k: (q._jobs.get(version_id) or {}).get(k) for k in ('model_id', 'file_id', 'model_data', 'version_data')}


real_client = civitai_pkg.CivitaiClient
civitai_pkg.CivitaiClient = TurnClient
by_ids = Queueing(max_concurrent=0)
row = queue_by_ids(by_ids, 680, file_name='from the page.safetensors', size_kb=2.0)
check('queued by its ids: the row shows the name and size the page sent, waiting',
      [getattr(row, 'file_name', None), getattr(row, 'total_bytes', None), getattr(row, 'status', None)],
      ['from the page.safetensors', 2048, 'pending'])
check('its job holds the ids alone, for its turn', job_of(by_ids, 680),
      {'model_id': 42, 'file_id': 1, 'model_data': None, 'version_data': None})

TurnClient.model, TurnClient.asked = dict(CHECKPOINT, modelVersions=[version(id=680)]), []
release(680)
by_ids.max_concurrent = 1
by_ids._pump()
by_ids.wait()
check('at its turn, Civitai is asked for the model, then that version downloads',
      [TurnClient.asked, queued[-1], getattr(by_ids.get_progress(680), 'status', None)],
      [[42], (680, None, 1, False), 'complete'])

TurnClient.fails = RuntimeError('Civitai is busy')
queue_by_ids(by_ids, 681)
by_ids.wait()
failed = by_ids.get_progress(681)
check('a fetch that fails at its turn: an Error row saying what it could not do',
      [getattr(failed, 'status', None), getattr(failed, 'error', None)],
      ['error', 'Could not ask Civitai about this version: Civitai is busy'])

# Refused at its turn - paid, not bought, say - after Civitai answered: the
# answer is kept on the job. A retry must not reuse it.
TurnClient.fails = None
by_ids.max_concurrent = 0
by_ids.queue_download(683, CHECKPOINT, version(id=683), file_id=1)
by_ids.get_progress(683).status, by_ids.get_progress(683).error = 'error', 'Not bought'
queue_by_ids(by_ids, 682)
retry = getattr(by_ids, 'retry', lambda version_id: None)
check('Retry on an Error row: waiting again, its error cleared, last in the list',
      [retry(683), [(p['version_id'], p['status'], p['error']) for p in by_ids.get_all_progress()][-2:]],
      [True, [(682, 'pending', None), (683, 'pending', None)]])
check('its job back to its ids alone, so its turn asks Civitai afresh', job_of(by_ids, 683),
      {'model_id': 42, 'file_id': 1, 'model_data': None, 'version_data': None})
check('Retry on a row that is not in error changes nothing',
      [retry(682), retry(680), [p['version_id'] for p in by_ids.get_all_progress()]],
      [False, False, [680, 681, 682, 683]])

TurnClient.model, TurnClient.asked = dict(CHECKPOINT, modelVersions=[version(id=682), version(id=683)]), []
release(682, 683)
by_ids.max_concurrent = 1
by_ids._pump()
by_ids.wait()
check('the retried one\'s turn asks Civitai again, then it downloads',
      [TurnClient.asked, queued[-1], getattr(by_ids.get_progress(683), 'status', None)],
      [[42, 42], (683, None, 1, False), 'complete'])
civitai_pkg.CivitaiClient = real_client

# ------------------------------------------ how many run at once, a setting (#279)
# Downloads at once: 1 to 10, the same top as Civitai's requests per second.
# The queue is made with it, and follows a change at once: a higher number
# starts waiting downloads now; a lower one stops nothing, and starts none
# until fewer than it run. It was 2, fixed in the code.
reader = getattr(ds, 'configured_downloads_at_once', None)


def reads(value):
    opts.model_manager_downloads_at_once = value
    return reader() if reader else None


check('the setting reads as a whole number from 1 to 10; unreadable is the default',
      [reads(3), reads(0), reads(20), reads('many')], [3, 1, 10, 2])

kept_before, kept['rows'] = kept['rows'], []
opts.model_manager_downloads_at_once = 3
ds._download_service = None
check('the queue, first made, takes the saved number', ds.get_download_service().max_concurrent, 3)
ds._download_service = None
kept['rows'] = kept_before


def until(what, cond, seconds=3.0):
    deadline = time.time() + seconds
    while time.time() < deadline and not cond():
        time.sleep(0.01)
    return cond()


def statuses(q, ids):
    return [getattr(q.get_progress(v), 'status', None) for v in ids]


AT_ONCE = [690, 691, 692, 693]
limited = Queueing(max_concurrent=2)
for version_id in AT_ONCE:
    limited.queue_download(version_id, CHECKPOINT, version(id=version_id))
until('two running', lambda: statuses(limited, AT_ONCE) == ['downloading', 'downloading', 'pending', 'pending'])
set_limit = getattr(limited, 'set_limit', lambda limit: None)
set_limit(3)
check('raised from 2 to 3: one more starts at once, the last still waits',
      [until('three running', lambda: statuses(limited, AT_ONCE)[2] == 'downloading') and statuses(limited, AT_ONCE)],
      [['downloading', 'downloading', 'downloading', 'pending']])

set_limit(1)
settle()
check('lowered to 1 with 3 running: none is paused or stopped',
      statuses(limited, AT_ONCE), ['downloading', 'downloading', 'downloading', 'pending'])
release(690)
until('one ended', lambda: statuses(limited, AT_ONCE)[0] == 'complete')
release(691)
until('two ended', lambda: statuses(limited, AT_ONCE)[1] == 'complete')
settle()
check('none starts while as many as the number still run - one does',
      statuses(limited, AT_ONCE), ['complete', 'complete', 'downloading', 'pending'])
release(692)
check('the last starts once fewer than 1 run',
      until('the last running', lambda: statuses(limited, AT_ONCE)[3] in ('downloading', 'complete')), True)
release(693)
limited.wait()
# Saving the setting tells a queue already made: settings_api_test.py.

# ------------------------------------------------------ a file in parts (#282)
# Civitai's storage holds each connection to about 60 MB/s, so a large file
# is fetched over several, each a part into a file of its own - part 1 the
# .partial, part N .partial.N - joined in order at the end. The storage here
# answers each request by the Range it asks. Parts are at least PART_MIN, made
# small so a 300-byte file is a "large" one.
import threading                                         # noqa: E402

STORAGE = 'https://storage.invalid/signed'
PARTS_URL = 'https://example.invalid/parts'


class PartResponse(FakeResponse):
    """A stretch of the file, in 10-byte chunks, with what a check puts between them."""
    def __init__(self, data, start, end, total, status_code=206, between=None, half=None, wait=0.0):
        def pieces(stretch):
            for at in range(0, len(stretch), 10):
                if wait:
                    yield lambda: time.sleep(wait)
                yield stretch[at:at + 10]
        half = len(data) // 2 if half is None else half
        chunks = (list(pieces(data[:half])) + [between] + list(pieces(data[half:])) if between is not None
                  else list(pieces(data)))
        super().__init__(chunks, total=len(data), status_code=status_code)
        if status_code == 206:
            self.headers['content-range'] = 'bytes %d-%d/%d' % (start, end, total)
        self.url = STORAGE
        self.counted = True

    def close(self):
        if self.counted:
            self.counted = False
            with PartsSession.lock:
                PartsSession.open_now -= 1
        super().close()


class PartsSession:
    """Civitai's address and its storage, answering by the Range asked - or as `script` says."""
    body = b''
    asked = []
    script = None
    wait = 0.0
    lock = threading.Lock()
    open_now = 0
    most_open = 0

    def get(self, url, headers=None, stream=False, timeout=None):
        asked = (headers or {}).get('Range')
        body = PartsSession.body
        start, end = 0, len(body) - 1
        if asked:
            first, last = asked[len('bytes='):].split('-')
            start, end = int(first), (int(last) if last else len(body) - 1)
        with PartsSession.lock:
            PartsSession.asked.append((url, asked))
            nth = sum(1 for _, r in PartsSession.asked if r and int(r[6:].split('-')[0]) // 75 == start // 75)
        what = PartsSession.script(url, start, end, nth) if PartsSession.script else None
        if isinstance(what, Exception):
            raise what
        if what == 'whole' or not asked:
            reply = PartResponse(body, 0, len(body) - 1, len(body), status_code=200, wait=PartsSession.wait)
        else:
            # Half way through the part asked: an open first request runs on
            # past its part, which ends at the next multiple of 75.
            part_end = min(end, (start // 75) * 75 + 74)
            reply = PartResponse(body[start:end + 1], start, end, len(body),
                                 between=what if callable(what) else None, half=(part_end - start + 1) // 2,
                                 wait=PartsSession.wait)
        with PartsSession.lock:
            PartsSession.open_now += 1
            PartsSession.most_open = max(PartsSession.most_open, PartsSession.open_now)
        return reply


def storage_says(body, script=None, wait=0.0):
    PartsSession.body, PartsSession.script, PartsSession.wait = body, script, wait
    PartsSession.asked = []
    PartsSession.open_now = PartsSession.most_open = 0


def in_parts(version_id, body):
    return version(id=version_id, files=[{
        'id': 90, 'name': 'parts_%d.safetensors' % version_id, 'primary': True,
        'downloadUrl': PARTS_URL, 'sizeKB': len(body) / 1024,
        'hashes': {'SHA256': hashlib.sha256(body).hexdigest().upper()}}])


def part_files(version_id):
    partial = os.path.join(CKPT_DIR, 'parts_%d.safetensors.partial' % version_id)
    return sorted(n for n in os.listdir(CKPT_DIR) if n.startswith(os.path.basename(partial)))


real_part_min = getattr(ds, 'PART_MIN', None)
ds.PART_MIN = 10
ds.requests = types.SimpleNamespace(Session=PartsSession, exceptions=real_requests.exceptions)
BIG = bytes(range(256)) + bytes(range(44))           # 300 bytes: four parts of 75
BIG_SHA = hashlib.sha256(BIG).hexdigest().upper()
kept['rows'] = []

storage_says(BIG)
whole = service.download_version(700, CHECKPOINT, in_parts(700, BIG))
ranges = [r for _, r in PartsSession.asked]
check('a large file: four requests, the first at Civitai\'s address from byte 0, the rest at the storage for '
      'their parts',
      [len(ranges), PartsSession.asked[0] if PartsSession.asked else None,
       sorted((u, r) for u, r in PartsSession.asked[1:])],
      [4, (PARTS_URL, 'bytes=0-'),
       [(STORAGE, 'bytes=150-224'), (STORAGE, 'bytes=225-299'), (STORAGE, 'bytes=75-149')]])
check('joined in order: the file, its SHA-256 Civitai\'s, complete, nothing left beside it',
      [whole.status, io.open(whole.file_path, 'rb').read() == BIG if whole.file_path else None, whole.sha256,
       part_files(700)], ['complete', True, BIG_SHA, []])

storage_says(BIG, script=lambda url, start, end, nth: 'whole')
taken = service.download_version(701, CHECKPOINT, in_parts(701, BIG))
check('a storage that sends the whole file for part 1\'s range: read as one connection, one request, '
      'no part file made',
      [PartsSession.asked, taken.status, io.open(taken.file_path, 'rb').read() == BIG if taken.file_path else None,
       part_files(701)], [[(PARTS_URL, 'bytes=0-')], 'complete', True, []])

storage_says(BIG[:15])
small = service.download_version(702, CHECKPOINT, in_parts(702, BIG[:15]))
check('a file under two parts: one request with no Range, today\'s one connection',
      [[r for _, r in PartsSession.asked], small.status], [[None], 'complete'])

opts.model_manager_download_in_parts = False
storage_says(BIG)
off = service.download_version(703, CHECKPOINT, in_parts(703, BIG))
check('the switch off: one request with no Range, whatever the count',
      [[r for _, r in PartsSession.asked], off.status], [[None], 'complete'])
opts.model_manager_download_in_parts = True


def sizes(version_id):
    partial = os.path.join(CKPT_DIR, 'parts_%d.safetensors.partial' % version_id)
    return [os.path.getsize(p) if os.path.exists(p) else None
            for p in [partial] + ['%s.%d' % (partial, n) for n in (2, 3, 4)]]


def pause_when_half(version_id, whole_parts):
    """
    A script: the parts in `whole_parts` (by their first byte's part, 0 to 3)
    come whole; the others stop half way until every one has, then the
    download is paused - so it pauses with those parts done, the rest half.
    """
    half = []

    def between():
        with PartsSession.lock:
            half.append(1)
        waiting = 4 - len(whole_parts)
        until('every part half way', lambda: len(half) >= waiting
              and all(s == 75 for i, s in enumerate(sizes(version_id)) if i in whole_parts))
        service._pause_flags[version_id] = True

    return lambda url, start, end, nth: None if start // 75 in whole_parts else between


storage_says(BIG, script=pause_when_half(704, {0, 1}))
paused_parts = service.download_version(704, CHECKPOINT, in_parts(704, BIG))
check('paused in parts: two done, two half way, every part file kept, nothing joined',
      [paused_parts.status, sizes(704)], ['paused', [75, 75, 37, 37]])
check('kept to resume after a restart, by its .partial',
      [(r['version_id'], os.path.basename(r['partial_path'] or '')) for r in kept['rows'] if r['version_id'] == 704],
      [(704, 'parts_704.safetensors.partial')])
after_restart = DownloadService(max_concurrent=2)
after_restart.restore()
check('after a restart, it is back paused, as far as all its parts got',
      [getattr(after_restart.get_progress(704), 'status', None),
       getattr(after_restart.get_progress(704), 'downloaded_bytes', None)], ['paused', 75 + 75 + 37 + 37])

storage_says(BIG)
on_again = service.download_version(704, CHECKPOINT, in_parts(704, BIG), resume=True)
check('resumed: the first request asks from part 1\'s own size; only the unfinished parts ask, each from its own, '
      'at the storage address it reached',
      [PartsSession.asked[0] if PartsSession.asked else None, sorted(PartsSession.asked[1:])],
      [(PARTS_URL, 'bytes=75-'), [(STORAGE, 'bytes=187-224'), (STORAGE, 'bytes=262-299')]])
check('and the file is whole, its SHA-256 Civitai\'s', [on_again.status, on_again.sha256, part_files(704)],
      ['complete', BIG_SHA, []])

# Turned off while paused: its parts one after another, never two at once.
storage_says(BIG, script=pause_when_half(705, {0, 1}))
service.download_version(705, CHECKPOINT, in_parts(705, BIG))
opts.model_manager_download_in_parts = False
storage_says(BIG, wait=0.005)
one_by_one = service.download_version(705, CHECKPOINT, in_parts(705, BIG), resume=True)
check('the switch turned off while paused: resumed one part at a time, nothing fetched twice, the file whole',
      [PartsSession.most_open, sorted(r for _, r in PartsSession.asked[1:]), one_by_one.sha256],
      [1, ['bytes=187-224', 'bytes=262-299'], BIG_SHA])
opts.model_manager_download_in_parts = True

# The count lowered while paused: at most that many parts at once.
storage_says(BIG, script=pause_when_half(706, set()))
service.download_version(706, CHECKPOINT, in_parts(706, BIG))
opts.model_manager_connections_per_file = 2
storage_says(BIG, wait=0.005)
two_at_once = service.download_version(706, CHECKPOINT, in_parts(706, BIG), resume=True)
check('four parts half way, the count set to 2, resumed: at most two at once, the file whole',
      [PartsSession.most_open <= 2, len(PartsSession.asked), two_at_once.sha256], [True, 4, BIG_SHA])
check('and it reads the count anew at each start: two did run at once', PartsSession.most_open, 2)

# The count changed while a download runs: it keeps what it began with.
opts.model_manager_connections_per_file = 4
arrived = []


def lower_meanwhile(url, start, end, nth):
    def between():
        with PartsSession.lock:
            arrived.append(start)
        until('all four running', lambda: len(arrived) >= 4)
        opts.model_manager_connections_per_file = 2
    return between


storage_says(BIG, script=lower_meanwhile)
kept_on = service.download_version(707, CHECKPOINT, in_parts(707, BIG))
check('the count lowered while it runs: its four parts carry on, the file whole',
      [len(arrived), PartsSession.most_open, kept_on.sha256], [4, 4, BIG_SHA])
opts.model_manager_connections_per_file = 4

# A part's connection drops: that part alone asks again, from its own size,
# through Civitai's address for a fresh storage link.
def drop_part_3(url, start, end, nth):
    if start // 75 == 2 and nth == 1:
        def broken():
            raise real_requests.exceptions.ConnectionError('dropped')
        return broken
    return None


storage_says(BIG, script=drop_part_3)
dropped = service.download_version(708, CHECKPOINT, in_parts(708, BIG))
asked_part_3 = [(u, r) for u, r in PartsSession.asked if r and int(r[6:].split('-')[0]) // 75 == 2]
check('a part\'s connection drops: it asks again from its own size, at Civitai\'s address; no other part again',
      [asked_part_3, len(PartsSession.asked), dropped.sha256],
      [[(STORAGE, 'bytes=150-224'), (PARTS_URL, 'bytes=187-224')], 5, BIG_SHA])

# A part the storage sends whole every time: asked three times, then the
# download pauses, saying why, its parts kept.
storage_says(BIG, script=lambda url, start, end, nth: 'whole' if start // 75 == 2 else None)
refused = service.download_version(709, CHECKPOINT, in_parts(709, BIG))
check('a part the storage will not send in part: asked three times, then paused, saying why, parts kept',
      [len([r for _, r in PartsSession.asked if r and int(r[6:].split('-')[0]) // 75 == 2]), refused.status,
       refused.error, len(part_files(709))],
      [3, 'paused', "Civitai's storage would not send part 3 of 4. Resume to try again.", 4])

# Cancelled while in parts: every part file goes.
def cancel_in_part_2(url, start, end, nth):
    if start // 75 == 1:
        return lambda: service._cancel_flags.__setitem__(710, True)
    return None


storage_says(BIG, script=cancel_in_part_2)
gone_parts = service.download_version(710, CHECKPOINT, in_parts(710, BIG))
check('cancelled while in parts: the .partial and every part file gone',
      [gone_parts.status, part_files(710)], ['cancelled', []])
service._cancel_flags.pop(710, None)

# A join cut short by a restart leaves a gap in the numbers: started again.
gap = os.path.join(CKPT_DIR, 'parts_711.safetensors.partial')
io.open(gap, 'wb').write(BIG[:150])
io.open(gap + '.3', 'wb').write(BIG[150:225])
storage_says(BIG)
restarted_join = service.download_version(711, CHECKPOINT, in_parts(711, BIG), resume=True)
check('a join cut short (part 2 gone, part 3 there): started again, and whole',
      [PartsSession.asked[0] if PartsSession.asked else None, restarted_join.sha256, part_files(711)],
      [(PARTS_URL, 'bytes=0-'), BIG_SHA, []])

ds.requests = types.SimpleNamespace(Session=FakeSession, exceptions=real_requests.exceptions)
if real_part_min is not None:
    ds.PART_MIN = real_part_min

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
