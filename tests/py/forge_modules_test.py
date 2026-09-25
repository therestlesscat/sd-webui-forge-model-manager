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
      [fm.classify(s) for s in (
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
      fm.classify({**te(256384, 4096, name='shared.weight'), **HF_T5}), 'umt5xxl')
check('as is a quantized one',
      fm.classify({**te(32128, 4096, name='shared.weight'),
                   'encoder.block.0.layer.0.SelfAttention.k.qweight': ((4096, 512), 'I32')}), 't5xxl')
check('but the same encoder in Wan\'s own layout is not a module Forge can load',
      fm.classify({'token_embedding.weight': ((256384, 4096), 'BF16'),
                   'blocks.0.attn.k.weight': ((4096, 4096), 'BF16'),
                   'blocks.0.ffn.gate.0.weight': ((10240, 4096), 'BF16')}), None)
check('and by a vision tower: Qwen3-VL is not Qwen3',
      fm.classify(te(151936, 2560, vision=True)), 'qwen3vl_4b')
check('VAEs by their latent channels, or the Wan-style layout',
      [fm.classify(vae(4)), fm.classify(vae(16)), fm.classify(vae(32)), fm.classify(vae(wan=True))],
      ['vae_sd', 'vae_ae', 'vae_flux2', 'vae_wan21'])
check('a whole checkpoint in the VAE folder is not a module',
      fm.classify({'model.diffusion_model.x': ((1,), 'F16'),
                   'first_stage_model.decoder.conv_in.weight': ((512, 4, 3, 3), 'F16')}), None)
check('nor is anything else', fm.classify({'emb_params': ((8, 768), 'F16')}), None)

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
check('a module file is read and classified, .sft included', fm.classify_file(path), ('t5xxl', 2))

# -------------------------------------------------------------- the endpoint
db, facts = fixtures.build(WORK)
dbmod._db_instance = db
client = TestClient((lambda app: (setup_api(app), app)[1])(FastAPI()))
fm.installed_modules = lambda: {label: label for label in MODULES}
fm.classify_file = lambda path: MODULES[path]
fm.saved_modules = lambda preset: []
settings = {}
fm.preferred_modules = lambda preset: fm.parse_file_names(settings.get(preset, ''))

flux_path = facts['linked_paths'][4]
db.set_architecture(flux_path, 'flux', 'Flux', False, False, '9999')
import model_manager.architecture as arch                 # noqa: E402
arch.needs_check = lambda db_, p: None                    # already read, as stored
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

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
