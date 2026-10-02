"""
What every tab's header and downloads panel are drawn from (#85).

The settings gear and the downloads panel's header were written out in each
tab's Python - the gear's button and drawing three times, Pause all, Resume
all and Dismiss all twice - while ui/header.py had a helper only the
Generations tab used. And that helper's gear said "TAB" from 0.44.21: the
placeholder it replaced had changed its quotes, and a suite reading the
template, not the drawn tab, saw "TAB" as it should be.

Here each tab is drawn, as gr.HTML is handed it: its gear opens the settings
window on its own tab, and comes from the one helper; both downloads panels
come from theirs, with their own tab's ids.
"""
import contextlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

try:
    import gradio as gr
except ImportError:
    print('gradio is not installed; run this with the WebUI\'s python')
    sys.exit(0)

drawn = []


class Blocks(contextlib.nullcontext):
    def __init__(self, *args, **kwargs):
        super().__init__(self)


gr.Blocks = Blocks
gr.HTML = lambda value='', **kwargs: drawn.append(value)

from model_manager.ui import header, tab_civitai_browser, tab_generations, tab_model_manager  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def draw(make):
    drawn.clear()
    make()
    return '\n'.join(drawn)


TABS = {'model_manager': tab_model_manager.create_ui, 'civitai_browser': tab_civitai_browser.create_civitai_browser_ui,
        'generations': tab_generations.create_generations_ui}
pages = {tab: draw(make) for tab, make in TABS.items()}

gears = {tab: re.findall(r'<button[^>]*class="mm-settings-btn"[^>]*>', page) for tab, page in pages.items()}
check('each tab draws one gear, opening the settings window on its own tab',
      {tab: [re.search(r'data-tab="([^"]*)"', g).group(1) for g in found] for tab, found in gears.items()},
      {tab: [tab] for tab in TABS})
check('and every gear is the helper\'s, as is the version beside it',
      [tab for tab, page in pages.items() if header.header_actions(tab) not in page], [])

for prefix, tab in (('mm', 'model_manager'), ('cb', 'civitai_browser')):
    panel = getattr(header, 'downloads_panel', None)
    check(f'the {tab} tab\'s downloads panel is the helper\'s',
          bool(panel) and panel(prefix) in pages[tab], True)
    check(f'with its own ids: the list, and Pause all, Resume all, Dismiss all',
          [f'id="{prefix}_{name}"' in pages[tab] for name in
           ('downloads', 'download_list', 'downloads_pause_all', 'downloads_resume_all', 'downloads_dismiss_all')],
          [True] * 5)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
