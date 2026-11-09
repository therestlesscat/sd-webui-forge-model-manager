"""
What Sync images reads from an image file (#408): Forge's infotext where Forge
writes it, and where it is not there, the prompts other tools write -
model_manager.image_text.read_text and model_manager.image_formats, over
files this suite writes as each tool writes them (the survey linked from #408
names the commits read). No real image is used.

Forge's text must come out as it did before #408: `head_read_text` below is
that function, frozen, and every Forge-shaped file is read by both.
"""
import html
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

import piexif                                            # noqa: E402
from PIL import Image                                    # noqa: E402
from PIL.PngImagePlugin import PngInfo                   # noqa: E402

from model_manager.image_text import read_text           # noqa: E402

# A failure naming 一 must print on a Windows console, or it hides the rest.
sys.stdout.reconfigure(errors='backslashreplace')

WORK = os.path.join(TESTS, 'work', 'image_formats')
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ------------------------------------------------------------- read_text before #408, frozen

def head_read_text(path):
    with Image.open(path) as image:
        width, height = image.size
        info = image.info or {}
        text = info.get("parameters")
        if not text and "exif" in info:
            text = _head_user_comment(image)
        if not text and isinstance(info.get("comment"), (bytes, str)):
            comment = info["comment"]
            text = comment.decode("utf-8", "ignore") if isinstance(comment, bytes) else comment
    text = text.strip() if isinstance(text, str) else None
    return (text or None), width, height


def _head_user_comment(image):
    try:
        value = image.getexif().get_ifd(0x8769).get(0x9286)
    except Exception:
        return None
    if isinstance(value, str):
        return value
    if not isinstance(value, bytes) or len(value) < 8:
        return None
    head, body = value[:8], value[8:]
    if head == b"UNICODE\x00":
        encoding = "utf-16-le" if body[1:2] == b"\x00" and body[:1] != b"\x00" else "utf-16-be"
        return body.decode(encoding, "ignore")
    return body.decode("utf-8", "ignore")


# ------------------------------------------------------------- writing files as each tool does

def png(name, *chunks, itxt=()):
    """A PNG with these text chunks, in order - a key twice where a tool writes it twice."""
    path = os.path.join(WORK, name)
    info = PngInfo()
    for key, value in chunks:
        info.add_text(key, value)
    for key, value in itxt:
        info.add_itxt(key, value)
    Image.new('RGB', (48, 32), (10, 20, 30)).save(path, pnginfo=info)
    return path


def user_comment(name, comment, kind='jpeg'):
    """A JPEG or WebP whose Exif part holds this UserComment, as piexif writes it -
    which every Forge does, and reads back under the original Forge's PIL too."""
    path = os.path.join(WORK, name)
    exif = piexif.dump({'Exif': {piexif.ExifIFD.UserComment: comment}})
    Image.new('RGB', (48, 32), (10, 20, 30)).save(path, 'JPEG' if kind == 'jpeg' else 'WEBP', exif=exif)
    return path


def forge_comment(text):
    """piexif's "unicode": Forge's own UserComment, big-endian."""
    return b'UNICODE\x00' + text.encode('utf-16-be')


def top_level(name, text, kind='jpeg', **tags):
    """Fooocus's JPEG or WebP: its text set on PIL's Exif at the top level, as a str."""
    path = os.path.join(WORK, name)
    exif = Image.Exif()
    exif[0x9286] = text
    for tag, value in tags.items():
        exif[int(tag[1:], 16)] = value
    Image.new('RGB', (48, 32), (10, 20, 30)).save(path, 'JPEG' if kind == 'jpeg' else 'WEBP', exif=exif)
    return path


def jpeg_comment(name, comment):
    path = os.path.join(WORK, name)
    Image.new('RGB', (48, 32), (10, 20, 30)).save(path, 'JPEG', comment=comment)
    return path


def prompts(path):
    """read_text's answer for a file with no Forge text: its prompts, checked to come with no text."""
    text, width, height, found = read_text(path)
    return found if (text, width, height) == (None, 48, 32) else ('text', text)


def p(prompt, negative, tool):
    return {'prompt': prompt, 'negative': negative, 'tool': tool}


FORGE = ('a castle on a hill\nNegative prompt: blurry\n'
         'Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 5, Size: 48x32, Model: x')
GRAPH = json.dumps({'3': {'class_type': 'KSampler', 'inputs': {'positive': ['6', 0], 'negative': ['7', 0]}},
                    '6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'a graph prompt'}}})
WORKFLOW = json.dumps({'nodes': [{'id': 6, 'type': 'CLIPTextEncode', 'widgets_values': ['a graph prompt']}]})


# ------------------------------------------------------------- one file per format

check('Endless Image_saver PNG: plain prompt and negative chunks',
      prompts(png('endless.png', ('prompt', 'a red fox'), ('negative_prompt', 'blurry'), ('batch_index', '0'),
                  ('creation_time', '2026-11-08T10:00:00'), ('workflow', WORKFLOW), ('workflow', WORKFLOW))),
      p('a red fox', 'blurry', 'Endless'))
check('Easy Diffusion PNG: one chunk per field, a negative it lacked written as None',
      prompts(png('ed.png', ('prompt', 'a blue lake'), ('negative_prompt', 'None'), ('seed', '42'),
                  ('use_stable_diffusion_model', 'sd-v1-5'))),
      p('a blue lake', None, 'Easy Diffusion'))
check('Easy Diffusion PNG, its txt spelling',
      prompts(png('ed_txt.png', ('Prompt', 'a green hill'), ('Negative Prompt', 'dark'), ('Seed', '42'))),
      p('a green hill', 'dark', 'Easy Diffusion'))
check('Easy Diffusion JPEG: JSON in the UserComment, a null negative',
      prompts(user_comment('ed.jpg', forge_comment(json.dumps(
          {'prompt': 'a yellow field', 'negative_prompt': None, 'seed': 42, 'use_stable_diffusion_model': 'x'})))),
      p('a yellow field', None, 'Easy Diffusion'))
check('Easy Diffusion WebP, its txt spelling in JSON',
      prompts(user_comment('ed.webp', forge_comment(json.dumps(
          {'Prompt': 'a white cloud', 'Negative Prompt': 'grey', 'Seed': 42})), kind='webp')),
      p('a white cloud', 'grey', 'Easy Diffusion'))
SWARM = {'sui_image_params': {'prompt': 'a tall tower', 'negativeprompt': 'low quality', 'seed': 7,
                              'swarm_version': '0.9'}, 'sui_models': []}
check('SwarmUI PNG: JSON in parameters', prompts(png('swarm.png', ('parameters', json.dumps(SWARM)))),
      p('a tall tower', 'low quality', 'SwarmUI'))
check('SwarmUI JPEG: JSON in the UserComment, UTF-16 little-endian',
      prompts(user_comment('swarm.jpg', b'UNICODE\x00' + json.dumps(SWARM).encode('utf-16-le'))),
      p('a tall tower', 'low quality', 'SwarmUI'))
check('RuinedFooocus PNG: JSON in parameters, marked by its software',
      prompts(png('ruined.png', ('parameters', json.dumps(
          {'Prompt': 'a quiet street', 'Negative': 'people', 'software': 'RuinedFooocus', 'steps': 30})))),
      p('a quiet street', 'people', 'RuinedFooocus'))
FOOOCUS = {'prompt': 'a cat', 'negative_prompt': 'dog', 'full_prompt': ['a cat', 'cinematic, sharp'],
           'full_negative_prompt': ['dog'], 'steps': 30, 'version': 'Fooocus v2.5.5'}
check('Fooocus PNG, its JSON scheme: the typed prompt, not the one its styles expanded to',
      prompts(png('fooocus.png', ('parameters', json.dumps(FOOOCUS)), ('fooocus_scheme', 'fooocus'))),
      p('a cat', 'dog', 'Fooocus'))
check('Fooocus JPEG, its JSON scheme at the top level of the EXIF',
      prompts(top_level('fooocus.jpg', json.dumps(FOOOCUS), x0131='Fooocus v2.5.5', x927C='fooocus')),
      p('a cat', 'dog', 'Fooocus'))
check('Fooocus WebP, nothing typed: the expanded prompt, joined',
      prompts(top_level('fooocus.webp', json.dumps(dict(FOOOCUS, prompt='')), kind='webp')),
      p('a cat, cinematic, sharp', 'dog', 'Fooocus'))
CIVITAI_META = json.dumps(json.dumps({'prompt': 'a stone bridge', 'negativePrompt': 'fog', 'steps': 25}))
check('Civitai\'s early on-site image: extraMetadata, encoded twice',
      prompts(png('civitai.png', ('parameters', json.dumps(
          {'prompt': {'3': {'class_type': 'KSampler'}}, 'extra': {'airs': []}, 'extraMetadata': CIVITAI_META})))),
      p('a stone bridge', 'fog', 'Civitai'))
check('InvokeAI 3: invokeai_metadata, a null negative',
      prompts(png('invoke3.png', ('invokeai_metadata', json.dumps(
          {'positive_prompt': 'a lighthouse', 'negative_prompt': None, 'seed': 1})),
          ('invokeai_workflow', '{}'), ('invokeai_graph', '{}'))),
      p('a lighthouse', None, 'InvokeAI'))
DREAM = '"a sailing ship [stormy]" -s 30 -S 12 -W 512 -H 512'
check('InvokeAI 2.x: sd-metadata\'s prompt as a list, the negative left inside it',
      prompts(png('invoke2_list.png', ('Dream', DREAM), ('sd-metadata', json.dumps(
          {'image': {'prompt': [{'prompt': 'a sailing ship [stormy]', 'weight': 1.0}]}})))),
      p('a sailing ship [stormy]', None, 'InvokeAI'))
check('InvokeAI 2.x: sd-metadata\'s prompt as a string',
      prompts(png('invoke2_str.png', ('sd-metadata', json.dumps({'image': {'prompt': 'a harbour'}})))),
      p('a harbour', None, 'InvokeAI'))
check('InvokeAI 2.x: Dream alone, its first quoted text',
      prompts(png('invoke2_dream.png', ('Dream', DREAM))), p('a sailing ship [stormy]', None, 'InvokeAI'))
check('NovelAI: Description, and Comment\'s uc',
      prompts(png('novelai.png', ('Title', 'AI generated image'), ('Description', 'a fox in snow'),
                  ('Software', 'NovelAI'), ('Comment', json.dumps({'uc': 'lowres', 'steps': 28, 'prompt': 'x'})))),
      p('a fox in snow', 'lowres', 'NovelAI'))
DRAW = {'c': 'salt & pepper <3 "fresh"', 'uc': 'bland', 'seed': 3}
XMP = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
       '<rdf:Description rdf:about="" xmlns:exif="http://ns.adobe.com/exif/1.0/"><exif:UserComment><rdf:Alt>'
       f'<rdf:li xml:lang="x-default">{html.escape(json.dumps(DRAW))}</rdf:li>'
       '</rdf:Alt></exif:UserComment></rdf:Description></rdf:RDF></x:xmpmeta>')
check('Draw Things: JSON in the XMP\'s UserComment, its &, < and quote undone',
      prompts(png('drawthings.png', itxt=[('XML:com.adobe.xmp', XMP)])),
      p('salt & pepper <3 "fresh"', 'bland', 'Draw Things'))

# ------------------------------------------------------------- Forge's text, as before

A1111_TEXT = 'a house\nSteps: 20, Sampler: Euler a, CFG scale: 7, Seed: 5, Size: 48x32'
SDNEXT = ('a road\nNegative prompt: \nTemplate: a {prompt}\nNegative template: \n'
          'Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 5, Size: 48x32, Original prompt: a road')
forge_files = {
    'Forge PNG': png('forge.png', ('parameters', FORGE)),
    'Forge JPEG': user_comment('forge.jpg', forge_comment(FORGE)),
    'Forge WebP': user_comment('forge.webp', forge_comment(FORGE), kind='webp'),
    'A1111 PNG, no negative line': png('a1111.png', ('parameters', A1111_TEXT)),
    'SD.Next PNG, its empty negative and templates': png('sdnext.png', ('parameters', SDNEXT)),
    'SD.Next JPEG, its UserComment key ahead of the text': user_comment(
        'sdnext.jpg', forge_comment('a note, ' + SDNEXT)),
    'Forge text in a JPEG\'s comment': jpeg_comment('forge_comment.jpg', FORGE.encode('utf-8')),
    'a PNG with parameters of spaces alone, and a prompt chunk after': png(
        'spaces.png', ('parameters', '   '), ('prompt', 'not read')),
    'a PNG with nothing': png('nothing.png'),
}
for label, path in forge_files.items():
    check(f'{label}: read as before #408, no prompts beside it',
          read_text(path), head_read_text(path) + (None,))
check('and Forge\'s text is what each holds', [read_text(forge_files[k])[0] for k in
      ('Forge PNG', 'Forge JPEG', 'Forge WebP', 'Forge text in a JPEG\'s comment')], [FORGE] * 4)

check('Fooocus\'s a1111 scheme in a JPEG, at the EXIF\'s top level: Forge\'s text, settings and all',
      read_text(top_level('fooocus_a1111.jpg', FORGE, x0131='Fooocus v2.5.5', x927C='a1111')),
      (FORGE, 48, 32, None))
check('Image-Saver PNG: parameters, a graph prompt and workflow - Forge\'s text',
      read_text(png('imagesaver.png', ('parameters', FORGE), ('prompt', GRAPH), ('workflow', WORKFLOW))),
      (FORGE, 48, 32, None))
check('Forge\'s text beside a plain prompt chunk: Forge\'s text, the chunk not asked',
      read_text(png('forge_and_prompt.png', ('parameters', FORGE), ('prompt', 'another prompt'),
                    ('negative_prompt', 'x'))),
      (FORGE, 48, 32, None))

# ------------------------------------------------------------- what is no text, and no prompt

check('unknown JSON in parameters: no text, no prompt - where it was taken for both',
      read_text(png('unknown.png', ('parameters', json.dumps(
          {'note': 'x', 'params': 'Steps: 20, Sampler: Euler a, CFG scale: 7'})))),
      (None, 48, 32, None))
check('unknown JSON in a JPEG\'s comment: nothing',
      read_text(jpeg_comment('unknown_comment.jpg', json.dumps(
          {'note': 'x', 'params': 'Steps: 20, Sampler: Euler a, CFG scale: 7'}).encode('utf-8'))),
      (None, 48, 32, None))
check('a JPEG\'s comment an image editor wrote: nothing',
      read_text(jpeg_comment('gimp.jpg', b'Created with GIMP')), (None, 48, 32, None))
check('unknown JSON in parameters, the Endless chunks beside it: those are read',
      prompts(png('unknown_then_chunks.png', ('parameters', '{"note": "x"}'), ('prompt', 'a red fox'),
                  ('batch_index', '0'))),
      p('a red fox', None, 'Endless'))

check('a top-level UserComment a script wrote, no settings line: nothing',
      read_text(top_level('top_note.jpg', 'Edited with SomeEditor')), (None, 48, 32, None))
swarm_spaces = os.path.join(WORK, 'swarm_spaces.png')
_info = PngInfo()
_info.add_text('parameters', json.dumps(SWARM))
Image.new('RGB', (48, 32), (10, 20, 30)).save(swarm_spaces, pnginfo=_info, exif=piexif.dump(
    {'Exif': {piexif.ExifIFD.UserComment: b'ASCII\x00\x00\x00   '}}))
check('SwarmUI\'s JSON, then a UserComment of spaces: the JSON\'s prompts kept',
      prompts(swarm_spaces), p('a tall tower', 'low quality', 'SwarmUI'))


def raised(path):
    try:
        return read_text(path)
    except Exception as e:      # a check, not a crash, when a break lets it escape
        return 'raised ' + type(e).__name__


check('JSON nested too deep for Python, in parameters: nothing, and no error',
      raised(png('deep.png', ('parameters', '[' * 100000))), (None, 48, 32, None))
check('nor in a prompt chunk',
      raised(png('deep_prompt.png', ('prompt', '{"a":' * 5000 + '1' + '}' * 5000))), (None, 48, 32, None))
check('JSON holding a whole number of 5,000 digits: JSON no reader knows, in either WebUI\'s Python',
      raised(png('long_number.png', ('parameters', '{"seed": 1' + '0' * 5000 + '}'))), (None, 48, 32, None))
_xmp = '<x:xmpmeta>' + '<exif:UserComment><rdf:li>' * 600 + '</x:xmpmeta>'
_unclosed = png('xmp_unclosed.png', itxt=[('XML:com.adobe.xmp', _xmp)])
_start = time.perf_counter()
_answer = read_text(_unclosed)
check('an XMP packet of 600 unclosed UserComments: read once, under a second',
      (_answer, time.perf_counter() - _start < 1.0), ((None, 48, 32, None), True))

# ------------------------------------------------------------- UTF-16's byte order

CJK = '一面の花畑\nNegative prompt: 低品質\nSteps: 20, Sampler: Euler a, CFG scale: 7, Seed: 5, Size: 48x32'
check('a Forge JPEG whose prompt starts with 一 (U+4E00): read right',
      read_text(user_comment('cjk.jpg', forge_comment(CJK)))[0], CJK)
CJK_HEAVY = '\u3000'.join(['猫'] * 80) + '\nSteps: 20, Sampler: Euler, CFG scale: 7, Seed: 1'
check('a Forge JPEG mostly of characters whose zero byte falls the other way (U+3000): read right',
      read_text(user_comment('cjk_heavy.jpg', forge_comment(CJK_HEAVY)))[0], CJK_HEAVY)
check('a SwarmUI JPEG\'s text, little-endian: read right',
      prompts(user_comment('swarm_cjk.jpg', b'UNICODE\x00' + json.dumps(
          {'sui_image_params': {'prompt': '一面の花畑', 'negativeprompt': ''}}).encode('utf-16-le'))),
      p('一面の花畑', None, 'SwarmUI'))

# ------------------------------------------------------------- ComfyUI's graph, left to #232

check('ComfyUI\'s PNG, its graph in prompt: nothing',
      read_text(png('comfy.png', ('prompt', GRAPH), ('workflow', WORKFLOW))), (None, 48, 32, None))
comfy_webp = os.path.join(WORK, 'comfy.webp')
_exif = Image.Exif()
_exif[0x0110] = 'prompt:' + GRAPH
_exif[0x010F] = 'workflow:' + WORKFLOW
Image.new('RGB', (48, 32), (10, 20, 30)).save(comfy_webp, 'WEBP', exif=_exif)
check('ComfyUI\'s WebP, prompt: in the EXIF\'s Model: never read', read_text(comfy_webp), (None, 48, 32, None))

# ------------------------------------------------------------- what a prompt is

check('a plain prompt of {red|blue}: text, not JSON',
      prompts(png('wildcard.png', ('prompt', '{red|blue} car'))), p('{red|blue} car', None, None))
check('one of [cat:dog:0.5]: text, not JSON',
      prompts(png('editing.png', ('prompt', '[cat:dog:0.5]'), ('negative_prompt', ' blurry '))),
      p('[cat:dog:0.5]', 'blurry', None))
check('a blank prompt: no prompts',
      prompts(png('blank.png', ('prompt', '   '), ('negative_prompt', 'blurry'))), None)
check('a negative alone: no prompts',
      prompts(png('negative_alone.png', ('Prompt', 'None'), ('Negative Prompt', 'blurry'))), None)
check('JSON\'s null for a prompt: no prompts',
      prompts(png('null.png', ('invokeai_metadata', json.dumps({'positive_prompt': None, 'negative_prompt': 'x'})))),
      None)
check('a Crystools PNG: a Description of its own, Software JSON-encoded - no NovelAI',
      prompts(png('crystools.png', ('Title', '"My picture"'), ('Description', '"a picture I made"'),
                  ('Software', '"ComfyUI"'), ('prompt', GRAPH), ('workflow', WORKFLOW))),
      None)

for line in fails:
    print('FAIL', line)
print('%d failed' % len(fails) if fails else 'image_formats_test: all passed')
sys.exit(1 if fails else 0)
