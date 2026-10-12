"""
How long the Generations tab's and the galleries' requests take at scale, on
the tables of v36 and of v37 (#231). Run by hand, not by the tests: a time
differs by machine.

    python tools/measure_generations.py [images]       default 76,000

Writes a synthetic library at v36 to a throwaway file under tests/work/ - no
live rows - with the live library's mix: about one distinct prompt per 2.4
images, 650 bytes each; 40 checkpoints; 0 to 3 LoRAs an image; rows padded to
real sizes. Times every request through the v36 reads (tests/v36_generations.py),
migrates the file, times them again through today's code, then deletes it.
Each time is the best of three.
"""
import json
import os
import random
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()
opts.model_manager_gallery_page_size = 100

import generation_fixture                                # noqa: E402
import v36_generations as v36                            # noqa: E402
from model_manager.api import generations as api         # noqa: E402
from model_manager.db.database import ModelsDatabase     # noqa: E402

WORK = os.path.join(TESTS, "work", "measure_generations")


def fill(connection, count):
    """`count` synthetic images at v36, in batches of 1 to 4."""
    rnd = random.Random(231)
    words = [f"w{i}" for i in range(3000)] + ["red", "hair", "girl", "forest", "city", "night"]
    prompts = [" ".join(rnd.choices(words, k=rnd.randint(80, 150))) for _ in range(count * 3 // 10)]
    checkpoints = [os.path.join(WORK, "Stable-diffusion", f"ckpt_{i:02}.safetensors") for i in range(40)]
    loras = [os.path.join(WORK, "Lora", f"lora_{i:02}.safetensors") for i in range(80)]
    for index, path in enumerate(checkpoints):
        generation_fixture.library_file(connection, path, index + 1,
                                        ["SDXL 1.0", "Pony", "Illustrious", "Flux.1 D"][index % 4], "Checkpoint")
    meta = json.dumps({"steps": 30, "sampler": "Euler a", "padding": "x" * 1200})
    generations, images, files = [], [], []
    generation_id = image_id = 0
    while image_id < count:
        generation_id += 1
        size = rnd.choice([1, 1, 2, 4])
        prompt = rnd.choice(prompts)
        checkpoint = rnd.choice(checkpoints)
        used = rnd.sample(loras, rnd.choice([0, 1, 1, 2, 3]))
        when = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(1_700_000_000 + generation_id * 1500))
        generations.append((generation_id, when, "txt2img", prompt, "bad hands", checkpoint, prompt + " " + "y" * 800,
                            size, json.dumps({"p": "z" * 3000}), json.dumps({"s": "z" * 3000})))
        for position in range(size):
            image_id += 1
            lora_json = json.dumps([{"name": os.path.basename(p)[:-12], "path": p, "te_multiplier": 0.8}
                                    for p in used])
            images.append((image_id, generation_id, position, 0, os.path.join(WORK, f"{image_id}.png"),
                           prompt + " " + "y" * 800, meta, prompt + (f" v{rnd.randint(0, 3)}" if position else ""),
                           "bad hands", image_id, lora_json,
                           *rnd.choice([(832, 1216), (1024, 1024), (1216, 832), (512, 768)]),
                           rnd.choice([1, 1, 1, 2, 4, 8, 16, None])))
            files.extend((p, image_id, generation_id) for p in [checkpoint] + used)
    connection.executemany("INSERT INTO generations (id, created_at, mode, prompt, negative_prompt, checkpoint_path, "
                           "infotext, image_count, params, settings) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", generations)
    connection.executemany("INSERT INTO generation_images (id, generation_id, position, iteration, path, infotext, "
                           "meta, prompt, negative_prompt, seed, loras, width, height, prompt_nsfw_level) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", images)
    connection.executemany("INSERT OR IGNORE INTO generation_files (file_path, image_id, generation_id) VALUES (?, ?, ?)",
                           files)
    connection.commit()
    return checkpoints[7]


def best(read, runs=3):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        read()
        times.append((time.perf_counter() - start) * 1000)
    return min(times)


def requests(browse, page, db, checkpoint):
    first = browse(db, False)
    generation = first["tiles"][0]["generation"]["id"]
    model = browse(db, False, group="model")["tiles"][0]["group"]["id"]
    return {
        "Top level, part 1": lambda: browse(db, False),
        "Top level, part 1, NSFW hidden": lambda: browse(db, True),
        "Top level, part 20": lambda: browse(db, False, page=20),
        **{f"Grouped by {g}": (lambda g=g: browse(db, False, group=g)) for g in api.GROUPINGS},
        "Grouped twice, model then prompt as written": lambda: browse(db, False, group="model>prompt_written"),
        "Inside a model's group": lambda: browse(db, False, group="model", in_group=model),
        "Inside a generation": lambda: browse(db, False, generation=generation),
        "Search, one word": lambda: browse(db, False, search="red"),
        "Your generations of a checkpoint, a page": lambda: page(db, checkpoint, True, False, 1),
    }


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 76000
    shutil.rmtree(WORK, ignore_errors=True)
    path, connection = generation_fixture.v36_database(WORK)
    start = time.perf_counter()
    checkpoint = fill(connection, count)
    print(f"{count:,} images written at v36 in {time.perf_counter() - start:.1f} s")

    old = v36.V36(connection)
    before = {label: best(read) for label, read in requests(v36.browse_page, v36.generation_page, old,
                                                            checkpoint).items()}
    connection.close()
    start = time.perf_counter()
    db = ModelsDatabase(extension_dir=ROOT, custom_db_path=path)
    print(f"Migrated to v37 in {time.perf_counter() - start:.1f} s")
    after = {label: best(read) for label, read in requests(api.browse_page, api.generation_page, db,
                                                           checkpoint).items()}

    print(f"\n{'Request':<46} {'v36':>9} {'v37':>9}")
    for label in before:
        print(f"{label:<46} {before[label]:7.0f} ms {after[label]:7.0f} ms")
    db._get_connection().close()
    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
