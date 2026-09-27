"""
The Civitai pull for the NSFW model: paced to stay just under Civitai's limit.

tools/train_nsfw_from_civitai.py fetches with many workers at a rate that
climbs until Civitai answers "too many requests", then backs off. The client
it replaces requests for gave a throttled request up after three tries, and
its prompt lookup dropped a failed batch without a word - images stored with
no prompt. A real 429 is not something to provoke on purpose, so a fake
session plays Civitai here.
"""
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS, os.path.join(ROOT, 'tools')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()
import train_nsfw_from_civitai as pull                    # noqa: E402
from model_manager.civitai import CivitaiClient           # noqa: E402
from model_manager.civitai.client import CivitaiNotFoundError  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


class Response:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError('HTTP %d' % self.status_code)


class Session:
    """Answers in turn from `script`, then with `then` for ever."""
    def __init__(self, script, then):
        self.script, self.then, self.asked = list(script), then, []
        self.headers = {}

    def request(self, method, url, params=None, timeout=None):
        self.asked.append(url)
        return self.script.pop(0) if self.script else self.then


pull.time = types.SimpleNamespace(time=time.time, sleep=lambda s: None)   # no real waits


def client_with(script, then, limiter):
    client = CivitaiClient('key')
    client.session = Session(script, then)
    pull.adaptive_requests(client, limiter)
    return client


# ------------------------------------------------------------ the pacing
check('1. the backoff is Civitai\'s advice: 1 s, doubling, capped at 30',
      [pull.backoff(n) for n in (1, 2, 3, 5, 6, 9)], [1, 2, 4, 16, 30, 30])

limiter = pull.AdaptiveRate(start=3)
check('   the ceiling is 5 requests a second - half what the extension\'s own client allows',
      (pull.CEILING, limiter.ceiling), (5.0, 5.0))
for _ in range(10):
    limiter.succeeded()
check('   before any throttle the rate climbs by 1% an answer', round(limiter.rate, 3), round(3 * 1.01 ** 10, 3))
for _ in range(200):
    limiter.succeeded()
check('   and never past the ceiling', limiter.rate, 5.0)

before = time.time()
limiter.throttled()
check('2. a throttle pauses every worker for 1 s', round(limiter.paused_until - before), 1)
check('   and cuts the rate by 30%', limiter.rate, 3.5)
limiter.throttled()
check('   a second worker caught in the same pause changes nothing', (limiter.rate, limiter.in_a_row), (3.5, 1))
for _ in range(50):
    limiter.succeeded()
check('   the rate stays down: climbing back would be aiming for the limit', limiter.rate, 3.5)

limiter = pull.AdaptiveRate(start=10)
limiter.throttled()
limiter.paused_until = 0                       # the pause is over
before = time.time()
limiter.throttled()
check('3. throttles in a row double the pause', round(limiter.paused_until - before), 2)
limiter.paused_until = 0
before = time.time()
limiter.throttled(retry_after=12)
check('   a longer Retry-After from Civitai wins', round(limiter.paused_until - before), 12)
limiter.paused_until = 0
for _ in range(pull.AdaptiveRate.CALM_AFTER):
    limiter.succeeded()
before = time.time()
limiter.throttled()
check('   and a calm stretch starts the doubling over', round(limiter.paused_until - before), 1)

# --------------------------------------------------------- the requests
limiter = pull.AdaptiveRate(start=10)
client = client_with([Response(429, headers={'Retry-After': '3'}), Response(429)], Response(200, {'ok': 1}), limiter)
check('3. a throttled request is sent again until it is answered',
      (client._request('GET', '/images'), len(client.session.asked)), ({'ok': 1}, 3))
check('   counting the throttles', limiter.throttles, 2)

client = client_with([Response(503), Response(502)], Response(200, {'ok': 2}), pull.AdaptiveRate(10))
check('4. a server error is retried with backoff', client._request('GET', '/images'), {'ok': 2})

client = client_with([], Response(404), pull.AdaptiveRate(10))
try:
    client._request('GET', '/images')
    raised = None
except CivitaiNotFoundError:
    raised = 'not found'
check('5. not found is an answer, not something to retry', raised, 'not found')

client = client_with([], Response(429), pull.AdaptiveRate(10))
try:
    client._request('GET', '/images')
    raised = None
except Exception as e:
    raised = str(e)
check('6. a throttle that never lifts is given up in the end, not waited on for ever',
      (raised, len(client.session.asked)), ('HTTP 429', 31))

# ------------------------------------------ prompts are not lost to a throttle
gen = [{'result': {'data': {'json': {'meta': {'prompt': 'a lighthouse %d' % i}}}}} for i in range(2)]
images = {'items': [{'id': 1}, {'id': 2}], 'metadata': {}}
# Four throttles in a row: the client's own requests give up after three,
# and its prompt lookup then drops the batch.
client = client_with([Response(200, images)] + [Response(429, headers={'Retry-After': '0'})] * 4,
                     Response(200, gen), pull.AdaptiveRate(10))
in_flight = pull.InFlight()
model_id, got, seconds = pull.fetch_model(client, 7, [70], 10, in_flight)
check('7. a prompt lookup that is throttled is sent again - no image is kept without its prompt',
      [((i.get('meta') or {}).get('prompt')) for i in got], ['a lighthouse 0', 'a lighthouse 1'])

check('8. a fetched model says how long it took, and leaves nothing in flight',
      (isinstance(seconds, float), in_flight.count), (True, 0))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
