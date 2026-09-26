"""
Train the NSFW prompt model nsfw.py uses, from a library's stored images.

    python tools/train_nsfw_model.py <path to models.db> [--out <file>]

Run it with the WebUI's Python (it needs numpy and scipy). The database is
opened read-only and nothing in it is changed.

What it learns: which prompts belong to images Civitai rates X or XXX, as
against PG or PG-13 - from each prompt's words, pairs of adjacent words and
negative prompt, as nsfw.prompt_features() reads them. R images are left out
of training: they are neither. Every image counts once, whichever galleries
hold it.

The percentage in the settings is turned into a score by a calibration
table. It is measured out-of-fold - each image scored by a model trained
without its post - because a model scores the prompts it learned from more
confidently than new ones, and would otherwise raise fewer than it says.

The model that ships is trained on everything but the PG and PG-13 images
the out-of-fold models find most explicit - CLEAN_PERCENT of them. Those are
mostly images Civitai rated too low (reviewed one by one: nearly all
explicit), and a model taught they are PG learns to leave them PG: trained
on them, it raised 25 of one library's 33,730 PG/PG-13 images at the 2%
setting instead of about 670. Without them it raised 535, 528 of them the
ones the out-of-fold models pick.

The file written holds no words: features are kept by their hash.
"""
import argparse
import datetime
import gzip
import json
import os
import sqlite3
import sys
import zlib

import numpy as np
from scipy import sparse
from scipy.optimize import minimize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from model_manager import nsfw   # noqa: E402

BITS = 20
REGULARISATION = 2.0
PRUNE_BELOW = 0.05       # measured: 46k weights of 497k, and no loss in recall
CLEAN_PERCENT = 2        # suspected mis-ratings left out of the final training
CALIBRATION = (0.25, 0.5, 0.75, 1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10, 15, 20)
DEFAULT_OUT = os.path.join(ROOT, "model_manager", "data", "nsfw_prompt_model.json.gz")


def read_library(path):
    """One row per image with a prompt: (level, prompt, negative, post)."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows, seen = [], set()
    for image_id, data in db.execute("SELECT id, data FROM images"):
        if image_id in seen:
            continue
        seen.add(image_id)
        image = json.loads(data)
        meta = image.get("meta") if isinstance(image.get("meta"), dict) else {}
        prompt = meta.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        negative = meta.get("negativePrompt")
        rows.append((nsfw.rated_level(image), prompt,
                     negative if isinstance(negative, str) else "",
                     image.get("postId") or f"image {image_id}"))
    db.close()
    return rows


def matrix(rows):
    indices, pointers = [], [0]
    for _, prompt, negative, _ in rows:
        indices.extend(sorted({nsfw.feature_hash(f, BITS) for f in nsfw.prompt_features(prompt, negative)}))
        pointers.append(len(indices))
    return sparse.csr_matrix((np.ones(len(indices), np.float32), indices, pointers),
                             shape=(len(rows), 1 << BITS))


def train(x, y):
    """L2-regularised logistic regression; returns (weights, bias)."""
    def loss(w):
        z = x @ w[:-1] + w[-1]
        value = np.sum(np.logaddexp(0, z) - y * z) + REGULARISATION / 2 * w[:-1] @ w[:-1]
        g = 1 / (1 + np.exp(-z)) - y
        return value, np.append(x.T @ g + REGULARISATION * w[:-1], g.sum())
    w = minimize(loss, np.zeros(x.shape[1] + 1), jac=True, method="L-BFGS-B",
                 options={"maxiter": 300}).x
    return w[:-1], w[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db")
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    rows = read_library(args.db)
    levels = np.array([r[0] for r in rows])
    explicit, safe = np.isin(levels, (nsfw.X, nsfw.XXX)), np.isin(levels, (nsfw.PG, nsfw.PG13))
    learn = explicit | safe
    print(f"{len(rows):,} prompts: {explicit.sum():,} X/XXX, {safe.sum():,} PG/PG-13, "
          f"{(levels == nsfw.R).sum():,} R")
    x = matrix(rows)

    # Out-of-fold scores, by post, for the calibration.
    fold = np.array([zlib.crc32(str(r[3]).encode()) % 2 for r in rows])
    scores = np.zeros(len(rows))
    for k in (0, 1):
        fit = learn & (fold != k)
        w, b = train(x[fit], explicit[fit].astype(float))
        scores[fold == k] = x[fold == k] @ w + b
    safe_scores = scores[safe]
    calibration, measured = [], []
    for percent in CALIBRATION:
        threshold = float(np.quantile(safe_scores, 1 - percent / 100))
        calibration.append([percent, round(threshold, 4)])
        measured.append({"percent": percent,
                         "x_xxx_caught": round(float(np.mean(scores[explicit] > threshold)), 4),
                         "r_caught": round(float(np.mean(scores[levels == nsfw.R] > threshold)), 4)})

    # The model that ships: trained on everything but the suspected
    # mis-ratings, pruned.
    suspect = safe & (scores > np.quantile(safe_scores, 1 - CLEAN_PERCENT / 100))
    w, b = train(x[learn & ~suspect], explicit[learn & ~suspect].astype(float))
    keep = np.flatnonzero(np.abs(w) >= PRUNE_BELOW)
    model = {
        "format": 1, "bits": BITS, "bias": round(float(b), 4),
        "keys": [int(i) for i in keep], "values": [round(float(w[i]), 4) for i in keep],
        "calibration": calibration,
        "about": {
            "trained": datetime.date.today().isoformat(),
            "prompts": {"x_xxx": int(explicit.sum()), "pg_pg13": int(safe.sum()),
                        "r": int((levels == nsfw.R).sum())},
            "weights_kept": len(keep),
            "left_out_as_suspected_mis_ratings": int(suspect.sum()),
            "measured_out_of_fold": measured,
        },
    }
    with gzip.open(args.out, "wt", encoding="utf-8") as f:
        json.dump(model, f, separators=(",", ":"))
    print(f"wrote {args.out}: {len(keep):,} weights, {os.path.getsize(args.out) / 1024:.0f} KB")
    for m in measured:
        print(f"  {m['percent']:>5}% of PG/PG-13 raised: X/XXX {m['x_xxx_caught']:.1%}, R {m['r_caught']:.1%}")


if __name__ == "__main__":
    main()
