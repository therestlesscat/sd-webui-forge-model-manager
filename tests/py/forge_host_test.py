"""
The extension's settings, read one way (model_manager/forge_host.py, #82).

Each setting used to be read where it was used, with its default written
beside every read. DEFAULTS is the one list now: Settings -> Model Manager
registers from it, and setting() reads by it. What is checked: registration
registers every setting in the table and no other, each with the table's
default; setting() answers what Forge holds, else the table's default - also
where there is no WebUI to ask - and refuses a name the table does not have;
every name the extension asks for, by a literal or a constant, is in the table.
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()

try:
    import gradio                                       # noqa: F401
except ImportError:
    print('gradio is not installed; run this with the WebUI\'s python')
    sys.exit(0)

from modules import shared                               # noqa: E402  (webui_stub's)
import model_manager.forge_host as host                  # noqa: E402
from model_manager.ui import settings as ui_settings     # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# --------------------------------------------------------------- registering
# Forge's option types, as far as registering needs them.
class Info(object):
    def __init__(self, default=None, **kwargs):
        self.default = default

    def info(self, *args, **kwargs):
        return self


class Registry(object):
    def __init__(self):
        self.data, self.options = {}, {}

    def add_option(self, key, info):
        self.options[key] = info


registry = Registry()
shared.opts, shared.OptionInfo, shared.OptionHTML = registry, Info, lambda *a, **k: Info()
try:
    ui_settings.on_ui_settings()
finally:
    shared.opts = opts
registered = {key: info.default for key, info in registry.options.items()
              if key != 'model_manager_modules_explanation'}       # text, not a setting
check('Settings -> Model Manager registers every setting in the table, and no other',
      sorted(registered), sorted(host.DEFAULTS))
check('each with the table\'s default',
      {key: value for key, value in registered.items() if value != host.DEFAULTS.get(key)}, {})

# ------------------------------------------------------------------- reading
opts.__dict__.clear()
check('a setting Forge holds nothing for reads as its default, every one of them',
      {key: host.setting(key) for key in host.DEFAULTS}, host.DEFAULTS)
opts.model_manager_page_size = 35
opts.model_manager_civitai_sfw_fill_page = True
check('one it holds reads as held',
      (host.setting('model_manager_page_size'), host.setting('model_manager_civitai_sfw_fill_page')),
      (35, True))
check('and there is a WebUI to ask', host.available(), True)

try:
    host.setting('model_manager_page_sise')
    check('a name the table does not have is refused', 'answered', 'KeyError')
except KeyError:
    pass

held = sys.modules['modules']
sys.modules['modules'] = None                            # no WebUI: importing it fails
try:
    check('with no WebUI there is none to ask', host.available(), False)
    check('and every setting reads as its default',
          {key: host.setting(key) for key in host.DEFAULTS}, host.DEFAULTS)
finally:
    sys.modules['modules'] = held

# An upscaler is named as Forge lists it (#134): by its file name in both
# WebUIs, but for the original Forge's built-ins ("R-ESRGAN 4x+"), and only
# once Forge has read it - at startup. So Forge is asked, by the file.
class Scaler:
    def __init__(self, name, data_path):
        self.name, self.data_path = name, data_path


shared = sys.modules['modules.shared']
ultrasharp = os.path.join(TESTS, 'work', 'ESRGAN', '4x-UltraSharp.pth')
shared.sd_upscalers = [Scaler('None', None), Scaler('Lanczos', None),
                       Scaler('R-ESRGAN 4x+', 'https://github.com/xinntao/RealESRGAN_x4plus.pth'),
                       Scaler('4x-UltraSharp', ultrasharp)]
check('an upscaler is named as Forge lists it, found by its file, case aside',
      host.upscaler_name(ultrasharp.upper()), '4x-UltraSharp')
check('one Forge does not list has no name',
      host.upscaler_name(os.path.join(TESTS, 'work', 'ESRGAN', 'added-since.pth')), None)
del shared.sd_upscalers
check('nor does any, with no list to ask', host.upscaler_name(ultrasharp), None)

# ----------------------------------------------------- every name asked for
# setting(KEY) with KEY a literal, or a module constant holding one. A name
# built at run time (a preset's, a card size's) is checked where it is built.
PACKAGE = os.path.join(ROOT, 'model_manager')
trees, constants = {}, {}
for folder, _, files in os.walk(PACKAGE):
    for name in files:
        if name.endswith('.py'):
            path = os.path.join(folder, name)
            trees[path] = ast.parse(open(path, encoding='utf-8').read(), path)
            for node in trees[path].body:
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            constants.setdefault(target.id, set()).add(node.value.value)

asked, unknown = 0, []
for path, tree in sorted(trees.items()):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'setting' and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant):
                names = {arg.value}
            elif isinstance(arg, ast.Name) and arg.id in constants:
                names = constants[arg.id]
            else:
                continue
            asked += 1
            unknown += ['%s:%d %s' % (os.path.relpath(path, ROOT), node.lineno, n)
                        for n in names if n not in host.DEFAULTS]
check('every setting the extension asks for by name is in the table', unknown, [])
check('and it asks for them that way (a count that cannot be zero)', asked > 20, True)

# ---------------------------------------- which embeddings a model loads
# Forge loads an embedding only if it is made for the model's kind, and skips
# the rest without a word (#179): each engine's embedding_expected_shape. The
# two WebUIs run different engines, read from their own code.
real_is_neo = host.is_neo
# Asked by name, so code without it fails these checks rather than the suite.
embedding_kind = getattr(host, 'embedding_kind', lambda *a: 'missing')
kinds = {}
for neo in (True, False):
    host.is_neo = lambda neo=neo: neo
    kinds[neo] = [embedding_kind(c) for c in ('SD15', 'SDXL', 'Flux', 'Chroma', 'QwenImage', 'Mugen', 'SD20', 'SD3')]
host.is_neo = real_is_neo
check('Neo: SD 1.5 and Flux load SD 1.x embeddings, SDXL and Mugen SDXL ones, the rest none',
      kinds[True], ['sd', 'xl', 'sd', 'none', 'none', 'xl', 'none', 'none'])
check('the original Forge: SD 2.x its own kind, SD 3 SD 1.x ones, and no Mugen',
      kinds[False], ['sd', 'xl', 'sd', 'none', 'none', 'none', 'sd2', 'sd'])
check('with no model class, the UI preset says it for SD and SDXL alone, else not known',
      [embedding_kind(None, p) for p in ('sd', 'xl', 'flux', None)], ['sd', 'xl', None, None])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
