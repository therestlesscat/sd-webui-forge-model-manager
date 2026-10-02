"""
Answers kept in memory for the server's life: a bounded map, under a lock.

Five caches were dicts of their own - Civitai's answers about versions for
Send to txt2img, what a missing resource will be called, file hashes, the
SFW check's verdicts, the versions an account bought - two of them without a
lock though threads share them, and none with a bound: kept for as long as
the WebUI ran, however many models a session saw. Each is small; together
they only grew.

A Remembered keeps at most `most` entries, dropping the one set longest ago;
setting one again makes it the newest. What an answer is worth - how old it
may be, when it must be asked again - stays the caller's: this keeps it,
and forgets it when there are too many.
"""
import threading
from collections import OrderedDict
from typing import Any, Hashable, Optional


class Remembered(object):
    """A map of at most `most` entries - None for no bound - safe across threads."""

    def __init__(self, most: Optional[int] = None):
        self.most = most
        self._entries: "OrderedDict[Hashable, Any]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            return self._entries.get(key, default)

    def __contains__(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._entries

    def __setitem__(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = value
            while self.most is not None and len(self._entries) > self.most:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
