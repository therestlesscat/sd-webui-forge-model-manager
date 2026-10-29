"""
The images an img2img generation started from (#34): model_manager/
generation_inputs.py, the press listener (scheduler/capture.py), the recorder
(generations.py), the loader Send and Load to UI share (scheduler/load.py),
the deletes and the route - with Forge and Gradio stood in, into the fixture
library.

A press holds the canvases its mode reads; the recorder keeps them as files
in a store, one file per picture, and names them in the generation's inputs
and in generation_input_files. Send sets them back, leaves every other mode's
canvases as they are on screen, and says whether the source came back. A
delete clears the rows of generations that are gone and the files no row
names. A queued task's generation keeps its own copies.

Each check runs on its own: on code without these, it fails by name.
"""
import copy
import dataclasses
import os
import shutil
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

WORK = os.path.join(TESTS, 'work', 'generation_inputs')
STORE = os.path.join(WORK, 'store')
OTHER_STORE = os.path.join(WORK, 'store-2')
OUT = os.path.join(WORK, 'outputs')
opts = webui_stub.install(model_manager_record_generations=True, model_manager_queue_enabled=True,
                          model_manager_queue_inputs_dir=os.path.join(WORK, 'queue-inputs'),
                          model_manager_generations_keep_inputs=True,
                          model_manager_generations_inputs_dir=STORE)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from PIL import Image
except ImportError:
    print('fastapi or PIL is not installed; run this with the WebUI\'s python')
    sys.exit(0)

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
    def __init__(self, label=None, elem_id=None, value=None, **attrs):
        self.label, self.elem_id, self.value = label, elem_id, value
        self.__dict__.update(attrs)

    def preprocess(self, value):
        return value

    def postprocess(self, value):
        return value


class Dropdown(Component): pass


class Button(Component):
    def click(self, **wiring):
        pass


CANVAS_NAMES = ['init_img', 'sketch', 'sketch_fg', 'init_img_with_mask', 'init_img_with_mask_fg',
                'inpaint_color_sketch', 'inpaint_color_sketch_fg', 'init_img_inpaint', 'init_mask_inpaint']
FIXED = ([Component(None), Component('Mode', value=0), Component('Prompt', 'img2img_prompt', value='')]
         + [Component(name) for name in CANVAS_NAMES])
SCRIPT_LIST = Dropdown('Script', 'script_list', value='None', type='index', choices=[('None', 'None')])
RUNNER = types.SimpleNamespace(inputs=[SCRIPT_LIST], scripts=[])


def img2img_function(id_task, request, mode, prompt, init_img, sketch, sketch_fg, init_img_with_mask,
                     init_img_with_mask_fg, inpaint_color_sketch, inpaint_color_sketch_fg,
                     init_img_inpaint, init_mask_inpaint, *args):
    pass


def img2img(*args):
    pass


# ------------------------------------------------------- Forge, stood in
modules = sys.modules['modules']
img2img_module = types.ModuleType('modules.img2img')
img2img_module.img2img_function = img2img_function
scripts_module = types.ModuleType('modules.scripts')
scripts_module.scripts_img2img = RUNNER
scripts_module.scripts_txt2img = types.SimpleNamespace(inputs=[], scripts=[])
progress = types.ModuleType('modules.progress')
progress.current_task = None
for name, module in (('img2img', img2img_module), ('scripts', scripts_module), ('progress', progress)):
    setattr(modules, name, module)
    sys.modules['modules.' + name] = module
shared = sys.modules['modules.shared']
shared.sd_model = types.SimpleNamespace(sd_checkpoint_info=types.SimpleNamespace(
    filename=facts['linked_paths'][0], sha256='abc123'))
networks = types.ModuleType('networks')
networks.loaded_networks = []
sys.modules['networks'] = networks

from model_manager import generation_inputs, generations          # noqa: E402
from model_manager.api import generations as api_generations      # noqa: E402
from model_manager.api import scheduler as api_scheduler          # noqa: E402
from model_manager.db import migrations                           # noqa: E402
from model_manager.install import INSTALL_KEY                     # noqa: E402
from model_manager.scheduler import capture, load                 # noqa: E402
from model_manager.scheduler.values import Keeper                 # noqa: E402

generations.parse_generation_parameters = lambda text: {'Prompt': (text or '').split('\n')[0]}
GENERATE = Button('Generate', 'img2img_generate')
OWN = types.SimpleNamespace(fn=img2img, inputs=FIXED + RUNNER.inputs, outputs=[],
                            targets=[(id(GENERATE), 'click')], js='submit')
capture._found.clear()
capture._found['img2img'] = {'root': types.SimpleNamespace(fns={0: OWN}), 'generate': GENERATE,
                             'queue': None}
capture.generate_listeners = lambda root, generate: (OWN, [])
record = capture._recorder('img2img', OWN)
app = FastAPI()
api_generations.register(app)
api_scheduler.register(app)
client = TestClient(app)


def picture(colour, size=(64, 48)):
    return Image.new('RGBA', size, colour)


def stroke(size=(64, 48), y=20):
    layer = Image.new('RGBA', size, (0, 0, 0, 0))
    for x in range(10, 30):
        layer.putpixel((x, y), (255, 255, 255, 255))
    return layer


def press_values(job, mode, **canvases):
    """Generate's values for a press of img2img: its id, the mode, a prompt,
    then each canvas - None where nothing is in it."""
    return [job, mode, 'a lighthouse'] + [canvases.get(name) for name in CANVAS_NAMES] + [0]


@dataclasses.dataclass
class Processing:
    """StableDiffusionProcessingImg2Img, as far as the hooks look at one."""
    prompt: str = 'a lighthouse'
    negative_prompt: str = ''
    n_iter: int = 1
    batch_size: int = 1
    width: int = 64
    height: int = 48
    init_images: list = dataclasses.field(default_factory=list)
    extra_generation_params: dict = dataclasses.field(default_factory=dict)
    script_args: list = dataclasses.field(default_factory=list)
    scripts: object = None


class PP(object):
    def __init__(self, image, index):
        self.image, self.index = image, index


counter = [0]


def run(job, saved=True, adetailer=False):
    """One run of a press through the recorder's hooks, as processing.py
    calls them; its result saved unless not. With adetailer, ADetailer's
    calls on copies of the run come before the result, as its
    postprocess_image makes them at a batch's first and last image (#241)."""
    progress.current_task = job
    p = Processing()
    generations.before_process(p)
    p.all_prompts, p.all_negative_prompts, p.all_seeds, p.all_subseeds = ['a lighthouse'], [''], [1], [2]
    generations.process(p)
    p.iteration = 0
    generations.process_batch(p)
    result = Image.new('RGB', (64, 48), (1, 2, 3))
    pp = PP(result, 0)
    if adetailer:
        generations.postprocess(copy.copy(p), types.SimpleNamespace(video_path=None))
        twin = copy.copy(p)
        generations.before_process(twin)
        generations.process(twin)
    generations.result_ready(p, pp)
    if saved:
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, '%05d.png' % counter[0])
        counter[0] += 1
        result.save(path)
        result.already_saved_as = path
        generations.image_saved(types.SimpleNamespace(image=result, p=p, filename=path,
                                                      pnginfo={'parameters': 'a lighthouse\nSteps: 20'}))
    answer = generations.postprocess(p, types.SimpleNamespace(video_path=None))
    progress.current_task = None
    return answer


def store_files(store=STORE):
    """Every file in the store, in its subfolders."""
    return sorted(os.path.relpath(os.path.join(at, name), store)
                  for at, _, names in os.walk(store) for name in names) if os.path.isdir(store) else []


def store_of(path):
    """The store a kept file is in: above its two-letter subfolder."""
    return os.path.dirname(os.path.dirname(path))


def kept_rows(generation_id):
    return dict(db._get_connection().execute(
        "SELECT name, path FROM generation_input_files WHERE generation_id = ?", (generation_id,)).fetchall())


def same_pixels(path, image):
    with Image.open(path) as kept:
        return kept.convert(image.mode).tobytes() == image.tobytes()


# ============================================== 1. an Inpaint press, recorded
source, mask = picture((40, 90, 160, 255)), stroke()
attempt(lambda: record(*press_values('task(inpaint)', 2, init_img_with_mask=source,
                                     init_img_with_mask_fg=mask, init_img=picture((9, 9, 9, 255)))))
inpaint_id = attempt(lambda: run('task(inpaint)'))
inputs = attempt(lambda: db.get_generation(inpaint_id)['inputs']['fixed'])
rows = attempt(lambda: kept_rows(inpaint_id))
check('an Inpaint press keeps its picture and its mask: two files in the store',
      len(store_files()), 2)
check('named in the generation\'s inputs, where Send reads them',
      attempt(lambda: (sorted(k for k in ('init_img_with_mask', 'init_img_with_mask_fg')
                              if '__image__' in inputs[k]),
                       same_pixels(inputs['init_img_with_mask']['__image__'], source),
                       same_pixels(inputs['init_img_with_mask_fg']['__image__'], mask))),
      (['init_img_with_mask', 'init_img_with_mask_fg'], True, True))
check('and in the table, one row each',
      attempt(lambda: sorted(rows)), ['init_img_with_mask', 'init_img_with_mask_fg'])
check('each under its name\'s first two letters, as a thumbnail is',
      attempt(lambda: [os.path.basename(os.path.dirname(p)) == os.path.basename(p)[:2]
                       and store_of(p) == os.path.abspath(STORE) for p in rows.values()]), [True, True])

# ===================== 2. an img2img press, an old picture left in Inpaint
attempt(lambda: record(*press_values('task(plain)', 0, init_img=picture((200, 10, 10, 255)),
                                     init_img_with_mask=picture((0, 200, 0, 255)))))
plain_id = attempt(lambda: run('task(plain)'))
plain = attempt(lambda: db.get_generation(plain_id)['inputs']['fixed'])
check('img2img\'s own mode keeps only its picture; Inpaint\'s old one is not kept',
      attempt(lambda: (sorted(kept_rows(plain_id)), plain['init_img_with_mask'])),
      (['init_img'], {'__missing__': 'Image'}))

# ======================================== 3. two presses, the same picture
attempt(lambda: record(*press_values('task(again)', 2, init_img_with_mask=picture((40, 90, 160, 255)),
                                     init_img_with_mask_fg=stroke())))
again_id = attempt(lambda: run('task(again)'))
check('the same picture and mask pressed again: no new file, both generations name the same ones',
      attempt(lambda: (len(store_files()), kept_rows(again_id) == kept_rows(inpaint_id))), (3, True))

# ===================================== 5. a press whose run saves nothing
before = store_files()
attempt(lambda: record(*press_values('task(nothing)', 2, init_img_with_mask=picture((1, 1, 1, 255)))))
check('a run that saves nothing records nothing', attempt(lambda: run('task(nothing)', saved=False)), None)
check('writes nothing to the store', store_files(), before)
check('and holds no images after it', attempt(lambda: len(capture._held)), 0)

# ============================================ 7 and 15. Send, and Load to UI
SKIP = object()
values = attempt(lambda: load.generation_values('img2img', inpaint_id, None, skip=SKIP))
at = {name: n - 1 for n, name in enumerate(['id_task', 'mode', 'prompt'] + CANVAS_NAMES)}
check('Send sets Inpaint\'s picture and mask from the kept files',
      attempt(lambda: (same_pixels(inputs['init_img_with_mask']['__image__'], values[0][at['init_img_with_mask']]),
                       values[0][at['init_img_with_mask_fg']].tobytes() == mask.tobytes())), (True, True))
check('and leaves every other mode\'s canvases as they are on screen',
      attempt(lambda: [values[0][at[name]] is SKIP for name in CANVAS_NAMES
                       if name not in ('init_img_with_mask', 'init_img_with_mask_fg')]), [True] * 7)
check('without listing them as left at their defaults',
      attempt(lambda: [n for n in values[1] + values[2] if n.startswith(('init_img:', 'sketch'))]), [])
check('the answer says the mode, Inpaint, and that the source came back',
      attempt(lambda: load._canvas_answer('img2img', {'generation': inpaint_id})), {'mode': 2, 'source': True})
old_style = db.record_generation({'created_at': '2026-10-18T10:00:00', 'mode': 'img2img', 'image_count': 1,
                                  'inputs': {'fixed': {'mode': 2, 'init_img_with_mask': {'__missing__': 'Image'}}}},
                                 [{'position': 0, 'path': os.path.join(OUT, 'old.png')}], [[]])
check('one recorded before #34: the source did not come back',
      attempt(lambda: load._canvas_answer('img2img', {'generation': old_style})), {'mode': 2, 'source': False})

task_inputs = capture.name_inputs('img2img', OWN.inputs,
                                  press_values('task(q)', 2, init_img_with_mask=picture((5, 6, 7, 255)),
                                               init_img_with_mask_fg=stroke(y=30), sketch=picture((8, 8, 8, 255))),
                                  Keeper(os.path.join(WORK, 'queue-inputs', 'task-one')))
loaded_task = db.add_task({'install': INSTALL_KEY, 'mode': 'img2img', 'inputs': task_inputs})
task_values = attempt(lambda: load.task_values('img2img', loaded_task, skip=SKIP))
check('Load to UI leaves the other modes\' canvases too, though the task kept Sketch\'s',
      attempt(lambda: (task_values[0][at['sketch']] is SKIP, task_values[0][at['init_img_with_mask']] is SKIP)),
      (True, False))

# =================== 6. a queued task's generation, then the task deleted
progress_job = 'task(mmq-%d-1)' % loaded_task
attempt(lambda: capture._pressed.clear())
queued_id = attempt(lambda: run(progress_job))
queued = attempt(lambda: db.get_generation(queued_id)['inputs']['fixed'])
check('a queued task\'s generation names its own copies in the store, not the task\'s files',
      attempt(lambda: (store_of(queued['init_img_with_mask']['__image__']) == os.path.abspath(STORE),
                       store_of(queued['init_img_with_mask_fg']['__image__']) == os.path.abspath(STORE),
                       queued['sketch'])),
      (True, True, {'__missing__': 'image'}))
answer = client.post('/model-manager/queue/delete', data={'ids': str(loaded_task), 'with_data': 'false'}).json()
check('the task deleted, its own files go - Sketch\'s too', attempt(lambda: (answer['deleted'], answer['deleted_inputs'])),
      ([loaded_task], 3))
check('and its generation\'s source still comes back',
      attempt(lambda: load._canvas_answer('img2img', {'generation': queued_id})), {'mode': 2, 'source': True})

# ================================================ 10. the route
got = client.get('/model-manager/generations/%d/input/init_img_with_mask' % inpaint_id)
check('the route sends a kept file', (got.status_code, got.headers.get('content-type')), (200, 'image/png'))
check('not a name the generation did not keep',
      client.get('/model-manager/generations/%d/input/sketch' % inpaint_id).status_code, 404)
check('nor a path', client.get('/model-manager/generations/%d/input/..%%5C..%%5Cmodels.db' % inpaint_id).status_code,
      404)
page = client.get('/model-manager/generations/%d/images' % inpaint_id).json()
check('an image of a kept generation says where its source and mask are, and what the mask is',
      attempt(lambda: page['images'][0]['inputs']),
      {'source': '/model-manager/generations/%d/input/init_img_with_mask' % inpaint_id,
       'layer': '/model-manager/generations/%d/input/init_img_with_mask_fg' % inpaint_id, 'layer_kind': 'mask'})
check('one that kept nothing says nothing of it',
      attempt(lambda: 'inputs' in api_generations._image(
          next(iter(db.get_generation_images([db.get_generation(old_style)['images'][0]['id']]).values())),
          api_generations._kept_views(db, [old_style]))), False)

# ======================================================== 4. the deletes
shared_files = sorted(kept_rows(inpaint_id).values())
client.post('/model-manager/generations/%d/delete' % inpaint_id)
check('one of two generations naming a file deleted: its rows go, the file stays',
      (kept_rows(inpaint_id), all(os.path.isfile(p) for p in shared_files)), ({}, True))
again_image = attempt(lambda: db.get_generation(again_id)['images'][0]['id'])
client.post('/model-manager/generations/images/%s/delete' % again_image)
check('the other, by deleting its last image: the files go too',
      (kept_rows(again_id), [os.path.isfile(p) for p in shared_files]), ({}, [False, False]))
plain_file = list(kept_rows(plain_id).values())
client.post('/model-manager/generations/delete-many', data={'generation_ids': str(plain_id)})
check('Select\'s Delete takes its files as well', [os.path.isfile(p) for p in plain_file], [False])
task_two = db.add_task({'install': INSTALL_KEY, 'mode': 'img2img', 'inputs': {'fixed': {}}})
db.link_task_generation(task_two, queued_id)
db._get_connection().execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_two,))
db._get_connection().commit()
queued_files = list(kept_rows(queued_id).values())
client.post('/model-manager/queue/delete', data={'ids': str(task_two), 'with_data': 'true'})
check('a task deleted with its data takes its generation\'s kept files',
      [os.path.isfile(p) for p in queued_files], [False, False])

# ====================== 16. ADetailer ends a copy of the run first (#241)
attempt(lambda: record(*press_values('task(adetailer)', 0, init_img=picture((30, 60, 90, 255)))))
adetailer_id = attempt(lambda: run('task(adetailer)', adetailer=True))
check('a press ADetailer ran in keeps its picture: its end hook on a copy of the run takes nothing',
      attempt(lambda: sorted(kept_rows(adetailer_id))), ['init_img'])

# =========================================== 9. the switch, and the folder
opts.model_manager_generations_keep_inputs = False
attempt(lambda: record(*press_values('task(off)', 0, init_img=picture((3, 3, 3, 255)))))
off_id = attempt(lambda: run('task(off)'))
check('with the switch off, a press keeps nothing', attempt(lambda: kept_rows(off_id)), {})
opts.model_manager_generations_keep_inputs = True
attempt(lambda: record(*press_values('task(first)', 0, init_img=picture((4, 4, 4, 255)))))
first_id = attempt(lambda: run('task(first)'))
opts.model_manager_generations_inputs_dir = OTHER_STORE
attempt(lambda: record(*press_values('task(second)', 0, init_img=picture((5, 5, 5, 255)))))
second_id = attempt(lambda: run('task(second)'))
opts.model_manager_generations_inputs_dir = STORE
check('the folder changed between two presses: each press\'s file where the folder was then',
      attempt(lambda: (store_of(kept_rows(first_id)['init_img']) == os.path.abspath(STORE),
                       store_of(kept_rows(second_id)['init_img']) == os.path.abspath(OTHER_STORE))),
      (True, True))
opts.model_manager_generations_inputs_dir = ''
check('with no folder named, the store is generation-inputs beside the database, as the thumbnails\' folder is',
      attempt(lambda: generation_inputs.folder()),
      os.path.join(os.path.dirname(os.path.abspath(dbmod.database_path())), 'generation-inputs'))
opts.model_manager_generations_inputs_dir = '"%s"' % STORE
check('a folder named in quotes is read without them', attempt(lambda: generation_inputs.folder()), os.path.normpath(STORE))
opts.model_manager_generations_inputs_dir = STORE

# ========================================== 12. migration v43 to v44
old = os.path.join(WORK, 'v43', 'models.db')
os.makedirs(os.path.dirname(old))
conn = sqlite3.connect(old)
conn.execute("CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT)")
migrations.run_migrations(conn.cursor(), 0, 43, old, os.path.dirname(old))
conn.execute("INSERT INTO generations (created_at, mode, image_count) VALUES ('2026-10-18', 'img2img', 1)")
conn.commit()


# What a later migration adds, which v44 does not touch: v46's column on
# models (#262). Such a table is compared by its other columns, not its SQL.
LATER = {'models': {'civitai_gone_at'}}


def dump(path):
    with sqlite3.connect(path) as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                          "AND name NOT IN ('schema_info', 'generation_input_files') ORDER BY name")]
        out = {}
        for t in tables:
            cols = [r[1] for r in c.execute('PRAGMA table_info("%s")' % t) if r[1] not in LATER.get(t, ())]
            sql = cols if t in LATER else c.execute("SELECT sql FROM sqlite_master WHERE name = ?", (t,)).fetchone()[0]
            out[t] = (sql, c.execute('SELECT %s FROM "%s"' % (', '.join('"%s"' % x for x in cols), t)).fetchall())
        return out


before = dump(old)
conn.close()
dbmod.ModelsDatabase(os.path.dirname(old), custom_db_path=old)
with sqlite3.connect(old) as c:
    added = [r[1] for r in c.execute('PRAGMA table_info(generation_input_files)')]
    count = c.execute('SELECT COUNT(*) FROM generation_input_files').fetchone()[0]
check('v44 adds generation_input_files, empty: a generation, an input\'s name, a path',
      (added, count), (['generation_id', 'name', 'path'], 0))
check('and every other table is as it was', dump(old) == before, True)

shutil.rmtree(WORK, ignore_errors=True)
if fails:
    print('\n'.join('FAIL ' + f for f in fails))
    sys.exit(1)
print('generation inputs: all checks passed')
