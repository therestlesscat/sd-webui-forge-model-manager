"""
The queue's endpoints: model_manager/api/scheduler.py and scheduler/tasks.py
(#151-#164), through FastAPI's test client, on the fixture library.

The queue's controls reach the runner; the Active and History lists come in
order, a page at a time, each row saying what its task asks for, with the
images its run made through the Generations tab's NSFW switch; a task's
details show everything it holds, readably; Retry queues a copy with the
first run's seed or a random one; Delete removes a task, with its data or
without, and its own files - but those a copy still names; Clear history
hides. Only this install's tasks are listed or acted on.
"""
import dataclasses
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

WORK = os.path.join(TESTS, 'work', 'queue_api')
INPUTS = os.path.join(WORK, 'queue-inputs')
OUTPUTS = os.path.join(WORK, 'outputs')
opts = webui_stub.install(model_manager_queue_inputs_dir=INPUTS)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from PIL import Image
except ImportError:
    print('fastapi or PIL is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.api import scheduler as api           # noqa: E402
from model_manager.install import INSTALL_KEY            # noqa: E402
from model_manager.nsfw import PG, PG13, X               # noqa: E402
from model_manager.scheduler import runner               # noqa: E402
from model_manager.scheduler.values import Keeper        # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
os.makedirs(OUTPUTS, exist_ok=True)
app = FastAPI()
api.register(app)
client = TestClient(app)


@dataclasses.dataclass
class Unit:
    enabled: bool = True
    weight: float = 0.5


def picture(path):
    Image.new('RGB', (8, 8), (200, 10, 10)).save(path)
    return path


def inputs(prompt, seed=-1, steps=30, hires=None, image=None):
    fixed = {'prompt': prompt, 'negative_prompt': 'blurry', 'n_iter': 2, 'batch_size': 1, 'width': 832,
             'height': 1216, 'enable_hr': False, 'hr_scale': 2, 'hr_resize_x': 0, 'hr_resize_y': 0}
    fixed.update(hires or {})
    if image:
        fixed['init_img'] = Keeper(os.path.join(INPUTS, 'task-' + image)).keep(
            Image.new('RGB', (8, 8)), image)
    return {'fixed': fixed, 'script': 'X/Y/Z plot', 'scripts': {
        'Seed': [{'id': 'txt2img_seed', 'label': 'Seed', 'value': seed},
                 {'id': 'txt2img_subseed', 'label': 'Variation seed', 'value': -1}],
        'Sampler': [{'id': 'txt2img_steps', 'label': 'Sampling Steps', 'value': steps},
                    {'id': 'txt2img_sampling', 'label': 'Sampling Method', 'value': 'Euler a'},
                    {'id': 'txt2img_scheduler', 'label': 'Schedule Type', 'value': 'Karras'}],
        'X/Y/Z plot': [{'id': 'script_txt2img_xyz_plot_x_type', 'label': 'X type', 'value': {'__label__': 'Seed'}}],
        'ControlNet': [{'id': None, 'label': None,
                        'value': {'__dataclass__': 'cn:Unit', 'fields': {'enabled': True, 'weight': 0.5}}},
                       {'id': None, 'label': None, 'value': {'__missing__': 'Thing'}}]}}


def queue(prompt, install=INSTALL_KEY, **kw):
    return db.add_task({'install': install, 'forge': 'neo', 'mode': 'txt2img', 'inputs': inputs(prompt, **kw),
                        'checkpoint': 'sdxl\\model.safetensors', 'modules': ['F:\\vae\\sdxl_vae.safetensors'],
                        'username': 'sachi'})


def run(task_id, status='completed', seed=None, generations=()):
    """End a task as the queue would, with generations of images at these levels."""
    db.start_task(task_id)
    made = []
    for n, levels in enumerate(generations):
        images = [{'position': i, 'path': picture(os.path.join(OUTPUTS, f'{task_id}-{n}-{i}.png')),
                   'prompt': 'a long enough prompt for the switch', 'prompt_nsfw_level': level}
                  for i, level in enumerate(levels)]
        generation_id = db.record_generation({'created_at': '2026-10-05T12:00:00', 'mode': 'txt2img',
                                              'image_count': len(images)}, images, [[] for _ in images])
        db.link_task_generation(task_id, generation_id)
        made.append(generation_id)
    db.finish_task(task_id, status, 'boom' if status == 'failed' else None, seed)
    return made


def post(path, **data):
    return client.post(path, data=data).json()


def listed(which, **params):
    return client.get('/model-manager/queue/tasks', params={'which': which, **params}).json()


# ------------------------------------------------------------- the queue
calls = []
runner.start = lambda force=False: calls.append(('start', force)) or {'started': force, 'missing': [] if force else [{'task': 1}]}
for action in ('stop', 'pause', 'resume'):
    setattr(runner, action, (lambda a: lambda: calls.append((a,)) or a != 'resume')(action))
check('Start asks the runner, not forced', client.post('/model-manager/queue/start').json(),
      {'success': True, 'started': False, 'missing': [{'task': 1}]})
check('Run anyway forces it', client.post('/model-manager/queue/start', params={'force': 'true'}).json()['started'], True)
check('Stop, Pause and Resume reach the runner',
      [post(f'/model-manager/queue/{a}')['acted'] for a in ('stop', 'pause', 'resume')], [True, True, False])
check('in that order', calls, [('start', False), ('start', True), ('stop',), ('pause',), ('resume',)])

# ------------------------------------------------------------- the lists
pending = queue('a red apple', image='apple')
done = queue('a lighthouse at dusk', image='lighthouse', seed=7)
broken = queue('a broken clock', image='clock')
theirs = queue('another install\'s task', install='another-install')
made = run(done, 'completed', seed=1234, generations=[[PG, X], [PG, PG13, None, PG]])
run(broken, 'failed', generations=[[PG]])

status = client.get('/model-manager/queue/status').json()
check("the status counts this install's tasks", (status['success'], status['counts']['pending'],
                                                 status['counts']['completed'], status['counts']['failed']),
      (True, 1, 1, 1))
active = listed('active')
check("Active holds this install's pending tasks", [t['id'] for t in active['tasks']], [pending])
history = listed('history', hide_nsfw_images='false')
check('History holds the ended ones, newest first', [t['id'] for t in history['tasks']], [broken, done])
check('a list says its size', (history['total'], history['page'], history['pages']), (2, 1, 1))
check('an unknown list is refused', client.get('/model-manager/queue/tasks', params={'which': 'all'}).status_code, 404)

row = history['tasks'][1]
check("a row says what its task asks for",
      {k: row[k] for k in ('prompt', 'mode', 'status', 'sampler', 'scheduler', 'steps', 'width', 'height',
                           'hires', 'batch_size', 'n_iter', 'script', 'checkpoint', 'modules', 'first_seed')},
      {'prompt': 'a lighthouse at dusk', 'mode': 'txt2img', 'status': 'completed', 'sampler': 'Euler a',
       'scheduler': 'Karras', 'steps': 30, 'width': 832, 'height': 1216, 'hires': None, 'batch_size': 1,
       'n_iter': 2, 'script': 'X/Y/Z plot', 'checkpoint': 'sdxl\\model.safetensors',
       'modules': ['F:\\vae\\sdxl_vae.safetensors'], 'first_seed': 1234})
check('a failed one, its error', history['tasks'][0]['error'], 'boom')
check("a row has its run's first images", ([i['generation_id'] for i in row['images']], row['image_count']),
      ([made[0], made[0], made[1], made[1]], 6))
check('drawn as the Generations tab draws them',
      (row['images'][0]['url'], row['images'][1]['mm_level']),
      ('/model-manager/generations/images/%d/file' % row['images'][0]['id'], X))
hiding = listed('history', hide_nsfw_images='true')['tasks'][1]
check('through its NSFW switch', ([i['mm_level'] for i in hiding['images']], hiding['hidden_nsfw']),
      ([PG, PG, PG13, PG], 2))
opts.model_manager_generations_hide_nsfw = True
check("the Generations tab's own setting when the page sends none",
      listed('history')['tasks'][1]['hidden_nsfw'], 2)
opts.model_manager_generations_hide_nsfw = False

hires = queue('hires', hires={'enable_hr': True, 'hr_scale': 1.5})
resized = queue('resized', hires={'enable_hr': True, 'hr_resize_x': 2048})
rows = {t['id']: t for t in listed('active')['tasks']}
check("hires fix as it was set: a scale, or a resize", (rows[hires]['hires'], rows[resized]['hires']),
      ({'scale': 1.5}, {'resize': [2048, 0]}))

many = [queue(f'page filler {n}') for n in range(api.PAGE_SIZE)]
second = listed('active', page=2)
# Three were pending before them: page 2 holds the last three.
check('a list comes a page at a time', ([t['id'] for t in second['tasks']], second['pages'], second['total']),
      (many[-3:], 2, api.PAGE_SIZE + 3))
post('/model-manager/queue/delete', ids=','.join(map(str, many + [hires, resized])))

# ------------------------------------------------------------- details
details = client.get(f'/model-manager/queue/tasks/{done}', params={'hide_nsfw_images': 'false'}).json()
check('details have every image of the run', len(details['task']['images']), 6)
fixed = {f['name']: f['value'] for f in details['inputs']['fixed']}
check("and Generate's inputs, by name", (fixed['prompt'], fixed['negative_prompt'], fixed['width']),
      ('a lighthouse at dusk', 'blurry', 832))
check('a kept image by its name', fixed['init_img'], {'__kind__': 'image', 'name': 'lighthouse.png'})
scripts = {s['title']: s['controls'] for s in details['inputs']['scripts']}
check('each script under its title, a label as itself', scripts['X/Y/Z plot'],
      [{'id': 'script_txt2img_xyz_plot_x_type', 'label': 'X type', 'value': 'Seed'}])
check('an object by its class and fields, a value not kept as such',
      [c['value'] for c in scripts['ControlNet']],
      [{'__kind__': 'object', 'name': 'Unit', 'fields': {'enabled': True, 'weight': 0.5}},
       {'__kind__': 'missing', 'name': 'Thing'}])
check("another install's task is not shown", client.get(f'/model-manager/queue/tasks/{theirs}').status_code, 404)
check('nor one that is not there', client.get('/model-manager/queue/tasks/999999').status_code, 404)

# ------------------------------------------------------------- Retry
textbox = queue('a textbox seed', seed='-1')
run(textbox, 'stopped', seed=55)
seedless = queue('failed before its first image', seed=77)
run(seedless, 'failed')
answer = post('/model-manager/queue/retry', ids=f'{done},{textbox},{seedless},{pending},{theirs}')
copies = answer['queued']
check('Retry copies each ended task', len(copies), 3)
check('but none still to run, nor another install\'s', answer['skipped'],
      [{'id': pending, 'why': 'still pending'}, {'id': theirs, 'why': 'not found'}])
seeds = [db.get_task(c)['inputs']['scripts']['Seed'][0]['value'] for c in copies]
check("with the first run's seed; a textbox's as text; none, the queued one", seeds, [1234, '55', 77])
copy = db.get_task(copies[0])
check('the copy is pending, at the end of the queue, naming its original',
      (copy['status'], copy['retry_of'], listed('active')['tasks'][-1]['id']), ('pending', done, copies[-1]))
check('the original names its copy', [t['retried_as'] for t in listed('history')['tasks'] if t['id'] == done],
      [copies[0]])
check('the copy is the task as it was queued',
      (copy['inputs']['fixed'], copy['checkpoint'], copy['modules'], copy['username']),
      (db.get_task(done)['inputs']['fixed'], 'sdxl\\model.safetensors', ['F:\\vae\\sdxl_vae.safetensors'], 'sachi'))
random_copy = post('/model-manager/queue/retry', ids=str(done), seed='random')['queued'][0]
check('or with a random seed', db.get_task(random_copy)['inputs']['scripts']['Seed'][0]['value'], -1)
check('an unknown seed choice is refused',
      client.post('/model-manager/queue/retry', data={'ids': str(done), 'seed': 'lucky'}).status_code, 400)

# ------------------------------------------------------------- Delete
clock_file = db.get_task(broken)['inputs']['fixed']['init_img']['__image__']
clock_generation = db.get_task(broken)['generations'][0]
answer = post('/model-manager/queue/delete', ids=str(broken))
check('Delete removes the task', (answer['deleted'], db.get_task(broken)), ([broken], None))
check('without its data, its generations stay', db.get_generation(clock_generation) is not None, True)
check('its own files go, and their folder',
      (answer['deleted_inputs'], os.path.exists(clock_file), os.path.exists(os.path.dirname(clock_file))),
      (1, False, False))

lighthouse_file = db.get_task(done)['inputs']['fixed']['init_img']['__image__']
image_paths = [db.get_generation_image_path(i['id']) for i in details['task']['images']]
answer = post('/model-manager/queue/delete', ids=str(done), with_data='true')
check('with its data, its generations go', [db.get_generation(g) for g in made], [None, None])
check('their image files too', (answer['deleted_files'], [os.path.exists(p) for p in image_paths]),
      (6, [False] * 6))
check("but not files a copy still names", (answer['deleted_inputs'], os.path.exists(lighthouse_file)), (0, True))
post('/model-manager/queue/delete', ids=f'{copies[0]},{random_copy}')
check('they go with the last task that names them', os.path.exists(lighthouse_file), False)

db.start_task(pending)
answer = post('/model-manager/queue/delete', ids=f'{pending},{theirs}')
check("a running task is not deleted, nor another install's",
      (answer['skipped'], db.get_task(pending)['status'], db.get_task(theirs) is not None),
      ([{'id': pending, 'why': 'running'}, {'id': theirs, 'why': 'not found'}], 'running', True))

# ------------------------------------------------------- Clear history
ended = listed('history')['total']
answer = post('/model-manager/queue/history/clear')
check('Clear history hides every ended task', (answer['hidden'], listed('history')['total']), (ended, 0))
check('and nothing else', [t['id'] for t in listed('active')['tasks']], [pending] + copies[1:])
check('nothing is deleted', db.get_task(textbox)['status'], 'stopped')

db.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
