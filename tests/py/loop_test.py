"""
A slow Civitai, a database or a disk must not stall the rest of the WebUI.

These endpoints are registered on the WebUI's own FastAPI app - the one Gradio
runs on - and it serves every request from one event loop. An `async def`
handler runs *on* that loop and promises to hand it back whenever it waits.
Ours call Civitai through `requests`, which is synchronous, so they could not:
while Civitai took its time, every other request in the WebUI queued behind
it. Measured: an unrelated request sent at 0.2s answered at 2.2s, behind a
2-second Civitai call.

A plain `def` handler is one FastAPI runs on a worker thread instead, leaving
the loop free. So there are two checks:

  - by rule: no handler does Civitai or sync work in its own body while
    declared `async def` (work inside a nested function - the streaming
    search's generator - is run off the loop already, and is left alone)
  - by running: every async route, asked once on a test library, opens no
    database connection and touches no file on the event loop - which the
    rule cannot see when a handler reaches them through what it calls. The
    grid, the details panel, delete, pins, the Generations tab and the
    settings window did (#80); a pin waiting on a sync's write lock froze
    the WebUI for up to SQLite's 30 seconds. A new async route needs a sample
    request below, or this fails
  - by timing: with Civitai made slow, an unrelated request still answers at
    once
"""
import ast
import asyncio
import io
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402
webui_stub.install()

try:
    import httpx
    from fastapi import FastAPI
except ImportError:
    print("fastapi/httpx are not installed; run this with the WebUI's python")
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.api.civitai as civitai_api          # noqa: E402
import model_manager.api.models as models_api            # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ------------------------------------------------------------------ by rule
# The calls that wait: every Civitai request, and a sync, which hashes files.
# Making a client or a SyncService is cheap and does not count - jobs.py's
# start_sync does that and hands the work to a thread, so it may stay async
# (model_manager.jobs takes the "is one already running?" check and the
# thread start under one lock, whichever thread asks).
BLOCKING = (
    'get_model', 'get_models_by_ids', 'get_model_by_hash', 'get_model_images',
    'get_generation_data', 'get_checkpoint_types', 'get_enums',
    'search_models', 'search_tags',
    'sync_model', 'sync_all', 'sync_metadata', 'scan_models',
)


def own_body_names(func):
    """Every name used in a function's own body, not in functions nested in it."""
    names = set()
    stack = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        stack.extend(ast.iter_child_nodes(node))
    return names


offenders = []
api_dir = os.path.join(ROOT, 'model_manager', 'api')
for name in sorted(os.listdir(api_dir)):
    if not name.endswith('.py'):
        continue
    source = io.open(os.path.join(api_dir, name), encoding='utf-8').read()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.AsyncFunctionDef) and own_body_names(node) & set(BLOCKING):
            offenders.append('%s: %s' % (name, node.name))

check('no async handler waits on Civitai or a sync in its own body', offenders, [])


# --------------------------------------------------------------- by running
import builtins                                           # noqa: E402
import inspect                                            # noqa: E402
import json                                               # noqa: E402
import shutil                                             # noqa: E402
import model_manager.jobs as jobs_module                  # noqa: E402
from modules import shared                                # noqa: E402  (webui_stub's)

db, facts = fixtures.build(os.path.join(TESTS, 'work', 'loop'))
dbmod._db_instance = db
doomed = os.path.join(TESTS, 'work', 'loop', 'library', 'to_delete.safetensors')
os.makedirs(os.path.dirname(doomed), exist_ok=True)
open(doomed, 'wb').write(b'\0' * 16)
db.upsert_version({'file_path': doomed, 'file_name': os.path.basename(doomed), 'id': 8801, 'model_id': 880})
some = facts['linked_paths'][0]

SAMPLES = {
    ('GET', '/model-manager/models'): {},
    ('GET', '/model-manager/filter-defaults'): {},
    ('GET', '/model-manager/models/details'): {'params': {'path': some}},
    ('GET', '/model-manager/filters'): {},
    ('POST', '/model-manager/models/delete'): {'data': {'path': doomed}},
    ('POST', '/model-manager/pin'): {'data': {'pinned': 'true', 'file_path': some}},
    ('POST', '/model-manager/bookmark'): {'data': {'model_id': '880', 'bookmarked': 'true'}},
    ('GET', '/model-manager/generations/browse'): {},
    ('GET', '/model-manager/generations/page'): {'params': {'path': some}},
    ('GET', '/model-manager/generations/{generation_id}/images'): {'url': '/model-manager/generations/1/images'},
    ('GET', '/model-manager/generations/images/{image_id}/file'): {'url': '/model-manager/generations/images/1/file'},
    ('POST', '/model-manager/sync'): {'data': {'paths': some}},
    ('POST', '/model-manager/sync/metadata'): {'data': {'paths': some}},
    ('GET', '/model-manager/sync/estimate'): {},
    ('GET', '/model-manager/sync/progress'): {},
    ('POST', '/model-manager/sync/cancel'): {},
    ('POST', '/model-manager/scan'): {'data': {'options': '{}'}},
    ('GET', '/model-manager/scan/progress'): {},
    ('POST', '/model-manager/scan/cancel'): {},
    ('GET', '/model-manager/civitai/models/stream'): {'params': {'query': 'x'}},
    ('GET', '/model-manager/civitai/models/random'): {'params': {'types': 'LORA'}},
    ('GET', '/model-manager/civitai/download/progress'): {},
    ('POST', '/model-manager/civitai/download/cancel'): {'data': {'version_id': '0'}},
    ('POST', '/model-manager/civitai/download/control'): {'data': {'action': 'pause_all'}},
    ('POST', '/model-manager/civitai/download/dismiss'): {'data': {'version_id': '0'}},
    ('GET', '/model-manager/ui-options'): {},
    ('GET', '/model-manager/settings'): {},
    ('GET', '/model-manager/settings/folder-example'): {'params': {'template': '{baseModel}'}},
    ('GET', '/model-manager/settings/nsfw-levels'): {},
    ('POST', '/model-manager/settings'): {'json': {'values': {}}},
}


class QuickCivitai:
    """Civitai, answering nothing at once - this check is about the loop, not Civitai."""
    wait_on_rate_limit = True

    @classmethod
    def from_settings(cls):
        return cls()

    def search_models(self, **kwargs):
        return {'items': [], 'nextCursor': None}

    def close(self):
        pass


def on_the_loop():
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


touched = []


def watched(what, real):
    def call(*args, **kwargs):
        if on_the_loop():
            touched.append(what)
        return real(*args, **kwargs)
    return call


DISK = [(builtins, 'open'), (os, 'remove'), (os, 'unlink'), (os, 'rmdir'), (os, 'listdir'),
        (os, 'scandir'), (os, 'replace'), (os, 'rename'), (os, 'makedirs'), (shutil, 'rmtree')]
real_disk = [(module, name, getattr(module, name)) for module, name in DISK]
real_connection = dbmod.ModelsDatabase._get_connection
real_start, real_client = jobs_module.jobs.start, civitai_api.CivitaiClient
shared.opts.data_labels = {}                              # the settings window's registry, empty


def made_not_run(kind, make, run, again=False):
    make()                                                # a job's service is made on the loop; its work is not
    return True


app = FastAPI()
setup_api(app)
asked, unsampled, on_loop = [], [], {}
try:
    for module, name, real in real_disk:
        setattr(module, name, watched('the disk (%s)' % name, real))
    dbmod.ModelsDatabase._get_connection = watched('the database', real_connection)
    jobs_module.jobs.start = made_not_run
    civitai_api.CivitaiClient = QuickCivitai

    async def ask_every_async_route():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://webui') as client:
            for route in app.routes:
                endpoint = getattr(route, 'endpoint', None)
                if not (route.path.startswith('/model-manager') and inspect.iscoroutinefunction(endpoint)):
                    continue
                for method in sorted(route.methods):
                    sample = SAMPLES.get((method, route.path))
                    if sample is None:
                        unsampled.append('%s %s' % (method, route.path))
                        continue
                    sample = dict(sample)
                    url = sample.pop('url', route.path)
                    del touched[:]
                    await client.request(method, url, **sample)
                    asked.append(url)
                    if touched:
                        on_loop['%s %s' % (method, route.path)] = sorted(set(touched))
    asyncio.run(ask_every_async_route())
finally:
    for module, name, real in real_disk:
        setattr(module, name, real)
    dbmod.ModelsDatabase._get_connection = real_connection
    jobs_module.jobs.start, civitai_api.CivitaiClient = real_start, real_client
    del shared.opts.data_labels

check('every async route has a sample request here', unsampled, [])
check('and was asked', len(asked) > 5, True)
check('no async route touches the database or the disk on the event loop',
      json.dumps(on_loop, indent=1), '{}')


# ---------------------------------------------------------------- by timing

SLOW = 1.5


class SlowCivitai:
    """Civitai, taking its time, as it does under load."""

    @classmethod
    def from_settings(cls):
        return cls()

    def search_models(self, **kwargs):
        time.sleep(SLOW)
        return {'items': [], 'nextCursor': None}

    def get_model_by_hash(self, value):
        time.sleep(SLOW)
        return None

    def close(self):
        pass


civitai_api.CivitaiClient = SlowCivitai
models_api.CivitaiClient = SlowCivitai

app = FastAPI()
setup_api(app)


async def race(method, url, **kwargs):
    """Start a slow request, then time an unrelated one sent while it runs."""
    started = time.time()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://webui') as client:
        async def slow():
            await client.request(method, url, **kwargs)
            return time.time() - started

        async def unrelated():
            await asyncio.sleep(0.2)
            await client.get('/model-manager/ui-options')
            return time.time() - started

        return await asyncio.gather(slow(), unrelated())


for label, method, url, kwargs in (
    ('a Civitai search', 'GET', '/model-manager/civitai/models', {}),
    ('resolving a resource hash', 'POST', '/model-manager/resolve-hashes',
     {'data': {'hashes': 'aaaaaaaaaa'}}),
):
    slow_done, unrelated_done = asyncio.run(race(method, url, **kwargs))
    check('%s still took as long as Civitai did' % label, slow_done >= SLOW, True)
    check('but an unrelated request sent meanwhile did not wait for it (answered at %.2fs)'
          % unrelated_done, unrelated_done < SLOW / 2, True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
