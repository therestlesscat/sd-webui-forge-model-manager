"""
A random draw of Civitai's models, for "I'm feeling lucky": every model the
filters allow equally likely.

Civitai has no random order and no page numbers - `page` is ignored, and a
cursor is a position in a sort - so a random page is not a random sample: a
random date over-picks the quiet months, a random download count whatever
the spread of counts favours. Model ids are a fairer handle. Civitai numbers
models once, in order, and its search takes a list of them (`ids`) together
with its own filters - type, checkpoint type, base model, tag, period, NSFW -
answering only the ids that exist, are public and match. Ids picked at random
from 1 to the newest model's are a uniform sample of what matches. A text
query ignores `ids`, so a draw takes none; the filters checked here -
prompts, SFW images, file size - cost requests per model and are left out.

What Civitai was measured to do (October 2026):
  - about one id in five is a public model, one in seven without NSFW;
  - one request takes about 4,000 ids - 30 KB of URL was answered, 34 KB
    refused with 431, so the commas between them go unencoded (client.py) -
    and answers at most 100 models;
  - when more than 100 match, it answers the first 100 by its sort, with a
    cursor to the rest: taking only those favours its most downloaded.

So a batch is sized to stay under 100 matches, and a cut answer is followed
to its end. Ids cost more the fewer models match - a page of 20 from 2,000
matches takes nine batches - and listing every match costs more the more
there are: after each batch the draw estimates how many match and does
whichever is cheaper. The two meet near 1,300 matches, at about thirteen
requests for a page of 20, which is the slowest draw.

A draw leaves out what it is told to (#191) - the models the draws before it
showed under the same filters, and those the library has: their ids are
never asked, a listing drops them, and the estimate counts only the ids that
can still be drawn. What was shown is kept here, with the filters it was
drawn under; a draw under others starts afresh, and Start over forgets it.
"""
import math
import random
import threading
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from ..remembered import Remembered
from .client import CivitaiAPIError, CivitaiRateLimitError

# Ids per request: under the ~4,000 Civitai's URL limit allows, leaving room
# for the filters and for ids a digit longer.
MOST_IDS = 3500
# The most models Civitai answers in one request.
CIVITAI_PAGE = 100
# The matches a batch aims at: well under CIVITAI_PAGE, so an answer is
# seldom cut.
AIM_HITS = 50
# The first batch with no filter but NSFW, where about one id in five
# matches: some 50.
FIRST_BATCH_UNFILTERED = 250
# A stop for a Civitai that no longer answers as measured - one that ignores
# `ids`, say. A draw takes about thirteen at most when the first estimate is
# right, twice that when a listing has to be given up.
SAFETY_STOP = 30
# How long the newest model's id is taken as the newest.
NEWEST_ID_SECONDS = 60 * 60

_newest_lock = threading.Lock()
_newest: Dict[str, Any] = {"id": None, "at": 0.0}

# The models the draws have shown, and the filters they were drawn under.
_shown_lock = threading.Lock()
_shown: Dict[str, Any] = {"key": None, "ids": set()}

# (ids asked, ids that matched) per set of filters, from every draw so far:
# a second draw sizes its first batch from them, or lists at once.
_rates = Remembered(most=64)


def _filters_key(filters: Dict[str, Any]) -> Tuple:
    return tuple(sorted((name, tuple(value) if isinstance(value, list) else value)
                        for name, value in filters.items()))


def forget() -> None:
    """Forget the newest id, every hit rate and what was shown: for tests."""
    with _newest_lock:
        _newest.update(id=None, at=0.0)
    _rates.clear()
    forget_shown()


def shown_for(filters: Dict[str, Any]) -> Set[int]:
    """
    The models the draws have shown under these filters. Under others,
    none: what was shown is forgotten once the filters change.
    """
    key = _filters_key(filters)
    with _shown_lock:
        if _shown["key"] != key:
            _shown.update(key=key, ids=set())
        return set(_shown["ids"])


def remember_shown(filters: Dict[str, Any], model_ids: Iterable[int]) -> None:
    """These models were shown by a draw under these filters."""
    key = _filters_key(filters)
    with _shown_lock:
        if _shown["key"] != key:
            _shown.update(key=key, ids=set())
        _shown["ids"].update(model_ids)


def forget_shown() -> None:
    """Start over: every model can be drawn again."""
    with _shown_lock:
        _shown.update(key=None, ids=set())


class _Draw(object):
    """One draw's state: what it asked, what it found, what it cost."""

    def __init__(self, client, filters: Dict[str, Any], page_size: int,
                 rng: random.Random, now: Callable[[], float], leave_out: Iterable[int] = ()):
        self.client = client
        self.leave_out = set(leave_out)
        self.open_ids = 0           # ids from 1 to the newest not left out
        self.left_out_matches = 0   # matches a listing dropped as left out
        self.filters = filters
        self.page_size = page_size
        self.rng = rng
        self.now = now
        self.key = _filters_key(filters)
        # Anything but NSFW narrows the draw, often to a few in a thousand.
        self.filtered = any(value for name, value in filters.items() if name != "nsfw")
        self.prior_asked, self.prior_hits = _rates.get(self.key, (0, 0))
        self.newest = 0
        self.asked = 0              # ids asked this draw
        self.hits = 0               # of those, the ones that matched
        self.floor = 0              # matches there are at least, from a listing given up
        self.drawn = set()
        self.found: Dict[int, Dict[str, Any]] = {}
        self.requests = 0
        self.listing = 0            # models listed so far, while listing
        self.listed: Optional[int] = None   # every match, when they were listed
        self.chosen: Optional[List[Dict[str, Any]]] = None
        self.rate_limited = False
        self.stopped = False

    # ------------------------------------------------------------- asking
    def ask_newest(self) -> None:
        """The newest model's id - the top of the range ids are picked from."""
        with _newest_lock:
            if _newest["id"] and self.now() - _newest["at"] < NEWEST_ID_SECONDS:
                self.newest = _newest["id"]
                return
        self.requests += 1
        result = self.client.search_models(sort="Newest", nsfw=True, limit=20)
        # The highest of a page rather than the first, in case Newest puts an
        # older model with a new version first.
        ids = [m.get("id") for m in result.get("items") or [] if isinstance(m.get("id"), int)]
        if not ids:
            raise CivitaiAPIError("Civitai listed no models to draw from")
        with _newest_lock:
            _newest.update(id=max(ids), at=self.now())
        self.newest = max(ids)

    def search(self, **extra) -> Dict[str, Any]:
        self.requests += 1
        return self.client.search_models(**self.filters, limit=CIVITAI_PAGE, **extra)

    # ----------------------------------------------------------- deciding
    def matches(self) -> Optional[float]:
        """How many models match, as far as the ids asked tell - None before any."""
        asked = self.prior_asked + self.asked
        if not asked:
            return None
        return max((self.prior_hits + self.hits) / asked * self.open_ids, self.floor)

    def sample_cost(self, matches: float) -> float:
        """Requests ids would take to fill the rest of the page."""
        per_request = min(matches / self.open_ids * MOST_IDS, AIM_HITS) if self.open_ids else 0
        if per_request <= 0:
            return math.inf
        return math.ceil((self.page_size - len(self.found)) / per_request)

    def listing_cheaper(self, matches: float) -> bool:
        return max(1, math.ceil(matches / CIVITAI_PAGE)) <= self.sample_cost(matches)

    def batch_size(self) -> int:
        matches = self.matches()
        if matches is None:
            return MOST_IDS if self.filtered else FIRST_BATCH_UNFILTERED
        if matches <= 0:
            return MOST_IDS
        return max(1, min(MOST_IDS, int(AIM_HITS / (matches / max(self.open_ids, 1)))))

    def pick(self, size: int) -> List[int]:
        """`size` ids from 1 to the newest, none asked before this draw nor left out."""
        ids = []
        while len(ids) < size and len(self.drawn) < self.newest:
            value = self.rng.randint(1, self.newest)
            if value not in self.drawn:
                self.drawn.add(value)
                ids.append(value)
        return ids

    # -------------------------------------------------------------- doing
    def ask_ids(self, ids: List[int]) -> None:
        """What of `ids` matches - every page of it, when the answer is cut."""
        wanted = set(ids)
        cursor = None
        while True:
            result = self.search(ids=ids, cursor=cursor)
            items = result.get("items") or []
            for model in items:
                # Only what was asked: a Civitai that ignored `ids` would
                # otherwise hand over its own first page as a random one.
                model_id = model.get("id")
                if model_id in wanted and model_id not in self.found:
                    self.found[model_id] = model
                    self.hits += 1
            cursor = result.get("nextCursor")
            if not cursor or not items:
                break
            if self.requests >= SAFETY_STOP:
                self.stopped = True
                break
        self.asked += len(ids)

    def list_all(self, matches: float) -> Iterator[Tuple[str, Dict[str, Any]]]:
        """
        Every match, page by page, and the page drawn from all of them.

        The estimate can be low - one hit in a batch is a rough count - so
        the listing gives up once it has cost what ids would, given that
        there are at least as many matches as it has seen. Its models are
        then dropped: a listing's first pages are Civitai's most downloaded,
        not a sample.
        """
        models: Dict[int, Dict[str, Any]] = {}
        cursor = None
        pages = 0
        while True:
            if self.requests >= SAFETY_STOP:
                self.stopped = True
                return
            self.listing = len(models)
            yield "progress", self.progress()
            result = self.search(cursor=cursor)
            pages += 1
            for model in result.get("items") or []:
                if model.get("id") is not None:
                    models.setdefault(model["id"], model)
            cursor = result.get("nextCursor")
            if not cursor or not result.get("items"):
                break
            at_least = len(models) + 1
            if pages >= self.sample_cost(max(matches, at_least)):
                self.floor = max(self.floor, at_least)
                self.listing = 0
                return

        everything = [model for model_id, model in models.items() if model_id not in self.leave_out]
        self.left_out_matches = len(models) - len(everything)
        self.listed = len(everything)
        self.chosen = self.rng.sample(everything, min(self.page_size, len(everything)))

    def run(self) -> Iterator[Tuple[str, Dict[str, Any]]]:
        self.ask_newest()
        # Taken as asked already: pick() never draws them.
        self.drawn.update(i for i in self.leave_out if 1 <= i <= self.newest)
        self.open_ids = self.newest - len(self.drawn)
        while len(self.found) < self.page_size and not self.stopped:
            if self.requests >= SAFETY_STOP:
                self.stopped = True
                break
            matches = self.matches()
            if matches is not None and self.listing_cheaper(matches):
                yield from self.list_all(matches)
                if self.listed is not None:
                    return
                continue
            ids = self.pick(self.batch_size())
            if not ids:
                break               # every id there is has been asked
            yield "progress", self.progress()
            self.ask_ids(ids)

    # ---------------------------------------------------------- reporting
    def remember(self) -> None:
        if self.listed is not None:
            # Every match, those left out too: the next draw may leave out others.
            _rates[self.key] = (self.newest, self.listed + self.left_out_matches)
            return
        asked, hits = self.prior_asked + self.asked, self.prior_hits + self.hits
        if self.floor and (not asked or hits / asked * self.newest < self.floor):
            asked, hits = self.newest, self.floor
        if asked:
            _rates[self.key] = (asked, hits)

    def progress(self) -> Dict[str, Any]:
        return {"asked": self.asked, "found": len(self.found), "requests": self.requests,
                "listing": self.listing}

    def summary(self) -> Dict[str, Any]:
        if self.chosen is None:
            found = list(self.found.values())
            self.chosen = self.rng.sample(found, min(self.page_size, len(found)))
        matches = self.listed if self.listed is not None else self.matches()
        return {
            "models": self.chosen,
            "asked": self.asked,
            "requests": self.requests,
            "listed": self.listed is not None,
            "matches": None if matches is None else int(round(matches)),
            "left_out_matches": self.left_out_matches,
            "rate_limited": self.rate_limited,
            "stopped": self.stopped,
        }


def iter_random_models(client, filters: Dict[str, Any], page_size: int,
                       rng: Optional[random.Random] = None,
                       now: Callable[[], float] = time.monotonic,
                       leave_out: Iterable[int] = ()):
    """
    Draw up to `page_size` models at random from those Civitai's filters allow.

    Args:
        client: Civitai client. A 429 ends the draw with what it found; with
            `wait_on_rate_limit` off it comes at once.
        filters: client.search_models's own - types, base_models, nsfw, tag,
            checkpoint_type, period. Never a query or a sort.
        page_size: How many models to draw.
        rng, now: The randomness and the clock, for tests.
        leave_out: Model ids never to draw: shown before, or in the library.

    Yields:
        ("progress", {"asked", "found", "requests", "listing"}) before each
            batch of ids, and each page while listing every match
        ("done", summary) once, last: models (in random order), asked,
            requests, listed (drawn from every match), matches (how many:
            exact when listed, else an estimate; none left out),
            left_out_matches (those a listing dropped), rate_limited, stopped
    """
    draw = _Draw(client, dict(filters), max(1, int(page_size)), rng or random.Random(), now, leave_out)
    try:
        yield from draw.run()
    except CivitaiRateLimitError:
        draw.rate_limited = True
    if draw.newest:
        draw.remember()
    yield "done", draw.summary()
