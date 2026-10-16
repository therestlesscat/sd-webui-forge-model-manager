"""
The NSFW prompt model's trainer (tools/train_nsfw_model.py): what it writes,
nsfw.py must read, and score an explicit prompt above a safe one.

Run by --tools, or by --changed when the trainer or nsfw.py changes - not by
every full run: the model is trained rarely, by hand. On a tiny library, in
2 ** 12 weights: the 2 ** 20 the shipped model has made every step of the
training work on a million weights, and this suite take 6 s.
"""
import gzip
import json
import os
import shutil
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()
from model_manager import nsfw                            # noqa: E402

WORK = os.path.join(TESTS, 'work', 'nsfw_trainer')
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
BITS = 12
TRAIN = [sys.executable, os.path.join(ROOT, 'tools', 'train_nsfw_model.py'), '--bits', str(BITS)]

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def use(path):
    nsfw.PROMPT_MODEL_FILE = path
    nsfw._model_loaded = False


nsfw.PROMPT_WORDS_FILE = os.path.join(WORK, 'no_words.txt')   # the model alone
nsfw._bundled = None
opts.model_manager_nsfw_detection = 'model'
opts.model_manager_nsfw_prompt_model_percent = 2

# A tiny library: X images say zorp, PG images say lighthouse. What the
# trainer writes, nsfw.py must read, and score the two apart.
db_path = os.path.join(WORK, 'library.db')
db = sqlite3.connect(db_path)
db.execute('CREATE TABLE images (id INTEGER, version_id INTEGER, data TEXT)')
rows = []
for n in range(100):
    explicit = n % 2 == 0
    rows.append((n, 1, json.dumps({'id': n, 'postId': n // 3, 'browsingLevel': 16 if explicit else 1,
        'meta': {'prompt': ('a zorp, ' if explicit else 'a lighthouse, ') + 'painting %d' % (n % 7)}})))
rows.append((0, 2, json.dumps({'id': 0, 'browsingLevel': 16, 'meta': {'prompt': 'counted once'}})))
db.executemany('INSERT INTO images VALUES (?, ?, ?)', rows)
db.commit()
db.close()
out = os.path.join(WORK, 'trained.json.gz')
run = subprocess.run(TRAIN + [db_path, '--out', out], capture_output=True, text=True)
check('1. the trainer runs', (run.returncode, run.stderr[-300:] if run.returncode else ''), (0, ''))
check('   counting an image once, whichever galleries hold it', '100 prompts' in run.stdout)

# A library since v42 (#283): each image's record once, in image_records.
new_path = os.path.join(WORK, 'library_v42.db')
if os.path.exists(new_path):
    os.remove(new_path)
new_db = sqlite3.connect(new_path)
new_db.execute('CREATE TABLE images (id INTEGER PRIMARY KEY, prompt_id INTEGER)')
new_db.execute('CREATE TABLE image_records (image_id INTEGER PRIMARY KEY, url TEXT, data TEXT NOT NULL)')
new_db.executemany('INSERT INTO image_records VALUES (?, NULL, ?)', [(r[0], r[2]) for r in rows if r[1] == 1])
new_db.commit()
new_db.close()
run_new = subprocess.run(TRAIN + [new_path, '--out', os.path.join(WORK, 'trained_v42.json.gz')],
                         capture_output=True, text=True)
check('   and a library since v42, its records in image_records',
      (run_new.returncode, '100 prompts' in run_new.stdout), (0, True))
use(out)
trained = nsfw.prompt_model()
check('   and writes a model nsfw.py reads', trained is not None)
if trained:
    check('   which tells the two apart',
          nsfw.prompt_score({'prompt': 'a zorp, painting 3'}) > nsfw.prompt_score({'prompt': 'a lighthouse, painting 3'}))
    check('   trained on the second feature set, and saying so', trained['features'], 2)
    check('   in the bits it was asked for, and saying so: nsfw.py reads by them', trained['bits'], BITS)
    check('   recording how many suspected mis-ratings it left out, 2% by default',
          (float(trained['about']['clean_percent']),
           isinstance(trained['about']['left_out_as_suspected_mis_ratings'], int)), (2.0, True))
    check('   with its calibration', len(trained['calibration']) > 5)
    check('   and nothing in it a word could be read from',
          all(isinstance(k, int) for k in trained['weights']))

kept_all = os.path.join(WORK, 'trained_clean0.json.gz')
run = subprocess.run(TRAIN + [db_path, '--out', kept_all, '--clean', '0'], capture_output=True, text=True)
about = {}
if os.path.exists(kept_all):
    with gzip.open(kept_all, 'rt', encoding='utf-8') as f:
        about = json.load(f)['about']
check('   --clean 0 keeps every image', (run.returncode, about.get('clean_percent'),
      about.get('left_out_as_suspected_mis_ratings')), (0, 0.0, 0))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
