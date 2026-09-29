"""
Recording the images you generate: model_manager.generations, driven the way
Forge drives it - its hooks in the order Forge calls them, with stand-ins for
Forge's objects - into the fixture library.

What matters most is which saves are recorded. Forge saves a result, and with
it grids, inpaint masks and the "before hires fix" copies, and ControlNet its
maps; only results are recorded, and a result is known by the object every
script's postprocess_image_after_composite is handed, because the image in it
can be replaced after ours sees it - forge-helpers' hires cap does.
"""
import dataclasses
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

opts = webui_stub.install()

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager import generations                    # noqa: E402
from model_manager.nsfw import PG, PROMPT_LEVEL          # noqa: E402

WORK = os.path.join(TESTS, 'work', 'generations')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
check('the schema is at 27, with the three tables',
      (dbmod.SCHEMA_VERSION, sorted(r[0] for r in db._get_connection().execute(
          "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'generation%'"))),
      (27, ['generation_files', 'generation_images', 'generations']))

# ------------------------------------------------------------ Forge, stood in
CHECKPOINT = facts['linked_paths'][0]
LORA_A = facts['linked_paths'][1]
LORA_B = os.path.join(WORK, 'models', 'Lora', 'not_in_library.safetensors')
VAE = os.path.join(WORK, 'models', 'VAE', 'sdxl_vae.safetensors')
OUT = os.path.join(WORK, 'outputs')

shared = sys.modules['modules.shared']
# Forge spells the checkpoint as it likes; Windows does not mind the case.
shared.sd_model = types.SimpleNamespace(sd_checkpoint_info=types.SimpleNamespace(
    filename=CHECKPOINT.upper() if os.name == 'nt' else CHECKPOINT, sha256='abc123'))
opts.forge_additional_modules = [VAE]

networks = types.ModuleType('networks')
sys.modules['networks'] = networks


def lora(name, path, weight):
    return types.SimpleNamespace(name=name, te_multiplier=weight, unet_multiplier=weight,
                                 network_on_disk=types.SimpleNamespace(filename=path))


# Forge's parser is not here; this one reads what the tests write.
def parse(infotext):
    lines = infotext.split('\n')
    parsed = {'Prompt': lines[0]}
    for line in lines[1:]:
        if line.startswith('Negative prompt: '):
            parsed['Negative prompt'] = line[len('Negative prompt: '):]
        else:
            for pair in line.split(', '):
                key, _, value = pair.partition(': ')
                parsed[key] = value
    return parsed


generations._parse_generation_parameters = parse


class Image(object):
    """A PIL image, as far as the hooks look at one."""
    def __init__(self, label, size=(832, 1216)):
        self.label, (self.width, self.height) = label, size

    def getpixel(self, xy):
        return 0


@dataclasses.dataclass
class Processing:
    """StableDiffusionProcessingTxt2Img, as far as the hooks look at one."""
    prompt: str = 'a {fox|cat}'
    negative_prompt: str = 'blurry'
    styles: list = dataclasses.field(default_factory=lambda: ['Cinematic'])
    n_iter: int = 2
    batch_size: int = 2
    width: int = 832
    height: int = 1216
    steps: int = 30
    enable_hr: bool = False
    sd_model: object = None
    extra_generation_params: dict = dataclasses.field(default_factory=dict)
    script_args: list = dataclasses.field(default_factory=list)
    scripts: object = None


class PP(object):
    """PostprocessImageArgs: one object, handed to every script in turn."""
    def __init__(self, image, index):
        self.image, self.index = image, index


class Always(object):
    def __init__(self, title, start, end):
        self._title, self.args_from, self.args_to = title, start, end

    def title(self):
        return self._title


def save(p, image, name):
    """images.save_image: the path on the image, then on_image_saved."""
    image.already_saved_as = os.path.join(OUT, name)
    os.makedirs(OUT, exist_ok=True)
    with open(image.already_saved_as, 'wb') as f:
        f.write(b'an image: ' + name.encode())
    generations.image_saved(types.SimpleNamespace(
        image=image, p=p, filename=image.already_saved_as,
        pnginfo={'parameters': getattr(image, 'infotext', None)}))


counter = [0]


def generate(p, prompts, loras_by_iteration, replace=(), extra_saves=True, video=None,
             names=None):
    """Drive one generation through the hooks, as processing.py does. Its
    files are numbered on from the last, as Forge numbers them, unless names
    says otherwise."""
    generations.before_process(p)
    # Styles are merged, then Dynamic Prompts rewrites the prompts - and p.prompt.
    p.prompt = 'a {fox|cat}, cinematic'
    p.all_prompts = prompts
    p.all_negative_prompts = ['blurry'] * len(prompts)
    p.all_seeds = [1000 + i for i in range(len(prompts))]
    p.all_subseeds = [5000 + i for i in range(len(prompts))]
    generations.process(p)
    for n in range(p.n_iter):
        p.iteration = n
        networks.loaded_networks = loras_by_iteration[n]
        generations.process_batch(p)
        for b in range(p.batch_size):
            index = n * p.batch_size + b
            pp = PP(Image('sampled %d' % index), index)
            generations.result_ready(p, pp)
            if index in replace:                 # a later script's hook
                pp.image = Image('resized %d' % index, (1664, 2432))
            pp.image.infotext = '%s\nNegative prompt: blurry\nSteps: 30, Sampler: Euler, Seed: %d' % (
                prompts[index], 1000 + index)
            if names:
                name = names[index]
            else:
                name = '%05d.png' % counter[0]
                counter[0] += 1
            save(p, pp.image, name)
            if extra_saves:
                mask = Image('mask %d' % index)
                mask.infotext = pp.image.infotext
                save(p, mask, '%05d-mask.png' % index)
    if extra_saves:
        grid = Image('grid')
        grid.infotext = 'grid'
        save(p, grid, 'grid-0001.png')
        # ControlNet saves its maps without p.
        detected = Image('canny')
        detected.already_saved_as = os.path.join(OUT, 'canny.png')
        generations.image_saved(types.SimpleNamespace(image=detected, p=None,
                                                      filename=detected.already_saved_as,
                                                      pnginfo={}))
    return generations.postprocess(p, types.SimpleNamespace(video_path=video))


# ---------------------------------------------------------------- a generation
p = Processing()
p.scripts = types.SimpleNamespace(alwayson_scripts=[Always('ADetailer', 0, 2)])
p.script_args = [True, {'ad_model': 'face_yolov8n.pt', 'image': Image('input')}]
PROMPTS = ['a fox, cinematic <lora:a:0.7>', 'a cat, cinematic <lora:a:0.7>',
           'a fox, cinematic <lora:b:0.5>', 'a cat, cinematic <lora:b:0.5>']
generation_id = generate(p, PROMPTS, [[lora('a', LORA_A, 0.7)], [lora('b', LORA_B, 0.5)]],
                         replace={1})
check('a generation is recorded', isinstance(generation_id, int))
g = db.get_generation(generation_id)

check('with the prompt as typed, not as styles and Dynamic Prompts left it',
      (g['prompt'], g['negative_prompt'], g['styles']), ('a {fox|cat}', 'blurry', ['Cinematic']))
check('its shape', (g['mode'], g['n_iter'], g['batch_size'], g['width'], g['height'],
                    g['image_count']), ('txt2img', 2, 2, 832, 1216, 4))
check('only its results: not the masks, the grid or ControlNet\'s map',
      [os.path.basename(i['path']) for i in g['images']],
      ['00000.png', '00001.png', '00002.png', '00003.png'])
check('a result a later script replaced is still recorded, at its final size',
      (g['images'][1]['width'], g['images'][1]['height']), (1664, 2432))
check('each with its own prompt, seed and place in the batch',
      [(i['prompt'], i['seed'], i['position'], i['iteration']) for i in g['images']],
      [(PROMPTS[0], 1000, 0, 0), (PROMPTS[1], 1001, 1, 0),
       (PROMPTS[2], 1002, 2, 1), (PROMPTS[3], 1003, 3, 1)])
check('and the infotext written into its file, word for word',
      g['images'][2]['infotext'],
      PROMPTS[2] + '\nNegative prompt: blurry\nSteps: 30, Sampler: Euler, Seed: 1002')
check('read into the shape a Civitai image\'s meta has, for the cards',
      {k: g['images'][2]['meta'].get(k) for k in ('prompt', 'negativePrompt', 'steps', 'sampler', 'seed')},
      {'prompt': PROMPTS[2], 'negativePrompt': 'blurry', 'steps': '30', 'sampler': 'Euler',
       'seed': '1002'})
check('the LoRAs of its own iteration',
      [[l['name'] for l in i['loras']] for i in g['images']], [['a'], ['a'], ['b'], ['b']])

in_library = db.get_version(CHECKPOINT)['file_path']
check('each image is filed under every model file it used, in the library\'s spelling',
      [sorted(i['files']) for i in g['images']][0],
      sorted([in_library, db.get_version(LORA_A)['file_path'], os.path.normpath(VAE)]))
check('a file the library does not hold is filed as Forge named it',
      os.path.normpath(LORA_B) in (g['images'][-1]['files'] if g['images'] else []), True)
check('and an iteration\'s LoRA only under its own images',
      [db.get_version(LORA_A)['file_path'] in i['files'] for i in g['images']],
      [True, True, False, False])
check('the checkpoint and modules are kept too', (g['checkpoint_path'], g['modules']),
      (os.path.normpath(os.path.abspath(shared.sd_model.sd_checkpoint_info.filename)),
       [os.path.normpath(VAE)]))
check('every field of p, by Forge\'s names', (g['params']['steps'], g['params']['prompt']),
      (30, 'a {fox|cat}, cinematic'))
check('but not the loaded model', 'sd_model' in g['params'], False)
check('each always-on script\'s arguments, by its title, images left out and said to be',
      g['script_args'], {'ADetailer': [True, {'ad_model': 'face_yolov8n.pt',
                                              'image': {'omitted': 'Image'}}]})
check('the prompts are judged, as nobody rated these images',
      [i['prompt_nsfw_level'] for i in g['images']], [PG] * 4)

# ------------------------------------------------------- what is not recorded
p = Processing(n_iter=1)
before = db._get_connection().execute('SELECT COUNT(*) FROM generations').fetchone()[0]


def counted():
    return db._get_connection().execute('SELECT COUNT(*) FROM generations').fetchone()[0] - before


opts.model_manager_record_generations = False
check('with the setting off, nothing is recorded',
      (generate(p, PROMPTS[:2], [[]]), counted()), (None, 0))
opts.model_manager_record_generations = True


def unsaved(p, prompts, loras):
    """"Always save all generated images" off: nothing is saved."""
    generations.before_process(p)
    p.all_prompts = prompts
    generations.process(p)
    p.iteration = 0
    generations.process_batch(p)
    for index in range(len(prompts)):
        generations.result_ready(p, PP(Image('sampled'), index))
    return generations.postprocess(p, types.SimpleNamespace(video_path=None))


check('with nothing saved to disk, nothing is recorded',
      (unsaved(Processing(n_iter=1), PROMPTS[:2], [[]]), counted()), (None, 0))
check('nor a video', (generate(Processing(n_iter=1), PROMPTS[:2], [[]], video='out.mp4'),
                      counted()), (None, 0))
check('and nothing is left on p afterwards', hasattr(p, generations._ATTR), False)

# ------------------------------------------------------------- the prompt words
changed, total = db.restamp_generation_levels(lambda meta: PROMPT_LEVEL
                                              if 'cat' in (meta or {}).get('prompt', '') else PG)
check('when the prompt words change the images are judged again', (changed, total), (2, 4))
g = db.get_generation(generation_id)
check('each by its own prompt', [i['prompt_nsfw_level'] for i in g['images']],
      [PG, PROMPT_LEVEL, PG, PROMPT_LEVEL])
check('and the generation by its most explicit', g['prompt_nsfw_level'], PROMPT_LEVEL)

# ---------------------------------------------------------------- the gallery
# The tab beside a model's Civitai images: a page of generation cards, through
# the same two switches, and an image served only by its record.
try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    has_fastapi = True
except ImportError:
    has_fastapi = False

if has_fastapi:
    from model_manager.api import setup_api                       # noqa: E402
    app = FastAPI()
    setup_api(app)
    client = TestClient(app)

    def page(path, **params):
        return client.get('/model-manager/generations/page', params={'path': path, **params}).json()

    # A page is a slice of the gallery's generations, newest first - its size
    # the images-per-page setting - before the switches.
    newer = generate(Processing(n_iter=1), PROMPTS[:2], [[]], extra_saves=False)
    opts.model_manager_gallery_page_size = 1
    first = page(CHECKPOINT, hide_nsfw_images='false', hide_promptless_images='false')
    second = page(CHECKPOINT, page=2, hide_nsfw_images='true', hide_promptless_images='false')
    opts.model_manager_gallery_page_size = 100
    check('at one generation a page, page 1 is the newest, and more come after it',
          ([c['id'] for c in first['generations']], first['page']['more']), ([newer], True))
    check('page 2 the one before it, the last',
          ([c['id'] for c in second['generations']], second['page']['more']), ([generation_id], False))
    check('each page\'s note counts its own images',
          {k: second['page'][k] for k in ('number', 'generations', 'count', 'shown', 'hidden_nsfw')},
          {'number': 2, 'generations': 1, 'count': 4, 'shown': 2, 'hidden_nsfw': 2})
    db.delete_generation(newer)

    # The prompt words above made images 1 and 3 explicit.
    body = page(CHECKPOINT, hide_nsfw_images='false', hide_promptless_images='false')
    card = body['generations'][0]
    check('the checkpoint\'s gallery holds the generation, as one card',
          (len(body['generations']), card['id'], card['matching_count']), (1, generation_id, 4))
    check('whose preview is its first four images, in order',
          [i['position'] for i in card['images']], [0, 1, 2, 3])
    check('each with what a card draws', sorted(card['images'][0]) == sorted(
        ['id', 'generation_id', 'position', 'iteration', 'seed', 'width', 'height', 'meta',
         'infotext', 'url', 'exists', 'mm_level', 'mm_level_from_prompt']), True)
    check('and the file is there', card['images'][0]['exists'], True)

    body = page(CHECKPOINT, hide_nsfw_images='true', hide_promptless_images='true')
    check('the NSFW switch hides the explicit ones, as in the Civitai gallery',
          [i['position'] for i in body['generations'][0]['images']], [0, 2])
    check('and how many generations are filed here, filtered or not, for the tab\'s label',
          body['state']['stored_generations'], 1)
    check('and the banner is told what it hid',
          {k: body['state'][k] for k in ('total', 'filtered', 'hidden_nsfw', 'nsfw_count')},
          {'total': 4, 'filtered': 2, 'hidden_nsfw': 2, 'nsfw_count': 2})
    check('an image made with a LoRA is in the LoRA\'s gallery too, and only those that used it',
          [i['position'] for i in page(LORA_A, hide_nsfw_images='false')['generations'][0]['images']],
          [0, 1])
    check('a model nobody generated with has an empty gallery',
          page(facts['linked_paths'][2])['generations'], [])

    body = client.get('/model-manager/generations/%d/images' % generation_id,
                      params={'path': CHECKPOINT, 'hide_nsfw_images': 'false'}).json()
    check('"Show all" brings every image of the generation the gallery shows',
          [i['position'] for i in body['images']], [0, 1, 2, 3])

    first = card['images'][0]
    served = client.get(first['url'])
    check('an image is served by its record', (served.status_code, served.content),
          (200, b'an image: 00000.png'))
    check('an id nobody recorded is not found',
          client.get('/model-manager/generations/images/999999/file').status_code, 404)

    details = client.get('/model-manager/models/details', params={'path': CHECKPOINT}).json()
    check('the details say how many generations the model has, for the tab\'s label',
          details['model']['generations_count'], 1)

    # Deleting: the records always, the files only when asked.
    kept = generate(Processing(n_iter=1), PROMPTS[:2], [[]], extra_saves=False)
    kept_paths = [i['path'] for i in db.get_generation(kept)['images']]
    body = client.post('/model-manager/generations/%d/delete' % kept).json()
    check('delete removes the records', (body['success'], db.get_generation(kept)), (True, None))
    check('from the index too', db.count_generations([in_library]), 1)
    check('and leaves the files, unless asked', all(os.path.isfile(p) for p in kept_paths), True)
    gone = generate(Processing(n_iter=1), PROMPTS[:2], [[]], extra_saves=False)
    gone_paths = [i['path'] for i in db.get_generation(gone)['images']]
    body = client.post('/model-manager/generations/%d/delete' % gone, data={'delete_files': 'true'}).json()
    check('asked, it deletes its image files as well',
          (body['deleted_files'], any(os.path.isfile(p) for p in gone_paths)), (2, False))
    check('and only those: the other generation\'s are still there',
          all(os.path.isfile(i['path']) for i in db.get_generation(generation_id)['images']), True)

    # Forge saved over an earlier image's file (replace action Override):
    # deleting the later generation must not take the earlier one's image.
    first_path = db.get_generation(generation_id)['images'][0]['path']
    over = generate(Processing(n_iter=1, batch_size=1), PROMPTS[:1], [[]], extra_saves=False,
                    names=[os.path.basename(first_path)])
    body = client.post('/model-manager/generations/%d/delete' % over, data={'delete_files': 'true'}).json()
    check('a file another record still names is not deleted with it',
          (body['deleted_files'], os.path.isfile(first_path)), (0, True))

    # A file gone from disk leaves its record, which can still be sent.
    os.remove(db.get_generation(generation_id)['images'][3]['path'])
    body = page(CHECKPOINT, hide_nsfw_images='false')
    check('an image whose file is gone keeps its record, marked missing',
          [i['exists'] for i in body['generations'][0]['images']], [True, True, True, False])
    check('and its file is not found', client.get(body['generations'][0]['images'][3]['url']).status_code,
          404)

# ------------------------------------------------------ a failure costs nothing
p = Processing(n_iter=1)
real = db.record_generation
db.record_generation = lambda *a: (_ for _ in ()).throw(RuntimeError('disk full'))
try:
    check('a failure while recording is not the generation\'s: it is printed, not raised',
          generate(p, PROMPTS[:2], [[]]), None)
finally:
    db.record_generation = real

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
