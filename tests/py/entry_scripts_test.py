"""
The two scripts Forge loads, loaded as Forge loads them: one copy of the
extension, and its endpoints back after Settings -> Reload UI.

model_manager_ui.py used to delete every model_manager module after the
recording script and the settings had imported theirs, and import the API
afresh. Two copies ran side by side: turning the update check on asked the
copy the page never reads, and each copy had its own database and download
service. Reload UI clears every callback and runs the scripts again, so the
script registers the API's app_started itself, each time.
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
    import fastapi                                       # noqa: F401
    import gradio                                        # noqa: F401
except ImportError:
    print('fastapi or gradio is not installed; run this with the WebUI\'s python')
    sys.exit(0)

from modules import script_callbacks                     # noqa: E402  (webui_stub's)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# What Forge's script_callbacks keeps, and clears on Reload UI.
registered = {}
for name in ('on_app_started', 'on_ui_settings', 'on_ui_tabs', 'on_image_saved'):
    setattr(script_callbacks, name, (lambda n: lambda fn: registered.setdefault(n, []).append(fn))(name))

# The always-on script's base class.
scripts = types.ModuleType('modules.scripts')
scripts.AlwaysVisible = object()
scripts.Script = type('Script', (object,), {})
sys.modules['modules.scripts'] = scripts
sys.modules['modules'].scripts = scripts


def load(name):
    """A scripts/*.py, run as Forge's script_loading.load_module runs it."""
    path = os.path.join(ROOT, 'scripts', name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_all():
    # Forge loads scripts/ in filename order: the recording script first.
    return load('model_manager_generations.py'), load('model_manager_ui.py')


def current(name):
    return sys.modules.get(name)


recorder, ui_script = load_all()

# --------------------------------------------------------------- one copy
check('the recording script records with the extension the API uses',
      recorder.generations is current('model_manager.generations'), True)
check('its image_saved hook is that copy\'s',
      registered['on_image_saved'][0] is getattr(current('model_manager.generations'), 'image_saved', None), True)
settings = current('model_manager.ui.settings')
check('turning the update check on asks the copy the page reads',
      settings is not None and settings.check_soon is current('model_manager.update_check').check_soon, True)
check('the settings callback is that copy\'s',
      registered['on_ui_settings'][0] is getattr(current('model_manager.ui'), 'on_ui_settings', None), True)
check('the API registered once',
      [fn.__module__ for fn in registered.get('on_app_started', [])], ['model_manager.api'])
check('and it is the API in sys.modules',
      registered['on_app_started'][0] is current('model_manager.api').on_app_started, True)

# --------------------------------------------------------------- Reload UI
# Forge clears every callback and runs the scripts again, in this process.
before = {name: module for name, module in sys.modules.items() if name.startswith('model_manager')}
registered.clear()
load_all()
check('after Reload UI the endpoints are registered again, once',
      [fn.__module__ for fn in registered.get('on_app_started', [])], ['model_manager.api'])
check('and every callback again', sorted(registered), ['on_app_started', 'on_image_saved', 'on_ui_settings',
                                                       'on_ui_tabs'])
after = {name: module for name, module in sys.modules.items() if name.startswith('model_manager')}
check('still one copy of the extension - the one already loaded',
      [name for name, module in before.items() if after.get(name) is not module], [])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
