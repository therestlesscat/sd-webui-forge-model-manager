"""
What the extension writes to the console - every "[ModelManager]" line - and
the last of those lines, kept for the page: the sync's log panel shows them as
they come (/model-manager/sync/progress?since=). Everything the extension says
goes through say(); a print of its own would reach the console and not the
panel (console_test.py finds one).
"""
import threading
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Tuple

#: How many lines are kept: a full sync of a large library says far more,
#: and the page wants the latest.
KEPT = 2000

_lines: deque = deque(maxlen=KEPT)      # (number, time, message)
_count = 0
_lock = threading.Lock()


def say(message: str) -> None:
    """Write a line to the console, as "[ModelManager] message", and keep it."""
    global _count
    print(f"[ModelManager] {message}")
    with _lock:
        _count += 1
        _lines.append((_count, datetime.now().strftime("%H:%M:%S"), str(message)))


def said() -> int:
    """How many lines have been said so far: where a reader of what comes next starts."""
    with _lock:
        return _count


def since(number: int) -> Tuple[List[Dict[str, Any]], int]:
    """
    The kept lines said after line `number`, oldest first, and the number to
    ask from next time. Lines no longer kept are gone: a reader that falls
    more than KEPT behind gets the latest.
    """
    with _lock:
        lines = [{"n": n, "time": time, "text": text} for n, time, text in _lines if n > number]
        return lines, _count
