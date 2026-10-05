"""
The queue's runner: model_manager/scheduler/replay.py and runner.py
(#150-#155), with Forge stood in - its lock, its id for the generation it
runs, Interrupt, the hooks, and what Generate's function gives back - into
the fixture library.

A task's inputs come back as Generate takes them now: by name, an index by
its label, a script's controls by id, an extension added since at its
defaults, a label no longer offered failing the task. The queue runs this
install's tasks in order, each through Generate's function under our own
id, until none is left; ends a task as failed, stopped or completed, and
goes on; sets each run up with its task's files; never interrupts the
person's own Generate; pauses between tasks; asks before running tasks
whose scripts are gone; and at startup stops what a restart left running.
"""
import dataclasses
import json
import os
import sys
import threading
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'queue_runner')
VAE = os.path.join(WORK, 'models', 'VAE', 'vae.safetensors')
opts = webui_stub.install(model_manager_queue_inputs_dir=os.path.join(WORK, 'queue-inputs'),
                          sd_model_checkpoint='model.safetensors', forge_additional_modules=[VAE])

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager import forge_host, generations        # noqa: E402
from model_manager.install import INSTALL_KEY            # noqa: E402
from model_manager.jobs import jobs                      # noqa: E402
from model_manager.scheduler import capture, replay, runner   # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def wait_until(condition, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


db, facts = fixtures.build(WORK)
dbmod._db_instance = db


# ------------------------------------------------------ Gradio, stood in
class Component(object):
    def __init__(self, label=None, elem_id=None, value=None, **attrs):
        self.label, self.elem_id, self.value = label, elem_id, value
        self.__dict__.update(attrs)

    def preprocess(self, value):
        return value


class Textbox(Component): pass
class Slider(Component): pass
class State(Component): pass


class Dropdown(Component):
    def preprocess(self, value):
        if getattr(self, 'type', None) == 'index':
            labels = [c[0] for c in self.choices]
            return labels.index(value) if value in labels else None
        return value


@dataclasses.dataclass
class Unit:
    enabled: bool = False
    weight: float = 1.0


def script(title, start, end):
    return types.SimpleNamespace(title=lambda: title, args_from=start, args_to=end)


SCRIPT_LIST = Dropdown('Script', 'script_list', value='None', type='index',
                       choices=[('None', 'None'), ('X/Y/Z plot', 'X/Y/Z plot')])
SEED = Slider('Seed', 'txt2img_seed', value=-1)
SUBSEED = Slider('Variation seed', None, value=-1)
UNIT = State(None, None, value=Unit())
XYZ_TYPE = Dropdown('X type', 'xyz_x_type', value='Seed', type='index',
                    choices=[('Nothing', 'Nothing'), ('Seed', 'Seed'), ('Steps', 'Steps')])
XYZ_VALUES = Textbox('X values', 'xyz_x_values', value='')
RUNNER = types.SimpleNamespace(
    inputs=[SCRIPT_LIST, SEED, SUBSEED, UNIT, XYZ_TYPE, XYZ_VALUES],
    scripts=[script('Seed', 1, 3), script('ControlNet', 3, 4), script('X/Y/Z plot', 4, 6)])

scripts_module = types.ModuleType('modules.scripts')
scripts_module.scripts_txt2img = RUNNER
txt2img_module = types.ModuleType('modules.txt2img')


def txt2img_create_processing(id_task, request, prompt, negative_prompt, n_iter, *args):
    pass


txt2img_module.txt2img_create_processing = txt2img_create_processing
modules = sys.modules['modules']
modules.scripts, modules.txt2img = scripts_module, txt2img_module
sys.modules.update({'modules.scripts': scripts_module, 'modules.txt2img': txt2img_module})

FIXED = [Textbox(None, None, value=''), Textbox('Prompt', 'txt2img_prompt', value=''),
         Textbox('Negative prompt', 'txt2img_neg_prompt', value=''), Slider('Batch count', 'txt2img_batch_count', value=1)]


# ------------------------------------------------------- Forge, stood in
class Forge(object):
    def __init__(self):
        self.job = None
        self.interrupted = False
        self.plan = []
        self.calls = []
        self.interrupts = []
        self.checkpoints = {'model.safetensors', 'other.safetensors'}
        self.modules = [VAE]
        self.waiting = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()


forge = Forge()
forge_host.current_job = lambda: forge.job
forge_host.interrupt = lambda: (forge.interrupts.append(forge.job), setattr(forge, 'interrupted', True))
forge_host.stop_this_run = lambda: setattr(forge, 'interrupted', True)
forge_host.was_interrupted = lambda: forge.interrupted
forge_host.checkpoint_listed = lambda name: name in forge.checkpoints
forge_host.installed_modules = lambda: {os.path.basename(p): p for p in forge.modules}
forge_host.last_error = lambda: None


def txt2img(id_task, request, *values):
    """Generate's function: Forge's lock, its id for the run, the hooks, its outputs."""
    outcome = forge.plan.pop(0) if forge.plan else 'ok'
    if outcome == 'locked':
        # The person's own Generate holds the lock: ours waits.
        forge.job = 'task(person)'
        forge.waiting.set()
        forge.release.wait(5)
    with forge.lock:
        forge.job, forge.interrupted = id_task, False
        p = types.SimpleNamespace(override_settings={})
        runner.on_before_process(p)
        call = {'job': id_task, 'username': request.username, 'values': list(values),
                'overrides': dict(p.override_settings), 'ended_at_start': forge.interrupted}
        forge.calls.append(call)
        if outcome == 'running':
            forge.waiting.set()
            forge.release.wait(5)
        if outcome == 'interrupt':
            forge.interrupted = True
        runner.on_postprocess(p, None)
        forge.job = None
    if outcome == 'error':
        return (None, None, '', '', "<div class='error'>RuntimeError: boom &amp; more</div><div class='performance'></div>")
    return ({'gallery': []}, None, json.dumps({'seed': 1000 + len(forge.calls), 'all_seeds': [1]}), '<p></p>', '<p></p>')


OUTPUTS = [Component(), Component(), Component(None, 'generation_info_txt2img'), Component(), Component()]
own = types.SimpleNamespace(fn=txt2img, inputs=FIXED + RUNNER.inputs, outputs=OUTPUTS, js='submit',
                            targets=[])
generate = Component('Generate', 'txt2img_generate', _id=1)
own.targets = [(1, 'click')]
capture._found['txt2img'] = {'root': types.SimpleNamespace(fns={0: own}), 'generate': generate,
                             'queue': Component('Queue', 'txt2img_queue')}


def queue_task(prompt, seed=7, unit=None, script_index=1, xyz=1):
    """Queue through the Queue button's own capture, as the page would."""
    values = {FIXED[0]: '', FIXED[1]: prompt, FIXED[2]: 'blurry', FIXED[3]: 2,
              SCRIPT_LIST: script_index, SEED: seed, SUBSEED: -1, UNIT: unit or Unit(enabled=True, weight=0.5),
              XYZ_TYPE: xyz, XYZ_VALUES: '1,2'}
    inputs = list(own.inputs)
    task_id, _ = capture.capture('txt2img', own, [], inputs, [values[c] for c in inputs], 'sachi')
    return task_id, [values[c] for c in inputs]


def clear():
    jobs.join(5)
    with db._cursor() as cursor:
        cursor.execute('DELETE FROM tasks')
        cursor.execute('DELETE FROM task_generations')
    forge.plan, forge.calls, forge.interrupts = [], [], []
    forge.waiting.clear()
    forge.release.clear()


def run_queue(force=False):
    started = runner.start(force)
    jobs.join(10)
    return started


def status_of(task_id):
    return db.get_task(task_id)['status']


# ------------------------------------------------------------- rebuilding
task_id, sent = queue_task('a red apple')
values, notes = replay.rebuild('txt2img', own.inputs, db.get_task(task_id)['inputs'])
check('a task comes back as Generate took it, every input but the id', values[1:], sent[1:])
check('with nothing taken from a default', notes, [])

XYZ_TYPE.choices.insert(1, ('Steps (old)', 'Steps (old)'))
values, _ = replay.rebuild('txt2img', own.inputs, db.get_task(task_id)['inputs'])
check('an index follows its label when the list grows before it', values[len(FIXED) + 4], 2)
XYZ_TYPE.choices[:] = [('Nothing', 'Nothing'), ('Steps', 'Steps')]
try:
    replay.rebuild('txt2img', own.inputs, db.get_task(task_id)['inputs'])
    raised = None
except replay.TaskError as e:
    raised = str(e)
check('a label no longer offered fails the task, naming it', raised,
      'X/Y/Z plot: X type: "Seed" is no longer offered')
XYZ_TYPE.choices[:] = [('Nothing', 'Nothing'), ('Seed', 'Seed'), ('Steps', 'Steps')]

RUNNER.inputs[1], RUNNER.inputs[2] = SUBSEED, SEED
own.inputs = FIXED + RUNNER.inputs
values, notes = replay.rebuild('txt2img', own.inputs, db.get_task(task_id)['inputs'])
check("a script's moved control finds its value by id, and the rest in order",
      (values[len(FIXED) + 1], values[len(FIXED) + 2], notes), (-1, 7, []))
RUNNER.inputs[1], RUNNER.inputs[2] = SEED, SUBSEED

ADDED = Slider('Strength', 'new_ext_strength', value=0.3)
RUNNER.inputs.append(ADDED)
RUNNER.scripts.append(script('New Extension', 6, 7))
own.inputs = FIXED + RUNNER.inputs
values, notes = replay.rebuild('txt2img', own.inputs, db.get_task(task_id)['inputs'])
check('an extension added since runs at its defaults', values[-1], 0.3)
check('and the task says so', notes, ['New Extension: not in the task; its defaults ran'])
RUNNER.inputs.pop()
RUNNER.scripts.pop()
own.inputs = FIXED + RUNNER.inputs

kept = db.get_task(task_id)['inputs']
kept['scripts']['ControlNet'][0]['value'] = {'__missing__': 'Thing'}
values, notes = replay.rebuild('txt2img', own.inputs, kept)
check("a value that was not kept runs at its control's default", values[len(FIXED) + 3], Unit())
check('and says so', notes, ['ControlNet: 0: could not be restored; its default ran'])

# ------------------------------------------------- scripts that are gone
clear()
task_id, _ = queue_task('uses X/Y/Z')
saved = list(RUNNER.inputs), list(RUNNER.scripts), list(SCRIPT_LIST.choices)
del RUNNER.inputs[4:6]
del RUNNER.scripts[2]
SCRIPT_LIST.choices[:] = [('None', 'None')]
own.inputs = FIXED + RUNNER.inputs
check('a task whose scripts are gone is listed before the queue starts', runner.missing_extensions(),
      [{'task': task_id, 'prompt': 'uses X/Y/Z', 'missing': ['X/Y/Z plot']}])
check('and the queue does not start', runner.start(), {'started': False, 'missing': runner.missing_extensions()})
check('nothing ran', (forge.calls, status_of(task_id)), ([], 'pending'))
run_queue(force=True)
check('Run anyway runs it without them', status_of(task_id), 'completed')
RUNNER.inputs[:], RUNNER.scripts[:], SCRIPT_LIST.choices[:] = saved
own.inputs = FIXED + RUNNER.inputs

# ---------------------------------------------------------------- a run
clear()
first, _ = queue_task('first')
second, _ = queue_task('second')
elsewhere = db.add_task({'install': 'another-install', 'mode': 'txt2img', 'inputs': {'fixed': {}}})
check('the queue starts', run_queue(), {'started': True, 'missing': []})
check("this install's tasks ran, in the order queued",
      [c['job'].split('-')[1] for c in forge.calls], [str(first), str(second)])
check('each under an id of the queue\'s own', all(runner.queued_task(c['job']) is not None for c in forge.calls), True)
check('and completed', (status_of(first), status_of(second)), ('completed', 'completed'))
check("with the first run's seed, from its generation info",
      (db.get_task(first)['first_seed'], db.get_task(second)['first_seed']), (1001, 1002))
check('as who queued it', forge.calls[0]['username'], 'sachi')
check("another install's task is left pending", status_of(elsewhere), 'pending')
check("each run is given its task's checkpoint and modules", forge.calls[0]['overrides'],
      {'sd_model_checkpoint': 'model.safetensors', 'forge_additional_modules': [VAE]})
check('the queue stopped by itself when none was left', runner.status()['progress']['state'], 'stopped')
check('and counted', (runner.status()['progress']['completed'], runner.status()['counts']['completed']), (2, 2))

# ------------------------------------------------- failures go on
clear()
failing, _ = queue_task('fails')
interrupted, _ = queue_task('interrupted')
last, _ = queue_task('last')
forge.plan = ['error', 'interrupt', 'ok']
run_queue()
check("an error fails the task, with Forge's text", (status_of(failing), db.get_task(failing)['error']),
      ('failed', 'RuntimeError: boom & more'))
check("Forge's own Interrupt stops the task", status_of(interrupted), 'stopped')
check('and the queue goes on to the next', status_of(last), 'completed')

# ------------------------------------------------------------- files
clear()
gone_model, _ = queue_task('model gone')
with db._cursor() as cursor:
    cursor.execute("UPDATE tasks SET checkpoint = 'missing.safetensors' WHERE id = ?", (gone_model,))
gone_vae, _ = queue_task('vae gone')
forge.modules = []
run_queue()
forge.modules = [VAE]
check('a checkpoint not in this WebUI fails the task, naming it',
      (status_of(gone_model), db.get_task(gone_model)['error']),
      ('failed', 'The checkpoint is not in this WebUI: missing.safetensors'))
check('so does a VAE or text encoder', db.get_task(gone_vae)['error'],
      f'A VAE or text encoder is not in this WebUI: {VAE}')
check('neither ran on whatever was loaded', forge.calls, [])

# --------------------------------------------------- Stop while running
clear()
running, _ = queue_task('running')
after, _ = queue_task('after')
forge.plan = ['running']
runner.start()
check('the run starts', forge.waiting.wait(5), True)
runner.stop()
check('Stop interrupts the run, as it is the queue\'s', forge.interrupts, [forge.calls[0]['job']])
check('the queue says it is stopping', runner.status()['progress']['state'], 'stopping')
forge.release.set()
jobs.join(10)
check('the task is stopped', status_of(running), 'stopped')
check('and no other starts', status_of(after), 'pending')

# --------------------------------- Stop while the person's Generate runs
clear()
waiting, _ = queue_task('waiting')
after, _ = queue_task('after')
forge.plan = ['locked']
runner.start()
check("the queue's run waits for the person's Generate", forge.waiting.wait(5), True)
theirs = types.SimpleNamespace(override_settings={'CLIP_stop_at_last_layers': 2})
runner.on_before_process(theirs)
check("the person's own Generate is not set up as a task", theirs.override_settings,
      {'CLIP_stop_at_last_layers': 2})
runner.stop()
check("Stop does not interrupt the person's Generate", forge.interrupts, [])
forge.release.set()
jobs.join(10)
check('our run ends as it starts', forge.calls[0]['ended_at_start'], True)
check('the task is stopped', status_of(waiting), 'stopped')
check('and no other starts', status_of(after), 'pending')

# ----------------------------------------------------------------- Pause
clear()
one, _ = queue_task('one')
two, _ = queue_task('two')
forge.plan = ['running']
runner.start()
forge.waiting.wait(5)
runner.pause()
check('Pause lets the running task finish', runner.status()['progress']['state'], 'pausing')
forge.release.set()
check('then the queue is paused', wait_until(lambda: runner.status()['progress']['state'] == 'paused'), True)
check('the task finished', status_of(one), 'completed')
check('and a paused queue names no task', (runner.status()['progress']['task_id'], runner.status()['progress']['job']),
      (None, None))
time.sleep(0.6)
check('and no other started', status_of(two), 'pending')
runner.resume()
jobs.join(10)
check('Resume goes on with the next', status_of(two), 'completed')

# --------------------------------------------------------------- startup
clear()
left, _ = queue_task('left running')
db.start_task(left)
check('at startup, a task a restart left running is stopped', (runner.recover(), status_of(left)),
      (1, 'stopped'))
blocked, _ = queue_task('blocked')
forge.plan = ['running']
runner.start()
forge.waiting.wait(5)
check('not while a queue runs: Reload UI keeps the process', runner.recover(), 0)
forge.release.set()
jobs.join(10)

# ------------------------------------------------- linking generations
check('a run of the queue is known by its id', runner.queued_task('task(mmq-12-1700000000000)'), 12)
check("the person's own Generate is not", runner.queued_task('task(abc123)'), None)
clear()
linked, _ = queue_task('linked')
generation_id = db.record_generation({'created_at': '2026-01-01T00:00:00', 'mode': 'txt2img', 'image_count': 1},
                                     [{'position': 0, 'path': os.path.join(WORK, 'x.png')}], [[]])
forge.job = f'task(mmq-{linked}-1)'
generations._link_to_task(db, generation_id)
forge.job = 'task(person)'
generations._link_to_task(db, generation_id + 1)
forge.job = None
check('the recorder links a generation to the task whose run made it', db.get_task(linked)['generations'],
      [generation_id])

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
