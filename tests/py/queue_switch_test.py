"""
The queue, one switch for all of it (#156), as "Your generations" is: off, no
Queue button is made beside Generate and no Queue tab built at the next
start, the queue does not start, a running one stops when it is turned off,
and the page hides the tab and the buttons at once (generations_switch_test.mjs).
The tasks are kept.

What is checked here: the switch as the server reads it, the Queue buttons
and the startup that leave the queue out, Start refused, the setting's
onchange stopping a running queue, and ui-options telling the page.
"""
import importlib.util
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
    from fastapi.testclient import TestClient
    import gradio                                        # noqa: F401
except ImportError:
    print('fastapi or gradio is not installed; run this with the WebUI\'s python')
    sys.exit(0)

from modules import script_callbacks, shared              # noqa: E402  (webui_stub's)
import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.jobs import jobs                      # noqa: E402
from model_manager.scheduler import QUEUE_ENABLED, capture, queue_enabled, runner   # noqa: E402

# The fixture library, so nothing here can reach another database.
db, facts = fixtures.build(os.path.join(TESTS, 'work', 'queue_switch'))
dbmod._db_instance = db

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def switch(on):
    setattr(shared.opts, QUEUE_ENABLED, on)


# ------------------------------------------------------------- the switch
switch(True)
check('on', queue_enabled(), True)
switch(False)
check('off', queue_enabled(), False)
delattr(shared.opts, QUEUE_ENABLED) if hasattr(shared.opts, QUEUE_ENABLED) else None
check('never set: on, as by default', queue_enabled(), True)

# --------------------------------------------------------- the Queue buttons
generate = types.SimpleNamespace(elem_id='txt2img_generate')
capture._found.clear()
switch(False)
capture.on_component(generate, elem_id='txt2img_generate')
check('off: no Queue button beside Generate', list(capture._found), [])
switch(True)
capture.on_component(generate, elem_id='txt2img_generate')
check('on: one', (list(capture._found), getattr(capture._found.get('txt2img', {}).get('queue'), 'elem_id', None)),
      (['txt2img'], 'txt2img_queue'))
capture._found.clear()

# -------------------------------------------------------------- Start, Stop
switch(False)
check('off: the queue does not start', (runner.start(), jobs.running(runner.KIND)),
      ({'started': False, 'missing': [], 'off': True}, False))
jobs.join(5)
stopped = []
real_stop = runner.stop
runner.stop = lambda: stopped.append(True) or True
from model_manager.ui import settings as ui_settings    # noqa: E402
ui_settings._queue_enabled_changed()
switch(True)
ui_settings._queue_enabled_changed()
runner.stop = real_stop
check('turned off, a running queue is stopped; turned on, nothing is', stopped, [True])

# ------------------------------------------------------------ the startup
# The WebUI builds its tabs once, at start: the Queue tab is left out when the
# switch is off. The tabs' own markup is stood in for.
tabs_callbacks = []
script_callbacks.on_ui_tabs = lambda fn: tabs_callbacks.append(fn)
fake_ui = types.ModuleType('model_manager.ui')
fake_ui.create_queue_ui = lambda: 'queue markup'
fake_ui.create_generations_ui = lambda: 'generations markup'
fake_ui.create_ui = lambda: [('model manager markup', 'Model Manager', 'model_manager_tab')]
fake_ui.create_civitai_browser_ui = lambda: 'browser markup'
fake_ui.on_ui_settings = lambda *a, **k: None
real_ui = sys.modules['model_manager.ui']
sys.modules['model_manager.ui'] = fake_ui
spec = importlib.util.spec_from_file_location('mm_ui_script', os.path.join(ROOT, 'scripts', 'model_manager_ui.py'))
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)
sys.modules['model_manager.ui'] = real_ui
names = lambda: [name for _, name, _ in tabs_callbacks[0]()]
switch(True)
check('on: the Queue first', names()[0], 'Queue')
switch(False)
check('off: not created at all', names(), ['Generations', 'Model Manager', 'Civitai Browser'])

# ------------------------------------------------------------ the page told
from model_manager.api import setup_api                  # noqa: E402
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))
switch(False)
check('ui-options tells the page it is off', client.get('/model-manager/ui-options').json().get('queue_enabled'), False)
switch(True)
check('and on', client.get('/model-manager/ui-options').json().get('queue_enabled'), True)

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
