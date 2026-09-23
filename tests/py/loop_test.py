"""
A slow Civitai must not stall the rest of the WebUI.

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
# start_sync does that and hands the work to a thread, and it has to stay
# async: its "is one already running?" check and the thread start happen with
# nothing able to run in between, which a thread pool would not guarantee.
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


# ---------------------------------------------------------------- by timing
db, _ = fixtures.build(os.path.join(TESTS, 'work', 'loop'))
dbmod._db_instance = db

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
