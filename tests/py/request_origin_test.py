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
"""
import asyncio
import functools
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

if fails:
    print('FAIL request_origin_test (%d)' % len(fails))
    for f in fails:
        print(' - ' + f)
    sys.exit(1)
print('ok request_origin_test')
