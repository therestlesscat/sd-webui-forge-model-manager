"""
A small library to test against, built from nothing.

The suites used to run against whichever database the author happened to have,
which made them fail for reasons that had nothing to do with the code: a count
that was right last week, three unmarked rows that were marked by a later sync,
a filter that found two models until the library grew. Four suites were caught
asserting facts about someone's models rather than about the extension.

So they build this instead. It is deliberately small and deliberately varied -
enough of each shape that the queries have something to discriminate between,
and few enough that every number in a test can be written down.

Everything goes through the real ModelsDatabase, so a fixture exercises the
migrations on the way in and cannot drift from the schema.
"""
import io
import json
import os
import shutil
import sys

# The extension package, from wherever this file happens to live.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from model_manager.db import ModelsDatabase          # noqa: E402


# What the fixture contains, so a test can assert against a number rather than
# a query. Keep these in step with build() below.
CHECKPOINTS = 6         # models of type Checkpoint, all with a local file
LORAS = 4
VAES = 2
MODELS = CHECKPOINTS + LORAS + VAES

LINKED_VERSIONS = 14    # versions that resolve to a Civitai model
LOCAL_ONLY = 3          # files on disk that Civitai has never heard of
VERSIONS = LINKED_VERSIONS + LOCAL_ONLY

TRAINED = 2             # checkpoints known to be trained
MERGED = 3              # and merged; the sixth is unclassified
IMAGES_PER_VERSION = 4


def _model(model_id, name, model_type, **overrides):
    """A Civitai model as the sync and the scan both hand it over."""
    model = {
        "id": model_id,
        "name": name,
        "description": "<p>%s</p>" % name,
        "type": model_type,
        "nsfw": False,
        "nsfw_level": 1,
        "tags": ["tag-%d" % model_id, model_type.lower()],
        "creator_username": "maker-%d" % (model_id % 3),
        "creator_image_url": "https://example.invalid/%d.png" % model_id,
        "stats_download_count": model_id * 100,
        "stats_thumbs_up": model_id * 10,
        "stats_thumbs_down": model_id,
        "stats_rating": 4.5,
        "allow_no_credit": True,
        "allow_commercial_use": ["Image", "Rent"],
        "allow_derivatives": True,
        "allow_different_license": True,
        "supports_generation": False,
    }
    model.update(overrides)
    return model


def _image(image_id, level):
    return {
        "id": image_id,
        "url": "https://example.invalid/i/%d.jpeg" % image_id,
        "width": 512,
        "height": 768,
        "browsingLevel": level,
        "createdAt": "2026-01-01T00:00:00.000Z",
        "meta": {"prompt": "a prompt for %d" % image_id, "Steps": 20},
    }


def build(directory):
    """
    Create a library under `directory` and return (db, facts).

    The directory is emptied first, so a suite always starts from the same
    place however it failed last time.

    Returns:
        db: an open ModelsDatabase over a fresh file.
        facts: paths and ids the tests need, so they do not have to re-derive
            them with the queries they are testing.
    """
    directory = os.path.abspath(directory)
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory)

    models_dir = os.path.join(directory, "models")
    for sub in ("Stable-diffusion", "Lora", "VAE"):
        os.makedirs(os.path.join(models_dir, sub))

    db = ModelsDatabase(extension_dir=ROOT,
                        custom_db_path=os.path.join(directory, "models.db"))

    facts = {
        "directory": directory,
        "models_dir": models_dir,
        "db_path": os.path.join(directory, "models.db"),
        "checkpoint_ids": [],
        "lora_ids": [],
        "vae_ids": [],
        "linked_paths": [],
        "local_only_paths": [],
        "version_ids": [],
        "trained_ids": [],
        "merged_ids": [],
        "unclassified_checkpoint_id": None,
        "restrictive_id": None,
        "unlicensed_id": None,
    }

    def write_file(folder, name, size):
        path = os.path.join(models_dir, folder, name)
        io.open(path, "wb").write(b"\0" * size)
        return path

    model_id = 1000
    version_id = 2000

    plan = ([("Checkpoint", "Stable-diffusion")] * CHECKPOINTS
            + [("LORA", "Lora")] * LORAS
            + [("VAE", "VAE")] * VAES)

    for index, (model_type, folder) in enumerate(plan):
        model_id += 1
        overrides = {}

        # One model refuses everything, so a licence filter has a "false" to
        # find as well as a "true".
        if index == 1:
            overrides.update(allow_derivatives=False, allow_different_license=False,
                             allow_no_credit=False, allow_commercial_use=None)
            facts["restrictive_id"] = model_id

        # One says nothing at all, which is the NULL the filters call unknown.
        if index == 2:
            overrides.update(allow_derivatives=None, allow_different_license=None,
                             allow_no_credit=None, allow_commercial_use=None)
            facts["unlicensed_id"] = model_id

        # A spread of NSFW levels, so max-mode has something to exclude.
        overrides.setdefault("nsfw_level", (1, 2, 4, 8, 16)[index % 5])

        db.upsert_civitai_model(_model(model_id, "Model %d" % model_id, model_type,
                                       **overrides),
                                from_civitai=True)

        key = {"Checkpoint": "checkpoint_ids", "LORA": "lora_ids",
               "VAE": "vae_ids"}[model_type]
        facts[key].append(model_id)

        # Most models have one local version; two checkpoints have a second,
        # so grouping has something to group.
        for copy in range(2 if index < 2 else 1):
            version_id += 1
            path = write_file(folder, "model_%d_v%d.safetensors" % (model_id, copy),
                              1024 + version_id)
            db.upsert_version({
                "id": version_id,
                "model_id": model_id,
                "version_name": "v%d" % (copy + 1),
                "base_model": "SDXL 1.0" if model_type == "Checkpoint" else "Pony",
                "published_at": "2026-0%d-01T00:00:00Z" % (1 + index % 8),
                "created_at": "2026-01-01T00:00:00Z",
                "nsfw_level": overrides["nsfw_level"],
                "trained_words": ["trigger-%d" % version_id],
                "description": "version %d" % version_id,
                "stats_download_count": 50,
                "stats_thumbs_up": 5,
                "file_path": path,
                "file_name": os.path.basename(path),
                "file_size": os.path.getsize(path),
                "file_hashes": {"sha256": ("%064x" % version_id).upper(),
                                "autov2": ("%010x" % version_id).upper()},
                "file_modified": "2026-01-01T00:00:00",
                "file_extension": ".safetensors",
                "has_civitai_data": True,
            })
            facts["linked_paths"].append(path)
            facts["version_ids"].append(version_id)

            db.store_images(version_id, page=1, images=[
                _image(version_id * 100 + n, (1, 2, 4, 8)[n % 4])
                for n in range(IMAGES_PER_VERSION)
            ])

    # Trained, merged, and one left unanswered - the three states the filter
    # offers.
    checkpoints = facts["checkpoint_ids"]
    facts["trained_ids"] = checkpoints[:TRAINED]
    facts["merged_ids"] = checkpoints[TRAINED:TRAINED + MERGED]
    facts["unclassified_checkpoint_id"] = checkpoints[TRAINED + MERGED]
    db.set_checkpoint_types(
        {i: "Trained" for i in facts["trained_ids"]}
        | {i: "Merge" for i in facts["merged_ids"]}
    )

    # Files Civitai has never heard of: most LoRAs and every text encoder
    # someone trained themselves look like this.
    for n in range(LOCAL_ONLY):
        path = write_file("Lora", "local_only_%d.safetensors" % n, 512 + n)
        db.upsert_version({
            "file_path": path,
            "file_name": os.path.basename(path),
            "file_size": os.path.getsize(path),
            "file_extension": ".safetensors",
            "file_modified": "2026-01-01T00:00:00",
            "has_civitai_data": False,
            "nsfw_level": 1,
        })
        facts["local_only_paths"].append(path)

    return db, facts


def sidecar(path, payload):
    """Write a .civitai.info beside a model file, as another tool would."""
    info = os.path.splitext(path)[0] + ".civitai.info"
    io.open(info, "w", encoding="utf-8").write(json.dumps(payload))
    return info


if __name__ == "__main__":
    import tempfile
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        tempfile.gettempdir(), "mm_fixture")
    _, facts = build(target)
    print("built a library in %s" % facts["directory"])
    for key in ("checkpoint_ids", "lora_ids", "vae_ids", "trained_ids", "merged_ids"):
        print("   %-26s %s" % (key, facts[key]))
    print("   %-26s %d" % ("linked versions", len(facts["linked_paths"])))
    print("   %-26s %d" % ("local-only files", len(facts["local_only_paths"])))
