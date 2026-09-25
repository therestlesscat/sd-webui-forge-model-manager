"""
"Only Show Models with SFW images" in the Model Manager.

The same question the Civitai Browser asks: are any of the first 20 images of
the version the card shows - in the order its gallery shows them - above
PG-13, or not rated at all? If so the model is left out. So is a model with
no images: nothing shows it does not generate NSFW.

Only the shown version is judged, and a model it rules out is not shown
through another of its versions instead. Asking it of every image of every
version was the first attempt: 13.7 s against a library of 101,759 images,
where the unfiltered grid takes 1.1.
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

webui_stub.install()                                    # before model_manager

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'mm_sfw')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db

app = FastAPI()
setup_api(app)
client = TestClient(app)


def listed(**params):
    """Model ids (or file names, for files Civitai does not know) the grid lists."""
    r = client.get('/model-manager/models', params=dict(page_size=100, **params))
    body = r.json()
    return {m.get('model_id') or m.get('file_name') for m in body.get('models', [])}, body['total']


def set_levels(version_id, *levels):
    """Give a version exactly these images, in this gallery order."""
    with db._cursor() as cursor:
        cursor.execute("DELETE FROM images WHERE version_id = ?", (version_id,))
        for n, level in enumerate(levels):
            # Pages and ids both run in order, as a sync stores them; two
            # pages, so the order is page first and id within it.
            cursor.execute(
                "INSERT INTO images (id, version_id, page, effective_nsfw_level, data) "
                "VALUES (?, ?, ?, ?, '{}')",
                (version_id * 1000 + n, version_id, 1 + n // 10, level))


def versions_of(model_id):
    with db._cursor() as cursor:
        cursor.execute("SELECT id FROM model_versions WHERE model_id = ? ORDER BY id", (model_id,))
        return [row['id'] for row in cursor.fetchall()]


def shown_version(model_id):
    """The version the grid shows for a model - the one that is judged."""
    body = client.get('/model-manager/models', params={'page_size': 100}).json()
    return next(m['id'] for m in body['models'] if m.get('model_id') == model_id)


clean, racy, unrated, blocked, late, two_versions, two_racy = (
    facts['checkpoint_ids'][2], facts['checkpoint_ids'][3], facts['lora_ids'][0],
    facts['lora_ids'][1], facts['lora_ids'][2],
    facts['checkpoint_ids'][0], facts['checkpoint_ids'][1])

set_levels(versions_of(clean)[0], 1, 2, 1)
set_levels(versions_of(racy)[0], 1, 1, 4)
set_levels(versions_of(unrated)[0], 1, 64)
set_levels(versions_of(blocked)[0], 2, 2, 32)
set_levels(versions_of(late)[0], *([1] * 20 + [16]))      # the 21st is not looked at

# Two models with two versions each: one whose card version is clean and whose
# other is not, and one the other way round.
shown = shown_version(two_versions)
set_levels(shown, 1, 2)
set_levels(next(v for v in versions_of(two_versions) if v != shown), 1, 8)
shown_racy = shown_version(two_racy)
set_levels(shown_racy, 1, 8)
set_levels(next(v for v in versions_of(two_racy) if v != shown_racy), 1, 2)

everything, total_all = listed()
kept, total_kept = listed(sfw_only='true')

check('a model whose images are all PG or PG-13 is kept', clean in kept)
check('one R image is enough to leave a model out', racy in kept, False)
check('as is an image nobody rated', unrated in kept, False)
check('and a Blocked one', blocked in kept, False)
check('only the first 20 are looked at, as in the Civitai Browser: '
      'an XXX image 21st in the gallery does not count', late in kept)
check('the version the card shows is what is judged', two_versions in kept)
check('and a model it rules out is not shown through its clean version instead',
      two_racy in kept, False)
local_only = {os.path.basename(p) for p in facts['local_only_paths']}
check('files with no images at all are left out: nothing shows they are safe',
      local_only & kept, set())
set_levels(versions_of(clean)[0])
check('as is a Civitai model whose card version has none',
      clean in listed(sfw_only='true')[0], False)
set_levels(versions_of(clean)[0], 1, 2, 1)
check('the total counts the same models the page lists', total_kept, len(kept))
check('and without the box, nothing is left out',
      {clean, racy, two_racy} <= everything, True)
check('so the box only ever takes away', kept < everything, True)

# The sync dialog asks the same endpoint for paths, so "these results" means
# what the grid shows.
r = client.get('/model-manager/models', params={'sfw_only': 'true', 'paths_only': 'true'})
paths = r.json().get('paths', [])
with db._cursor() as cursor:
    cursor.execute("SELECT file_path FROM model_versions WHERE model_id = ?", (racy,))
    racy_paths = {row['file_path'] for row in cursor.fetchall()}
check('a sync of "these results" leaves out what the grid left out',
      bool(racy_paths & set(paths)), False)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
