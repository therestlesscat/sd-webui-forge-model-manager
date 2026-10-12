"""
A database at schema v36 holding your generations, for the suites of #231:
made by the migrations up to v36 and written as the recorder of 0.57.1 wrote
(tests/v36_generations.py), so migration v37 and the new reads meet what
libraries hold.

`varied()` writes a small library with everything the reads and the
migration can trip on; `bulk()` writes many plain images fast.
"""
import json
import os
import random
import shutil
import sqlite3
from datetime import datetime, timedelta

from model_manager.db import migrations
import v36_generations


def v36_database(directory):
    """An empty database at v36 in `directory`, emptied first: (path, connection)."""
    directory = os.path.abspath(directory)
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory)
    path = os.path.join(directory, "models.db")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT)")
    migrations.run_migrations(cursor, 0, 36, path, directory)
    connection.commit()
    return path, connection


def library_file(connection, path, version_id=None, base_model=None, file_type=None):
    """A file the library holds, with its version's base model."""
    if version_id is not None:
        connection.execute("INSERT OR IGNORE INTO models (id, name) VALUES (?, ?)",
                           (version_id, f"model {version_id}"))
        connection.execute("INSERT OR IGNORE INTO versions (id, model_id, base_model) VALUES (?, ?, ?)",
                           (version_id, version_id, base_model))
    connection.execute("INSERT INTO files (file_path, file_name, version_id, file_type) VALUES (?, ?, ?, ?)",
                       (path, os.path.basename(path), version_id, file_type))


def varied(connection, root):
    """
    About forty generations with what the reads and the migration can trip
    on. Returns facts: the file paths by name, and the task the Queue linked.
    """
    lib = os.path.join(root, "lib")
    p = {
        "a": os.path.join(lib, "Stable-diffusion", "a.safetensors"),
        "b": os.path.join(lib, "Stable-diffusion", "b.safetensors"),
        # Another checkpoint of the same file name: one Model group.
        "a2": os.path.join(lib, "Stable-diffusion", "sub", "a.safetensors"),
        # One the library does not hold.
        "x": os.path.join(lib, "Stable-diffusion", "x.safetensors"),
        "vae": os.path.join(lib, "VAE", "ae.safetensors"),
        "te": os.path.join(lib, "text_encoder", "t5.safetensors"),
        "unknown_module": os.path.join(lib, "VAE", "other.safetensors"),
        "hr": os.path.join(lib, "Stable-diffusion", "hr.safetensors"),
        "refiner": os.path.join(lib, "Stable-diffusion", "refiner.safetensors"),
    }
    for name in "lmnop":
        p[name] = os.path.join(lib, "Lora", f"{name}.safetensors")
    library_file(connection, p["a"], 1, "SDXL 1.0", "Checkpoint")
    library_file(connection, p["b"], 2, "Pony", "Checkpoint")
    library_file(connection, p["a2"], 3, "Illustrious", "Checkpoint")
    library_file(connection, p["vae"], 4, None, "VAE")
    library_file(connection, p["te"], None, None, "Text Encoder")
    library_file(connection, p["hr"], 5, "SDXL 1.0", "Checkpoint")
    for index, name in enumerate("lmno"):
        library_file(connection, p[name], 10 + index, "SDXL 1.0", "LORA")
    connection.commit()

    v36 = v36_generations.V36(connection)
    rng = random.Random(231)
    typed = ["a cat", "a  cat", "a cat\n", "red fox {red|white}", "100% done", "snake_case here",
             "lighthouse at dusk", "", None, "   ", "golden hour, storm"]
    negatives = ["watermark", None, "", "lighthouse"]
    checkpoints = ["a", "b", "a2", "x", None]
    module_sets = [[], ["vae"], ["vae", "te"], ["te", "vae"], ["unknown_module"]]
    sizes = [(832, 1216), (1024, 1024), (None, None), (0, 512)]
    levels = [1, 2, 4, 8, 16, None]
    start = datetime(2026, 1, 1)
    linked = []
    for g in range(40):
        # Pairs share a date: the order's tie-break.
        created = (start + timedelta(minutes=(g // 2) * 7)).isoformat(timespec="seconds")
        prompt = typed[g % len(typed)]
        checkpoint = checkpoints[g % len(checkpoints)]
        modules = [p[m] for m in module_sets[g % len(module_sets)]]
        hr_modules = [None, [], [p["vae"]]][g % 3]
        count = 1 + g % 4
        images, used = [], []
        for i in range(count):
            if prompt == "red fox {red|white}":
                image_prompt = ["red fox red", "red fox white"][i % 2]
            else:
                image_prompt = prompt
            loras = []
            for name in rng.sample("lmnop", rng.choice([0, 1, 2, 3])):
                loras.append({"name": name, "path": p[name], "te_multiplier": rng.choice([0.5, 0.8, 1.0]),
                              "unet_multiplier": 1.0, "pass": "base"})
            if g % 7 == 0 and loras:
                loras.append(dict(loras[0]))          # the same LoRA twice
            if g % 9 == 0:
                loras.append({"name": "hires", "path": p["l"], "weight": 0.7, "pass": "hires"})
            if g % 11 == 0:
                loras.append({"name": "nameless_path", "path": None, "te_multiplier": 1.0, "pass": "base"})
            width, height = sizes[(g + i) % len(sizes)]
            images.append({
                "position": i, "iteration": i // 2, "path": os.path.join(root, "out", f"{g}-{i}.png"),
                "infotext": f"{image_prompt}\nSteps: 20, Seed: {g * 10 + i}",
                "meta": {"prompt": image_prompt, "steps": 20, "Lora hashes": "l: abc123"},
                "prompt": image_prompt, "negative_prompt": negatives[(g + i) % len(negatives)],
                "seed": g * 10 + i, "subseed": None, "hr_prompt": image_prompt if g % 3 == 0 else None,
                "hr_negative_prompt": None, "loras": loras, "width": width, "height": height,
                "prompt_nsfw_level": levels[(g + i) % len(levels)],
            })
            # As the recorder lists them: checkpoint, hires checkpoint, refiner,
            # modules, hires modules, the image's LoRAs.
            files = [checkpoint and p[checkpoint], p["hr"] if g % 6 == 0 else None,
                     p["refiner"] if g % 8 == 0 else None] + modules + (hr_modules or []) + \
                [l["path"] for l in loras if l.get("path")]
            used.append(list(dict.fromkeys(f for f in files if f)))
        generation_id = v36.record_generation({
            "created_at": created, "mode": "txt2img" if g % 5 else "img2img", "forge": "neo",
            "prompt": prompt, "negative_prompt": negatives[g % len(negatives)], "styles": [],
            "n_iter": 1, "batch_size": count, "width": 1024, "height": 1024,
            "checkpoint_path": checkpoint and p[checkpoint], "checkpoint_hash": "abc",
            "modules": modules, "hr_checkpoint_path": p["hr"] if g % 6 == 0 else None,
            "hr_modules": hr_modules, "refiner_path": p["refiner"] if g % 8 == 0 else None,
            "params": {"steps": 20}, "extra_params": {}, "script_args": {}, "settings": {},
            "inputs": {"fixed": {"prompt": prompt}} if g % 4 == 0 else None,
            "infotext": f"{prompt}\nSteps: 20", "image_count": count,
            "prompt_nsfw_level": max((im["prompt_nsfw_level"] or 0) for im in images),
        }, images, used)
        if g % 6 == 1:
            linked.append(generation_id)
    # A person's ratings, and the Queue's task.
    connection.execute("UPDATE generation_images SET user_nsfw_level = 4 WHERE id % 5 = 0")
    connection.execute("UPDATE generation_images SET user_nsfw_level = 1 WHERE id % 7 = 0")
    for generation_id in linked:
        connection.execute("INSERT INTO task_generations (task_id, generation_id) VALUES (7, ?)",
                           (generation_id,))
    connection.commit()
    return {"paths": p, "task": 7, "linked": linked}


def bulk(connection, count, root):
    """`count` plain images, a third as many generations, fast: for counting
    what a read hands to Python."""
    connection.execute("INSERT INTO files (file_path, file_name) VALUES (?, ?)",
                       (os.path.join(root, "ck.safetensors"), "ck.safetensors"))
    images, files, generation = [], [], 0
    rows = []
    while len(images) < count:
        generation += 1
        prompt = f"prompt {generation % 300}"
        rows.append((generation, f"2026-01-01T00:{generation // 60 % 60:02d}:{generation % 60:02d}",
                     "txt2img", prompt, os.path.join(root, "ck.safetensors"), 3))
        for position in range(3):
            image_id = len(images) + 1
            images.append((image_id, generation, position, os.path.join(root, f"{image_id}.png"), prompt,
                           json.dumps([{"name": f"l{image_id % 5}", "path": os.path.join(root, f"l{image_id % 5}.st")}]),
                           832, 1216, [1, 2, 8, None][image_id % 4]))
            files.append((os.path.join(root, "ck.safetensors"), image_id, generation))
            files.append((os.path.join(root, f"l{image_id % 5}.st"), image_id, generation))
    connection.executemany("INSERT INTO generations (id, created_at, mode, prompt, checkpoint_path, image_count) "
                           "VALUES (?, ?, ?, ?, ?, ?)", rows)
    connection.executemany("INSERT INTO generation_images (id, generation_id, position, path, prompt, loras, "
                           "width, height, prompt_nsfw_level) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", images)
    connection.executemany("INSERT INTO generation_files (file_path, image_id, generation_id) VALUES (?, ?, ?)",
                           files)
    connection.commit()
    return {"checkpoint": os.path.join(root, "ck.safetensors")}
