"""
The NSFW prompt model: an image rated PG or PG-13 whose prompt the model
reads as explicit is X, as one whose prompt uses a filter word is.

The words alone caught 81% of X/XXX prompts; the model, weighing every word,
pair of words, the other prompts and the resources, 94% at the setting's
default, on a library it had never seen. The
setting is a percentage - how much of PG/PG-13 it may raise - turned into a
score by the calibration the trainer measured. A model of made-up features
is used here, so every number can be written down; then the one that ships
is checked to load. The trainer is nsfw_trainer_test.py's.
"""
import gzip
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()
from model_manager import nsfw                            # noqa: E402

WORK = os.path.join(TESTS, 'work', 'nsfw_model')
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


SHIPPED = nsfw.PROMPT_MODEL_FILE
nsfw.PROMPT_WORDS_FILE = os.path.join(WORK, 'no_words.txt')   # the model alone
nsfw._bundled = None


def model_file(name, weights, bias=-1.0, calibration=((1, 2.5), (2, 1.5), (4, 0.5)), features=1):
    path = os.path.join(WORK, name)
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        json.dump({'format': 1, 'features': features, 'bits': 20, 'bias': bias,
                   'keys': [nsfw.feature_hash(k, 20) for k in weights],
                   'values': list(weights.values()), 'calibration': [list(c) for c in calibration]}, f)
    return path


def use(path):
    nsfw.PROMPT_MODEL_FILE = path
    nsfw._model_loaded = False


def image(prompt, level=1, negative=None):
    meta = {'prompt': prompt}
    if negative is not None:
        meta['negativePrompt'] = negative
    return {'browsingLevel': level, 'meta': meta}


# ------------------------------------------------------------- what it reads
check('1. the model reads words, pairs of adjacent words, and the negative prompt apart',
      sorted(nsfw.prompt_features('Blue sky, a zorp!', 'zorp')),
      ['a', 'a_zorp', 'blue', 'blue_sky', 'neg:zorp', 'sky', 'sky_a', 'zorp'])

use(model_file('made_up.json.gz', {'zorp': 3.0, 'neg:zorp': -5.0, 'blue_sky': 2.0}))
check('2. a prompt\'s score is the bias and the weights of what it holds',
      nsfw.prompt_score({'prompt': 'a zorp'}), 2.0)
check('   a word in the negative prompt counts as its own feature',
      nsfw.prompt_score({'prompt': 'a zorp', 'negativePrompt': 'zorp'}), -3.0)
check('   a model of the first feature set reads nothing else',
      nsfw.prompt_score({'prompt': 'a lighthouse', 'ADetailer prompt': 'zorp',
                         'civitaiResources': [{'modelVersionId': 7}]}), -1.0)

# ---------------------------------------------- the second feature set
# Every positive prompt - the image's own, ADetailer's, hires' - every
# negative one, and the resources the image names.
META = {'prompt': 'blue sky', 'negativePrompt': 'blurry', 'ADetailer prompt': 'a zorp',
        'ADetailer negative prompt': 'snib', 'Hires prompt': 'at dusk',
        'civitaiResources': [{'modelVersionId': 123}, {'type': 'lora'}],
        'resources': [{'hash': 'ABCDEF1234', 'name': 'x'}]}
check('7a. the second set reads ADetailer and hires prompts as more of the prompt',
      sorted(nsfw.image_features(META, 2)),
      ['a', 'a_zorp', 'at', 'at_dusk', 'blue', 'blue_sky', 'dusk', 'neg:blurry', 'neg:snib',
       'res:habcdef1234', 'res:v123', 'sky', 'zorp'])
check('    with word pairs within each prompt, never across two',
      'sky_a' in nsfw.image_features(META, 2), False)
check('    and the first set is still the prompt and negative alone',
      sorted(nsfw.image_features(META, 1)), ['blue', 'blue_sky', 'neg:blurry', 'sky'])

use(model_file('second.json.gz', {'res:v123': 4.0, 'zorp': 0.5}, features=2))
opts.model_manager_nsfw_prompt_model_percent = 2
check('    a resource can raise an image whose prompt says nothing',
      nsfw.image_level({'browsingLevel': 1, 'meta': {'prompt': 'a lighthouse',
                                                     'civitaiResources': [{'modelVersionId': 123}]}}),
      nsfw.X)
check('    but an image with no prompt of its own is left to its rating',
      nsfw.image_level({'browsingLevel': 1, 'meta': {'civitaiResources': [{'modelVersionId': 123}]}}),
      nsfw.PG)
use(model_file('made_up.json.gz', {'zorp': 3.0, 'neg:zorp': -5.0, 'blue_sky': 2.0}))

words = os.path.join(WORK, 'words.txt')
open(words, 'w').write('snib\n')
nsfw.PROMPT_WORDS_FILE, nsfw._bundled = words, None
opts.model_manager_nsfw_prompt_model_percent = 0
check('    and the words are looked for in ADetailer\'s prompt too',
      nsfw.image_level({'browsingLevel': 1, 'meta': {'prompt': 'a lighthouse', 'ADetailer prompt': 'snib'}}),
      nsfw.X)
nsfw.PROMPT_WORDS_FILE, nsfw._bundled = os.path.join(WORK, 'no_words.txt'), None

# ------------------------------------------------------------- the setting
for percent, want in ((2, 1.5), (3, 1.0), (0.5, 2.5), (10, 0.5), (0, None)):
    opts.model_manager_nsfw_prompt_model_percent = percent
    check('3. %s%% of PG/PG-13 is a score of %r, read off the calibration' % (percent, want),
          nsfw.prompt_model_threshold(), want)
opts.model_manager_nsfw_prompt_model_percent = 'not a number'
check('   a setting that is not a number is the default', nsfw.prompt_model_percent(), 2.0)

opts.model_manager_nsfw_prompt_model_percent = 2
check('4. a PG image whose prompt scores over the threshold is X',
      nsfw.image_level(image('a zorp')), nsfw.X)
check('   PG-13 too', nsfw.image_level(image('a zorp', level=2)), nsfw.X)
check('   one under it keeps its rating', nsfw.image_level(image('a lighthouse')), nsfw.PG)
check('   and the negative prompt can keep it there', nsfw.image_level(image('a zorp', negative='zorp')), nsfw.PG)
check('   an image already above PG-13 is left as rated', nsfw.image_level(image('a zorp', level=4)), nsfw.R)
opts.model_manager_nsfw_prompt_model_percent = 1
check('   a stricter setting raises less', nsfw.image_level(image('a zorp')), nsfw.PG)
opts.model_manager_nsfw_prompt_model_percent = 0
check('   0 turns the model off', nsfw.image_level(image('a zorp')), nsfw.PG)

# --------------------------------------------------- what makes a restamp
opts.model_manager_nsfw_prompt_model_percent = 2
first = nsfw.prompt_words_fingerprint()
opts.model_manager_nsfw_prompt_model_percent = 3
check('5. changing the setting changes the fingerprint, so stored images are judged again',
      nsfw.prompt_words_fingerprint() != first)
opts.model_manager_nsfw_prompt_model_percent = 2
use(model_file('other.json.gz', {'zorp': 4.0}))
check('   so does a new model', nsfw.prompt_words_fingerprint() != first)

# ------------------------------------------------- the model, or the words
# Settings -> NSFW detection: the trained model, or the word list alone. The
# model is right more often and wrong in ways nobody can point at; the choice
# is the user's.
opts.model_manager_nsfw_prompt_model_percent = 2
check('5b. the trained model is the default', (nsfw.detection(), nsfw.image_level(image('a zorp'))),
      ('model', nsfw.X))
with_model = nsfw.prompt_words_fingerprint()
opts.model_manager_nsfw_detection = 'words'
check('    with the word list chosen, the model judges nothing',
      (nsfw.detection(), nsfw.prompt_model_threshold(), nsfw.image_level(image('a zorp'))),
      ('words', None, nsfw.PG))
check('    and stored images are judged again', nsfw.prompt_words_fingerprint() != with_model)
open(words, 'w').write('zorp\n')
nsfw.PROMPT_WORDS_FILE, nsfw._bundled = words, None
check('    while the words still work', nsfw.image_level(image('a zorp')), nsfw.X)
nsfw.PROMPT_WORDS_FILE, nsfw._bundled = os.path.join(WORK, 'no_words.txt'), None
opts.model_manager_nsfw_detection = 'something else'
check('    a value it does not know is the model', nsfw.detection(), 'model')
opts.model_manager_nsfw_detection = 'model'

use(os.path.join(WORK, 'missing.json.gz'))
check('6. with no model file, the words still work and nothing fails',
      (nsfw.prompt_model(), nsfw.prompt_model_threshold(), nsfw.image_level(image('a zorp'))),
      (None, None, nsfw.PG))

# --------------------------------------------------------- the one that ships
use(SHIPPED)
model = nsfw.prompt_model()
check('7. the shipped model loads', model is not None)
if model:
    check('   with thousands of weights', len(model['weights']) > 1000)
    check('   and a calibration that covers the default',
          min(p for p, _ in model['calibration']) <= 2 <= max(p for p, _ in model['calibration']))
    check('   which says what it was measured at',
          any(m['percent'] == 2 for m in model['about']['measured_out_of_fold']))
    check('   and an everyday prompt is not raised',
          nsfw.image_level(image('a lighthouse on a cliff at dusk, masterpiece, best quality, detailed')),
          nsfw.PG)

nsfw.PROMPT_MODEL_FILE = SHIPPED
nsfw._model_loaded = False
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
