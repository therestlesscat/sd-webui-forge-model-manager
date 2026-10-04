"""
Picking the text encoders and VAE a model needs, from what is installed.

An image's generation data never names a Flux model's CLIP-L and T5-XXL or a
Qwen-Image model's Qwen2.5-VL - they were loaded already. So each module
file is told apart by what it is: a text encoder by its token embedding
(vocabulary by width) and whether it has a vision tower, a VAE by its latent
channels or its Wan-style layout. A model's architecture says which kinds it
needs; what its file bundles is left out; the rest are picked, Forge's saved
choice for the preset first when it is the right kind.
"""
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

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.file_identity as fi                 # noqa: E402
import model_manager.forge_host as host                  # noqa: E402
import model_manager.forge_modules as fm                 # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'forge_modules')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def te(vocab, width, dtype='F16', vision=False, name='model.embed_tokens.weight'):
    shapes = {name: ((vocab, width), dtype), 'model.norm.weight': ((width,), dtype)}
    if vision:
        shapes['visual.blocks.0.attn.qkv.weight'] = ((3072, 1024), dtype)
    return shapes


def vae(channels=None, wan=False):
    if wan:
        return {'decoder.middle.0.residual.0.gamma': ((384, 1, 1, 1), 'F16')}
    return {'decoder.conv_in.weight': ((512, channels, 3, 3), 'F16'),
            'encoder.conv_in.weight': ((128, 3, 3, 3), 'F16')}


# ------------------------------------------------------------- telling apart
HF_T5 = {'encoder.block.0.layer.0.SelfAttention.k.weight': ((4096, 4096), 'F16')}
check('text encoders are told apart by their embedding',
      [fi.classify(s) for s in (
          te(49408, 768, name='text_model.embeddings.token_embedding.weight'),
          te(49408, 1280, name='text_model.embeddings.token_embedding.weight'),
          {**te(32128, 4096, name='shared.weight'), **HF_T5},
          {**te(256384, 4096, name='shared.weight'), **HF_T5},
          te(151936, 1024), te(151936, 2560), te(151936, 4096),
          te(152064, 3584, vision=True), te(256000, 2304), te(131072, 3072))],
      ['clip_l', 'clip_g', 't5xxl', 'umt5xxl', 'qwen3_06b', 'qwen3_4b', 'qwen3_8b',
       'qwen25_7b', 'gemma2_2b', 'ministral3_3b'])
# T5 and UMT5 only in the layout Forge's loader takes: Hugging Face's, which
# it finds by encoder.block...SelfAttention. The same UMT5-XXL saved in Wan's
# own layout has the right embedding and would never load, so it must count
# as missing rather than be picked.
HF_T5 = {'encoder.block.0.layer.0.SelfAttention.k.weight': ((4096, 4096), 'F16')}
check('UMT5-XXL in Hugging Face\'s layout is UMT5-XXL',
      fi.classify({**te(256384, 4096, name='shared.weight'), **HF_T5}), 'umt5xxl')
check('as is a quantized one',
      fi.classify({**te(32128, 4096, name='shared.weight'),
                   'encoder.block.0.layer.0.SelfAttention.k.qweight': ((4096, 512), 'I32')}), 't5xxl')
check('but the same encoder in Wan\'s own layout is not a module Forge can load',
      fi.classify({'token_embedding.weight': ((256384, 4096), 'BF16'),
                   'blocks.0.attn.k.weight': ((4096, 4096), 'BF16'),
                   'blocks.0.ffn.gate.0.weight': ((10240, 4096), 'BF16')}), None)
check('and by a vision tower: Qwen3-VL is not Qwen3',
      fi.classify(te(151936, 2560, vision=True)), 'qwen3vl_4b')
check('VAEs by their latent channels, or the Wan-style layout',
      [fi.classify(vae(4)), fi.classify(vae(16)), fi.classify(vae(32)), fi.classify(vae(wan=True))],
      ['vae_sd', 'vae_ae', 'vae_flux2', 'vae_wan21'])
check('a whole checkpoint in the VAE folder is not a module',
      fi.classify({'model.diffusion_model.x': ((1,), 'F16'),
                   'first_stage_model.decoder.conv_in.weight': ((512, 4, 3, 3), 'F16')}), None)
check('nor is anything else', fi.classify({'emb_params': ((8, 768), 'F16')}), None)

# ------------------------------------------------------------------- picking
MODULES = {
    'clip_l.safetensors': ('clip_l', 2),
    't5xxl_fp8.safetensors': ('t5xxl', 1),
    't5xxl_fp16.safetensors': ('t5xxl', 2),
    'ae.safetensors': ('vae_ae', 2),
    'qwen_image_vae.safetensors': ('vae_wan21', 2),
    'wan_2.1_vae.safetensors': ('vae_wan21', 2),
    'sdxl_vae.safetensors': ('vae_sd', 2),
}
got = fm.pick('Flux', 'flux', False, False, MODULES, [])
check('a Flux diffusion model alone needs CLIP-L, T5-XXL and the Flux VAE',
      (got['needed'], got['select'], got['missing']),
      (['clip_l', 't5xxl', 'vae_ae'],
       ['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae.safetensors'], []))
check('the finer weights win: fp16 over fp8', 't5xxl_fp16.safetensors' in got['select'])
check('but Forge\'s saved choice for the preset wins over that',
      fm.pick('Flux', 'flux', False, False, MODULES, ['t5xxl_fp8.safetensors'])['select'][1],
      't5xxl_fp8.safetensors')
check('a saved choice of the wrong kind is not kept - it is simply not picked',
      fm.pick('Flux', 'flux', False, False, MODULES, ['sdxl_vae.safetensors'])['select'],
      ['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae.safetensors'])
check('an all-in-one file needs nothing', fm.pick('Flux', 'flux', True, True, MODULES, [])['select'], [])
check('one bringing only its encoders needs only the VAE',
      fm.pick('Flux', 'flux', True, False, MODULES, [])['select'], ['ae.safetensors'])
check('where two files share a layout, the one named for the architecture is picked',
      (fm.pick('WAN21_T2V', 'wan', True, False, MODULES, [])['select'],
       fm.pick('QwenImage', 'qwen', True, False, MODULES, [])['select']),
      (['wan_2.1_vae.safetensors'], ['qwen_image_vae.safetensors']))
got = fm.pick('QwenImage', 'qwen', False, False, MODULES, [])
check('what nothing installed is, is reported, not guessed at',
      (got['select'], got['missing']), (['qwen_image_vae.safetensors'], ['qwen25_7b']))
check('with only a preset known, its class is assumed',
      fm.pick(None, 'flux', False, False, MODULES, [])['needed'], ['clip_l', 't5xxl', 'vae_ae'])

# ---------------------------------------------------- the settings' choice
# A person names the files a preset should use - an fp8 text encoder where
# the full one does not fit their card. Named files beat everything else of
# their kind; only the right kind is taken, so one list can serve every
# model of a preset.
check('a setting is read as file names: commas or lines, folders dropped, no repeats',
      fm.parse_file_names(' t5xxl_fp8.safetensors,\nsub\\dir/ae.safetensors, ,ae.safetensors'),
      ['t5xxl_fp8.safetensors', 'ae.safetensors'])
got = fm.pick('Flux', 'flux', False, False, MODULES, ['t5xxl_fp16.safetensors'],
              ['T5XXL_FP8'])
check('a file named in the settings beats Forge\'s saved choice and finer weights; '
      'case and extension do not matter',
      got['select'], ['clip_l.safetensors', 't5xxl_fp8.safetensors', 'ae.safetensors'])
got = fm.pick('Flux', 'flux', False, False, MODULES, [],
              ['sdxl_vae.safetensors', 'ae.safetensors'])
check('one of a kind the model does not need is left out',
      got['select'], ['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae.safetensors'])
check('as a Flux setting\'s CLIP-L is for Chroma, which does not use it',
      fm.pick('Chroma', 'flux', False, False, MODULES, [], ['clip_l'])['select'],
      ['t5xxl_fp16.safetensors', 'ae.safetensors'])
got = fm.pick('Flux', 'flux', False, False, MODULES, [], ['t5xxl_q8.gguf'])
check('a name nothing installed has is reported, and the pick goes on without it',
      (got['select'], got['not_found']),
      (['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae.safetensors'], ['t5xxl_q8.gguf']))
odd = {**MODULES, 'my_qwen_encoder.safetensors': (None, 0)}
got = fm.pick('QwenImage', 'qwen', False, False, odd, [], ['my_qwen_encoder'])
check('a named file this cannot identify is selected anyway, and nothing called missing',
      (got['select'], got['missing']),
      (['qwen_image_vae.safetensors', 'my_qwen_encoder.safetensors'], []))
check('but an unidentified file nobody named is never selected',
      fm.pick('QwenImage', 'qwen', False, False, odd, [])['missing'], ['qwen25_7b'])
check('nor is a named one for a model that needs nothing',
      fm.pick('Flux', 'flux', True, True, odd, [], ['my_qwen_encoder'])['select'], [])

# ------------------------------------------------------ reading module files
path = os.path.join(TESTS, 'work', 'forge_modules_t5.sft')
os.makedirs(os.path.dirname(path), exist_ok=True)
raw = json.dumps({'shared.weight': {'dtype': 'BF16', 'shape': [32128, 4096], 'data_offsets': [0, 0]},
                  'encoder.block.0.layer.0.SelfAttention.k.weight':
                      {'dtype': 'BF16', 'shape': [4096, 4096], 'data_offsets': [0, 0]}}).encode()
open(path, 'wb').write(struct.pack('<Q', len(raw)) + raw)
check('a module file is read and classified, .sft included', fi.classify_file(path), ('t5xxl', 2))

# -------------------------------------------------------------- the endpoint
db, facts = fixtures.build(WORK)
dbmod._db_instance = db
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))
host.installed_modules = lambda: {label: label for label in MODULES}
fi.classify_file = lambda path: MODULES[path]
host.saved_modules = lambda preset: []
settings = {}
fm.preferred_modules = lambda preset: fm.parse_file_names(settings.get(preset, ''))

flux_path = facts['linked_paths'][4]
db.set_architecture(flux_path, 'flux', 'Flux', False, False, '9999', file_type='Checkpoint')
import model_manager.identity_store as store             # noqa: E402
store.needs_check = lambda db_, p: None                   # already read, as stored
body = client.get('/model-manager/forge-modules', params={'file_path': flux_path}).json()
check('for a checkpoint read as Flux: its preset, and what to select, from the file',
      (body['preset'], body['source'], body['manage_modules'], body['select']),
      ('flux', 'file', True, ['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae.safetensors']))

settings['flux'] = 't5xxl_fp8.safetensors, t5xxl_gone.safetensors'
body = client.get('/model-manager/forge-modules', params={'file_path': flux_path}).json()
check('the endpoint takes the preset\'s setting, and says which names are not installed',
      (body['select'], body['not_found']),
      (['clip_l.safetensors', 't5xxl_fp8.safetensors', 'ae.safetensors'], ['t5xxl_gone.safetensors']))
settings.clear()

body = client.get('/model-manager/forge-modules', params={'base_model': 'Flux.1 D'}).json()
check('a gallery that is not a checkpoint\'s goes by Civitai\'s baseModel',
      (body['preset'], body['source'], body['select'][:1]), ('flux', 'civitai', ['clip_l.safetensors']))

body = client.get('/model-manager/forge-modules', params={'base_model': 'Illustrious'}).json()
check('SD and SDXL bring their own: modules are left to the image\'s VAE, as before',
      (body['preset'], body['manage_modules'], body['select']), ('xl', False, []))

body = client.get('/model-manager/forge-modules', params={'base_model': 'HiDream'}).json()
check('and with no preset to go by, nothing is set up', (body['preset'], body['manage_modules']),
      (None, False))

# What Send makes the VAE / Text Encoder control hold: `target`, exactly - the
# page changes only what differs from it. For a model whose modules are
# managed, what pick() selects; for SD and SDXL, the image's own VAE as Forge
# lists it, or nothing.
body = client.get('/model-manager/forge-modules', params={'file_path': flux_path}).json()
check('a managed model\'s target is what is picked for it', body['target'], body['select'])
body = client.get('/model-manager/forge-modules', params={'base_model': 'Illustrious',
                                                          'vae': 'sdxl_vae'}).json()
check('an SDXL image\'s is its own VAE, found by its bare name',
      (body['target'], body['vae_not_found']), (['sdxl_vae.safetensors'], None))
body = client.get('/model-manager/forge-modules', params={'base_model': 'Illustrious',
                                                          'vae': 'vae_i_do_not_have'}).json()
check('a VAE not installed is said, and nothing is its target',
      (body['target'], body['vae_not_found']), ([], 'vae_i_do_not_have'))
body = client.get('/model-manager/forge-modules', params={'base_model': 'Illustrious'}).json()
check('and an image that names none has nothing to hold', body['target'], [])

# A checkpoint that carries its own text encoders and VAE - an all-in-one
# Flux.1 or Krea 2 - gets none of them selected, and the page is told which
# it brings, to say so: an empty control read as a send that had failed.
body = client.get('/model-manager/forge-modules', params={'file_path': flux_path}).json()
check('a checkpoint without them brings nothing', body['bundled'], [])
db.set_architecture(flux_path, 'flux', 'Flux', True, True, '9999', file_type='Checkpoint')
body = client.get('/model-manager/forge-modules', params={'file_path': flux_path}).json()
check('an all-in-one Flux.1 brings its text encoders and VAE, and none is selected',
      (body['bundled'], body['select'], body['target']), (['clip_l', 't5xxl', 'vae_ae'], [], []))
db.set_architecture(flux_path, 'flux', 'Flux', True, False, '9999', file_type='Checkpoint')
body = client.get('/model-manager/forge-modules', params={'file_path': flux_path}).json()
check('one with its text encoders alone gets only the VAE',
      (body['bundled'], body['select']), (['clip_l', 't5xxl'], ['ae.safetensors']))
body = client.get('/model-manager/forge-modules', params={'base_model': 'Illustrious'}).json()
check('and SD or SDXL, which always bring their own, are not said to', body['bundled'], [])
db.set_architecture(flux_path, 'flux', 'Flux', False, False, '9999', file_type='Checkpoint')

# The gallery's own file is the primary (#134): sent from a VAE's gallery,
# that VAE is selected, whatever would have been picked; from a text
# encoder's, that encoder in its kind's place. The rest is picked as ever.
own_vae, own_sd_vae, own_te, lora_path = facts['linked_paths'][:4]
db.set_architecture(own_vae, None, None, False, False, '9999', file_type='VAE')
db.set_architecture(own_sd_vae, None, None, False, False, '9999', file_type='VAE')
db.set_architecture(own_te, None, None, False, False, '9999', file_type='Text Encoder')
db.set_architecture(lora_path, 'flux', None, False, False, '9999', file_type='LORA')
OWN = {own_vae: ('ae_own.safetensors', ('vae_ae', 1)), own_sd_vae: ('sd_own.safetensors', ('vae_sd', 2)),
       own_te: ('t5_own.safetensors', ('t5xxl', 1))}
listed = {label: label for label in MODULES}
listed.update({label: path for path, (label, _) in OWN.items()})
kinds = {**MODULES, **{path: kind for path, (_, kind) in OWN.items()}}
host.installed_modules = lambda: dict(listed)
fi.classify_file = lambda path: kinds[path]
flux_id = db.get_version(flux_path)['id']
host.checkpoint_name = lambda path: None          # no Forge here to list checkpoints


def sent_from(path, **params):
    return client.get('/model-manager/forge-modules', params={'file_path': path, **params}).json()


body = sent_from(own_vae, version_ids=str(flux_id))
check('a VAE\'s gallery, a Flux image: that VAE, in place of the one picked, the rest as picked',
      (body['preset'], body['target']),
      ('flux', ['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae_own.safetensors']))
body = sent_from(own_sd_vae, version_ids=str(flux_id))
check('a VAE takes the VAE\'s place whatever kind it is: the gallery\'s is the one asked for',
      (body['target'], body['missing']),
      (['clip_l.safetensors', 't5xxl_fp16.safetensors', 'sd_own.safetensors'], []))
body = sent_from(own_te, version_ids=str(flux_id))
check('a text encoder\'s gallery: that encoder, in its kind\'s place',
      body['target'], ['clip_l.safetensors', 't5_own.safetensors', 'ae.safetensors'])
body = sent_from(own_sd_vae, base_model='Illustrious', vae='sdxl_vae')
check('an SDXL image from a VAE\'s gallery: that VAE, not the one the image names',
      (body['preset'], body['target'], body['vae_not_found']), ('xl', ['sd_own.safetensors'], None))
del listed['ae_own.safetensors']
body = sent_from(own_vae, version_ids=str(flux_id))
check('a gallery\'s file Forge does not list is said, and the rest picked as ever',
      (body.get('own_not_listed'), body['target']),
      (os.path.basename(own_vae), ['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae.safetensors']))
listed['ae_own.safetensors'] = own_vae

# And the image's checkpoint, which a gallery that is not a checkpoint's
# never loaded: by the name Forge lists it under - or, where it cannot be
# loaded, why, for the page to say rather than send.
import model_manager.model_dirs as dirs                    # noqa: E402
import model_manager.send_plan as sp                       # noqa: E402
names = {flux_path: 'flux.safetensors [abcd1234]'}
host.checkpoint_name = lambda path: names.get(path)
body = sent_from(lora_path, version_ids=str(flux_id))
check('a LoRA\'s gallery, the image\'s checkpoint in the library: Forge\'s name for it, nothing wrong',
      (body.get('checkpoint'), body.get('checkpoint_problem')), ('flux.safetensors [abcd1234]', None))
check('a checkpoint\'s gallery loads its own, and is told of no other',
      (sent_from(flux_path).get('checkpoint'), sent_from(flux_path).get('checkpoint_problem')), (None, None))
names.clear()
body = sent_from(lora_path, version_ids=str(flux_id))
check('one Forge does not list, outside this WebUI\'s folders: where it is',
      (body.get('checkpoint'), body.get('checkpoint_problem')),
      (None, {'reason': 'elsewhere', 'name': os.path.basename(flux_path), 'path': flux_path}))
here = dirs.folder_of
dirs.folder_of = sp.folder_of = lambda path, *a, **k: ('Checkpoint', os.path.dirname(path))
body = sent_from(lora_path, version_ids=str(flux_id))
check('one in this WebUI\'s folders that Forge does not list yet: said so',
      (body.get('checkpoint_problem') or {}).get('reason'), 'not_listed')
dirs.folder_of = sp.folder_of = here
body = sent_from(lora_path, model_name='a_checkpoint_i_lack', hashes='0123456789')
check('one the library lacks: missing, by its name',
      body.get('checkpoint_problem'), {'reason': 'missing', 'name': 'a_checkpoint_i_lack'})
body = sent_from(lora_path, version_ids=str(db.get_version(own_vae)['id']))
check('what it names as a checkpoint is not one: said so',
      body.get('checkpoint_problem'), {'reason': 'not_checkpoint'})
check('and an image that names none: nothing to say yet', sent_from(lora_path).get('checkpoint_problem'), None)

# An upscaler's gallery: that upscaler, as Hires fix's, by the name Forge
# lists it under (forge_host.upscaler_name); one it does not list is said.
upscaler_path = facts['linked_paths'][5]
db.set_architecture(upscaler_path, None, None, False, False, '9999', file_type='Upscaler')
upscalers = {upscaler_path: '4x-UltraSharp'}
host.upscaler_name = lambda path: upscalers.get(path)
body = sent_from(upscaler_path, version_ids=str(flux_id))
check('an upscaler\'s gallery: Forge\'s name for it, and the image\'s checkpoint as from any other',
      (body.get('upscaler'), body.get('upscaler_not_listed'), (body.get('checkpoint_problem') or {}).get('reason')),
      ('4x-UltraSharp', None, 'elsewhere'))
upscalers.clear()
body = sent_from(upscaler_path, version_ids=str(flux_id))
check('one Forge does not list: said, by its file', (body.get('upscaler'), body.get('upscaler_not_listed')),
      (None, os.path.basename(upscaler_path)))
check('and any other gallery has no upscaler to set',
      (sent_from(lora_path).get('upscaler'), sent_from(lora_path).get('upscaler_not_listed')), (None, None))
host.installed_modules = lambda: {label: label for label in MODULES}
fi.classify_file = lambda path: MODULES[path]

labels = ['sdxl_vae.safetensors', 'vae-ft-mse-840000-ema-pruned.safetensors', 'ae.safetensors']
check('a VAE name is matched as the file, the file less its extension, or the start of one',
      [fm.match_vae(n, labels) for n in ('ae.safetensors', 'SDXL_VAE', 'vae-ft-mse-840000', 'nope', '')],
      ['ae.safetensors', 'sdxl_vae.safetensors', 'vae-ft-mse-840000-ema-pruned.safetensors', None, None])

# What Forge holds, to check a change took: its setting, as the labels it shows.
shared = sys.modules['modules.shared']
shared.opts.forge_additional_modules = ['C:/models/VAE/ae.safetensors', 'C:/models/text_encoder/clip_l.safetensors']
check('what Forge holds is read from its setting, by file name',
      client.get('/model-manager/forge-modules/current').json()['modules'],
      ['ae.safetensors', 'clip_l.safetensors'])
del shared.opts.forge_additional_modules
check('and where there is no such setting, nothing is claimed',
      client.get('/model-manager/forge-modules/current').json()['modules'], None)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
