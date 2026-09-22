"""
upsert_civitai_model(): the same rule as upsert_version, one table over.

A scan reading a thin .civitai.info cannot see the licence flags or the vote
counts. It used to write a permissive default and a zero over both, so one
scan turned 51,834 thumbs into 0 and a real commercial-use list into nothing.
"""

import os
import sys

# The extension and the test helpers, found from this file rather than from a
# working directory, so a suite runs from anywhere.
HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fixtures                                       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'model_clobber_test')
import os
import shutil
import sqlite3
import sys



fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# Every row this examines is written below, so an empty library is
# exactly right - and one nobody has synced cannot drift.
db, facts = fixtures.build(WORK)
DB = facts['db_path']

MODEL_ID = 987654321
RICH = {
    "id": MODEL_ID, "name": "Subject", "description": "a real description",
    "type": "Checkpoint", "nsfw": True, "nsfw_level": 8,
    "tags": ["one", "two"], "creator": {"username": "someone", "image": "http://x/y.png"},
    "stats": {"downloadCount": 4321, "thumbsUpCount": 51834,
              "thumbsDownCount": 95, "ratingCount": 0},
    "stats_download_count": 4321, "stats_thumbs_up": 51834,
    "stats_thumbs_down": 95, "stats_rating": 4.99,
    "creator_username": "someone", "creator_image_url": "http://x/y.png",
    "allow_no_credit": False, "allow_commercial_use": ["Rent", "Image"],
    "allow_derivatives": False, "allow_different_license": False,
    "supports_generation": True,
}
db.upsert_civitai_model(RICH, from_civitai=True)


def row():
    raw = sqlite3.connect(DB)
    raw.row_factory = sqlite3.Row
    r = raw.execute('SELECT * FROM civitai_models WHERE id = ?', (MODEL_ID,)).fetchone()
    raw.close()
    return r


WATCH = ['allow_no_credit', 'allow_commercial_use', 'allow_derivatives',
         'allow_different_license', 'supports_generation', 'stats_thumbs_up',
         'stats_thumbs_down', 'stats_rating', 'stats_download_count',
         'description', 'nsfw_level', 'tags', 'creator_username']
before = {k: row()[k] for k in WATCH}
check('the rich row went in', before['stats_thumbs_up'], 51834)
check('with its commercial terms', 'Rent' in (before['allow_commercial_use'] or ''))
check('and its refusals recorded as 0, not lost', before['allow_derivatives'], 0)

# What a scan builds from a thin sidecar: a name, and silence.
THIN = {"id": MODEL_ID, "name": "Subject", "type": "Checkpoint",
        "description": None, "nsfw": None, "nsfw_level": 64, "tags": None,
        "creator_username": None, "creator_image_url": None,
        "stats_download_count": 0, "stats_thumbs_up": 0, "stats_thumbs_down": 0,
        "stats_rating": 0,
        "allow_no_credit": None, "allow_commercial_use": None,
        "allow_derivatives": None, "allow_different_license": None,
        "supports_generation": None}
db.upsert_civitai_model(THIN)
after = row()

for field in WATCH:
    check('%s survives a silent sidecar' % field, after[field], before[field])

# A real value still replaces a real one.
UPDATED = dict(THIN)
UPDATED.update({"stats_thumbs_up": 60000, "stats_thumbs_down": 100, "stats_rating": 4.5,
                "stats_download_count": 9999, "allow_derivatives": True,
                "allow_commercial_use": ["Sell"], "description": "newer",
                "nsfw_level": 16, "supports_generation": False})
db.upsert_civitai_model(UPDATED)
latest = row()
check('a newer vote count lands', latest['stats_thumbs_up'], 60000)
check('a newer rating lands', latest['stats_rating'], 4.5)
check('a newer description lands', latest['description'], 'newer')
check('a newer level lands', latest['nsfw_level'], 16)
check('a flag can be turned on', latest['allow_derivatives'], 1)
check('and off again', latest['supports_generation'], 0)
check('a newer commercial list lands', latest['allow_commercial_use'], '{Sell}')

# An absent flag stays NULL on a fresh row, which every query reads as unknown.
FRESH = {"id": MODEL_ID + 1, "name": "Never synced", "type": "LORA"}
db.upsert_civitai_model(FRESH)
raw = sqlite3.connect(DB)
raw.row_factory = sqlite3.Row
fresh = raw.execute('SELECT * FROM civitai_models WHERE id = ?', (MODEL_ID + 1,)).fetchone()
raw.close()
check('an unsaid flag is NULL, not a guess', fresh['allow_derivatives'], None)
check('which the licence filter can ask for as "unknown"',
      db.get_civitai_model(MODEL_ID + 1)['allow_derivatives'], True)

# And the reader agrees with query.py, which treats NULL as permissive.
check('the details panel reads unknown as allowed',
      db.get_civitai_model(MODEL_ID + 1)['allow_no_credit'], True)
check('a recorded refusal still reads as refused',
      db.get_civitai_model(MODEL_ID)['allow_no_credit'], False)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
