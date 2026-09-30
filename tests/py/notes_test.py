"""
Notes to the user, per release (model_manager/release_notes.py).

Some changes need everyone who updates to do something - run Scan Disk once
to read files again - and a changelog reaches only those who read it. So
each release that has one ships a note; a tab shows the notes that apply and
are not dismissed, and the settings window's "What's new" lists them all.

What is checked: which notes an install sees - a fresh one skips notes for
people updating; one from before notes were kept sees them all; one made by
an older version, those newer than it - that a dismissal is kept in the
database, and the notes file the extension ships: well formed, and every
action one the page knows.
"""
import json
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
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.release_notes as rn                 # noqa: E402
from model_manager.api import setup_api                  # noqa: E402
from model_manager.version import VERSION                # noqa: E402

WORK = os.path.join(TESTS, 'work', 'notes')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ---------------------------------------------------------- the shipped file
shipped = rn.load_notes()
check('the extension ships notes', len(shipped) > 0)
check('each note\'s id is its own', len({n['id'] for n in shipped}), len(shipped))
for note in shipped:
    where = note.get('id')
    check(f'{where}: every field', sorted(k for k in ('id', 'version', 'kind', 'audience', 'tabs', 'title', 'text')
                                          if not note.get(k)), [])
    check(f'{where}: a kind there is', note.get('kind') in rn.KINDS)
    check(f'{where}: an audience there is', note.get('audience') in rn.AUDIENCES)
    check(f'{where}: tabs there are', set(note.get('tabs') or []) <= set(rn.TABS) and bool(note.get('tabs')))
    check(f'{where}: a condition there is, if any', not note.get('when') or note['when'] in rn.CONDITIONS)
    check(f'{where}: important is true or absent', note.get('important', True) is True)
    check(f'{where}: replaces notes there are, older than it',
          all(old in {n['id'] for n in shipped}
              and rn.version_key(next(n for n in shipped if n['id'] == old)['version']) <= rn.version_key(note['version'])
              for old in note.get('replaces') or []))
    check(f'{where}: an action there is, if any',
          not note.get('action') or (note['action'].get('id') in rn.ACTIONS and bool(note['action'].get('label'))))
    check(f'{where}: from this version or before - a later one would never show',
          rn.version_key(note['version']) <= rn.version_key(VERSION))
common = open(os.path.join(ROOT, 'javascript', 'shared', 'common.mjs'), encoding='utf-8').read()
block = re.search(r'const NOTE_ACTIONS = \{(.*?)\n\};', common, re.S).group(1)
check('the page knows every action a note can name, and no other',
      sorted(re.findall(r'^\s+(\w+):', block, re.M)), sorted(rn.ACTIONS))

# ------------------------------------------------------ who sees which notes
path = os.path.join(WORK, 'notes.json')
NOTES = [
    {'id': 'feature-old', 'version': '0.30.0', 'kind': 'feature', 'audience': 'everyone',
     'tabs': ['model_manager'], 'title': 'Old feature', 'text': 't'},
    {'id': 'action-old', 'version': '0.30.0', 'kind': 'action', 'audience': 'update',
     'tabs': ['model_manager'], 'title': 'Old action', 'text': 't', 'action': {'id': 'settings', 'label': 'Go'}},
    {'id': 'action-new', 'version': VERSION, 'kind': 'action', 'audience': 'update',
     'tabs': ['model_manager', 'generations'], 'title': 'New action', 'text': 't'},
    {'id': 'browser-only', 'version': '0.35.0', 'kind': 'feature', 'audience': 'everyone',
     'tabs': ['civitai_browser'], 'title': 'Browser', 'text': 't'},
    {'id': 'future', 'version': '99.0.0', 'kind': 'feature', 'audience': 'everyone',
     'tabs': ['model_manager'], 'title': 'Not yet', 'text': 't'},
    {'id': 'shared-only', 'version': '0.30.0', 'kind': 'warning', 'audience': 'everyone',
     'when': 'custom_database', 'tabs': ['civitai_browser'], 'title': 'Shared database', 'text': 't'},
    {'id': 'rescan-again', 'version': '0.37.0', 'kind': 'action', 'audience': 'update', 'replaces': ['rescan-first'],
     'tabs': ['generations'], 'title': 'Scan again', 'text': 't'},
    {'id': 'rescan-first', 'version': '0.36.0', 'kind': 'action', 'audience': 'update',
     'tabs': ['generations', 'civitai_browser'], 'title': 'Scan', 'text': 't'},
]
db, facts = fixtures.build(WORK)          # which empties WORK first
dbmod._db_instance = db
with open(path, 'w', encoding='utf-8') as f:
    json.dump(NOTES, f)
real_file = rn.NOTES_FILE
rn.NOTES_FILE = path
ids = lambda notes: [n['id'] for n in notes]

check('a database made now says which version made it', db.get_info(rn.CREATED_BY), VERSION)
check('a fresh install sees what is for everyone, not what is for people updating - newest first',
      ids(rn.notes_for(db, 'model_manager')), ['feature-old'])
check('each tab its own', ids(rn.notes_for(db, 'civitai_browser')), ['browser-only'])
check('and never a note from a later version', 'future' in ids(rn.notes_for(db)), False)

# A note for installs with a database file of their own - the only way two
# WebUIs share one - shows only there.
from modules import shared                              # noqa: E402  (webui_stub's)
check('a note for a custom database is not shown without one', 'shared-only' in ids(rn.notes_for(db)), False)
shared.opts.model_manager_database_path = r'F:\elsewhere\models.db'
check('and is with one', ids(rn.notes_for(db, 'civitai_browser')), ['browser-only', 'shared-only'])
shared.opts.model_manager_database_path = ''

with db._cursor() as cursor:
    cursor.execute("DELETE FROM schema_info WHERE key = ?", (rn.CREATED_BY,))
check('a database from before notes were kept sees them all, newest first',
      ids(rn.notes_for(db, 'model_manager')), ['action-new', 'feature-old', 'action-old'])
db.set_info(rn.CREATED_BY, '0.35.0')
check('one made by an older version, the notes for updating newer than it',
      ids(rn.notes_for(db, 'model_manager')), ['action-new', 'feature-old'])

check('a note a later one replaces leaves the tabs - every tab it was in',
      [ids(rn.notes_for(db, 'generations')), 'rescan-first' in ids(rn.notes_for(db, 'civitai_browser'))],
      [['action-new', 'rescan-again'], False])
check('and "What\'s new" still lists it', 'rescan-first' in ids(rn.notes_for(db)), True)
rn.dismiss(db, 'rescan-again')
check('even once the one replacing it is dismissed', 'rescan-first' in ids(rn.notes_for(db, 'generations')), False)

rn.dismiss(db, 'action-new')
check('a dismissed note leaves every tab it was in',
      [ids(rn.notes_for(db, 'model_manager')), ids(rn.notes_for(db, 'generations'))], [['feature-old'], []])
check('and stays in "What\'s new", marked', {n['id']: n['dismissed'] for n in rn.notes_for(db)},
      {'action-new': True, 'feature-old': False, 'browser-only': False, 'rescan-again': True,
       'rescan-first': False})
again = dbmod.ModelsDatabase(extension_dir=ROOT, custom_db_path=facts['db_path'])
check('kept in the database: every browser, and another WebUI sharing it, sees it dismissed',
      ids(rn.notes_for(again, 'generations')), [])

# ---------------------------------------------------------------- the API
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))
body = client.get('/model-manager/notes', params={'tab': 'model_manager'}).json()
check('a tab asks for its notes', (body['success'], ids(body['notes'])), (True, ['feature-old']))
check('and dismisses one', client.post('/model-manager/notes/dismiss', data={'id': 'feature-old'}).json()['success'])
check('which then is not there', ids(client.get('/model-manager/notes', params={'tab': 'model_manager'}).json()['notes']),
      [])
check('while "What\'s new" still has it', 'feature-old' in ids(client.get('/model-manager/notes').json()['notes']))

rn.NOTES_FILE = real_file
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
