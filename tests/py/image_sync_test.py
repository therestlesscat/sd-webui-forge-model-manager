"""
Sync images (#233): images already on disk added to the Generations tab -
model_manager.image_sync over folders of images this suite writes, into the
fixture library.

Each situation is one the plan names: what is skipped, what is read, how a
press's images become one generation again, which files they are matched
to, what a delete leaves on the removed list, what a restamp and the
recorder do to what a sync brought.
"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager import generations, image_sync        # noqa: E402
from model_manager.api.generations import remember_kept  # noqa: E402
from model_manager.nsfw import PG, PROMPT_LEVEL, UNKNOWN, generated_level  # noqa: E402

from PIL import Image                                    # noqa: E402
from PIL.PngImagePlugin import PngInfo                   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'image_sync')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def parse(infotext):
    """Forge's parser is not here; this one reads what the suite writes."""
    lines = infotext.split('\n')
    parsed = {'Prompt': lines[0]}
    for line in lines[1:]:
        if line.startswith('Negative prompt: '):
            parsed['Negative prompt'] = line[len('Negative prompt: '):]
        else:
            for pair in line.split(', '):
                key, _, value = pair.partition(': ')
                parsed[key] = value.strip('"')
    return parsed


generations.parse_generation_parameters = parse

db, facts = fixtures.build(WORK)
dbmod._db_instance = db
raw = db._get_connection()

CHECKPOINT = facts['linked_paths'][0]
CHECKPOINT_HASH = ('%010x' % facts['version_ids'][0]).upper()
LORA_PATH = [p for p in facts['linked_paths'] if os.sep + 'Lora' + os.sep in p][0]
LORA_VERSION = facts['version_ids'][facts['linked_paths'].index(LORA_PATH)]
LORA_HASH = ('%010x' % LORA_VERSION).upper()
LORA_NAME = os.path.splitext(os.path.basename(LORA_PATH))[0]
LOCAL_LORA = facts['local_only_paths'][0]
LOCAL_LORA_NAME = os.path.splitext(os.path.basename(LOCAL_LORA))[0]
raw.execute("UPDATE files SET file_type = 'Checkpoint' WHERE file_path = ?", (CHECKPOINT,))
raw.commit()

OUT = os.path.join(WORK, 'outputs')
BASE = time.time() - 86400


def infotext(prompt, seed, steps=20, model_hash=CHECKPOINT_HASH, model='model_x', extra=''):
    return (f'{prompt}\nNegative prompt: blurry\nSteps: {steps}, Sampler: Euler a, CFG scale: 7, '
            f'Seed: {seed}, Size: 64x64, Model hash: {model_hash}, Model: {model}{extra}')


def save(folder, name, text=None, at=0.0, kind='png', size=64):
    """An image file as Forge saves one, its text where Forge puts it."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    image = Image.new('RGB', (size, size), (at * 7 % 255 if isinstance(at, int) else 10, 20, 30))
    if kind == 'png':
        info = PngInfo()
        if text:
            info.add_text('parameters', text)
        image.save(path, pnginfo=info)
    else:
        exif = Image.Exif()
        if text:
            exif.get_ifd(0x8769)[0x9286] = b'UNICODE\x00' + text.encode('utf-16-be')
        image.save(path, exif=exif.tobytes()) if text else image.save(path)
    stamp = int((BASE + at) * 1e9)
    os.utime(path, ns=(stamp, stamp))
    return path


def run(folders, level=UNKNOWN, group=True, mode=None):
    sync = image_sync.ImageSync([{'path': f, 'key': mode} for f in folders], level, group)
    sync.run()
    return sync.progress


def rows(sql, args=()):
    return [tuple(r) for r in raw.execute(sql, args).fetchall()]


def images_at(folder):
    return rows("SELECT gi.path, gi.generation_id FROM generation_images gi WHERE gi.path LIKE ? "
                "ORDER BY gi.path", (folder + '%',))


# ------------------------------------------------------------- v38's tables
tables = {r[0] for r in rows("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}
check('v38 adds the folder table, the removed list and the two indexes',
      {'image_sources', 'removed_images', 'idx_images_path', 'idx_generations_source'} <= tables, True)
check('generations name their folder', 'source_id' in {r[1] for r in rows("PRAGMA table_info(generations)")})

# ------------------------------------------------------------ what is read
READ = os.path.join(OUT, 'read')
png = save(READ, '00001-a.png', infotext('a castle', 7))
jpg = save(READ, '00002-b.jpg', infotext('a jpeg castle', 70), kind='jpg')
bare = save(READ, '00003-c.png', None)
broken = os.path.join(READ, '00004-d.png')
open(broken, 'wb').write(b'not an image at all')
from model_manager.image_text import read_text   # noqa: E402
check('a PNG\'s text is its parameters chunk', read_text(png)[0], infotext('a castle', 7))
check('a JPEG\'s text is its EXIF comment', read_text(jpg)[0], infotext('a jpeg castle', 70))
check('an image with no text reads as none, with its size', read_text(bare), (None, 64, 64))
progress = run([READ])
check('a file that is no image is reported, not fatal', (progress.state, progress.error_count), ('done', 1))
check('the readable three come in', len(images_at(READ)), 3)

# ------------------------------------------------------------ what is skipped
SKIP = os.path.join(OUT, 'skip')
kept = save(SKIP, '00010-kept.png', infotext('kept', 1))
for name in ('grid-0001-x.png', '00011-grid-x.png', 'xyz_grid-0002.png', '00012-x-before-highres-fix.png',
             '00013-x-before-color-correction.png', '00014-x-before-face-restoration.png',
             '00015-x-mask.png', '00016-x-mask-composite.png', '00017-x-pid.png'):
    save(SKIP, name, infotext('skipped', 2))
save(os.path.join(SKIP, 'detected_maps', 'canny'), 'canny-0001.png', None)
open(os.path.join(SKIP, '00018-video.mp4'), 'wb').write(b'\0' * 10)
big = save(SKIP, '00019-big.png', infotext('big', 3), at=5)
save(SKIP, '00019-big.jpg', infotext('big', 3), at=5, kind='jpg')
run([SKIP])
check('grids, "before" copies, masks, PiD copies, ControlNet maps, videos and Forge\'s JPEG copy are left out',
      [os.path.basename(p) for p, _ in images_at(SKIP)], ['00010-kept.png', '00019-big.png'])

# ----------------------------------------------------- held, in another case
HELD = os.path.join(OUT, 'held')
held = save(HELD, '00020-held.png', infotext('held', 4))
generations_before = rows("SELECT COUNT(*) FROM generations")[0][0]
db.record_generation({'created_at': '2026-01-01T00:00:00', 'mode': 'txt2img', 'image_count': 1},
                     [{'position': 0, 'path': held.upper(), 'infotext': 'x'}], [[]])
run([HELD])
check('an image already held, spelt in another case, is not added twice',
      rows("SELECT COUNT(*) FROM generation_images WHERE path = ? COLLATE NOCASE", (held,))[0][0], 1)

# ------------------------------------------------------- one press, two presses
PRESS = os.path.join(OUT, 'press')
# A wildcard picks a prompt, and with it LoRAs, image by image.
eight = [save(PRESS, '%05d-p.png' % (100 + n), infotext('a castle, %s' % ('red', 'blue')[n % 2], 500 + n,
                                                          extra=', Lora hashes: "pick%d: %04x"' % (n % 2, n % 2)),
              at=n)
         for n in range(8)]
fixed = [save(PRESS, '%05d-p.png' % (108 + n), infotext('fixed', 900), at=100 + n) for n in range(2)]
run([PRESS])
groups = {}
for path, gid in images_at(PRESS):
    groups.setdefault(gid, []).append(os.path.basename(path))
check('eight images of one press, wildcard prompts, become one generation in order',
      sorted(groups.values(), key=len)[-1], [os.path.basename(p) for p in eight])
check('two presses with the same fixed seed, numbered one after the other, stay two',
      sorted(len(v) for v in groups.values()), [1, 1, 8])
order = rows("SELECT gi.position, gi.path FROM generation_images gi WHERE gi.path = ?", (eight[3],))
check('each image keeps its place in the press', order[0][0], 3)

UNNUMBERED = os.path.join(OUT, 'unnumbered')
for n in range(3):
    save(UNNUMBERED, 'img_%s.png' % 'cab'[n], infotext('loose', 40 + n), at=200 + n)
run([UNNUMBERED])
check('images with no running numbers join by their time and seed',
      len({g for _, g in images_at(UNNUMBERED)}), 1)

# ----------------------------------------------------------------- matching
MATCH = os.path.join(OUT, 'match')
lora_text = infotext(f'a castle <lora:{LORA_NAME}:0.7> <lora:{LOCAL_LORA_NAME}:0.5> <lora:gone_lora:1>', 3000,
                     extra=f', Lora hashes: "{LORA_NAME}: {LORA_HASH}", Module 1: sdxl_vae')
matched = save(MATCH, '00300-m.png', lora_text)
unmatched = save(MATCH, '00301-n.png', infotext('no such model', 4000, model_hash='0123456789',
                                                 model='mystery_model'), at=50)
VAE = os.path.join(facts['models_dir'], 'VAE', 'sdxl_vae.safetensors')
from model_manager import forge_host   # noqa: E402
forge_host.installed_modules = lambda: {'sdxl_vae.safetensors': VAE}
run([MATCH])


def resources(path):
    return sorted(rows("SELECT r.role, r.name, r.file_path, r.weight FROM generation_resources r "
                       "JOIN generation_images gi ON gi.id = r.image_id WHERE gi.path = ?", (path,)))


got = resources(matched)
check('Model hash finds the library\'s checkpoint', [r[2] for r in got if r[0] == 'checkpoint'], [CHECKPOINT])
check('Lora hashes finds a LoRA, and <lora:name> another by Forge\'s rule; one the library lacks keeps its name',
      sorted((r[1], r[2], r[3]) for r in got if r[0] == 'lora'),
      sorted([(LORA_NAME, LORA_PATH, 0.7), (LOCAL_LORA_NAME, LOCAL_LORA, 0.5), ('gone_lora', None, 1.0)]))
check('Module 1 is Forge\'s module by that name - Neo writes it without its extension',
      [r[2] for r in got if r[0] in ('module', 'vae')], [VAE])
check('a checkpoint the library lacks is kept by the text\'s name, with no path',
      [(r[1], r[2]) for r in resources(unmatched) if r[0] == 'checkpoint'], [('mystery_model', None)])
from model_manager.api.generations import send_plan   # noqa: E402
gid_unmatched = rows("SELECT generation_id FROM generation_images WHERE path = ?", (unmatched,))[0][0]
check('Send stops for a checkpoint the library lacks, naming the one the text names, as for a recorded image (#134)',
      send_plan(db, gid_unmatched)['checkpoint_missing'], 'mystery_model')
from model_manager.api.generations import image_resources   # noqa: E402
unmatched_row = db.get_generation(gid_unmatched)['images'][0]
check('an image\'s resources name its checkpoint by the text\'s Model and hash, for Resources to find on Civitai',
      (image_resources(unmatched_row) or [None])[0], {'type': 'Checkpoint', 'name': 'mystery_model', 'weight': None,
                                          'hash': '0123456789'})
# Downloaded from that dialog: the library has a file with the hash, and Forge lists it.
import types   # noqa: E402
downloaded = os.path.join(facts['models_dir'], 'Stable-diffusion', 'mystery_model.safetensors')
open(downloaded, 'wb').write(b'\0' * 2048)
db.upsert_version({'file_path': downloaded, 'file_name': os.path.basename(downloaded), 'file_size': 2048,
                   'file_extension': '.safetensors', 'file_modified': '2026-01-01T00:00:00',
                   'has_civitai_data': False, 'nsfw_level': 1, 'file_hashes': {'autov2': '0123456789'}})
sd_models = types.ModuleType('modules.sd_models')
sd_models.checkpoints_list = {'m': types.SimpleNamespace(filename=downloaded, title='mystery_model.safetensors [0123456789]')}
sys.modules['modules.sd_models'] = sd_models
plan = send_plan(db, gid_unmatched)
check('once downloaded, Send finds it by the hash and sets it up',
      (plan['checkpoint'], plan['checkpoint_missing']), ('mystery_model.safetensors [0123456789]', None))
del sys.modules['modules.sd_models']
gid_matched = rows("SELECT generation_id FROM generation_images WHERE path = ?", (matched,))[0][0]
check('and sets up the VAE the text names', send_plan(db, gid_matched)['target'], ['sdxl_vae.safetensors'])
from model_manager.db.generations_ops import GROUP_KEYS, Scope   # noqa: E402
units = db.generation_scope_units(Scope(), 'model', None, False, 0, 100)
check('grouped by model, the unmatched image is in its text\'s model\'s group',
      'mystery_model' in {u.get('u') for u in units}, True)
generation = db.get_generation(rows("SELECT generation_id FROM generation_images WHERE path = ?", (matched,))[0][0])
check('an imported generation keeps its text, its folder, and when the file was saved',
      (generation['infotext'], generation['source_id'] is not None, generation['mode'],
       generation['images'][0]['seed']),
      (lora_text, True, 'txt2img', 3000))

# ------------------------------------------------------------ levels
LEVELS = os.path.join(OUT, 'levels')
quiet = save(LEVELS, '00400-q.png', None, at=0)
noisy = save(LEVELS, '00401-w.png', infotext('a calm lake', 77), at=600)
run([LEVELS], level=PG)


def level_of(path):
    return rows("SELECT prompt_nsfw_level, user_nsfw_level FROM generation_images WHERE path = ?", (path,))[0]


check('an image with no text gets the level picked for its sync', level_of(quiet), (PG, None))
check('an image with text is judged by its prompt', level_of(noisy)[0], generated_level(parse(infotext('a calm lake', 77))))
run([LEVELS], level=UNKNOWN)
check('a later sync with another level leaves them as they were', level_of(quiet), (PG, None))
raw.execute("UPDATE generation_images SET prompt_nsfw_level = ? WHERE path = ?", (UNKNOWN, noisy))
raw.commit()
db.restamp_generation_levels(lambda meta: PROMPT_LEVEL)
check('a restamp leaves an imported image with no text at its sync\'s level', level_of(quiet), (PG, None))
check('a restamp judges an imported image with text again', level_of(noisy)[0], PROMPT_LEVEL)
db.set_generation_image_levels([rows("SELECT id FROM generation_images WHERE path = ?", (quiet,))[0][0]], 16)
db.restamp_generation_levels(lambda meta: PG)
check('a rating the person gave wins', level_of(quiet), (PG, 16))

# -------------------------------------------------------- the removed list
REMOVED = os.path.join(OUT, 'removed')
gone = save(REMOVED, '00500-g.png', infotext('gone', 1))
stay = save(REMOVED, '00501-s.png', infotext('stays', 9))
run([REMOVED])
image_id = rows("SELECT id FROM generation_images WHERE path = ?", (gone,))[0][0]
paths, _ = db.delete_generation_image(image_id)
remember_kept(db, paths)
check('a delete that keeps the file puts it on the removed list', gone.lower() in db.removed_images())
run([REMOVED])
check('the next sync skips it', rows("SELECT COUNT(*) FROM generation_images WHERE path = ?", (gone,))[0][0], 0)
image_id = rows("SELECT id FROM generation_images WHERE path = ?", (stay,))[0][0]
paths, _ = db.delete_generation_image(image_id)
os.remove(stay)
remember_kept(db, paths)
check('a delete with the file puts nothing on the list', stay.lower() in db.removed_images(), False)
save(REMOVED, '00500-g.png', infotext('a new image at the old path', 11), at=999, size=80)
run([REMOVED])
check('a new file at a removed path comes in',
      rows("SELECT COUNT(*) FROM generation_images WHERE path = ?", (gone,))[0][0], 1)
image_id = rows("SELECT id FROM generation_images WHERE path = ?", (gone,))[0][0]
remember_kept(db, db.delete_generation_image(image_id)[0])
os.remove(gone)
run([REMOVED])
check('once the file is gone from disk, it leaves the list', gone.lower() in db.removed_images(), False)

# --------------------------------------------------- the recorder meets an import
RECORDED = os.path.join(OUT, 'recorded')
both = save(RECORDED, '00600-r.png', infotext('recorded later', 5))
run([RECORDED])
replaced = db.replace_imported_images([both])
db.record_generation({'created_at': '2026-01-02T00:00:00', 'mode': 'txt2img', 'image_count': 1},
                     [{'position': 0, 'path': both, 'infotext': 'the full record'}], [[]])
check('the recorder replaces an imported row for its file: one generation remains, the recorded one',
      (replaced, rows("SELECT g.source_id, d.infotext FROM generation_images gi JOIN generations g "
                      "ON g.id = gi.generation_id JOIN image_details d ON d.image_id = gi.id "
                      "WHERE gi.path = ?", (both,))),
      (1, [(None, 'the full record')]))
check('a recorded image is never replaced', db.replace_imported_images([both]), 0)

# ---------------------------------------------------------------- cancel
CANCEL = os.path.join(OUT, 'cancel')
for n in range(6):
    save(CANCEL, '%05d-c.png' % (700 + n), infotext('cancel %d' % n, 7000 + n * 10), at=n * 1000)
sync = image_sync.ImageSync([{'path': CANCEL}])
real = db.record_generations
calls = []


def record_then_cancel(chunk):
    calls.append(len(chunk))
    out = real(chunk)
    sync.cancel()
    return out


db.record_generations = record_then_cancel
old_chunk, image_sync.CHUNK = image_sync.CHUNK, 2
try:
    sync.run()
finally:
    db.record_generations = real
    image_sync.CHUNK = old_chunk
check('cancel mid-sync: it ends cancelled, and what was written stays',
      (sync.progress.state, len(images_at(CANCEL))), ('cancelled', 2))
run([CANCEL])
check('the next sync adds the rest only', len(images_at(CANCEL)), 6)

# ------------------------------------------- which file of a version a hash is
from model_manager.resources import file_for_hash   # noqa: E402


class Civitai(object):
    """Civitai's by-hash answer, as it lists a version's files and their hashes."""
    def get_model_by_hash(self, file_hash):
        if file_hash.lower() == 'ffffffffff':
            return None
        return {'id': 2312428, 'modelId': 71185, 'files': [
            {'id': 2202961, 'name': 'full.safetensors', 'sizeKB': 5780198.5, 'metadata': {'fp': 'fp32', 'size': 'full'},
             'hashes': {'AutoV2': 'F0DD839481', 'SHA256': 'F0DD839481' + 'A' * 54}},
            {'id': 2202950, 'name': 'pruned.safetensors', 'sizeKB': 2082667.3, 'metadata': {'fp': 'fp16', 'size': 'pruned'},
             'hashes': {'SHA256': 'BDFC5BAFD3' + 'B' * 54}}]}


check('a hash finds its own file among the version\'s, by the hash Civitai lists',
      (file_for_hash(Civitai(), 'f0dd839481') or {}).get('file_id'), 2202961)
check('or as the start of its SHA256, where Civitai lists no AutoV2',
      (file_for_hash(Civitai(), 'BDFC5BAFD3') or {}).get('file_id'), 2202950)
check('a version that holds no file with the hash says so, with its version',
      ((file_for_hash(Civitai(), '1234512345') or {}).get('file_id'), (file_for_hash(Civitai(), '1234512345') or {}).get('version_id')),
      (None, 2312428))
check('a hash Civitai knows no version by finds nothing', file_for_hash(Civitai(), 'ffffffffff'), None)

# --------------------------------------- another file of the version, proven
from model_manager.resources import other_files   # noqa: E402
# The library holds version V's file, its SHA256 stored; the image names
# another file of V by an AutoV2 Civitai answered for.
V = facts['version_ids'][0]
V_PATH = facts['linked_paths'][0]
db.remember_hash('aaaa000001', {'id': V, 'modelId': 1001, 'name': 'v', 'model': {'name': 'm', 'type': 'Checkpoint'}})
check('an AutoV2 no library file has, its version held with every SHA256 stored, is another file',
      sorted(other_files(db, ['AAAA000001'], {})), ['aaaa000001'])
check('with the file the library holds instead, as Civitai\'s list describes it',
      sorted((other_files(db, ['aaaa000001'], {}).get('aaaa000001') or {}).keys()), ['file_size', 'fp', 'name', 'size'])
check('a hash a library file has is not', other_files(db, ['aaaa000001'], {'aaaa000001': {}}), {})
db.remember_hash('aaaa00000100', {'id': V, 'modelId': 1001, 'name': 'v', 'model': {'name': 'm', 'type': 'LORA'}})
check('a hash of another length - an AutoV3 the library may not have read - is never proven another',
      other_files(db, ['aaaa00000100'], {}), {})
raw.execute("UPDATE files SET file_hashes = '{}' WHERE file_path = ?", (V_PATH,))
raw.commit()
check('nor one whose version\'s file has no SHA256 stored to tell by', other_files(db, ['aaaa000001'], {}), {})

# Sent with the library's file of the version instead, chosen in the dialog.
sd_models = types.ModuleType('modules.sd_models')
sd_models.checkpoints_list = {'v': types.SimpleNamespace(filename=V_PATH, title='model_v0.safetensors [aaaa]')}
sys.modules['modules.sd_models'] = sd_models
plan = send_plan(db, gid_unmatched, use_version=V)
check('asked to use the installed file, Send sets up the library\'s file of that version, and says which',
      (plan.get('checkpoint'), plan.get('instead'), plan.get('checkpoint_missing')),
      ('model_v0.safetensors [aaaa]', os.path.basename(V_PATH), None))
del sys.modules['modules.sd_models']

# ------------------------------------- a checkpoint this WebUI cannot load
# A recorded image whose checkpoint is in the library and on disk, but in a
# folder only the other WebUI loads: Send stops saying so - not "download it"
# - as a Civitai image's does. Here in a folder this WebUI does load, but not
# listed by Forge yet: it says that.
elsewhere = os.path.join(WORK, 'other_webui', 'Stable-diffusion', 'theirs.safetensors')
os.makedirs(os.path.dirname(elsewhere), exist_ok=True)
open(elsewhere, 'wb').write(b'\0' * 64)
mine = os.path.join(facts['models_dir'], 'Stable-diffusion', 'mine_unlisted.safetensors')
open(mine, 'wb').write(b'\0' * 64)
paths_module = sys.modules['modules.paths']
paths_module.models_path = facts['models_dir']


def recorded_with(checkpoint):
    return db.record_generation({'created_at': '2026-01-03T00:00:00', 'mode': 'txt2img', 'image_count': 1,
                                 'checkpoint_path': checkpoint, 'infotext': 'x\nSteps: 1, Seed: 1, Size: 1x1'},
                                [{'position': 0, 'path': os.path.join(WORK, 'r_%s.png' % os.path.basename(checkpoint)),
                                  'infotext': 'x'}], [[checkpoint]])


check('a checkpoint in a folder only the other WebUI loads: Send says so, with where it is',
      (send_plan(db, recorded_with(elsewhere)).get('checkpoint_problem') or {}).get('reason'), 'elsewhere')
check('one here that Forge has not listed yet: Send says that',
      (send_plan(db, recorded_with(mine)).get('checkpoint_problem') or {}).get('reason'), 'not_listed')
check('one gone from disk: not in the library',
      (send_plan(db, recorded_with(os.path.join(WORK, 'gone.safetensors'))).get('checkpoint_problem') or {}).get('reason'),
      'missing')
paths_module.models_path = ''

print('image_sync: %d failure(s)' % len(fails))
for f in fails:
    print('FAIL ' + f)
sys.exit(1 if fails else 0)
