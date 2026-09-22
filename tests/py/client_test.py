"""
The Civitai client: its rate limiter, its retries, and how it batches.

Nothing here touches the network. `_request` is the single door to the outside,
so a stub in front of it lets every endpoint method be driven - including the
paths that only happen when Civitai says no.
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

from model_manager.civitai import (                      # noqa: E402
    CivitaiClient, CivitaiAPIError, CivitaiNotFoundError,
    CivitaiRateLimitError, TokenBucketRateLimiter,
)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# --------------------------------------------------------------- the bucket
bucket = TokenBucketRateLimiter(100.0, 2)
check('a full bucket hands one over', bucket.acquire(timeout=1.0), True)
check('and another', bucket.acquire(timeout=1.0), True)
check('nothing to wait for when it is full', TokenBucketRateLimiter(100.0, 5).wait_time(), 0.0)

slow = TokenBucketRateLimiter(0.5, 1)
check('the one token is available', slow.acquire(timeout=1.0), True)
started = time.time()
check('and the next one is refused rather than waited for forever',
      slow.acquire(timeout=0.2), False)
check('having waited about as long as it was told',
      0.1 <= time.time() - started <= 1.5, True)
check('and it can say how long the wait would be', slow.wait_time() > 0, True)


# ------------------------------------------------------------- a stub Civitai
class Stub(CivitaiClient):
    """Answers whatever the test put in `replies`, and records the asking."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.asked = []
        self.api_key = 'a-key'
        self.rate_limiter = TokenBucketRateLimiter(1000.0, 100)

    def _request(self, method, endpoint, params=None, absolute_url=None):
        self.asked.append((endpoint or absolute_url, params or {}))
        if not self.replies:
            return {}
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


# ------------------------------------------------------------ one at a time
c = Stub([{'id': 5, 'modelId': 9, 'name': 'v1'}])
check('a hash lookup answers', c.get_model_by_hash('A' * 64)['id'], 5)
check('and asks the by-hash endpoint', 'by-hash' in c.asked[0][0], True)

c = Stub([CivitaiNotFoundError('nope')])
check('a hash Civitai does not know is None', c.get_model_by_hash('B' * 64), None)

c = Stub([{'id': 9, 'name': 'A Model'}])
check('a model fetch answers', c.get_model(9)['name'], 'A Model')
c = Stub([CivitaiNotFoundError('nope')])
check('a model that is gone is None', c.get_model(9), None)

# ------------------------------------------------------------------ batching
c = Stub([{'items': [{'id': i, 'name': 'm%d' % i} for i in range(1, 101)]},
          {'items': [{'id': i, 'name': 'm%d' % i} for i in range(101, 151)]}])
got = c.get_models_by_ids(list(range(1, 151)))
check('150 ids take two requests', len(c.asked), 2)
check('the first asks for a hundred', len(c.asked[0][1]['ids'].split(',')), 100)
check('and the second for the rest', len(c.asked[1][1]['ids'].split(',')), 50)
check('and every id comes back keyed', len(got), 150)

c = Stub()
check('no ids, no request', c.get_models_by_ids([]), {})
check('and nothing was asked', c.asked, [])

c = Stub([{'items': [{'id': 3}]}])
c.get_models_by_ids([3, 3, 3, None, 0])
check('duplicates and blanks are dropped', c.asked[0][1]['ids'], '3')

# --------------------------------------------------- trained or merged, inferred
c = Stub([{'items': [{'id': 1}, {'id': 2}]}, {'items': [{'id': 3}]}])
check('the two queries answer', c.get_checkpoint_types([1, 2, 3, 4]),
      {1: 'Trained', 2: 'Trained', 3: 'Merge'})
check('asking for each type once', len(c.asked), 2)
check('naming them', [a[1]['checkpointType'] for a in c.asked], ['Trained', 'Merge'])

c = Stub([{'items': [{'id': 99}]}, {'items': []}])
check('an answer about something else is discarded', c.get_checkpoint_types([1, 2]), {})

c = Stub([CivitaiAPIError('server said no'), {'items': []}])
check('a failure yields nothing rather than raising', c.get_checkpoint_types([1, 2]), {})

# ------------------------------------------------------------------ searching
c = Stub([{'items': [{'id': 1}], 'metadata': {'nextCursor': 'abc'}}])
# `types` is a list; handing it a string would join it character by
# character, which is worth knowing but is not what any caller does.
result = c.search_models(query='thing', types=['Checkpoint'], limit=10)
check('a search answers', len(result.get('items', [])), 1)
check('passing the query on', c.asked[0][1].get('query'), 'thing')
check('and the type', c.asked[0][1].get('types'), 'Checkpoint')

c = Stub([{'items': []}])
c.search_models(checkpoint_type='Trained', nsfw='true', sort='Newest')
check('and every filter it is given',
      (c.asked[0][1].get('checkpointType'), c.asked[0][1].get('sort')),
      ('Trained', 'Newest'))

c = Stub([{'items': [{'name': 'anime'}, {'name': 'realistic'}]}])
check('tags answer', len(c.search_tags('an')), 2)

c = Stub([{'types': ['Checkpoint', 'LORA'], 'baseModels': ['SDXL 1.0']}])
enums = c.get_enums()
check('the enums come back', bool(enums), True)

# -------------------------------------------------------------------- images
c = Stub([{'items': [{'id': 1, 'url': 'u'}], 'metadata': {'nextCursor': 'next'}}])
images = c.get_model_images(4242, cursor=None, limit=100)
check('images answer', len(images.get('images', [])), 1)
check('with a cursor for the next page', images.get('next_cursor'), 'next')
check('asked by version', c.asked[0][1].get('modelVersionId'), 4242)

# ------------------------------------------------------- generation data (tRPC)
BATCH = [{'result': {'data': {'json': {'meta': {'prompt': 'p1'}}}}},
         {'result': {'data': {'json': {'meta': {'prompt': 'p2'}}}}}]
c = Stub([BATCH])
got = c.get_generation_data([11, 22])
check('two ids come back', len(got), 2)
check('with their prompts', got[11]['meta']['prompt'], 'p1')
check('in one batched request', len(c.asked), 1)

MIXED = [{'error': {'message': 'gone'}},
         {'result': {'data': {'json': {'meta': {}}}}}]
c = Stub([MIXED])
got = c.get_generation_data([11, 22])
check('the entry that errored is skipped', 11 in got, False)
check('and the one beside it is kept', 22 in got, True)

c = Stub([{'not': 'a list'}])
check('an unexpected shape yields nothing', c.get_generation_data([1]), {})

c = Stub()
c.api_key = None
check('without a key it does not even ask', c.get_generation_data([1, 2]), {})
check('and made no request', c.asked, [])

# ------------------------------------------------------------ from settings
webui_stub.install(model_manager_civitai_api_key='  spaced-key  ',
                   model_manager_civitai_requests_per_second=3)
configured = CivitaiClient.from_settings()
check('the key is read and trimmed', configured.api_key, 'spaced-key')
check('and the rate honoured', configured.rate_limiter.tokens_per_second, 3.0)
configured.close()

webui_stub.install(model_manager_civitai_api_key='')
anonymous = CivitaiClient.from_settings()
check('no key means no key', anonymous.api_key, None)
check('and the slower anonymous rate',
      anonymous.rate_limiter.tokens_per_second, CivitaiClient.UNAUTH_RATE)
anonymous.close()
webui_stub.install()

# a rate outside what the API will take is brought back into range
webui_stub.install(model_manager_civitai_api_key='k',
                   model_manager_civitai_requests_per_second=999)
clamped = CivitaiClient.from_settings()
check('an absurd rate is clamped', clamped.rate_limiter.tokens_per_second <= 10.0, True)
clamped.close()
webui_stub.install()

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
