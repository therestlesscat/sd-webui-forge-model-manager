"""
What the endpoint modules share and none of them owns: no endpoints here.

The card-size parser was written four times, and the same try/except that
logs a failure and answers 500 twenty-four times. And the gate every route
passes: refusing a request another website's page sent, one addressed by
a name the WebUI does not know while it listens on this computer alone,
one without the WebUI's own login where it has one, and one whose tab is
off.
"""
import base64
import binascii
import functools
import hmac
import inspect
import ipaddress
import json
import queue
import re
import threading
from typing import Any, Callable, Optional, Tuple
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..civitai.client import telling
from ..forge_host import (DEFAULTS, api_credentials, cors_origins, gradio_login_named,
                          listens_on_this_computer_alone, no_web_ui, other_host_names, refuses_unknown_names,
                          setting)
from ..tabs import check_area, on, why_off
from ..console import say, say_failure


def card_size(key: str) -> Tuple[int, int]:
    """
    A tab's card size, as its setting holds it - "WIDTHxHEIGHT" - or the
    default when the setting is missing or cannot be read.
    """
    return _size(setting(key)) or _size(DEFAULTS[key])


def _size(text: Any) -> Optional[Tuple[int, int]]:
    """(width, height) from "WIDTHxHEIGHT", or None."""
    text = str(text or "").lower()
    if "x" in text:
        width, height = text.split("x")[:2]
        try:
            return int(width.strip()), int(height.strip())
        except ValueError:
            pass
    return None


def failed(e: Exception, doing: Optional[str] = None) -> JSONResponse:
    """
    Log a failed request - what it was doing, and the traceback - and answer
    it as every endpoint does: success false, the error, 500.
    """
    say_failure(f"{doing}: {e}" if doing else f"Request failed: {e}")
    return JSONResponse({"success": False, "error": str(e)}, status_code=500)


def gate(area: str) -> Callable:
    """
    A route of `area` - a tab, what several share, or ALWAYS (tabs.py): run
    while it is on, refused while it is off - with 403, success false and
    why, as every failure answers. Before that, a request another website's
    page sent is refused (from_elsewhere), and, while the WebUI listens on
    this computer alone, one addressed by a name it does not know
    (unknown_name), whatever its tab: the browser sends such a request, and
    the route would carry it out. Then one without the WebUI's own login,
    where it has one (not_logged_in): Gradio and Forge ask theirs only on
    their own routes. On the line under
    each route's own, so the next route is written with it;
    tab_switches_test.py fails on a route without one.

    Not a FastAPI dependency: that answers {"detail": ...}, which the pages
    do not read. Not a middleware: Starlette refuses one once the app has
    served a request, and our routes are added after the WebUI's have.
    """
    check_area(area)

    def wrap(endpoint: Callable) -> Callable:
        signature = inspect.signature(endpoint)
        name, added = request_parameter(signature)

        def take(kwargs):
            # The request, kept for the route when it asked for one itself;
            # None when the gate is called directly, with none, as a script.
            return kwargs.pop(name, None) if added else kwargs.get(name)

        if inspect.iscoroutinefunction(endpoint):
            @functools.wraps(endpoint)
            async def answer(*args, **kwargs):
                refusal = refusal_of(take(kwargs))
                if refusal is not None:
                    return refusal
                if not on(area):
                    return refused(area)
                return await endpoint(*args, **kwargs)
        else:
            @functools.wraps(endpoint)
            def answer(*args, **kwargs):
                refusal = refusal_of(take(kwargs))
                if refusal is not None:
                    return refusal
                if not on(area):
                    return refused(area)
                return endpoint(*args, **kwargs)
        if added:
            answer.__signature__ = signature.replace(parameters=[
                *signature.parameters.values(),
                inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=Request)])
        answer.mm_area = area
        answer.mm_request_parameter = name
        # Itself: functools.wraps copies the attributes above onto any wrapper
        # put outside the gate, but this one points at the gate's own.
        answer.mm_gate = answer
        return answer
    return wrap


GATE_REQUEST = "mm_gate_request"


def request_parameter(signature: inspect.Signature) -> Tuple[str, bool]:
    """
    Where the gate finds a route's request, and whether it adds the
    parameter itself. FastAPI hands a route one request, to the last
    parameter typed Request or a kind of it: a route that has one already -
    streams_status adds one beneath the gate - is read through it, as a
    second would leave the first unfilled.
    """
    found = [name for name, parameter in signature.parameters.items()
             if inspect.isclass(parameter.annotation) and issubclass(parameter.annotation, Request)]
    return (found[-1], False) if found else (GATE_REQUEST, True)


# What the browser says of where a request came from (Fetch Metadata). It
# sends it only to https addresses and to localhost, 127.0.0.1 and [::1]:
# over plain http by a network address, Origin, else Referer, decides.
OWN_REQUEST = ("same-origin", "none")
DEFAULT_PORTS = {"http": 80, "https": 443}


def refusal_of(request: Optional[Request]) -> Optional[JSONResponse]:
    """
    The gate's answer to a request it refuses before its tab is asked; None
    to go on. Another website's page and an unknown name first, then the
    WebUI's own login, where it has one.
    """
    name = unknown_name(request)
    if name is not None:
        return refused_from(name, by_name=True)
    origin = from_elsewhere(request)
    if origin is not None:
        return refused_from(origin)
    return not_logged_in(request)


# ------------------------------------------------------- the WebUI's login
# Gradio asks its login only on the routes it adds itself, and Forge asks
# --api-auth only on those its API adds: the extension's routes ask the same
# login here, exactly where the WebUI has one. Read from the request's own
# app as Gradio 4.40 keeps it in both WebUIs (get_current_user, gradio/routes.py).
GRADIO_LOGIN = ("auth", "auth_dependency", "tokens", "cookie_id")


def not_logged_in(request: Optional[Request]) -> Optional[JSONResponse]:
    """
    None when the WebUI asks no login, or the request has it: Gradio's
    session - the page's own requests carry its cookie - or, where Forge's
    API is on, --api-auth's Basic credentials. Either is enough; a Basic
    header never undoes a session. Where the command line names a Gradio
    login the app does not hold, refused rather than let through. No
    exemption for this computer: every tunnel arrives from it.
    """
    if request is None:
        return None
    app = request.scope.get("app")
    credentials = api_credentials()
    holds_login = all(hasattr(app, attribute) for attribute in GRADIO_LOGIN)
    gradio_login = holds_login and (app.auth is not None or app.auth_dependency is not None)
    lost_login = not holds_login and gradio_login_named() and not no_web_ui()
    if not (gradio_login or lost_login or (no_web_ui() and credentials)):
        return None
    if gradio_login and gradio_user(request, app) is not None:
        return None
    if credentials and basic_user(request, credentials) is not None:
        return None
    error = "Not logged in: log in to the WebUI first"
    error += ", or give the credentials it was started with (--api-auth)." if credentials else "."
    # The challenge only to a caller that sent Basic credentials that could
    # count: a browser behind a proxy of its own sends that proxy's, and the
    # challenge would bring up its own login box for the wrong login.
    sent_basic = bool(credentials) and (request.headers.get("authorization") or "").split(" ", 1)[0].lower() == "basic"
    return JSONResponse({"success": False, "error": error}, status_code=401,
                        headers={"WWW-Authenticate": "Basic"} if sent_basic else None)


def gradio_user(request: Request, app: Any) -> Optional[str]:
    """The user Gradio's session names, read as Gradio's get_current_user reads it; None for none."""
    try:
        if app.auth_dependency is not None:
            return app.auth_dependency(request)
        token = (request.cookies.get(f"access-token-{app.cookie_id}")
                 or request.cookies.get(f"access-token-unsecure-{app.cookie_id}"))
        return app.tokens.get(token) if token else None
    except Exception:
        return None


def basic_user(request: Request, credentials: dict) -> Optional[str]:
    """
    The user whose Basic credentials match --api-auth's, decoded as FastAPI's
    HTTPBasic decodes them, the password compared in constant time on its
    UTF-8 bytes; None for none.
    """
    scheme, _, param = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        data = base64.b64decode(param).decode("ascii")
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None
    user, separator, password = data.partition(":")
    if not separator:
        return None
    stored = credentials.get(user)
    matches = hmac.compare_digest(password.encode("utf-8"), (stored if stored is not None else "").encode("utf-8"))
    return user if stored is not None and matches else None


# The names a WebUI listening on this computer alone is reached by, as the
# URL parser reads a Host: localhost, 127.0.0.1, [::1].
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def unknown_name(request: Optional[Request]) -> Optional[str]:
    """
    The name a request was addressed to, when the WebUI listens on this
    computer alone, the user's switch is on, and the name is none of
    localhost, an IP address or a name in the setting - another website's
    name pointed at this computer. An address passes: rebinding needs a
    name, as an address involves no DNS lookup.

    It passes too when the browser sent Sec-Fetch-Site, which it sends only
    over https or to this computer's own addresses - through an https tunnel,
    whatever name it passes on - unless an Origin or Referer it sent is a
    plain-http page's. A page under another site's name reaches the WebUI
    over plain http, and no browser adds the header there. The header is the
    sign, not the Origin or Referer: both WebUIs tell their page to send no
    Referer, so its GETs through a tunnel carry the header alone.
    None to go on; no browser sends a request with no Host.
    """
    if request is None or not listens_on_this_computer_alone() or not refuses_unknown_names():
        return None
    headers = request.headers
    host = headers.get("host")
    if not host:
        return None
    try:
        name = urlsplit("//" + host).hostname
    except ValueError:
        return host
    if name in LOOPBACK_NAMES or name in other_host_names() or is_address(name):
        return None
    if headers.get("sec-fetch-site") is not None:
        sent = (headers.get("origin"), headers.get("referer"))
        if not any(page and page.strip().lower().startswith("http:") for page in sent):
            return None
    return name or host


def is_address(name: Optional[str]) -> bool:
    """
    Whether a Host's name is an IP address, v4 or v6, rather than a name -
    but 0.0.0.0 and ::, which a browser on Linux or macOS sends to this
    computer, without Sec-Fetch-Site, from any site's page.
    """
    try:
        address = ipaddress.ip_address(name or "")
    except ValueError:
        return False
    return not address.is_unspecified


def from_elsewhere(request: Optional[Request]) -> Optional[str]:
    """
    The origin a request came from when it is another website's page, which
    the gate refuses; None for the WebUI's own page, and for a script or a
    tool, which sends none of these headers - or a direct call, with no
    request at all. An origin the WebUI lets read its answers
    (--cors-allow-origins, its pattern; not "*") is let through too, and
    one whose host the user named in the setting (named_host).
    """
    if request is None:
        return None
    headers = request.headers
    site = headers.get("sec-fetch-site")
    origin = headers.get("origin") or referer_origin(headers.get("referer"))
    if site is not None:
        if site.strip().lower() in OWN_REQUEST or allowed_origin(origin):
            return None
        return origin or UNNAMED
    if origin is None or allowed_origin(origin):
        return None
    if same_host(origin, headers.get("host")) or named_host(origin):
        return None
    return origin


def named_host(origin: str) -> bool:
    """
    Whether an origin's host is one the user named in the setting: their
    own proxy's page, whatever Host the proxy passes on - nginx's default
    rewrites it to 127.0.0.1 - at any port and either scheme.
    """
    try:
        name = urlsplit(origin).hostname
    except ValueError:
        return False
    return bool(name) and name in other_host_names()


# What a refusal names when the page said nothing of where it came from.
UNNAMED = "a page that did not say where it came from"


def referer_origin(referer: Optional[str]) -> Optional[str]:
    """
    The origin of the page a Referer names; None with no Referer. One that
    cannot be read is returned as it is: it names no host, and is refused.
    """
    if not referer:
        return None
    try:
        parts = urlsplit(referer)
    except ValueError:
        return referer
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else referer


def same_host(origin: str, host: Optional[str]) -> bool:
    """
    Whether an origin names the host and port the request was sent to, as
    the URL parser reads both: lower-cased, an IPv6 address unbracketed, a
    missing port the origin's scheme's. A user name, a port that is not a
    number, or anything that cannot be read is no match.
    """
    try:
        sent, to = urlsplit(origin), urlsplit("//" + (host or ""))
        default = DEFAULT_PORTS.get(sent.scheme.lower())
        if not sent.hostname or not to.hostname or sent.username is not None or to.username is not None:
            return False
        return (sent.hostname, sent.port or default) == (to.hostname, to.port or default)
    except ValueError:
        return False


def allowed_origin(origin: Optional[str]) -> bool:
    """
    Whether the WebUI lets this origin read its answers, read as it reads
    its list: an exact entry, or the whole origin matching its pattern. "*"
    would let every origin through, and counts for nothing here.
    """
    if not origin:
        return False
    listed, pattern = cors_origins()
    if origin in listed and origin != "*":
        return True
    return bool(pattern) and re.fullmatch(pattern, origin) is not None


MOST_ORIGINS_SAID = 20
_said: set = set()
_said_more = []
_said_lock = threading.Lock()


# As Forge's Settings page names them: while a name is refused, the
# extension's own settings window cannot save either, its route gated too.
ACCESS_SETTING = "Settings -> Model Manager -> Access -> Other names this computer is reached by over plain http"
ACCESS_SWITCH = "Refuse requests sent to a name this computer does not know"
OWN_PROXY = ("If it is this WebUI's own page, reached through a proxy of yours, add the proxy's name in "
             f"{ACCESS_SETTING}.")


def refused_from(origin: str, by_name: bool = False) -> JSONResponse:
    """
    What a request another website's page sent is answered - or, by_name,
    one addressed by a name the WebUI does not know - and the console's
    line about it: once for each origin or name until the WebUI restarts,
    for at most MOST_ORIGINS_SAID, so a page sending many cannot fill it.
    """
    origin = str(origin)[:100]
    with _said_lock:
        new = origin not in _said
        first = new and len(_said) < MOST_ORIGINS_SAID
        more = new and not first and not _said_more
        if first:
            _said.add(origin)
        if more:
            _said_more.append(origin)
    if by_name:
        error = (f"Refused: this WebUI was reached as {origin}, a name it does not know. If that is how you "
                 f"reach it, add the name in {ACCESS_SETTING}, or turn off {ACCESS_SWITCH} there.")
    else:
        # The one refusal a page of the user's own can meet with its first
        # answer allowed - a WebUI started for the network behind a proxy that
        # passes it on under another name - so its words carry the fix.
        error = ("Refused: this request came from another website's page, not the WebUI's own. "
                 f"{OWN_PROXY}")
    if first:
        say(error if by_name else f"Refused requests from {origin}: another website's page. To allow a page "
            f"of your own, start the WebUI with --cors-allow-origins naming it. {OWN_PROXY}")
    if more:
        say("Refusing requests from more websites' pages or names; they are not named.")
    return JSONResponse({"success": False, "refused": origin, "error": error}, status_code=403)


def refused(area: str) -> JSONResponse:
    """What a route of an area that is off answers."""
    return JSONResponse({"success": False, "error": why_off(area), "off": area}, status_code=403)


def streams_status(endpoint: Callable) -> Callable:
    """
    An endpoint that can say what it waits on before it answers (#132): a
    turn at Civitai's rate, a retry in Civitai's words, a slow step.

    Asked with Accept: application/x-ndjson, it runs on a thread of its own
    and answers in lines of JSON, as the search's stream does: {"type":
    "status", "text", "wait"} for each wait the Civitai client tells of
    (civitai.client.telling), then {"type": "result", "result": its answer}.
    Asked as before, it answers as before.
    """
    signature = inspect.signature(endpoint)

    @functools.wraps(endpoint)
    def answer(*args, mm_request: Request, **kwargs):
        if "application/x-ndjson" not in mm_request.headers.get("accept", ""):
            return endpoint(*args, **kwargs)
        return _status_stream(lambda: endpoint(*args, **kwargs))

    # FastAPI reads the parameters from the signature: the endpoint's, and
    # the request, to see what was asked for.
    answer.__signature__ = signature.replace(parameters=[
        *signature.parameters.values(),
        inspect.Parameter("mm_request", inspect.Parameter.KEYWORD_ONLY, annotation=Request)])
    return answer


def _status_stream(work: Callable[[], Any]) -> StreamingResponse:
    """`work`'s answer as the last line of a stream, after what it waited on."""
    events: "queue.Queue" = queue.Queue()

    def run():
        with telling(lambda said: events.put({"type": "status", **said})):
            try:
                reply = work()
            except Exception as e:
                reply = failed(e, "Streamed request")
        events.put({"type": "result", "result": json.loads(reply.body) if isinstance(reply, Response) else reply})

    def lines():
        threading.Thread(target=run, daemon=True, name="mm-status-stream").start()
        while True:
            event = events.get()
            yield json.dumps(event) + "\n"
            if event["type"] == "result":
                return

    # Proxies and buffering layers would otherwise hold the lines back.
    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
