"""
"Your generations", one switch for all of it (#27): off, nothing is
recorded, the Generations tab is not created at the next start, and the page
hides it and each model's "Your generations" at once (generations_switch_test.mjs).
What was recorded is kept.

What is checked here: the switch as the server reads it - for recording and
for the UI, which differ only when the setting cannot be read - the startup
that leaves the Generations tab out, and ui-options telling the page.
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
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

from modules import script_callbacks, shared              # noqa: E402  (webui_stub's)
import model_manager.generations as gen                  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def switch(on):
    setattr(shared.opts, gen.RECORD_GENERATIONS, on)


# ------------------------------------------------------------- the switch
switch(True)
check('on: images are recorded, and their tabs shown', (gen._recording(), gen.generations_enabled()), (True, True))
switch(False)
check('off: neither', (gen._recording(), gen.generations_enabled()), (False, False))
delattr(shared.opts, gen.RECORD_GENERATIONS) if hasattr(shared.opts, gen.RECORD_GENERATIONS) else None
check('never set: on, as by default', gen.generations_enabled(), True)

# ------------------------------------------------------------ the startup
# The WebUI builds its tabs once, at start: the Generations tab is left out
# when the switch is off. The tabs' own markup is stood in for.
tabs_callbacks = []
script_callbacks.on_ui_tabs = lambda fn: tabs_callbacks.append(fn)
fake_ui = types.ModuleType('model_manager.ui')
fake_ui.create_generations_ui = lambda: 'generations markup'
fake_ui.create_ui = lambda: [('model manager markup', 'Model Manager', 'model_manager_tab')]
fake_ui.create_civitai_browser_ui = lambda: 'browser markup'
fake_ui.on_ui_settings = lambda *a, **k: None
sys.modules['model_manager.ui'] = fake_ui
spec = importlib.util.spec_from_file_location('mm_ui_script', os.path.join(ROOT, 'scripts', 'model_manager_ui.py'))
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)
names = lambda: [name for _, name, _ in tabs_callbacks[0]()]
switch(True)
check('on: the Generations tab first, before the Model Manager',
      names(), ['Generations', 'Model Manager', 'Civitai Browser'])
switch(False)
check('off: not created at all', names(), ['Model Manager', 'Civitai Browser'])

# ------------------------------------------------------------ the page told
from model_manager.api import setup_api                  # noqa: E402
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))
switch(False)
check('ui-options tells the page it is off', client.get('/model-manager/ui-options').json()['generations_enabled'], False)
switch(True)
check('and on', client.get('/model-manager/ui-options').json()['generations_enabled'], True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
