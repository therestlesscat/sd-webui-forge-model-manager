"""
Which model Send to txt2img sets Forge up for.

Not always the gallery's: a LoRA's or a VAE's gallery holds images made with
some checkpoint, and "Qwen-Image - GGUF" on Civitai is a VAE and a text
encoder filed as a Checkpoint. Its gallery's images were made with Anima
checkpoints this library does not have, and the send used to fall back to
the VAE's baseModel, "Other", and set nothing up - the text encoder was
never selected. The order: the gallery's checkpoint, the image's installed
checkpoint, the gallery file's own model, the image's checkpoint on Civitai,
the gallery's baseModel. Each is checked here on its own.
"""
import gzip
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

import fixtures                                          # noqa: E402
import model_manager.identity_store as store             # noqa: E402
import model_manager.send_plan as sp                     # noqa: E402

WORK = os.path.join(TESTS, 'work', 'send_plan')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
store.needs_check = lambda db_, p: None         # every file below is as stored
paths = facts['linked_paths']


def is_(path, file_type, preset, cls=None, hashes=None):
    db.set_architecture(path, preset, cls, False, False, '1', file_type=file_type)
    if hashes is not None:
        with db._cursor() as cursor:
            cursor.execute("UPDATE files SET file_hashes = ? WHERE file_path = ?",
                           (__import__('json').dumps(hashes), path))


def version_id(path):
    return db.get_version(path)['id']


asked = []
CIVITAI = {('v', '9001'): {'baseModel': 'Other', 'files': [{'name': 'clip_l.safetensors'}]},
           ('v', '9002'): {'baseModel': 'Anima', 'files': [{'name': 'anima-preview2.safetensors'}]},
           ('v', '9003'): {'baseModel': 'Flux.1 D', 'files': [{'name': 'other.safetensors'}]},
           ('h', 'abc123def456'): {'baseModel': 'Qwen', 'files': [{'name': 'q.safetensors'}]}}


def civitai(kind, value):
    asked.append((kind, value))
    return CIVITAI.get((kind, value))


def plan(**kw):
    sp._remembered.clear()
    asked.clear()
    found = sp.plan_model(db, lookup=civitai, **kw)
    return found.preset, found.source


gallery_ckpt, vae, lora, image_ckpt, other_ckpt = paths[0], paths[1], paths[2], paths[3], paths[5]
is_(gallery_ckpt, 'Checkpoint', 'xl', 'SDXL')
is_(vae, 'VAE', None)
is_(lora, 'LORA', 'anima')
is_(image_ckpt, 'Checkpoint', 'flux', 'Flux', hashes={'autov2': 'AAAA111122', 'autov3': 'bbbb2222cccc'})
is_(other_ckpt, 'Checkpoint', 'zit', 'ZImage')

check('1. a checkpoint\'s gallery: that checkpoint, which the send loads',
      plan(file_path=gallery_ckpt, version_ids=[version_id(image_ckpt)]), ('xl', 'file'))
check('2. any other gallery: the image\'s checkpoint, when installed - by version id',
      plan(file_path=vae, version_ids=[version_id(image_ckpt)]), ('flux', 'image'))
check('   or by any hash stored for the file, AutoV3 included',
      plan(file_path=vae, hashes=['BBBB2222CCCC']), ('flux', 'image'))
check('   a hash names one file, and beats the version ids an image lists',
      plan(file_path=vae, version_ids=[version_id(other_ckpt)], hashes=['aaaa111122']),
      ('flux', 'image'))
check('   a "checkpoint" the image names that is really a VAE is passed over',
      plan(file_path=lora, version_ids=[version_id(vae)]), ('anima', 'gallery'))
check('3. no installed checkpoint: the gallery file\'s own model - an Anima LoRA',
      plan(file_path=lora, version_ids=[9002]), ('anima', 'gallery'))
check('   and Civitai is not asked', asked, [])

check('4. a VAE\'s gallery, its image\'s checkpoint not installed: asked of Civitai',
      plan(file_path=vae, base_model='Other', version_ids=[9001, 9002], model_name='anima-preview2'),
      ('anima', 'image_civitai'))
check('   its encoder and VAE filed as checkpoints say "Other", and are passed over',
      asked, [('v', '9001'), ('v', '9002')])
check('   of two that say something, the one named as the image\'s model wins',
      plan(file_path=vae, version_ids=[9003, 9002], model_name='anima-preview2.safetensors')[0], 'anima')
check('   else the first', plan(file_path=vae, version_ids=[9003, 9002])[0], 'flux')
check('   a hash is asked about too', plan(file_path=vae, hashes=['abc123def456']), ('qwen', 'image_civitai'))
plan(file_path=vae, version_ids=[version_id(vae)], hashes=['aaaa111122'])
check('   a version or hash this library has is never asked about', asked, [])

sp._remembered.clear()
asked.clear()
sp.plan_model(db, file_path=vae, version_ids=[9002], lookup=civitai)
sp.plan_model(db, file_path=vae, version_ids=[9002], lookup=civitai)
check('   and an answer is remembered: one request, however many sends', asked, [('v', '9002')])

sp._remembered.clear()
def down(kind, value):
    raise OSError('no network')
check('5. nothing else: the gallery\'s own baseModel, as before',
      (sp.plan_model(db, file_path=vae, base_model='Flux.1 D', version_ids=[9002], lookup=down).preset,
       sp.plan_model(db, file_path=vae, base_model='Flux.1 D', version_ids=[9002], lookup=down).source),
      ('flux', 'civitai'))
check('   a failed request is not remembered as an answer', ('v', '9002') in sp._remembered, False)
check('   and with nothing at all, nothing', plan(file_path=vae, base_model='Other'), (None, None))


# Wan text-to-video and image-to-video. Forge's detector calls every Wan 2.2
# file WAN21_T2V - it tells I2V by img_emb, which only Wan 2.1 has - so an
# I2V file sent to txt2img failed in the sampler. The file's patch embedding
# says which: 16 input channels of noise, or 36 with the start frame's.
def video(**kw):
    sp._remembered.clear()
    return sp.plan_model(db, lookup=civitai, **kw).video


def patch_embedding(width):
    return {'model.diffusion_model.patch_embedding.weight': ((5120, width, 1, 2, 2), 'F16')}


widths = {}
sp.read_shapes = lambda p: patch_embedding(widths[p]) if p in widths else None
is_(gallery_ckpt, 'Checkpoint', 'wan', 'WAN21_T2V')
is_(image_ckpt, 'Checkpoint', 'wan', 'WAN21_T2V')

widths[gallery_ckpt] = 36
check('6. a Wan checkpoint with 36 input channels is image-to-video, whatever its class says',
      video(file_path=gallery_ckpt), 'i2v')
widths[gallery_ckpt] = 16
check('   16 is text-to-video', video(file_path=gallery_ckpt), 't2v')
widths[gallery_ckpt] = 48
check('   any other width is neither: Wan 2.2 5B, which Neo does not run',
      video(file_path=gallery_ckpt, base_model='Wan Video 2.2 T2V-A14B'), None)
widths[image_ckpt] = 36
check('   the image\'s installed checkpoint is read the same way',
      video(file_path=vae, version_ids=[version_id(image_ckpt)]), 'i2v')

del widths[gallery_ckpt]
check('   a file that cannot be read: its baseModel on Civitai',
      video(file_path=gallery_ckpt, base_model='Wan Video 2.2 I2V-A14B'), 'i2v')
check('   Wan 2.1\'s naming too', video(file_path=gallery_ckpt, base_model='Wan Video 14B t2v'), 't2v')
check('   TI2V is neither, not both', video(file_path=gallery_ckpt, base_model='Wan Video 2.2 TI2V-5B'), None)

is_(lora, 'LORA', 'wan')
check('7. a Wan LoRA\'s gallery: the LoRA\'s own baseModel',
      video(file_path=lora, base_model='Wan Video 2.2 T2V-A14B'), 't2v')
CIVITAI[('v', '9004')] = {'baseModel': 'Wan Video 2.2 I2V-A14B', 'files': [{'name': 'w.safetensors'}]}
check('   a checkpoint only Civitai knows: the baseModel Civitai gave it',
      video(file_path=vae, version_ids=[9004], base_model='Wan Video 2.2 T2V-A14B'), 'i2v')
check('8. anything not Wan is not video', video(file_path=other_ckpt), None)


# The checkpoint an image names, for a send from a gallery that is not a
# checkpoint's (#134): the plan found it and took only its preset, and Forge
# kept whatever it had loaded. The checkpoint is the one thing a send cannot
# do without: one the library lacks is said, not sent around.
def named(**kw):
    sp._remembered.clear()
    asked.clear()
    return sp.image_checkpoint(db, lookup=civitai, **kw)


is_(image_ckpt, 'Checkpoint', 'flux', 'Flux', hashes={'autov2': 'AAAA111122'})
is_(other_ckpt, 'Checkpoint', 'zit', 'ZImage')
check('9. the image\'s checkpoint, when the library has it',
      named(file_path=lora, version_ids=[version_id(image_ckpt)]), {'path': image_ckpt})
is_(other_ckpt, 'Checkpoint', 'flux', 'Flux', hashes={'autov2': 'AAAA111122'})
check('   of two copies, the one in this WebUI\'s folders',
      named(file_path=lora, hashes=['aaaa111122'], here=lambda p: p == other_ckpt), {'path': other_ckpt})
check('   and with neither there, still the first - for the page to say where it is',
      named(file_path=lora, hashes=['aaaa111122'], here=lambda p: False)['path'] in (image_ckpt, other_ckpt))
is_(other_ckpt, 'Checkpoint', 'zit', 'ZImage', hashes={})
check('   not one the library lacks, by the name the image gives it',
      named(file_path=lora, version_ids=[9002], model_name='anima-preview2'), {'missing': 'anima-preview2'})
check('   or the name Civitai gives its file',
      named(file_path=lora, version_ids=[9003]), {'missing': 'other.safetensors'})
check('   or, with no name anywhere, its hash', named(file_path=lora, hashes=['ffffeeee0000']),
      {'missing': 'ffffeeee0000'})
check('   what it names as checkpoints, all something else on Civitai, is no checkpoint',
      named(file_path=lora, version_ids=[9001]), {'not_checkpoint': True})
check('   as is a VAE of this library\'s filed as one - and Civitai is not asked',
      (named(file_path=lora, version_ids=[version_id(vae)]), asked), ({'not_checkpoint': True}, []))
check('   and an image that names none names none', named(file_path=lora), {})

# What else a version Civitai is asked about can answer (#377): until then a
# 404, a failed request and a family no UI preset runs all read "names no
# checkpoint", and the stop offered nothing.
CIVITAI[('v', '9005')] = {'baseModel': 'OpenAI', 'files': [{'name': 'o.safetensors'}]}
check('10. a version Civitai answers 404 for: missing, by the name the image\'s own resource entry gives it',
      named(file_path=lora, version_ids=[9404], names={9404: 'A Model - v1'}), {'missing': 'A Model - v1'})
check('    with no entry naming it, by its version', named(file_path=lora, version_ids=[9404]),
      {'missing': 'version 9404'})
sp._remembered.clear()
check('    asking Civitai fails: missing too, and asked again next time',
      (sp.image_checkpoint(db, file_path=lora, version_ids=[9406], lookup=down, names={9406: 'B - v2'}),
       ('v', '9406') in sp._remembered), ({'missing': 'B - v2'}, False))
check('    Civitai files it under a family no UI preset runs: unsupported, its base model named',
      named(file_path=lora, version_ids=[9005], names={9005: 'Image Gen - v1'}),
      {'unsupported': 'OpenAI', 'name': 'Image Gen - v1'})
check('    beside a VAE filed as a checkpoint ("Other"), the unsupported one still answers',
      named(file_path=lora, version_ids=[9001, 9005]), {'unsupported': 'OpenAI', 'name': ''})

# A checkpoint named by its hash alone (#441): one of a family no preset runs
# was said missing by the hash, with a Download offer.
CIVITAI[('h', 'abcd00000001')] = {'baseModel': 'Flux.2 D', 'files': [{'name': 'made-up.safetensors'}]}
CIVITAI[('h', 'abcd00000002')] = {'baseModel': 'Pony V7', 'files': []}
CIVITAI[('h', 'abcd00000005')] = {'baseModel': '', 'files': [{'name': 'b_vae.safetensors'}]}
CIVITAI[('h', 'abcd00000006')] = {'baseModel': 'SD 3.5', 'files': [{'name': 'a.safetensors'}, {'name': 'b.safetensors'}]}
CIVITAI[('h', 'abcd00000004')] = {'baseModel': 'Flux.1 D', 'files': []}
CIVITAI[('h', 'abcd00000003')] = {'baseModel': 'Other', 'files': [{'name': 'a_vae.safetensors'}]}
check('11. a hash of a family no preset runs: unsupported, by its file\'s name on Civitai, the case aside',
      named(file_path=lora, hashes=['ABCD00000001']), {'unsupported': 'Flux.2 D', 'name': 'made-up.safetensors'})
check('    with no file named there, its base model alone',
      named(file_path=lora, hashes=['abcd00000002']), {'unsupported': 'Pony V7', 'name': ''})
check('    asked once', asked, [('h', 'abcd00000002')])
check('    the second of two, the first not on Civitai',
      named(file_path=lora, hashes=['ffffeeee0000', 'abcd00000001']),
      {'unsupported': 'Flux.2 D', 'name': 'made-up.safetensors'})
check('    of two such, the first, by the first of its files',
      named(file_path=lora, hashes=['abcd00000006', 'abcd00000001']), {'unsupported': 'SD 3.5', 'name': 'a.safetensors'})
check('    beside a version of a family no preset runs, the hash\'s',
      named(file_path=lora, hashes=['abcd00000001'], version_ids=[9005]),
      {'unsupported': 'Flux.2 D', 'name': 'made-up.safetensors'})
check('    a hash filed "Other", or under nothing, names no family: the hash, as before',
      [named(file_path=lora, hashes=[h]) for h in ('abcd00000003', 'abcd00000005')],
      [{'missing': 'abcd00000003'}, {'missing': 'abcd00000005'}])
check('    beside a version a preset runs, that one, as before',
      named(file_path=lora, hashes=['abcd00000006'], version_ids=[9003]), {'missing': 'other.safetensors'})
check('    or beside a hash of one whose file Civitai does not name, the first hash, as before',
      named(file_path=lora, hashes=['abcd00000004', 'abcd00000001']), {'missing': 'abcd00000004'})
sp._remembered.clear()
sp._remembered[('h', 'abcd00000007')] = ('Flux.1 D', ['e.safetensors'])
check('    nor is one past the four asked, of a family a preset runs, said to have none',
      sp.image_checkpoint(db, file_path=lora, hashes=['e1', 'e2', 'e3', 'e4', 'abcd00000007'], lookup=civitai),
      {'missing': 'e1'})
is_(image_ckpt, 'Checkpoint', None, hashes={'autov2': 'DEAD000001'})
sp._remembered.clear()
sp._remembered[('h', 'dead000001')] = ('SD 3.5', ['held.safetensors'])
check('    one the library holds, its family not read: the hash, as before, whatever was asked earlier',
      sp.image_checkpoint(db, file_path=lora, hashes=['dead000001'], lookup=civitai), {'missing': 'dead000001'})
check('    as is one of a family a preset runs, whose file Civitai does not name',
      named(file_path=lora, hashes=['abcd00000004']), {'missing': 'abcd00000004'})
check('    and one Civitai does not know, beside a version of a family no preset runs',
      named(file_path=lora, hashes=['ffffeeee0000'], version_ids=[9005]), {'missing': 'ffffeeee0000'})
sp._remembered.clear()
tries = []
check('    one that could not be asked: the hash, and not asked twice',
      (sp.image_checkpoint(db, file_path=lora, hashes=['abcd00000001'],
                           lookup=lambda kind, value: (tries.append(value), down(kind, value))),
       tries), ({'missing': 'abcd00000001'}, ['abcd00000001']))
check('    and a name the image gives it comes first, as before',
      named(file_path=lora, hashes=['abcd00000001'], model_name='a-name'), {'missing': 'a-name'})
CIVITAI[('v', '9006')] = {'baseModel': 'Flux.2 D', 'files': [{'name': 'made-up.safetensors'}]}
CIVITAI[('v', '9007')] = {'baseModel': 'Wan Video 2.7', 'files': []}
check('    by a version id alone: the base model is named the same way',
      [named(file_path=lora, version_ids=[v]) for v in (9006, 9007)],
      [{'unsupported': 'Flux.2 D', 'name': ''}, {'unsupported': 'Wan Video 2.7', 'name': ''}])

# A checkpoint of the two newer families, read from a published file's header
# (#441): MOSS-Image's was of no type, and said missing after its download;
# Qwen-Image 2.1's was Qwen-Image's.
with gzip.open(os.path.join(TESTS, 'family_headers.json.gz'), 'rt', encoding='utf-8') as f:
    HEADERS = json.load(f)['files']
for key, (name, vid) in {'moss': ('moss_bf16', 441001), 'qwen21': ('q21_bf16', 441002)}.items():
    newer = os.path.join(facts['directory'], name + '.safetensors')
    header = json.dumps({n: {'dtype': 'BF16', 'shape': s, 'data_offsets': [0, 0]}
                         for n, s in HEADERS[name]['tensors'].items()}).encode()
    with open(newer, 'wb') as f:
        f.write(struct.pack('<Q', len(header)) + header)
    db.upsert_version({'file_path': newer, 'file_name': name + '.safetensors', 'id': vid, 'model_id': vid + 1000,
                       'has_civitai_data': True})
    store.record_architecture(db, newer, force=True)
    check('12. an image naming a %s checkpoint the library holds: that file' % key,
          named(file_path=lora, version_ids=[vid]), {'path': newer})
    check('    set up for its own family', plan(file_path=vae, version_ids=[vid]), (key, 'image'))
check('    and one only Civitai knows, by its base model',
      [plan(file_path=vae, base_model=b)[0] for b in ('Qwen 2.1', 'MOSS Image', 'Qwen')], ['qwen21', 'moss', 'qwen'])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
