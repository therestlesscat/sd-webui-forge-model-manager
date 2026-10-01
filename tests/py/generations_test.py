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
check('the database has the three tables',
      sorted(r[0] for r in db._get_connection().execute(
          "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'generation%'")),
      ['generation_files', 'generation_images', 'generations'])

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
         'infotext', 'url', 'exists', 'mm_level', 'mm_level_from_prompt', 'user_level']), True)
    check('and the file is there', card['images'][0]['exists'], True)
    # Its LoRAs and embeddings as a Civitai image lists them, for Send's chips:
    # the LoRAs Forge loaded for its own iteration, at their weight.
    check('each image lists the LoRAs of its own iteration, as a Civitai image lists its resources',
          [i['meta']['resources'] for i in card['images'][1:3]],
          [[{'type': 'lora', 'name': 'a', 'weight': 0.7, 'hash': ''}],
           [{'type': 'lora', 'name': 'b', 'weight': 0.5, 'hash': ''}]])
    from model_manager.api.generations import image_resources          # noqa: E402
    check('with each LoRA\'s hash from the infotext, and its embeddings from "TI hashes"',
          image_resources({'loras': [{'name': 'add_detail', 'te_multiplier': 0.6}],
                           'meta': {'Lora hashes': 'add_detail: 47aaaf0d2945, other: 1234abcd',
                                    'TI hashes': '"easynegative: c74b4e810b"'}}),
          [{'type': 'lora', 'name': 'add_detail', 'weight': 0.6, 'hash': '47aaaf0d2945'},
           {'type': 'lora', 'name': 'other', 'weight': None, 'hash': '1234abcd'},
           {'type': 'embedding', 'name': 'easynegative', 'weight': None, 'hash': 'c74b4e810b'}])

    body = page(CHECKPOINT, hide_nsfw_images='true', hide_promptless_images='true')
    check('the NSFW switch hides the explicit ones, as in the Civitai gallery',
          [i['position'] for i in body['generations'][0]['images']], [0, 2])
    check('and how many generations are filed here, filtered or not, for the tab\'s label',
          body['state']['stored_generations'], 1)
    check('and the banner is told what it hid',
          {k: body['state'][k] for k in ('total', 'filtered', 'hidden_nsfw', 'nsfw_count')},
          {'total': 4, 'filtered': 2, 'hidden_nsfw': 2, 'nsfw_count': 2})
    # An image both switches hide is counted apart, as in the Civitai gallery
    # (api_test.py): each switch's number is what it alone hides.
    from model_manager.api.generations import _filtered                 # noqa: E402
    rows = [{'level': 1, 'prompt_length': 40}, {'level': 8, 'prompt_length': 40},
            {'level': 1, 'prompt_length': 0}, {'level': 8, 'prompt_length': 0}]
    _, both_hiding = _filtered(rows, True, True)
    _, nsfw_shown = _filtered(rows, False, True)
    check('your generations: what each switch alone hides, and what both do',
          [both_hiding[k] for k in ('hidden_nsfw', 'hidden_promptless', 'hidden_both', 'hidden')], [1, 1, 1, 3])
    check('the NSFW switch\'s number, hiding, is what it shows once ticked',
          both_hiding['hidden_nsfw'], nsfw_shown['nsfw_count'])
    check('and the prompt switch\'s every image with an unusable prompt, either way',
          [both_hiding['promptless_total'], nsfw_shown['promptless_total']], [2, 2])
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

    # -------------------------------------------------- the Generations tab
    # Every generation, whatever model made it: a tile each - its first four
    # images, and how many it has. The tab scrolls and has no page notes, so
    # images are filtered first and the parts cut from what is left.
    def browse(**params):
        return client.get('/model-manager/generations/browse', params=params).json()

    single = generate(Processing(n_iter=1, batch_size=1), PROMPTS[:1], [[]], extra_saves=False)
    body = browse(hide_nsfw_images='false')
    tiles = {t['generation']['id']: t for t in body['tiles']}
    check('every generation is a tile, the newest first, whatever model made it',
          (body['tiles'][0]['generation']['id'], single in tiles, generation_id in tiles), (single, True, True))
    check('a generation of four: its four images, and how many it has',
          ([i['position'] for i in tiles[generation_id]['images']], tiles[generation_id]['matching_count']),
          ([0, 1, 2, 3], 4))
    check('with what a tile says of its generation',
          (tiles[generation_id]['generation']['mode'], tiles[generation_id]['generation']['image_count']),
          ('txt2img', 4))
    check('and every generation recorded is counted', body['state']['stored_generations'],
          db.count_generations(None))

    body = browse(hide_nsfw_images='true')
    tile = next(t for t in body['tiles'] if t['generation']['id'] == generation_id)
    check('the NSFW switch leaves a generation what it does not hide',
          ([i['position'] for i in tile['images']], tile['matching_count']), ([0, 2], 2))

    # Grouped: a tile per group of images, whatever generation each is of -
    # a group opens onto its generations, a generation onto its images.
    def groups(by):
        return {t['group']['value']: t for t in browse(group=by, hide_nsfw_images='false')['tiles']}

    body = browse(group='prompt', hide_nsfw_images='false')
    check('grouped, every tile is a group', {t['kind'] for t in body['tiles']}, {'group'})
    fox = groups('prompt')[PROMPTS[0]]
    check('by the prompt each image was made with: two generations\' images in one group',
          (fox['matching_count'], fox['group']['generations']), (2, 2))
    check('its other prompts a group each', all(groups('prompt')[p]['matching_count'] == 1 for p in PROMPTS[1:]),
          True)
    written = groups('prompt_written')['a {fox|cat}']
    check('by the prompt as written, a wildcard batch stays together', written['matching_count'] >= 4, True)
    check('by the LoRAs each image used, the same set a group whatever the weight, none a group too',
          {k: v['matching_count'] for k, v in groups('loras').items() if k in ('a', 'b', '')},
          {'a': 2, 'b': 2, '': 1})
    check('by size, an image a later script enlarged in a group of its own',
          groups('size')['1664×2432']['matching_count'], 1)
    check('by model, the checkpoint by its name',
          os.path.splitext(os.path.basename(CHECKPOINT))[0].lower() in {k.lower() for k in groups('model')}, True)
    check('by day, the day each was made', all(len(k) == 10 for k in groups('day')), True)
    # By base model: the checkpoint's, as the library holds it - what the
    # Model Manager's Base Model filter reads (#35).
    library_base = db._get_connection().execute(
        'SELECT base_model FROM model_versions WHERE file_path = ? COLLATE NOCASE',
        (db.get_generation(generation_id)['checkpoint_path'],)
    ).fetchone()
    check('by base model, the checkpoint\'s in the library',
          [library_base and library_base[0], sum(t['matching_count'] for k, t in groups('base_model').items()
                                                 if library_base and k == library_base[0]) > 0],
          ['SDXL 1.0', True])

    inside = browse(group='prompt', in_group=fox['group']['id'], hide_nsfw_images='false')
    check('a group opens onto its generations, each a tile of the images it has there',
          (sorted(t['generation']['id'] for t in inside['tiles']), {t['kind'] for t in inside['tiles']},
           [t['matching_count'] for t in inside['tiles']]),
          (sorted([generation_id, single]), {'generation'}, [1, 1]))
    check('saying what the group is, for its header', (inside['scope']['value'], inside['scope']['count'],
                                                      inside['scope']['grouping']),
          (PROMPTS[0], 2, 'Prompt, as generated'))
    batch = browse(generation=generation_id, hide_nsfw_images='false')
    check('a generation opens onto its images, a tile each',
          ([t['kind'] for t in batch['tiles']], [t['images'][0]['position'] for t in batch['tiles']],
           batch['scope']['generation']['id']), (['image'] * 4, [0, 1, 2, 3], generation_id))
    deeper = browse(group='prompt', in_group=fox['group']['id'], generation=generation_id,
                    hide_nsfw_images='false')
    check('and a generation opened inside a group shows only its images in that group',
          [t['images'][0]['position'] for t in deeper['tiles']], [0])
    check('an unknown grouping groups nothing', {t['kind'] for t in browse(group='nonsense')['tiles']},
          {'generation'})

    # Grouped twice, "LoRA combination, then Prompt": the top level is the
    # prompts' groups, in sections by LoRA set - each tile says its section -
    # and a prompt's group opens straight onto its batches.
    top = browse(group='loras>prompt', hide_nsfw_images='false')['tiles']
    by_section = {}
    for t in top:
        by_section.setdefault(t['section']['value'], []).append(t)
    check('grouped twice, the top level is the second grouping\'s groups, each in a section of the first',
          [{t['kind'] for t in top}, {t['group']['by'] for t in top}, {t['section']['by'] for t in top},
           set(by_section) >= {'a', 'b'}],
          [{'group'}, {'prompt'}, {'loras'}, True])
    check('a section\'s groups are one run of tiles, not scattered',
          [t['section']['value'] for t in top],
          [v for v in dict.fromkeys(t['section']['value'] for t in top) for _ in by_section[v]])
    with_a = by_section['a']
    check('a section counts its images and groups, and its groups add up to the LoRA set\'s',
          [with_a[0]['section']['count'], with_a[0]['section']['groups'], sum(t['matching_count'] for t in with_a),
           {t['group']['value'] for t in with_a} <= set(PROMPTS)],
          [groups('loras')['a']['matching_count'], len(with_a), groups('loras')['a']['matching_count'], True])
    fox_with_a = next(t for t in with_a if t['group']['value'] == PROMPTS[0])
    batches = browse(group='loras>prompt', in_group=fox_with_a['section']['id'],
                     in_subgroup=fox_with_a['group']['id'], hide_nsfw_images='false')
    check('a group opens onto its batches, of the images in it and its section',
          [{t['kind'] for t in batches['tiles']}, sum(t['matching_count'] for t in batches['tiles']),
           batches['scope']['grouping'], [v['value'] for v in batches['scope']['values']]],
          [{'generation'}, fox_with_a['matching_count'], 'LoRA combination › Prompt, as generated', ['a', PROMPTS[0]]])
    one_batch = batches['tiles'][0]['generation']['id']
    inner = browse(group='loras>prompt', in_group=fox_with_a['section']['id'], in_subgroup=fox_with_a['group']['id'],
                   generation=one_batch, hide_nsfw_images='false')
    check('a batch opened there shows its images in both groups',
          [{t['kind'] for t in inner['tiles']}, len(inner['tiles'])],
          [{'image'}, batches['tiles'][0]['matching_count']])
    check('three groupings, or one unknown in a pair, group nothing',
          [{t['kind'] for t in browse(group='loras>prompt>day')['tiles']},
           {t['kind'] for t in browse(group='loras>nonsense')['tiles']}], [{'generation'}, {'generation'}])

    # Each tile says its checkpoint, for "Show model in Model Manager" - a
    # group only if every image of it had the same one - and each image its own.
    recorded = db.get_generation(generation_id)['checkpoint_path']
    tile = next(t for t in browse(hide_nsfw_images='false')['tiles'] if t['generation']['id'] == generation_id)
    check('a generation\'s tile names its checkpoint, and so does each image',
          (tile['checkpoint_path'], {i['checkpoint_path'] for i in tile['images']}), (recorded, {recorded}))
    # For the menus, by version and model (#42): another tab is asked for
    # those, not for a path. A LoRA the library does not hold says so.
    library = db.get_version(CHECKPOINT)
    check('its checkpoint by version and model, as the library knows it',
          {k: tile['checkpoint'][k] for k in ('version_id', 'model_id', 'in_library')},
          {'version_id': library['id'], 'model_id': library['model_id'], 'in_library': True})
    loras = {l['name']: l for l in tile['loras']}
    lora_a = db.get_version(LORA_A)
    check('and each LoRA its images used: one the library has by version, one it has not, not in the library',
          [(loras[os.path.splitext(os.path.basename(LORA_A))[0]]['version_id'],
            loras[os.path.splitext(os.path.basename(LORA_A))[0]]['in_library']),
           (loras['not_in_library']['version_id'], loras['not_in_library']['in_library'])],
          [(lora_a['id'], True), (None, False)])
    check('each image too, with its own LoRAs only',
          [len(i['loras']) for i in tile['images']], [len(i['meta']['resources']) for i in tile['images']])
    real_info = shared.sd_model.sd_checkpoint_info
    shared.sd_model = types.SimpleNamespace(sd_checkpoint_info=types.SimpleNamespace(
        filename=facts['linked_paths'][2], sha256='def456'))
    other = generate(Processing(n_iter=1, batch_size=1), PROMPTS[:1], [[]], extra_saves=False)
    shared.sd_model = types.SimpleNamespace(sd_checkpoint_info=real_info)
    today = next(iter(groups('day').values()))
    check('a group of images made with two checkpoints names none', today['checkpoint_path'], None)
    check('while its images keep their own', len({i['checkpoint_path'] for i in
          browse(generation=other, hide_nsfw_images='false')['tiles'][0]['images']}), 1)
    db.delete_generation(other)

    # Rating: a person's own NSFW level for an image, over its prompt's - one
    # image, or what a batch or group shows, and never what a switch hid.
    def rate(**data):
        return client.post('/model-manager/generations/rate', data=data)

    def user_levels():
        return [i['user_nsfw_level'] for i in db.get_generation(generation_id)['images']]

    images = db.get_generation(generation_id)['images']
    first_id = images[0]['id']
    body = rate(image_id=first_id, level=8, hide_nsfw_images='true').json()
    check('one image rated X is X, as rated, not as its prompt says',
          (body['rated'], body['image']['mm_level'], body['image']['user_level'],
           body['image']['mm_level_from_prompt']), (1, 8, 8, False))
    check('and with the NSFW switch on, is said to be hidden now', body['visible'], False)
    body = rate(image_id=first_id, level='', hide_nsfw_images='true').json()
    check('a rating cleared, it goes back to its prompt\'s level, and shows again',
          (body['image']['user_level'], body['image']['mm_level'], body['visible']), (None, PG, True))
    check('a level nobody can choose is refused', rate(image_id=first_id, level=5).status_code, 400)
    check('and so is a rating of nothing in particular', rate(level=8).status_code, 400)

    body = rate(generation=generation_id, level=4, hide_nsfw_images='true').json()
    check('a batch rated: the images of it the tab shows, and not those the switch hid',
          (body['rated'], user_levels()), (2, [4, None, 4, None]))
    tile = next(t for t in browse(hide_nsfw_images='false')['tiles'] if t['generation']['id'] == generation_id)
    check('a tile of mixed levels shows none as the one they share', (tile['level'], tile['user_level']), (None, None))
    rate(generation=generation_id, level=1, hide_nsfw_images='false')
    tile = next(t for t in browse(hide_nsfw_images='false')['tiles'] if t['generation']['id'] == generation_id)
    check('one they all share, it does', (tile['level'], tile['user_level'], user_levels()), (PG, PG, [PG] * 4))
    refused = rate(group='prompt', in_group=groups('prompt')[PROMPTS[1]]['group']['id'], level=16,
                   hide_nsfw_images='false')
    check('a group is not rated whole: its images are of any prompt, and easily misrated',
          (refused.status_code, user_levels()), (400, [PG] * 4))
    body = rate(group='prompt', in_group=groups('prompt')[PROMPTS[1]]['group']['id'], generation=generation_id,
                level=16, hide_nsfw_images='false').json()
    check('a batch opened from a group is: its images in that group', (body['rated'], user_levels()),
          (1, [PG, 16, PG, PG]))
    rate(path=CHECKPOINT, generation=generation_id, level=2, hide_nsfw_images='false',
         hide_promptless_images='false')
    check('a card of a model\'s "Your generations": its images that gallery shows', user_levels(), [2] * 4)
    db.restamp_generation_levels(lambda meta: PG)
    check('the prompt words changing leaves a rating as it was', user_levels(), [2] * 4)
    rate(generation=generation_id, level='', hide_nsfw_images='false')
    check('and a batch\'s ratings clear together', user_levels(), [None] * 4)

    # A group is not deleted whole: its images are of any number of generations.
    before_group = groups('loras')['']['matching_count']
    refused = client.post('/model-manager/generations/group/delete', data={
        'group': 'loras', 'in_group': groups('loras')['']['group']['id']})
    check('there is no deleting a group: it is refused, and nothing goes',
          (refused.status_code != 200, groups('loras')['']['matching_count']), (True, before_group))

    opts.model_manager_gallery_page_size = 1
    parts = [browse(page=n, hide_nsfw_images='false') for n in (1, 2)]
    last = browse(page=db.count_generations(None), hide_nsfw_images='false')
    opts.model_manager_gallery_page_size = 100
    check('parts of the images-per-page setting, one after another, until there are no more',
          ([len(p['tiles']) for p in parts], parts[0]['more'], last['more'],
           parts[1]['tiles'][0]['generation']['id'] != parts[0]['tiles'][0]['generation']['id']),
          ([1, 1], True, False, True))

    body = client.get('/model-manager/generations/%d/images' % generation_id,
                      params={'hide_nsfw_images': 'false'}).json()
    check('a tile opens out into every image of its generation, with no model to go by',
          [i['position'] for i in body['images']], [0, 1, 2, 3])

    # Deleting one image: its record, the generation's with its last, and its
    # file only when asked.
    pair = generate(Processing(n_iter=1), PROMPTS[:2], [[]], extra_saves=False)
    first_image, second_image = db.get_generation(pair)['images']
    body = client.post('/model-manager/generations/images/%d/delete' % first_image['id']).json()
    after = db.get_generation(pair)
    check('one image of a generation is deleted alone, and its generation stays',
          (body['success'], body['generation_deleted'], [i['id'] for i in after['images']],
           after['image_count']), (True, None, [second_image['id']], 1))
    check('with its file, unless asked', os.path.isfile(first_image['path']), True)
    body = client.post('/model-manager/generations/images/%d/delete' % second_image['id'],
                       data={'delete_files': 'true'}).json()
    check('the last image takes its generation with it, and its file when asked',
          (body['generation_deleted'], db.get_generation(pair), body['deleted_files'],
           os.path.isfile(second_image['path'])), (pair, None, 1, False))
    check('an image nobody recorded is nothing to delete',
          client.post('/model-manager/generations/images/999999/delete').json()['generation_deleted'],
          None)
    db.delete_generation(single)

    # Select's one Delete: generations whole and single images, in one
    # request, by the single deletes' rules - records always, files only when
    # asked, and only files no other record names.
    three = generate(Processing(n_iter=1, batch_size=3), PROMPTS[:3], [[]], extra_saves=False)
    two = generate(Processing(n_iter=1), PROMPTS[:2], [[]], extra_saves=False)
    other = generate(Processing(n_iter=1), PROMPTS[:2], [[]], extra_saves=False)
    three_paths = [i['path'] for i in db.get_generation(three)['images']]
    two_first, two_second = db.get_generation(two)['images']
    body = client.post('/model-manager/generations/delete-many', data={
        'generation_ids': str(three), 'image_ids': str(two_first['id'])}).json()
    check('a generation whole and an image alone, in one request: every record named, the rest kept',
          (body['success'], body['images'], db.get_generation(three),
           [i['id'] for i in db.get_generation(two)['images']], len(db.get_generation(other)['images'])),
          (True, 4, None, [two_second['id']], 2))
    check('and the files kept, unless asked', all(os.path.isfile(p) for p in three_paths + [two_first['path']]),
          True)
    other_first = db.get_generation(other)['images'][0]
    body = client.post('/model-manager/generations/delete-many', data={
        'generation_ids': f'{other},{two}', 'image_ids': str(other_first['id']),
        'delete_files': 'true'}).json()
    check('an image of a generation also named is counted once, and the files go when asked',
          (body['images'], body['deleted_files'], db.get_generation(other), db.get_generation(two),
           os.path.isfile(other_first['path']), os.path.isfile(two_second['path'])),
          (3, 3, None, None, False, False))
    body = client.post('/model-manager/generations/delete-many', data={'generation_ids': '999999'}).json()
    check('ids nobody recorded delete nothing, and fail nothing', (body['success'], body['images']), (True, 0))

    # Sending one back: Forge set up as it was made with, from its record -
    # the checkpoint's preset, the name Forge lists it under, exactly the
    # modules it loaded. Neo ignores an infotext's checkpoint and modules by
    # default, so the paste alone set up none of it.
    import model_manager.architecture as arch                  # noqa: E402
    import model_manager.forge_modules as fm                   # noqa: E402
    sd_models = types.ModuleType('modules.sd_models')
    sd_models.checkpoints_list = {'m': types.SimpleNamespace(filename=CHECKPOINT, title='linked/m.safetensors [abc]')}
    sys.modules['modules.sd_models'] = sd_models
    sys.modules['modules'].sd_models = sd_models
    db.set_architecture(CHECKPOINT, 'sd', 'SD15', True, True, '1', file_type='Checkpoint')
    real_check, real_installed = arch.needs_check, fm.installed_modules
    arch.needs_check = lambda db_, p: None                     # read already, as stored
    fm.installed_modules = lambda: {'sdxl_vae.safetensors': VAE}
    try:
        plan = client.get('/model-manager/generations/%d/send-plan' % generation_id).json()
        check('a generation is sent back set up as it was made: preset, checkpoint as Forge lists it, '
              'exactly its modules',
              {k: plan[k] for k in ('preset', 'checkpoint', 'checkpoint_missing', 'target', 'modules_missing')},
              {'preset': 'sd', 'checkpoint': 'linked/m.safetensors [abc]', 'checkpoint_missing': None,
               'target': ['sdxl_vae.safetensors'], 'modules_missing': []})
        sd_models.checkpoints_list = {}
        fm.installed_modules = lambda: {}
        plan = client.get('/model-manager/generations/%d/send-plan' % generation_id).json()
        check('what Forge no longer lists is named, and not asked for',
              (plan['checkpoint'], plan['checkpoint_missing'].lower(), plan['target'], plan['modules_missing']),
              (None, os.path.basename(CHECKPOINT).lower(), [], ['sdxl_vae.safetensors']))
        check('a generation nobody recorded has no plan',
              client.get('/model-manager/generations/999999/send-plan').status_code, 404)
    finally:
        arch.needs_check, fm.installed_modules = real_check, real_installed

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
