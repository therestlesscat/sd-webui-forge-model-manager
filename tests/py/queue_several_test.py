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
for a name it held. A refused press saves nothing, and says why.
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
send.family_pick = lambda db_, path: PICKS.get(path, ([], []))


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
check("every checkpoint's file is read before any row's usual settings are asked",
      [kind for kind, _ in order], ['read', 'read', 'read', 'usual', 'usual'])

# A file Forge lists that the library holds no row for - put in a folder since
# the last sync - is read as Send reads one, not refused.
FRESH = os.path.join(WORK, 'fresh.safetensors')
open(FRESH, 'wb').close()
FILES['fresh.safetensors'] = FRESH
import model_manager.file_identity as file_identity      # noqa: E402
real_identify = file_identity.identify
file_identity.identify = lambda path: types.SimpleNamespace(preset='xl' if path == FRESH else None)
try:
    rows = several.checkpoint_rows(db, ['fresh.safetensors'], None, SELECTED)
    fresh = (rows[0]['modules'], rows[0]['settings'])
except several.Refused as e:
    fresh = str(e)
check('a file with no library row is read, its family known: here the selected one\'s, the VAE on screen',
      fresh, (SELECTED['modules'], None))
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
capture.capture = real_capture

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
