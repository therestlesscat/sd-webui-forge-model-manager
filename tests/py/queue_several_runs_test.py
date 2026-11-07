"""
What each checkpoint of several mode's list would run with, before it is
pressed (#406): the answer Change's window shows, from
scheduler/several.runs_preview and POST /model-manager/queue/several/runs.

Each name is decided as the press decides it - your settings for the one they
were set up for, the image's own as made, what a task held for a name it held
(by its file, where Forge renamed it since), else its usual settings, too few
uses or none - with its family read from the library's row alone: no
checkpoint of the list is read, nothing is stored. A name the press would
refuse says so, in the press's own words, and nothing is raised. "Another
family" is judged against Forge's selected checkpoint, and not told where the
row of either is not read at the file's modified time now.

The one rule: for lists the press accepts, the window's usual settings and
marks equal the press's rows, both reaching the same usual_settings.usual
through the real chosen() and applied(); send.family_pick and Forge's lists
are stood in for both alike.

The no-read proof covers runs_preview's own path: with family_pick and usual
stood in, the files an image's usual settings may read and store
(send_plan.local_checkpoint, as the Resources dialog's do) are not reached.
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

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

from modules import shared                               # noqa: E402  (webui_stub's)
import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.file_identity as file_identity      # noqa: E402
from model_manager import forge_host, send, send_plan, usual_settings  # noqa: E402
from model_manager.install import INSTALL_KEY            # noqa: E402
from model_manager.model_dirs import file_modified       # noqa: E402
from model_manager.scheduler import several              # noqa: E402

WORK = os.path.join(TESTS, 'work', 'queue_several_runs')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, _facts = fixtures.build(WORK)
dbmod._db_instance = db

# ------------------------------------------------------------ the library
# Real files and real rows: a family is read from a row only when the row was
# read at the file's modified time now.
CKPT = os.path.join(WORK, 'ckpt')
os.makedirs(CKPT, exist_ok=True)
FAMILY = {'anime': 'xl', 'photo': 'xl', 'thin': 'xl', 'lacking': 'xl', 'broken': 'xl', 'flux': 'flux', 'chroma': 'chroma',
          'unread': None, 'fresh': None, 'changed': 'flux'}
FILES = {}
for stem in FAMILY:
    path = os.path.join(CKPT, stem + '.safetensors')
    open(path, 'wb').write(b'\0' * 64)
    FILES[stem + '.safetensors'] = path
    if stem == 'fresh':
        continue                                        # no row: never synced
    db.upsert_version({'file_path': path, 'file_name': os.path.basename(path), 'file_size': 64,
                       'file_extension': '.safetensors', 'file_modified': '2026-01-01T00:00:00',
                       'has_civitai_data': False, 'nsfw_level': 1})
    checked = '2020-01-01T00:00:00' if stem == 'changed' else file_modified(path)
    db.set_architecture(path, FAMILY[stem], None, False, False, checked, file_type='Checkpoint')
# Forge renamed photo's file since a task named it: its old name maps to the same file.
FILES['photo_old.safetensors'] = FILES['photo.safetensors']
# Forge lists it, and gives no file for it: a task's row for it is found by its name alone.
LISTED = (set(FILES) - {'photo_old.safetensors'}) | {'ghost.safetensors'}
forge_host.checkpoint_listed = lambda name: name in LISTED
forge_host.checkpoint_file = lambda name: FILES.get(name)
INSTALLED = {'ae.safetensors': r'F:\models\VAE\ae.safetensors', 't5xxl.safetensors': r'F:\models\TE\t5xxl.safetensors'}
forge_host.installed_modules = lambda: dict(INSTALLED)
PICKS = {'flux': (['ae.safetensors', 't5xxl.safetensors'], []), 'chroma': (['ae.safetensors'], ['t5xxl'])}


def family_pick(db_, path, found=None):
    """Send's picks for the family it is handed, or reads from the row, as the real one."""
    preset = found.preset if found is not None else send_plan.row_model(db_, path)[0].preset
    return PICKS.get(preset, ([], []))


send.family_pick = family_pick
SELECTED = {'checkpoint': 'anime.safetensors', 'modules': [r'F:\models\VAE\sdxl_vae.safetensors']}


# ------------------------------------------------------- usual settings
def rows(values, thin=False, missing=False):
    return [{'key': k, 'value': v, 'count': 9, 'of': 9, 'thin': thin, 'missing': missing} for k, v in values.items()]


USUAL = {'photo.safetensors': {'steps': 30, 'cfg': 5}, 'anime.safetensors': {'steps': 28},
         'flux.safetensors': {'cfg': 1, 'distilled_cfg': 3.5}, 'chroma.safetensors': {'steps': 26},
         'thin.safetensors': {'steps': 40}, 'unread.safetensors': {'steps': 22}, 'fresh.safetensors': {'steps': 24},
         'changed.safetensors': {'steps': 18}, 'lacking.safetensors': {'sampler': 'Some Sampler'},
         'ghost.safetensors': {'steps': 16}}
usual_asked = []


def usual(db_, checkpoint, source):
    """usual_settings.usual's answer: as made for the image's own, none for a generation gone, else rows."""
    usual_asked.append(checkpoint)
    if checkpoint == 'broken.safetensors':
        raise RuntimeError('the settings rows could not be read')
    if source.get('gone'):
        return {'applies': False, 'kind': None}
    if source.get('image_model') == checkpoint:
        return {'applies': False, 'kind': 'own'}
    return {'applies': True, 'kind': 'model', 'settings': rows(USUAL[checkpoint], thin=checkpoint == 'thin.safetensors',
                                                               missing=checkpoint == 'lacking.safetensors')}


usual_settings.usual = usual
real_record, real_shapes = send_plan.record_architecture, send_plan.read_shapes
real_identify, real_classify = file_identity.identify, file_identity.classify_file


READS = []                                              # each read or store a run tried


def no_reading(on):
    """Every way a model file is read or stored, as bound where it is called: on, each is noted and fails the run."""
    def refuse(*args, **_k):
        READS.append(args[-1] if args else None)
        raise AssertionError('a model file was read')
    send_plan.record_architecture = refuse if on else real_record
    send_plan.read_shapes = refuse if on else real_shapes
    file_identity.identify = refuse if on else real_identify
    file_identity.classify_file = refuse if on else real_classify


def preview(names, source=None, selected=SELECTED):
    no_reading(True)
    try:
        return several.runs_preview(db, names, source, selected)
    except AssertionError:
        return {'runs': {}, 'selected': None, 'gone_task': None}
    finally:
        no_reading(False)


EMPTY = dict.fromkeys(('how', 'usual', 'family', 'family_state', 'another_family', 'problem'))


def run(answer, name):
    return answer['runs'].get(name) or EMPTY


def press(names, source=None, selected=SELECTED):
    try:
        return several.checkpoint_rows(db, names, source, selected)
    except several.Refused as e:
        return str(e)


# ------------------------------------------- 1. a list ticked in txt2img
answer = preview(['photo.safetensors', 'anime.safetensors', 'thin.safetensors', 'broken.safetensors'])
check('txt2img: Forge\'s selected checkpoint runs with your settings, nothing asked for it',
      (run(answer, 'anime.safetensors')['how'], run(answer, 'anime.safetensors')['usual'],
       'anime.safetensors' in usual_asked), ('yours', None, False))
check('txt2img: another with 5 or more uses takes its usual settings, by key',
      (run(answer, 'photo.safetensors')['how'], run(answer, 'photo.safetensors')['usual']),
      ('usual', {'steps': 30, 'cfg': 5}))
check('txt2img: one too few uses record runs with your settings: thin',
      (run(answer, 'thin.safetensors')['how'], run(answer, 'thin.safetensors')['usual']), ('thin', None))
answer = preview(['lacking.safetensors'])
check('txt2img: one whose usual sampler this WebUI lacks runs with your settings: thin',
      (run(answer, 'lacking.safetensors')['how'], run(answer, 'lacking.safetensors')['usual']), ('thin', None))
answer = preview(['photo.safetensors', 'anime.safetensors', 'thin.safetensors', 'broken.safetensors'])
check('txt2img: one whose usual settings could not be read says so, and runs with yours, as the press does',
      (run(answer, 'broken.safetensors')['how'], run(answer, 'broken.safetensors')['usual'],
       press(['broken.safetensors'])[0]['settings']), ('error', None, None))
check('in the order asked, one entry each', list(answer['runs']),
      ['photo.safetensors', 'anime.safetensors', 'thin.safetensors', 'broken.safetensors'])

# ------------------------------------------------- 2. a list from an image
IMAGE = {'kind': 'image', 'image_id': 7, 'image_model': 'photo.safetensors'}
answer = preview(['photo.safetensors', 'anime.safetensors'], {'image': IMAGE})
check("an image: its own checkpoint runs as made; Forge's selected one takes its usual settings",
      [(run(answer, n)['how'], run(answer, n)['usual']) for n in ('photo.safetensors', 'anime.safetensors')],
      [('as_made', None), ('usual', {'steps': 28})])
answer = preview(['photo.safetensors'], {'image': {'kind': 'generation', 'generation': 99, 'gone': True}})
check("an image whose generation is gone since: plain, your settings", run(answer, 'photo.safetensors')['how'],
      'plain')

# --------------------------------------------------- 3. a list from a task
task = db.add_task({'install': INSTALL_KEY, 'mode': 'txt2img', 'inputs': {'fixed': {}},
                    'checkpoints': [{'checkpoint': 'anime.safetensors', 'modules': [], 'settings': None},
                                    {'checkpoint': 'photo_old.safetensors', 'modules': [],
                                     'settings': {'usual': {'steps': 12}}},
                                    {'checkpoint': 'gone_now.safetensors', 'modules': [], 'settings': None},
                                    {'checkpoint': 'ghost.safetensors', 'modules': [],
                                     'settings': {'usual': {'steps': 9}}}]})
answer = preview(['anime.safetensors', 'photo.safetensors', 'flux.safetensors', 'gone_now.safetensors',
                  'ghost.safetensors'], {'task': task})
check('a task: a name it held, found by its name alone, runs as the task held it',
      (run(answer, 'ghost.safetensors')['how'], run(answer, 'ghost.safetensors')['usual']), ('held', {'steps': 9}))
check('a task: a name it held runs as it ran there - here with your settings',
      (run(answer, 'anime.safetensors')['how'], run(answer, 'anime.safetensors')['usual']), ('held', None))
check('a task: a name Forge renamed since is found by its file, and runs as the task held it',
      (run(answer, 'photo.safetensors')['how'], run(answer, 'photo.safetensors')['usual']), ('held', {'steps': 12}))
check('a task: a name added since takes its usual settings',
      (run(answer, 'flux.safetensors')['how'], run(answer, 'flux.safetensors')['usual']),
      ('usual', {'cfg': 1, 'distilled_cfg': 3.5}))
check('a task: a name it held that Forge no longer lists is the press\'s refusal',
      run(answer, 'gone_now.safetensors')['problem'],
      'Forge does not list the checkpoint gone_now.safetensors: refresh its list, or pick another.')
check('a task still held: no gone task', answer['gone_task'], None)
db.delete_task(task, with_data=False)
answer = preview(['anime.safetensors', 'photo.safetensors'], {'task': task})
check('a task deleted since: named, and each takes its usual settings',
      (answer['gone_task'], [run(answer, n)['how'] for n in ('anime.safetensors', 'photo.safetensors')]),
      (task, ['usual', 'usual']))

# ------------------------------------------------------ 4. families from rows
answer = preview(['photo.safetensors', 'flux.safetensors', 'fresh.safetensors', 'changed.safetensors',
                  'unread.safetensors'])
check('families from rows: read, not read yet, changed since, read and not recognised - no file read',
      [(run(answer, n)['family'], run(answer, n)['family_state'], run(answer, n)['another_family'])
       for n in ('photo.safetensors', 'flux.safetensors', 'fresh.safetensors', 'changed.safetensors')],
      [('xl', 'read', False), ('flux', 'read', True), (None, 'not_read', None), (None, 'not_read', None)])
check('a name not read yet still says what it runs with', run(answer, 'fresh.safetensors')['how'], 'usual')
check('read and not recognised: told as its state, not refused - the press reads the file again, and may find it',
      (run(answer, 'unread.safetensors')['family_state'], run(answer, 'unread.safetensors')['problem'],
       run(answer, 'unread.safetensors')['another_family'], run(answer, 'unread.safetensors')['how']),
      ('unrecognised', None, None, 'usual'))
check('Forge\'s selected checkpoint, read', answer['selected'], {'name': 'anime.safetensors', 'state': 'read'})
answer = preview(['photo.safetensors', 'flux.safetensors'], selected={'checkpoint': 'fresh.safetensors', 'modules': []})
check('Forge\'s selected checkpoint not read yet: no marks, and its state said',
      ([run(answer, n)['another_family'] for n in ('photo.safetensors', 'flux.safetensors')], answer['selected']),
      ([None, None], {'name': 'fresh.safetensors', 'state': 'not_read'}))
answer = preview(['photo.safetensors', 'flux.safetensors'], selected={'checkpoint': None, 'modules': []})
check('none selected: every name of another family, as the press marks them',
      ([run(answer, n)['another_family'] for n in ('photo.safetensors', 'flux.safetensors')], answer['selected'],
       [bool((r['settings'] or {}).get('another_family'))
        for r in press(['photo.safetensors', 'flux.safetensors'], selected={'checkpoint': None, 'modules': []})]),
      ([True, True], {'name': None, 'state': None}, [True, True]))
answer = preview(['fresh.safetensors'], selected={'checkpoint': None, 'modules': []})
check('none selected: a name not read yet is of another family too, as the press marks every row then',
      run(answer, 'fresh.safetensors')['another_family'], True)
answer = preview(['photo.safetensors', 'flux.safetensors'], selected={'checkpoint': 'nowhere.safetensors', 'modules': []})
check('a selected checkpoint Forge does not list: every name of another family, and none named',
      ([run(answer, n)['another_family'] for n in ('photo.safetensors', 'flux.safetensors')], answer['selected']),
      ([True, True], {'name': None, 'state': None}))
answer = preview(['photo.safetensors', 'flux.safetensors'], selected={'checkpoint': 'unread.safetensors', 'modules': []})
check('a selected checkpoint read and not recognised: no marks - the press reads it again - and its state said',
      ([run(answer, n)['another_family'] for n in ('photo.safetensors', 'flux.safetensors')], answer['selected']),
      ([None, None], {'name': 'unread.safetensors', 'state': 'unrecognised'}))

# --------------------------------------------------- 5. what the press refuses
answer = preview(['chroma.safetensors', 'nowhere.safetensors'])
check('a family lacking a kind: the press\'s refusal, word for word, nothing raised',
      (run(answer, 'chroma.safetensors')['problem'], press(['chroma.safetensors'])),
      ('chroma.safetensors needs T5-XXL, which this WebUI does not have.',) * 2)
check('a name Forge does not list: the press\'s refusal, word for word',
      (run(answer, 'nowhere.safetensors')['problem'], press(['nowhere.safetensors'])),
      ('Forge does not list the checkpoint nowhere.safetensors: refresh its list, or pick another.',) * 2)

check('no model file was read or stored by any of the window\'s answers', READS, [])

# ------------------------------------------------------------- 6. one rule
# Lists the press accepts, from each source: the window says what the press does.
task = db.add_task({'install': INSTALL_KEY, 'mode': 'txt2img', 'inputs': {'fixed': {}},
                    'checkpoints': [{'checkpoint': 'photo_old.safetensors', 'modules': [],
                                     'settings': {'usual': {'steps': 12}}}]})
for label, names, source, selected in (
        ('txt2img', ['anime.safetensors', 'photo.safetensors', 'flux.safetensors', 'thin.safetensors'], None, SELECTED),
        ('an image', ['photo.safetensors', 'anime.safetensors', 'flux.safetensors'], {'image': IMAGE}, SELECTED),
        ('a task', ['photo.safetensors', 'anime.safetensors', 'flux.safetensors'], {'task': task}, SELECTED),
        ('Flux selected', ['anime.safetensors', 'flux.safetensors'], None,
         {'checkpoint': 'flux.safetensors', 'modules': []})):
    window = preview(names, source, selected)
    rows_ = press(names, source, selected)
    check(f'one rule, {label}: each name\'s usual settings and mark as the press gives its row',
          [(run(window, n)['usual'], run(window, n)['another_family']) for n in names],
          [((r['settings'] or {}).get('usual'), bool((r['settings'] or {}).get('another_family'))) for r in rows_])

# ------------------------------------------------------------ 8. the route
from model_manager import api                             # noqa: E402
client = TestClient((lambda app: (api.setup_api(app), app)[1])(FastAPI()))
forge_host.selected_models = lambda: dict(SELECTED)
URL = '/model-manager/queue/several/runs'
setattr(shared.opts, 'model_manager_queue_enabled', False)
check('with the Queue off, the route refuses', client.post(URL, json={'names': ['photo.safetensors']}).status_code,
      403)
setattr(shared.opts, 'model_manager_queue_enabled', True)


def files_rows():
    with db._cursor() as cursor:
        return cursor.execute('SELECT file_path, architecture, architecture_checked FROM files ORDER BY file_path'
                              ).fetchall()


def data_version():
    """SQLite's count of commits other connections made: the route runs on a thread, with its own."""
    with db._cursor() as cursor:
        return cursor.execute('PRAGMA data_version').fetchone()[0]


# The real readers here, and a name whose row was read before its file changed:
# a build that read it would store what it found, a write the checks see.
before_rows, before_version = files_rows(), data_version()
got = client.post(URL, json={'names': ['photo.safetensors', 'changed.safetensors', 7, None], 'source': None})
body = got.json()
check('the route answers what runs_preview does, names that are not text taken as none, as the press takes them',
      (got.status_code, body.get('success'), list(body.get('runs', {})),
       body.get('runs', {}).get('photo.safetensors', {}).get('usual')),
      (200, True, ['photo.safetensors', 'changed.safetensors'], {'steps': 30, 'cfg': 5}))
check('the route writes nothing: no commit by another connection, every file row\'s family and read time as before',
      (data_version(), files_rows()), (before_version, before_rows))
check('a body that is not an object is taken as no names, as the press takes it',
      client.post(URL, json=['photo.safetensors']).json().get('runs'), {})

if fails:
    print('\n'.join('FAIL ' + f for f in fails))
    print(f'{len(fails)} check(s) failed.')
    sys.exit(1)
print('All checks passed.')
