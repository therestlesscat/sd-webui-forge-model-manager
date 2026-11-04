"""
What a checkpoint picked in the Resources dialog is usually run with (#378):
`usual_settings.usual()` and its route, `GET /model-manager/send/usual`.

The user's own generations with the pick answer when 5 or more record
settings, while the Generations tab is on; else the stored Civitai images
naming its version, when 5 or more do. Each setting's most used value, with
its count out of the uses that record one, split by Send's own rule and
matched to this WebUI's lists; a fifth row, Distilled CFG Scale or Shift,
where the pick's UI preset takes one. Counted from the settings rows each
image and generation keeps (v48), through the indexes that find a
checkpoint's images, never another image's record.
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.forge_host as host                  # noqa: E402
import model_manager.identity_store as store             # noqa: E402
import model_manager.send as send                        # noqa: E402
import model_manager.send_plan as sp                     # noqa: E402
import model_manager.tabs as tabs                        # noqa: E402
import model_manager.api.common as common                # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'usual_settings')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# Looked up, not imported: on the code before #378 its checks fail, rather than the suite.
try:
    import model_manager.usual_settings as us
except ImportError:
    us = types.SimpleNamespace(usual=lambda *a: {}, most_used=lambda *a: None)


db, facts = fixtures.build(WORK)
dbmod._db_instance = db
raw = db._get_connection()
SD = facts['models_dir']
path_of = {os.path.basename(p): p for p in facts['linked_paths']}
A = path_of['model_1003_v0.safetensors']             # version 2005
B = path_of['model_1004_v0.safetensors']             # version 2006
C = path_of['model_1005_v0.safetensors']             # version 2007
D = path_of['model_1006_v0.safetensors']             # version 2008
F = path_of['model_1002_v0.safetensors']             # version 2003: Flux
G = path_of['model_1002_v1.safetensors']             # version 2004: Z-Image
X = path_of['model_1001_v0.safetensors']             # version 2001: SDXL
H = path_of['model_1001_v1.safetensors']             # version 2002: Flux, from Civitai
# A second file of D's version, in a folder only the other WebUI is given,
# spelt in the library in a case of its own; a file Civitai does not know;
# another file of A's version.
D2 = os.path.join(facts['directory'], 'Other', 'Models', 'Stable-diffusion', 'Model_1006_FP16.safetensors')
E = os.path.join(SD, 'Stable-diffusion', 'merged_at_home.safetensors')
A2 = os.path.join(SD, 'Stable-diffusion', 'model_1003_v0_fp16.safetensors')
# A file no sync has read: no architecture.
E2 = os.path.join(SD, 'Stable-diffusion', 'just_copied_in.safetensors')
raw.executemany("INSERT INTO files (file_path, file_name, version_id) VALUES (?, ?, ?)",
                [(D2, os.path.basename(D2), 2008), (E, os.path.basename(E), None), (A2, os.path.basename(A2), 2005),
                 (E2, os.path.basename(E2), None)])
raw.execute("UPDATE files SET file_type = 'Checkpoint'")
raw.commit()

PICKS = {'ck_a': A, 'ck_a2': A2, 'ck_b': B, 'ck_c': C, 'ck_d': D.upper(), 'ck_e': E, 'ck_f': F, 'ck_g': G,
         'ck_x': X, 'ck_h': H, 'ck_e2': E2}
host.checkpoint_file = lambda name: PICKS.get(name)
host.checkpoint_name = lambda path: next((n for n, p in PICKS.items() if p.lower() == str(path).lower()), None)
sp._ask_civitai = lambda kind, value: None                 # a suite asks Civitai nothing
store.needs_check = lambda db_, path: None                 # read already, as stored
# An ask reads no file: a file's header read would show here.
files_read = []
real_record_architecture = sp.record_architecture
sp.record_architecture = lambda db_, path, *a, **k: files_read.append(path)
PRESETS = {A: 'sd', B: None, C: 'sd', D: 'sd', E: 'sd', F: 'flux', G: 'zit', X: 'xl', H: 'flux'}
for path, preset in PRESETS.items():
    if preset:
        db.set_architecture(path, preset, 'Model', False, False, '1234', file_type='Checkpoint')

SAMPLERS = [('Euler', ['k_euler', 'euler']), ('Euler a', ['k_euler_a', 'euler_ancestral']),
            ('DPM++ 2M', ['k_dpmpp_2m', 'dpmpp_2m'])]
SCHEDULERS = [('Karras', ['karras']), ('Simple', ['simple']), ('SGM Uniform', ['sgm_uniform'])]
send.forge_lists = lambda: (SAMPLERS, SCHEDULERS)

# Neo's presets module, as forge_host_test stands it in.
presets = types.ModuleType('modules_forge.presets')
presets.use_distill = lambda arch: arch in ('flux',)
presets.use_shift = lambda arch: arch in ('xl', 'lumina', 'zit', 'wan', 'anima', 'ernie', 'pid', 'krea')
sys.modules['modules_forge.presets'] = presets
host.is_neo = lambda: True

generations_on = [True]
real_on = tabs.on
tabs.on = lambda area: generations_on[0] if area == 'generations' else real_on(area)

# The image sent: a Civitai image whose checkpoint is of another model, which
# the library lacks.
OTHER_MODEL = {'kind': 'civitai', 'image': 7001, 'version_ids': '2999', 'image_model': 999}
db.store_images(2999, page=1, images=[{
    'id': 7001, 'url': 'https://example.invalid/7001.jpeg', 'nsfwLevel': 1, 'modelVersionIds': [2999],
    'meta': {'prompt': 'the image sent', 'sampler': 'Euler a', 'Schedule type': 'Simple', 'steps': 28,
             'cfgScale': 4.5, 'Denoising strength': 0.4, 'Hires upscale': 1.5,
             'civitaiResources': [{'type': 'checkpoint', 'modelVersionId': 2999}]}}])

made = [0]


def line(sampler=None, schedule=None, steps=None, cfg=None, more=''):
    fields = [('Steps', steps), ('Sampler', sampler), ('Schedule type', schedule), ('CFG scale', cfg)]
    return 'a prompt\nNegative prompt: bad\n' + ', '.join(
        ['%s: %s' % (k, v) for k, v in fields if v is not None] + ['Seed: 1', 'Size: 512x512'] +
        ([more] if more else []))


def generation(checkpoint, text, images=1, own=None, meta=None, **paths):
    """A generation as the recorder hands it to the writer: `own` its own
    text where it differs from its images', `paths` its Hires fix checkpoint
    or refiner."""
    made[0] += 1
    g = {'created_at': '2026-01-01T00:%02d:%02d' % divmod(made[0], 60), 'mode': 'txt2img', 'image_count': images,
         'checkpoint_path': checkpoint, 'infotext': text if own is None else own, **paths}
    rows = [{'position': n, 'path': os.path.join(WORK, 'out', '%d-%d.png' % (made[0], n)), 'meta': meta or {},
             'prompt_nsfw_level': 1, **({'infotext': text} if text is not None else {})} for n in range(images)]
    return g, rows, [[] for _ in rows]


def record(*made_):
    return db.record_generations(list(made_))


def civitai(version, metas, first_id, gallery=None):
    """Civitai images naming `version` as their checkpoint, stored in its gallery."""
    db.store_images(gallery or version, page=1, images=[{
        'id': first_id + n, 'url': 'https://example.invalid/%d.jpeg' % (first_id + n), 'nsfwLevel': 1,
        'modelVersionIds': [version],
        'meta': {'prompt': 'a stored image', **meta,
                 'civitaiResources': meta.get('civitaiResources') or [{'type': 'checkpoint', 'modelVersionId': version}]}}
        for n, meta in enumerate(metas)])


def usual(name, source=None):
    return us.usual(db, name, source or OTHER_MODEL)


def row(answer, key):
    """One setting of an answer; {} where it has none, so a break fails a check rather than the suite."""
    return next((r for r in answer.get('settings') or [] if r.get('key') == key), {})


def top(answer, key):
    r = row(answer, key)
    return (r.get('value'), r.get('count'), r.get('of'))


# ------------------------------------------------ 1. each setting's most used
ids_a = record(generation(A, line('DPM++ 2M', 'Karras', 20, 7), images=4),
               generation(A, line('DPM++ 2M', 'Karras', 20, '7.0')),
               generation(A, line('DPM++ 2M', None, 30, 7)),
               generation(A, line('Euler a', 'Karras', 20, 5)),
               generation(A, line('Euler a', None, 30, 5)),
               generation(A, line('DPM++ 2M', 'Karras', 0, 0)))
a = usual('ck_a')
check('1. six generations, one a batch of four: the source is yours, each counted once',
      (a.get('applies'), a.get('source'), a.get('uses')), (True, 'yours', 6))
check('   the sampler most used, with its count of those recording one', top(a, 'sampler'), ('DPM++ 2M', 4, 6))
check('   steps and CFG by their most used value, not a median', (top(a, 'steps'), top(a, 'cfg')),
      ((20, 3, 5), (7, 3, 5)))
first_batch = db.get_generation(ids_a[0])
db.delete_generation_image(first_batch['images'][-1]['id'])
check('   one of the batch\'s images deleted: the same answer', top(usual('ck_a'), 'sampler'), ('DPM++ 2M', 4, 6))

# ---------------------------------------------------- 3. what counts, and how
check('3. a generation with no schedule type counts in the sampler\'s row alone; under 5 is thin',
      (top(a, 'schedule_type'), row(a, 'schedule_type').get('thin'), row(a, 'sampler').get('thin')),
      (('Karras', 4, 4), True, False))
check('   CFG 7 and 7.0 one value, shown 7', (row(a, 'cfg').get('value'), type(row(a, 'cfg').get('value'))), (7, int))
check('   a steps or CFG of 0 is not recorded: of 5, not 6', (row(a, 'steps').get('of'), row(a, 'cfg').get('of')),
      (5, 5))
check('   an SD 1.x pick: the four, no fifth', ([r.get('key') for r in a.get('settings') or []], a.get('extra')),
      (['sampler', 'schedule_type', 'steps', 'cfg'], None))
check('   the image\'s own values beside, by the same readings, and that it had Hires fix',
      a.get('image'), {'sampler': 'Euler a', 'schedule_type': 'Simple', 'steps': 28, 'cfg': 4.5,
                       'distilled_cfg': None, 'shift': None, 'hires': True})

# ------------------------------------------------------- 2. which source
EULER = line('Euler', 'Simple', 25, 4)
record(generation(B, EULER), generation(B, EULER),
       # Recording none of the settings counted: no use of them.
       generation(B, line(more='Clip skip: 2')),
       # By what Sync images read from its file name, with no text at all.
       generation(B, None, meta={'Sampler': 'Euler', 'Steps': '25', 'CFG scale': '4'}),
       # Its own text empty, its image's not.
       generation(B, EULER, own=''))
civitai(2006, [{'sampler': 'DPM++ 2M Karras', 'steps': 30, 'cfgScale': 6}] * 30, 8001)
b = usual('ck_b')
check('2. 4 of your generations and 30 Civitai images: Civitai answers, and says so',
      (b.get('source'), b.get('uses'), top(b, 'sampler'), top(b, 'cfg')), ('civitai', 30, ('DPM++ 2M', 30, 30), (6, 30, 30)))
record(generation(B, EULER))
b = usual('ck_b')
check('   at 5, yours answer - one by its file name, one by its image\'s text among them',
      (b.get('source'), b.get('uses'), top(b, 'sampler'), top(b, 'steps'), top(b, 'cfg')),
      ('yours', 5, ('Euler', 5, 5), (25, 5, 5), (4, 5, 5)))
generations_on[0] = False
check('   the Generations tab off: Civitai answers, whatever yours hold', usual('ck_b').get('source'), 'civitai')
generations_on[0] = True

# ------------------------------------------- 4. Send's split, and 7. missing
def civitai_round(metas, first_id):
    db.clear_version_images(2007)
    civitai(2007, metas, first_id)
    c = usual('ck_c')
    return top(c, 'sampler')[0], top(c, 'schedule_type')[0], row(c, 'sampler').get('missing'), \
        row(c, 'schedule_type').get('missing')


check('4. DPM++ 2M Karras with no schedule type: DPM++ 2M and Karras',
      civitai_round([{'sampler': 'DPM++ 2M Karras'}] * 5, 9101), ('DPM++ 2M', 'Karras', False, False))
check('   Euler a_simple: Euler a and Simple', civitai_round([{'sampler': 'Euler a_simple'}] * 5, 9111),
      ('Euler a', 'Simple', False, False))
check('   Undefined: Euler, as both WebUIs paste it', civitai_round([{'sampler': 'Undefined'}] * 5, 9121),
      ('Euler', None, False, False))
check('   ComfyUI\'s lowercase scheduler: by its name in Forge\'s list',
      civitai_round([{'sampler': 'euler', 'scheduler': 'karras'}] * 5, 9131), ('Euler', 'Karras', False, False))
check('   Schedule type Automatic: kept, and never missing',
      civitai_round([{'sampler': 'Euler', 'Schedule type': 'Automatic'}] * 5, 9141),
      ('Euler', 'Automatic', False, False))
check('   ComfyUI\'s lowercase scheduler this WebUI lists none of: by its name, missing - never dropped',
      civitai_round([{'sampler': 'euler', 'scheduler': 'bong_tangent'}] * 3 + [{'sampler': 'euler', 'scheduler': 'karras'}] * 2,
                    9135), ('Euler', 'bong_tangent', False, True))
check('7. a sampler and a schedule type this WebUI does not list: missing',
      civitai_round([{'sampler': 'Heun Plus', 'Schedule type': 'Bong Tangent'}] * 5, 9151),
      ('Heun Plus', 'Bong Tangent', True, True))

# ------------------------------------------------- 6. a tie, the newest wins
check('6. a tie goes to the newest use, in either order',
      [(us.most_used(rows) or {}).get('value') for rows in
       ([('Euler', 3, 10), ('DPM++ 2M', 3, 20)], [('DPM++ 2M', 3, 20), ('Euler', 3, 10)])], ['DPM++ 2M', 'DPM++ 2M'])
check('   through the database, asked twice',
      [civitai_round([{'sampler': 'Euler'}] * 3 + [{'sampler': 'DPM++ 2M'}] * 3, 9161)[0],
       civitai_round([{'sampler': 'DPM++ 2M'}] * 3 + [{'sampler': 'Euler'}] * 3, 9171)[0],
       civitai_round([{'sampler': 'DPM++ 2M'}] * 3 + [{'sampler': 'Euler'}] * 3, 9171)[0]],
      ['DPM++ 2M', 'Euler', 'Euler'])
check('   by each value\'s newest use, its uses in among the other\'s',
      civitai_round([{'sampler': s} for s in ('Euler', 'Euler', 'DPM++ 2M', 'DPM++ 2M', 'DPM++ 2M', 'Euler')], 9175)[0],
      'Euler')
record(*[generation(E2, line(s, 'Simple', 10, 2)) for s in ('Euler', 'Euler', 'DPM++ 2M', 'DPM++ 2M', 'DPM++ 2M', 'Euler')])
check('   and so for your generations', top(usual('ck_e2'), 'sampler'), ('Euler', 3, 6))

# ------------------------------------------- 5. which files and roles count
record(*[generation(D, line('Euler a', 'Karras', 24, 6)) for _ in range(3)],
       *[generation(D2, line('Euler a', 'Karras', 24, 6)) for _ in range(2)],
       generation(X, line('DPM++ 2M', 'Simple', 40, 3), hr_checkpoint_path=D),
       generation(X, line('DPM++ 2M', 'Simple', 40, 3), refiner_path=D))
d = usual('ck_d')
check('5. every file of the version counts, the other WebUI\'s in its own spelling, the pick in another case',
      (d.get('source'), d.get('uses'), top(d, 'sampler')), ('yours', 5, ('Euler a', 5, 5)))
check('   a generation using it as its Hires fix or refiner checkpoint does not', top(d, 'steps'), (24, 5, 5))
record(*[generation(E, line('Euler', 'Simple', 12, 2)) for _ in range(5)])
check('   a file Civitai does not know counts by its path', (usual('ck_e').get('source'), top(usual('ck_e'), 'steps')),
      ('yours', (12, 5, 5)))
# An image naming two checkpoints counts for each: version 2006's gallery, naming 2007 too.
db.clear_version_images(2007)
civitai(2007, [{'sampler': 'Euler'}] * 5, 9181)
civitai(2006, [{'sampler': 'Euler', 'civitaiResources': [{'type': 'checkpoint', 'modelVersionId': 2006},
                                                          {'type': 'checkpoint', 'modelVersionId': 2007}]},
                     # Listing one version twice, as two entries of a record can.
                     {'sampler': 'Euler', 'civitaiResources': [{'type': 'checkpoint', 'modelVersionId': 2007},
                                                               {'type': 'checkpoint', 'modelVersionId': 2007}]}], 9191)
generations_on[0] = False
check('   an image naming two checkpoints counts for each; one naming a version twice, once',
      (usual('ck_c').get('uses'), usual('ck_b').get('uses')), (7, 31))
generations_on[0] = True

# --------------------------------------------------- 8. when it applies
check('8. the image\'s own version, named alone: own, nothing else read',
      usual('ck_a', {'kind': 'civitai', 'image': 7001, 'version_ids': '2005'}), {'applies': False, 'kind': 'own'})
check('   another file of it picked - "Same version, other file" in the list: own to Send too',
      usual('ck_a2', {'kind': 'civitai', 'image': 7001, 'version_ids': '2005'}).get('applies'), False)
check('   a pick Forge no longer lists: none', usual('gone', OTHER_MODEL).get('applies'), False)
real_kind = send._source_pick_kind
kinds = {}
for kind in ('own', 'same', 'file', 'version', 'model'):
    send._source_pick_kind = lambda db_, source, kind=kind: kind
    kinds[kind] = usual('ck_a').get('applies')
send._source_pick_kind = real_kind
check('   false for own and same, true for the rest', kinds,
      {'own': False, 'same': False, 'file': True, 'version': True, 'model': True})
gen_source = {'kind': 'generation', 'generation': ids_a[1], 'image_model': 999}
check('   a generation of yours sent with another version\'s checkpoint: applies, its own values beside',
      (usual('ck_b', gen_source).get('applies'), usual('ck_b', gen_source).get('image')),
      (True, {'sampler': 'DPM++ 2M', 'schedule_type': 'Karras', 'steps': 20, 'cfg': 7, 'distilled_cfg': None,
              'shift': None, 'hires': False}))

# ---------------------------------------- 30, 35, 36. the fifth setting
record(*[generation(F, line('Euler', 'Simple', 20, 1, 'Distilled CFG Scale: 3.5')) for _ in range(5)],
       *[generation(G, line('Euler', 'Simple', 8, 1, 'Shift: 9')) for _ in range(5)])
f, g = usual('ck_f'), usual('ck_g')
check('30. a Flux pick: a Distilled CFG Scale row from the uses that record it',
      (f.get('extra'), [r.get('key') for r in f.get('settings') or []][4:], top(f, 'distilled_cfg')),
      ('distilled', ['distilled_cfg'], (3.5, 5, 5)))
check('    a Z-Image pick: a Shift row', (g.get('extra'), top(g, 'shift')), ('shift', (9, 5, 5)))
host.is_neo = lambda: False
check('    in the original Forge: a Z-Image pick none, a Flux pick its Distilled CFG Scale',
      (usual('ck_g').get('extra'), len(usual('ck_g').get('settings') or []), usual('ck_f').get('extra')),
      (None, 4, 'distilled'))
host.is_neo = lambda: True

record(*[generation(X, line('DPM++ 2M', 'Karras', 30, 6)) for _ in range(4)])
x = usual('ck_x')
check('35. an SDXL pick whose uses record no Shift: no fifth row',
      (x.get('source'), x.get('extra'), len(x.get('settings') or [])), ('yours', None, 4))
record(*[generation(X, line('Euler', 'Simple', 30, 1, 'Shift: 3')) for _ in range(4)])
check('    4 recording one: still none', usual('ck_x').get('extra'), None)
record(generation(X, line('Euler', 'Simple', 30, 1, 'Shift: 3')))
check('    5: a Shift row, of the 5', (usual('ck_x').get('extra'), top(usual('ck_x'), 'shift')), ('shift', (3, 5, 5)))

civitai(2002, [{'sampler': 'Euler', 'cfgScale': 3.5}] * 3 + [{'sampler': 'Euler', 'cfgScale': 2.5,
                                                               'Distilled CFG Scale': 4}] * 2, 9201)
h = usual('ck_h')
check('36. a Flux pick from Civitai: a record\'s cfgScale is its Distilled CFG Scale, with CFG 1, where it gives none',
      (h.get('source'), top(h, 'distilled_cfg'), top(h, 'cfg')), ('civitai', (3.5, 3, 5), (1, 3, 5)))
check('    one that gives a Distilled CFG Scale is read as it is, its CFG too',
      (top(h, 'distilled_cfg')[:2], top(h, 'cfg')[:2]), ((3.5, 3), (1, 3)))
generations_on[0] = False
check('    a pick of another family is not touched', top(usual('ck_b'), 'cfg'), (6, 30, 30))
generations_on[0] = True

# ----------------------------------------------------- nothing to go by
raw.execute("DELETE FROM generation_params WHERE generation_id IN (%s)" % ', '.join(map(str, ids_a)))
raw.commit()
empty = usual('ck_a')
check('under 5 uses from either source: no source, every setting thin, the image\'s still read',
      (empty.get('applies'), empty.get('source'), empty.get('uses'), [r.get('thin') for r in empty.get('settings') or []],
       (empty.get('image') or {}).get('steps')), (True, None, 0, [True] * 4, 28))

# ---------------------------------------- 26. answered from the index
# With no statistics, SQLite takes `role = 'checkpoint'` as the way into
# generations' rows once two paths are asked - D's version has two files -
# and walks every checkpoint row of the library.
def plan_of(name, word, args):
    statements = []
    raw.set_trace_callback(statements.append)
    us.usual(db, name, OTHER_MODEL)
    raw.set_trace_callback(None)
    sql = next((s for s in statements if word in s and 'GROUP BY' in s), None)
    if sql is None:
        return []
    return [r[3] for r in raw.execute('EXPLAIN QUERY PLAN ' + sql, args if '?' in sql else ())]


civitai_plan = plan_of('ck_c', 'image_params', (2007,))
yours_plan = plan_of('ck_d', 'generation_params', db.generation_gallery_files(D))
check('    (two files asked for yours)', len(db.generation_gallery_files(D)), 2)
check('26. Civitai\'s read: the version\'s rows from its index alone, each settings row by its key',
      (any('COVERING INDEX idx_image_resources_version' in s for s in civitai_plan),
       any('INTEGER PRIMARY KEY' in s for s in civitai_plan)), (True, True))
check('    yours: the paths\' rows from their index alone, the role read from it',
      any('COVERING INDEX idx_resources_path' in s for s in yours_plan), True)

# --------------------------- 27. no record or text but the source's own
asked = {'records': [], 'generations': []}
real_records, real_generation = db.stored_records, db.get_generation
inside = [False]


def records(ids):
    asked['records'].append(list(ids))
    inside[0] = True
    try:
        return real_records(ids)
    finally:
        inside[0] = False


def get_generation(generation_id):
    asked['generations'].append(generation_id)
    inside[0] = True
    try:
        return real_generation(generation_id)
    finally:
        inside[0] = False


db.stored_records, db.get_generation = records, get_generation
outside = []
raw.set_trace_callback(lambda s: outside.append(s) if not inside[0] and any(
    t in s for t in ('image_records', 'generation_details', 'generation_image_details')) else None)
us.usual(db, 'ck_h', OTHER_MODEL)
us.usual(db, 'ck_d', {'kind': 'generation', 'generation': ids_a[1], 'image_model': 999})
raw.set_trace_callback(None)
db.stored_records, db.get_generation = real_records, real_generation
check('27. a pick reads the settings rows, and only the source\'s own record or generation',
      (asked['records'], sorted(set(asked['generations'])), outside), ([[7001]], [ids_a[1]], []))

# ------------------------------------- the image's own, and no file read
W = record(generation(X, line('DPM++ 2M', 'Karras', 22, 6), own=line('Euler', 'Simple', 11, 3)))[0]
whole = {'kind': 'generation', 'generation': W, 'image_model': 999}
check('the Model Manager\'s card sends the generation\'s own text: its values are the image\'s',
      [(usual('ck_b', {**whole, 'whole': w}).get('image') or {}).get('steps') for w in (True, False)], [11, 22])
# The pick's own file. (Telling the pick's kind reads, as Send's plan does,
# a file of the image's own version no sync has read - not this image's.)
files_read.clear()
check('the pick\'s file is not read, one no sync has read included: no fifth row, never a header read',
      (usual('ck_e2').get('extra'), files_read), (None, []))

# -------------------------------------------------------- 9. the route
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))
params = {'checkpoint': 'ck_d', 'kind': 'civitai', 'image': 7001, 'version_ids': '2999', 'image_model': 999}
answer = client.get('/model-manager/send/usual', params=params)
body = answer.json() if answer.status_code == 200 else {}
check('9. the route answers as the function does', (body.pop('success', None), body),
      (True, us.usual(db, 'ck_d', {**OTHER_MODEL, 'hashes': '', 'generation': 0, 'whole': False})))
real_gate_on = common.on
common.on = lambda area: area != 'send'
check('   refused with Send\'s tabs off', client.get('/model-manager/send/usual', params=params).status_code, 403)
common.on = real_gate_on
generations_on[0] = False
check('   a generation\'s refused while the Generations tab is off, as send/plan refuses it',
      client.get('/model-manager/send/usual', params={'checkpoint': 'ck_b', 'kind': 'generation',
                                                       'generation': ids_a[1]}).status_code, 403)
generations_on[0] = True

# ----------------------------------------- Send, with the tick (#378, 0.75.3)
# D's usual settings come from 5 of your generations: Euler a, Karras, 24
# steps, CFG 6. The image sent has Euler a, Simple, 28 and 4.5.
def line_of(found):
    return ((found or {}).get('text') or '').split('\n')[-1] if isinstance(found, dict) else str(found)


def sent(name, usual_on, **source):
    """Send's settings as its callers ask them: the ticked usual ones first (usual_settings.chosen)."""
    source = {**OTHER_MODEL, 'use_checkpoint': name, **({'usual': True} if usual_on else {}), **source}
    try:
        # Without the tick, as Send was called before #378's.
        return send.settings(db, source, False, getattr(us, 'chosen', lambda *a: None)(db, source)) if usual_on \
            else send.settings(db, source)
    except Exception as e:                               # noqa: BLE001 - a break fails a check, not the suite
        return 'raised %s' % type(e).__name__


def picked(line, *keys):
    return [f for f in line.split(', ') if f.split(': ')[0] in keys]


SETTINGS4 = ('Steps', 'Sampler', 'Schedule type', 'CFG scale')
check('10. Send with the tick: the usual four in the paste, worked out again at the Send',
      picked(line_of(sent('ck_d', True)), *SETTINGS4),
      ['Steps: 24', 'Sampler: Euler a', 'Schedule type: Karras', 'CFG scale: 6'])
check('    without it, the image\'s', picked(line_of(sent('ck_d', False)), *SETTINGS4),
      ['Steps: 28', 'Sampler: Euler a', 'Schedule type: Simple', 'CFG scale: 4.5'])
check('14. a pick with nothing to go by, ticked: the image\'s', line_of(sent('ck_a', True)), line_of(sent('ck_a', False)))
check('    an as-made pick, ticked: the image\'s',
      line_of(sent('ck_a', True, version_ids='2005')), line_of(sent('ck_a', False, version_ids='2005')))
text_params = {'kind': 'civitai', 'image': 7001, 'version_ids': '2999', 'image_model': 999, 'use_checkpoint': 'ck_d',
               'text': 1}
# The page writes a source's flag as `true` (fetchSendText).
routed = [client.get('/model-manager/send/plan', params={**text_params, **extra}).json()
          for extra in ({'usual': 'true'}, {'usual': '1'}, {})]
check('12. send/plan?text=1 with usual=true, as the page sends it: the usual text, for Forge\'s own paste button;'
      ' without, the image\'s', [picked(line_of(r), 'Steps') for r in routed], [['Steps: 24'], ['Steps: 24'], ['Steps: 28']])
check('19. its answer names what the text took, for the notice; nothing without the tick',
      [routed[0].get('usual'), 'usual_text' in routed[0], 'usual' in routed[2]],
      [{'sampler': 'Euler a', 'schedule_type': 'Karras', 'steps': 24, 'cfg': 6}, False, False])
# A generation whose text has no settings line takes none of them: the text
# route, which only pastes, names none.
LINELESS = record(generation(X, 'a prompt alone\nSteps: 20'))[0]
lineless = client.get('/model-manager/send/plan', params={'kind': 'generation', 'generation': LINELESS, 'text': 1,
                                                          'use_checkpoint': 'ck_d', 'image_model': 999, 'usual': 'true'}).json()
check('    a generation with no settings line, through the text route: its text, nothing named as applied',
      [lineless.get('text'), 'usual' in lineless], ['a prompt alone\nSteps: 20', False])
real_kind = send._source_pick_kind
send._source_pick_kind = lambda db_, source: 'same'
check('14. a same pick - the image\'s file under another model - ticked: nothing applied',
      getattr(us, 'chosen', lambda *a: 'missing')(db, {**OTHER_MODEL, 'use_checkpoint': 'ck_d', 'usual': True}), None)
send._source_pick_kind = real_kind

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
