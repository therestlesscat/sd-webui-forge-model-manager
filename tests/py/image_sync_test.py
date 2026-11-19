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
from model_manager.nsfw import PG, PROMPT_LEVEL, R, UNKNOWN, X, generated_level  # noqa: E402

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
check('an image with no text reads as none, with its size, and no prompts', read_text(bare), (None, 64, 64, None))
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

# Sent with a checkpoint of the library's instead, picked in the dialog by
# Forge's name for it (#377). The generation names a hash nothing knows, so
# the pick counts as another model's.
sd_models = types.ModuleType('modules.sd_models')
picked = types.SimpleNamespace(filename=V_PATH, title='model_v0.safetensors [aaaa]')
sd_models.checkpoints_list = {'v': picked}
sd_models.checkpoint_aliases = {'model_v0.safetensors [aaaa]': picked}
sys.modules['modules.sd_models'] = sd_models
plan = send_plan(db, gid_unmatched, use_checkpoint='model_v0.safetensors [aaaa]')
check('a checkpoint picked, Send sets up that very file, and says which, and what it is to the image',
      (plan.get('checkpoint'), plan.get('instead'), plan.get('checkpoint_missing'), plan.get('pick')),
      ('model_v0.safetensors [aaaa]', os.path.basename(V_PATH), None, 'model'))
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

# ------------------------------------- other tools' prompts, stored (#408)
from model_manager import nsfw as nsfw_rules                              # noqa: E402
from model_manager.image_text import read_text as real_read_text          # noqa: E402

# A word the bundled list rates explicit, found here so none is written down.
EXPLICIT = next(w.strip() for w in open(nsfw_rules.PROMPT_WORDS_FILE, encoding='utf-8')
                if w.strip() and not w.startswith('#') and generated_level({'prompt': 'a ' + w.strip()}) > PG)
pattern_before = getattr(opts, 'samples_filename_pattern', None)
opts.samples_filename_pattern = '[model_name]-[steps]'


def save_prompts(folder, name, prompt, negative=None, at=0.0, tool_chunk=True):
    """A PNG as Endless-Nodes' Image_saver writes one: plain prompt chunks, no infotext."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    info = PngInfo()
    info.add_text('prompt', prompt)
    if negative is not None:
        info.add_text('negative_prompt', negative)
    if tool_chunk:
        info.add_text('batch_index', '0')
    Image.new('RGB', (64, 64), (40, 50, 60)).save(path, pnginfo=info)
    stamp = int((BASE + at) * 1e9)
    os.utime(path, ns=(stamp, stamp))
    return path


def stored(path):
    """What a sync stored of an image: its prompt, negative, infotext, level, data, generation."""
    row = rows("SELECT p.text, q.text, d.infotext, gi.prompt_nsfw_level, gi.user_nsfw_level, d.meta, "
               "gi.generation_id FROM generation_images gi "
               "LEFT JOIN generation_prompts p ON p.id = gi.prompt_id "
               "LEFT JOIN generation_prompts q ON q.id = gi.negative_id "
               "LEFT JOIN generation_image_details d ON d.image_id = gi.id WHERE gi.path = ?", (path,))[0]
    return {'prompt': row[0], 'negative': row[1], 'infotext': row[2], 'level': row[3], 'rating': row[4],
            'meta': json.loads(row[5]) if row[5] else None, 'generation': row[6]}


OTHERS = os.path.join(OUT, 'others')
spicy = save_prompts(OTHERS, '03000-modelx-20.png', 'a portrait, %s, <lora:x:1>' % EXPLICIT, 'blurry')
plain = save_prompts(OTHERS, '03001-modelx-30.png', 'a quiet lake', '  ', at=500, tool_chunk=False)
run([OTHERS], level=PG)
got = stored(spicy)
check('408. a prompts-only image: its prompt and negative stored, its infotext empty',
      (got['prompt'], got['negative'], got['infotext']), ('a portrait, %s, <lora:x:1>' % EXPLICIT, 'blurry', None))
check('408. its level judged from them as an image with text is, above the dialog\'s PG',
      (got['level'], got['level'] > PG), (generated_level(got['meta']), True))
check('408. its data: the prompts, Made with, the size and what the file name gives',
      got['meta'], {'prompt': 'a portrait, %s, <lora:x:1>' % EXPLICIT, 'negativePrompt': 'blurry',
                    'Made with': 'Endless', 'Model': 'modelx', 'Steps': '20', 'Size': '64x64',
                    'Read from': 'text in the file, file name'})
check('408. its <lora:> tag names no file',
      rows("SELECT COUNT(*) FROM generation_resources r JOIN generation_images gi ON gi.id = r.image_id "
           "WHERE gi.path = ? AND r.role = 'lora'", (spicy,))[0][0], 0)
check('408. "Prompt, as written" files it under its prompt: its generation\'s own prompt row',
      rows("SELECT p.text FROM generations g JOIN generation_prompts p ON p.id = g.prompt_id WHERE g.id = ?",
           (got['generation'],)), [('a portrait, %s, <lora:x:1>' % EXPLICIT,)])
check('408. its generation\'s settings from the file name, Made with not among them',
      rows("SELECT steps, sampler FROM generation_params WHERE generation_id = ?", (got['generation'],)),
      [(20, None)])
got = stored(plain)
check('408. a blank negative stores none, and a prompt with no tool\'s mark no Made with',
      (got['prompt'], got['negative'], 'Made with' in got['meta']), ('a quiet lake', None, False))

JOINS = os.path.join(OUT, 'others-join')
first = save_prompts(JOINS, '03100-modely-20.png', 'a red barn', at=0)
other = save_prompts(JOINS, '03101-modely-20.png', 'a blue barn', at=0.2)
same = save_prompts(JOINS, '03102-modely-20.png', 'a blue barn', at=0.4)
empty = save(JOINS, '03103-modely-20.png', None, at=0.6)
run([JOINS], level=PG)
check('408. images whose names join: other prompts stay apart, the same prompts join, none never joins one',
      [stored(path)['generation'] for path in (first, other, same, empty)].count(stored(other)['generation']),
      2)
check('408. and the four make three generations', len({stored(p)['generation'] for p in (first, other, same, empty)}), 3)
JOINS_EMPTY = os.path.join(OUT, 'others-join-empty')
empties = [save(JOINS_EMPTY, '%05d-modely-20.png' % (3200 + n), None, at=n * 0.2) for n in range(2)]
run([JOINS_EMPTY], level=PG)
check('408. two images with nothing join by their names, as before',
      len({stored(p)['generation'] for p in empties}), 1)

# Read every image again, as the prompts a file holds change.
AGAIN = os.path.join(OUT, 'others-again')
gains = save(AGAIN, '03300-modelz-20.png', None, at=0)
loses = save_prompts(AGAIN, '03301-modelz-20.png', 'a %s scene' % EXPLICIT, at=500)
still = save(AGAIN, '03302-modelz-20.png', None, at=1000)
run([AGAIN], level=UNKNOWN)
db.set_generation_image_levels([id_of(gains)], 4)
judged_before = stored(loses)['level']
save_prompts(AGAIN, '03300-modelz-20.png', 'a %s view' % EXPLICIT, at=0)
save(AGAIN, '03301-modelz-20.png', None, at=500)
image_sync.ImageSync([{'path': AGAIN}], PG, True, force=True).run()
check('408. read again after a file gained a prompt: judged from it, not left at the first sync\'s Unknown; '
      'its rating kept', (stored(gains)['level'], stored(gains)['rating']), (generated_level(stored(gains)['meta']), 4))
check('408. read again after a file lost its prompt: this sync\'s level, not the one its prompt was judged',
      (stored(loses)['level'], judged_before != PG), (PG, True))
check('408. read again, an image still with nothing: the level of its first sync',
      stored(still)['level'], UNKNOWN)

# Rows an earlier version wrote, JSON stored as the infotext and the prompt.
OLD_JSON = os.path.join(OUT, 'others-json')
os.makedirs(OLD_JSON, exist_ok=True)
SWARM_JSON = json.dumps({'sui_image_params': {'prompt': 'a %s tower' % EXPLICIT, 'negativeprompt': 'fog'}})
UNKNOWN_JSON = json.dumps({'note': 'a tool nobody knows'})
swarm_old = save(OLD_JSON, '03400-modelw-20.png', SWARM_JSON, at=0)
unknown_old = save(OLD_JSON, '03401-modelw-20.png', UNKNOWN_JSON, at=500)
# As an earlier version read them: the JSON taken for text.
image_sync.read_text = lambda path: ((SWARM_JSON if path == swarm_old else UNKNOWN_JSON), 64, 64, None)
run([OLD_JSON], level=PG)
image_sync.read_text = real_read_text
db.set_generation_image_levels([id_of(swarm_old)], 2)
# Three levels apart - stored before (PG), this sync's (R), judged (X) - so
# the check below tells which one the row came out with.
raw.execute("UPDATE generation_images SET prompt_nsfw_level = ? WHERE path = ?", (PG, swarm_old))
raw.commit()
check('as an earlier version stored them: the JSON as infotext and prompt',
      [stored(p)['infotext'] for p in (swarm_old, unknown_old)], [SWARM_JSON, UNKNOWN_JSON])
image_sync.ImageSync([{'path': OLD_JSON}], R, True, force=True).run()
got = stored(swarm_old)
check('408. SwarmUI\'s JSON read again: prompts-only, judged, its rating kept, the JSON\'s prompt row gone',
      (got['prompt'], got['negative'], got['infotext'], got['level'], got['rating'],
       rows("SELECT COUNT(*) FROM generation_prompts WHERE text = ?", (SWARM_JSON,))[0][0]),
      ('a %s tower' % EXPLICIT, 'fog', None, X, 2, 0))
got = stored(unknown_old)
check('408. JSON nobody knows read again: nothing, at this sync\'s level - it had infotext, so no first level',
      (got['prompt'], got['infotext'], got['level']), (None, None, R))

# A restamp after the words change.
raw.execute("UPDATE generation_images SET prompt_nsfw_level = ? WHERE path IN (?, ?)", (PG, plain, still))
raw.commit()
db.restamp_generation_levels(lambda meta: PROMPT_LEVEL)
check('408. a restamp judges a prompts-only image again; one with nothing keeps its level',
      (stored(plain)['level'], stored(still)['level']), (PROMPT_LEVEL, PG))
check('no prompt is left that nothing names', unused(), [])

# Send's server, for a prompts-only image (#408).
from model_manager import send as send_module                               # noqa: E402
SENDS = os.path.join(OUT, 'others-send')
CK_STEM = os.path.splitext(os.path.basename(CHECKPOINT))[0]
# An earlier section's sync read the fixture's file, no real checkpoint, as
# Unknown: filed as a checkpoint again, as the suite's top files it.
raw.execute("UPDATE files SET file_type = 'Checkpoint' WHERE file_path = ?", (CHECKPOINT,))
raw.commit()
po_free = save_prompts(SENDS, 'freeform.png', 'a free <lora:alias_x:0.5> scene', 'dull', at=0)
po_known = save_prompts(SENDS, '03500-%s-25.png' % CK_STEM, 'a known scene', at=500)
po_unknown = save_prompts(SENDS, '03501-nomodel_here-25.png', 'an unknown scene', at=1000)
run([SENDS], level=PG)
gen = {path: stored(path)['generation'] for path in (po_free, po_known, po_unknown)}
sd_models = types.ModuleType('modules.sd_models')
sd_models.checkpoints_list = {'c': types.SimpleNamespace(filename=CHECKPOINT, title='%s.safetensors [abcd]' % CK_STEM)}
sd_models.checkpoint_aliases = {'%s.safetensors [abcd]' % CK_STEM: sd_models.checkpoints_list['c']}
sys.modules['modules.sd_models'] = sd_models
# getattr: on the code before #411 there is no family_plan, and the checks
# below fail rather than the suite.
family_before, offered_before = getattr(send_module, 'family_plan', None), forge_host.installed_modules
forge_host.installed_modules = lambda: {'sdxl_vae.safetensors': VAE}
# Its checkpoint's family needs a kind Forge offers none of - T5 for a Flux
# file - which a Civitai image's plan names, and this one dropped (#411).
send_module.family_plan = lambda db_, path, found=None: {
    'target': ['family_of_%s' % os.path.basename(path)], 'missing': ['t5xxl'], 'not_found': [], 'bundled': []}
check('408. Send\'s plan for a generation that names no checkpoint: a stop of its own, not_named',
      send_plan(db, gen[po_free])['checkpoint_problem'], {'reason': 'not_named'})
known_plan = send_plan(db, gen[po_known])
check('408. one whose file name names a checkpoint the library has: that checkpoint, with its family\'s VAE '
      'and text encoders, not the empty list it recorded',
      (known_plan['checkpoint'], known_plan['target'], known_plan.get('checkpoint_problem')),
      ('%s.safetensors [abcd]' % CK_STEM, ['family_of_%s' % os.path.basename(CHECKPOINT)], None))
check('411. and the kind its family needs that Forge offers none of, handed to the page as missing',
      (known_plan.get('missing'), known_plan['modules_missing']), (['t5xxl'], []))
# Its own checkpoint picked: a pick of the same file, which for a generation
# with text keeps the modules it recorded - this one recorded none.
picked_plan = send_plan(db, gen[po_known], use_checkpoint='%s.safetensors [abcd]' % CK_STEM)
check('408. its own checkpoint picked in the Resources dialog: with its family\'s modules, not none',
      (picked_plan['checkpoint'], picked_plan['target']),
      ('%s.safetensors [abcd]' % CK_STEM, ['family_of_%s' % os.path.basename(CHECKPOINT)]))
check('one whose file name names a checkpoint the library lacks: today\'s stop, naming it',
      send_plan(db, gen[po_unknown])['checkpoint_problem'], {'reason': 'missing', 'name': 'nomodel_here'})
recorded_plan = send_plan(db, gid_matched)
check('a generation with text keeps the modules it recorded', recorded_plan['target'], ['sdxl_vae.safetensors'])
send_module.family_plan, forge_host.installed_modules = family_before, offered_before
del sys.modules['modules.sd_models']
po_settings = send_module.settings(db, {'kind': 'generation', 'generation': gen[po_free],
                                        'renames': [{'from': 'alias_x', 'to': 'file_x'}]})
check('408. its text, built from its data, the chips\' rename applied',
      po_settings['text'].split('\n')[:2], ['a free <lora:file_x:0.5> scene', 'Negative prompt: dull'])
# A file name's sampler with its schedule type folded in, which the paste splits.
raw.execute("UPDATE generation_image_details SET meta = json_set(meta, '$.Sampler', 'DPM++ 2M Karras') "
            "WHERE image_id = (SELECT id FROM generation_images WHERE path = ?)", (po_free,))
raw.commit()
lists_before = send_module.forge_lists
send_module.forge_lists = lambda: (['Euler a', 'DPM++ 2M'], ['Automatic', 'Karras'])
check('408. the schedule type set after the paste is the one the built text gives, not Automatic',
      send_module.settings(db, {'kind': 'generation', 'generation': gen[po_free]})['scheduler'], 'Karras')
send_module.forge_lists = lists_before
check('408. into img2img, the prompts go with the picture',
      send_module.settings(db, {'kind': 'generation', 'generation': gen[po_free]}, into=True)['text'].split('\n')[0],
      'a free <lora:alias_x:0.5> scene')
check('408. a whole generation\'s Send - a model\'s gallery card - builds the same way',
      send_module.settings(db, {'kind': 'generation', 'generation': gen[po_known], 'whole': True})['text'].split('\n')[0],
      'a known scene')
opts.samples_filename_pattern = pattern_before

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

# A seed of 0 is a seed (#409): `or` once stored none for it. The file's name
# gives no seed, so the text's is the only one there to store.
SEED_ZERO = os.path.join(WORK, 'seed_zero')
zero = save(SEED_ZERO, '00001-a.png', infotext('a lighthouse at dawn', 0))
run([SEED_ZERO])
check('409. an image whose text says Seed: 0 is stored with seed 0',
      rows("SELECT seed FROM generation_images WHERE path = ?", (zero,)), [(0,)])

# ComfyUI's files (#232): a PNG's run version in `prompt`, the editor version
# in `workflow`; a WebP's in the EXIF's Model and Make.
COMFY = os.path.join(WORK, 'comfy')
CK_FILE = os.path.basename(CHECKPOINT)


def run_graph(seed=4321, prompt='a lighthouse at dusk', checkpoint='SD\\' + CK_FILE, loras=(), loader='Checkpoint',
              vae='sdxl_vae.safetensors', clips=None):
    """ComfyUI's SD 1.5 graph, as its own save writes the run version."""
    def node(kind, **inputs):
        return {"class_type": kind, "inputs": inputs}
    graph = {
        "5": node("EmptyLatentImage", width=512, height=768, batch_size=1),
        "7": node("CLIPTextEncode", text="blurry", clip=["4", 1]),
        "3": node("KSampler", seed=seed, steps=25, cfg=7.5, sampler_name="dpmpp_2m", scheduler="karras",
                  denoise=1.0, model=["4", 0], positive=["6", 0], negative=["7", 0], latent_image=["5", 0]),
        "8": node("VAEDecode", samples=["3", 0], vae=["40", 0] if vae else ["4", 2]),
        "9": node("SaveImage", filename_prefix="ComfyUI", images=["8", 0]),
    }
    graph["4"] = node("UNETLoader", unet_name=checkpoint, weight_dtype="default") if loader == 'UNET' \
        else node("CheckpointLoaderSimple", ckpt_name=checkpoint)
    graph["6"] = node("CLIPTextEncode", text=prompt, clip=["4", 1]) if prompt is not None \
        else node("SomeTextNodeNobodyKnows", clip=["4", 1])
    if vae:
        graph["40"] = node("VAELoader", vae_name=vae)
    if clips:
        graph["41"] = node("DualCLIPLoader", clip_name1=clips[0], clip_name2=clips[1], type="flux")
        graph["6"]["inputs"]["clip"] = ["41", 0]
    model = ["4", 0]
    for n, (name, strength) in enumerate(loras):
        graph[str(50 + n)] = node("LoraLoader", lora_name=name, strength_model=strength, strength_clip=strength,
                                  model=model, clip=["4", 1])
        model = [str(50 + n), 0]
    graph["3"]["inputs"]["model"] = model
    return graph


def save_comfy(folder, name, graph=None, workflow=None, plain=None, kind='png', at=0.0):
    """A file as ComfyUI's save writes one: its graphs as JSON text."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    image = Image.new('RGB', (64, 64), (70, 80, 90))
    if kind == 'png':
        info = PngInfo()
        if plain is not None:
            info.add_text('prompt', plain)
            info.add_text('negative_prompt', 'blurry')
            info.add_text('batch_index', '0')
        elif graph is not None:
            info.add_text('prompt', json.dumps(graph))
        if workflow is not None:
            info.add_text('workflow', json.dumps(workflow))
        image.save(path, pnginfo=info)
    else:
        # As ComfyUI's WebP save writes them, at the EXIF's top level, which
        # PIL 9.5 writes out too (#370's trap is the Exif sub-IFD).
        exif = Image.Exif()
        if graph is not None:
            exif[0x0110] = 'prompt:' + json.dumps(graph)
        if workflow is not None:
            exif[0x010F] = 'workflow:' + json.dumps(workflow)
        image.save(path, exif=exif.tobytes())
    stamp = int((BASE + at) * 1e9)
    os.utime(path, ns=(stamp, stamp))
    return path


def editor_version(prompt='an editor prompt'):
    """The SD 1.5 graph as ComfyUI's canvas holds it, with no run version."""
    def n(nid, kind, widgets, inputs=(), outputs=()):
        return {"id": nid, "type": kind, "mode": 0, "widgets_values": widgets,
                "inputs": [{"name": k, "type": t, "link": l} for k, l, t in inputs], "outputs": [{"type": t} for t in outputs]}
    return {"nodes": [
        n(4, "CheckpointLoaderSimple", [CK_FILE], outputs=("MODEL", "CLIP", "VAE")),
        n(5, "EmptyLatentImage", [512, 768, 1]),
        n(6, "CLIPTextEncode", [prompt], [("clip", 3, "CLIP")]),
        n(7, "CLIPTextEncode", ["blurry"], [("clip", 4, "CLIP")]),
        n(3, "KSampler", [777, "fixed", 30, 6.0, "euler", "normal", 1.0],
          [("model", 1, "MODEL"), ("positive", 5, "CONDITIONING"), ("negative", 6, "CONDITIONING"),
           ("latent_image", 2, "LATENT")]),
        n(8, "VAEDecode", [], [("samples", 7, "LATENT"), ("vae", 8, "VAE")]),
        n(9, "SaveImage", ["x"], [("images", 9, "IMAGE")]),
        n(10, "LoraLoader", [LORA_NAME + ".safetensors", 0.8, 0.8], [("model", 10, "MODEL"), ("clip", 11, "CLIP")],
          outputs=("MODEL", "CLIP"))],
        "links": [[1, 10, 0, 3, 0, "MODEL"], [10, 4, 0, 10, 0, "MODEL"], [11, 4, 1, 10, 1, "CLIP"], [2, 5, 0, 3, 3, "LATENT"], [3, 4, 1, 6, 0, "CLIP"], [4, 4, 1, 7, 0, "CLIP"],
                  [5, 6, 0, 3, 1, "CONDITIONING"], [6, 7, 0, 3, 2, "CONDITIONING"], [7, 3, 0, 8, 0, "LATENT"],
                  [8, 4, 2, 8, 1, "VAE"], [9, 8, 0, 9, 0, "IMAGE"]]}


def settings_row(path):
    return rows("SELECT gp.sampler, gp.schedule_type, gp.steps, gp.cfg FROM generation_params gp JOIN "
                "generation_images gi ON gi.generation_id = gp.generation_id WHERE gi.path = ?", (path,))


def seed_of(path):
    return rows("SELECT seed FROM generation_images WHERE path = ?", (path,))[0][0]


GRAPH_META = {'prompt': 'a lighthouse at dusk', 'negativePrompt': 'blurry', 'Made with': 'ComfyUI',
              'Sampler': 'dpmpp_2m', 'scheduler': 'karras', 'Steps': 25, 'CFG scale': 7.5, 'Seed': 4321,
              'Size': '512x768', 'Model': os.path.splitext(CK_FILE)[0], 'Module 1': 'sdxl_vae.safetensors',
              'Read from': 'workflow'}
png = save_comfy(COMFY, 'ComfyUI_00001_.png', run_graph(loras=[('characters\\' + LORA_NAME + '.safetensors', 0.6)]),
                 workflow={'nodes': [], 'links': []})
webp = save_comfy(COMFY, 'ComfyUI_00002_.webp', run_graph(seed=99), workflow={'nodes': []}, kind='webp', at=1)
unet = save_comfy(COMFY, 'ComfyUI_00003_.png', run_graph(seed=7, loader='UNET', vae=None), at=2)
missing = save_comfy(COMFY, 'ComfyUI_00004_.png', run_graph(seed=8, checkpoint='nowhere_xl.safetensors'), at=3)
flux = save_comfy(COMFY, 'ComfyUI_00005_.png', run_graph(seed=9, clips=('t5xxl_fp16.safetensors', 'clip_l.safetensors')),
                  at=4)
CLIP_L = os.path.join(facts['models_dir'], 'text_encoder', 'clip_l.safetensors')
no_prompt = save_comfy(COMFY, 'ComfyUI_00007_.png', run_graph(seed=10, prompt=None, loras=[(LORA_NAME + '.safetensors', 0.4)]),
                       at=6)
blank = save_comfy(COMFY, 'ComfyUI_00008_.png', run_graph(seed=11, prompt='  \n '), at=7)
editor_webp = save_comfy(COMFY, 'ComfyUI_00009_.webp', workflow=editor_version(), kind='webp', at=8)
modules_before = forge_host.installed_modules
forge_host.installed_modules = lambda: {'sdxl_vae.safetensors': VAE, 'clip_l.safetensors': CLIP_L}
run([COMFY], level=R)
forge_host.installed_modules = modules_before
got = stored(png)
check('232. a ComfyUI PNG: its prompts, its settings under the file-name names, Made with ComfyUI',
      (got['prompt'], got['negative'], got['infotext'], got['meta']),
      ('a lighthouse at dusk', 'blurry', None, GRAPH_META))
check('232. its schedule type in the settings row', settings_row(png), [('dpmpp_2m', 'karras', 25, 7.5)])
check('232. its seed in its column', seed_of(png), 4321)
check('232. its level judged from its prompt', got['level'], generated_level(got['meta']))
# The role a module the text names is recorded under, as the matching section saw it.
VAE_ROLE = next(r[0] for r in resources(matched) if r[2] == VAE)
check('232. its checkpoint found by stem, its LoRA by stem with its strength, its VAE as a module',
      sorted((r[0], r[2], r[3]) for r in resources(png)),
      sorted([('checkpoint', CHECKPOINT, None), ('lora', LORA_PATH, 0.6), (VAE_ROLE, VAE, None)]))
got = stored(webp)
check('232. a ComfyUI WebP, its graph in the EXIF: read as the PNG is',
      (got['prompt'], got['meta'].get('Sampler'), seed_of(webp), [r[2] for r in resources(webp) if r[0] == 'checkpoint']),
      ('a lighthouse at dusk', 'dpmpp_2m', 99, [CHECKPOINT]))
check('232. a bare diffusion model (UNETLoader) the library files as a Checkpoint: found',
      [r[2] for r in resources(unet) if r[0] == 'checkpoint'], [CHECKPOINT])
check('232. a checkpoint the library lacks: kept by name',
      [(r[1], r[2]) for r in resources(missing) if r[0] == 'checkpoint'], [('nowhere_xl', None)])
check('232. and Send\'s plan stops as missing, naming it',
      send_plan(db, stored(missing)['generation']).get('checkpoint_missing'), 'nowhere_xl')
got = stored(flux)
check('232. a Flux graph whose T5 Forge lacks: kept by name in its data, beside the two matched',
      ([got['meta'].get('Module %d' % n) for n in (1, 2, 3)],
       sorted(r[2] for r in resources(flux) if r[0] in ('module', 'vae'))),
      (['sdxl_vae.safetensors', 't5xxl_fp16.safetensors', 'clip_l.safetensors'], sorted([VAE, CLIP_L])))
BIG = os.path.join(WORK, 'comfy-big-seed')
big_seed = save_comfy(BIG, 'ComfyUI_00006_.png', run_graph(seed=2 ** 64 - 1))
beside = save_comfy(BIG, 'ComfyUI_00007_.png', run_graph(seed=12), at=1)
strong = save_comfy(BIG, 'ComfyUI_00008_.png', run_graph(seed=14, loras=[(LORA_NAME + '.safetensors', 10 ** 19)]), at=2)
try:
    run([BIG], level=PG)
    outcome = (seed_of(big_seed), seed_of(beside))
except Exception as e:                    # noqa: BLE001 - a failed write is the fault
    outcome = type(e).__name__
check('232. a seed of 2^64 - 1: no seed for it, and the chunk written with the rest', outcome, (None, 12))
check('232. a LoRA strength written as a whole number past 64 bits: kept as a number, the chunk written',
      [r[3] for r in resources(strong) if r[0] == 'lora'] if outcome != 'OverflowError' else outcome, [1e19])
# A text a saver wrote with such a seed failed its chunk's write, and every
# sync after it at the same file: no seed for it, its infotext kept whole.
FORGE_BIG = os.path.join(WORK, 'forge-big-seed')
# At the edge: 2^63 is past it, 2^63 - 1 is kept.
forge_big_text = infotext('a big seed', 2 ** 63, extra=', Variation seed: %d' % (2 ** 64 - 2))
forge_edge_text = infotext('an edge seed', 2 ** 63 - 1)
forge_big = save(FORGE_BIG, '03900-f.png', forge_big_text)
forge_edge = save(FORGE_BIG, '03901-f.png', forge_edge_text, at=600)
# A press of such seeds, read whole, still joins by seed + 1.
pressed = [save(FORGE_BIG, '%05d-f.png' % (3910 + n), infotext('a pressed seed', 2 ** 64 - 2 + n), at=1200 + n * 0.2)
           for n in range(2)]
try:
    run([FORGE_BIG], level=PG)
    outcome = rows("SELECT gi.seed, gi.subseed, d.infotext FROM generation_images gi JOIN generation_image_details d "
                   "ON d.image_id = gi.id WHERE gi.path IN (?, ?) ORDER BY gi.path", (forge_big, forge_edge))
except Exception as e:                    # noqa: BLE001 - a failed write is the fault
    outcome = type(e).__name__
check('232. a Forge text\'s seed of 2^63 and a variation seed past it: none stored, its infotext whole; 2^63 - 1 '
      'kept; the chunk written', outcome, [(None, None, forge_big_text), (2 ** 63 - 1, None, forge_edge_text)])
check('232. two images of one press whose seeds are past 2^63: one generation, as they join by seed + 1',
      len({stored(p)['generation'] for p in pressed}) if outcome != 'OverflowError' else outcome, 1)
try:
    image_sync.ImageSync([{'path': FORGE_BIG}], PG, True, force=True).run()
    outcome = rows("SELECT gi.seed, d.infotext FROM generation_images gi JOIN generation_image_details d "
                   "ON d.image_id = gi.id WHERE gi.path = ?", (forge_big,))
except Exception as e:                    # noqa: BLE001 - a failed write is the fault
    outcome = type(e).__name__
check('232. Read every image again over it: rebuilt, its seed none, its infotext whole', outcome,
      [(None, forge_big_text)])
got = stored(no_prompt)
check('232. a graph whose prompt cannot be reached: its settings and LoRAs, no prompt in its data - Send\'s '
      'refusal reads that - and the dialog\'s level',
      (got['prompt'], 'prompt' in got['meta'], got['meta'].get('Sampler'), got['meta'].get('Made with'), got['level'],
       [(r[2], r[3]) for r in resources(no_prompt) if r[0] == 'lora']),
      (None, False, 'dpmpp_2m', 'ComfyUI', R, [(LORA_PATH, 0.4)]))
got = stored(blank)
check('232. a graph whose prompt is spaces alone: no prompt, as #408 trims one, and the dialog\'s level',
      (got['prompt'], 'prompt' in got['meta'], got['level']), (None, False, R))
got = stored(editor_webp)
check('232. a ComfyUI WebP holding only the editor version, in the EXIF\'s Make: read from it',
      (got['prompt'], got['meta'].get('Sampler'), seed_of(editor_webp)), ('an editor prompt', 'euler', 777))
check('232. each ComfyUI file its own generation',
      len({stored(p)['generation'] for p in (png, webp, unet, missing, flux, no_prompt, blank, editor_webp)}), 8)

PATTERN = os.path.join(WORK, 'comfy-pattern')
pair = [save_comfy(PATTERN, '%05d-modelx-20.png' % (3500 + n), run_graph(seed=55), at=n * 0.2) for n in range(2)]
# Names the library's pattern reads, as #408's joining images do; two files
# with nothing of the graph's and those names would join.
pattern_was = getattr(opts, 'samples_filename_pattern', None)
opts.samples_filename_pattern = '[model_name]-[steps]'
run([PATTERN], level=PG)
opts.samples_filename_pattern = pattern_was
check('232. two ComfyUI files whose names fit the library\'s pattern, the same graph and seed: two generations',
      len({stored(p)['generation'] for p in pair}), 2)
check('232. the graph\'s steps over the file name\'s, in its data and its settings row',
      (stored(pair[0])['meta']['Steps'], settings_row(pair[0])[0][2]), (25, 25))
# A name giving a model hash the library has and a schedule type: the graph's
# checkpoint, one the library lacks, and its schedule type win.
HASHED = os.path.join(WORK, 'comfy-hashed')
# The file the matching section gave the hash 0123456789, filed as a
# checkpoint as the suite's top files its own: the name's hash finds it,
# unless the graph's checkpoint goes first.
raw.execute("UPDATE files SET file_type = 'Checkpoint' WHERE file_path = ?", (downloaded,))
raw.commit()
check('232. (the library holds a checkpoint under the name\'s hash, so the next check can tell)',
      db.hash_index().get('0123456789'), (downloaded, 'Checkpoint'))
hashed = save_comfy(HASHED, '0123456789-Normal.png', run_graph(seed=56, checkpoint='nowhere_xl.safetensors'))
opts.samples_filename_pattern = '[model_hash]-[scheduler]'
run([HASHED], level=PG)
opts.samples_filename_pattern = pattern_was
got = stored(hashed)
check('232. the graph\'s checkpoint over a file name\'s model hash, its schedule type over the name\'s',
      ([(r[1], r[2]) for r in resources(hashed) if r[0] == 'checkpoint'], 'Schedule type' in got['meta'],
       settings_row(hashed)[0][1]),
      ([('nowhere_xl', None)], False, 'karras'))

SAVER = os.path.join(WORK, 'comfy-saver')
os.makedirs(SAVER, exist_ok=True)
saver = os.path.join(SAVER, '03600-s.png')
info = PngInfo()
info.add_text('parameters', infotext('an image saver picture', 61))
info.add_text('prompt', json.dumps(run_graph(seed=62)))
Image.new('RGB', (64, 64), (1, 2, 3)).save(saver, pnginfo=info)
run([SAVER], level=PG)
got = stored(saver)
check('232. an Image-Saver PNG, Forge\'s text and a graph: Forge\'s text, as today',
      (got['infotext'], seed_of(saver), 'Made with' in (got['meta'] or {})),
      (infotext('an image saver picture', 61), 61, False))

ENDLESS = os.path.join(WORK, 'comfy-endless')
endless = save_comfy(ENDLESS, '03700-e.png', workflow=editor_version(), plain='the plain prompt')
run([ENDLESS], level=PG)
got = stored(endless)
check('232. an Endless PNG: its prompts as #408 reads them, its settings, checkpoint and LoRAs from the editor version',
      (got['prompt'], got['negative'], got['meta'].get('Made with'), got['meta'].get('Sampler'),
       got['meta'].get('Steps'), seed_of(endless), sorted((r[0], r[2], r[3]) for r in resources(endless)
                                                         if r[0] in ('checkpoint', 'lora'))),
      ('the plain prompt', 'blurry', 'ComfyUI', 'euler', 30, 777,
       sorted([('checkpoint', CHECKPOINT, None), ('lora', LORA_PATH, 0.8)])))

COMFY_AGAIN = os.path.join(WORK, 'comfy-again')
later = save(COMFY_AGAIN, '03800-a.png', None)
run([COMFY_AGAIN], level=PG)
before = stored(later)
save_comfy(COMFY_AGAIN, '03800-a.png', run_graph(seed=31, prompt='a %s harbour' % EXPLICIT))
image_sync.ImageSync([{'path': COMFY_AGAIN}], PG, True, force=True).run()
got = stored(later)
check('232. Read every image again on a ComfyUI file synced before with nothing: read in full, judged from its prompt',
      (before['prompt'], got['prompt'], got['meta'].get('Sampler'), seed_of(later), got['level']),
      (None, 'a %s harbour' % EXPLICIT, 'dpmpp_2m', 31, generated_level(got['meta'])))

# Read from (#232): where the data of an image without infotext came from -
# the file's own text, the workflow, the file name - and nothing on an image
# whose data is Forge's text, or that gave nothing.
READ_FROM = os.path.join(WORK, 'read-from')
text_only = save_prompts(READ_FROM, 'just-text.png', 'a text prompt')
name_only = save(READ_FROM, '04000-modely-40.png', None, at=600)
nothing = save(READ_FROM, 'plain-picture.png', None, at=1200)
opts.samples_filename_pattern = '[seed]-[model_name]-[steps]'
run([READ_FROM], level=PG)
CLIPPED = os.path.join(WORK, 'read-from-clip')
clipped = save_comfy(CLIPPED, '04010-2.png', run_graph(seed=58))
opts.samples_filename_pattern = '[seed]-[clip_skip]'
run([CLIPPED], level=PG)
opts.samples_filename_pattern = pattern_was
read_from = lambda path: (stored(path)['meta'] or {}).get('Read from')  # noqa: E731
check('232. Read from: a ComfyUI file whose name gives nothing: the workflow', read_from(png), 'workflow')
check('232. Read from: an Endless file: its prompts\' text, then the workflow', read_from(endless),
      'text in the file, workflow')
check('232. Read from: a ComfyUI file whose name gives a field no graph does: the workflow, then the file name',
      (read_from(clipped), stored(clipped)['meta'].get('Clip skip')), ('workflow, file name', '2'))
check('232. Read from: a name whose fields the graph gives too, its checkpoint included: the workflow alone',
      read_from(pair[0]), 'workflow')
check('232. Read from: a graph whose prompt cannot be reached: the workflow', read_from(no_prompt), 'workflow')
check('232. Read from: #408\'s prompts and its file name; its prompts alone',
      (read_from(spicy), read_from(text_only)), ('text in the file, file name', 'text in the file'))
check('232. Read from: an image with no text whose name gives fields: the file name', read_from(name_only), 'file name')
check('232. no Read from on an image that gave nothing, nor on one with Forge\'s text',
      (read_from(nothing), 'Read from' in (stored(saver)['meta'] or {})), (None, False))

print('image_sync: %d failure(s)' % len(fails))
for f in fails:
    print('FAIL ' + f)
sys.exit(1 if fails else 0)
