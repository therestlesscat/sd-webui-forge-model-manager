"""
What a model file is, read from its own header.

Send to txt2img has to switch Forge Neo's UI preset to the model's
architecture and load the text encoders and VAE it lacks. The file says
both: its header names every tensor and its shape, which is enough for the
detector Forge itself uses when loading (huggingface_guess), and shows
whether the text encoder and VAE are inside it. Civitai's baseModel is only
the fallback, for files Forge does not recognise.

Forge's detector is stood in for here - the tests run without Forge. What
is checked is ours: reading the header, turning Forge's answer into a
preset and what the file bundles, the fallback, and when files are read -
new or changed ones on Scan Disk, every time on a forced sync or download.
"""
import json
import os
import struct
import sys
import time

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
import model_manager.db.database as dbmod                # noqa: E402
import model_manager.scan_service as scan_module         # noqa: E402
import model_manager.sync_service as sync_module         # noqa: E402

WORK = os.path.join(TESTS, 'work', 'architecture')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def write_safetensors(path, tensors):
    """A real .safetensors header, with no data behind it."""
    header = {name: {'dtype': 'F16', 'shape': list(shape), 'data_offsets': [0, 0]}
              for name, shape in tensors.items()}
    header['__metadata__'] = {'format': 'pt'}
    raw = json.dumps(header).encode()
    with open(path, 'wb') as f:
        f.write(struct.pack('<Q', len(raw)) + raw)


db, facts = fixtures.build(WORK)
dbmod._db_instance = db

# ------------------------------------------------------------ the header
flux_file = os.path.join(WORK, 'flux_aio.safetensors')
write_safetensors(flux_file, {
    'model.diffusion_model.double_blocks.0.img_attn.qkv.weight': (9216, 3072),
    'text_encoders.clip_l.transformer.text_model.final_layer_norm.weight': (768,),
    'vae.decoder.conv_in.weight': (512, 16, 3, 3),
})
shapes = arch.read_shapes(flux_file)
check('a safetensors header is read for names and shapes',
      shapes['vae.decoder.conv_in.weight'], ((512, 16, 3, 3), 'F16'))
check('its metadata entry is not a tensor', '__metadata__' in shapes, False)
check('a file that is not safetensors reads as nothing',
      arch.read_shapes(facts['linked_paths'][0]), None)
check('nor a .ckpt that is not there', arch.read_shapes(WORK + '/a.ckpt'), None)

# --------------------------------------------------------- Forge's answer
class Flux:                     # named as Forge names its model classes
    text_encoder_key_prefix = ['text_encoders.']
    vae_key_prefix = ['vae.']


class QwenImage(Flux):
    pass


class SD3:                      # a class Forge Neo has no preset for
    pass


def forge_says(config):
    return lambda shapes: (config, dict(shapes))


found = arch.detect(flux_file, guess=forge_says(Flux()))
check('Forge\'s class becomes the UI preset that runs it, with what the file brings',
      (found.preset, found.model_class, found.bundled_text_encoder, found.bundled_vae),
      ('flux', 'Flux', True, True))

bare = os.path.join(WORK, 'qwen_unet.safetensors')
write_safetensors(bare, {'transformer_blocks.0.img_mlp.net.0.proj.weight': (12288, 3072)})
found = arch.detect(bare, guess=forge_says(QwenImage()))
check('a diffusion model alone brings neither', (found.preset, found.bundled_text_encoder,
      found.bundled_vae), ('qwen', False, False))

# A class's declared prefix does not always name where its encoders are:
# SDXL keeps them under conditioner.embedders. Forge's own
# process_clip_state_dict() knows, so that is what is asked.
class SDXL:
    text_encoder_key_prefix = ['cond_stage_model.']      # what it inherits
    vae_key_prefix = ['first_stage_model.']

    def process_clip_state_dict(self, sd):
        return {k: v for k, v in sd.items() if k.startswith('conditioner.embedders.')}


sdxl = os.path.join(WORK, 'sdxl.safetensors')
write_safetensors(sdxl, {'model.diffusion_model.input_blocks.0.0.weight': (320, 4, 3, 3),
                         'conditioner.embedders.0.transformer.text_model.final_layer_norm.weight': (768,),
                         'first_stage_model.decoder.conv_in.weight': (512, 4, 3, 3)})
found = arch.detect(sdxl, guess=forge_says(SDXL()))
check('an SDXL checkpoint bundles its text encoders, found as Forge finds them',
      (found.preset, found.bundled_text_encoder, found.bundled_vae), ('xl', True, True))

check('a class with no Forge Neo preset is not recognised',
      arch.detect(flux_file, guess=forge_says(SD3())), None)


def refuses(shapes):
    raise ModuleNotFoundError('Failed to recognize model...')


check('nor is a file Forge refuses', arch.detect(flux_file, guess=refuses), None)
check('nor one that is not there', arch.detect(WORK + '/missing.safetensors'), None)
check('and without Forge installed, nothing is recognised - never an error',
      arch.detect(flux_file), None)

# ------------------------------------------------------ Civitai's fallback
check('Civitai\'s baseModel maps to a preset when the file says nothing',
      [arch.preset_for_base_model(b) for b in
       ('SD 1.5', 'Illustrious', 'Pony', 'NoobAI', 'SDXL 1.0', 'Flux.1 D', 'Flux.1 Krea',
        'Krea 2', 'Qwen', 'ZImageTurbo', 'Wan Video 2.2 T2V-A14B', 'Anima')],
      ['sd', 'xl', 'xl', 'xl', 'xl', 'flux', 'flux', 'krea', 'qwen', 'zit', 'wan', 'anima'])
check('and to none when Forge Neo has no preset for it',
      [arch.preset_for_base_model(b) for b in ('HiDream', 'Kolors', 'SD 3.5', 'Other', None)],
      [None] * 5)

# ------------------------------------------------------ when files are read
path = facts['linked_paths'][0]
reads = []
import model_manager.file_identity as identity_module       # noqa: E402
real_detect = identity_module.identify
identity_module.identify = lambda p, guess=None: reads.append(p) or arch.Architecture('xl', 'SDXL', True, True)
try:
    check('a file never read is read', arch.record_architecture(db, path).preset, 'xl')
    row = db.get_version(path)
    check('and what it said is stored, with Forge\'s class, the file\'s type, and when',
          (row['architecture'], row['architecture_class'], row['bundled_text_encoder'],
           row['bundled_vae'], row['file_type'], row['architecture_checked'] == arch.file_modified(path)),
          ('xl', 'SDXL', True, True, 'Checkpoint', True))
    check('an unchanged file is not read again',
          (arch.record_architecture(db, path), len(reads)), (None, 1))
    check('unless forced - a forced sync or a download',
          (arch.record_architecture(db, path, force=True).preset, len(reads)), ('xl', 2))
    time.sleep(0.05)
    os.utime(path, None)
    arch.record_architecture(db, path)
    check('a file that has changed is read again', len(reads), 3)

    identity_module.identify = lambda p, guess=None: reads.append(p) or \
        arch.Architecture(None, None, False, False, 'LORA', 'no layer names this knows')
    other = facts['linked_paths'][1]
    arch.record_architecture(db, other)
    row = db.get_version(other)
    check('a file whose model cannot be told is stored as none, so it is not read again',
          (row['architecture'], row['file_type'], row['architecture_checked'] is not None,
           arch.record_architecture(db, other)), (None, 'LORA', True, None))
finally:
    identity_module.identify = real_detect

# ---------------------------------------------------------------- Scan Disk
# GGUF checkpoints (quantized Flux, Wan, Z-Image) were never indexed at all.
for name in ('quantized_flux.gguf', 'ae_short_name.sft'):
    open(os.path.join(facts['models_dir'], 'Stable-diffusion', name), 'wb').write(b'\0' * 64)
indexed = {os.path.basename(p) for p in scan_module.ScanService().find_model_files([facts['models_dir']])}
check('Scan Disk indexes .gguf and .sft files', {'quantized_flux.gguf', 'ae_short_name.sft'} <= indexed)

scanned = []
real_scan_detect = scan_module.identify
scan_module.identify = lambda p: scanned.append(p) or arch.Architecture('sd', 'SD15', True, True)
try:
    scan = scan_module.ScanService()
    scan.scan_models(directories=[facts['models_dir']])
    first = len(scanned)
    check('Scan Disk reads the architecture of files never read', first > 0)
    check('and stores it', db.get_version(facts['linked_paths'][3])['architecture'], 'sd')
    scanned.clear()
    scan.scan_models(directories=[facts['models_dir']])
    check('a second scan reads none of the files unchanged since', scanned, [])
finally:
    scan_module.identify = real_scan_detect

# ------------------------------------------------ forced sync, and downloads
recorded = []
real_record = sync_module.record_architecture
real_inner = sync_module.SyncService._sync_model
sync_module.record_architecture = lambda db_, p, force=False: recorded.append((p, force))
sync_module.SyncService._sync_model = lambda self, p, force=False, classify_checkpoint=True: \
    sync_module.SyncResult()
try:
    sync = sync_module.SyncService(client=None)
    sync.sync_model(path)
    check('an ordinary sync leaves the architecture to Scan Disk', recorded, [])
    sync.sync_model(path, force=True)
    check('a forced sync - which a finished download runs - reads it again',
          recorded, [(path, True)])
finally:
    sync_module.record_architecture = real_record
    sync_module.SyncService._sync_model = real_inner

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
