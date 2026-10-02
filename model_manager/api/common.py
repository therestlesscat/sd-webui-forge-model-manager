"""
What the endpoint modules share and none of them owns: no endpoints here.

The card-size parser was written four times, and the same try/except that
logs a failure and answers 500 twenty-four times.
"""
import traceback
from typing import Any, Optional, Tuple

from fastapi.responses import JSONResponse

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
