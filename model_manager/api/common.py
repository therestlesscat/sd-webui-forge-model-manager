"""
What the endpoint modules share and none of them owns: no endpoints here.

The card-size parser was written four times, and the same try/except that
logs a failure and answers 500 twenty-four times.
"""
import traceback
from typing import Optional, Tuple

from fastapi.responses import JSONResponse

DEFAULT_CARD_SIZE = (200, 280)


def card_size(setting: str) -> Tuple[int, int]:
    """
    A tab's card size, as its setting holds it - "WIDTHxHEIGHT" - or the
    default when the setting is missing or cannot be read.
    """
    try:
        from modules import shared
        text = str(getattr(shared.opts, setting, "") or "").lower()
        if "x" in text:
            width, height = text.split("x")[:2]
            return int(width.strip()), int(height.strip())
    except (ImportError, ValueError):
        pass
    return DEFAULT_CARD_SIZE


def failed(e: Exception, doing: Optional[str] = None) -> JSONResponse:
    """
    Log a failed request - what it was doing, and the traceback - and answer
    it as every endpoint does: success false, the error, 500.
    """
    if doing:
        print(f"[ModelManager] {doing}: {e}")
    traceback.print_exc()
    return JSONResponse({"success": False, "error": str(e)}, status_code=500)
