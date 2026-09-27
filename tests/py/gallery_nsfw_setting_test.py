"""
Whether a gallery hides explicit images is its own setting.

"Preview: Use least NSFW image" once decided two things: which image a card
shows, and whether the Model Manager's gallery opened with explicit images
hidden. Turning it off for newer thumbnails showed explicit images in every
gallery, and the label said nothing of it. The Civitai Browser's gallery
followed neither: it opened as the search's Include NSFW models was set, which
chooses models, not images.

Now model_manager_gallery_hide_nsfw decides how both galleries open, the old
setting only the thumbnail, and the new one starts from what the old one said.
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
from model_manager.api import setup_api                  # noqa: E402
from model_manager.ui.settings import carry_over_gallery_nsfw   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'gallery_nsfw_setting')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


OLD, NEW = 'model_manager_preview_least_nsfw', 'model_manager_gallery_hide_nsfw'

# ------------------------------------------------------------- carrying over
check('a fresh install hides them, as the old default did', carry_over_gallery_nsfw({}), True)
check('whoever had turned the old setting on keeps them hidden',
      carry_over_gallery_nsfw({OLD: True}), True)
check('whoever had turned it off keeps seeing them',
      carry_over_gallery_nsfw({OLD: False}), False)
check('once the new setting has a value, the old one no longer decides it',
      carry_over_gallery_nsfw({OLD: False, NEW: True}), None)

# ------------------------------------------------- what the endpoints read
db, facts = fixtures.build(WORK)
dbmod._db_instance = db
app = FastAPI()
setup_api(app)
client = TestClient(app)


def details_hide():
    body = client.get('/model-manager/models/details',
                      params={'path': facts['linked_paths'][0]}).json()
    return body['model']['images_state']['hide_nsfw_images']


for thumb in (True, False):
    for gallery in (True, False):
        setattr(opts, OLD, thumb)
        setattr(opts, NEW, gallery)
        check('Model Manager gallery with thumbnail=%s, gallery=%s opens hiding %s'
              % (thumb, gallery, gallery), details_hide(), gallery)
        check('and the Civitai Browser is told the same (thumbnail=%s, gallery=%s)'
              % (thumb, gallery),
              client.get('/model-manager/ui-options').json().get('gallery_hide_nsfw'), gallery)

# The Civitai Browser asks this each time it opens a model, for both switches.
for hide in (True, False):
    setattr(opts, 'model_manager_hide_promptless_images', hide)
    check('the Civitai Browser is told whether to hide images without a prompt (%s)' % hide,
          client.get('/model-manager/ui-options').json().get('hide_promptless_images'), hide)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
