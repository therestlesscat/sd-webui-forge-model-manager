#!/usr/bin/env bash
# Pull images and prompts from Civitai and train the NSFW prompt model from
# them, in a Python environment of its own. See tools/train_nsfw_from_civitai.py.
#
#   tools/run_nsfw_training.sh [data.db]
#
# Asks for a Civitai API key unless CIVITAI_API_KEY is set. The pull resumes
# where it stopped if run again. Optional:
#   MODELS, IMAGES   how much to pull (1000 and 1000)
#   WORKERS          models fetched at once (12)
#   RATE, MAX_RATE   requests per second to start at (5), and never to exceed
#                    (5). On a throttle every worker backs off as Civitai
#                    advises - 1 s doubling to 30 s - and the rate drops 30%
#                    for the rest of the run
#   CLEAN            percent of PG/PG-13 left out of training as suspected
#                    mis-ratings (2); 0 for none. The model file is named for it.
#   LIBRARY          a library's models.db, to judge with the model at the end.
#                    Close the WebUI first: from WSL, a database the WebUI has
#                    open cannot be read.
set -euo pipefail
cd "$(dirname "$0")/.."

DATA="${1:-tests/work/nsfw_from_civitai/top1000.db}"
VENV=tests/work/nsfw_venv
CLEAN="${CLEAN:-2}"
OUT="${DATA%.db}_model_clean${CLEAN}.json.gz"

if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating the Python environment in $VENV"
    python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet numpy scipy requests

if [ -z "${CIVITAI_API_KEY:-}" ]; then
    read -rsp "Civitai API key: " CIVITAI_API_KEY
    echo
fi
export CIVITAI_API_KEY

"$VENV/bin/python" tools/train_nsfw_from_civitai.py pull "$DATA" \
    --models "${MODELS:-1000}" --images "${IMAGES:-1000}" \
    --workers "${WORKERS:-12}" --rate "${RATE:-5}" --max-rate "${MAX_RATE:-5}"
"$VENV/bin/python" tools/train_nsfw_from_civitai.py train "$DATA" --out "$OUT" --clean "$CLEAN"

if [ -n "${LIBRARY:-}" ]; then
    # The model is already written, so a library that cannot be read loses
    # nothing: close the WebUI and run the command printed below.
    "$VENV/bin/python" tools/train_nsfw_from_civitai.py evaluate "$OUT" "$LIBRARY" \
        || echo "Could not judge $LIBRARY - is the WebUI running? Close it and run:
  $VENV/bin/python tools/train_nsfw_from_civitai.py evaluate $OUT $LIBRARY
or leave it running and use its own Python, from Windows:
  <WebUI folder>\\venv\\Scripts\\python.exe tools\\train_nsfw_from_civitai.py evaluate $OUT <path to models.db>"
fi
echo "Model: $OUT"
