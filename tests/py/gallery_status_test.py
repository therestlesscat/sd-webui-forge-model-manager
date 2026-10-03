"""
What a gallery waits on while Civitai is asked, said to the page as it waits
(#132): a turn at the request rate, a retry - in Civitai's words, with how
long until the next try - and each slow step.

The client retries inside one request - a 503 backs off, a 429 waits out its
Retry-After, a timeout or a lost connection tries again - and the page saw
"Loading images..." until the end. Now the client tells whoever listens for
the request being served (telling), and a gallery's endpoint, asked for a
stream, sends each of those as a line before its answer (streams_status).
"""
import json
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

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import requests                                          # noqa: E402
import model_manager.civitai.client as client_module     # noqa: E402
from model_manager.civitai import CivitaiAPIError, CivitaiClient, TokenBucketRateLimiter  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


telling = getattr(client_module, 'telling', None)
tell = getattr(client_module, 'tell', None)
check('the client has a way to be listened to', (telling is not None, tell is not None), (True, True))
if telling is None or tell is None:
    print('\n'.join('FAIL ' + f for f in fails))
    sys.exit(1)


class Answer(object):
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body if body is not None else {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError('HTTP %d' % self.status_code)


def quick(api_key=None):
    client = CivitaiClient(api_key)
    client.RETRY_BACKOFF_BASE = 0.001
    client.rate_limiter = TokenBucketRateLimiter(1000.0, 100)
    return client


def answers(*replies):
    """A session answering these in turn: an Answer, or an exception to raise."""
    queue = list(replies)

    def request(method, url, **kw):
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return request


def heard(work):
    said = []
    with telling(said.append):
        work()
    return said


texts = lambda events: [e['text'] for e in events]

# ------------------------------------------------------------- each retry
OVERLOADED = 'Image search is temporarily overloaded - please retry.'
client = quick()
client.session.request = answers(Answer(503, {'error': OVERLOADED}), Answer(200, {'items': [], 'metadata': {}}))
said = heard(lambda: client.get_model_images(1, limit=1))
check('a 503 is said in Civitai\'s words, with the try to come and how long until it',
      [e for e in said if 'overloaded' in e['text']],
      [{'text': 'Civitai: %s Trying again (1 of %d)' % (OVERLOADED, client.MAX_RETRIES), 'wait': 0.001}])
check('and the step it was on, before it', texts(said)[0], 'Asking Civitai for images...')

client = quick()
client.session.request = answers(Answer(503), Answer(200, {'items': [], 'metadata': {}}))
check('a 503 that says nothing is said by its number',
      [e['text'] for e in heard(lambda: client.get_model_images(1, limit=1)) if 'again' in e['text']],
      ['Civitai answered 503. Trying again (1 of %d)' % client.MAX_RETRIES])

client = quick()
client.session.request = answers(Answer(429, {'message': 'Slow down'}, {'Retry-After': '0'}),
                                 Answer(200, {'items': [], 'metadata': {}}))
check('a 429 says Civitai is limiting requests, in its words, and waits its Retry-After',
      [e for e in heard(lambda: client.get_model_images(1, limit=1)) if 'again' in e['text']],
      [{'text': 'Civitai is limiting requests: Slow down. Trying again (1 of %d)' % client.MAX_RETRIES, 'wait': 0}])

client = quick()
client.session.request = answers(requests.exceptions.Timeout(), Answer(200, {'items': [], 'metadata': {}}))
check('a timeout says so', [e['text'] for e in heard(lambda: client.get_model_images(1, limit=1))
                            if 'again' in e['text']],
      ['Civitai did not answer within %d s. Trying again (1 of %d)' % (client.REQUEST_TIMEOUT, client.MAX_RETRIES)])

client = quick()
client.session.request = answers(requests.exceptions.ConnectionError('refused'),
                                 Answer(200, {'items': [], 'metadata': {}}))
check('a lost connection says so', [e['text'] for e in heard(lambda: client.get_model_images(1, limit=1))
                                    if 'again' in e['text']],
      ['Could not reach Civitai. Trying again (1 of %d)' % client.MAX_RETRIES])

# -------------------------------------------------------- a turn at the rate
client = quick()
client.rate_limiter = TokenBucketRateLimiter(0.8, 1)
client.rate_limiter.tokens = 0.0
client.session.request = answers(Answer(200, {'items': [], 'metadata': {}}))
waits = [e for e in heard(lambda: client.get_model_images(1, limit=1)) if 'turn' in e['text']]
check('a request waiting a second or more for its turn at the rate says so, and for how long',
      [(e['text'], 1.0 <= e['wait'] <= 1.3) for e in waits],
      [('Waiting for a turn: Civitai is asked at most 0.8 times a second', True)])

# ------------------------------------------- the prompts, on worker threads
client = quick('a-key')
replies = {}


def trpc(method, url, **kw):
    # Each batch fails once, then answers: told from the worker threads.
    first = url not in replies
    replies[url] = True
    return Answer(503, {'error': 'busy'}) if first else Answer(200, [])
client.session.request = trpc
said = heard(lambda: client.get_generation_data(list(range(1, 2 * client.GENERATION_DATA_BATCH + 1)), workers=2))
check('the prompts\' step is said', texts(said)[0],
      'Asking Civitai for the prompts of %d images...' % (2 * client.GENERATION_DATA_BATCH))
check('and their retries, from the threads that fetch them',
      sum(1 for e in said if e['text'].startswith('Civitai: busy')), 2)

# ---------------------------------------------------------- nobody listening
client = quick()
client.session.request = answers(Answer(503, {'error': OVERLOADED}), Answer(200, {'items': [], 'metadata': {}}))
check('with nobody listening, a request goes as before', client.get_model_images(1, limit=1),
      {'images': [], 'next_cursor': None})


def broken(event):
    raise RuntimeError('a listener that fails')
client.session.request = answers(Answer(503), Answer(200, {'items': [], 'metadata': {}}))
with telling(broken):
    check('and a listener that fails does not fail the request', client.get_model_images(1, limit=1),
          {'images': [], 'next_cursor': None})

# --------------------------------------------------- a gallery's endpoint
# Asked for a stream, a gallery's endpoint sends what it is told as status
# lines, then its answer; asked as before, it answers as before.
import model_manager.api.civitai as civitai_api          # noqa: E402
from model_manager.api import setup_api                  # noqa: E402


class Talking(object):
    """Civitai, saying a wait before it answers."""

    @classmethod
    def from_settings(cls):
        return cls()

    api_key = None

    def get_model_images(self, version_id, cursor=None, limit=100):
        tell('Civitai: overloaded. Trying again (1 of 3)', wait=2)
        return {'images': [{'id': 1, 'url': 'https://example.invalid/1.jpeg', 'nsfwLevel': 1,
                            'meta': {'prompt': 'a lighthouse by the sea at dusk'}}], 'next_cursor': None}

    def get_generation_data(self, ids, workers=1, errors=None):
        return {}

    def close(self):
        pass


real_client = civitai_api.CivitaiClient
civitai_api.CivitaiClient = Talking
try:
    app = FastAPI()
    setup_api(app)
    web = TestClient(app)
    plain = web.get('/model-manager/civitai/versions/70/images')
    check('asked as before, the Civitai Browser\'s gallery answers JSON',
          (plain.headers.get('content-type', '').split(';')[0], plain.json().get('success')),
          ('application/json', True))
    streamed = web.get('/model-manager/civitai/versions/70/images', headers={'Accept': 'application/x-ndjson'})
    lines = [json.loads(line) for line in streamed.text.splitlines() if line.strip()]
    check('asked for a stream, it sends what it waits on, then the same answer',
          (streamed.headers.get('content-type', '').split(';')[0], lines[:-1], lines[-1:]),
          ('application/x-ndjson',
           [{'type': 'status', 'text': 'Civitai: overloaded. Trying again (1 of 3)', 'wait': 2}],
           [{'type': 'result', 'result': plain.json()}]))
finally:
    civitai_api.CivitaiClient = real_client

# The Model Manager's gallery and Resync stream the same way.
import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
db, facts = fixtures.build(os.path.join(TESTS, 'work', 'gallery_status'))
dbmod._db_instance = db
for label, ask in (('the Model Manager\'s gallery', lambda h: web.get(
                        '/model-manager/images/gallery-page', params={'version_id': facts['version_ids'][0]}, headers=h)),
                   ('Resync Images', lambda h: web.post('/model-manager/images/resync', data={'version_id': 0}, headers=h))):
    plain = ask({})
    streamed = ask({'Accept': 'application/x-ndjson'})
    lines = [json.loads(line) for line in streamed.text.splitlines() if line.strip()]
    check('%s streams when asked, ending with its answer' % label,
          (streamed.headers.get('content-type', '').split(';')[0], lines[-1:]),
          ('application/x-ndjson', [{'type': 'result', 'result': plain.json()}]))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
