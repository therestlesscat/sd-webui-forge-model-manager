"""
Which tabs are on, decided in one place (model_manager/tabs.py, #181): a tab
switched off has its routes refuse and its startup work left out.

What is checked here: every route naming its area - all 71 held to the table
below, which is the spec; with every tab off, every route but ui-options
refusing, in the shape every failure answers; an off tab's routes refused
through the app; the shared areas, on while any of their tabs is; the
startup work left out; and the page told which tabs are on and were built.

The Model Manager and the Civitai Browser have no switch yet (#185): to see
the shared areas go off, they are given one here.
"""
import asyncio
import importlib.util
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

from modules import script_callbacks, shared              # noqa: E402  (webui_stub's)
import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402

# The fixture library, so nothing here can reach another database.
db, facts = fixtures.build(os.path.join(TESTS, 'work', 'tab_switches'))
dbmod._db_instance = db

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


QUEUE = 'model_manager_queue_enabled'
GENERATIONS = 'model_manager_record_generations'


def switch(key, on):
    setattr(shared.opts, key, on)


from model_manager import api                             # noqa: E402
client = TestClient((lambda app: (api.setup_api(app), app)[1])(FastAPI()))

# ------------------------------------------------------- an off tab refuses
switch(QUEUE, False)
check('the Queue off: its status refused', client.get('/model-manager/queue/status').status_code, 403)
switch(QUEUE, True)
check('on: answered', client.get('/model-manager/queue/status').status_code, 200)

switch(GENERATIONS, False)
check('Generations off: its tab\'s page refused', client.get('/model-manager/generations/browse').status_code, 403)
switch(GENERATIONS, True)
check('on: answered', client.get('/model-manager/generations/browse').status_code, 200)

# ------------------------------------------------------------- the startup
# Queued tasks a restart left running are stopped at startup: seen where it
# reaches the database. The rest of the startup is checked further down.
recovered = []
real_stop_running = db.stop_running_tasks
db.stop_running_tasks = lambda install: recovered.append(install) or 0
real_restamp, real_update_check = api.prompt_levels.start_in_background, api.update_check.start_in_background
api.prompt_levels.start_in_background = lambda: None
api.update_check.start_in_background = lambda: None
switch(QUEUE, False)
api.on_app_started(None, FastAPI())
check('the Queue off: its tasks are not recovered at startup', len(recovered), 0)
switch(QUEUE, True)
api.on_app_started(None, FastAPI())
check('on: they are', len(recovered), 1)
db.stop_running_tasks = real_stop_running
api.prompt_levels.start_in_background, api.update_check.start_in_background = real_restamp, real_update_check

# ---------------------------------------------------------- every route's area
# The spec: each route, and the area it is refused with.
SPEC = {
    ('GET', '/model-manager/civitai/models'): 'civitai_browser',
    ('GET', '/model-manager/civitai/models/stream'): 'civitai_browser',
    ('GET', '/model-manager/civitai/models/random'): 'civitai_browser',
    ('GET', '/model-manager/civitai/models/{model_id}'): 'civitai_browser',
    ('GET', '/model-manager/civitai/versions/{version_id}/images'): 'civitai_browser',
    ('GET', '/model-manager/civitai/tags'): 'civitai_browser',
    ('GET', '/model-manager/civitai/enums'): 'civitai_browser',
    ('POST', '/model-manager/civitai/download'): 'downloads',
    ('GET', '/model-manager/civitai/download/progress'): 'downloads',
    ('POST', '/model-manager/civitai/download/cancel'): 'downloads',
    ('POST', '/model-manager/civitai/download/control'): 'downloads',
    ('POST', '/model-manager/civitai/download/dismiss'): 'downloads',
    ('GET', '/model-manager/generations/browse'): 'generations',
    ('GET', '/model-manager/generations/page'): 'generations',
    ('GET', '/model-manager/generations/{generation_id}/images'): 'generations',
    ('GET', '/model-manager/generations/{generation_id}/send-plan'): 'generations',
    ('GET', '/model-manager/generations/images/{image_id}/file'): 'generations',
    ('POST', '/model-manager/generations/images/{image_id}/delete'): 'generations',
    ('POST', '/model-manager/generations/rate'): 'generations',
    ('POST', '/model-manager/generations/delete-many'): 'generations',
    ('POST', '/model-manager/generations/{generation_id}/delete'): 'generations',
    ('GET', '/model-manager/images/gallery-page'): 'model_manager',
    ('POST', '/model-manager/sync'): 'model_manager',
    ('POST', '/model-manager/sync/metadata'): 'model_manager',
    ('GET', '/model-manager/sync/estimate'): 'model_manager',
    ('GET', '/model-manager/sync/new-files'): 'model_manager',
    ('GET', '/model-manager/sync/misplaced'): 'model_manager',
    ('GET', '/model-manager/sync/progress'): 'model_manager',
    ('POST', '/model-manager/sync/cancel'): 'model_manager',
    ('GET', '/model-manager/models'): 'model_manager',
    ('GET', '/model-manager/filter-defaults'): 'model_manager',
    ('GET', '/model-manager/models/details'): 'model_manager',
    ('GET', '/model-manager/models/versions'): 'model_manager',
    ('GET', '/model-manager/filters'): 'model_manager',
    ('POST', '/model-manager/models/force-sync'): 'model_manager',
    ('POST', '/model-manager/models/delete'): 'model_manager',
    ('POST', '/model-manager/pin'): 'model_manager',
    ('POST', '/model-manager/bookmark'): 'model_manager',
    ('POST', '/model-manager/resolve-hashes'): 'send',
    ('POST', '/model-manager/missing-resources'): 'send',
    ('GET', '/model-manager/image-resources'): 'send',
    ('GET', '/model-manager/forge-modules'): 'send',
    ('GET', '/model-manager/forge-modules/current'): 'send',
    ('GET', '/model-manager/queue/status'): 'queue',
    ('POST', '/model-manager/queue/start'): 'queue',
    ('POST', '/model-manager/queue/stop'): 'queue',
    ('POST', '/model-manager/queue/pause'): 'queue',
    ('POST', '/model-manager/queue/resume'): 'queue',
    ('GET', '/model-manager/queue/tasks'): 'queue',
    ('GET', '/model-manager/queue/tasks/{task_id}'): 'queue',
    ('GET', '/model-manager/queue/tasks/{task_id}/send-plan'): 'queue',
    ('POST', '/model-manager/queue/run-next'): 'queue',
    ('POST', '/model-manager/queue/cancel'): 'queue',
    ('POST', '/model-manager/queue/retry'): 'queue',
    ('POST', '/model-manager/queue/delete'): 'queue',
    ('POST', '/model-manager/queue/unhide'): 'queue',
    ('POST', '/model-manager/queue/history/clear'): 'queue',
    ('GET', '/model-manager/saved-search'): 'saved_search',
    ('POST', '/model-manager/saved-search'): 'saved_search',
    ('GET', '/model-manager/notes'): 'any',
    ('POST', '/model-manager/notes/dismiss'): 'any',
    ('GET', '/model-manager/update'): 'any',
    ('GET', '/model-manager/settings'): 'any',
    ('GET', '/model-manager/settings/folder-example'): 'any',
    ('GET', '/model-manager/settings/modules'): 'any',
    ('POST', '/model-manager/settings/test-key'): 'any',
    ('GET', '/model-manager/settings/nsfw-levels'): 'any',
    ('POST', '/model-manager/settings'): 'any',
    ('GET', '/model-manager/asset-version'): 'any',
    ('GET', '/model-manager/video-still'): 'any',
    ('GET', '/model-manager/ui-options'): 'always',
}
check('the spec holds 71 routes', len(SPEC), 71)

app = FastAPI()
api.setup_api(app)
routes = {(method, route.path): route for route in app.routes
          if isinstance(route, APIRoute) and route.path.startswith('/model-manager/') for method in route.methods}
areas = {key: getattr(route.endpoint, 'mm_area', None) for key, route in routes.items()}
check('every route names its area', sorted(key for key, area in areas.items() if area is None), [])
check('each route\'s area is the spec\'s', areas, SPEC)

# ------------------------------------------------------ the shared areas
# The Model Manager and the Civitai Browser given a switch, as #185 will.
import model_manager.forge_host as forge_host             # noqa: E402
import model_manager.tabs as tabs                         # noqa: E402
MM, CB = 'mm_test_model_manager_enabled', 'mm_test_civitai_browser_enabled'
real_tabs = dict(tabs.TABS)
forge_host.DEFAULTS.update({MM: True, CB: True})
tabs.TABS.update(model_manager=MM, civitai_browser=CB)
KEYS = {'queue': QUEUE, 'generations': GENERATIONS, 'model_manager': MM, 'civitai_browser': CB}


def only(*on):
    """Each tab on or off: on, the ones named."""
    for tab, key in KEYS.items():
        switch(key, tab in on)


def areas_on():
    return sorted(area for area in ('queue', 'generations', 'model_manager', 'civitai_browser',
                                    *tabs.SERVICES, tabs.ALWAYS) if tabs.on(area))


only('model_manager', 'civitai_browser', 'generations', 'queue')
check('all on: every area', areas_on(), sorted(['queue', 'generations', 'model_manager', 'civitai_browser',
                                                 'downloads', 'saved_search', 'send', 'restamp', 'any', 'always']))
only('civitai_browser')
check('the Civitai Browser alone: downloads, saved searches, Send - no restamp',
      areas_on(), ['always', 'any', 'civitai_browser', 'downloads', 'saved_search', 'send'])
only('generations')
check('Generations alone: Send and the restamp - no downloads, no saved searches',
      areas_on(), ['always', 'any', 'generations', 'restamp', 'send'])
only('queue')
check('the Queue alone: Send', areas_on(), ['always', 'any', 'queue', 'send'])
only()
check('all off: ui-options alone', areas_on(), ['always'])
delattr(shared.opts, QUEUE)
check('a switch never set is on, as by default', tabs.on('queue'), True)


def raises(fn):
    try:
        fn()
    except KeyError:
        return True
    return False


check('a misspelt area is an error, not an area', (raises(lambda: tabs.on('queues')),
      raises(lambda: api.common.gate('queues')), raises(lambda: tabs.mark_built(['send']))), (True, True, True))

# --------------------------------------------- every route refused, all off
def call(endpoint):
    answer = endpoint()
    return asyncio.run(answer) if asyncio.iscoroutine(answer) else answer


# The gate first, on stand-ins that say whether they ran: a gate that let
# calls through would run the real routes below.
ran = []


@api.common.gate('queue')
def plain():
    ran.append('plain')


@api.common.gate('queue')
async def awaited():
    ran.append('async')


only()
check('off: refused before the endpoint runs, a plain one and an async one',
      (getattr(call(plain), 'status_code', 'ran'), getattr(call(awaited), 'status_code', 'ran'), ran),
      (403, 403, []))
only('queue')
call(plain)
call(awaited)
check('on: run', ran, ['plain', 'async'])

# Each route's own function, called with nothing: refused before it runs.
# Only a gated one, and only once the gate refuses and every area is off.
only()
if ran == ['plain', 'async'] and areas_on() == ['always']:
    refusals = {}
    for key, route in routes.items():
        if areas.get(key) in (None, tabs.ALWAYS):
            continue
        try:
            answer = call(route.endpoint)
            refusals[key] = (answer.status_code, json.loads(answer.body))
        except Exception as e:
            refusals[key] = ('ran', type(e).__name__)
    want = {key: (403, {'success': False, 'error': tabs.why_off(area), 'off': area})
            for key, area in SPEC.items() if area != tabs.ALWAYS}
    check('all off: every route refused, saying why, as every failure answers', refusals, want)
check('async routes among them', sum(asyncio.iscoroutinefunction(route.endpoint) for route in routes.values()) > 0)
answer = client.get('/model-manager/ui-options')
check('ui-options still answers, and says each tab is off',
      (answer.status_code, {tab: state['on'] for tab, state in answer.json().get('tabs', {}).items()}),
      (200, {'queue': False, 'generations': False, 'model_manager': False, 'civitai_browser': False}))
check('through the app, in words', client.get('/model-manager/queue/status').json(),
      {'success': False, 'error': 'The Queue is turned off in the settings', 'off': 'queue'})
check('a shared one', client.get('/model-manager/civitai/download/progress').json().get('error'),
      'Every tab that uses this is turned off in the settings')

# ----------------------------------------------- startup work left out
from model_manager.jobs import jobs                      # noqa: E402
asked = []
real_start = jobs.start
jobs.start = lambda kind, *a, **k: asked.append(kind) or False
only('queue', 'civitai_browser')
api.prompt_levels.start_in_background()
check('the Model Manager and Generations off: stored images are not judged again', asked, [])
only('generations')
api.prompt_levels.start_in_background()
check('Generations on: they are', asked, ['restamp'])
jobs.start = real_start

threads = []
real_threading = api.update_check.threading
api.update_check.threading = types.SimpleNamespace(
    enumerate=lambda: [],
    Thread=lambda target, name, daemon: types.SimpleNamespace(start=lambda: threads.append(name)))
switch('model_manager_check_updates', True)
only()
api.update_check.start_in_background()
api.update_check.check_soon()
check('every tab off: GitHub is not asked, now or every 12 hours', (threads, api.update_check.enabled()), ([], False))
only('queue')
api.update_check.start_in_background()
check('one on: it is', (threads, api.update_check.enabled()), (['model-manager-update-check'], True))
api.update_check.threading = real_threading

# --------------------------------------------- the build, and the page told
tabs_callbacks = []
real_on_ui_tabs = script_callbacks.on_ui_tabs
script_callbacks.on_ui_tabs = lambda fn: tabs_callbacks.append(fn)
fake_ui = types.ModuleType('model_manager.ui')
fake_ui.create_queue_ui = lambda: 'queue markup'
fake_ui.create_generations_ui = lambda: 'generations markup'
fake_ui.create_ui = lambda: [('model manager markup', 'Model Manager', 'model_manager_tab')]
fake_ui.create_civitai_browser_ui = lambda: 'browser markup'
fake_ui.on_ui_settings = lambda *a, **k: None
real_ui = sys.modules.get('model_manager.ui')
sys.modules['model_manager.ui'] = fake_ui
spec = importlib.util.spec_from_file_location('mm_ui_script', os.path.join(ROOT, 'scripts', 'model_manager_ui.py'))
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)
if real_ui is None:
    del sys.modules['model_manager.ui']
else:
    sys.modules['model_manager.ui'] = real_ui
script_callbacks.on_ui_tabs = real_on_ui_tabs

only('queue', 'model_manager', 'civitai_browser')
check('built: the tabs that are on, in order',
      [name for _, name, _ in tabs_callbacks[0]()], ['Queue', 'Model Manager', 'Civitai Browser'])
check('and kept', sorted(tabs.built()), ['civitai_browser', 'model_manager', 'queue'])
only('queue', 'generations', 'model_manager', 'civitai_browser')
check('the page told: on now, and whether this start created it',
      client.get('/model-manager/ui-options').json().get('tabs'),
      {'queue': {'on': True, 'built': True}, 'generations': {'on': True, 'built': False},
       'model_manager': {'on': True, 'built': True}, 'civitai_browser': {'on': True, 'built': True}})
only('generations')
tabs_callbacks[0]()
check('built again - Reload UI: what this build created', sorted(tabs.built()), ['generations'])

tabs.TABS.clear()
tabs.TABS.update(real_tabs)
db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
