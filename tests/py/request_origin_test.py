"""
The request each route hands the gate every route passes.

FastAPI hands a route one request, to the last parameter typed Request. The
gate reads it there: from the route's own parameter where it has one - the
two streaming routes do, through streams_status beneath the gate - else from
one it adds and takes out again. A second would leave the first unfilled, and
those two routes would fail on every call.

What is checked here: every one of the 96 routes hands its request to the
gate, the gate outermost; a route that asked for its request still gets it,
one that did not is not handed it; a direct call, with no request, runs as a
script's. The streaming routes' own answers, plain and streamed, are
gallery_status_test's.

And what the gate does with it: a request another website's page sent is
refused, read from the browser's Sec-Fetch-Site, else Origin, else Referer;
the WebUI's own page, a script and the test client are not; an origin the
WebUI allows (--cors-allow-origins, its pattern, never "*") is let through;
the refusal comes before a tab's own; the console says it once an origin;
and each of the 96 routes, called with such a request, refuses it before
any of its own code runs.
"""
import asyncio
import functools
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
    from fastapi import FastAPI, Request
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402

# The fixture library, so nothing here can reach another database.
db, facts = fixtures.build(os.path.join(TESTS, 'work', 'request_origin'))
dbmod._db_instance = db

from model_manager import api                             # noqa: E402
from model_manager.api import common                      # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def call(endpoint, **kwargs):
    answer = endpoint(**kwargs)
    return asyncio.run(answer) if asyncio.iscoroutine(answer) else answer


# ------------------------------------------------ every route's request
app = FastAPI()
api.setup_api(app)
routes = {(method, route.path): route for route in app.routes
          if isinstance(route, APIRoute) and route.path.startswith('/model-manager/') for method in route.methods}
check('all 96 routes', len(routes), 96)
# The gate's own mark points at itself: a wrapper put outside it would
# carry a copy pointing at the gate within.
check('the gate is each route\'s outermost wrapper: what FastAPI calls is the gate itself',
      sorted(key for key, route in routes.items() if getattr(route.endpoint, 'mm_gate', None) is not route.endpoint), [])
check('each route hands its request to the gate: FastAPI\'s one request parameter is the one the gate reads',
      sorted(key for key, route in routes.items()
             if route.dependant.request_param_name != getattr(route.endpoint, 'mm_request_parameter', 'none')), [])
check('the two streaming routes are read through their own parameter, not a second',
      sorted(name for name in (str(getattr(route.endpoint, 'mm_request_parameter', None)) for route in routes.values())
             if name != getattr(common, 'GATE_REQUEST', 'mm_gate_request')), ['mm_request', 'mm_request'])

# ------------------------------------------------ stand-ins, through the app
seen = []
stand_ins = FastAPI()


@stand_ins.get('/asks')
@common.gate('always')
def asks(request: Request, n: int = 0):
    seen.append(('asks', request.url.path, n))
    return {'n': n}


@stand_ins.get('/plain')
@common.gate('always')
def plain(n: int = 0):
    seen.append(('plain', n))
    return {'n': n}


@stand_ins.get('/awaited')
@common.gate('always')
async def awaited(n: int = 0):
    seen.append(('awaited', n))
    return {'n': n}


# A route that raises answers 500 here, so a fault fails a check rather than the suite.
client = TestClient(stand_ins, raise_server_exceptions=False)
answers = [client.get(path, params={'n': 7}).status_code for path in ('/asks', '/plain', '/awaited')]
check('through the app: a route that asks for its request gets it; the others run without one',
      (answers, seen), ([200, 200, 200], [('asks', '/asks', 7), ('plain', 7), ('awaited', 7)]))

# The outermost check on a wrapper put outside the gate, as functools.wraps
# makes one: it carries the gate's marks, and is still caught.
def outer(endpoint):
    @functools.wraps(endpoint)
    def wrapped(*args, **kwargs):
        return endpoint(*args, **kwargs)
    return wrapped


check('a wrapper outside the gate is told apart: the marks copied, the gate not outermost',
      (getattr(outer(plain), 'mm_area', None), getattr(outer(plain), 'mm_gate', None) is outer(plain),
       getattr(plain, 'mm_gate', None) is plain),
      ('always', False, True))

# A direct call, as the suites make, with no request: run, as a script's.
seen.clear()
for endpoint, n in ((plain, 1), (awaited, 2)):
    try:
        call(endpoint, n=n)
    except Exception as e:
        seen.append(('raised', type(e).__name__))
check('called directly with no request: run', seen, [('plain', 1), ('awaited', 2)])

# ------------------------------------------------ where a request came from
from modules import shared                                # noqa: E402  (webui_stub's)
from starlette.requests import Request as StarletteRequest  # noqa: E402

said = []
common.say = said.append
cors = {'listed': [], 'pattern': None}
common.cors_origins = lambda: (list(cors['listed']), cors['pattern'])
runs = []
origin_app = FastAPI()


@origin_app.post('/act')
@common.gate('always')
def act():
    runs.append('act')
    return {'success': True}


@origin_app.get('/act')
@common.gate('always')
def act_get():
    runs.append('act')
    return {'success': True}


@origin_app.get('/queued')
@common.gate('queue')
def queued():
    runs.append('queued')
    return {'success': True}


origin_client = TestClient(origin_app, raise_server_exceptions=False)


def ask(headers, method='post', host='127.0.0.1:7860'):
    """(status, whether the route ran, what was refused) for a request with these headers."""
    del runs[:]
    answer = getattr(origin_client, method)('/act', headers={'host': host, **headers})
    body = answer.json() if answer.headers.get('content-type', '').startswith('application/json') else {}
    return answer.status_code, bool(runs), body.get('refused')


def fresh():
    # The console's memory of origins said; on the code before the check there is none.
    getattr(common, '_said', set()).clear()
    del getattr(common, '_said_more', [])[:]
    del said[:]


fresh()
check('Sec-Fetch-Site cross-site, same-site, and a value none of the four: refused, the route never run',
      [ask({'sec-fetch-site': v, 'origin': 'https://example.invalid'})[:2] for v in ('cross-site', 'same-site', 'other')],
      [(403, False)] * 3)
check('the refusal names the origin', ask({'sec-fetch-site': 'cross-site', 'origin': 'https://example.invalid'})[2],
      'https://example.invalid')
check('a cross-site image, no Origin: refused by its Referer\'s origin',
      ask({'sec-fetch-site': 'cross-site', 'referer': 'https://example.invalid/page'}, method='get'),
      (403, False, 'https://example.invalid'))
check('Sec-Fetch-Site same-origin, and none: run',
      [ask({'sec-fetch-site': v})[:2] for v in ('same-origin', 'none')], [(200, True)] * 2)

check('no Sec-Fetch-Site: an Origin of another host, and Origin null, refused',
      [ask({'origin': o})[:2] for o in ('http://example.invalid:7860', 'null')], [(403, False)] * 2)
check('no Sec-Fetch-Site: the request\'s own host - as is, a default port, capitals, IPv6 - run',
      [ask({'origin': o}, host=h)[:2] for o, h in (('http://127.0.0.1:7860', '127.0.0.1:7860'),
                                                     ('http://webui.lan', 'webui.lan:80'),
                                                     ('https://webui.lan', 'WebUI.LAN:443'),
                                                     ('http://[::1]:7860', '[::1]:7860'))],
      [(200, True)] * 4)
check('the same host at another port is another origin: refused',
      ask({'origin': 'http://127.0.0.1:7861'})[:2], (403, False))
check('no Sec-Fetch-Site, no Origin, a Referer of another host: refused',
      ask({'referer': 'http://example.invalid/page'}, method='get')[:2], (403, False))
check('neither header - a script, curl, the test client: run', ask({})[:2], (200, True))

# What no browser sends, which only a script could: refused, with a 403, not an error.
check('an empty Sec-Fetch-Site, and one in capitals',
      [ask({'sec-fetch-site': ''})[:2], ask({'sec-fetch-site': 'SAME-ORIGIN'})[:2]], [(403, False), (200, True)])
check('an Origin that cannot be read, with and without Sec-Fetch-Site: refused, not an error',
      [ask({'origin': 'http://[abc/'})[:2], ask({'sec-fetch-site': 'cross-site', 'origin': 'http://[abc/'})[:2]],
      [(403, False)] * 2)
check('a Host whose port is not a number; a Referer with a user name: refused',
      [ask({'origin': 'http://127.0.0.1'}, host='127.0.0.1:abc')[:2],
       ask({'referer': 'http://127.0.0.1:x@example.invalid/'}, method='get', host='127.0.0.1')[:2]],
      [(403, False)] * 2)
check('cross-site with no Origin and no Referer: refused, saying it did not say where it came from',
      ask({'sec-fetch-site': 'cross-site'}, method='get'), (403, False, 'a page that did not say where it came from'))

cors.update(listed=['https://mine.example', ' https://second.example'], pattern=r'https://[a-z]+\.tools\.example')
check('an origin in the WebUI\'s list, and one its pattern matches: run',
      [ask({'sec-fetch-site': 'cross-site', 'origin': o})[:2] for o in ('https://mine.example', 'https://a.tools.example')],
      [(200, True)] * 2)
check('the pattern matches the whole origin; the list as the WebUI splits it, nothing stripped: refused',
      [ask({'sec-fetch-site': 'cross-site', 'origin': o})[:2]
       for o in ('https://a.tools.example.evil', 'https://second.example')], [(403, False)] * 2)
cors.update(listed=['*'], pattern=None)
check('"*" in the list lets nothing through here',
      ask({'sec-fetch-site': 'cross-site', 'origin': 'https://example.invalid'})[:2], (403, False))
cors.update(listed=[], pattern=None)

import model_manager.tabs as tabs                         # noqa: E402
setattr(shared.opts, tabs.TABS['queue'], False)
del runs[:]
answer = origin_client.get('/queued', headers={'sec-fetch-site': 'cross-site', 'origin': 'https://example.invalid'})
check('the tab off, and the request cross-site: refused for where it came from, not for the tab',
      (answer.status_code, answer.json().get('refused'), 'off' in answer.json(), runs),
      (403, 'https://example.invalid', False, []))
setattr(shared.opts, tabs.TABS['queue'], True)

fresh()
for o in ('https://one.example', 'https://one.example', 'https://two.example'):
    ask({'sec-fetch-site': 'cross-site', 'origin': o})
check('the console says it once an origin', len(said), 2)
check('naming the origin and how to allow one\'s own',
      ('https://one.example' in ''.join(said[:1]), '--cors-allow-origins' in ''.join(said[:1])), (True, True))
fresh()
for n in range(25):
    ask({'sec-fetch-site': 'cross-site', 'origin': 'https://s%d.example' % n})
check('25 origins: 20 named, then one line that more are refused, and no more',
      (len(said), 'more' in ''.join(said[-1:])), (21, True))
check('a very long origin is cut to 100 characters',
      len(ask({'sec-fetch-site': 'cross-site', 'origin': 'https://' + 'x' * 300 + '.example'})[2] or ''), 100)


# ------------------------------------------- every route, from another site
def from_another_site():
    return StarletteRequest({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                             'headers': [(b'host', b'127.0.0.1:7860'), (b'sec-fetch-site', b'cross-site'),
                                         (b'origin', b'https://example.invalid')]})


# Only once the stand-ins have shown the refusal, with every tab on: a gate
# that let the request through would run the real routes - a restart, deletes.
for key in tabs.TABS.values():
    setattr(shared.opts, key, True)
if ask({'sec-fetch-site': 'cross-site', 'origin': 'https://example.invalid'})[:2] == (403, False):
    walked = {}
    for key, route in routes.items():
        parameter = getattr(route.endpoint, 'mm_request_parameter', None)
        try:
            answer = call(route.endpoint, **{parameter: from_another_site()})
            walked[key] = (answer.status_code, json.loads(answer.body).get('refused'))
        except Exception as e:
            walked[key] = ('ran', type(e).__name__)
    check('each of the 96 routes, asked from another site with its tab on: refused before its own code',
          sorted(key for key, got in walked.items() if got != (403, 'https://example.invalid')), [])
else:
    check('the stand-in refuses a request from another site, so the routes can be walked', False)

if fails:
    print('FAIL request_origin_test (%d)' % len(fails))
    for f in fails:
        print(' - ' + f)
    sys.exit(1)
print('ok request_origin_test')
