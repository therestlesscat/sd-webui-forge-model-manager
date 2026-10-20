"""
A picture sent into one of img2img's modes (#299), and img2img's canvases set
apart: the settings button (scheduler/load.py `_loader`) never has a canvas
among its outputs, and each mode's canvas button sets that mode's canvases
alone, always with a value - never "leave as is", which made Gradio put a
copy of the canvas into the page's session that failed on the next picture
(seen on a test install: Forge's own Send to img2img failed after one of
ours). With Forge's paste, the press replay and the database stood in.

The settings button sets `mode`, and width and height from the settings - the
picture's, as the page gives them, only when they give none. An image with no
infotext is pasted nothing: Forge's paste of an empty text pastes the last
run's settings. A canvas button puts in one of your generations' files or a
Civitai original - from Civitai's image server alone, over https, within the
time and the size allowed - its layer emptied; or a press's or a task's kept
canvases (#34).

Each check runs on its own: on code without these, it fails by name.
"""
import io
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
opts = webui_stub.install()

try:
    import gradio as gr
    from PIL import Image
except ImportError:
    print('gradio or PIL is not installed; run this with the WebUI\'s python')
    sys.exit(0)

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


# ------------------------------------------------------- Forge, stood in
CANVASES = ['init_img', 'sketch', 'sketch_fg', 'init_img_with_mask', 'init_img_with_mask_fg',
            'inpaint_color_sketch', 'inpaint_color_sketch_fg', 'init_img_inpaint', 'init_mask_inpaint']


def img2img_function(id_task, request, mode, prompt, negative_prompt, init_img, sketch, sketch_fg,
                     init_img_with_mask, init_img_with_mask_fg, inpaint_color_sketch, inpaint_color_sketch_fg,
                     init_img_inpaint, init_mask_inpaint, height, width, *args):
    pass


NAMES = ['id_task', 'mode', 'prompt', 'negative_prompt'] + CANVASES + ['height', 'width']
modules = sys.modules['modules']
img2img_module = types.ModuleType('modules.img2img')
img2img_module.img2img_function = img2img_function
modules.img2img = img2img_module
sys.modules['modules.img2img'] = img2img_module

from model_manager.scheduler import capture, load      # noqa: E402

SKIP = gr.update()
COUNT = len(NAMES) - 1
EXTRAS = ['an extra the paste sets']
OWN = types.SimpleNamespace(inputs=[types.SimpleNamespace(name=n) for n in NAMES])
capture.generate_click = lambda tab: OWN
at = {name: n - 1 for n, name in enumerate(NAMES) if n}

pasted = []
pasted_for = []                       # the generation each paste was corrected from


def paste_values(tab, infotext, generation_id, outputs, skip=None):
    """Forge's paste: the prompt from the text, everything else as on screen."""
    pasted.append(infotext)
    pasted_for.append(generation_id)
    values = [skip] * len(outputs)
    values[at['prompt']] = (infotext or '').split('\n')[0]
    return values, []


def generation_values(tab, generation_id, image_id, skip=None):
    """A kept press, replayed: its prompt, its size, its own Inpaint canvases.
    Generation 14's cannot be: a script it kept is gone."""
    if generation_id == 14:
        raise RuntimeError('Script "X" is gone')
    values = [skip] * COUNT
    values[at['mode']] = 2
    values[at['prompt']] = 'a pressed <lora:alias_y:1> prompt' if generation_id == 15 else 'a pressed prompt'
    values[at['init_img_with_mask']] = 'the press\'s picture'
    values[at['init_img_with_mask_fg']] = 'the press\'s mask'
    values[at['width']], values[at['height']] = 512, 768
    return values, [], []


load.paste_values = paste_values
load.generation_values = generation_values
load.parse_generation_parameters = lambda text: (
    {'Size-1': 832, 'Size-2': 1216} if 'Size:' in (text or '') else {})

WORK = os.path.join(TESTS, 'work', 'img2img_send')
os.makedirs(WORK, exist_ok=True)
FILE = os.path.join(WORK, 'generated.png')
Image.new('RGBA', (96, 64), (200, 30, 30, 255)).save(FILE)
paths = {7: FILE, 8: os.path.join(WORK, 'gone.png')}
load.get_models_db = lambda: types.SimpleNamespace(get_generation_image_path=lambda image_id: paths.get(image_id))

asked_urls = []


class Reply(object):
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError('%d Not Found' % self.status)

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]


def png(size):
    out = io.BytesIO()
    Image.new('RGB', size, (10, 120, 200)).save(out, format='PNG')
    return out.getvalue()


answers = {'https://image.civitai.com/x/original=true/1.jpeg': Reply(png((120, 80))),
           'https://image.civitai.com/x/original=true/404.jpeg': Reply(b'', 404),
           'https://image.civitai.com/x/original=true/text.jpeg': Reply(b'<html>not an image</html>'),
           'https://image.civitai.com/x/original=true/big.jpeg': Reply(b'x' * 300)}


def get(url, **kwargs):
    asked_urls.append(url)
    return answers[url]


real_picture = getattr(load, '_picture', None)
if real_picture:
    load._picture = lambda asked, get_=None: real_picture(asked, get=get)


from model_manager.install import INSTALL_KEY      # noqa: E402

KEPT = [n for n, name in enumerate(NAMES[1:]) if name not in CANVASES]
KEPT_NAMES = [NAMES[1:][n] for n in KEPT]
kat = {name: n for n, name in enumerate(KEPT_NAMES)}
MASK = os.path.join(WORK, 'mask.png')
Image.new('RGBA', (96, 64), (255, 255, 255, 255)).save(MASK)
kept_press = {'fixed': {'mode': 2, 'init_img_with_mask': {'__image__': FILE},
                        'init_img_with_mask_fg': {'__image__': MASK}}}
load.get_models_db = lambda: types.SimpleNamespace(
    get_generation_image_path=lambda image_id: paths.get(image_id),
    get_generation=lambda gid: {'inputs': kept_press} if gid == 12 else None,
    get_task=lambda tid: {'install': INSTALL_KEY if tid == 5 else 'another', 'inputs': kept_press})


def ask(**request):
    """img2img's settings button, asked as the page asks: its values and its answer."""
    out = load._loader('img2img', KEPT, EXTRAS, KEPT_NAMES)(json.dumps({'nonce': 'n', **request}))
    return out[:-1], json.loads(out[-1])


def asked(**request):
    """ask(), or - on code that cannot - no values and its error."""
    out = attempt(lambda: ask(**request))
    return out if isinstance(out, tuple) else ([], {'error': out})


def value(values, name):
    return values[kat[name]] if len(values) > kat[name] else 'unset'


def canvas(mode, **request):
    """img2img's canvas button of `mode`: its canvases' values and its answer, or the error raised."""
    try:
        out = load._canvas_loader(mode)(json.dumps({'nonce': 'c', **request}))
    except Exception as e:                               # noqa: BLE001
        return [], {'error': 'raised %s: %s' % (type(e).__name__, e)}
    return out[:-1], json.loads(out[-1])


def size_of(picture):
    return getattr(picture, 'size', picture)


INTO = {'mode': 2, 'width': 96, 'height': 64}

# ----------------------------------------------- a Civitai image's source (#302)
# The page hands the loader the image's source, not a text: the loader builds
# the text from the image's stored record (send.civitai_settings), pastes it,
# and sets the scheduler and Hires fix in the same event (load.after_paste).
records = {41: {'id': 41, 'width': 96, 'height': 64, 'meta': {'prompt': 'a stored castle', 'steps': 20, 'Size': '96x64'}}}
db_before = load.get_models_db
load.get_models_db = lambda: types.SimpleNamespace(
    **vars(db_before()), stored_records=lambda ids: [records[i] for i in ids if i in records])
after = []
real_after = getattr(load, 'after_paste', None)
if real_after:
    load.after_paste = lambda *args: (after.append(args[4:]), real_after(*args))[1]
pasted.clear()
values, answer = asked(source={'kind': 'civitai', 'image': 41})
check('a source\'s text built from the image\'s stored record, pasted, and handed back for Forge\'s paste button',
      [(pasted or [''])[-1].split('\n')[0], value(values, 'prompt'), answer.get('pasted'),
       (answer.get('text') or '').split('\n')[0]], ['a stored castle', 'a stored castle', True, 'a stored castle'])
check('and its scheduler and Hires fix set in the same event: none named, Automatic; none had, off',
      [after, answer.get('scheduler'), answer.get('hires')], [[('Automatic', False)], 'Automatic', False])
values, answer = asked(source={'kind': 'civitai', 'image': 41}, into={**INTO, 'picture': {'url': 'x'}})
check('into a mode: the mode set, the size the text\'s', [value(values, 'mode'), value(values, 'width'), answer.get('mode')],
      [2, SKIP, 2])
values, answer = asked(source={'kind': 'civitai', 'image': 99})
check('an image the library has no record of: said, nothing pasted', [answer.get('error'), answer.get('pasted')],
      ['The image is not in the library', None])

# ------------------------------------------------- a generation's source (#302)
# A generation's Send hands the loader the generation as its source: the
# server replays its kept press (#7) - into img2img only an img2img one's - or
# pastes its image's own infotext, the chips' renames applied and its Lora
# hashes left out, corrected from its record; a replay that fails is pasted in
# the same event. The Model Manager's card sends the generation's own text.
def gen(mode, inputs, image_text, own_text=None, meta=None):
    return {'mode': mode, 'inputs': inputs, 'infotext': own_text,
            'images': [{'id': 5, 'infotext': image_text, 'meta': meta or {}}]}
generations = {
    12: gen('img2img', kept_press, 'a kept castle\nSteps: 20'),
    13: gen('txt2img', None, 'a <lora:alias_x:0.8> tower\nSteps: 20, Lora hashes: "alias_x: abc123"',
            own_text='the generation\'s own text\nSteps: 20', meta={'Schedule type': 'Karras'}),
    14: gen('img2img', kept_press, 'a castle whose press is gone\nSteps: 20'),
    15: gen('img2img', kept_press, 'a pressed castle\nSteps: 20'),
    16: gen('txt2img', kept_press, 'a txt2img press\nSteps: 20'),
    17: gen('img2img', None, ''),
    18: gen('img2img', None, 'a castle\nSteps: 20'),
    19: gen('img2img', None, 'a castle\nSize: 832x1216'),
}
load.get_models_db = lambda: types.SimpleNamespace(
    **{**vars(db_before()), 'get_generation': lambda gid: generations.get(gid)})


def ask_tab(tab, **request):
    out = load._loader(tab, KEPT, EXTRAS, KEPT_NAMES)(json.dumps({'nonce': 'n', **request}))
    return out[:-1], json.loads(out[-1])


# The settings button, whatever it is asked: no canvas, only the other
# controls, then the extras (#299); `into` sets the mode and, where the text
# gives no size, the picture's.
values, answer = asked(source={'kind': 'generation', 'generation': 19},
                       into={**INTO, 'picture': {'generation_image': 7}})
check('the settings button answers no canvas at all - only the other controls, then the extras',
      [len(values), answer.get('error')], [len(KEPT) + len(EXTRAS), None])
check('the infotext pasted, `mode` the chosen mode, its answer saying so; a text with a size keeps it',
      [value(values, 'prompt'), value(values, 'mode'), answer.get('mode'), value(values, 'width')],
      ['a castle', 2, 2, SKIP])
values, answer = asked(source={'kind': 'generation', 'generation': 18},
                       into={**INTO, 'mode': 4, 'picture': {'generation_image': 7}})
check('an infotext with no size: width and height the picture\'s, as the page gives them',
      [value(values, 'width'), value(values, 'height'), answer.get('mode')], [96, 64, 4])
pasted.clear()
values, answer = asked(source={'kind': 'generation', 'generation': 17},
                       into={**INTO, 'mode': 1, 'picture': {'generation_image': 7}})
check('no infotext: nothing pasted - Forge\'s paste of an empty text pastes the last run\'s settings',
      [pasted, answer.get('mode')], [[], 1])
check('only the mode and the picture\'s size set; the rest as on screen',
      [n for n in KEPT_NAMES if value(values, n) != SKIP], ['mode', 'height', 'width'])
values, answer = asked(source={'kind': 'generation', 'generation': 12, 'image': 5},
                       into={**INTO, 'mode': 1, 'picture': {'generation_image': 7}})
check('a kept press replayed into Sketch: its settings and size, the mode Sketch, no canvas',
      [value(values, 'prompt'), value(values, 'width'), value(values, 'mode'), len(values), answer.get('mode')],
      ['a pressed prompt', 512, 1, len(KEPT) + len(EXTRAS), 1])
pasted.clear()
values, answer = asked(source={'kind': 'generation', 'generation': 18})
check('without `into`: the paste as it was, and no mode set',
      [pasted, [n for n in KEPT_NAMES if value(values, n) != SKIP], 'mode' in answer],
      [['a castle\nSteps: 20'], ['prompt'], False])
txt = attempt(lambda: ask_tab('txt2img', source={'kind': 'generation', 'generation': 13},
                              into={**INTO, 'picture': {'generation_image': 7}})[1])
check('txt2img takes no picture: its paste is as it was', [txt.get('mode') if isinstance(txt, dict) else txt],
      [None])

RENAME_X = [{'from': 'alias_x', 'to': 'file_x'}]
pasted.clear(), pasted_for.clear(), after.clear()
out = attempt(lambda: ask_tab('txt2img', source={'kind': 'generation', 'generation': 13, 'image': 5,
                                                  'renames': RENAME_X}))
values, answer = out if isinstance(out, tuple) else ([], {'error': out})
check('a generation pasted: its image\'s text, the LoRA renamed, no Lora hashes, corrected from its record',
      [pasted[-1:], pasted_for[-1:], answer.get('pasted'), answer.get('replayed')],
      [['a <lora:file_x:0.8> tower\nSteps: 20'], [13], True, None])
check('its schedule type and Hires fix set in the same event, as the page read them from the image\'s data',
      after[-1:], [('Karras', False)])
pasted.clear()
values, answer = asked(source={'kind': 'generation', 'generation': 13, 'image': 5, 'whole': True})
check('the Model Manager\'s card: the generation\'s own text', pasted, ['the generation\'s own text\nSteps: 20'])

pasted.clear()
values, answer = asked(source={'kind': 'generation', 'generation': 15, 'image': 5,
                               'renames': [{'from': 'alias_y', 'to': 'file_y'}]})
check('a kept press replayed, nothing pasted, the renames applied to its prompt, its mode and source said',
      [pasted, answer.get('replayed'), value(values, 'prompt'), answer.get('mode'), answer.get('source')],
      [[], True, 'a pressed <lora:file_y:1> prompt', 2, True])
values, answer = asked(source={'kind': 'generation', 'generation': 12, 'image': 5},
                       into={**INTO, 'mode': 1, 'picture': {'generation_image': 7}})
check('into a mode: an img2img press replayed, with the mode sent', [answer.get('replayed'), answer.get('mode'),
      value(values, 'mode')], [True, 1, 1])
pasted.clear()
values, answer = asked(source={'kind': 'generation', 'generation': 16, 'image': 5},
                       into={**INTO, 'mode': 2, 'picture': {'generation_image': 7}})
check('a txt2img generation\'s press into img2img: not replayed, its text pasted',
      [answer.get('replayed'), pasted], [None, ['a txt2img press\nSteps: 20']])
pasted.clear()
values, answer = asked(source={'kind': 'generation', 'generation': 14, 'image': 5})
check('a replay that fails: pasted in the same event, no error',
      [answer.get('replayed'), answer.get('pasted'), answer.get('error'), pasted],
      [None, True, None, ['a castle whose press is gone\nSteps: 20']])
values, answer = asked(source={'kind': 'generation', 'generation': 99})
check('no such generation: said, nothing set', [answer.get('error'), answer.get('pasted')], ['No generation #99', None])

# A task's source is its id: set back from what it was queued with, as {task} was.
tasks_asked = []
real_task_values = load.task_values
load.task_values = lambda tab, task_id, skip=None: (tasks_asked.append(task_id), ([skip] * COUNT, [], []))[1]
values, answer = asked(source={'kind': 'task', 'task': 5})
check('a task\'s source: the task set back, and named in the answer', [tasks_asked, answer.get('task')], [[5], 5])
load.task_values = real_task_values

load.get_models_db = db_before
if real_after:
    load.after_paste = real_after

# ---------------------------------------------------------- a mode's canvas button
values, answer = canvas(2, picture={'generation_image': 7})
check('Inpaint\'s canvas button: its picture the file\'s, as RGB, its mask emptied - values, never "leave as is"',
      [[size_of(v) if v is not None else None for v in values], getattr(values[0], 'mode', None) if values else None,
       any(isinstance(v, dict) for v in values), answer.get('mode'), answer.get('source')],
      [[(96, 64), None], 'RGB', False, 2, True])
values, answer = canvas(4, picture={'generation_image': 7})
check('Inpaint upload\'s: its picture box the picture, its mask box empty',
      [size_of(v) if v is not None else None for v in values], [(96, 64), None])
values, answer = canvas(0, picture={'generation_image': 7})
check('img2img\'s: its one canvas', [size_of(v) for v in values], [(96, 64)])
values, answer = canvas(3, picture={'url': 'https://image.civitai.com/x/original=true/1.jpeg'})
check('a Civitai original fetched, into Inpaint sketch, its strokes emptied',
      [asked_urls[-1:], [size_of(v) if v is not None else None for v in values]],
      [['https://image.civitai.com/x/original=true/1.jpeg'], [(120, 80), None]])
values, answer = canvas(2, generation=12)
check('a press\'s kept canvases (#34): its picture and its mask, from their files',
      [[size_of(v) if v is not None else None for v in values], answer.get('source')], [[(96, 64), (96, 64)], True])
values, answer = canvas(2, task=5)
check('a task\'s kept canvases (Load to UI)', [size_of(v) if v is not None else None for v in values],
      [(96, 64), (96, 64)])
values, answer = canvas(2, task=6)
check('another WebUI\'s task: said, nothing set', [answer.get('error'), values], ['No task #6 in this WebUI', [None, None]])


def refused(picture):
    """What a canvas button answers for a picture it cannot have: its error, and what it set."""
    values, answer = canvas(2, picture=picture)
    return answer.get('error'), [v for v in values if v is not None]


before = len(asked_urls)
check('another host: refused, not asked, nothing set',
      [refused({'url': 'https://example.com/a.png'}), len(asked_urls) - before],
      [("Only Civitai's image server is asked for an image", []), 0])
check('Civitai\'s image server over http: refused',
      refused({'url': 'http://image.civitai.com/x/original=true/1.jpeg'}),
      ("Only Civitai's image server is asked for an image", []))
check('Civitai answering 404: said, nothing set',
      refused({'url': 'https://image.civitai.com/x/original=true/404.jpeg'}),
      ('Could not fetch the image from Civitai: 404 Not Found', []))
check('Civitai answering what is not an image: said, nothing set',
      refused({'url': 'https://image.civitai.com/x/original=true/text.jpeg'}),
      ('What Civitai sent is not an image', []))
limit = getattr(load, 'PICTURE_LIMIT', None)
load.PICTURE_LIMIT = 200
check('an original over the size allowed: said, nothing set',
      refused({'url': 'https://image.civitai.com/x/original=true/big.jpeg'}), ('The image is larger than 50 MB', []))
load.PICTURE_LIMIT = limit
check('a generation whose file is gone: said, nothing set', refused({'generation_image': 8}),
      ('The image file is gone: deleted or moved', []))

# ---------------------------------------------------------- the wiring
# The buttons as Gradio is handed them: the settings button's outputs hold no
# canvas; each canvas button's hold its mode's canvases alone, then its answer.
wired = {}


class Clickable(object):
    def __init__(self, elem_id=None, **kwargs):
        self.elem_id = elem_id

    def click(self, fn=None, inputs=None, outputs=None, **kwargs):
        wired[self.elem_id] = [getattr(o, 'name', getattr(o, 'elem_id', o)) for o in outputs]


class Box(object):
    def __init__(self, elem_id=None, **kwargs):
        self.elem_id = elem_id


real_button, real_textbox = gr.Button, gr.Textbox
gr.Button, gr.Textbox = Clickable, Box
capture.generate_click = lambda tab: OWN if tab == 'img2img' else None
load.paste_outputs = lambda tab: [types.SimpleNamespace(name='an extra')]
try:
    attempt(load.wire_load_buttons)
finally:
    gr.Button, gr.Textbox = real_button, real_textbox
check('the settings button\'s outputs: every control but the canvases, the extras, the answer',
      wired.get('mm_load_img2img'), KEPT_NAMES + ['an extra', 'mm_load_img2img_answer'])
check('a canvas button per mode that takes a picture, each its mode\'s canvases alone, then its answer',
      {k: v for k, v in wired.items() if k.startswith('mm_load_img2img_canvas_')},
      {'mm_load_img2img_canvas_%d' % m: list(names) + ['mm_load_img2img_canvas_answer']
       for m, names in {0: ['init_img'], 1: ['sketch', 'sketch_fg'], 2: ['init_img_with_mask', 'init_img_with_mask_fg'],
                        3: ['inpaint_color_sketch', 'inpaint_color_sketch_fg'],
                        4: ['init_img_inpaint', 'init_mask_inpaint']}.items()})

if fails:
    print('FAIL ' + '\nFAIL '.join(fails))
    sys.exit(1)
print('ok')
