"""
The checkpoint a group of your images shares (#238): what a group tile's ⋯
menu offers, read for each tile of a grouped level of the Generations tab.

A group names one only if every image of it was made with the same, as
recorded where it is now (generation_resources, followed when the sync moves
a file); otherwise none. It was looked up for every image of the part's
groups - a subquery per row, 75,684 times grouped by base model in one
library, for 7,762 batches: 1.7 s of a 2.8 s request. An image's checkpoint
is its batch's, so it is now looked up once per batch. The answer must not
change; the work must stop growing with the images.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()

import generation_fixture                                # noqa: E402
from model_manager.api import generations as api         # noqa: E402
from model_manager.db.database import ModelsDatabase     # noqa: E402

WORK = os.path.join(TESTS, 'work', 'group_checkpoint')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def library(name, batches):
    """A v36 library brought up to date: `batches` is [(prompt, checkpoint or None, images)]."""
    root = os.path.join(WORK, name)
    path, connection = generation_fixture.v36_database(root)
    rows, images, files = [], [], []
    for checkpoint in {c for _, c, _ in batches if c}:
        generation_fixture.library_file(connection, checkpoint)
    for number, (prompt, checkpoint, count) in enumerate(batches, start=1):
        rows.append((number, f"2026-01-01T00:{number // 60 % 60:02d}:{number % 60:02d}", "txt2img", prompt,
                     checkpoint, count))
        for position in range(count):
            image_id = len(images) + 1
            images.append((image_id, number, position, os.path.join(root, f"{image_id}.png"), prompt,
                           json.dumps([]), 832, 1216, 1))
            if checkpoint:
                files.append((checkpoint, image_id, number))
    connection.executemany("INSERT INTO generations (id, created_at, mode, prompt, checkpoint_path, image_count) "
                           "VALUES (?, ?, ?, ?, ?, ?)", rows)
    connection.executemany("INSERT INTO generation_images (id, generation_id, position, path, prompt, loras, "
                           "width, height, prompt_nsfw_level) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", images)
    connection.executemany("INSERT INTO generation_files (file_path, image_id, generation_id) VALUES (?, ?, ?)",
                           files)
    connection.commit()
    connection.close()
    return ModelsDatabase(extension_dir=ROOT, custom_db_path=path)


def shared(db, by):
    """Each group's shared checkpoint, by the group's value."""
    return {t['group']['value']: t['checkpoint_path'] for t in api.browse_page(db, False, group=by)['tiles']}


# ------------------------------------------------------------ the rule
A = os.path.join(WORK, 'models', 'a.safetensors')
B = os.path.join(WORK, 'models', 'b.safetensors')
db = library('rule', [('one', A, 2), ('one', A, 3),          # every batch the same
                      ('two', A, 2), ('two', B, 1),          # one batch another
                      ('none', A, 2), ('none', None, 2)])    # one batch with none recorded
groups = shared(db, 'prompt')
check('a group whose batches all used one checkpoint names it', groups.get('one'), A)
check('one whose batch was made with another names none', groups.get('two'), None)
check('one with a batch that recorded none names none', groups.get('none'), None)

# The sync moves a file into its type's folder, and its rows follow it (#234):
# the checkpoint is named where it is now.
MOVED = os.path.join(WORK, 'models', 'Stable-diffusion', 'a.safetensors')
raw = db._get_connection()
raw.execute("UPDATE generation_resources SET file_path = ? WHERE file_path = ?", (MOVED, A))
raw.commit()
check('a file the sync moved is named where it is now', shared(db, 'prompt').get('one'), MOVED)


# ------------------------------------------------------------ the work
def steps(database):
    """SQLite's steps to read the shared checkpoint of one group holding every image."""
    scope = api._scope('size')
    units = database.generation_scope_units(scope, 'size', None, False, 0, 101)
    part = [(u['u'],) for u in units]
    connection = database._get_connection()
    count = [0]

    def tick():
        count[0] += 1
    connection.set_progress_handler(tick, 1)
    try:
        answer = database.generation_scope_unit_checkpoints(scope, 'size', None, False, part)
    finally:
        connection.set_progress_handler(None, 1)
    return count[0], list(answer.values())


single, one_each = steps(library('one_image', [(f'p{n}', A, 1) for n in range(100)]))
twenty, twenty_each = steps(library('twenty_images', [(f'p{n}', A, 20) for n in range(100)]))
check('the same answer either way: one group, one checkpoint', (one_each, twenty_each), ([A], [A]))
# Looked up per image, 20 images a batch took 75 times the steps of 1 (774,030
# against 10,287): each lookup also read its batch's other rows. Per batch, 7.
check('20 times the images in as many batches: the read\'s work grows less than 10 times',
      (twenty < 10 * single, f'{single} steps, then {twenty}'), (True, f'{single} steps, then {twenty}'))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
