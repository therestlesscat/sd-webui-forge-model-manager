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


def unused():
    """The prompts nothing names: no generation, no image, no prompt they head."""
    return [r[0] for r in rows(
        "SELECT p.id FROM generation_prompts p "
        "WHERE NOT EXISTS (SELECT 1 FROM generations g WHERE g.prompt_id = p.id OR g.negative_id = p.id) "
        "AND NOT EXISTS (SELECT 1 FROM generation_images i WHERE i.prompt_id = p.id OR i.negative_id = p.id) "
        "AND NOT EXISTS (SELECT 1 FROM generation_prompts q WHERE q.grouped_as = p.id AND q.id <> p.id)")]


def images_at(folder):
    return rows("SELECT gi.path, gi.generation_id FROM generation_images gi WHERE gi.path LIKE ? "
                "ORDER BY gi.path", (folder + '%',))


# ------------------------------------------------------------- v38's tables
tables = {r[0] for r in rows("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}
check('v38 adds the folder table, the removed list and the two indexes - the tables named for your '
      'generations since v41',
      {'generation_sources', 'generation_images_removed', 'idx_generation_images_path',
       'idx_generations_source'} <= tables,
      True)
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

# ------------------------------------------- what the walk finds, as it finds it
# Cold on a hard disk the walk took minutes (#365), so the page says how many
# new images it has found so far. Each image's size and time come from its
# folder's listing: a stat of each took 46.6 s of one cold walk of 78,611.
FOUND = os.path.join(OUT, 'found')
for n in range(3):
    save(FOUND, '%05d-new.png' % (40 + n), infotext('found %d' % n, 40 + n), at=n)
for n in range(2):
    kept = save(FOUND, '%05d-kept.png' % (50 + n), infotext('kept %d' % n, 50 + n), at=10 + n)
    db.record_generation({'created_at': '2026-01-01T00:00:00', 'mode': 'txt2img', 'image_count': 1},
                         [{'position': 0, 'path': kept, 'infotext': 'x'}], [[]])
on_disk = sorted((os.path.join(FOUND, name), os.stat(os.path.join(FOUND, name)).st_size,
                  os.stat(os.path.join(FOUND, name)).st_mtime_ns) for name in os.listdir(FOUND))
stats = []
real_stat = os.stat


def counted_stat(path, *args, **kwargs):
    if str(path).lower().endswith('.png'):
        stats.append(path)
    return real_stat(path, *args, **kwargs)


os.stat = counted_stat
try:
    walked = sorted(image_sync.walk(FOUND))
finally:
    os.stat = real_stat
check('the walk asks no stat of an image, and gives each the size and time a stat would',
      (len(stats), walked), (0, on_disk))
found_progress = run([FOUND])
check('the sync counts the new images as its walk finds them, a held one not, and says it walked one folder',
      (getattr(found_progress, 'found', None), getattr(found_progress, 'folders', None)), (3, 1))

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
from model_manager.send import generation_plan as send_plan   # noqa: E402
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
                      "ON g.id = gi.generation_id JOIN generation_image_details d ON d.image_id = gi.id "
                      "WHERE gi.path = ?", (both,))),
      (1, [(None, 'the full record')]))
check('a recorded image is never replaced', db.replace_imported_images([both]), 0)
check("the import's prompt, which nothing else names, goes with its row (#248)",
      rows("SELECT COUNT(*) FROM generation_prompts WHERE text = 'recorded later'")[0][0], 0)

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

# ------------------------------------------- folders added, and removed (0.58.2)
def store(values):
    """Forge's settings writer: here, the stub's options."""
    for key, value in values.items():
        setattr(opts, key, value)
    return list(values)


image_sync.forge_host.store_settings = store
FORGE_DIR = os.path.join(OUT, 'forge_results')
os.makedirs(FORGE_DIR, exist_ok=True)
image_sync.forge_host.result_folders = lambda: [{'key': 'outdir_txt2img_samples', 'path': FORGE_DIR}]
ADDED = os.path.join(OUT, 'added')
OTHER = os.path.join(OUT, 'other_added')
added_files = [save(ADDED, '%05d-a.png' % (800 + n), infotext('added %d' % n, 8000 + n * 10), at=n * 1000)
               for n in range(3)]
save(OTHER, '00900-o.png', infotext('other', 9000))

check('a path not from its drive is refused', image_sync.add_folder(os.path.join('outputs', 'added'))[0], None)
check('a folder that is not there is refused', image_sync.add_folder(os.path.join(OUT, 'nowhere'))[0], None)
check('a folder already listed - Forge\'s - is refused',
      image_sync.add_folder(FORGE_DIR), (None, 'That folder is in the list already.'))
check('a folder is added, its quotes and spaces trimmed',
      image_sync.add_folder('  "%s"  ' % ADDED), (os.path.normpath(ADDED), None))
image_sync.add_folder(OTHER)
check('added folders are listed after Forge\'s, ticked',
      [(f['path'], f['forge'], f['ticked']) for f in image_sync.folders()],
      [(FORGE_DIR, True, True), (ADDED, False, True), (OTHER, False, True)])
off = image_sync.unticked(image_sync.folders(), [ADDED])
check('unticked: Forge\'s folder kept by its key, an added one by its path', off,
      ['outdir_txt2img_samples', OTHER])
opts.model_manager_image_folders_off = '\n'.join(off)
check('an added folder unticked stays unticked', [f['ticked'] for f in image_sync.folders()], [False, True, False])

run([ADDED])
run([OTHER])
synced = db.synced_counts()
check('each folder counts the generations it brought', (synced.get(ADDED.lower()), synced.get(OTHER.lower())), (3, 1))
check('one of Forge\'s folders is not removed: it is unticked',
      image_sync.remove_folder(db, FORGE_DIR), (None, "Forge saves results there: untick it instead."))
check('a folder not in the list is not removed', image_sync.remove_folder(db, os.path.join(OUT, 'nowhere'))[0], None)
freed = {x for r in rows("SELECT gi.prompt_id, gi.negative_id, g.prompt_id, g.negative_id FROM generation_images gi "
                         "JOIN generations g ON g.id = gi.generation_id WHERE gi.path LIKE ?", (ADDED + '%',))
         for x in r if x}
removed, why = image_sync.remove_folder(db, ADDED.upper())
check('Remove takes the folder\'s generations, spelt in any case', (removed, why, images_at(ADDED)), (3, None, []))
check('and leaves the other folder\'s', len(images_at(OTHER)), 1)
check('no image file is touched, and none goes on the removed list',
      ([os.path.exists(p) for p in added_files], [p.lower() in db.removed_images() for p in added_files]),
      ([True] * 3, [False] * 3))
check('nothing of them is left in any table',
      rows("SELECT (SELECT COUNT(*) FROM generation_resources WHERE image_id NOT IN (SELECT id FROM generation_images)),"
           " (SELECT COUNT(*) FROM generation_image_details WHERE image_id NOT IN (SELECT id FROM generation_images)),"
           " (SELECT COUNT(*) FROM generation_details WHERE generation_id NOT IN (SELECT id FROM generations)),"
           " (SELECT COUNT(*) FROM generation_sources WHERE path = ? COLLATE NOCASE)", (ADDED,)),
      [(0, 0, 0, 0)])
check('nor a prompt only they named (#248)', [p for p in unused() if p in freed], [])
check('it is off the list', [f['path'] for f in image_sync.folders()], [FORGE_DIR, OTHER])
image_sync.remove_folder(db, OTHER)
check('an unticked folder removed leaves the off setting too', opts.model_manager_image_folders_off,
      'outdir_txt2img_samples')
image_sync.add_folder(ADDED)
run([ADDED])
check('added again, its images come back', len(images_at(ADDED)), 3)

# ------------------------------------- Remove arriving while Start is starting
# Start reads the folder list, then registers its job as running. On 7880 a
# Remove landing between the two passed the "running" check and took the
# folder off the list; the sync wrote 54 generations under it anyway, which
# no Remove could reach again. Here Remove is sent from inside Start, after
# the list is read and before the job runs, and the sync waits to be let go.
try:
    import threading
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from model_manager.jobs import jobs as image_sync_jobs
    has_fastapi = True
except ImportError:
    has_fastapi = False
if has_fastapi:
    RACE = os.path.join(OUT, 'race')
    save(RACE, '00950-r.png', infotext('race', 9500))
    let_go = threading.Event()
    real_sync = image_sync.ImageSync

    class HeldSync(real_sync):
        def run(self):
            race['force'] = self.force
            let_go.wait(5)
            return super().run()

    image_sync.ImageSync = HeldSync
    race = {'armed': False}
    answers = []

    def store_racing(values):
        store(values)
        if race['armed'] and image_sync.LEVEL_SETTING in values:
            race['armed'] = False
            remover = threading.Thread(target=lambda: answers.append(client.post(
                '/model-manager/generations/sync/folders/remove', data={'path': RACE}).status_code))
            remover.start()
            remover.join(1.0)
            race['remover'] = remover

    image_sync.forge_host.store_settings = store_racing
    from model_manager.api import setup_api                   # noqa: E402
    app = FastAPI()
    setup_api(app)
    client = TestClient(app)
    check('the folder is added through its route',
          client.post('/model-manager/generations/sync/folders/add', data={'path': RACE}).json().get('success'))
    race['armed'] = True
    started = client.post('/model-manager/generations/sync', data={'folders': json.dumps([RACE]),
                                                                   'force': 'true'}).json()
    let_go.set()
    race['remover'].join(5)
    for _ in range(100):
        if not image_sync_jobs.running(image_sync.KIND):
            break
        time.sleep(0.05)
    check('a Remove sent while Start is starting waits, then is refused: the sync is running',
          (started.get('success'), answers), (True, [409]))
    check('Start passes Force sync on to the sync (#246)', race.get('force'), True)
    check('so the folder stays listed, holding what its sync wrote',
          (RACE in [f['path'] for f in image_sync.folders()], db.synced_counts().get(RACE.lower())), (True, 1))
    image_sync.ImageSync = real_sync

# ------------------------------------- a module named with a space (#246)
# Neo writes a module by its stem; a file `x .safetensors` has the stem "x ",
# and the parser strips the text's value to "x".
SPACED = os.path.join(facts['models_dir'], 'VAE', 'spaced .safetensors')
TRIM = os.path.join(OUT, 'trim')
trimmed_image = save(TRIM, '00980-t.png', infotext('a spaced vae', 9800, extra=', Module 1: spaced'))
forge_host.installed_modules = lambda: {'spaced .safetensors': SPACED}
run([TRIM])
check('a module whose file name ends in a space is matched',
      [r[2] for r in resources(trimmed_image) if r[0] == 'module'], [os.path.normpath(SPACED)])

# ------------------------------------------------------- Force sync (#246)
FORCE = os.path.join(OUT, 'force')
lost = save(FORCE, '01000-f.png', infotext('force a', 10000, extra=', Module 1: spaced'))
split_a = save(FORCE, '01001-f.png', infotext('force b', 20000, steps=20), at=10)
split_b = save(FORCE, '01002-f.png', infotext('force c', 20001, steps=30), at=11)
bare = save(FORCE, '01003-n.png', None, at=500)
dropped = save(FORCE, '01004-d.png', infotext('force d', 30000), at=1000)
kept_record = save(FORCE, '01005-r.png', infotext('force e', 40000), at=2000)
db.record_generation({'created_at': '2026-01-03T00:00:00', 'mode': 'txt2img', 'image_count': 1},
                     [{'position': 0, 'path': kept_record, 'infotext': 'the full record'}], [[]])
# Written as 0.58.2 wrote it: the module not found.
forge_host.installed_modules = lambda: {}
run([FORCE], level=PG)
id_of = lambda path: rows("SELECT id FROM generation_images WHERE path = ?", (path,))[0][0]   # noqa: E731
gen_of = lambda path: rows("SELECT generation_id FROM generation_images WHERE path = ?", (path,))[0][0]   # noqa: E731
db.set_generation_image_levels([id_of(lost)], 4)
remember_kept(db, db.delete_generation_image(id_of(dropped))[0])
# Two presses an older rule had joined: one generation holding both.
raw.execute("UPDATE generation_images SET generation_id = ?, position = 1 WHERE path = ?", (gen_of(split_a), split_b))
raw.commit()
recorded_before = rows("SELECT gi.id, gi.generation_id, d.infotext FROM generation_images gi "
                       "JOIN generation_image_details d ON d.image_id = gi.id WHERE gi.path = ?", (kept_record,))
forge_host.installed_modules = lambda: {'spaced .safetensors': SPACED}
run([FORCE], level=UNKNOWN)
check('a plain sync leaves a held image as it was written: no module',
      [r[2] for r in resources(lost) if r[0] == 'module'], [])
forced = image_sync.ImageSync([{'path': FORCE}], UNKNOWN, True, force=True)
forced.run()
check('Force sync reads the synced images again, and says how many',
      (forced.progress.state, forced.progress.again, forced.progress.images), ('done', 4, 4))
check('Force sync gives the image the module it missed',
      [r[2] for r in resources(lost) if r[0] == 'module'], [os.path.normpath(SPACED)])
check('and keeps its rating', level_of(lost)[1], 4)
check('an image without infotext keeps the level of its first sync, whatever this one picked',
      level_of(bare), (PG, None))
check('two presses an older rule joined come out two', gen_of(split_a) != gen_of(split_b), True)
check('a deleted image is not brought back', rows("SELECT COUNT(*) FROM generation_images WHERE path = ?",
                                                  (dropped,))[0][0], 0)
check('a recorded image is untouched: same row, same record',
      rows("SELECT gi.id, gi.generation_id, d.infotext FROM generation_images gi "
           "JOIN generation_image_details d ON d.image_id = gi.id WHERE gi.path = ?", (kept_record,)), recorded_before)
check('no image is held twice',
      rows("SELECT COUNT(*) FROM (SELECT LOWER(path) FROM generation_images GROUP BY LOWER(path) HAVING COUNT(*) > 1)")[0][0], 0)

# Cancel between chunks: what was written is new, the rest keeps its old rows.
before_ids = {p: id_of(p) for p in (lost, split_a, split_b, bare)}
image_sync.CHUNK = 1
forced = image_sync.ImageSync([{'path': FORCE}], UNKNOWN, True, force=True)
real_replace = db.replace_synced_generations


def replace_then_cancel(chunk):
    out = real_replace(chunk)
    forced.cancel()
    return out


db.replace_synced_generations = replace_then_cancel
forced.run()
db.replace_synced_generations = real_replace
image_sync.CHUNK = 200
after_ids = {p: id_of(p) for p in before_ids}
check('a Force sync cancelled after one chunk: one file rewritten, the rest as they were, none lost',
      (forced.progress.state, sum(before_ids[p] != after_ids[p] for p in before_ids), len(after_ids)),
      ('cancelled', 1, 4))

# ---------------------------------------------- Force sync and its prompts (#248)
# A Force sync deletes a file's synced rows and writes them anew: a prompt the
# new rows name again keeps its number, and one only the old rows named goes.
PROMPTS = os.path.join(OUT, 'force-prompts')
save(PROMPTS, '02000-p.png', infotext('force prompt kept', 50000))
save(PROMPTS, '02001-p.png', infotext('force prompt before', 60000), at=5000)
run([PROMPTS])
# A prompt written after them: SQLite gives a new row the highest number
# plus one, so without it a prompt deleted and made again could get its old
# number back, and the check below could not fail.
db.record_generation({'created_at': '2026-01-04T00:00:00', 'mode': 'txt2img', 'image_count': 1,
                      'prompt': 'force prompt later'},
                     [{'position': 0, 'path': os.path.join(OUT, 'force-later.png'), 'prompt': 'force prompt later'}],
                     [[]])
kept_prompt = rows("SELECT id FROM generation_prompts WHERE text = 'force prompt kept'")
save(PROMPTS, '02001-p.png', infotext('force prompt after', 60000), at=5000)
image_sync.ImageSync([{'path': PROMPTS}], UNKNOWN, True, force=True).run()
check('Force sync keeps the number of a prompt the new rows name again',
      rows("SELECT id FROM generation_prompts WHERE text = 'force prompt kept'"), kept_prompt)
check('and drops the prompt only the old rows named, for the new one',
      [rows("SELECT COUNT(*) FROM generation_prompts WHERE text = ?", (t,))[0][0]
       for t in ('force prompt before', 'force prompt after')], [0, 1])
check('no prompt is left that nothing names', unused(), [])

# ---------------------------------------- folders reached through links (#348)
# Sync images walked with os.walk(folder): a symbolic link inside a result
# folder was never entered, a junction always - a junction to a folder above
# it again and again - and a folder reached by two routes brought each image
# twice, as two generations.
import folder_links                                       # noqa: E402

LINKED = os.path.join(OUT, 'links')
real = os.path.join(LINKED, 'real')
older = os.path.join(LINKED, 'older')
link_in, loop_in = os.path.join(real, 'linked'), os.path.join(real, 'self')
route, again_route, kept_route = (os.path.join(LINKED, n) for n in ('route', 'again', 'kept'))
links = [link_in, loop_in, route, again_route, kept_route]
for link in links:
    folder_links.remove(link)
shutil.rmtree(LINKED, ignore_errors=True)


def paths_at(folder):
    # Under the folder itself: "cancel" is how "cancel_route" starts too.
    return [os.path.relpath(p, LINKED) for p, _ in images_at(folder + os.sep)]


def as_copies(folders):
    """A sync as one before #348 ran it: each image by every route, the copy
    of a held file written as new."""
    elsewhere = getattr(image_sync, 'Elsewhere', None)
    drop = getattr(image_sync, 'drop_copies', None)
    if elsewhere:
        holds = elsewhere.holds
        elsewhere.holds = lambda self, path, size, mtime_ns: False
        image_sync.drop_copies = lambda db: (0, [])
    try:
        for folder in folders:
            run([folder])
    finally:
        if elsewhere:
            elsewhere.holds = holds
            image_sync.drop_copies = drop


try:
    save(older, '03000-far.png', infotext('linked far', 70000))
    save(real, '03001-own.png', infotext('linked own', 70001))
    kind = folder_links.symbolic(older, link_in)
    run([real])
    check("a folder of images linked into a result folder, by %s: read, under the link's path" % kind,
          paths_at(real), [os.path.join('real', '03001-own.png'), os.path.join('real', 'linked', '03000-far.png')])
    folder_links.remove(link_in)

    folder_links.junction(real, loop_in)
    check("a junction in a result folder to that folder itself: each image once",
          [os.path.relpath(p, LINKED) for p, _, _ in image_sync.walk(real)], [os.path.join('real', '03001-own.png')])
    folder_links.remove(loop_in)

    NEST = os.path.join(LINKED, 'nest')
    save(NEST, '03010-outer.png', infotext('nest outer', 71000))
    save(os.path.join(NEST, 'inner'), '03011-inner.png', infotext('nest inner', 71001))
    run([os.path.join(NEST, 'inner'), NEST])
    check("a folder inside another ticked folder: each image once, under the first listed",
          [(os.path.relpath(p, LINKED), rows("SELECT path FROM generation_sources WHERE id = "
                                             "(SELECT source_id FROM generations WHERE id = ?)", (g,))[0][0])
           for p, g in images_at(NEST)],
          [(os.path.join('nest', '03010-outer.png'), NEST),
           (os.path.join('nest', 'inner', '03011-inner.png'), os.path.join(NEST, 'inner'))])

    # Two ticked folders, one a junction to the other, neither synced yet.
    TWICE = os.path.join(LINKED, 'twice')
    save(TWICE, '03002-twice.png', infotext('twice', 70002))
    folder_links.junction(TWICE, route)
    run([TWICE, route])
    check('two ticked folders, one a junction to the other: each image once, under the first listed',
          (paths_at(TWICE), paths_at(route)), ([os.path.join('twice', '03002-twice.png')], []))

    # A folder synced, then the same folder by a second route: the image's
    # first record stays, and the new path is never written.
    ONCE = os.path.join(LINKED, 'once')
    first_copy = save(ONCE, '03003-once.png', infotext('once', 70003))
    run([ONCE])
    folder_links.junction(ONCE, again_route)
    run([again_route, ONCE])
    check('a held image found by another route is not added: its first record stays',
          (paths_at(ONCE), paths_at(again_route)), ([os.path.join('once', '03003-once.png')], []))

    # A removed image found by another route stays removed.
    remember_kept(db, db.delete_generation_image(id_of(first_copy))[0])
    run([again_route])
    check('an image removed with its file kept, found by another route, stays removed',
          (paths_at(ONCE), paths_at(again_route)), ([], []))

    # Copies an older sync wrote: the oldest stays, the copies go, a rating
    # moving to the one kept, with the copies' thumbnails.
    KEPT = os.path.join(LINKED, 'copied')
    a = save(KEPT, '03004-a.png', infotext('copied a', 70004))
    b = save(KEPT, '03005-b.png', infotext('copied b', 70005), at=1)
    folder_links.junction(KEPT, kept_route)
    as_copies([KEPT, kept_route])
    a2, b2 = os.path.join(kept_route, '03004-a.png'), os.path.join(kept_route, '03005-b.png')
    db.set_generation_image_levels([id_of(a2)], PG)
    thumb = os.path.join(LINKED, 'a2-thumb.webp')
    open(thumb, 'wb').write(b'webp')
    db.record_thumbnails([(a2, thumb, 1, 1)])
    run([KEPT])
    check("an older sync's copies by another route are removed; the first record of each file stays",
          (paths_at(KEPT), paths_at(kept_route)),
          ([os.path.join('copied', '03004-a.png'), os.path.join('copied', '03005-b.png')], []))
    check("the copy's rating moves to the image kept, which had none",
          rows("SELECT user_nsfw_level FROM generation_images WHERE path = ?", (a,)), [(PG,)])
    check("and the copy's thumbnail goes", (os.path.exists(thumb), db.thumbnail_rows([a2])), (False, {}))

    # A recorded image, and a synced copy of it by a link.
    RECORDED = os.path.join(LINKED, 'recorded')
    shot = save(RECORDED, '03006-shot.png', infotext('recorded shot', 70006))
    db.record_generation({'created_at': '2026-01-05T00:00:00', 'mode': 'txt2img', 'image_count': 1,
                          'prompt': 'recorded shot'}, [{'position': 0, 'path': shot, 'prompt': 'recorded shot'}], [[]])
    recorded_row = rows("SELECT id, generation_id FROM generation_images WHERE path = ?", (shot,))
    shot_route = os.path.join(LINKED, 'shot_route')
    links.append(shot_route)
    folder_links.junction(RECORDED, shot_route)
    as_copies([shot_route])
    copied = len(paths_at(shot_route))
    run([shot_route])
    check('a recorded image and a synced copy of it by a link: the copy goes, the recorded row is untouched',
          (copied, paths_at(shot_route), rows("SELECT id, generation_id FROM generation_images WHERE path = ?", (shot,))),
          (1, [], recorded_row))

    # Cancelled while writing: nothing removed.
    CANCEL = os.path.join(LINKED, 'cancel')
    save(CANCEL, '03007-c.png', infotext('cancel c', 70007))
    cancel_route = os.path.join(LINKED, 'cancel_route')
    links.append(cancel_route)
    folder_links.junction(CANCEL, cancel_route)
    as_copies([CANCEL, cancel_route])
    # One new image, one chunk: the cancel comes after the last, where the
    # write loop has nothing left to stop.
    save(CANCEL, '03008-d.png', infotext('cancel d', 70008), at=9000)
    halted = image_sync.ImageSync([{'path': CANCEL}], UNKNOWN, True)
    real_record = db.record_generations


    def record_then_halt(chunk):
        out = real_record(chunk)
        halted.cancel()
        return out


    db.record_generations = record_then_halt
    halted.run()
    db.record_generations = real_record
    check('a Sync images cancelled while writing removes no copy',
          (len(paths_at(CANCEL)), paths_at(cancel_route)), (2, [os.path.join('cancel_route', '03007-c.png')]))
finally:
    for link in links:
        folder_links.remove(link)
    shutil.rmtree(LINKED, ignore_errors=True)

print('image_sync: %d failure(s)' % len(fails))
for f in fails:
    print('FAIL ' + f)
sys.exit(1 if fails else 0)
