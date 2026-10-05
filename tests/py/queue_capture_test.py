"""
The Queue button: model_manager/scheduler/capture.py (#148, #149, #165), with
stand-ins for Forge's script runner and signatures and for Gradio's blocks,
into the fixture library.

Queue is given the inputs of Generate's own click - found by its function's
name among the click's listeners - and of the others, whose states it
refreshes as Generate's click would. What it keeps is named: the fixed
inputs by Forge's signature, the scripts' by title and control, an index
by its label. A task is written for this install, with the checkpoint and
modules Forge has selected. Nothing is written when the inputs cannot be
named.
"""
import dataclasses
import os
import shutil
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'queue_capture')
INPUTS = os.path.join(WORK, 'queue-inputs')
opts = webui_stub.install(model_manager_queue_inputs_dir=INPUTS,
                          sd_model_checkpoint='model.safetensors [abc123]',
                          forge_additional_modules=[r'F:\models\VAE\vae.safetensors'])

import numpy                                             # noqa: E402
from PIL import Image                                    # noqa: E402

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.install import INSTALL_KEY            # noqa: E402
from model_manager.scheduler import capture              # noqa: E402
from model_manager.scheduler.values import restore       # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db


# ------------------------------------------------------ Gradio, stood in
class Component(object):
    _next = 1

    def __init__(self, label=None, elem_id=None, **attrs):
        self.label, self.elem_id = label, elem_id
        self._id = Component._next
        Component._next += 1
        self.__dict__.update(attrs)


class Textbox(Component): pass
class Slider(Component): pass
class Checkbox(Component): pass
class Dropdown(Component): pass
class State(Component): pass
class Files(Component): pass
class LogicalImage(Component): pass
class Button(Component):
    def click(self, **wiring):
        self.wired = wiring


@dataclasses.dataclass
class Unit:
    enabled: bool = False
    weight: float = 1.0
    image: object = None


# -------------------------------------------- Forge's scripts, stood in
def script(title, start, end):
    return types.SimpleNamespace(title=lambda: title, args_from=start, args_to=end)


def runner_for(tab):
    script_list = Dropdown('Script', 'script_list', type='index',
                           choices=[('None', 'None'), ('X/Y/Z plot', 'X/Y/Z plot')])
    seed = Slider('Seed', f'{tab}_seed')
    subseed = Slider('Variation seed', None)
    unit = State(None, None)
    unit.value = Unit()
    xyz_type = Dropdown('X type', 'script_xyz_x_type', type='index',
                        choices=[('Nothing', 'Nothing'), ('Seed', 'Seed'), ('Steps', 'Steps')])
    xyz_values = Textbox('X values', 'script_xyz_x_values')
    loose = Checkbox('Unclaimed', None)
    inputs = [script_list, seed, subseed, unit, xyz_type, xyz_values, loose]
    return types.SimpleNamespace(
        inputs=inputs,
        scripts=[script('Seed', 1, 3), script('ControlNet', 3, 4), script('X/Y/Z plot', 4, 6)],
        selectable_scripts=[script('X/Y/Z plot', 4, 6)])


RUNNERS = {tab: runner_for(tab) for tab in ('txt2img', 'img2img')}
scripts_module = types.ModuleType('modules.scripts')
scripts_module.scripts_txt2img = RUNNERS['txt2img']
scripts_module.scripts_img2img = RUNNERS['img2img']


def txt2img_create_processing(id_task, request, prompt, negative_prompt, prompt_styles, n_iter,
                              override_settings_texts, *args, force_enable_hr=False):
    pass


def img2img_function(id_task, request, mode, prompt, init_img, img2img_batch_upload, *args):
    pass


txt2img_module = types.ModuleType('modules.txt2img')
txt2img_module.txt2img_create_processing = txt2img_create_processing
img2img_module = types.ModuleType('modules.img2img')
img2img_module.img2img_function = img2img_function
modules = sys.modules['modules']
modules.scripts, modules.txt2img, modules.img2img = scripts_module, txt2img_module, img2img_module
sys.modules.update({'modules.scripts': scripts_module, 'modules.txt2img': txt2img_module,
                    'modules.img2img': img2img_module})


# ------------------------------------------------- Generate's click, stood in
def txt2img(*args):
    pass


def img2img(*args):
    pass


def UiControlNetUnit(enabled, weight, image):
    return Unit(enabled=enabled, weight=weight, image=image)


def listener(fn, inputs, outputs, target, js=None):
    return types.SimpleNamespace(fn=fn, inputs=inputs, outputs=outputs, targets=[(target._id, 'click')], js=js)


def tab_blocks(tab, fixed):
    runner = RUNNERS[tab]
    generate, other = Button('Generate', f'{tab}_generate'), Button('Other', None)
    unit_state = runner.inputs[3]
    cn_enabled, cn_weight, cn_image = Checkbox('Enable'), Slider('Control Weight'), LogicalImage('Image')
    own = listener(txt2img if tab == 'txt2img' else img2img, fixed + runner.inputs, [Component()] * 5,
                   generate, js='submit')
    controlnet = listener(UiControlNetUnit, [cn_enabled, cn_weight, cn_image], [unit_state], generate)
    with_js = listener(lambda *a: Unit(enabled=True), [cn_enabled], [unit_state], generate, js='update()')
    elsewhere = listener(lambda *a: None, [cn_enabled], [], other)
    root = types.SimpleNamespace(fns={0: controlnet, 1: own, 2: with_js, 3: elsewhere})
    return root, generate, own, (controlnet, with_js, elsewhere), (cn_enabled, cn_weight, cn_image)


T_FIXED = [Textbox(None, None), Textbox('Prompt', 'txt2img_prompt'), Textbox('Negative prompt', 'txt2img_neg_prompt'),
           Dropdown('Styles', 'txt2img_styles', multiselect=True), Slider('Batch count', 'txt2img_batch_count'),
           Dropdown('Override settings', 'txt2img_override_settings', multiselect=True)]
root, generate, own, (cn_dep, js_dep, other_dep), (cn_enabled, cn_weight, cn_image) = tab_blocks('txt2img', T_FIXED)

# ----------------------------------------------------- finding Generate
found_own, others = capture.generate_listeners(root, generate)
check("Generate's own listener is found by its function's name", found_own is own, True)
check('the other listeners on its click are kept apart', others, [cn_dep, js_dep])
inputs = capture.queue_inputs(own, others)
check("Queue is given Generate's inputs first, in their order", inputs[:len(own.inputs)], own.inputs)
check("then what the other listeners read, once each", inputs[len(own.inputs):], [cn_enabled, cn_weight, cn_image])

# --------------------------------------------------------------- a capture
runner = RUNNERS['txt2img']
picture = numpy.zeros((4, 4, 3), dtype=numpy.uint8)
by_component = {
    T_FIXED[0]: '', T_FIXED[1]: 'a red apple', T_FIXED[2]: 'blurry', T_FIXED[3]: ['Style one'],
    T_FIXED[4]: 2, T_FIXED[5]: [],
    runner.inputs[0]: 1, runner.inputs[1]: 1234, runner.inputs[2]: -1,
    runner.inputs[3]: Unit(enabled=False), runner.inputs[4]: 1, runner.inputs[5]: '1,2', runner.inputs[6]: True,
    cn_enabled: True, cn_weight: 0.5, cn_image: picture,
}
values = [by_component[c] for c in inputs]
task_id, prompt = capture.capture('txt2img', own, others, inputs, values, 'sachi')
check('a capture returns its task and prompt', (isinstance(task_id, int), prompt), (True, 'a red apple'))
task = db.get_task(task_id)
check('the task is pending, for this install', (task['status'], task['install'], task['mode']),
      ('pending', INSTALL_KEY, 'txt2img'))
check('with the checkpoint and modules Forge has selected', (task['checkpoint'], task['modules']),
      ('model.safetensors [abc123]', [r'F:\models\VAE\vae.safetensors']))
check('and who queued it', task['username'], 'sachi')
named = task['inputs']
check('fixed inputs are named by Forge\'s signature, but the task id', named['fixed'],
      {'prompt': 'a red apple', 'negative_prompt': 'blurry', 'prompt_styles': ['Style one'], 'n_iter': 2,
       'override_settings_texts': []})
check('the selected script is kept by its title', named['script'], 'X/Y/Z plot')
check("a script's controls are kept by id, label and value", named['scripts']['Seed'],
      [{'id': 'txt2img_seed', 'label': 'Seed', 'value': 1234},
       {'id': None, 'label': 'Variation seed', 'value': -1}])
check('an index control is kept as its label', named['scripts']['X/Y/Z plot'][0]['value'], {'__label__': 'Seed'})
check('an input no script claims is kept by its place', named['loose'], [{'at': 6, 'value': True}])
unit = restore(named['scripts']['ControlNet'][0]['value'])
check("ControlNet's unit was refreshed, as Generate's click would", (unit.enabled, unit.weight), (True, 0.5))
check('its image kept with it', numpy.array_equal(unit.image, picture), True)
check('a listener with code of its own in the page is not run for it', unit.enabled, True)
check("the stale state the click carried is not what is kept", unit != Unit(enabled=False), True)

# ---------------------------------------------- a failing listener
cn_dep.fn = lambda *a: (_ for _ in ()).throw(RuntimeError('broken'))
task_id, _ = capture.capture('txt2img', own, others, inputs, values, None)
unit = restore(db.get_task(task_id)['inputs']['scripts']['ControlNet'][0]['value'])
check('a listener that fails leaves the state as the click carried it', unit.enabled, False)
check('a capture with no files makes no folder: only the first, with its image, has one',
      len(os.listdir(INPUTS)) if os.path.isdir(INPUTS) else 0, 1)
cn_dep.fn = UiControlNetUnit

# ------------------------------------------------------------- img2img
I_FIXED = [Textbox(None, None), Dropdown('Mode', None), Textbox('Prompt', 'img2img_prompt'),
           LogicalImage('background', 'uuid_0f3c'), Files('Files', 'img2img_batch_upload')]
i_root, i_generate, i_own, i_others, _ = tab_blocks('img2img', I_FIXED)
i_runner = RUNNERS['img2img']
source = Image.new('RGBA', (6, 6), (10, 200, 10, 255))
upload = os.path.join(WORK, 'batch-one.png')
source.save(upload)
i_inputs = capture.queue_inputs(i_own, i_others)
i_values = {I_FIXED[0]: '', I_FIXED[1]: 0, I_FIXED[2]: 'an apple', I_FIXED[3]: source, I_FIXED[4]: [upload],
            i_runner.inputs[0]: 0, i_runner.inputs[1]: -1, i_runner.inputs[2]: -1,
            i_runner.inputs[3]: Unit(), i_runner.inputs[4]: 0, i_runner.inputs[5]: '', i_runner.inputs[6]: False}
i_values = [i_values.get(c, None) for c in i_inputs]
task_id, _ = capture.capture('img2img', i_own, i_others, i_inputs, i_values, None)
fixed = db.get_task(task_id)['inputs']['fixed']
image_path = fixed['init_img']['__image__']
check('a source image is kept as a file in its task folder', (os.path.isfile(image_path),
                                                              os.path.dirname(os.path.dirname(image_path))),
      (True, INPUTS))
check('and comes back as it was', restore(fixed['init_img']).tobytes(), source.tobytes())
copy = fixed['img2img_batch_upload'][0]['__file__']
check('an upload is copied beside it', (os.path.isfile(copy), os.path.dirname(copy)),
      (True, os.path.dirname(image_path)))
check('no script selected is None', db.get_task(task_id)['inputs']['script'], None)

# ------------------------------------------------- what cannot be named
before = db.count_tasks(INSTALL_KEY)['pending']
short = capture.queue_inputs(own, others)[1:]
try:
    capture.capture('txt2img', types.SimpleNamespace(inputs=own.inputs[1:]), others, short,
                    [by_component[c] for c in short], None)
    raised = None
except RuntimeError as e:
    raised = str(e)
check('inputs Forge\'s signature does not name are refused, saying so',
      raised, "txt2img's Generate sends 5 inputs before the scripts', and Forge's signature names 6")
check('and no task is written', db.count_tasks(INSTALL_KEY)['pending'], before)

shuffled = types.SimpleNamespace(inputs=T_FIXED + [runner.inputs[1], runner.inputs[0]] + runner.inputs[2:])
try:
    capture.capture('txt2img', shuffled, [], shuffled.inputs, [by_component[c] for c in shuffled.inputs], None)
    raised = False
except RuntimeError:
    raised = True
check("script inputs out of the runner's order are refused", raised, True)

check('an index out of range keeps the index', capture._label([('a', 'a')], 7), {'__label__': None, 'index': 7})
check('a list of indexes keeps a list of labels', capture._label(['x', 'y'], [1, 0]),
      [{'__label__': 'y'}, {'__label__': 'x'}])
check('two scripts of one title are told apart', capture._unique('Seed', {'Seed': []}), 'Seed (2)')

# ------------------------------------------------------------ wiring
queue_button = Button('Queue', 'txt2img_queue')
capture._found.clear()
capture._found['txt2img'] = {'root': root, 'generate': generate, 'queue': queue_button}
capture._found['img2img'] = {'root': types.SimpleNamespace(fns={}), 'generate': i_generate,
                             'queue': Button('Queue', 'img2img_queue')}
capture.wire_queue_buttons()
check("the Queue button is wired to Generate's inputs and its listeners'",
      queue_button.wired['inputs'], capture.queue_inputs(own, others))
check('it shows nothing while it captures', (queue_button.wired['outputs'], queue_button.wired['show_progress']),
      ([], 'hidden'))
check('a tab whose Generate is not found is left unwired',
      hasattr(capture._found['img2img']['queue'], 'wired'), False)

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
