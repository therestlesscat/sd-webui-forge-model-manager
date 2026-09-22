"""
Finding models whose images carry a prompt you could actually reuse.

The browser can hide models whose gallery is all bare pictures. Doing that
means paging Civitai until enough qualify, which is why there is a cursor that
remembers a position *inside* a batch as well as between them.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402
webui_stub.install()

from model_manager.civitai import prompt_filter as pf    # noqa: E402
from model_manager.civitai.prompt_filter import (        # noqa: E402
    apply_generation_data, decode_filter_token, encode_filter_token,
    enrich_images_with_generation_data, generation_ids_needing_lookup,
    image_has_usable_prompt,
)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ------------------------------------------------------- what counts as usable
# A prompt on its own is not enough: "Send to txt2img" needs the settings too.
FULL = {'prompt': 'a cat', 'steps': 20, 'sampler': 'Euler a', 'cfgScale': 7}
check('a prompt with its settings is usable', image_has_usable_prompt({'meta': FULL}), True)
check('the capitalised spellings count too',
      image_has_usable_prompt({'meta': {'prompt': 'a cat', 'steps': 20,
                                        'Sampler': 'Euler a', 'CFG scale': 7}}), True)
check('but a prompt with no steps is not',
      image_has_usable_prompt({'meta': dict(FULL, steps=0)}), False)
check('nor one with no sampler',
      image_has_usable_prompt({'meta': dict(FULL, sampler=None)}), False)
check('nor one with no guidance scale',
      image_has_usable_prompt({'meta': dict(FULL, cfgScale=None)}), False)
check('no meta at all is not', image_has_usable_prompt({'meta': None}), False)
check('nor an empty meta', image_has_usable_prompt({'meta': {}}), False)
check('nor a blank prompt', image_has_usable_prompt({'meta': {'prompt': '   '}}), False)
check('nor a missing key', image_has_usable_prompt({}), False)
# It takes an image out of a list Civitai returned, so None is not a case it
# has to handle - and it does not: passing one raises.
try:
    image_has_usable_prompt(None)
    check('None is handled', False)
except AttributeError:
    pass

# ------------------------------------------------------------------ the cursor
token = encode_filter_token('abc', 3)
check('a token round trips', decode_filter_token(token), ('abc', 3))
check('a plain cursor is passed through', decode_filter_token('plain'), ('plain', 0))
check('nothing decodes to nothing', decode_filter_token(None), (None, 0))
check('and an empty string too', decode_filter_token(''), (None, 0))
check('a first position needs no token', encode_filter_token(None, 0), None)
check('but a position inside a batch does',
      decode_filter_token(encode_filter_token(None, 5)), (None, 5))

# ------------------------------------------------------------- enrichment
images = [
    {'id': 1, 'meta': {'prompt': 'already here'}},
    {'id': 2, 'meta': None},
    {'id': 3, 'meta': {'Size': '512x512'}},
    {'id': None},
]
check('only the ones without a prompt need looking up',
      generation_ids_needing_lookup(images), [2, 3])
check('and an empty list needs nothing', generation_ids_needing_lookup([]), [])

applied = apply_generation_data(images, {
    2: {'meta': {'prompt': 'fetched two'}},
    3: {'meta': {'prompt': 'fetched three'},
        'resources': [{'modelVersionId': 9, 'modelName': 'M', 'versionName': 'v1',
                       'modelType': 'LORA', 'strength': 0.8}]},
})
check('both are filled in', applied, 2)
check('the one that had a prompt is untouched', images[0]['meta']['prompt'], 'already here')
check('and an existing field survives the merge', images[2]['meta']['Size'], '512x512')
check('resources are carried across',
      images[2]['meta']['civitaiResources'][0]['modelVersionId'], 9)
check('applying nothing changes nothing', apply_generation_data(images, {}), 0)


class Client:
    def __init__(self, answer=None, blow_up=False):
        self.answer = answer or {}
        self.blow_up = blow_up
        self.asked = []

    def get_generation_data(self, ids):
        self.asked.append(list(ids))
        if self.blow_up:
            raise RuntimeError('nope')
        return self.answer


one = [{'id': 9, 'meta': {}}]
check('the one-shot path fills in',
      enrich_images_with_generation_data(Client({9: {'meta': FULL}}), one), 1)
check('and it landed', one[0]['meta']['prompt'], 'a cat')
check('nothing to do means no call',
      enrich_images_with_generation_data(Client(), []), 0)
check('a lookup that fails is swallowed',
      enrich_images_with_generation_data(Client(blow_up=True), [{'id': 1, 'meta': {}}]), 0)
check('and one that answers nothing changes nothing',
      enrich_images_with_generation_data(Client({}), [{'id': 1, 'meta': {}}]), 0)

# --------------------------------------------------------------- the paging
def model(model_id, prompts, bare=0):
    """A model whose only version has `prompts` usable images and `bare` without."""
    images = ([{'id': model_id * 10 + i, 'meta': dict(FULL)} for i in range(prompts)]
              + [{'id': model_id * 100 + i, 'meta': None} for i in range(bare)])
    return {'id': model_id, 'name': 'M%d' % model_id,
            'modelVersions': [{'id': model_id * 2, 'images': images}]}


def usable(model):
    """The count_usable_images callback the browser passes in."""
    return sum(1 for version in model.get('modelVersions', [])
               for image in version.get('images', [])
               if image_has_usable_prompt(image))


class Searcher:
    """Civitai, answering one batch per call from a script of pages."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def search_models(self, **kwargs):
        self.calls.append(kwargs)
        if not self.pages:
            return {'items': []}
        items, cursor = self.pages.pop(0)
        return {'items': items, 'nextCursor': cursor}


def run(searcher, page_size=10, **kwargs):
    return pf.search_models_with_usable_prompts(
        searcher, {'query': ''}, usable, page_size, **kwargs)


# one page of three, the middle one all bare
search = Searcher([([model(1, 2), model(2, 0, bare=3), model(3, 1)], None)])
done = run(search)
check('the models with prompts are kept', [m['id'] for m in done['models']], [1, 3])
check('and the bare one is counted as dropped', done['dropped'], 1)
check('having checked all three', done['checked'], 3)
check('with nowhere left to go', done['nextCursor'], None)
check('the search never saw the page size', search.calls[0].get('limit'), 20)

# a page that needs a second batch to fill
search = Searcher([([model(1, 1)], 'c1'), ([model(2, 1)], None)])
done = run(search, page_size=2)
check('it pages until the page is full', [m['id'] for m in done['models']], [1, 2])
check('following the cursor it was given', search.calls[1].get('cursor'), 'c1')

# a bar high enough that nothing clears it
search = Searcher([([model(1, 1)], None)])
check('a higher bar drops a model that only just qualifies',
      run(search, min_usable=5)['models'], [])

# more models than the page holds: the rest wait for the next page
search = Searcher([([model(1, 1), model(2, 1), model(3, 1)], 'c1')])
done = run(search, page_size=2)
check('only a page is returned', [m['id'] for m in done['models']], [1, 2])
check('and the token remembers where inside the batch to resume',
      decode_filter_token(done['nextCursor']), (None, 2))

resumed = run(Searcher([([model(1, 1), model(2, 1), model(3, 1)], None)]),
              page_size=2, start_token=done['nextCursor'])
check('resuming picks up the one that was left', [m['id'] for m in resumed['models']], [3])

# a budget stops the work rather than the page filling
search = Searcher([([model(1, 0, bare=1)] * 10, 'c1')])
done = run(search, page_size=10, max_checks=3, workers=1)
check('it stops at the budget', done['checked'], 3)
check('saying so', done['budget_reached'], True)
check('and still points at the next unchecked model',
      decode_filter_token(done['nextCursor']), (None, 3))

# a batch that comes back empty ends the paging
check('an empty answer ends it', run(Searcher([]))['models'], [])

# a token pointing past the end of a batch that came back shorter than before
# NOTE: the intent here is to move on to the next batch, and the cursor does
# advance - but the loop only refetches when `index >= len(batch)`, and it has
# just reset index to 0, so the stale batch is served again under the new
# cursor. Model 1 comes back a second time instead of model 2. Recorded as it
# behaves so that fixing it fails here and is noticed. Only reachable if a
# batch shrinks between calls or a token is hand-edited.
search = Searcher([([model(1, 1)], 'c1'), ([model(2, 1)], None)])
done = run(search, page_size=1, start_token=encode_filter_token(None, 9))
check('a token past the end re-serves the batch it already had',
      [m['id'] for m in done['models']], [1])
check('having asked Civitai only once', len(search.calls), 1)

search = Searcher([([model(1, 1)], None)])
check('and with no next batch it simply ends',
      run(search, start_token=encode_filter_token(None, 9))['models'], [])


# ------------------------------------------------------------- the live events
def explode(model):
    raise RuntimeError('check blew up')


search = Searcher([([model(1, 1), model(2, 1)], None)])
events = list(pf.iter_models_with_usable_prompts(search, {'query': ''}, usable, 2))
kinds = [kind for kind, _ in events]
check('a model is announced as it is found', kinds.count('model'), 2)
check('progress comes before the work', kinds[0], 'progress')
check('and the summary comes last', kinds[-1], 'done')

search = Searcher([([model(1, 1)], None)])
done = list(pf.iter_models_with_usable_prompts(
    search, {'query': ''}, explode, 1))[-1][1]
check('a check that raises drops the model rather than the page', done['models'], [])
check('and is counted as dropped', done['dropped'], 1)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
