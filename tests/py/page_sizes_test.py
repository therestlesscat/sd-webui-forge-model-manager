"""
Page sizes per tab, and a sync's own (#230).

One setting, "Shared: images per page", paged every gallery and decided how
many images a sync kept: set to 5 for Civitai's images, your own loaded 5 at
a time too, and a sync kept 5. Now each tab that has pages reads its own -
the Model Manager's Civitai images, the Civitai Browser's images, the Model
Manager's Your generations - and a sync its own; the Generations tab and the
Civitai Images tab, which load as you scroll, read none: a fixed part.

Carrying the old value over is settings_api_test's: it registers the
settings through Forge's own options, and importing ui/settings.py loads
Gradio.
"""
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

import model_manager.gallery as gallery                  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


MM = 'model_manager_mm_images_per_page'
CB = 'model_manager_cb_images_per_page'
GEN = 'model_manager_mm_generations_per_page'
SYNC = 'model_manager_sync_images_per_version'
NEW = (MM, CB, GEN, SYNC)

# Looked up, not imported: on the code before #230 these checks fail, rather than the suite.
def reader(name):
    return getattr(gallery, name, lambda: None)


# ---------------------------------------------------------- each its own
for key, size in zip(NEW, (5, 8, 7, 15)):
    setattr(opts, key, size)
check('each tab reads its own: the Model Manager\'s images, the Civitai Browser\'s, Your generations, a sync',
      [reader(n)() for n in ('mm_images_page_size', 'cb_images_page_size', 'generations_page_size',
                             'sync_image_count')], [5, 8, 7, 15])
check('a sync of a gallery with nothing stored fetches the sync\'s number', gallery.refresh_size(0, False), 15)
check('and one keeping the count, what is stored when that is more', gallery.refresh_size(150, True), 150)
check('the tabs that scroll read none of them: a fixed part',
      (gallery.gallery_page_size(), getattr(gallery, 'TILE_PART', None)), (100, 100))

setattr(opts, MM, 3)
setattr(opts, CB, 500)
setattr(opts, GEN, 'many')
check('kept to range: 3 reads as 5, 500 as 200, nonsense as the default',
      [reader(n)() for n in ('mm_images_page_size', 'cb_images_page_size', 'generations_page_size')],
      [5, 200, 100])

print('\n'.join('FAIL ' + f for f in fails) if fails else 'All checks passed.')
sys.exit(1 if fails else 0)
