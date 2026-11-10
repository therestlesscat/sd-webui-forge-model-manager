"""
The WebUI's own login on the extension's routes. Gradio asks its login only
on the routes it adds, and Forge asks --api-auth only on those its API adds;
the gate asks the same login on every route of the extension, exactly where
the WebUI has one: Gradio's session - the page's own requests carry its
cookie - or, while Forge's API is on, --api-auth's Basic credentials. Either
is enough. No login set: as before. A login the command line names that the
app does not hold: refused rather than let through. No exemption for this
computer: every tunnel arrives from it.

One check goes through Gradio 4.40's own app and its real login form; the
rest stand Gradio's app in, with the attributes Gradio sets. And each of the
96 routes, with a login set and none given, refuses before its own code runs.
"""
import asyncio
import base64
import json
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

try:
    from fastapi import FastAPI
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient
    from starlette.requests import Request as StarletteRequest
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402

# The fixture library, so nothing here can reach another database.
db, facts = fixtures.build(os.path.join(TESTS, 'work', 'login'))
dbmod._db_instance = db

from model_manager import api, forge_host, tabs           # noqa: E402
from model_manager.api import common                      # noqa: E402
from modules import shared                                # noqa: E402  (webui_stub's)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# The WebUI's command line, as each check needs it.
options = {}
forge_host.model_folders = lambda: (types.SimpleNamespace(**options), '')
def started(**given):
    options.clear()
    options.update(given)


runs = []
def routed(app):
    """A route on `app` added as the extension adds its routes: through the gate."""
    @app.get('/model-manager/act')
    @common.gate('always')
    def act():
        runs.append('act')
        return {'success': True}
    return app


def basic(user, password):
    return {'authorization': 'Basic ' + base64.b64encode(f'{user}:{password}'.encode('utf-8')).decode('ascii')}


def ask(client, headers=None, cookies=None):
    """(status, whether the route ran, the answer's error) for one request."""
    del runs[:]
    client.cookies.clear()
    for name, value in (cookies or {}).items():
        client.cookies.set(name, value)
    answer = client.get('/model-manager/act', headers={'host': '127.0.0.1:7860', **(headers or {})})
    body = answer.json() if answer.headers.get('content-type', '').startswith('application/json') else {}
    return answer.status_code, bool(runs), body.get('error')


# ------------------------------------------------ Gradio's own app, its real login
try:
    import gradio as gr
    from gradio.routes import App
except ImportError:
    gr = None
if gr is not None:
    started(gradio_auth='tester:secret')
    with gr.Blocks() as demo:
        gr.Markdown('x')
    demo.auth = [('tester', 'secret')]
    real = TestClient(routed(App.create_app(demo)), raise_server_exceptions=False)
    before = ask(real)[:2]
    del runs[:]
    logged = real.post('/login', data={'username': 'tester', 'password': 'secret'})
    answer = real.get('/model-manager/act', headers={'host': '127.0.0.1:7860'})
    check('Gradio\'s own app with a login: refused before logging in, run after its own login form',
          [before, logged.status_code, answer.status_code, bool(runs)], [(401, False), 200, 200, True])
else:
    check('Gradio is there to log in through', False)


# ------------------------------------------------ Gradio's app, stood in
class GradioApp(FastAPI):
    """Gradio's App as 4.40 holds its login: auth, auth_dependency, tokens, cookie_id."""
    def __init__(self, auth=None, auth_dependency=None):
        super().__init__()
        self.auth = auth
        self.auth_dependency = auth_dependency
        self.tokens = {'held-token': 'tester'}
        self.cookie_id = 'c0ffee'


def client(app):
    return TestClient(routed(app), raise_server_exceptions=False)


started()
check('no login set: runs', ask(client(GradioApp()))[:2], (200, True))

started(gradio_auth='tester:secret')
gated = client(GradioApp(auth={'tester': 'secret'}))
check('a Gradio login: no cookie; a cookie Gradio does not hold; the unsecure cookie of a session it holds',
      [ask(gated)[:2], ask(gated, cookies={'access-token-c0ffee': 'stolen'})[:2],
       ask(gated, cookies={'access-token-unsecure-c0ffee': 'held-token'})[:2]],
      [(401, False), (401, False), (200, True)])
check('the session cookie of a logged-in browser: runs',
      ask(gated, cookies={'access-token-c0ffee': 'held-token'})[:2], (200, True))
loopback = StarletteRequest({'type': 'http', 'method': 'GET', 'path': '/', 'query_string': b'',
                             'client': ('127.0.0.1', 50123), 'app': GradioApp(auth={'tester': 'secret'}),
                             'headers': [(b'host', b'127.0.0.1:7860')]})
check('from 127.0.0.1, with no session: refused - no exemption for this computer',
      getattr(getattr(common, 'not_logged_in', lambda request: None)(loopback), 'status_code', None), 401)

names = {'user': None}
check('a login by auth_dependency: a user runs, none is refused',
      [ask(client(GradioApp(auth_dependency=lambda request: 'tester')))[:2],
       ask(client(GradioApp(auth_dependency=lambda request: names['user'])))[:2]],
      [(200, True), (401, False)])

started(gradio_auth='tester:secret')
check('the command line names a Gradio login the app does not hold: refused, not let through',
      ask(client(FastAPI()))[:2], (401, False))
started(gradio_auth=',')
check('--gradio-auth set to no login: Gradio holds none, and the gate goes on',
      ask(client(GradioApp()))[:2], (200, True))

# --api-auth, where Forge's API is on.
started(gradio_auth='tester:secret', api=True, api_auth='script:key,other:pa:ss')
check('a Gradio login and --api-auth: right credentials; a wrong password; an unknown user; nothing',
      [ask(gated, headers=basic('script', 'key'))[:2], ask(gated, headers=basic('script', 'nope'))[:2],
       ask(gated, headers=basic('someone', 'key'))[:2], ask(gated)[:2]],
      [(200, True), (401, False), (401, False), (401, False)])
check('a password with a colon in it: split on the first colon only',
      ask(gated, headers=basic('other', 'pa:ss'))[:2], (200, True))
check('a valid session and a proxy\'s own wrong Basic header: runs',
      ask(gated, headers=basic('proxy', 'login'), cookies={'access-token-c0ffee': 'held-token'})[:2], (200, True))
started(gradio_auth='tester:secret', api_auth='script:key')
check('--api-auth while Forge\'s API is off: it counts for nothing, as in Forge',
      ask(gated, headers=basic('script', 'key'))[:2], (401, False))

started(api=True, api_auth='script:key')
check('--api-auth alone, with the page: runs with nothing, as Gradio\'s own routes do',
      ask(client(GradioApp()))[:2], (200, True))
started(nowebui=True, api_auth='script:key')
plain = client(FastAPI())
check('--nowebui with --api-auth: nothing is refused, its credentials run',
      [ask(plain)[:2], ask(plain, headers=basic('script', 'key'))[:2]], [(401, False), (200, True)])
started(nowebui=True, gradio_auth='tester:secret')
check('--nowebui with --gradio-auth: Forge ignores the Gradio login there, and so does the gate',
      ask(plain)[:2], (200, True))

# --api-auth read without raising.
def parsed():
    try:
        return getattr(forge_host, 'api_credentials', dict)()
    except Exception as e:
        return ('raised', type(e).__name__)


started(api=True, api_auth=' a:1,,b,c:x:y,é:ü,')
check('--api-auth with a stray comma, an entry without a colon, a password with one, a non-ASCII one',
      parsed(), {' a': '1', 'c': 'x:y', 'é': 'ü'})
started(api=True, api_auth='u:ü')
check('a non-ASCII password compared as UTF-8 bytes: refused, not a 500',
      ask(client(GradioApp(auth={'tester': 'secret'})), headers=basic('u', 'wrong'))[0], 401)

# What a refused request is answered.
started(gradio_auth='tester:secret')
answer = gated.get('/model-manager/act', headers={'host': '127.0.0.1:7860'})
check('refused: 401, the words, and no Basic challenge for a browser that sent none',
      [answer.status_code, answer.json(), answer.headers.get('www-authenticate')],
      [401, {'success': False, 'error': 'Not logged in: log in to the WebUI first.'}, None])
started(gradio_auth='tester:secret', api=True, api_auth='script:key')
answer = gated.get('/model-manager/act', headers={'host': '127.0.0.1:7860', **basic('script', 'nope')})
check('with --api-auth, wrong credentials sent: the words name it, and the Basic challenge',
      [answer.json().get('error'), answer.headers.get('www-authenticate')],
      ['Not logged in: log in to the WebUI first, or give the credentials it was started with (--api-auth).', 'Basic'])
started(gradio_auth='tester:secret')
answer = gated.get('/model-manager/act', headers={'host': '127.0.0.1:7860', **basic('proxy', 'login')})
check('a proxy\'s own Basic login, no session, --api-auth not counting: refused with no challenge',
      [answer.status_code, answer.headers.get('www-authenticate')], [401, None])
started(gradio_auth='tester:secret', api=True)
check('--gradio-auth and --api without --api-auth: no Basic header counts',
      ask(gated, headers=basic('script', 'key'))[:2], (401, False))
started(nowebui=True)
check('--nowebui with no login at all: runs, as /sdapi does', ask(client(FastAPI()))[:2], (200, True))

# S1's refusals come first; the gate called directly goes on.
started(gradio_auth='tester:secret')
answer = gated.get('/model-manager/act', headers={'host': '127.0.0.1:7860', 'sec-fetch-site': 'cross-site',
                                                  'origin': 'https://elsewhere.example'})
check('another website\'s page, with a login set and no session: still refused as S1 refuses it, in S1\'s words',
      [answer.status_code, answer.json().get('refused'),
       answer.json().get('error', '').startswith('Refused: this request came from another website\'s page')],
      [403, 'https://elsewhere.example', True])
real_alone, real_switch, real_names = (common.listens_on_this_computer_alone, common.refuses_unknown_names,
                                       common.other_host_names)
common.listens_on_this_computer_alone = lambda: True
common.refuses_unknown_names = lambda: True
common.other_host_names = lambda: frozenset()
answer = gated.get('/model-manager/act', headers={'host': 'example.invalid:7860'})
check('an unknown name, with a login set and no session: still refused as S1 refuses it, by name',
      [answer.status_code, answer.json().get('refused')], [403, 'example.invalid'])
common.listens_on_this_computer_alone, common.refuses_unknown_names, common.other_host_names = (
    real_alone, real_switch, real_names)
check('the gate called directly, with no request: goes on',
      [getattr(common, 'not_logged_in', lambda request: 'missing')(None), common.refusal_of(None)], [None, None])


# ------------------------------------------------ every route, not logged in
def call(endpoint, **kwargs):
    answer = endpoint(**kwargs)
    return asyncio.run(answer) if asyncio.iscoroutine(answer) else answer


app = FastAPI()
api.setup_api(app)
routes = {(method, route.path): route for route in app.routes
          if isinstance(route, APIRoute) and route.path.startswith('/model-manager/') for method in route.methods}
check('all 96 routes', len(routes), 96)
login_app = GradioApp(auth={'tester': 'secret'})


def not_logged_in():
    return StarletteRequest({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'', 'app': login_app,
                             'headers': [(b'host', b'127.0.0.1:7860')]})


# Only once the stand-in has shown the refusal, with every tab on: a gate
# that let the request through would run the real routes - a restart, deletes.
for key in tabs.TABS.values():
    setattr(shared.opts, key, True)
started(gradio_auth='tester:secret')
if ask(gated)[:2] == (401, False):
    walked = {}
    for key, route in routes.items():
        parameter = getattr(route.endpoint, 'mm_request_parameter', None)
        try:
            answer = call(route.endpoint, **{parameter: not_logged_in()})
            walked[key] = answer.status_code
        except Exception as e:
            walked[key] = ('ran', type(e).__name__)
    check('each of the 96 routes, a login set and none given, its tab on: refused before its own code',
          sorted(key for key, got in walked.items() if got != 401), [])
else:
    check('the stand-in refuses a request with no login, so the routes can be walked', False)

if fails:
    print('FAIL login_test (%d)' % len(fails))
    for f in fails:
        print(' - ' + f)
    sys.exit(1)
print('ok login_test')
