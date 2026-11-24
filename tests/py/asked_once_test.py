"""
A press of Queue for N checkpoints, and Change's window's ask, find what the
image's files are once for the whole list (#433): several.AskedOnce keeps the
lookup by hash, which read every file row for every checkpoint, for one press
or one ask.

The real usual settings, pick kinds and lookups over a library of real rows:
how often the rows are read; every pick kind - own, same, file, version, model -
from five sources, the answers fixed; a lookup that fails asked again at the
next name; a row its reader changed handed as stored to the next; a library
changed between two asks seen by the second. Also what the route compares
families with, where it is told (#407).
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.tabs as tabs                        # noqa: E402
from model_manager import forge_host, resources, send, send_plan, usual_settings  # noqa: E402
from model_manager.db.models_ops import ModelsOps        # noqa: E402
from model_manager.install import INSTALL_KEY            # noqa: E402
from model_manager.model_dirs import file_modified       # noqa: E402
from model_manager.scheduler import several              # noqa: E402

WORK = os.path.join(TESTS, 'work', 'asked_once')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# Looked up, not imported: on the code before #433 its own checks fail, rather
# than the suite, and the guards run through the database itself.
AskedOnce = getattr(several, 'AskedOnce', lambda db_: db_)

db, _facts = fixtures.build(WORK)
dbmod._db_instance = db
raw = db._get_connection()

# ------------------------------------------------------------ the library
# The image's model 100: its version 1001, held as two files - the one whose hash
# the image names, and one with no hash of its own - and its version 1002. The
# same bytes under another model, 2001; and a checkpoint of a model of its own.
H = 'ABCDEF0123'
ROWS = {'own': (1001, 100, {'AutoV2': H}), 'fp16': (1001, 100, None), 'copy': (2001, 200, {'AutoV2': H}),
        'v2': (1002, 100, {'AutoV2': '1111111111'}), 'other': (3001, 300, {'AutoV2': '2222222222'}),
        'flux': (3002, 301, {'AutoV2': '3333333333'})}
CKPT = os.path.join(WORK, 'ckpt')
os.makedirs(CKPT, exist_ok=True)
FILES = {}
for stem, (version, model, hashes) in ROWS.items():
    path = os.path.join(CKPT, stem + '.safetensors')
    open(path, 'wb').write(b'\0' * 64)
    FILES[stem] = path
    db.upsert_version({'file_path': path, 'file_name': os.path.basename(path), 'file_size': 64, 'id': version,
                       'model_id': model, 'file_extension': '.safetensors', 'file_modified': '2026-01-01T00:00:00',
                       'has_civitai_data': True, 'nsfw_level': 1, 'file_hashes': hashes})
    db.set_architecture(path, 'flux' if stem == 'flux' else 'xl', None, False, False, file_modified(path),
                        file_type='Checkpoint')
check('set-up: the hash held by the two files alone, the image\'s own first',
      [r['file_path'] for r in db.versions_named_by([], [H])], [FILES['own'], FILES['copy']])
check('set-up: the other file of its version holding no hash',
      raw.execute('SELECT file_hashes FROM files WHERE file_path = ?', (FILES['fp16'],)).fetchone()[0], None)

NAMES = list(ROWS)
forge_host.checkpoint_listed = lambda name: name in FILES
forge_host.checkpoint_file = lambda name: FILES.get(name)
forge_host.installed_modules = lambda: {}
forge_host.script_checkpoint = lambda since, selection_too=False: None
send_plan.loads_here = lambda path: True
send.family_pick = lambda db_, path, found=None: ([], ['t5xxl'] if path == FILES['flux'] else [])
send.forge_lists = lambda: ([('Euler', ['euler']), ('Euler a', ['euler_ancestral'])], [('Karras', ['karras'])])
presets = types.ModuleType('modules_forge.presets')
presets.use_distill = lambda arch: False
presets.use_shift = lambda arch: False
sys.modules['modules_forge.presets'] = presets
real_on = tabs.on
tabs.on = lambda area: True if area == 'generations' else real_on(area)
SELECTED = {'checkpoint': 'other', 'modules': []}


def record(checkpoint, steps, uses=1, meta=None, **more):
    text = 'a prompt\nSteps: %d, Sampler: Euler, CFG scale: 5, Seed: 1, Size: 512x512' % steps
    made = []
    for n in range(uses):
        record.made += 1
        made.append(({'created_at': '2026-01-01T00:00:%02d' % (record.made % 60), 'mode': 'txt2img', 'image_count': 1,
                      'checkpoint_path': checkpoint, 'infotext': text, **more},
                     [{'position': 0, 'path': os.path.join(WORK, 'out', '%d.png' % record.made), 'meta': meta or {},
                       'prompt_nsfw_level': 1, 'infotext': text}], [[]]))
    return db.record_generations(made)


record.made = 0
# Six uses of each, its steps its own: what a pick runs with says which file was asked about.
STEPS = {'fp16': 21, 'copy': 22, 'v2': 23, 'other': 24, 'flux': 25}
for stem, steps in STEPS.items():
    record(FILES[stem], steps, uses=6)
# Every file of a version counts: its own file's uses are the other's too.
STEPS['own'] = STEPS['fp16']
[own_generation] = record(FILES['own'], 20, checkpoint_hash=H)
[workflow] = record(None, 20, meta={'Read from': 'workflow'})
raw.execute("INSERT INTO generation_resources (generation_id, image_id, position, role, name, file_path) "
            "SELECT generation_id, id, 0, 'checkpoint', 'other', NULL FROM generation_images WHERE generation_id = ?",
            (workflow,))
db.store_images(1001, page=1, images=[{
    'id': 7001, 'url': 'https://example.invalid/7001.jpeg', 'nsfwLevel': 1, 'modelVersionIds': [1001],
    'meta': {'prompt': 'the image', 'sampler': 'Euler a', 'steps': 28, 'cfgScale': 4.5}}])
raw.commit()
check('set-up: the workflow\'s generation names its checkpoint by name alone',
      send.workflow_checkpoint(db, db.get_generation(workflow)), 'other')
# Civitai's answers: the version's file's hash, as the open dialog's lookup keeps it (#304), and the hash's version (#233).
resources._MISSING_FILES[1001] = {'file_hash': H}
db.remember_hash(H, {'id': 1001, 'modelId': 100, 'name': 'v1', 'model': {'name': 'The model', 'type': 'Checkpoint'}})

CIVITAI = {'kind': 'civitai', 'image': 7001, 'image_model': 100}
SOURCES = {
    'by version and hash': {**CIVITAI, 'version_ids': '1001', 'hashes': H},
    'by version alone': {**CIVITAI, 'version_ids': '1001', 'hashes': ''},
    'by a hash alone': {**CIVITAI, 'version_ids': '', 'hashes': H, 'image_model': ''},
    'a generation': {'kind': 'generation', 'generation': own_generation, 'image_model': ''},
    'a workflow\'s generation': {'kind': 'generation', 'generation': workflow, 'image_model': 100},
}
# Each pick's kind, written from the code before #433: own, fp16, copy, v2, other, flux.
KINDS = {
    'by version and hash': ['own', 'file', 'same', 'version', 'model', 'model'],
    'by version alone': ['own', 'own', 'same', 'version', 'model', 'model'],
    'by a hash alone': ['own', 'file', 'same', 'version', 'model', 'model'],
    'a generation': ['own', 'file', 'same', 'version', 'model', 'model'],
    'a workflow\'s generation': ['version', 'version', 'model', 'version', 'own', 'model'],
}
MADE = ('own', 'same')


def runs_with(kind, name):
    """What a pick of a kind runs with: nothing of its own as made, else its version's most used."""
    return None if kind in MADE else {'sampler': 'Euler', 'steps': STEPS[name], 'cfg': 5}


# ------------------------------------------------ 1. every kind, from every source
for label, source in SOURCES.items():
    want = KINDS[label]
    for order, names in (('in order', NAMES), ('the other way round', NAMES[::-1])):
        asked = AskedOnce(db)
        got = {n: send._source_pick_kind(asked, {**source, 'use_checkpoint': n}) for n in names}
        check('%s, %s: each pick\'s kind, one lookup shared by all of them' % (label, order),
              [got[n] for n in NAMES], want)
    answer = several.runs_preview(db, NAMES, {'image': source}, SELECTED)
    check('%s: the window says what each runs with' % label,
          [(answer['runs'][n]['how'] in ('as_made',), answer['runs'][n]['usual']) for n in NAMES if n != 'flux'],
          [(k in MADE, runs_with(k, n)) for n, k in zip(NAMES, want) if n != 'flux'])
    rows = several.checkpoint_rows(db, NAMES[:-1], {'image': source}, SELECTED)
    check('%s: and the press queues the same' % label,
          [(r['checkpoint'], (r['settings'] or {}).get('usual')) for r in rows],
          [(n, runs_with(k, n)) for n, k in zip(NAMES, want) if n != 'flux'])

# ------------------------------------------------------- 2. how often the rows are read
scans = []
real_hashed = ModelsOps._hashed_files
ModelsOps._hashed_files = staticmethod(lambda cursor: scans.append(1) or real_hashed(cursor))
BY_HASH = {'image': SOURCES['by version and hash']}
# None of the five is the image's own by its path: each pick looks its hashes up.
FIVE = ['fp16', 'copy', 'v2', 'other', 'fp16 again']
FILES['fp16 again'] = FILES['fp16']


def scanned(what):
    scans.clear()
    what()
    return len(scans)


check('#433: a press of five checkpoints from an image naming a version and a hash reads the file rows\' hashes twice',
      scanned(lambda: several.checkpoint_rows(db, FIVE, BY_HASH, SELECTED)), 2)
check('#433: and so does Change\'s window\'s ask of the same list',
      scanned(lambda: several.runs_preview(db, FIVE, BY_HASH, SELECTED)), 2)
check('the press again reads them afresh: nothing is kept past it',
      scanned(lambda: several.checkpoint_rows(db, FIVE, BY_HASH, SELECTED)) > 0)
check('a list with no image behind it reads none', scanned(lambda: several.runs_preview(db, FIVE, None, SELECTED)), 0)
ModelsOps._hashed_files = staticmethod(real_hashed)

# ------------------------------------------------------- 3. what is not kept
real_named = db.versions_named_by
failing = [1]


def fails_first(version_ids, hashes):
    """The files holding the image's hashes, unread the first time: a kept failure would make `copy` another model's."""
    if failing and not version_ids:
        failing.pop()
        raise RuntimeError('the rows could not be read')
    return real_named(version_ids, hashes)


db.versions_named_by = fails_first
answer = several.runs_preview(db, ['v2', 'copy', 'fp16'], BY_HASH, SELECTED)
check('a lookup that fails at the first name is asked again at the second, and its answer is the one kept',
      [(answer['runs'][n]['how'], answer['runs'][n]['usual']) for n in ('v2', 'copy', 'fp16')],
      [('error', None), ('as_made', None), ('usual', runs_with('file', 'fp16'))])
failing.append(1)
rows = several.checkpoint_rows(db, ['v2', 'copy', 'fp16'], BY_HASH, SELECTED)
check('and in a press', [(r['settings'] or {}).get('usual') for r in rows], [None, None, runs_with('file', 'fp16')])
db.versions_named_by = real_named

asked = AskedOnce(db)
first = asked.versions_named_by([1001], [H])
first[0]['file_path'] = 'changed by its reader'
first.clear()
check('a row its reader changed, and a list it emptied, are as stored for the next',
      [r['file_path'] for r in asked.versions_named_by([1001], [H])], [FILES['own'], FILES['copy'], FILES['fp16']])
check('other arguments are another question', [r['file_path'] for r in asked.versions_named_by([], ['1111111111'])],
      [FILES['v2']])
check('every other call reaches the database', asked.get_version(FILES['v2'])['id'], 1002)

before = several.runs_preview(db, ['copy'], BY_HASH, SELECTED)['runs']['copy']['how']
db.store_file_hashes(FILES['copy'], {'AutoV2': '4444444444'}, None)
after = several.runs_preview(db, ['copy'], BY_HASH, SELECTED)['runs']['copy']['how']
check('a file\'s hashes changed between two asks: the second sees it', (before, after), ('as_made', 'usual'))
db.store_file_hashes(FILES['copy'], {'AutoV2': H}, None)

# ------------------------------------------------------- 4. compared with the checkpoint Send will load (#407)
def told(names, against, source=BY_HASH):
    """The ask told what to compare with; on the code before, which takes nothing more, the ask as it is."""
    try:
        return several.runs_preview(db, names, source, SELECTED, against)
    except TypeError:
        return several.runs_preview(db, names, source, SELECTED)


def marks(answer, names):
    return [answer['runs'][n].get('another_family') for n in names]


TWO = ['flux', 'v2']
answer = told(TWO, 'flux')
check('#407: told the first ticked, families are judged against it, and it is named',
      (marks(answer, TWO), answer['selected']), ([False, True], {'name': 'flux', 'state': 'read'}))
check('    and so is a missing text encoder: none is said for one of its own family',
      answer['runs']['flux'].get('problem'), None)
answer = told(TWO, 'v2')
check('    told the other: the first is of another family, and lacks one',
      (answer['runs']['flux'].get('problem'), marks(answer, ['v2'])),
      ('flux needs T5-XXL, which this WebUI does not have.', [False]))
# As the dialog asks it: the checkpoint Send will load is first of the list.
LISTED = ['gone'] + TWO
answer = told(LISTED, 'gone')
check('    one Forge no longer lists: no family judged, none refused for it, and it is named as not listed',
      (marks(answer, LISTED), [answer['runs'][n].get('problem') for n in LISTED], answer['selected']),
      ([None] * 3, ['Forge does not list the checkpoint gone: refresh its list, or pick another.', None, None],
       {'name': 'gone', 'state': 'not_listed'}))
raw.execute('UPDATE files SET architecture = NULL WHERE file_path = ?', (FILES['v2'],))
raw.commit()
answer = told(['v2', 'flux'], 'v2')
check('    one read and not recognised: no family judged, its state said',
      (marks(answer, ['v2', 'flux']), answer['selected']), ([None, None], {'name': 'v2', 'state': 'unrecognised'}))
raw.execute("UPDATE files SET architecture = 'xl' WHERE file_path = ?", (FILES['v2'],))
raw.execute('UPDATE files SET architecture_checked = NULL WHERE file_path = ?', (FILES['v2'],))
raw.commit()
answer = told(TWO, 'v2')
check('    one not read yet: no family judged, its state said',
      (marks(answer, TWO), answer['selected']), ([None, None], {'name': 'v2', 'state': 'not_read'}))
raw.execute('UPDATE files SET architecture_checked = ? WHERE file_path = ?', (file_modified(FILES['v2']), FILES['v2']))
raw.commit()
plain = several.runs_preview(db, TWO, BY_HASH, SELECTED)
check('    nothing told, or no text, or no name: as Forge has it selected',
      [told(TWO, a) == plain for a in (None, 7, ['flux'], '')], [True] * 4)
task = db.add_task({'install': INSTALL_KEY, 'mode': 'txt2img', 'inputs': {'fixed': {}},
                    'checkpoints': [{'checkpoint': 'v2', 'modules': [], 'settings': None}]})
for label, source in (('no image', None), ('a task', {'task': task}), ('a task and an image', {**BY_HASH, 'task': task})):
    check('    a list from %s: as Forge has it selected' % label,
          told(TWO, 'flux', source), several.runs_preview(db, TWO, source, SELECTED))

db.close()
if fails:
    print('\n'.join('FAIL ' + f for f in fails))
    print(f'{len(fails)} check(s) failed.')
    sys.exit(1)
print('All checks passed.')
