"""
How an image's and a generation's settings are read for their settings rows
(#378): a Civitai record by Send's own reading of it, a generation by its
settings line - read alike in either WebUI - else what Sync images read from
its file name. A value is typed as its column holds it, and nothing is
filled in that the image does not give.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

from model_manager.db import params_table as pt          # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def col(row, key):
    """One column of a row; None where there is no row, so a break fails a check rather than the suite."""
    return (row or {}).get(key)


def none_but(row, **given):
    """The row's values, every column not named None."""
    return {k: v for k, v in (row or {}).items() if v is not None} == given


# ------------------------------------------------------------- a Civitai record
full = {'meta': {'sampler': 'DPM++ 2M Karras', 'Schedule type': 'Karras', 'scheduler': 'karras', 'steps': 30,
                 'cfgScale': 7, 'Distilled CFG Scale': '3.5', 'seed': 0, 'Size': '832x1216', 'clipSkip': 2,
                 'Hires upscale': '1.5', 'Hires steps': '12', 'Hires upscaler': '4x-UltraSharp',
                 'Denoising strength': 0.4},
        'width': 1664, 'height': 2432}
row = pt.image_params_row(full)
check('a record: every column from its field, numbers as numbers, the seed 0 kept',
      row, {'sampler': 'DPM++ 2M Karras', 'schedule_type': 'Karras', 'scheduler': 'karras', 'steps': 30, 'cfg': 7,
            'distilled_cfg': 3.5, 'shift': None, 'seed': 0, 'width': 832, 'height': 1216, 'clip_skip': 2,
            'hires_upscale': 1.5, 'hires_steps': 12, 'hires_upscaler': '4x-UltraSharp', 'denoise': 0.4})
check('    the sampler kept as written, not split', col(row, 'sampler'), 'DPM++ 2M Karras')
check('    the size is the settings\', not the picture\'s', (col(row, 'width'), col(row, 'height')), (832, 1216))
check('every column of image_params, and none other', sorted(row or {}), sorted(pt.IMAGE_COLUMNS))

check('a size given as width and height, no Size',
      none_but(pt.image_params_row({'meta': {'steps': 20, 'width': 512, 'height': 768}, 'width': 1, 'height': 1}),
               steps=20, width=512, height=768))
check('a record giving no setting: no row', pt.image_params_row({'meta': {'prompt': 'a cat'}}), None)
check('    no meta at all: no row', pt.image_params_row({'meta': None}), None)
check('    not a record: no row', pt.image_params_row(None), None)

check('text that reads as a number is the number; 7 and 7.0 are one value',
      [col(pt.image_params_row({'meta': {'cfgScale': v}}), 'cfg') for v in ('7', '7.0', 7, 7.0)], [7.0, 7.0, 7, 7.0])
check('    and compare equal, so a count holds them as one', len({7.0, 7}), 1)
check('a whole count written 20.0 is 20', col(pt.image_params_row({'meta': {'steps': 20.0}}), 'steps'), 20)
check('a value that is neither text nor a number is no value: a list, an object, a yes or no',
      none_but(pt.image_params_row({'meta': {'steps': [20], 'cfgScale': {'v': 7}, 'sampler': ['Euler'],
                                             'seed': True, 'Hires upscaler': 4, 'Denoising strength': 'high'}})),
      )
check('a steps or CFG of 0 is not recorded, as Send\'s paste writes none',
      pt.image_params_row({'meta': {'steps': 0, 'cfgScale': '0', 'seed': 5}}),
      {**{k: None for k in pt.IMAGE_COLUMNS}, 'seed': 5})
check('nothing is filled in: an image giving its sampler alone has only its sampler',
      none_but(pt.image_params_row({'meta': {'sampler': 'Euler a'}}), sampler='Euler a'))

line_in_negative = {'meta': {'prompt': 'a cat',
                             'negativePrompt': 'blurry\nSteps: 25, Sampler: Euler a, CFG scale: 6, Seed: 42, Size: 512x512'}}
check('a settings line kept in the negative prompt (#313) is read in, by Send\'s own reading',
      none_but(pt.image_params_row(line_in_negative), sampler='Euler a', steps=25, cfg=6, seed=42, width=512,
               height=512))
check('    the record itself is not changed', 'Steps:' in line_in_negative['meta']['negativePrompt'])
check('    the same data Send pastes from', pt.record_meta(line_in_negative)['steps'], '25')

check('Distilled CFG Scale and Shift each in a column of its own',
      [(col(r, 'distilled_cfg'), col(r, 'shift')) for r in map(pt.image_params_row, (
          {'meta': {'Distilled CFG Scale': 3.5}}, {'meta': {'Shift': 3}}, {'meta': {'shift': '5'}}))],
      [(3.5, None), (None, 3), (None, 5.0)])
check('    Civitai\'s lowercase shift only where Shift is not given',
      col(pt.image_params_row({'meta': {'Shift': 3, 'shift': 9}}), 'shift'), 3)
check('the clip skip by Send\'s own keys (#318)',
      [col(pt.image_params_row({'meta': m}), 'clip_skip') for m in ({'clipSkip': 2}, {'Clip skip': '3'}, {'CLIP Skip': 1})],
      [2, 3, 1])

# ------------------------------------------------------------ a generation
LINE = ('a cat\nNegative prompt: blurry\nSteps: 20, Sampler: DPM++ 2M, Schedule type: Karras, CFG scale: 7, '
        'Distilled CFG Scale: 3.5, Seed: 123, Size: 832x1216, Model hash: abc, Clip skip: 2, '
        'Hires upscale: 1.5, Hires steps: 10, Hires upscaler: "4x-UltraSharp", Denoising strength: 0.4')
row = pt.generation_params_row(LINE)
check('a generation\'s settings line: every column, a quoted value unquoted',
      row, {'sampler': 'DPM++ 2M', 'schedule_type': 'Karras', 'steps': 20, 'cfg': 7.0, 'distilled_cfg': 3.5,
            'shift': None, 'width': 832, 'height': 1216, 'clip_skip': 2, 'hires_upscale': 1.5, 'hires_steps': 10,
            'hires_upscaler': '4x-UltraSharp', 'denoise': 0.4})
check('    every column of generation_params, and none other: no scheduler, no seed',
      sorted(row or {}), sorted(pt.GENERATION_COLUMNS))
check('Neo\'s Shift, in its own column',
      none_but(pt.generation_params_row('x\nSteps: 9, Sampler: Euler, Schedule type: Simple, CFG scale: 1, Shift: 3'),
               sampler='Euler', schedule_type='Simple', steps=9, cfg=1.0, shift=3.0))
check('a size written as its two halves (#313)',
      none_but(pt.generation_params_row('x\nSteps: 9, Size-1: 640, Size-2: 960'), steps=9, width=640, height=960))

NAME = {'Model': 'a_model', 'Sampler': 'Euler a', 'Steps': '28', 'CFG scale': '5', 'Clip skip': '2', 'Size': '512x768'}
check('no text: what Sync images read from the file name, under the line\'s own names',
      none_but(pt.generation_params_row(None, NAME), sampler='Euler a', steps=28, cfg=5.0, clip_skip=2, width=512,
               height=768))
check('    an empty text, the same', pt.generation_params_row('', NAME), pt.generation_params_row(None, NAME))
check('    a text without a settings line, the same',
      pt.generation_params_row('just a prompt', NAME), pt.generation_params_row(None, NAME))
check('    a settings line wins over the file name',
      col(pt.generation_params_row('x\nSteps: 40, Sampler: Euler, CFG scale: 3', NAME), 'steps'), 40)
check('neither: no row', pt.generation_params_row('just a prompt', None), None)

# The original Forge's pattern, in either WebUI: a row reads the same
# whichever of two WebUIs sharing a database wrote it. Neo's own pattern
# (Neo's infotext_utils.py `re_param`) reads these lines' fields alike.
NEO = re.compile(r'\s*([\w\s\-\/]+):\s*("(?:\\.|[^\\"])+"|[^,]*)(?:,|$)')
from model_manager.image_text import line_params         # noqa: E402
from model_manager import forge_host                     # noqa: E402
for text in (LINE, 'x\nSteps: 9, Sampler: Euler a, Schedule type: Automatic, CFG scale: 4.5, Shift: 3',
             'x\nSampler: "DPM++ 2M", Steps: 30, CFG scale: 6, Lora hashes: "a: 1, b: 2"'):
    keys = ('Sampler', 'Schedule type', 'Steps', 'CFG scale')
    neo, fixed = line_params(text, NEO), line_params(text, forge_host.fixed_line_pattern())
    check('the four fields read alike under Neo\'s pattern and the original Forge\'s: ' + text[2:30],
          [neo.get(k) for k in keys], [fixed.get(k) for k in keys])
check('the row reads its line with the original Forge\'s pattern, whatever the WebUI\'s own',
      forge_host.fixed_line_pattern().pattern, forge_host._PARAM_LINE)
# image_text took Forge's pattern by name: its copy is the one to stand in for.
from model_manager import image_text                     # noqa: E402
own = image_text.infotext_line_pattern
image_text.infotext_line_pattern = lambda: re.compile(r'(?!)(x)(y)')      # this WebUI's, reading nothing
try:
    check('    a WebUI whose own pattern reads the line otherwise gets the same row',
          pt.generation_params_row(LINE), row)
finally:
    image_text.infotext_line_pattern = own

print('\n'.join('FAIL ' + f for f in fails) if fails else 'All checks passed.')
sys.exit(1 if fails else 0)
