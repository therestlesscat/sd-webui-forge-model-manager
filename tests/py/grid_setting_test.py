"""
How each tab places its grid is a setting of its own (#240): Fast, the tab's
own placing and the default, or Classic, the browser's grid.

ui-options tells the page each tab's choice; a fresh install, or anything
but the two choices saved, is Fast. The settings register both with the two
choices, under the labels the plan named.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                       # noqa: E402

opts = webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import gradio                                       # noqa: F401
except ImportError:
    print('fastapi or gradio is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager import grids                          # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.forge_host import DEFAULTS            # noqa: E402

WORK = os.path.join(TESTS, 'work', 'grid_setting')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


GEN, GAL = 'model_manager_generations_grid', 'model_manager_gallery_grid'

check('the keys are the ones the page reads', (grids.GENERATIONS_GRID, grids.GALLERY_GRID), (GEN, GAL))
check('two choices, Fast first', grids.CHOICES, ('Fast', 'Classic'))
check('a fresh install is Fast in both tabs', (DEFAULTS[GEN], DEFAULTS[GAL]), ('Fast', 'Fast'))

# ------------------------------------------------- what the page is told
db, facts = fixtures.build(WORK)
dbmod._db_instance = db
app = FastAPI()
setup_api(app)
client = TestClient(app)


def told():
    body = client.get('/model-manager/ui-options').json()
    return body.get('generations_grid'), body.get('gallery_grid')


for name in (GEN, GAL):
    if hasattr(opts, name):
        delattr(opts, name)
check('nothing saved: both tabs are told Fast', told(), ('Fast', 'Fast'))
setattr(opts, GEN, 'Classic')
check('Classic for Generations: that tab alone is told so', told(), ('Classic', 'Fast'))
setattr(opts, GAL, 'Classic')
check('Classic for Civitai Images too', told(), ('Classic', 'Classic'))
said = []
for value in (None, '', 'classic', 'Placed', 0):
    setattr(opts, GEN, value)
    said.append(told()[0])
check('anything but the two choices saved: Fast', said, ['Fast'] * 5)
setattr(opts, GEN, ' Classic ')
check('a choice saved with spaces around it is still that choice', told()[0], 'Classic')

# ------------------------------------------------- what the settings register
# Forge's option types, as far as registering needs them (as forge_host_test).
from modules import shared                               # noqa: E402
from model_manager.ui import settings as ui_settings     # noqa: E402


class Info(object):
    def __init__(self, default=None, label='', component=None, component_args=None, **kwargs):
        self.default, self.label, self.component, self.component_args = default, label, component, component_args
        self.text = ''

    def info(self, text='', *args, **kwargs):
        self.text = text
        return self


class Registry(object):
    def __init__(self):
        self.data, self.options = {}, {}

    def add_option(self, key, info):
        self.options[key] = info


registry = Registry()
saved = shared.opts, getattr(shared, 'OptionInfo', None), getattr(shared, 'OptionHTML', None)
shared.opts, shared.OptionInfo, shared.OptionHTML = registry, Info, lambda *a, **k: Info()
try:
    ui_settings.on_ui_settings()
finally:
    shared.opts, shared.OptionInfo, shared.OptionHTML = saved
# Named as the registry names them on Forge's page (#320).
for key, label in ((GEN, 'Tiles the Generations Tab keeps on the page'),
                   (GAL, 'Tiles the Civitai Images Tab keeps on the page')):
    info = registry.options.get(key)
    check('%s is registered' % key, info is not None)
    if info is None:
        continue
    check('%s: its label' % key, info.label, label)
    check('%s: a dropdown of the two choices, each in words with its saved value' % key,
          (getattr(info.component, '__name__', ''), list((info.component_args or {}).get('choices', []))),
          ('Dropdown', [('Only those near the view', 'Fast'), ('All of them', 'Classic')]))
    check('%s: its default is Fast' % key, info.default, 'Fast')
    check('%s: its line says what each choice does' % key,
          ('Only those near the view: draws only the rows near' in info.text,
           'All of them: puts every tile on the page' in info.text),
          (True, True))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
