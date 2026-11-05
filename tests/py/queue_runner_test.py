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
person's own Generate, and waits for it before each task (#170); pauses
between tasks; runs a task now, before the others (#169); asks before running tasks whose scripts are gone; and at
startup stops what a restart left running.
"""
import dataclasses
import enum
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

    def postprocess(self, value):
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


class Mode(enum.Enum):
    BALANCED = 'Balanced'
    PROMPT = 'My prompt is more important'


@dataclasses.dataclass
class Unit:
    enabled: bool = False
    weight: float = 1.0
    # ControlNet's default holds an enum; the page sends back its text.
    mode: object = Mode.BALANCED


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


def queue_task(prompt, seed=7, unit=None, script_index=1, xyz=1, checkpoints=None):
    """Queue through the Queue button's own capture, as the page would - for several checkpoints, with their rows."""
    values = {FIXED[0]: '', FIXED[1]: prompt, FIXED[2]: 'blurry', FIXED[3]: 2,
              SCRIPT_LIST: script_index, SEED: seed, SUBSEED: -1, UNIT: unit or Unit(enabled=True, weight=0.5),
              XYZ_TYPE: xyz, XYZ_VALUES: '1,2'}
    inputs = list(own.inputs)
    task_id, _ = capture.capture('txt2img', own, [], inputs, [values[c] for c in inputs], 'sachi',
                                 checkpoints=checkpoints)
    return task_id, [values[c] for c in inputs]


def clear():
    jobs.join(5)
    with db._cursor() as cursor:
        cursor.execute('DELETE FROM tasks')
        cursor.execute('DELETE FROM task_generations')
        cursor.execute('DELETE FROM task_checkpoints')
    forge.plan, forge.calls, forge.interrupts = [], [], []
    forge.waiting.clear()
    forge.release.clear()
    runner._first.clear()
    runner._go.clear()


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
check('and the task says so', notes, ['New Extension: not in the task; its defaults were used'])
RUNNER.inputs.pop()
RUNNER.scripts.pop()
own.inputs = FIXED + RUNNER.inputs

kept = db.get_task(task_id)['inputs']
kept['scripts']['ControlNet'][0]['value'] = {'__missing__': 'Thing'}
values, notes = replay.rebuild('txt2img', own.inputs, kept)
check("a value that was not kept runs at its control's default", values[len(FIXED) + 3], Unit())
check('and says so', notes, ['ControlNet: 0: could not be restored; its default was used'])

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

# A task with no checkpoint - its one row with none, as v49 moves a v48 task
# whose columns were both NULL (#400) - runs on what Forge has loaded: no
# checkpoint in the override, and no VAE / text encoders.
clear()
bare, _ = queue_task('no checkpoint')
with db._cursor() as cursor:
    cursor.execute("UPDATE task_checkpoints SET checkpoint = NULL, modules = NULL WHERE task_id = ?", (bare,))
run_queue()
check('a task saved with no checkpoint runs on what Forge has loaded', (status_of(bare), forge.calls[0]['overrides']),
      ('completed', {'forge_additional_modules': []}))

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
    cursor.execute("UPDATE task_checkpoints SET checkpoint = 'missing.safetensors' WHERE task_id = ?",
                   (gone_model,))
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

# --------------------------------------------------------------- Run next
def ran():
    return [runner.queued_task(c['job']) for c in forge.calls]


def active():
    return [t['id'] for t in db.list_tasks(INSTALL_KEY, 'active', first=runner.first())[0]]


clear()
a, _ = queue_task('a')
b, _ = queue_task('b')
c, _ = queue_task('c')
check('stopped, Run next would move any task: it runs it alone', runner.unmoved(), set())
answer = runner.run_next([c])
jobs.join(10)
check('a stopped queue starts for the task alone', (answer['first'], answer['after'], ran()), ([c], None, [c]))
check('and stops after it, the rest left waiting',
      (runner.status()['progress']['state'], status_of(a), status_of(b)), ('stopped', 'pending', 'pending'))

clear()
a, _ = queue_task('a')
b, _ = queue_task('b')
c, _ = queue_task('c')
d, _ = queue_task('d')
e, _ = queue_task('e')
forge.plan = ['running']
runner.start()
forge.waiting.wait(5)
check('running, Run next would not move the next task', runner.unmoved(), {b})
answer = runner.run_next([d, c])
check('a running queue takes them next, in the order queued, after its task',
      (answer['first'], answer['after']), ([c, d], a))
check('Active shows them so', active(), [a, c, d, b, e])
check('nor them, nor the oldest left waiting, which runs after them anyway', runner.unmoved(), {c, d, b})
forge.release.set()
jobs.join(10)
check('and runs them so', ran(), [a, c, d, b, e])

clear()
a, _ = queue_task('a')
b, _ = queue_task('b')
c, _ = queue_task('c')
forge.plan = ['running']
runner.start()
forge.waiting.wait(5)
runner.run_next([c])
runner.pause()
forge.release.set()
check('Pause holds a task Run next asked for before it',
      wait_until(lambda: runner.status()['progress']['state'] == 'paused'), True)
time.sleep(0.6)
check('it waits', (ran(), status_of(c)), ([a], 'pending'))
check('paused, Run next would move it: it would run', runner.unmoved(), set())
answer = runner.run_next([b])
check('a paused queue runs one asked for since', wait_until(lambda: status_of(b) == 'completed'), True)
check('then is paused again', wait_until(lambda: runner.status()['progress']['state'] == 'paused'), True)
time.sleep(0.6)
check('the one held stays held', (answer['after'], ran(), status_of(c)), (None, [a, b], 'pending'))
runner.resume()
jobs.join(10)
check('Resume runs it', (ran(), status_of(c)), ([a, b, c], 'completed'))

clear()
a, _ = queue_task('a')
b, _ = queue_task('b')
forge.plan = ['running']
runner.run_next([a])
forge.waiting.wait(5)
check('Start, while a queue runs for Run next alone, has it go on with the rest', runner.start(),
      {'started': True, 'missing': []})
forge.release.set()
jobs.join(10)
check('and it does', ran(), [a, b])

clear()
a, _ = queue_task('a')
b, _ = queue_task('b')
forge.plan = ['running']
runner.start()
forge.waiting.wait(5)
runner.stop()
check('not while the queue is stopping: it would end first', runner.run_next([b]),
      {'first': [], 'after': None, 'skipped': [], 'missing': [], 'stopping': True})
forge.release.set()
jobs.join(10)
check('nothing was put first', (runner.first(), status_of(b)), ([], 'pending'))

clear()
a, _ = queue_task('a')
runner.run_next([a])
jobs.join(10)
gone = db.add_task({'install': 'another-install', 'mode': 'txt2img', 'inputs': {'fixed': {}}})
check('a task that ran, or is not this install\'s, is not run', runner.run_next([a, gone, 10 ** 9])['skipped'],
      [{'id': a, 'why': 'already completed'}, {'id': gone, 'why': 'not found'}, {'id': 10 ** 9, 'why': 'not found'}])

clear()
uses, _ = queue_task('uses X/Y/Z')
saved = list(RUNNER.inputs), list(RUNNER.scripts), list(SCRIPT_LIST.choices)
del RUNNER.inputs[4:6]
del RUNNER.scripts[2]
SCRIPT_LIST.choices[:] = [('None', 'None')]
own.inputs = FIXED + RUNNER.inputs
answer = runner.run_next([uses])
check('a task whose scripts are gone asks first, as Start does',
      (answer['missing'], answer['first'], status_of(uses)),
      ([{'task': uses, 'prompt': 'uses X/Y/Z', 'missing': ['X/Y/Z plot']}], [], 'pending'))
runner.run_next([uses], force=True)
jobs.join(10)
check('Run anyway runs it without them', status_of(uses), 'completed')
RUNNER.inputs[:], RUNNER.scripts[:], SCRIPT_LIST.choices[:] = saved
own.inputs = FIXED + RUNNER.inputs

# ------------------------------------- the person's own generation first
modules.progress = types.SimpleNamespace(current_task='task(abc)',
                                         pending_tasks={'task(mmq-3-1)': 1.0, 'task(def)': 2.0})
sys.modules['modules.progress'] = modules.progress
check("Forge's runs: the one holding its lock, then those waiting for it", forge_host.forge_jobs(),
      ['task(abc)', 'task(mmq-3-1)', 'task(def)'])
del sys.modules['modules.progress'], modules.progress
clear()
held, _ = queue_task('held')
real_jobs, real_grace = forge_host.forge_jobs, runner.HOLD_GRACE
forge_jobs_now = ['task(person-1)']
forge_host.forge_jobs = lambda: list(forge_jobs_now)
runner.HOLD_GRACE = 0.3
runner.start()
time.sleep(0.6)
check("while the person's own generation runs, the queue waits before its task",
      (ran(), status_of(held), runner.status()['progress']['holding']), ([], 'pending', True))
forge_jobs_now[:] = ['task(mmq-99-1)']
check("the queue's own runs do not hold it: a moment after, it goes on",
      wait_until(lambda: status_of(held) == 'completed'), True)
jobs.join(10)
check('and no longer says it waits', runner.status()['progress']['holding'], False)
forge_host.forge_jobs, runner.HOLD_GRACE = real_jobs, real_grace

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

# ------------------------------------------------------------ Load to UI
from model_manager.scheduler import load                 # noqa: E402

clear()
loaded, sent = queue_task('to load', unit=Unit(enabled=True, weight=0.7))
SKIP = object()
values, skipped, notes = load.task_values('txt2img', loaded, skip=SKIP)
# Generate's inputs but the first: prompt, negative, batch count, then the scripts'.
check("Load to UI hands each of Generate's inputs but the first its value",
      (values[:3], values[4:6], values[8]), (sent[1:4], sent[5:7], sent[9]))
check('an index as its choice, not its number', (values[3], values[7]), ('X/Y/Z plot', 'Seed'))
check("a state - ControlNet's units - keeps what is on screen, and is named",
      (values[6] is SKIP, skipped, notes), (True, ['ControlNet: 0'], []))
plain, _ = queue_task('units left off', unit=Unit(mode='Balanced'))
check("a state at its default keeps what is on screen, and is not named",
      load.task_values('txt2img', plain, skip=SKIP)[1:], ([], []))
SEED.postprocess = lambda value: (_ for _ in ()).throw(ValueError('not a seed'))
values, skipped, _ = load.task_values('txt2img', loaded, skip=SKIP)
del SEED.postprocess
check('a value its control does not take is skipped too', (values[4] is SKIP, skipped),
      (True, ['Seed: Seed', 'ControlNet: 0']))

theirs = db.add_task({'install': 'another-install', 'mode': 'txt2img', 'inputs': {'fixed': {}}})
other_tab = db.add_task({'install': INSTALL_KEY, 'mode': 'img2img', 'inputs': {'fixed': {}}})
for task_id, why in ((theirs, 'No task #%d in this WebUI' % theirs), (other_tab, 'Task #%d is an img2img task' % other_tab)):
    try:
        load.task_values('txt2img', task_id)
        raised = None
    except replay.TaskError as e:
        raised = str(e)
    check('only this install\'s tasks of this tab are loaded', raised, why)

import gradio as gr                                      # noqa: E402
answered = load._loader('txt2img', list(range(9)))(json.dumps({'task': loaded, 'nonce': 'n1'}))
check('the hidden button answers every output, and its own nonce, with what it skipped',
      (len(answered), answered[0], json.loads(answered[-1])),
      (10, 'to load', {'nonce': 'n1', 'task': loaded, 'skipped': ['ControlNet: 0'], 'notes': []}))
failed_load = load._loader('txt2img', list(range(9)))(json.dumps({'task': theirs, 'nonce': 'n2'}))
check('a task it cannot load changes nothing, and says why',
      (failed_load[:9] == [gr.update()] * 9, json.loads(failed_load[-1])),
      (True, {'nonce': 'n2', 'task': theirs, 'error': 'No task #%d in this WebUI' % theirs}))

# ------------------------------------- a task of several checkpoints (#400)
from model_manager.scheduler import tasks as task_rows   # noqa: E402

OTHER_VAE = os.path.join(WORK, 'models', 'VAE', 'other_vae.safetensors')
forge.checkpoints.add('third.safetensors')
forge.modules = [VAE, OTHER_VAE]
ROWS = [{'checkpoint': 'model.safetensors', 'modules': [VAE]},
        {'checkpoint': 'other.safetensors', 'modules': [OTHER_VAE], 'settings': {'usual': {'steps': 30}}},
        {'checkpoint': 'third.safetensors', 'modules': [], 'settings': {'another_family': True}}]
AT_SEED = own.inputs.index(SEED) - 1     # Generate's function is sent every input but the first


def several(prompt, seed=-1):
    return queue_task(prompt, seed=seed, checkpoints=ROWS)[0]


def statuses(task_id):
    return [r['status'] for r in db.get_task(task_id)['checkpoints']]


clear()
three = several('three checkpoints')
given = []
real_for_run = load.for_run
runner.load.for_run = lambda tab, named, settings: (given.append((id(named), settings)), real_for_run(tab, named, settings))[1]
run_queue()
runner.load.for_run = real_for_run
check("each run is given its own row's settings, from one copy of the task's inputs",
      ([settings for _, settings in given], len({named for named, _ in given})),
      ([None, {'usual': {'steps': 30}}, {'another_family': True}], 1))
check('a task of three checkpoints runs Generate three times, each run given its own checkpoint and VAE',
      [c['overrides'] for c in forge.calls],
      [{'sd_model_checkpoint': 'model.safetensors', 'forge_additional_modules': [VAE]},
       {'sd_model_checkpoint': 'other.safetensors', 'forge_additional_modules': [OTHER_VAE]},
       {'sd_model_checkpoint': 'third.safetensors', 'forge_additional_modules': []}])
check("each under an id of its own that names the task, so the recorder links every image to it",
      (ran(), len({c['job'] for c in forge.calls})), ([three] * 3, 3))
check('a seed of -1 is drawn once, and every run has it',
      (len({c['values'][AT_SEED] for c in forge.calls}), forge.calls[0]['values'][AT_SEED] != -1), (1, True))
check('the task completes, each row too, its first seed the first run\'s',
      (status_of(three), statuses(three), db.get_task(three)['first_seed']),
      ('completed', ['completed'] * 3, 1001))
check('the task itself keeps -1, for a Retry to draw again',
      db.get_task(three)['inputs']['scripts']['Seed'][0]['value'], -1)
check("and the queue's progress no longer names a run", (runner.status()['progress']['run'],
                                                         runner.status()['progress']['runs']), (0, 0))

clear()
boxed = several('an empty seed box', seed='')
run_queue()
seeds = {c['values'][AT_SEED] for c in forge.calls}
check("an empty seed box is drawn once too, kept as text as the box sends it",
      (len(seeds), all(isinstance(v, str) and v.isdigit() for v in seeds)), (1, True))

clear()
again = several('retried')
run_queue()
copy_id = db.add_task(task_rows.retried(db.get_task(again), 'random'))
forge.calls.clear()
run_queue()
check('Retry with a random seed of a task of three: one seed across its three runs',
      (len(forge.calls), len({c['values'][AT_SEED] for c in forge.calls})), (3, 1))

clear()
two_gone = several('rows 1 and 3 gone')
forge.checkpoints.difference_update({'model.safetensors', 'third.safetensors'})
run_queue()
forge.checkpoints.update({'model.safetensors', 'third.safetensors'})
check('two runs failing are each named, the error once each',
      db.get_task(two_gone)['error'],
      '2 of 3 failed: The checkpoint is not in this WebUI: model.safetensors; '
      'The checkpoint is not in this WebUI: third.safetensors')

clear()
gone = several('row 2 gone')
forge.checkpoints.discard('other.safetensors')
run_queue()
forge.checkpoints.add('other.safetensors')
check("row 2's checkpoint gone: rows 1 and 3 run", [c['overrides']['sd_model_checkpoint'] for c in forge.calls],
      ['model.safetensors', 'third.safetensors'])
check('the task ends Failed, its error naming row 2', (status_of(gone), db.get_task(gone)['error']),
      ('failed', '1 of 3 failed: The checkpoint is not in this WebUI: other.safetensors'))
check('each row as its run ended', statuses(gone), ['completed', 'failed', 'completed'])

clear()
stopped = several('stopped in run 2')
forge.plan = ['ok', 'running']
runner.start()
check('run 2 starts', wait_until(lambda: forge.waiting.is_set() and len(forge.calls) == 2), True)
runner.stop()
check('Stop interrupts run 2, the one going', forge.interrupts, [forge.calls[1]['job']])
forge.release.set()
jobs.join(10)
check('run 3 never starts, and the task ends Stopped', (len(forge.calls), status_of(stopped)), (2, 'stopped'))
check("run 1's row completed, run 2's stopped, run 3's never reached", statuses(stopped),
      ['completed', 'stopped', None])

clear()
interrupted = several('interrupted in run 2')
next_one, _ = queue_task('next')
forge.plan = ['ok', 'interrupt']
run_queue()
check("Forge's own Interrupt in run 2 ends the task Stopped, run 3 not run",
      (status_of(interrupted), statuses(interrupted)), ('stopped', ['completed', 'stopped', None]))
check('and the queue goes on to the next task', status_of(next_one), 'completed')

clear()
held_between = several('held between runs')
real_jobs, real_grace = forge_host.forge_jobs, runner.HOLD_GRACE
forge_jobs_now = []
forge_host.forge_jobs = lambda: list(forge_jobs_now)
runner.HOLD_GRACE = 0.3
forge.plan = ['running']
runner.start()
forge.waiting.wait(5)
forge_jobs_now[:] = ['task(person-2)']
forge.release.set()
time.sleep(0.6)
check("the person's own Generate waiting as run 1 ends: run 2 waits for it",
      (len(forge.calls), runner.status()['progress']['holding'], runner.status()['progress']['run']), (1, True, 1))
forge_jobs_now[:] = []
check('then runs 2 and 3 run', wait_until(lambda: status_of(held_between) == 'completed'), True)
jobs.join(10)

clear()
stopped_waiting = several('stopped while run 2 waits')
forge.plan = ['running']
runner.start()
forge.waiting.wait(5)
forge_jobs_now[:] = ['task(person-3)']
forge.release.set()
check('run 2 waits for the person', wait_until(lambda: runner.status()['progress']['holding']), True)
runner.stop()
jobs.join(10)
forge_jobs_now[:] = []
check('Stop while run 2 waits: no other run, the task ends Stopped, not Completed',
      (len(forge.calls), status_of(stopped_waiting), statuses(stopped_waiting)),
      (1, 'stopped', ['completed', None, None]))
forge_host.forge_jobs, runner.HOLD_GRACE = real_jobs, real_grace

clear()
paused = several('paused in run 1')
after_pause, _ = queue_task('after the pause')
forge.plan = ['running']
runner.start()
forge.waiting.wait(5)
runner.pause()
forge.release.set()
check('Pause during a task of three: all three run, then the queue pauses',
      wait_until(lambda: runner.status()['progress']['state'] == 'paused'), True)
check('the task completed every run, the next not started',
      (len(forge.calls), status_of(paused), status_of(after_pause)), (3, 'completed', 'pending'))
runner.resume()
jobs.join(10)

# The variation seed of a task of several, as fixed_seeds draws it (#400):
# drawn once where its strength is above 0, left alone where it is 0.
SEEDED = {'fixed': {}, 'scripts': {'Seed': [{'id': 'txt2img_seed', 'value': 5},
                                            {'id': 'txt2img_subseed', 'value': -1},
                                            {'id': 'txt2img_subseed_strength', 'value': 0.5}]}}
varied = runner.fixed_seeds('txt2img', SEEDED)['scripts']['Seed']
check('a variation seed of -1 with a strength above 0 is drawn; a seed set stays',
      (varied[0]['value'], varied[1]['value'] != -1, SEEDED['scripts']['Seed'][1]['value']), (5, True, -1))
SEEDED['scripts']['Seed'][2]['value'] = 0
check('with a strength of 0 the variation seed stays -1',
      runner.fixed_seeds('txt2img', SEEDED)['scripts']['Seed'][1]['value'], -1)

# A run's inputs as its row takes them (#400): its usual settings, Hires fix
# following what they set and no more; another family's run Hires fix's
# checkpoint "Use same" and the refiner off. The press itself is never changed.
PRESS = {'fixed': {'prompt': 'p', 'cfg_scale': 7.0, 'distilled_cfg_scale': 3.5, 'hr_cfg': 6.0, 'hr_distilled_cfg': 3.0,
                   'hr_sampler_name': 'Euler', 'hr_scheduler': 'Karras', 'hr_checkpoint_name': 'hires.safetensors',
                   'hr_additional_modules': ['sdxl_vae.safetensors']},
         'scripts': {'Sampler': [{'id': 'txt2img_sampling', 'value': 'Euler a'},
                                 {'id': 'txt2img_scheduler', 'value': 'Karras'},
                                 {'id': 'txt2img_steps', 'value': 20}],
                     'Refiner': [{'id': 'txt2img_enable', 'value': True}]}}


def hires(named):
    f = named['fixed']
    return (f['hr_sampler_name'], f['hr_scheduler'], f['hr_cfg'], f['hr_distilled_cfg'], f['hr_checkpoint_name'],
            named['scripts']['Refiner'][0]['value'])


every = load.for_run('txt2img', PRESS, {'usual': {'sampler': 'DPM++ 2M', 'schedule_type': 'Simple', 'cfg': 4,
                                                  'distilled_cfg': 2.5}})
check("a run takes its usual settings, Hires fix following: its sampler and schedule type Use same, its CFG the run's",
      (every['fixed']['cfg_scale'], hires(every)),
      (4, ('Use same sampler', 'Use same scheduler', 4, 2.5, 'hires.safetensors', True)))
some = load.for_run('txt2img', PRESS, {'usual': {'steps': 30}})
check('a Hires setting the usual ones leave alone stays as pressed', hires(some),
      ('Euler', 'Karras', 6.0, 3.0, 'hires.safetensors', True))
check('a usual Shift goes to Hires fix\'s one slider for either',
      load.for_run('txt2img', PRESS, {'usual': {'shift': 6}})['fixed']['hr_distilled_cfg'], 6)
other = load.for_run('txt2img', PRESS, {'another_family': True})
check("another family's run: Hires fix's checkpoint Use same and the refiner off, the rest as pressed",
      hires(other), ('Euler', 'Karras', 6.0, 3.0, 'Use same checkpoint', False))
check('a row with no settings runs the press as it is', load.for_run('txt2img', PRESS, None), PRESS)
check('and the press itself is never changed', hires(PRESS), ('Euler', 'Karras', 6.0, 3.0, 'hires.safetensors', True))

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
