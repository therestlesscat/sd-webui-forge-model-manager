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
import os
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
import model_manager.architecture as arch                # noqa: E402
import model_manager.send_plan as sp                     # noqa: E402

WORK = os.path.join(TESTS, 'work', 'send_plan')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
arch.needs_check = lambda db_, p: None          # every file below is as stored
paths = facts['linked_paths']


def is_(path, file_type, preset, cls=None, hashes=None):
    db.set_architecture(path, preset, cls, False, False, '1', file_type=file_type)
    if hashes is not None:
        with db._cursor() as cursor:
            cursor.execute("UPDATE model_versions SET file_hashes = ? WHERE file_path = ?",
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

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
