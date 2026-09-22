"""
upsert_version(): an absent value must not erase a present one.

The case that prompted this is a scan reading a thin .civitai.info - one with
no trainedWords, no publishedAt, no files - and writing its emptiness over a
row that had all three. The scan cannot tell "this model has no trigger words"
from "this file does not mention any", so the database must not treat them the
same.
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

WORK = os.path.join(TESTS, 'work', 'clobber_test')
import json
import os
import shutil
import sqlite3
import sys



def as_json(value, default=None):
    """Read a JSON column that the code under test may have nulled."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# Every row this examines is written below, so an empty library is
# exactly right - and one nobody has synced cannot drift.
db, facts = fixtures.build(WORK)
DB = facts['db_path']

PATH = r'Z:\clobber\subject.safetensors'
RICH = {
    "id": 4242, "model_id": 99, "file_path": PATH,
    "file_name": "subject.safetensors", "file_extension": ".safetensors",
    "file_size": 1234, "file_modified": "2026-01-01T00:00:00",
    "version_name": "v3", "base_model": "SDXL 1.0",
    "published_at": "2025-05-05T00:00:00", "created_at": "2025-05-04T00:00:00",
    "nsfw_level": 4, "trained_words": ["trigger one", "trigger two"],
    "description": "the real description",
    "stats_download_count": 5000, "stats_thumbs_up": 120,
    "file_hashes": {"sha256": "A" * 64, "autov2": "B" * 10},
    "has_civitai_data": True,
}
db.upsert_version(RICH)


def row():
    raw = sqlite3.connect(DB)
    raw.row_factory = sqlite3.Row
    r = raw.execute('SELECT * FROM model_versions WHERE file_path = ?', (PATH,)).fetchone()
    raw.close()
    return r


before = row()
check('the rich row went in', before['version_name'], 'v3')
check('with its trigger words', as_json(before['trained_words'], []), ['trigger one', 'trigger two'])
check('and its hashes', as_json(before['file_hashes'], {}).get('sha256'), 'A' * 64)

# What scan_service builds from a stub sidecar: a name and a base model, and
# silence about everything else.
STUB = {
    "id": 4242, "model_id": 99, "file_path": PATH,
    "file_name": "subject.safetensors", "file_extension": ".safetensors",
    "file_size": 1234, "file_modified": "2026-01-01T00:00:00",
    "version_name": "v3", "base_model": "SDXL 1.0",
    "published_at": None, "created_at": None,
    "nsfw_level": 64, "trained_words": [], "description": None,
    "stats_download_count": 0, "stats_thumbs_up": 0,
    "has_civitai_data": True,
}
db.upsert_version(STUB)
after = row()

check('trigger words survive a silent sidecar',
      as_json(after['trained_words'], []), ['trigger one', 'trigger two'])
check('so does the publish date', after['published_at'], '2025-05-05T00:00:00')
check('and the created date', after['created_at'], '2025-05-04T00:00:00')
check('and the description', after['description'], 'the real description')
check('and the download count', after['stats_download_count'], 5000)
check('and the thumbs', after['stats_thumbs_up'], 120)
check('and the NSFW level, rather than dropping to Unknown', after['nsfw_level'], 4)
check('and the hashes, so nothing has to be re-read',
      as_json(after['file_hashes'], {}).get('sha256'), 'A' * 64)
check('and the ids', (after['id'], after['model_id']), (4242, 99))

# A real value still replaces a real value - this must not become write-once.
UPDATED = dict(STUB)
UPDATED.update({
    "trained_words": ["a new trigger"], "published_at": "2026-02-02T00:00:00",
    "description": "a newer description", "stats_download_count": 9000,
    "stats_thumbs_up": 300, "nsfw_level": 8,
    "file_hashes": {"sha256": "C" * 64},
})
db.upsert_version(UPDATED)
latest = row()
check('a real update still lands', as_json(latest['trained_words'], []), ['a new trigger'])
check('so does a newer date', latest['published_at'], '2026-02-02T00:00:00')
check('and a newer description', latest['description'], 'a newer description')
check('and newer stats', (latest['stats_download_count'], latest['stats_thumbs_up']), (9000, 300))
check('and a newer level', latest['nsfw_level'], 8)
check('and newer hashes', as_json(latest['file_hashes'], {}).get('sha256'), 'C' * 64)

# The file's own facts are the file's own: those always come from disk.
MOVED = dict(STUB)
MOVED.update({"file_size": 8888, "file_modified": "2026-03-03T00:00:00"})
db.upsert_version(MOVED)
moved = row()
check('file size always reflects the file', moved['file_size'], 8888)
check('and so does its timestamp', moved['file_modified'], '2026-03-03T00:00:00')

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
