"""
What a Civitai image's Send pastes, built on the server (#302): the VAEs an
image names, the infotext, its size, and what the loader sets in the paste's
own event.

All of it was the page's until #302 (vaeFromMeta, modulesFromMeta,
buildInfotext, unquotePrompt, the Size filled in sendGalleryImageTo,
withVideoParams), and these checks were the page's suites' - vae_meta_test.js
and forge_preset_test.mjs's reading of the pasted text. Every stored image's
text is compared with the page's old code by hand (tests/work/r302/, check 1).
"""
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

webui_stub.install()

from model_manager import send                           # noqa: E402
from model_manager.scheduler import load                 # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ------------------------------------------------------- the VAE an image names
# Every spelling Civitai uses for a VAE, and every placeholder that only looks
# like one. Counts from 67,458 stored images.
v = send.named_vae
check('VAE, the usual field (11,304 images)', v({'VAE': 'blessed2.vae'}), 'blessed2.vae')
check('vaes, a ComfyUI list (2,392 images, none of which have VAE)',
      v({'vaes': ['qwen_image_vae.safetensors']}), 'qwen_image_vae.safetensors')
check('vae, lowercase', v({'vae': 'aaaAnimeSDXLVAE_v15'}), 'aaaAnimeSDXLVAE_v15')
check('vae_name, a real one', v({'vae_name': 'sdxl_vae.safetensors'}), 'sdxl_vae.safetensors')
check('resources, a VAE among them', v({'resources': [{'type': 'vae', 'name': 'x.safetensors'}]}), 'x.safetensors')
for label, meta in (('Default (model), 131 images', {'VAE': 'Default (model)'}), ('Default, 14 images', {'VAE': 'Default'}),
                    ('Baked VAE, 5 images', {'VAE': 'Baked VAE'}), ('Baked VAE under Vae', {'Vae': 'Baked VAE'}),
                    ('automatic, 30 images', {'vae_name': 'automatic'}), ('None', {'VAE': 'None'}),
                    ('a placeholder inside the list', {'vaes': ['automatic']}),
                    ('VAE hash alone is not a name', {'VAE hash': '235745af8d'}), ('empty data', {}),
                    ('no data at all', None), ('an empty list', {'vaes': []}), ('a blank string', {'VAE': '   '}),
                    ('ADetailer fields are not the main VAE', {'ADetailer VAE': 'vae-ft-mse-840000-ema-pruned.ckpt'})):
    check(f'no VAE: {label}', v(meta), None)
check('VAE outranks the list', v({'VAE': 'a.safetensors', 'vaes': ['b.safetensors']}), 'a.safetensors')
check('a placeholder in VAE falls through to the list', v({'VAE': 'Default', 'vaes': ['b.safetensors']}), 'b.safetensors')
check('surrounding whitespace is trimmed', v({'VAE': '  c.safetensors  '}), 'c.safetensors')

# Forge writes its VAE / Text Encoder selection as Module 1, Module 2, ...:
# 4,277 stored images name their modules only so (#204).
m = send.named_modules
check('an image naming its VAE only as Module 1 gives it', m({'Module 1': 'sdxl_vae'}), ['sdxl_vae'])
check('every Module N, in order of its number, after the VAE key',
      m({'VAE': 'ae', 'Module 2': 'qwen_3_06b_base', 'Module 10': 'x', 'Module 1': 'qwen_image_vae'}),
      ['ae', 'qwen_image_vae', 'qwen_3_06b_base', 'x'])
check('each once, whatever its case', m({'VAE': 'sdxl_vae', 'Module 1': 'SDXL_VAE'}), ['sdxl_vae'])
check('a placeholder is no module', m({'Module 1': 'Automatic'}), [])
check('an image naming none gives none', m({'prompt': 'x'}), [])

# ------------------------------------------------------------- the infotext
SAMPLERS = ['Euler a', 'Euler', 'DPM++ 2M']
SCHEDULERS = ['Karras', 'Simple', 'SGM Uniform']


def text(meta, width=832, height=1216, **kw):
    return send.civitai_infotext({'meta': meta, 'width': width, 'height': height}, SAMPLERS, SCHEDULERS, **kw)


def settings(t):
    return t.split('\n')[-1]


IMAGE = {'prompt': 'a lighthouse at dusk', 'negativePrompt': 'blurry', 'steps': 20, 'sampler': 'Euler a',
         'cfgScale': 7, 'seed': 1, 'Size': '832x1216'}
check('the prompt, the negative prompt, then the settings line',
      text(IMAGE), 'a lighthouse at dusk\nNegative prompt: blurry\n'
      'Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 1, Size: 832x1216, ADetailer enable: False')
# Some tools give Civitai the prompt as a quoted string. Pasted as it is, a
# model reading prompts as instructions took the whole as one quotation and
# drew noise; the quotes around the whole go, and only those.
check('a prompt and a negative prompt quoted whole go in without the quotes',
      text({**IMAGE, 'prompt': ' "a lighthouse at dusk, (fog:1.2)" ', 'negativePrompt': '"blurry"'}).split('\n')[:2],
      ['a lighthouse at dusk, (fog:1.2)', 'Negative prompt: blurry'])
check('a prompt with quotes of its own inside keeps every one',
      text({**IMAGE, 'prompt': '"a sign" reading "open"'}).split('\n')[0], '"a sign" reading "open"')
check('as does one quoted only in part', text({**IMAGE, 'prompt': 'a sign reading "open"'}).split('\n')[0],
      'a sign reading "open"')
check('seed 0 is a seed (#310)', 'Seed: 0,' in settings(text({**IMAGE, 'seed': 0})), True)
check('the sampler\'s name read for its schedule type, as Forge names both',
      'Sampler: Euler a, Schedule type: Karras' in settings(text({**IMAGE, 'sampler': 'euler_a_karras'})), True)
# ComfyUI and Civitai's own generator name the schedule type under a
# lowercase `scheduler` (#308): 5,226 of 107,469 stored images, with no
# `Schedule type`. Read, it is Forge's by case and `_ - +` as spaces.
check('a schedule type under `scheduler`, as Forge lists it',
      'Sampler: Euler a, Schedule type: Karras' in settings(text({**IMAGE, 'scheduler': 'karras'})), True)
check('`scheduler` matched with `_` as a space', 'Schedule type: SGM Uniform' in settings(text({**IMAGE, 'scheduler': 'sgm_uniform'})), True)
check('`scheduler` wins over the one the sampler\'s name ends in; the sampler is still split from it',
      'Sampler: DPM++ 2M, Schedule type: Simple' in settings(text({**IMAGE, 'sampler': 'DPM++ 2M Karras', 'scheduler': 'simple'})), True)
check('`Schedule type` wins over `scheduler`',
      'Schedule type: Simple' in settings(text({**IMAGE, 'Schedule type': 'Simple', 'scheduler': 'karras'})), True)
check('one Forge does not list: the sampler\'s name read, as before',
      'Schedule type: Karras' in settings(text({**IMAGE, 'sampler': 'euler_a_karras', 'scheduler': 'beta57'})), True)
check('one Forge does not list, and none in the sampler\'s name: no schedule type',
      'Schedule type' in settings(text({**IMAGE, 'scheduler': 'beta57'})), False)
check('the raw field stays in the settings line, as it was', 'scheduler: karras' in settings(text({**IMAGE, 'scheduler': 'karras'})), True)
i = lambda meta: send.image_scheduler(meta, SAMPLERS, SCHEDULERS)
check('the schedule type Send sets after the paste: `scheduler` too, and the same order',
      [i({'scheduler': 'karras'}), i({'sampler': 'DPM++ 2M Karras', 'scheduler': 'simple'}),
       i({'Schedule type': 'Simple', 'scheduler': 'karras'}), i({'scheduler': 'beta57'})],
      ['Karras', 'Simple', 'Simple', None])
check('numbers written as the page wrote them: 7.0 as 7',
      'CFG scale: 7,' in settings(text({**IMAGE, 'cfgScale': 7.0})), True)
check('Lora hashes are not pasted: Forge would rename its LoRAs by them',
      'Lora hashes' in text({**IMAGE, 'Lora hashes': '"a: 1234, b: 5678"', 'Version': 'neo'}), False)
check('ADetailer turned on by the image naming its fields',
      'ADetailer enable: True' in text({**IMAGE, 'ADetailer model': 'face_yolov8n.pt'}), True)
check('the page\'s renamed prompt over the image\'s (the chips\' rule)',
      text(IMAGE, prompt='a <lora:local_file:1> lighthouse').split('\n')[0], 'a <lora:local_file:1> lighthouse')

HIRES = {**IMAGE, 'Denoising strength': 0.4, 'Hires upscale': 2, 'Hires upscaler': 'Latent'}
check('an image with no Hires fix: no Denoising strength, so the paste does not turn it on',
      'Denoising strength' in text(IMAGE), False)
check('an upscaler\'s gallery\'s own upscaler, as Hires fix\'s, and no Denoising strength',
      ('Hires upscaler: 4x-UltraSharp' in text(IMAGE, hires_upscaler='4x-UltraSharp'),
       'Denoising strength' in text(IMAGE, hires_upscaler='4x-UltraSharp')), (True, False))
check('an image with Hires fix: the gallery\'s upscaler in place of the image\'s, once',
      settings(text(HIRES, hires_upscaler='4x-UltraSharp')).count('Hires upscaler'), 1)
check('and its Denoising strength', 'Denoising strength: 0.4' in text(HIRES), True)
check('img2img for an image-to-video model: a denoising strength of 1',
      'Denoising strength: 1,' in settings(text(IMAGE, denoising_strength=1)), True)
check('an image-to-video model: Wan\'s size and the video\'s frames',
      ('Size: 1088x1920' in text({**IMAGE, 'Size': '1080x1920'}, 1080, 1920, video=True, frames=81),
       'Batch size: 81' in text(IMAGE, video=True, frames=81)), (True, True))

check('a size Wan can make is kept', send.video_size(832, 480), {'width': 832, 'height': 480})
check('any other goes to the nearest 16', send.video_size(1080, 1920), {'width': 1088, 'height': 1920})
check('never below 16', send.video_size(3, 5), {'width': 16, 'height': 16})
check('halves rounded up, as the page rounded them', send.video_size(8, 24), {'width': 16, 'height': 32})

# ------------------------------------------------- the size (#299, R8)
check('no Size in the data: the picture\'s', 'Size: 832x1216' in text({k: v for k, v in IMAGE.items() if k != 'Size'}), True)
check('the same shape, scaled - Hires fix\'s picture: the data\'s size',
      'Size: 832x1216' in text(IMAGE, 1664, 2432), True)
check('Size alone, of another shape than the picture: the picture\'s',
      'Size: 1536x1024' in text({**IMAGE, 'Size': '512x512'}, 1536, 1024), True)
other = text({**{k: v for k, v in IMAGE.items() if k != 'Size'}, 'width': 512, 'height': 512}, 2304, 1664)
check('width and height of another shape: the picture\'s Size, and neither of them, which Forge reads over it',
      ('Size: 2304x1664' in other, 'width:' in other, 'height:' in other), (True, False, False))
kept = text({**{k: v for k, v in IMAGE.items() if k != 'Size'}, 'width': 416, 'height': 608}, 832, 1216)
check('width and height of the same shape: passed on as they are',
      ('width: 416' in kept, 'height: 608' in kept), (True, True))
check('within 3%: the data\'s', 'Size: 832x1216' in text(IMAGE, 840, 1216), True)

# ----------------------------------- what the loader sets in the paste's event
def control(elem_id, choices=None):
    return types.SimpleNamespace(elem_id=elem_id, choices=choices or [])


outputs = [control('txt2img_prompt'), control(None), control('txt2img_scheduler', [('Automatic', 'Automatic'),
                                                                                    ('Karras', 'Karras')])]
names = ['prompt', 'enable_hr']
values = ['x', True, 'Simple']
load.after_paste('txt2img', values, outputs, names, 'Karras', False)
check('the image\'s schedule type, and Hires fix off for an image made without it', values, ['x', False, 'Karras'])
values = ['x', True, 'Simple']
load.after_paste('txt2img', values, outputs, names, 'Exponential', True)
check('a schedule type the dropdown does not offer leaves the paste\'s; Hires fix kept for an image with it',
      values, ['x', True, 'Simple'])
values = ['x', True, 'Simple']
load.after_paste('img2img', values, outputs, names, 'Karras', False)
check('img2img: Hires fix is txt2img\'s alone, and this is not img2img\'s scheduler', values, ['x', True, 'Simple'])

# ------------------------------------- a generation's renames and settings (#302)
# The chips' rename (renameLoraTags in chips.mjs), ported: the page sends the
# pairs, the server applies them. Every LoRA tag of the stored generations is
# compared with the page's own function by hand (tests/work/r302/, check 1c).
r = send.rename_lora_tags
check('a tag renamed, its weight kept', r('a <lora:alias:0.8> tower', 'alias', 'file'), 'a <lora:file:0.8> tower')
check('in any case, as the page\'s /i', r('<LORA:Alias:1> and <lora:ALIAS>', 'alias', 'file'), '<lora:file:1> and <lora:file>')
check('only the whole name: a longer one is another LoRA', r('<lora:alias2:1>', 'alias', 'file'), '<lora:alias2:1>')
check('every tag, not the first alone', r('<lora:a:1>, <lora:a:0.5>', 'a', 'b'), '<lora:b:1>, <lora:b:0.5>')
check('a name with a regular expression\'s characters is matched as it is',
      [r('<lora:a.b(1)+:1>', 'a.b(1)+', 'x'), r('<lora:aXb(1)+:1>', 'a.b(1)+', 'x')], ['<lora:x:1>', '<lora:aXb(1)+:1>'])
# JavaScript reads `$` in a replacement string: $$ a dollar, $& the match,
# $` what comes before it, $' what comes after; Python's re would read `\`.
check('$$ in the new name is one dollar', r('<lora:a:1>', 'a', 'x$$y'), '<lora:x$y:1>')
check('$& is the tag matched', r('<lora:a:1>', 'a', 'x$&'), '<lora:x<lora:a:1>')
check('$` and $\' are what is before and after it', r('p <lora:a:1> q', 'a', '[$`|$\']'), 'p <lora:[p |:1> q]:1> q')
check('a lone $, and $1 with no group, stay', r('<lora:a:1>', 'a', 'x$1$'), '<lora:x$1$:1>')
check('a backslash is a backslash', r('<lora:a:1>', 'a', 'x\\1y'), '<lora:x\\1y:1>')
# JavaScript's case-blind match without the u flag: a character past ASCII
# never matches an ASCII one - `ſ` is not `s` there, nor the Kelvin sign `k`;
# Python's re says they are.
check('the long s and the Kelvin sign are not s and k, as in JavaScript',
      [r('<lora:ſun:1>', 'sun', 'x'), r('<lora:Kite:1>', 'kite', 'x')], ['<lora:ſun:1>', '<lora:Kite:1>'])
check('nothing, an empty name or the same name: the text as it is',
      [r('', 'a', 'b'), r(None, 'a', 'b'), r('<lora:a:1>', '', 'b'), r('<lora:a:1>', 'a', ''), r('<lora:a:1>', 'a', 'a')],
      ['', None, '<lora:a:1>', '<lora:a:1>', '<lora:a:1>'])
check('the pairs in their order, each over the last one\'s text',
      send.renamed('<lora:a:1>', [{'from': 'a', 'to': 'b'}, {'from': 'b', 'to': 'c'}]), '<lora:c:1>')

g = send.replays
check('a kept press is replayed into its own tab; into img2img only an img2img one\'s; none kept, none replayed',
      [g({'inputs': {'x': 1}, 'mode': 'txt2img'}, False), g({'inputs': {'x': 1}, 'mode': 'txt2img'}, True),
       g({'inputs': {'x': 1}, 'mode': 'img2img'}, True), g({'inputs': None, 'mode': 'img2img'}, False)],
      [True, False, True, False])


class Generations(object):
    def __init__(self, generations):
        self.generations = generations

    def get_generation(self, generation_id):
        return self.generations.get(generation_id)


db = Generations({7: {'mode': 'txt2img', 'inputs': None, 'infotext': 'the generation\'s own\nSteps: 20', 'images': [
    {'id': 70, 'infotext': 'first <lora:alias:1>\nSteps: 20, Lora hashes: "alias: abc"', 'meta': {'sampler': 'Euler'}},
    {'id': 71, 'infotext': 'second\nSteps: 20, Schedule type: Karras',
     'meta': {'Schedule type': 'Karras', 'Denoising strength': 0.4, 'Hires upscale': 2}}]},
                  8: {'mode': 'txt2img', 'inputs': None, 'infotext': None, 'images': [{'id': 80, 'infotext': None}]}})
s = send.generation_settings
first = s(db, {'generation': 7, 'image': 70, 'renames': [{'from': 'alias', 'to': 'file'}]})
check('an image\'s own text, renamed, its Lora hashes left out; no schedule type named: Automatic; no Hires fix',
      [first['text'], first['scheduler'], first['hires'], first['replay']],
      ['first <lora:file:1>\nSteps: 20', 'Automatic', False, False])
second = s(db, {'generation': 7, 'image': 71})
check('another image of it: its own text, its schedule type, its Hires fix',
      [second['text'].split('\n')[0], second['scheduler'], second['hires']], ['second', 'Karras', True])
check('the Model Manager\'s card (`whole`): the generation\'s own text',
      s(db, {'generation': 7, 'image': 70, 'whole': True})['text'], 'the generation\'s own\nSteps: 20')
check('no image named: the first', s(db, {'generation': 7})['text'].split('\n')[0], 'first <lora:alias:1>')
check('no text at all: nothing to paste; no such generation: None',
      [s(db, {'generation': 8, 'whole': True})['text'], s(db, {'generation': 9})], ['', None])
check('settings() takes a generation\'s source to it', send.settings(db, {'kind': 'generation', 'generation': 7,
                                                                         'image': 71})['scheduler'], 'Karras')

# ------------------------------------------------- the card's reading (#302)
# The sampler and schedule type an image's card shows, read where its level
# is stamped. The card read them itself; every stored image is compared with
# its code by hand (tests/work/r302/, check 1e).
c = lambda meta: send.card_reading(meta, SAMPLERS + ['Euler a Uniform'], ['Uniform', 'Karras', 'Simple'])
check('a Schedule type is shown as it is, the sampler too', c({'sampler': 'Euler a', 'Schedule type': 'Karras'}),
      {'mm_sampler': 'Euler a', 'mm_scheduler': 'Karras'})
check('else the sampler\'s name read for one, as Forge names both', c({'sampler': 'Euler a Uniform'}),
      {'mm_sampler': 'Euler a', 'mm_scheduler': 'Uniform'})
check('a sampler with no schedule type in its name: as given', c({'sampler': 'Euler'}),
      {'mm_sampler': 'Euler', 'mm_scheduler': None})
check('a schedule type under `scheduler` shown as Forge lists it (#308)', c({'sampler': 'Euler a', 'scheduler': 'karras'}),
      {'mm_sampler': 'Euler a', 'mm_scheduler': 'Karras'})
check('`scheduler` wins over the sampler\'s name, which is still split', c({'sampler': 'Euler a Uniform', 'scheduler': 'simple'}),
      {'mm_sampler': 'Euler a', 'mm_scheduler': 'Simple'})
check('no data: nothing to show', [c({}), c(None)], [{'mm_sampler': None, 'mm_scheduler': None}] * 2)
images = [{'meta': {'sampler': 'euler_a_karras'}}, 'not an image', {'meta': None}]
send.forge_lists = lambda: (SAMPLERS, SCHEDULERS)
check('stamped on each image in place, beside its level', send.stamp_readings(images)[0],
      {'meta': {'sampler': 'euler_a_karras'}, 'mm_sampler': 'Euler a', 'mm_scheduler': 'Karras'})

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
