"""
A press of Queue for N checkpoints (#400): the task's checkpoint rows, as
the server decides them (scheduler/several.py), and the button's handler.

Each name Forge must list, or the press is refused, naming it, and nothing
is saved; a file whose family cannot be read is refused too, and a family
this WebUI lacks a VAE or text encoder for. A checkpoint of the family of the
one selected in Forge gets the VAE / text encoders on screen; another family
what Send picks for it, as paths, and is marked so. Its usual settings are
asked as Send asks them, against the image Send was given - its own
checkpoint takes none - or, for a list Load to UI loaded, kept from the task
for a name it held - and, from a task deleted since, asked afresh, which
the press says. A refused press saves nothing, and says why.
"""
import json
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
from model_manager import forge_host, send, send_plan, usual_settings  # noqa: E402
from model_manager.architecture import Architecture      # noqa: E402
from model_manager.install import INSTALL_KEY            # noqa: E402
from model_manager.scheduler import capture, several  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'queue_several')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, _facts = fixtures.build(WORK)
dbmod._db_instance = db

# Forge, stood in: its checkpoints by name, each file's family, what Send
# picks for a family, and the VAE / text encoders it offers.
FILES = {'anime.safetensors': r'F:\models\anime.safetensors', 'photo.safetensors': r'F:\models\photo.safetensors',
         'flux.safetensors': r'F:\models\flux.safetensors', 'unread.safetensors': r'F:\models\unread.safetensors',
         'chroma.safetensors': r'F:\models\chroma.safetensors', 'bare.safetensors': r'F:\models\bare.safetensors'}
FAMILY = {r'F:\models\anime.safetensors': 'xl', r'F:\models\photo.safetensors': 'xl',
          r'F:\models\flux.safetensors': 'flux', r'F:\models\unread.safetensors': None,
          r'F:\models\chroma.safetensors': 'chroma', r'F:\models\bare.safetensors': 'flux'}
PICKS = {r'F:\models\flux.safetensors': (['ae.safetensors', 't5xxl.safetensors'], []),
         r'F:\models\chroma.safetensors': (['ae.safetensors'], ['t5xxl']),
         r'F:\models\bare.safetensors': ([], ['clip_l', 't5xxl', 'vae_ae'])}
INSTALLED = {'ae.safetensors': r'F:\models\VAE\ae.safetensors', 't5xxl.safetensors': r'F:\models\TE\t5xxl.safetensors',
             'sdxl_vae.safetensors': r'F:\models\VAE\sdxl_vae.safetensors'}
SELECTED = {'checkpoint': 'anime.safetensors', 'modules': [r'F:\models\VAE\sdxl_vae.safetensors']}
USUAL = {'photo.safetensors': {'steps': 30, 'cfg': 5}, 'flux.safetensors': {'cfg': 1, 'distilled_cfg': 3.5},
         'anime.safetensors': {'steps': 28}}
asked = []

forge_host.checkpoint_listed = lambda name: name in FILES
forge_host.checkpoint_file = lambda name: FILES.get(name)
forge_host.installed_modules = lambda: dict(INSTALLED)
order = []


def picked_model(db_, path):
    order.append(('read', path))
    return send_plan.SendModel(preset=FAMILY.get(path), source='picked')


send_plan.picked_model = picked_model
# Files the library holds no row for. Handed nothing, the real family_pick reads
# a file's family from its row alone, so for one of these it finds none.
NO_ROW = set()
FRESH_PRESETS = {}


# What each pick was handed, by path, as the real one picks only for the family
# it is told: handed what another file is, it picks for that one.
handed = {}


def family_pick(db_, path, found=None):
    handed[path] = found
    if found is None:
        family = None if path in NO_ROW else FAMILY.get(path)
    else:
        family = found.preset
    if family != FAMILY.get(path, FRESH_PRESETS.get(path)):
        return [], []
    return PICKS.get(path, ([], []))


send.family_pick = family_pick


def chosen(db_, source):
    """Send's answer: none for the image's own checkpoint, its usual settings for any other."""
    asked.append(dict(source))
    order.append(('usual', source.get('use_checkpoint')))
    if source.get('image_model') == source.get('use_checkpoint'):
        return None
    return USUAL.get(source['use_checkpoint'])


usual_settings.chosen = chosen


def refused(names, source=None, selected=SELECTED):
    try:
        several.checkpoint_rows(db, names, source, selected)
        return None
    except several.Refused as e:
        return str(e)


# ----------------------------------------------------- the rows, from an image
IMAGE = {'kind': 'image', 'image_id': 7, 'image_model': 'anime.safetensors'}
rows = several.checkpoint_rows(db, ['anime.safetensors', 'photo.safetensors', 'flux.safetensors'],
                               {'image': IMAGE}, SELECTED)
check('a checkpoint of the selected one\'s family gets the VAE / text encoders on screen',
      [r['modules'] for r in rows[:2]], [SELECTED['modules']] * 2)
check('another family gets what Send picks for it, as paths, and is marked so',
      (rows[2]['modules'], rows[2]['settings'].get('another_family')),
      ([r'F:\models\VAE\ae.safetensors', r'F:\models\TE\t5xxl.safetensors'], True))
check("the image's own checkpoint takes no usual settings: it runs as made", rows[0]['settings'], None)
check('every other takes its usual settings, as Send works them out',
      [r['settings'].get('usual') for r in rows[1:]], [USUAL['photo.safetensors'], USUAL['flux.safetensors']])
check('asked against the image Send was given, for each name',
      [(a.get('image_id'), a.get('usual'), a.get('use_checkpoint')) for a in asked],
      [(7, True, 'anime.safetensors'), (7, True, 'photo.safetensors'), (7, True, 'flux.safetensors')])
check('in the order picked, one row each', [r['checkpoint'] for r in rows],
      ['anime.safetensors', 'photo.safetensors', 'flux.safetensors'])
check('a name picked twice is one row',
      [r['checkpoint'] for r in several.checkpoint_rows(db, ['photo.safetensors', 'photo.safetensors'], None, SELECTED)],
      ['photo.safetensors'])

# ------------------------------- a list ticked in txt2img: no image, no task
# Several checkpoints…: the checkpoint Forge has selected is the one your
# settings were set up for, and keeps them; each other takes its usual settings.
for source in (None, {}):
    asked.clear()
    rows = several.checkpoint_rows(db, ['photo.safetensors', 'anime.safetensors', 'flux.safetensors'], source, SELECTED)
    check(f'source {source!r}: the checkpoint Forge has selected keeps your settings, wherever it is in the list',
          rows[1]['settings'], None)
    check(f'source {source!r}: each other takes its usual settings, asked with no image',
          ([r['settings'].get('usual') for r in (rows[0], rows[2])],
           [(a.get('image_id'), a.get('use_checkpoint')) for a in asked]),
          ([USUAL['photo.safetensors'], USUAL['flux.safetensors']],
           [(None, 'photo.safetensors'), (None, 'flux.safetensors')]))
# From an image, the selected one is like any other: only the image's own runs as made.
OTHER_IMAGE = {'kind': 'image', 'image_id': 8, 'image_model': 'photo.safetensors'}
rows = several.checkpoint_rows(db, ['anime.safetensors', 'photo.safetensors'], {'image': OTHER_IMAGE}, SELECTED)
check('from an image, the checkpoint Forge has selected takes its usual settings; the image\'s own runs as made',
      [rows[0]['settings'], rows[1]['settings']], [{'usual': USUAL['anime.safetensors']}, None])

# ------------------------------------------------------------ refusals
check('no name is refused', refused([]), 'No checkpoint to queue for.')
check('a name Forge does not list is refused, naming it', refused(['photo.safetensors', 'gone.safetensors']),
      'Forge does not list the checkpoint gone.safetensors: refresh its list, or pick another.')
check('a file whose family cannot be read is refused, naming it', refused(['unread.safetensors']),
      'Could not read unread.safetensors, so its family is not known.')
check('a family this WebUI lacks a kind for is refused, naming it as the page does', refused(['chroma.safetensors']),
      'chroma.safetensors needs T5-XXL, which this WebUI does not have.')
check('several kinds, in a sentence', refused(['bare.safetensors']),
      'bare.safetensors needs CLIP-L, T5-XXL and Flux VAE (ae), which this WebUI does not have.')
check('a source or names that are not what the page sends are taken as none',
      ([r['checkpoint'] for r in several.checkpoint_rows(db, ['photo.safetensors', 7, None], ['not', 'a', 'dict'],
                                                         SELECTED)]), ['photo.safetensors'])

# ------------------------------------------- read before anything is decided
order.clear()
several.checkpoint_rows(db, ['photo.safetensors', 'flux.safetensors'], {'image': IMAGE}, SELECTED)
check("every checkpoint's file is read before any row's usual settings are asked: the names', in order, "
      "then the selected one's",
      order, [('read', FILES['photo.safetensors']), ('read', FILES['flux.safetensors']),
              ('read', FILES['anime.safetensors']), ('usual', 'photo.safetensors'), ('usual', 'flux.safetensors')])
# A refused press reads nothing past its refusal.
order.clear()
refused(['photo.safetensors', 'gone.safetensors'])
check('a name Forge does not list is refused before any file is read', order, [])
order.clear()
refused(['photo.safetensors', 'unread.safetensors', 'flux.safetensors'])
check("a file whose family cannot be read is refused before the next name's file or the selected one's is read",
      order, [('read', FILES['photo.safetensors']), ('read', FILES['unread.safetensors'])])
order.clear()
refused(['photo.safetensors', 'chroma.safetensors', 'flux.safetensors'])
check("a family lacking a kind is refused before its own usual settings, or the next name's, are asked",
      order, [('read', FILES['photo.safetensors']), ('read', FILES['chroma.safetensors']),
              ('read', FILES['flux.safetensors']), ('read', FILES['anime.safetensors']),
              ('usual', 'photo.safetensors')])

# A file Forge lists that the library holds no row for - put in a folder since
# the last sync - is read as Send reads one, not refused.
FRESH = os.path.join(WORK, 'fresh.safetensors')
open(FRESH, 'wb').close()
FILES['fresh.safetensors'] = FRESH
import model_manager.file_identity as file_identity      # noqa: E402
real_identify = file_identity.identify
FRESH_FLUX = os.path.join(WORK, 'fresh_flux.safetensors')
FRESH_CHROMA = os.path.join(WORK, 'fresh_chroma.safetensors')
for _path in (FRESH_FLUX, FRESH_CHROMA):
    open(_path, 'wb').close()
FILES.update({'fresh_flux.safetensors': FRESH_FLUX, 'fresh_chroma.safetensors': FRESH_CHROMA})
NO_ROW.update({FRESH, FRESH_FLUX, FRESH_CHROMA})
PICKS.update({FRESH_FLUX: (['ae.safetensors', 't5xxl.safetensors'], []), FRESH_CHROMA: (['ae.safetensors'], ['t5xxl'])})
FRESH_PRESETS.update({FRESH: 'xl', FRESH_FLUX: 'flux', FRESH_CHROMA: 'chroma'})
file_identity.identify = lambda path: Architecture(FRESH_PRESETS.get(path), None, False, False)
try:
    rows = several.checkpoint_rows(db, ['fresh.safetensors'], None, SELECTED)
    fresh = (rows[0]['modules'], rows[0]['settings'])
except several.Refused as e:
    fresh = str(e)
check('a file with no library row is read, its family known: here the selected one\'s, the VAE on screen',
      fresh, (SELECTED['modules'], None))
# Of another family, it gets what Send picks for the family it was read as:
# picked again from the library's row alone, it got none, and was not refused.
try:
    rows = several.checkpoint_rows(db, ['fresh_flux.safetensors'], None, SELECTED)
    fresh = (rows[0]['modules'], rows[0]['settings'])
except several.Refused as e:
    fresh = str(e)
check('a file with no library row, of another family, gets what Send picks for the family it was read as',
      fresh, ([r'F:\models\VAE\ae.safetensors', r'F:\models\TE\t5xxl.safetensors'], {'another_family': True}))
check('the no-row file\'s pick is handed what it was read as, not another file\'s',
      handed.get(FRESH_FLUX), send_plan.SendModel(preset='flux', source='picked'))
handed.clear()
several.checkpoint_rows(db, ['flux.safetensors'], None, SELECTED)
check('a file with a library row is handed exactly what picked_model read of it, as its pick read for itself before',
      handed, {FILES['flux.safetensors']: send_plan.SendModel(preset='flux', source='picked')})
check('a file with no library row, of a family this WebUI lacks a kind for, is refused, naming it',
      refused(['fresh_chroma.safetensors']), 'fresh_chroma.safetensors needs T5-XXL, which this WebUI does not have.')
file_identity.identify = real_identify

# The family is judged against the checkpoint Forge has selected, not the
# image's own nor the list's first.
rows = several.checkpoint_rows(db, ['anime.safetensors', 'photo.safetensors', 'flux.safetensors'], {'image': IMAGE},
                               {'checkpoint': 'flux.safetensors', 'modules': ['on-screen-ae.safetensors']})
check("with Flux selected in Forge, the SDXL rows are another family, the Flux row takes the VAE on screen",
      [(r['modules'], bool((r['settings'] or {}).get('another_family'))) for r in rows],
      [([], True), ([], True), (['on-screen-ae.safetensors'], False)])

# ------------------------------------------------- a list Load to UI loaded
task = db.add_task({'install': INSTALL_KEY, 'mode': 'txt2img', 'inputs': {'fixed': {}},
                    'checkpoints': [{'checkpoint': 'anime.safetensors', 'modules': [], 'settings': None},
                                    {'checkpoint': 'photo.safetensors', 'modules': [],
                                     'settings': {'usual': {'steps': 12}}}]})
asked.clear()
rows = several.checkpoint_rows(db, ['anime.safetensors', 'photo.safetensors', 'flux.safetensors'],
                               {'task': task}, SELECTED)
check("against a task, each name it held runs as it ran there",
      [r['settings'] for r in rows[:2]], [None, {'usual': {'steps': 12}}])
check('and a name added since takes its usual settings, asked with no image',
      ([a['use_checkpoint'] for a in asked], rows[2]['settings']['usual']),
      (['flux.safetensors'], USUAL['flux.safetensors']))
# Forge adds a file's hash to its name the first time it loads it, and Load
# to UI hands the name Forge lists the file under now: the task's row is
# found by its file, and runs as it ran there - not as one added since.
FILES['anime.safetensors [abcd1234]'] = FILES['anime.safetensors']
asked.clear()
rows = several.checkpoint_rows(db, ['anime.safetensors [abcd1234]', 'photo.safetensors'], {'task': task}, SELECTED)
check("a name Forge has renamed since: its task's row found by its file, run as it ran there, nothing asked",
      ([r['settings'] for r in rows], [a['use_checkpoint'] for a in asked]), ([None, {'usual': {'steps': 12}}], []))
del FILES['anime.safetensors [abcd1234]']
theirs = db.add_task({'install': 'another-install', 'mode': 'txt2img', 'inputs': {'fixed': {}},
                      'checkpoints': [{'checkpoint': 'photo.safetensors', 'settings': {'usual': {'steps': 99}}}]})
check("another install's task is not read",
      several.checkpoint_rows(db, ['photo.safetensors'], {'task': theirs}, SELECTED)[0]['settings'],
      {'usual': USUAL['photo.safetensors']})

# --------------------------------------------------------- the button's press
import gradio as gr                                      # noqa: E402

said = []
gr.Warning = lambda text: said.append(('warning', text))
gr.Info = lambda text: said.append(('info', text))
saved = []
real_capture = capture.capture
capture.capture = lambda tab, own, others, inputs, values, username, checkpoints=None: (
    saved.append((tab, list(values), username, checkpoints)), (41, 'a red apple'))[1]
forge_host.selected_models = lambda: dict(SELECTED)
capture.selected_models = forge_host.selected_models
press = capture._several_handler('txt2img', None, [], ['prompt', 'steps'])
request = types.SimpleNamespace(username='someone')
press(request, 'a red apple', 20,
      json.dumps({'names': ['photo.safetensors', 'flux.safetensors'], 'source': {'image': IMAGE}}))
check("the press saves one task with the list's rows, Generate's inputs without the list",
      [(t, v, u, [r['checkpoint'] for r in c]) for t, v, u, c in saved],
      [('txt2img', ['a red apple', 20], 'someone', ['photo.safetensors', 'flux.safetensors'])])
check('and says so', said, [('info', 'Queued for 2 checkpoints: a red apple')])
said.clear()
saved.clear()
press(request, 'a red apple', 20, json.dumps({'names': ['gone.safetensors']}))
press(request, 'a red apple', 20, '')
press(request, 'a red apple', 20, '[1, 2]')
press(request, 'a red apple', 20, json.dumps({'names': 'photo.safetensors'}))
check('a refused press saves nothing and says why; no list, or one not as the page sends it, says there is none',
      (saved, said),
      ([], [('warning', 'Forge does not list the checkpoint gone.safetensors: refresh its list, or pick another.')]
       + [('warning', 'No checkpoint to queue for.')] * 3))
said.clear()
press(request, 'a red apple', 20, json.dumps({'names': ['photo.safetensors']}))
check('one checkpoint is said as one', said, [('info', 'Queued for 1 checkpoint: a red apple')])
# A list Load to UI loaded from a task deleted since: what each name ran
# with there went with it, so each takes its usual settings, and the press
# says so. A task still there says nothing more.
said.clear()
saved.clear()
press(request, 'a red apple', 20, json.dumps({'names': ['anime.safetensors', 'photo.safetensors'],
                                              'source': {'task': 999999}}))
check('from a task deleted since: queued, each with its usual settings, and said',
      ([r['settings'] for r in saved[0][3]] if saved else None, said),
      ([{'usual': USUAL['anime.safetensors']}, {'usual': USUAL['photo.safetensors']}],
       [('info', 'Queued for 2 checkpoints: a red apple'),
        ('info', 'Task #999999 is deleted, so each checkpoint runs with its usual settings where it has them.')]))
said.clear()
press(request, 'a red apple', 20, json.dumps({'names': ['anime.safetensors', 'photo.safetensors'],
                                              'source': {'task': task}}))
check('from a task still there, nothing more is said', said, [('info', 'Queued for 2 checkpoints: a red apple')])

# Generate for N checkpoints: the same task, then the runner's Run next for it
# alone - after the running task, or now - and said; left queued where Run
# next does not put it first, saying why and where to start it.
answers = []
asked_next = []
def run_next(ids, alone=False):
    asked_next.append((ids, alone))
    answer = answers.pop(0)
    if isinstance(answer, Exception):
        raise answer
    return answer
go = capture._several_handler('txt2img', None, [], ['prompt', 'steps'], run_next=run_next)
LIST = json.dumps({'names': ['photo.safetensors', 'flux.safetensors'], 'source': {'image': IMAGE}})
said.clear()
saved.clear()
answers[:] = [{'first': [41], 'after': None, 'skipped': [], 'missing': []}]
go(request, 'a red apple', 20, LIST)
check('Generate for N checkpoints saves the task as Queue for N does, then asks Run next for it alone',
      ([(t, v, [r['checkpoint'] for r in c]) for t, v, _u, c in saved], asked_next),
      ([('txt2img', ['a red apple', 20], ['photo.safetensors', 'flux.safetensors'])], [([41], True)]))
check('started now: said so', said, [('info', 'Generating for 2 checkpoints: a red apple')])
cases = [
    ({'first': [41], 'after': 7, 'skipped': [], 'missing': []},
     ('info', 'Queued for 2 checkpoints, to run once task #7 ends: a red apple')),
    ({'first': [], 'after': None, 'skipped': [],
      'missing': [{'task': 41, 'prompt': 'a red apple', 'missing': ['Gone Script', 'Another']}]},
     ('warning', 'Queued for 2 checkpoints, not started: it uses Another, Gone Script, which this WebUI no longer '
                 'has. Start it from the Queue tab.')),
    ({'first': [], 'after': None, 'skipped': [], 'missing': [], 'stopping': True},
     ('warning', 'Queued for 2 checkpoints, not started: the queue is stopping. Start it from the Queue tab.')),
    ({'first': [], 'after': None, 'skipped': [], 'missing': [], 'off': True},
     ('warning', 'Queued for 2 checkpoints, not started: the Queue is off. Start it from the Queue tab.')),
    (RuntimeError('the database is busy'),
     ('warning', 'Queued for 2 checkpoints, but it could not start: the database is busy. Start it from the Queue tab.')),
]
for answer, want in cases:
    said.clear()
    answers[:] = [answer]
    go(request, 'a red apple', 20, LIST)
    check(f'Run next answering {answer!r}: said as it is', said, [want])
said.clear()
asked_next.clear()
go(request, 'a red apple', 20, json.dumps({'names': ['gone.safetensors']}))
check('a refused press saves nothing and starts nothing', (asked_next, said),
      ([], [('warning', 'Forge does not list the checkpoint gone.safetensors: refresh its list, or pick another.')]))
capture.capture = real_capture

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
