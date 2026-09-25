"""
An image rated PG whose prompt asks for something explicit is not PG.

A short list of words, bundled and added to in the settings, raises a PG or
PG-13 image whose prompt uses one to X - everywhere, because image_level()
is what every view judges by. Stored images carry the verdict stamped when
they were stored, so a change of words restamps them, once, from the stored
payloads; a safe cover that is no longer safe is cleared, and the grid falls
back to the version's first image that still is.

The words here are made up. The prompt cases are shared with the browser's
test (tests/nsfw_prompt_cases.json), so the two must agree.
"""
import json
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
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.nsfw as nsfw                        # noqa: E402
import model_manager.prompt_levels as prompt_levels      # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'nsfw_prompt')
os.makedirs(WORK, exist_ok=True)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


CASES = json.load(open(os.path.join(TESTS, 'nsfw_prompt_cases.json'), encoding='utf-8'))

# The bundled list, stood in by a file of made-up words.
bundled = os.path.join(WORK, 'words.txt')
open(bundled, 'w', encoding='utf-8').write('# a comment\n' + '\n'.join(CASES['words']) + '\n')
nsfw.PROMPT_WORDS_FILE = bundled
nsfw._bundled = None

# --------------------------------------------------------------- the rule
for case in CASES['cases']:
    check(case['why'], nsfw.image_level(case['image']), case['level'])

check('Civitai\'s rating itself is kept apart', nsfw.rated_level({'browsingLevel': 1,
      'meta': {'prompt': 'zorp'}}), 1)
check('the bundled list is read, its comments not',
      sorted(nsfw.prompt_words()), sorted(CASES['words']))

opts.model_manager_nsfw_prompt_words = 'Glorb, snib\nquux'
check('words added in the settings count too, commas or lines, any case',
      nsfw.image_level({'browsingLevel': 1, 'meta': {'prompt': 'a quux'}}), nsfw.X)
before = nsfw.prompt_words_fingerprint()
opts.model_manager_nsfw_prompt_words = ''
check('and the fingerprint follows the words', before != nsfw.prompt_words_fingerprint())

# A stripped showcase is judged by Civitai's rating: Civitai strips by its own.
flagged_pg = {'url': 'https://example.invalid/f.jpeg', 'browsingLevel': 1, 'meta': {'prompt': 'zorp'}}
clean_pg = {'url': 'https://example.invalid/c.jpeg', 'browsingLevel': 1, 'meta': {'prompt': 'a cat'}}
check('a showcase of PG images is still "maybe stripped", a flagged one among them or not',
      nsfw.showcase_is_complete([flagged_pg, clean_pg]), False)
check('its safe cover is the first image that is safe by prompt as well',
      nsfw.version_covers([flagged_pg, clean_pg], complete=True),
      ('https://example.invalid/f.jpeg', 'https://example.invalid/c.jpeg'))

# ---------------------------------------------------- stored images, stamped
db, facts = fixtures.build(WORK)
dbmod._db_instance = db
version = facts['version_ids'][0]
path = next(p for p in facts['linked_paths'] if db.get_version(p)['id'] == version)
with db._cursor() as cursor:
    cursor.execute("DELETE FROM images WHERE version_id = ?", (version,))
snib_pg = {'id': 9101, 'url': 'https://example.invalid/snib.jpeg', 'browsingLevel': 1,
           'meta': {'prompt': 'a snib, 1girl'}}
zorp_pg = {'id': 9102, 'url': 'https://example.invalid/zorp.jpeg', 'browsingLevel': 1,
           'meta': {'prompt': 'a zorp'}}
plain_pg = {'id': 9103, 'url': 'https://example.invalid/plain.jpeg', 'browsingLevel': 1,
            'meta': {'prompt': 'a quiet lake'}}
db.store_images(version, 1, [snib_pg, zorp_pg, plain_pg])


def stored(image_id):
    with db._cursor() as cursor:
        cursor.execute("SELECT effective_nsfw_level FROM images WHERE id = ?", (image_id,))
        return cursor.fetchone()[0]


check('an image is judged by its prompt when stored', (stored(9101), stored(9102), stored(9103)),
      (1, nsfw.X, 1))
check('so a gallery with NSFW hidden leaves it out',
      [i['id'] for i in db.get_images(version, max_nsfw_level=nsfw.SFW_MAX)], [9101, 9103])

# The words change: "snib" is added. Its image was stored as PG.
prompt_levels.bring_up_to_date(db)            # the current words, recorded
with db._cursor() as cursor:
    cursor.execute("UPDATE model_versions SET safe_cover_url = ? WHERE file_path = ?",
                   ('https://example.invalid/snib.jpeg', path))
opts.model_manager_nsfw_prompt_words = 'snib'
changed = prompt_levels.bring_up_to_date(db)
check('a change of words restamps what is stored', (changed >= 1, stored(9101)), (True, nsfw.X))
with db._cursor() as cursor:
    cursor.execute("SELECT safe_cover_url FROM model_versions WHERE file_path = ?", (path,))
    check('a safe cover no longer safe is cleared', cursor.fetchone()[0], '')
rows, _ = db.query_models_grouped(limit=500)
preview = next(r for r in rows if r['id'] == version)['preview_url']
check('and the grid shows the version\'s first image still safe', preview,
      'https://example.invalid/plain.jpeg')
check('the same words again restamp nothing', prompt_levels.bring_up_to_date(db), None)
opts.model_manager_nsfw_prompt_words = ''
prompt_levels.bring_up_to_date(db)
check('taking a word out puts Civitai\'s rating back', stored(9101), 1)

# -------------------------------------------------- run in the background
# At start, and on each settings save. Asked again mid-pass, it runs once
# more afterwards - with the words as they are then - and never two at once.
import threading                                          # noqa: E402
import time                                               # noqa: E402
passes, overlapping, busy = [], [], threading.Event()
def slow_pass(db_):
    if busy.is_set():
        overlapping.append(True)
    busy.set()
    time.sleep(0.2)
    passes.append(1)
    busy.clear()
real_pass = prompt_levels.bring_up_to_date
prompt_levels.bring_up_to_date = slow_pass
try:
    for _ in range(3):
        prompt_levels.start_in_background()
    for _ in range(50):
        time.sleep(0.05)
        if not prompt_levels._running:
            break
finally:
    prompt_levels.bring_up_to_date = real_pass
check('three asks while one runs: that pass and one more, never two at once',
      (len(passes), overlapping), (2, []))

# ------------------------------------------------------ for the browser
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))
opts.model_manager_nsfw_prompt_words = 'snib'
check('the browser is sent every word, bundled and added',
      client.get('/model-manager/nsfw-prompt-words').json()['words'], ['blick', 'snib', 'zorp'])

# ----------------------------------------------------- the list that ships
nsfw.PROMPT_WORDS_FILE = os.path.join(ROOT, 'model_manager', 'data', 'nsfw_prompt_words.txt')
nsfw._bundled = None
check('the bundled list is there, and has words', len(nsfw.prompt_words()) >= 1)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
