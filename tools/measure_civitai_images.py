"""
How long the Civitai Images tab's requests take at scale, on v42's tables
(#283): migration v42 itself, then every level the tab asks for - every
image, each grouping, a group opened, two deep, searches - and a model's
gallery and the grid's NSFW filter. Run by hand, not by the tests: a time
differs by machine.

    python tools/measure_civitai_images.py [images]       default 117,142

Writes a made-up library at v41 to a throwaway file under tests/work/ - no
live rows - in the shape one library had on 2026-10-15: 9% of images in two
galleries or more, a distinct prompt per 1.4 images of about 600 characters,
0 to 12 LoRAs an image, records padded to 3.7 KB. Migrates it to v42, times
the tab through its endpoint's own code, then deletes it. Each time is the
best of three.
"""
import bisect
import json
import math
import os
import random
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()
import model_manager.gallery as gallery_module        # noqa: E402
gallery_module.TILE_PART = 100   # the tab's part, as it ships (#230)

from model_manager.api import gallery as api             # noqa: E402
from model_manager.db import migrations                  # noqa: E402
from model_manager.db.database import ModelsDatabase     # noqa: E402

WORK = os.path.join(TESTS, "work", "measure_civitai_images")
SEED = 181061363

# One library's shape (2026-10-15), scaled to the images asked for.
COPIES = {1: 109_400, 2: 5_460, 3: 1_337, 4: 519, 5: 231, 6: 87, 7: 54, 8: 54}
LEVELS = {1: 38_455, 2: 11_607, 4: 20_404, 8: 16_750, 16: 29_926}
LORAS = {0: 26_170, 1: 29_385, 2: 17_963, 3: 13_430, 4: 9_830, 5: 8_061, 6: 5_219, 7: 2_986, 8: 1_792,
         9: 1_122, 10: 700, 11: 300, 12: 184}
LIVE = 117_142


def picker(rnd, weights):
    """A random index by `weights`."""
    total, cum = sum(weights), []
    acc = 0.0
    for w in weights:
        acc += w / total
        cum.append(acc)
    return lambda: min(bisect.bisect_left(cum, rnd.random()), len(weights) - 1)


def spread(rnd, table, count):
    """`count` values drawn in `table`'s proportions, shuffled."""
    values = [v for v, n in table.items() for _ in range(math.ceil(n * count / LIVE))][:count]
    rnd.shuffle(values)
    return values


def text(rnd, word, median):
    words, size, length = [], 0, max(4, int(rnd.lognormvariate(math.log(median), 0.6)))
    while size < length:
        words.append(f"w{word()}")
        size += len(words[-1]) + 2
    return ", ".join(" ".join(words[i:i + 3]) for i in range(0, len(words), 3))


def fill(path, count):
    """A v41 library of `count` made-up images, in the shape above."""
    rnd = random.Random(283)
    connection = sqlite3.connect(path)
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT)")
    migrations.run_migrations(cursor, 0, 41, path, os.path.dirname(path))
    connection.commit()
    versions = max(40, count * 1334 // LIVE)
    cursor.executemany("INSERT INTO models (id, name, type) VALUES (?, ?, ?)",
                       [(v, f"model {v}", rnd.choice(("LORA", "LORA", "Checkpoint"))) for v in range(1, versions + 1)])
    cursor.executemany("INSERT INTO versions (id, model_id, base_model, version_name) VALUES (?, ?, ?, ?)",
                       [(v, v, f"base{min(int(rnd.expovariate(0.25)), 27)}", f"v{v}") for v in range(1, versions + 1)])
    cursor.executemany("INSERT INTO files (file_path, file_name, version_id, file_type) VALUES (?, ?, ?, ?)",
                       [(f"C:\\models\\{v}.safetensors", f"{v}.safetensors", v, "LORA") for v in range(1, versions + 1)])
    word = picker(rnd, [1 / (i + 1) ** 1.05 for i in range(176_713)])
    distinct = count * 80_867 // LIVE
    prompts = [text(rnd, word, 516) for _ in range(distinct)]
    negatives = [text(rnd, word, 209) for _ in range(max(1, count * 26_914 // LIVE))]
    lora = picker(rnd, [1 / (i + 1) for i in range(28_325)])
    gallery = picker(rnd, [rnd.paretovariate(1.0) for _ in range(versions)])
    copies, levels, loras = spread(rnd, COPIES, count), spread(rnd, LEVELS, count), spread(rnd, LORAS, count)
    places, rows = {}, []
    for i in range(count):
        image_id = 10_000_000 + i
        meta = {"prompt": prompts[i % distinct] if rnd.random() < 0.97 else None,
                "negativePrompt": rnd.choice(negatives) if rnd.random() < 0.86 else None,
                "steps": 30, "sampler": "Euler a", "cfgScale": 5,
                "civitaiResources": [{"type": "LORA", "modelVersionId": 500_000 + lora(), "modelId": 1,
                                      "name": "lora", "modelVersionName": "v1"} for _ in range(loras[i])]}
        when = time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                             time.gmtime(1_600_000_000 + rnd.randint(0, 1313) * 86_400 + rnd.randint(0, 86_399)))
        width, height = 64 * (8 + rnd.randint(0, 23)), 64 * (8 + rnd.randint(0, 29))
        record = {"id": image_id, "url": f"https://image.example/{image_id:x}/{'a' * 100}.jpeg",
                  "width": width, "height": height, "type": "image", "createdAt": when,
                  "stats": {"pad": "x" * 2400}, "meta": meta}
        data = json.dumps(record)
        for _ in range(copies[i]):
            v = gallery() + 1
            places[v] = places.get(v, 0) + 1
            rows.append((image_id, v, 1 + places[v] // 100, places[v] % 100, record["url"], width, height,
                         levels[i], when, data))
        if len(rows) >= 5000:
            cursor.executemany("INSERT OR IGNORE INTO images (id, version_id, page, position, url, width, height, "
                               "effective_nsfw_level, created_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            rows = []
    cursor.executemany("INSERT OR IGNORE INTO images (id, version_id, page, position, url, width, height, "
                       "effective_nsfw_level, created_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()
    return prompts


def best(read, runs=3):
    """
    The best of `runs` timings of `read()`, in milliseconds, and what it
    answered - each with the endpoint's kept group lists emptied, so a
    grouping's work is timed, not the list it kept.
    """
    times, answer = [], None
    for _ in range(runs):
        api._groups_kept.clear()
        start = time.perf_counter()
        answer = read()
        times.append((time.perf_counter() - start) * 1000)
    return min(times), answer


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else LIVE
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    path = os.path.join(WORK, "models.db")
    start = time.perf_counter()
    prompts = fill(path, count)
    print(f"{count:,} made-up images written at v41 in {time.perf_counter() - start:.1f} s")
    try:
        start = time.perf_counter()
        db = ModelsDatabase(extension_dir=ROOT, custom_db_path=path)
        print(f"migrated to v42, backup included: {time.perf_counter() - start:.1f} s\n")

        def browse(hide=False, **kw):
            return lambda: api.browse_page(db, SEED, hide, 1, **kw)

        def show(label, read):
            ms, answer = best(read)
            tiles = answer.get("tiles", answer) if isinstance(answer, dict) else answer
            print(f"{label:58} {ms:8.1f} ms   {len(tiles) if hasattr(tiles, '__len__') else ''}")
            return answer

        show("every image, a part", browse())
        show("every image, NSFW hidden", browse(hide=True))
        for by in ("model", "base_model", "type", "size", "prompt", "loras", "day"):
            groups = show(f"grouped by {by}", browse(group=by))
            first = (groups.get("tiles") or [{}])[0].get("group", {}).get("key", "v")
            show(f"   a group of it opened", browse(group=by, in_group=str(first)))
        for a, b in (("model", "day"), ("prompt", "loras"), ("day", "loras")):
            groups = api.browse_page(db, SEED, False, 1, group=a)
            first = (groups.get("tiles") or [{}])[0].get("group", {}).get("key", "v")
            show(f"two deep: a {a} group, by {b}", browse(group=f"{a}>{b}", in_group=str(first)))
        words = prompts[0].replace(",", "").split()
        for search in (words[0], words[len(words) // 2], " ".join(words[:3])):
            show(f"search '{search[:30]}'", browse(search=search))
            show(f"   grouped by model", browse(search=search, group="model"))
        busiest = db._get_connection().execute(
            "SELECT version_id FROM image_galleries GROUP BY version_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
        show("a model's gallery, a page, \"Hide images with no prompt\"",
             lambda: db.get_image_page(busiest, 0, 100, 2, True))
        show("   its switches' counts", lambda: [db.get_image_counts(busiest, 2, True)])
        show("the grid's NSFW filter: every version's worst level", lambda: db._get_connection().execute(
            "SELECT version_id, MAX(effective_nsfw_level) FROM image_galleries GROUP BY version_id").fetchall())
    finally:
        try:
            db._get_connection().close()
        except Exception:
            pass
        shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
