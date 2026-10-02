"""
The counts beside a gallery's switches, and in its banner, mean the same
whoever counts them (#74).

A page counts its images in Python (gallery.switch_counts, through
filter_images for Civitai images); the banner counts every stored image in
SQL (ImagesOps.get_image_counts). AGENTS.md: a switch's number holds when it
is flipped - which needs the two to agree, for every combination of the
switches. They were written apart, and nothing held them to each other.

Prompts padded with tabs or newlines are left out on purpose: Python's
strip() and SQL's TRIM disagree on them, which is #61's to settle.
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
webui_stub.install()

from model_manager.db import ModelsDatabase              # noqa: E402
from model_manager.gallery import filter_images, switch_counts   # noqa: E402
from model_manager.nsfw import SFW_MAX                   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'switch_counts')
os.makedirs(WORK, exist_ok=True)
for name in os.listdir(WORK):
    os.remove(os.path.join(WORK, name))

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# Every kind there is: safe and explicit, each with a prompt worth reading,
# a short one, an empty one, and none - so no count is zero by accident.
PROMPTS = ['a prompt long enough to read', 'ok', '', None]
IMAGES = []
for level in (1, 2, 4, 8, 16):
    for prompt in PROMPTS:
        meta = None if prompt is None else {'prompt': prompt}
        IMAGES.append({'id': len(IMAGES) + 1, 'url': 'u%d' % len(IMAGES), 'browsingLevel': level,
                       'meta': meta})

db = ModelsDatabase(WORK, custom_db_path=os.path.join(WORK, 'counts.db'))
VERSION = 4242
db.store_images(VERSION, 1, IMAGES)
KEYS = ('total', 'filtered', 'hidden_nsfw', 'hidden_promptless', 'hidden_both', 'hidden',
        'nsfw_count', 'promptless_count', 'promptless_total')

for hide_nsfw in (False, True):
    for hide_promptless in (False, True):
        shown, py = filter_images(IMAGES, hide_nsfw, hide_promptless)
        sql = db.get_image_counts(VERSION, max_nsfw_level=SFW_MAX if hide_nsfw else None,
                                  require_prompt=hide_promptless)
        check('hide NSFW %s, hide unusable prompts %s: the page counts as the banner does'
              % (hide_nsfw, hide_promptless),
              {k: py[k] for k in KEYS}, {k: sql[k] for k in KEYS})
        check('and shows the images it counts as shown (%s, %s)' % (hide_nsfw, hide_promptless),
              len(shown), py['filtered'])

_, both = filter_images(IMAGES, True, True)
check('none of the counts is zero by accident', all(both[k] for k in KEYS), True)

# Every gallery counts through one function; how it tells safe and readable
# is the only part its own. The same answers from the same verdicts:
safe = [img['browsingLevel'] <= SFW_MAX for img in IMAGES]
readable = [bool(img['meta'] and len((img['meta'].get('prompt') or '').strip()) >= 4) for img in IMAGES]
check('switch_counts, given the verdicts, counts as filter_images does',
      switch_counts(IMAGES, safe, readable, True, True)[1], both)

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
