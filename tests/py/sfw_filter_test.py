"""
"Only Show Models with SFW images": leaving out models whose examples show otherwise.

Civitai's own NSFW switch leaves out the models it rates NSFW and strips the
mature images from the rest - but most of what it still lists has NSFW images
in its gallery. This check looks at each model's first 20 images itself and
leaves the model out if any is above PG-13, or not rated at all - or if it
has no images, since then nothing shows it is safe.

Most Civitai models fail it, so it makes more requests than anything else in
the browser. What is held in place here is how few: one /images request per
model at most, none for one already decided, none for the generation data
of a model it rules out, one set of lookups for a whole chunk of models - and
a 429 stops the page, where it can be resumed, instead of waiting out
Retry-After with nothing on screen.
"""
import os
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

from model_manager.api import prompts                    # noqa: E402
from model_manager.api.prompts import has_nsfw_image, inspect_model, inspect_models  # noqa: E402
from model_manager.civitai import CivitaiClient, CivitaiRateLimitError  # noqa: E402
from model_manager.civitai import client as client_module             # noqa: E402
from model_manager.civitai import prompt_filter as pf                  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


USABLE = {'prompt': 'a cat on a mat', 'steps': 20, 'sampler': 'Euler a', 'cfgScale': 7}


def img(level, meta=None):
    return {'id': level * 1000 + len(str(meta)), 'browsingLevel': level, 'meta': meta}


# ------------------------------------------------------------ what counts
check('PG and PG-13 are safe', has_nsfw_image([img(1), img(2), img(3)]), False)
check('one R image is enough', has_nsfw_image([img(1)] * 19 + [img(4)]), True)
check('as is X, XXX or Blocked',
      [has_nsfw_image([img(n)]) for n in (8, 16, 32)], [True, True, True])
check('an image nobody rated is not known to be safe', has_nsfw_image([{'id': 1}]), True)
check('the old names read the same way: Soft is safe, Mature is not',
      (has_nsfw_image([{'nsfwLevel': 'Soft'}]), has_nsfw_image([{'nsfwLevel': 'Mature'}])),
      (False, True))
# It answers "is any of these NSFW" and nothing more; what having no images
# means is decided by inspect_model(), below.
check('no images, none of them NSFW', has_nsfw_image([]), False)


# ------------------------------------------------------------ one model
class Civitai:
    """Answers /images and generation data, and counts what it was asked."""

    def __init__(self, galleries, generation=None, rate_limited=False, lookup_fails=None):
        self.galleries = galleries          # version id -> images
        self.generation = generation or {}
        self.rate_limited = rate_limited
        self.lookup_fails = lookup_fails    # an exception every lookup batch fails with
        self.images_asked = []
        self.generation_asked = []

    def get_model_images(self, version_id, cursor=None, limit=None):
        if self.rate_limited:
            raise CivitaiRateLimitError(60)
        self.images_asked.append(version_id)
        return {'images': [dict(i) for i in self.galleries.get(version_id, [])],
                'next_cursor': None}

    def get_generation_data(self, ids, workers=1, errors=None):
        self.generation_asked.append(list(ids))
        if self.lookup_fails is not None:
            # as the client does: a failed batch is logged, and named in errors
            if errors is not None:
                errors.update((i, self.lookup_fails) for i in ids)
            return {}
        return {i: {'meta': dict(USABLE)} for i in ids if i in self.generation}


def model(version_id):
    return {'id': version_id // 10, 'modelVersions': [{'id': version_id}]}


def sfw(civitai, version_id, **kw):
    return inspect_model(civitai, model(version_id), want_prompts=False, want_sfw=True, **kw)


prompts.forget_sfw_verdicts()
civitai = Civitai({10: [img(1), img(2)], 20: [img(1), img(4)], 30: []})
check('a model whose first images are all safe is kept', sfw(civitai, 10), None)
check('one with an R image among them is left out', sfw(civitai, 20), 'nsfw')
check('one with no images at all is left out: nothing shows it is safe',
      sfw(civitai, 30), 'nsfw')
check('as is one with no version to look at',
      inspect_model(civitai, {'id': 1, 'modelVersions': []},
                    want_prompts=False, want_sfw=True), 'nsfw')
check('each costing one /images request', civitai.images_asked, [10, 20, 30])
check('and no generation data - the SFW check needs none', civitai.generation_asked, [])

civitai.images_asked = []
check('asked again, the answers are the same',
      [sfw(civitai, 10), sfw(civitai, 20)], [None, 'nsfw'])
check('and cost nothing: pass or fail, the verdict is remembered', civitai.images_asked, [])

prompts.forget_sfw_verdicts()
old = prompts.SFW_VERDICT_TTL_SECONDS
prompts.SFW_VERDICT_TTL_SECONDS = -1
civitai = Civitai({50: [img(1)]})
sfw(civitai, 50)
sfw(civitai, 50)
check('a verdict older than its lifetime is asked again', civitai.images_asked, [50, 50])
prompts.SFW_VERDICT_TTL_SECONDS = old

# Both checks on: one request serves both, and SFW goes first.
prompts.forget_sfw_verdicts()
civitai = Civitai({60: [img(1, None), img(4, None)],
                   70: [img(1, None), img(2, None)]},
                  generation={1000 + len('None'): True, 2000 + len('None'): True})
both = dict(want_prompts=True, want_sfw=True, min_usable=1)
check('with both on, the SFW check rules a model out first',
      inspect_model(civitai, model(60), **both), 'nsfw')
check('before any generation data is looked up for it', civitai.generation_asked, [])
check('a model that passes it goes on to the prompt check',
      inspect_model(civitai, model(70), **both), None)
check('which reuses the images the SFW check fetched: one request per model',
      civitai.images_asked, [60, 70])
check('fills in their generation data', len(civitai.generation_asked), 1)

# Nothing is kept of the images: the prompt check asks again each time. It
# used to read a cache of them - every cached image, not the first 20, so a
# model someone had paged through could pass on images no fresh check sees.
civitai.images_asked, civitai.generation_asked = [], []
inspect_model(civitai, model(70), **both)
check('a model checked again is fetched again, its SFW verdict still remembered',
      (civitai.images_asked, len(civitai.generation_asked)), ([70], 1))


# A chunk of models at once: their lookups pooled into one.
def gallery(base, levels, prompted):
    return [{'id': base + n, 'browsingLevel': level, 'meta': None}
            for n, level in enumerate(levels)], {base + n: True for n in prompted}


prompts.forget_sfw_verdicts()
g1, p1 = gallery(100, [1, 1], [0])        # safe, one prompt
g2, p2 = gallery(200, [1, 8], [0, 1])     # an X image
g3, p3 = gallery(300, [1, 1], [])         # safe, no prompts
g4, p4 = gallery(400, [2], [0])           # safe, one prompt
civitai = Civitai({101: g1, 201: g2, 301: g3, 401: g4}, generation={**p1, **p2, **p3, **p4})
chunk = [model(101), model(201), model(301), model(401), {'id': 5, 'modelVersions': []}]
check('a chunk is answered model by model, in order',
      inspect_models(civitai, chunk, **both), [None, 'nsfw', 'prompt', None, 'nsfw'])
check('with one /images request each for those with a version',
      sorted(civitai.images_asked), [101, 201, 301, 401])
check('and one lookup for all their images, less those the SFW check ruled out',
      [sorted(ids) for ids in civitai.generation_asked], [[100, 101, 300, 301, 400]])

# A lookup that fails says nothing about a model's prompts. It used to be
# swallowed, and the model dropped as promptless.
prompts.forget_sfw_verdicts()
civitai = Civitai({101: g1, 301: g3}, generation={**p1, **p3}, lookup_fails=RuntimeError('500'))
check('a model whose prompts could not be looked up has failed, not been found promptless',
      inspect_models(civitai, [model(101), model(301)], want_prompts=True, want_sfw=False),
      ['failed', 'failed'])
civitai = Civitai({101: g1}, generation=p1, lookup_fails=CivitaiRateLimitError(60))
check('and one Civitai refused to look up is rate-limited, so the page stops at it',
      inspect_models(civitai, [model(101)], want_prompts=True, want_sfw=False),
      [pf.RATE_LIMITED])

prompts.forget_sfw_verdicts()
civitai = Civitai({80: [img(1)]}, rate_limited=True)
try:
    sfw(civitai, 80)
    check('a 429 reaches the filter loop', False)
except CivitaiRateLimitError:
    pass
check('and nothing is remembered about a model that was never looked at',
      prompts._remembered_sfw(80), None)


# ------------------------------------------------------------ the loop
class Searcher:
    """Civitai, answering one batch per call from a script of pages."""

    def __init__(self, pages, rate_limited_after=None):
        self.pages = list(pages)
        self.calls = 0
        self.rate_limited_after = rate_limited_after

    def search_models(self, **kwargs):
        if self.rate_limited_after is not None and self.calls >= self.rate_limited_after:
            raise CivitaiRateLimitError(60)
        self.calls += 1
        if not self.pages:
            return {'items': []}
        items, cursor = self.pages.pop(0)
        return {'items': items, 'nextCursor': cursor}


def m(model_id):
    return {'id': model_id}


def verdicts(table):
    """An inspect() answering from a table: id -> None, a reason, or an exception."""
    def inspect(model):
        answer = table[model['id']]
        if isinstance(answer, Exception):
            raise answer
        return answer
    return inspect


def run(searcher, page_size, inspect, **kwargs):
    return pf.search_models_with_usable_prompts(
        searcher, {'query': ''}, None, page_size, inspect=inspect, workers=1, **kwargs)


done = run(Searcher([([m(1), m(2), m(3), m(4)], None)]), 10,
           verdicts({1: 'nsfw', 2: None, 3: 'prompt', 4: 'nsfw'}))
check('the loop keeps what inspect keeps', [x['id'] for x in done['models']], [2])
check('counting each reason on its own', (done['unsafe'], done['dropped']), (2, 1))
check('and every model it looked at as a check', done['checked'], 4)

done = run(Searcher([([m(1), m(2)], None)]), 10,
           verdicts({1: RuntimeError('boom'), 2: None}))
check('a check that fails is counted as failed, not as NSFW',
      (done['failed'], done['unsafe'], done['dropped']), (1, 0, 0))

# A 429 on a check: the page stops, and resumes at that model.
done = run(Searcher([([m(1), m(2), m(3)], 'next')]), 10,
           verdicts({1: None, 2: CivitaiRateLimitError(60), 3: None}))
check('a 429 stops the page', [x['id'] for x in done['models']], [1])
check('saying so', (done['rate_limited'], done['budget_reached']), (True, True))
check('and the token points at the model that was not checked',
      pf.decode_filter_token(done['nextCursor']), (None, 1))
check('which is not counted as anything',
      (done['unsafe'], done['dropped'], done['failed']), (0, 0, 0))

# A chunk inspector: handed the chunk, less what accept() rules out.
handed = []
def chunk_verdicts(table):
    def inspect_many(models):
        handed.append([x['id'] for x in models])
        return [table[x['id']] for x in models]
    return inspect_many


done = pf.search_models_with_usable_prompts(
    Searcher([([m(1), m(2), m(3), m(4), m(5)], 'next')]), {'query': ''}, None, 10,
    inspect_many=chunk_verdicts({1: None, 2: 'nsfw', 4: pf.RATE_LIMITED, 5: None}),
    accept=lambda x: x['id'] != 3, workers=8)
check('a chunk inspector is handed the models together, less what accept() rules out',
      handed, [[1, 2, 4, 5]])
check('keeping what it keeps, until a model Civitai refused',
      [[x['id'] for x in done['models']], done['unsafe'], done['rejected'], done['rate_limited']],
      [[1], 1, 1, True])
check('which the page resumes at', pf.decode_filter_token(done['nextCursor']), (None, 3))

# A 429 on a search: the same, at the batch it could not fetch.
done = run(Searcher([([m(1)], 'b2'), ([m(2)], None)], rate_limited_after=1), 10,
           verdicts({1: None, 2: None}))
check('a 429 on a search stops the page too',
      ([x['id'] for x in done['models']], done['rate_limited']), ([1], True))
check('resuming at the batch it could not fetch',
      pf.decode_filter_token(done['nextCursor']), ('b2', 0))


# ------------------------------------------------------------ the client
# A filter turns waiting off, so a 429 is raised at once instead of slept on.
class Response:
    status_code = 429
    headers = {'Retry-After': '60'}


slept = []
real_sleep = client_module.time.sleep
client_module.time.sleep = lambda s: slept.append(s)
try:
    client = CivitaiClient(api_key='k')
    client.session.request = lambda *a, **k: Response()
    client.wait_on_rate_limit = False
    try:
        client.search_models(query='x')
        check('a 429 is raised', False)
    except CivitaiRateLimitError:
        pass
    check('without sleeping first', slept, [])

    client = CivitaiClient(api_key='k')
    client.session.request = lambda *a, **k: Response()
    try:
        client.search_models(query='x')
    except CivitaiRateLimitError:
        pass
    check('while everything else still waits it out, as before', slept, [60, 60, 60])
finally:
    client_module.time.sleep = real_sleep

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
