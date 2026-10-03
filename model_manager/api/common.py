"""
What the endpoint modules share and none of them owns: no endpoints here.

The card-size parser was written four times, and the same try/except that
logs a failure and answers 500 twenty-four times.
"""
import functools
import inspect
import json
import queue
import threading
import traceback
from typing import Any, Callable, Optional, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..civitai.client import telling
from ..forge_host import DEFAULTS, setting


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
    if doing:
        print(f"[ModelManager] {doing}: {e}")
    traceback.print_exc()
    return JSONResponse({"success": False, "error": str(e)}, status_code=500)


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
