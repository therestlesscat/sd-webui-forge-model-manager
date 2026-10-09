"""
A generation set back as it was made (#7): scheduler/capture.py, load.py,
generations.py and migration v36, with Forge and Gradio stood in, into the
fixture library.

Each press of Generate is named at the click, as Queue names a task, and
kept under Forge's id for the run until the recorder writes it with the
generation - or, for a run of the queue, the task's inputs are. Send on one
image sets every control back from that record, with the image's own seed
and prompts and a batch of one. An infotext - a Civitai image's, or a
generation recorded before - goes through Forge's own paste, run by the
hidden button, and what Neo's paste gets wrong is corrected: the hires
checkpoint, which it reads as `name [hash]` where the control lists paths;
the hires VAE / text encoders, whose keys it drops; the refiner's checkpoint;
and, from a record, the refiner's CFG scale, which no infotext carries.

Each check runs on its own: on code without these, it fails by name.
"""
import copy
import json
import os
import sqlite3
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'generation_replay')
opts = webui_stub.install(model_manager_queue_inputs_dir=os.path.join(WORK, 'queue-inputs'),
                          model_manager_record_generations=True, model_manager_queue_enabled=False)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402

fails = []


def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def attempt(fn):
    """What fn gives, or the error it raised - so a check fails, not the suite."""
    try:
        return fn()
    except Exception as e:                               # noqa: BLE001
        return 'raised %s: %s' % (type(e).__name__, e)


db, facts = fixtures.build(WORK)
dbmod._db_instance = db


# ------------------------------------------------------ Gradio, stood in
class Component(object):
    _next = 1

    def __init__(self, label=None, elem_id=None, value=None, **attrs):
        self.label, self.elem_id, self.value = label, elem_id, value
        self._id = Component._next
        Component._next += 1
        self.__dict__.update(attrs)

    def preprocess(self, value):
        return value

    def postprocess(self, value):
        return value


class Textbox(Component): pass
class Slider(Component): pass
class Dropdown(Component): pass
class State(Component): pass


class Button(Component):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.wired = []

    def click(self, **wiring):
        self.wired.append(wiring)


def script(title, start, end):
    return types.SimpleNamespace(title=lambda: title, args_from=start, args_to=end)


SCRIPT_LIST = Dropdown('Script', 'script_list', value='None', type='index',
                       choices=[('None', 'None'), ('X/Y/Z plot', 'X/Y/Z plot')])
SEED = Slider('Seed', 'txt2img_seed', value=-1)
SUBSEED = Slider('Variation seed', 'txt2img_subseed', value=-1)
REFINER_ON = Slider('Refiner', 'txt2img_enable', value=False)
REFINER = Dropdown('Checkpoint', 'txt2img_checkpoint', value='', choices=[])
REFINER_SWITCH = Slider('Switch at', 'txt2img_switch_at', value=0.875)
REFINER_CFG = Slider('Refiner CFG Scale', 'txt2img_cfg', value=1.0)
RUNNER = types.SimpleNamespace(
    inputs=[SCRIPT_LIST, SEED, SUBSEED, REFINER_ON, REFINER, REFINER_SWITCH, REFINER_CFG],
    scripts=[script('Seed', 1, 3), script('Refiner', 3, 7)])

PATHS = {'chill': r'F:\webui\models\Stable-diffusion\_SD_1_5\chilloutmix.safetensors',
         'rv': r'F:\webui\models\Stable-diffusion\_Hyper\realisticVision.safetensors'}
NEO_CHOICES = ['Use same checkpoint', r'_SD_1_5\chilloutmix.safetensors', r'_Hyper\realisticVision.safetensors']
HR_CHECKPOINT = Dropdown('Hires Checkpoint', 'hr_checkpoint', value='Use same checkpoint',
                         choices=[(c, c) for c in NEO_CHOICES])
HR_MODULES = Dropdown('Hires VAE / Text Encoder', 'hr_vae_te', value=['Use same choices'], multiselect=True)
REFINER.choices = [(c, c) for c in ['None'] + NEO_CHOICES[1:]]

FIXED = [Textbox(None, None, value=''), Textbox('Prompt', 'txt2img_prompt', value=''),
         Textbox('Negative prompt', 'txt2img_neg_prompt', value=''),
         Dropdown('Styles', 'txt2img_styles', value=[], multiselect=True),
         Slider('Batch count', 'txt2img_batch_count', value=1), Slider('Batch size', 'txt2img_batch_size', value=1),
         HR_CHECKPOINT, HR_MODULES, Textbox('Hires prompt', 'txt2img_hr_prompt', value='')]


def txt2img_create_processing(id_task, request, prompt, negative_prompt, prompt_styles, n_iter, batch_size,
                              hr_checkpoint_name, hr_additional_modules, hr_prompt, *args):
    pass


# ------------------------------------------------------- Forge, stood in
class Info(object):
    def __init__(self, key, short_hash):
        self.filename = PATHS[key]
        self.name = os.path.relpath(PATHS[key], r'F:\webui\models\Stable-diffusion')
        self.name_for_extra = os.path.splitext(os.path.basename(PATHS[key]))[0]
        self.short_title = f'{self.name_for_extra} [{short_hash}]'
        self.title = f'{self.name} [{short_hash}]'


INFOS = {'chill': Info('chill', 'fc2511737a'), 'rv': Info('rv', 'f47e942ad4')}
sd_models = types.ModuleType('modules.sd_models')
sd_models.checkpoints_list = {i.title: i for i in INFOS.values()}
sd_models.checkpoint_aliases = {}


def get_closet_checkpoint_match(name):
    for info in INFOS.values():
        if name in (info.title, info.short_title, info.name, info.name_for_extra) or name in info.title:
            return info
    return None


sd_models.get_closet_checkpoint_match = get_closet_checkpoint_match


def parse_generation_parameters(text):
    """Enough of Forge's parser: the prompt, then the settings line's keys."""
    lines = text.strip().split('\n')
    params = {'Prompt': lines[0]}
    for part in lines[-1].split(', ') if len(lines) > 1 else []:
        key, _, value = part.partition(': ')
        params[key] = value
    # Neo's own quirk: every Hires Module key read is dropped.
    for key in [k for k in params if k.startswith('Hires Module ')]:
        params.pop(key)
    params.setdefault('Hires checkpoint', 'Use same checkpoint')
    return params


infotext_utils = types.ModuleType('modules.infotext_utils')
infotext_utils.parse_generation_parameters = parse_generation_parameters
OVERRIDE = Dropdown('Override settings', 'txt2img_override_settings', value=[])
infotext_utils.paste_fields = {'txt2img': {
    'fields': [(FIXED[1], 'Prompt'), (HR_CHECKPOINT, 'Hires checkpoint'), (HR_MODULES, 'Hires VAE/TE'),
               (REFINER, 'Refiner'), (SEED, 'Seed'), (REFINER_CFG, 'Refiner CFG scale')],
    'override_settings_component': OVERRIDE}}

main_entry = types.ModuleType('modules_forge.main_entry')
main_entry.module_list = {'clearvaeSD15_v23.safetensors': r'F:\vae\clearvaeSD15_v23.safetensors',
                          'ae.safetensors': r'F:\vae\ae.safetensors'}
modules_forge = types.ModuleType('modules_forge')
modules_forge.main_entry = main_entry

scripts_module = types.ModuleType('modules.scripts')
scripts_module.scripts_txt2img = RUNNER
txt2img_module = types.ModuleType('modules.txt2img')
txt2img_module.txt2img_create_processing = txt2img_create_processing
progress = types.ModuleType('modules.progress')
progress.current_task = None

modules = sys.modules['modules']
for name, module in (('scripts', scripts_module), ('txt2img', txt2img_module), ('sd_models', sd_models),
                     ('infotext_utils', infotext_utils), ('progress', progress)):
    setattr(modules, name, module)
    sys.modules['modules.' + name] = module
sys.modules.update({'modules_forge': modules_forge, 'modules_forge.main_entry': main_entry})

from model_manager.scheduler import capture, load, replay   # noqa: E402
from model_manager import generations                     # noqa: E402
from model_manager.db import migrations                   # noqa: E402


# ------------------------------------------ Generate, its paste, stood in
def txt2img(*args):
    pass


def paste_func(text):
    """Neo's paste, as it answers: a value per field, the two checkpoints
    blank - `name [hash]` is not among their choices - and the hires
    modules "Use same choices", whatever the text said."""
    params = parse_generation_parameters(text)
    return [{'__type__': 'update', 'value': params['Prompt']}, {'__type__': 'update', 'value': ''},
            {'__type__': 'update', 'value': ['Use same choices']}, {'__type__': 'update', 'value': ''},
            {'__type__': 'update', 'value': params.get('Seed')}, {'__type__': 'update'},
            {'__type__': 'update', 'value': []}]


GENERATE = Button('Generate', 'txt2img_generate')
PASTE_BUTTON = Button('\u2199', 'paste')
OWN = types.SimpleNamespace(fn=txt2img, inputs=FIXED + RUNNER.inputs, outputs=[],
                            targets=[(GENERATE._id, 'click')], js='submit')
PASTE_OUTPUTS = [f[0] for f in infotext_utils.paste_fields['txt2img']['fields']] + [OVERRIDE]
PASTE = types.SimpleNamespace(fn=paste_func, inputs=[FIXED[1]], outputs=PASTE_OUTPUTS,
                              targets=[(PASTE_BUTTON._id, 'click')])
ROOT_BLOCK = types.SimpleNamespace(fns={0: OWN})


def found(queue=None):
    capture._found.clear()
    capture._found['txt2img'] = {'root': ROOT_BLOCK, 'generate': GENERATE, 'queue': queue}


# =============================================================== a press
# Neo hides every Queue button with the queue off; Generate's place is
# kept all the same, for recording and Send.
capture._found.clear()
attempt(lambda: capture.on_component(GENERATE, elem_id='txt2img_generate'))
check('with the queue off, Generate\'s place is kept, with no Queue button',
      attempt(lambda: (list(capture._found), capture._found['txt2img']['queue'])), (['txt2img'], None))

found()
GENERATE.wired.clear()
attempt(lambda: capture.wire_generate_record())
wiring = GENERATE.wired[0] if GENERATE.wired else {}
check('recording wires a listener of ours on Generate\'s click, with Generate\'s inputs, outside the queue',
      (len(GENERATE.wired), wiring.get('inputs') == OWN.inputs, wiring.get('outputs'), wiring.get('queue')),
      (1, True, [], False))
check('its page code waits for the run id Forge stores for the tab, and sends it',
      all(part in (wiring.get('js') or '') for part in ("'txt2img_task_id'", 'args[0] =', 'before')), True)
check("and Generate's own listener is still told apart from it",
      attempt(lambda: capture.generate_click('txt2img') is OWN), True)

# The listener's server side: the press named, as Queue names a task, and
# kept under the run's id, without its files.
record = wiring.get('fn') or (lambda *a: None)
press = ['task(abc)', 'a red apple', 'blurry', ['Style one'], 2, 3, r'_Hyper\realisticVision.safetensors',
         ['clearvaeSD15_v23.safetensors'], '', 0, -1, -1, True, r'_Hyper\realisticVision.safetensors', 0.6, 3.0]
attempt(lambda: record(*press))
kept = attempt(lambda: capture.pressed_inputs('task(abc)'))
check('a press is kept under its run\'s id, named as a task is',
      attempt(lambda: (kept['fixed']['prompt'], kept['fixed']['hr_checkpoint_name'], kept['scripts']['Refiner'][3]['value'])),
      ('a red apple', r'_Hyper\realisticVision.safetensors', 3.0))
check('and taken once: asked again, nothing', attempt(lambda: capture.pressed_inputs('task(abc)')), None)
attempt(lambda: record('', 'no id'))
check('a press whose id never came keeps nothing', attempt(lambda: len(capture._pressed)), 0)

from PIL import Image                                    # noqa: E402
image_press = list(press)
image_press[0] = 'task(img)'
image_press[8] = Image.new('RGB', (4, 4))
attempt(lambda: record(*image_press))
check('an image it was sent is not written to disk: kept as what it was',
      attempt(lambda: capture.pressed_inputs('task(img)')['fixed']['hr_prompt']), {'__missing__': 'Image'})
check('and no folder is made for it', os.path.isdir(os.path.join(WORK, 'queue-inputs')), False)
for n in range(40):
    attempt(lambda n=n: record(*(['task(%d)' % n] + press[1:])))
check('presses whose runs saved nothing are dropped, the oldest first: at most 32 kept',
      attempt(lambda: (len(capture._pressed), capture.pressed_inputs('task(0)'), bool(capture.pressed_inputs('task(39)')))),
      (32, None, True))

# The recorder writes the press its run came from: the listener's, or a
# queued task's own inputs.
attempt(lambda: record(*(['task(mine)'] + press[1:])))
task_id = db.add_task({'install': 'x', 'mode': 'txt2img', 'inputs': {'fixed': {'prompt': 'queued'}}})
check('a run of the queue is recorded with its task\'s inputs',
      attempt(lambda: generations._named_inputs(db, 'task(mmq-%d-1)' % task_id)), {'fixed': {'prompt': 'queued'}})
check('a press of Generate with what our listener kept',
      attempt(lambda: generations._named_inputs(db, 'task(mine)')['fixed']['prompt']), 'a red apple')
check('a run from elsewhere, Forge\'s API say, with none', attempt(lambda: generations._named_inputs(db, None)), None)

# ======================================================== the record
# A record's inputs, named as the listener names them: Queue's own naming.
from model_manager.scheduler.values import Keeper   # noqa: E402
generation_inputs = capture.name_inputs('txt2img', OWN.inputs, ['task(rec)'] + press[1:],
                                        Keeper(os.path.join(WORK, 'unused')))
generation_id = db.record_generation(
    {'created_at': '2026-10-09T12:00:00', 'mode': 'txt2img', 'prompt': 'a red apple', 'n_iter': 2,
     'batch_size': 3, 'image_count': 2, 'inputs': generation_inputs, 'refiner_path': PATHS['rv'],
     'params': {'refiner_cfg': 3.0}},
    [{'position': 0, 'iteration': 0, 'path': 'a.png', 'prompt': 'a red apple, style one', 'seed': 101,
      'subseed': 7, 'negative_prompt': 'blurry, bad', 'infotext': 'a red apple\nSteps: 20'},
     {'position': 1, 'iteration': 0, 'path': 'b.png', 'prompt': 'a green apple, style one', 'seed': 102,
      'subseed': 8, 'negative_prompt': 'blurry, bad', 'infotext': 'a green apple\nSteps: 20'}],
    [[], []])
stored = db.get_generation(generation_id)
check('a generation keeps the named inputs of its press', attempt(lambda: stored['inputs'] == generation_inputs), True)
second = stored['images'][1]

# ===================================================== Send, for one image
one = attempt(lambda: load.for_image('txt2img', generation_inputs, second))
check('one image is set back as it was made: its prompts, styles cleared, a batch of one',
      attempt(lambda: (one['fixed']['prompt'], one['fixed']['negative_prompt'], one['fixed']['prompt_styles'],
                       one['fixed']['n_iter'], one['fixed']['batch_size'])),
      ('a green apple, style one', 'blurry, bad', [], 1, 1))
check('with its own seed and subseed',
      attempt(lambda: [c['value'] for c in one['scripts']['Seed']]), [102, 8])
check('and the record itself is not changed', generation_inputs['fixed']['n_iter'], 2)

SKIP = object()
values = attempt(lambda: load.generation_values('txt2img', generation_id, second['id'], skip=SKIP))
check('the hidden button hands each of Generate\'s inputs its value: the hires checkpoint and VAE, the refiner',
      attempt(lambda: (values[0][5], values[0][6], values[0][12], values[0][13], values[0][14])),
      (r'_Hyper\realisticVision.safetensors', ['clearvaeSD15_v23.safetensors'], r'_Hyper\realisticVision.safetensors',
       0.6, 3.0))
other = db.record_generation({'created_at': '2026-10-09T12:00:01', 'mode': 'img2img', 'image_count': 1,
                              'inputs': generation_inputs}, [{'position': 0, 'path': 'c.png'}], [[]])
bare = db.record_generation({'created_at': '2026-10-09T12:00:02', 'mode': 'txt2img', 'image_count': 1},
                            [{'position': 0, 'path': 'd.png'}], [[]])
check('a generation of the other tab is not loaded here',
      attempt(lambda: load.generation_values('txt2img', other, None)), 'raised TaskError: Generation #%d is an img2img generation' % other)
check('nor one recorded without its press', attempt(lambda: load.generation_values('txt2img', bare, None)),
      'raised TaskError: Generation #%d kept no inputs' % bare)

# A generation the other WebUI made, through a shared database: its
# checkpoints spelt by its own folders. The original Forge lists them by
# `name [hash]`; both find a file by its name alone, an alias.
for info in INFOS.values():
    sd_models.checkpoint_aliases[info.name_for_extra] = info
SHORT_CHOICES = [('Use same checkpoint', 'Use same checkpoint'),
                 ('chilloutmix [fc2511737a]', 'chilloutmix [fc2511737a]'),
                 ('realisticVision [f47e942ad4]', 'realisticVision [f47e942ad4]')]
neo_choices, refiner_choices = HR_CHECKPOINT.choices, REFINER.choices
HR_CHECKPOINT.choices, REFINER.choices = SHORT_CHOICES, [('', '')] + SHORT_CHOICES[1:]
theirs = list(press)
theirs[0] = 'task(theirs)'
theirs[6] = r'_Their_Folder\realisticVision.safetensors'
theirs[13] = r'_Their_Folder\chilloutmix.safetensors'
their_id = db.record_generation({'created_at': '2026-10-09T12:00:03', 'mode': 'txt2img', 'image_count': 1,
                                 'inputs': capture.name_inputs('txt2img', OWN.inputs, theirs,
                                                               Keeper(os.path.join(WORK, 'unused')))},
                                [{'position': 0, 'path': 'e.png', 'seed': 9}], [[]])
values = attempt(lambda: load.generation_values('txt2img', their_id, None, skip=SKIP))
check("the other WebUI's generation: its hires and refiner checkpoints as this WebUI lists them",
      attempt(lambda: (values[0][5], values[0][12])), ('realisticVision [f47e942ad4]', 'chilloutmix [fc2511737a]'))
gone = list(theirs)
gone[0], gone[6] = 'task(gone)', r'_Their_Folder\notHere.safetensors'
gone_id = db.record_generation({'created_at': '2026-10-09T12:00:04', 'mode': 'txt2img', 'image_count': 1,
                                'inputs': capture.name_inputs('txt2img', OWN.inputs, gone,
                                                              Keeper(os.path.join(WORK, 'unused')))},
                               [{'position': 0, 'path': 'f.png', 'seed': 9}], [[]])
values = attempt(lambda: load.generation_values('txt2img', gone_id, None, skip=SKIP))
check('one this WebUI lacks keeps what is on screen, and is named',
      attempt(lambda: (values[0][5] is SKIP, values[1])),
      (True, [r'Hires Checkpoint: _Their_Folder\notHere.safetensors is not in this WebUI']))
HR_CHECKPOINT.choices, REFINER.choices = neo_choices, refiner_choices

# ================================================ an infotext, corrected
CIVITAI = ('a lighthouse\nSteps: 20, Seed: 5, Hires checkpoint: realisticVision [f47e942ad4], '
           'Hires Module 1: clearvaeSD15_v23, Refiner: chilloutmix [fc2511737a], Refiner switch at: 0.6')
controls = {'hr_checkpoint': HR_CHECKPOINT, 'hr_vae_te': HR_MODULES, 'txt2img_checkpoint': REFINER,
            'txt2img_cfg': REFINER_CFG}
check('Neo\'s paste is corrected: each name to the path its control lists, the hires modules read',
      attempt(lambda: load.corrections('txt2img', CIVITAI, None, controls)),
      ({'hr_checkpoint': r'_Hyper\realisticVision.safetensors', 'txt2img_checkpoint': r'_SD_1_5\chilloutmix.safetensors',
        'hr_vae_te': ['clearvaeSD15_v23.safetensors']}, []))
SHORT = ['Use same checkpoint', 'chilloutmix [fc2511737a]', 'realisticVision [f47e942ad4]']
short_hr = Dropdown('Hires Checkpoint', 'hr_checkpoint', choices=[(c, c) for c in SHORT])
check('the original Forge lists `name [hash]`: what its paste set is right, and stays',
      attempt(lambda: load.corrections('txt2img', CIVITAI, None, {'hr_checkpoint': short_hr})[0]),
      {'hr_checkpoint': 'realisticVision [f47e942ad4]'})
check('a hires module "Use same choices", or "Built-in", is said as Forge means it',
      attempt(lambda: (load.corrections('txt2img', 'x\nSteps: 1, Hires Module 1: Use same choices', None, controls)[0],
                       load.corrections('txt2img', 'x\nSteps: 1, Hires Module 1: Built-in', None, controls)[0])),
      ({'hr_vae_te': ['Use same choices']}, {'hr_vae_te': []}))
check('a file this WebUI lacks keeps what is on screen, and is named',
      attempt(lambda: load.corrections('txt2img', 'x\nSteps: 1, Hires checkpoint: gone [123], Hires Module 1: nope',
                                       None, controls)),
      ({'hr_checkpoint': None, 'hr_vae_te': []}, ['gone [123]', 'nope']))
check('an infotext with none of them corrects nothing',
      attempt(lambda: load.corrections('txt2img', 'x\nSteps: 1, Seed: 2', None, controls)), ({}, []))
OLD = {'hr_checkpoint_path': PATHS['chill'], 'hr_modules': [r'F:\vae\ae.safetensors'], 'refiner_path': PATHS['rv'],
       'params': {'refiner_cfg': 3.0}}
check('a record\'s own paths win, and its refiner CFG comes back, which no infotext carries',
      attempt(lambda: load.corrections('txt2img', CIVITAI, OLD, controls)),
      ({'hr_checkpoint': r'_SD_1_5\chilloutmix.safetensors', 'txt2img_checkpoint': r'_Hyper\realisticVision.safetensors',
        'hr_vae_te': ['ae.safetensors'], 'txt2img_cfg': 3.0}, []))

# Forge's own paste, run by the hidden button: found when asked, its answer
# corrected in the same event.
OUTPUTS = FIXED[1:] + RUNNER.inputs + [OVERRIDE]
found()
check('without Forge\'s paste the button says so, for the page to paste itself',
      attempt(lambda: load.paste_values('txt2img', CIVITAI, None, OUTPUTS, skip=SKIP)),
      "raised NoPaste: Forge's paste for txt2img was not found")
# Forge wires its paste once the tabs are built, in the page's whole Blocks
# (shared.demo), not the tab's: found there.
PAGE = types.SimpleNamespace(fns={0: OWN, 1: PASTE})
sys.modules['modules.shared'].demo = PAGE
check("Forge's paste is found in the page's whole Blocks, where Forge wires it",
      attempt(lambda: capture.paste_click('txt2img') is PASTE), True)
pasted = attempt(lambda: load.paste_values('txt2img', CIVITAI, None, OUTPUTS, skip=SKIP))
at = {id(c): n for n, c in enumerate(OUTPUTS)}
check("Forge's paste is run, and what it gets wrong set right",
      attempt(lambda: (pasted[0][at[id(FIXED[1])]]['value'], pasted[0][at[id(HR_CHECKPOINT)]],
                       pasted[0][at[id(HR_MODULES)]], pasted[0][at[id(REFINER)]], pasted[1])),
      ('a lighthouse', r'_Hyper\realisticVision.safetensors', ['clearvaeSD15_v23.safetensors'],
       r'_SD_1_5\chilloutmix.safetensors', []))
check('a control the paste does not set keeps what is on screen',
      attempt(lambda: pasted[0][at[id(SUBSEED)]] is SKIP), True)
def short_answer(text):
    return [{'__type__': 'update'}]


short_answer.__name__ = 'paste_func'
PASTE.fn = short_answer
check('a paste that answers otherwise than a value per control is not trusted',
      attempt(lambda: load.paste_values('txt2img', CIVITAI, None, OUTPUTS, skip=SKIP)),
      "raised NoPaste: Forge's paste for txt2img answered list, not a value for each of its 7 controls")
PASTE.fn = paste_func
check("with a generation named, its record corrects the paste: its refiner's CFG too",
      attempt(lambda: load.paste_values('txt2img', 'a\nSteps: 1', generation_id, OUTPUTS, skip=SKIP)[0][at[id(REFINER_CFG)]]),
      3.0)

# =============================================================== the button
import gradio as gr                                      # noqa: E402
generate_count = len(OWN.inputs) - 1
extras = [OVERRIDE]
answer = attempt(lambda: load._loader('txt2img', generate_count, extras)(
    json.dumps({'paste': 'x\nSteps: 1, Hires checkpoint: gone [1]', 'nonce': 'p1'})))
check('an infotext is answered for every output, and the files missing named',
      attempt(lambda: (len(answer), json.loads(answer[-1]))),
      (generate_count + len(extras) + 1, {'nonce': 'p1', 'pasted': True, 'missing': ['gone [1]']}))
answer = attempt(lambda: load._loader('txt2img', generate_count, extras)(
    json.dumps({'generation': generation_id, 'image': second['id'], 'nonce': 'g1'})))
check('a generation\'s image is answered as a task is',
      attempt(lambda: json.loads(answer[-1])),
      {'nonce': 'g1', 'generation': generation_id, 'skipped': [], 'notes': []})
del PAGE.fns[1]
answer = attempt(lambda: load._loader('txt2img', generate_count, extras)(json.dumps({'paste': 'x', 'nonce': 'p2'})))
check('with Forge\'s paste not found, nothing is set and the page is told to paste itself',
      attempt(lambda: (answer[:-1] == [gr.update()] * (generate_count + 1), json.loads(answer[-1]).get('no_paste'))),
      (True, True))

# Built once per build of the UI, with the first of our tabs: the queue off
# needs them too.
built = []
real_textbox, real_button = gr.Textbox, gr.Button
gr.Textbox = lambda **k: Textbox(None, k.get('elem_id'))


def a_button(**k):
    button = Button(None, k.get('elem_id'))
    built.append(button)
    return button


gr.Button = a_button
GENERATE.wired.clear()
attempt(lambda: load.new_build())
attempt(lambda: load.wire_send_buttons())
attempt(lambda: load.wire_send_buttons())
gr.Textbox, gr.Button = real_textbox, real_button
check('the hidden buttons are built once per build, named for Send', [b.elem_id for b in built], ['mm_load_txt2img'])
wired = built[0].wired[0] if built and built[0].wired else {}
check("their outputs: Generate's inputs, then the paste's other controls, then the answer",
      attempt(lambda: (wired['outputs'][:-1] == OWN.inputs[1:] + [OVERRIDE], wired['outputs'][-1].elem_id)),
      (True, 'mm_load_txt2img_answer'))
check('and, generations being recorded, our listener on Generate', len(GENERATE.wired), 1)

# ============================================================ migration v36
memory = sqlite3.connect(':memory:')
cursor = memory.cursor()
cursor.execute('CREATE TABLE generations (id INTEGER PRIMARY KEY, prompt TEXT)')
cursor.execute("INSERT INTO generations (prompt) VALUES ('kept')")
attempt(lambda: migrations._migrate_to_v36(cursor))
attempt(lambda: migrations._migrate_to_v36(cursor))
cursor.execute('PRAGMA table_info(generations)')
check('v36 adds the inputs column, once, and touches no row',
      ([r[1] for r in cursor.fetchall()], attempt(lambda: cursor.execute('SELECT prompt, inputs FROM generations').fetchall())),
      (['id', 'prompt', 'inputs'], [('kept', None)]))
memory.close()

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
