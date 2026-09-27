"""
Train the NSFW prompt model from Civitai directly, rather than from a library.

    python tools/train_nsfw_from_civitai.py pull  <data.db> [--models 1000] [--images 1000]
    python tools/train_nsfw_from_civitai.py train <data.db> [--out <file>] [--clean 2] [--evaluate <models.db>]
    python tools/train_nsfw_from_civitai.py evaluate <model file> <models.db>

Run it with the WebUI's Python. A Civitai API key is needed - prompts come
from an endpoint that answers only with one - in CIVITAI_API_KEY or --api-key.

pull: the models with the most images (Civitai's "Most Images" sort, which
it accepts but does not document), and each model's images with the most
reactions, version by version, newest first - asking for a whole model's
images at once runs 20 s on Civitai and comes back empty - at every rating, because the model learns the difference between
explicit and safe prompts and has nothing to learn from one side alone. The
image list comes without prompts; they are fetched 30 images at a time. It
is all kept in data.db, never in a library, and a model fully fetched is not
fetched again: a pull that is stopped carries on where it was.

train: as tools/train_nsfw_model.py trains from a library, from the same
code. --evaluate judges a library with the result - a library the model has
never seen, so what it raises there is what the setting promises. A model
trained on a library forgives that library's own under-rated images.
"""
import argparse
import json
import os
import random
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]
import train_nsfw_model as trainer                        # noqa: E402
from model_manager import nsfw                            # noqa: E402
from model_manager.civitai import CivitaiClient           # noqa: E402
from model_manager.civitai.client import CivitaiNotFoundError  # noqa: E402
from model_manager.civitai.prompt_filter import (         # noqa: E402
    apply_generation_data, generation_ids_needing_lookup)

DEFAULT_OUT = os.path.join(ROOT, "tests", "work", "nsfw_from_civitai", "model.json.gz")


#: Requests per second never to exceed. Half of what the extension's own
#: client allows (civitai/client.py, 10, measured to be served without
#: complaint): a pull runs for an hour or more, and Civitai publishes no limit
#: and asks that none be aimed for.
CEILING = 5.0


def backoff(attempt):
    """Civitai's advice for a 429 or a 5xx: exponential, from about 1 s, capped at about 30."""
    return min(30.0, 2.0 ** (attempt - 1))


class AdaptiveRate:
    """
    Requests spaced evenly, at no more than the ceiling. Until Civitai first
    answers "too many requests" the rate climbs by 1% an answer, from where it
    started to the ceiling. A throttle then pauses every worker - 1 s, then
    2, 4, ... to 30 s for throttles in a row, as Civitai's documentation
    advises, or the Retry-After it sent if that is longer - and cuts the rate
    by 30%, where it stays: climbing back would be aiming for the limit,
    which Civitai asks clients not to do. One throttle counts once, however
    many workers hit it together.
    """

    #: Requests answered in a row that end a run of throttles.
    CALM_AFTER = 20

    def __init__(self, start, ceiling=CEILING, floor=0.5):
        self.ceiling, self.floor = ceiling, floor
        self.rate = min(start, ceiling)
        self.next_slot = 0.0
        self.paused_until = 0.0
        self.in_a_row = 0          # throttles without CALM_AFTER answers between them
        self.answered = 0          # answers since the last throttle
        self.requests = self.throttles = 0
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = time.time()
            slot = max(now, self.next_slot, self.paused_until)
            self.next_slot = slot + 1.0 / self.rate
        time.sleep(max(0.0, slot - time.time()))

    def succeeded(self):
        with self._lock:
            self.requests += 1
            self.answered += 1
            if self.answered >= self.CALM_AFTER:
                self.in_a_row = 0
            if not self.throttles:
                self.rate = min(self.ceiling, self.rate * 1.01)

    def throttled(self, retry_after=None):
        with self._lock:
            now = time.time()
            self.throttles += 1
            if now < self.paused_until:
                return        # a worker caught in the pause already under way
            self.in_a_row += 1
            self.answered = 0
            pause = max(backoff(self.in_a_row), retry_after or 0.0)
            self.paused_until = now + pause
            self.rate = max(self.floor, self.rate * 0.7)


def adaptive_requests(client, limiter, max_throttles=30, max_errors=5):
    """
    Replace the client's requests with ones paced by `limiter` and that never
    give a throttled request up: the client's own would, after three tries,
    and its prompt lookup drops a failed batch without a word - images stored
    with no prompt. Server errors and timeouts are retried with backoff.
    """
    session = client.session

    def request(method, endpoint, params=None, absolute_url=None):
        url = absolute_url or f"{client.BASE_URL}{endpoint}"
        throttles = errors = 0
        while True:
            limiter.acquire()
            try:
                response = session.request(method, url, params=params, timeout=client.REQUEST_TIMEOUT)
            except Exception as e:
                errors += 1
                if errors > max_errors:
                    raise
                time.sleep(backoff(errors) + random.random())
                continue
            if response.status_code == 429:
                throttles += 1
                if throttles > max_throttles:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                limiter.throttled(float(retry_after) if retry_after else None)
                continue
            if response.status_code == 404:
                raise CivitaiNotFoundError(f"Not found: {endpoint}")
            if response.status_code >= 500:
                errors += 1
                if errors > max_errors:
                    response.raise_for_status()
                time.sleep(backoff(errors) + random.random())
                continue
            response.raise_for_status()
            limiter.succeeded()
            return response.json()

    client._request = request


class InFlight:
    """How many models the workers are fetching right now, for the progress line."""

    def __init__(self):
        self.count = 0
        self._lock = threading.Lock()

    def change(self, by):
        with self._lock:
            self.count += by


def fetch_model(client, model_id, versions, wanted, in_flight=None):
    """
    A model's images, version by version, with their prompts; for a worker.
    Returns (model id, images, seconds it took).
    """
    started = time.time()
    if in_flight:
        in_flight.change(1)
    try:
        return model_id, _fetch_images(client, versions, wanted), time.time() - started
    finally:
        if in_flight:
            in_flight.change(-1)


def _fetch_images(client, versions, wanted):
    images = []
    for version_id in versions:
        cursor = None
        while len(images) < wanted:
            params = {"modelVersionId": version_id, "limit": 100, "nsfw": "X", "sort": "Most Reactions"}
            if cursor:
                params["cursor"] = cursor
            data = client._request("GET", "/images", params)
            items = (data.get("items") or [])[:wanted - len(images)]
            if not items:
                break
            ids = generation_ids_needing_lookup(items)
            batch = client.GENERATION_DATA_BATCH
            for start in range(0, len(ids), batch):
                apply_generation_data(items, client.get_generation_data(ids[start:start + batch]))
            images.extend(items)
            cursor = (data.get("metadata") or {}).get("nextCursor")
            if not cursor:
                break
        if len(images) >= wanted:
            break
    return images


def kept(image):
    """
    What training reads of an image, and nothing else: its ratings, post,
    prompts - ADetailer's and hires' included - and the resources it names,
    by id and hash. Civitai's whole record is about 3.4 KB; a million of them
    would be 3.4 GB.
    """
    meta = image.get("meta") if isinstance(image.get("meta"), dict) else {}
    out = {k: image.get(k) for k in ("id", "browsingLevel", "nsfwLevel", "nsfw", "postId")}
    texts = ("prompt", "negativePrompt") + nsfw.EXTRA_PROMPTS + nsfw.EXTRA_NEGATIVES
    out["meta"] = {k: meta.get(k) for k in texts if meta.get(k)}
    out["meta"]["civitaiResources"] = [{"modelVersionId": r["modelVersionId"]}
                                       for r in meta.get("civitaiResources") or []
                                       if isinstance(r, dict) and r.get("modelVersionId")]
    out["meta"]["resources"] = [{"hash": r["hash"]} for r in meta.get("resources") or []
                                if isinstance(r, dict) and r.get("hash")]
    return json.dumps(out, separators=(",", ":"))


def open_data(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS models (id INTEGER PRIMARY KEY, rank INTEGER, name TEXT,
                                           versions TEXT, images INTEGER, done INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS images (id INTEGER PRIMARY KEY, model_id INTEGER, data TEXT NOT NULL);
    """)
    return db


def pull(args):
    key = args.api_key or os.environ.get("CIVITAI_API_KEY")
    if not key:
        sys.exit("A Civitai API key is needed: set CIVITAI_API_KEY or pass --api-key.")
    client = CivitaiClient(key)
    limiter = AdaptiveRate(args.rate, args.max_rate)
    adaptive_requests(client, limiter)
    db = open_data(args.data)

    # The models, in order, once.
    have = db.execute("SELECT COUNT(*) FROM models").fetchone()[0]
    cursor = None
    while have < args.models:
        page = client.search_models(sort="Most Images", nsfw=True, limit=100, cursor=cursor)
        for model in page["items"]:
            if have >= args.models:
                break
            versions = [v["id"] for v in model.get("modelVersions") or [] if v.get("id")]
            db.execute("INSERT OR IGNORE INTO models (id, rank, name, versions) VALUES (?, ?, ?, ?)",
                       (model["id"], have + 1, model.get("name"), json.dumps(versions)))
            have = db.execute("SELECT COUNT(*) FROM models").fetchone()[0]
        db.commit()
        cursor = (page.get("metadata") or {}).get("nextCursor")
        if not cursor:
            break
    todo = db.execute("SELECT id, rank, name, versions FROM models WHERE done = 0 ORDER BY rank LIMIT ?",
                      (args.models,)).fetchall()
    print(f"{have} models listed; {len(todo)} still to fetch")

    started = time.time()
    names = {model_id: (rank, name) for model_id, rank, name, _ in todo}
    in_flight = InFlight()
    stored = [0]
    finished = threading.Event()

    def progress():
        # While workers are busy between finished models, the log would say
        # nothing for a quarter of a minute; this says it is working.
        while not finished.wait(args.progress_every):
            elapsed = time.time() - started
            print(f"  ... {in_flight.count} model{'' if in_flight.count == 1 else 's'} in flight, {limiter.requests:,} requests, "
                  f"{limiter.rate:.1f} req/s now, {limiter.requests / max(elapsed, 1):.1f} on average, "
                  f"{limiter.throttles} throttled, {stored[0]:,} images stored")

    reporter = threading.Thread(target=progress, daemon=True)
    reporter.start()
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs = [pool.submit(fetch_model, client, model_id, json.loads(versions or "[]"),
                                args.images, in_flight)
                    for model_id, _, _, versions in todo]
            for n, job in enumerate(as_completed(jobs), 1):
                try:
                    model_id, images, fetch_seconds = job.result()
                except Exception as e:
                    # Left not done, so the next run tries it again.
                    print(f"  a model failed, to be retried next run: {e}")
                    continue
                write_started = time.perf_counter()
                db.executemany("INSERT OR IGNORE INTO images (id, model_id, data) VALUES (?, ?, ?)",
                               [(i["id"], model_id, kept(i)) for i in images if i.get("id")])
                db.execute("UPDATE models SET done = 1, images = ? WHERE id = ?", (len(images), model_id))
                db.commit()
                write_ms = (time.perf_counter() - write_started) * 1000
                stored[0] += len(images)
                elapsed = time.time() - started
                rank, name = names[model_id]
                print(f"[{rank:>4}] {len(images):>5} images  {(name or '')[:30]:30}  {n}/{len(todo)}  "
                      f"fetched in {fetch_seconds:.1f} s, written in {write_ms:.0f} ms; "
                      f"about {elapsed / n * (len(todo) - n) / 60:.0f} min to go")
    finally:
        finished.set()
    total = db.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    print(f"done: {total:,} images in {args.data}")
    client.close()


def evaluate(model, library):
    """Judge a library the model never saw, at each calibrated percentage."""
    rows = trainer.read_library(library)
    levels = np.array([r[0] for r in rows])
    weights, bits, bias = dict(zip(model["keys"], model["values"])), model["bits"], model["bias"]
    features = model.get("features", 1)
    scores = np.array([bias + sum(weights.get(nsfw.feature_hash(f, bits), 0.0)
                                  for f in nsfw.image_features(meta, features)) for _, meta, _ in rows])
    safe = np.isin(levels, (nsfw.PG, nsfw.PG13))
    explicit = np.isin(levels, (nsfw.X, nsfw.XXX))
    print(f"\njudging {library}: {len(rows):,} prompts, none seen in training")
    print("setting  PG/PG-13 raised        X/XXX caught   R caught")
    for percent, threshold in model["calibration"]:
        raised = int((scores[safe] > threshold).sum())
        print(f"{percent:>6}%  {raised:>6} ({raised / max(1, safe.sum()):5.2%})     "
              f"{np.mean(scores[explicit] > threshold):6.1%}      {np.mean(scores[levels == nsfw.R] > threshold):6.1%}")


def train(args):
    model = trainer.build_model(trainer.read_library(args.data), args.clean)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    trainer.write_model(model, args.out)
    if args.evaluate:
        evaluate(model, args.evaluate)


def evaluate_file(args):
    import gzip
    with gzip.open(args.model, "rt", encoding="utf-8") as f:
        evaluate(json.load(f), args.library)


def main():
    # Model names hold characters a Windows console cannot print.
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    steps = parser.add_subparsers(dest="step", required=True)
    p = steps.add_parser("pull", help="fetch models, images and prompts from Civitai")
    p.add_argument("data")
    p.add_argument("--models", type=int, default=1000)
    p.add_argument("--images", type=int, default=1000)
    p.add_argument("--api-key")
    p.add_argument("--rate", type=float, default=CEILING, help="requests per second to start at")
    p.add_argument("--max-rate", type=float, default=CEILING,
                   help="requests per second never to exceed (5, half what the extension's client allows)")
    p.add_argument("--workers", type=int, default=12, help="models fetched at once")
    p.add_argument("--progress-every", type=float, default=5.0,
                   help="seconds between progress lines while models are being fetched")
    t = steps.add_parser("train", help="train a model from pulled data")
    t.add_argument("data")
    t.add_argument("--out", default=DEFAULT_OUT)
    t.add_argument("--clean", type=float, default=trainer.CLEAN_PERCENT,
                   help="percent of PG/PG-13 left out as suspected mis-ratings; 0 for none")
    t.add_argument("--evaluate", help="a library's models.db to judge with the result")
    e = steps.add_parser("evaluate", help="judge a library with a model file already written")
    e.add_argument("model")
    e.add_argument("library")
    args = parser.parse_args()
    {"pull": pull, "train": train, "evaluate": evaluate_file}[args.step](args)


if __name__ == "__main__":
    main()
