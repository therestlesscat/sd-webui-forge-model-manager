"""
ControlNets, and what else Forge keeps in its ControlNet folder (#118).

A ControlNet is shaped like the UNet or DiT it steers. Forge's checkpoint
detector refuses one, and its layer names then read as a bare diffusion
model: file_identity called it a Checkpoint, a download of one was moved
into Stable-diffusion, and Scan Disk typed those on disk as Checkpoints and
offered to move them there too.

Here, on the headers of 19 published files (tests/controlnet_headers.json.gz:
names and shapes, never weights) - ControlNets in diffusers' and the original
layout, Union ones, Control-LoRAs, T2I-Adapters, ControlLLLites, IP-Adapters,
Flux ControlNets: each is a Controlnet, told before Forge's detector is
asked; its folder is ControlNet's; a download of one stays there, and Scan
Disk does not list one as misplaced. And a Checkpoint known only by its
layer names - something UNet-shaped Forge did not take - is never moved: as
a checkpoint, Forge could not load it either.
"""
import gzip
import io
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
import model_manager.db.database as dbmod                # noqa: E402
from modules import paths                                # noqa: E402  (webui_stub's)
from model_manager import file_identity, model_dirs     # noqa: E402
from model_manager import architecture                   # noqa: E402
from model_manager.architecture import Architecture     # noqa: E402
from model_manager.download_service import DownloadProgress, DownloadService  # noqa: E402
from model_manager.identity_store import store_architecture  # noqa: E402
from model_manager.model_dirs import file_modified, misplaced_files  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'controlnet')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def not_forge(shapes):
    raise ValueError('Forge does not recognise this')


class SDXL:
    """What Forge's detector answers for an SDXL UNet."""


def forge_takes_it(shapes):
    return SDXL(), shapes


with gzip.open(os.path.join(TESTS, 'controlnet_headers.json.gz'), 'rt', encoding='utf-8') as f:
    HEADERS = json.load(f)['files']


def shapes_of(name):
    return {n: (tuple(s), 'F16') for n, s in HEADERS[name]['tensors'].items()}


# ------------------------------------------------------------ what it is
told = {name: file_identity.identify_shapes(shapes_of(name), not_forge) for name in HEADERS}
check('every one of them is a Controlnet, as Civitai spells the type',
      sorted(name for name, found in told.items() if found.file_type != 'Controlnet'), [])
check('saying which kind', sorted({found.note.split(';')[0] for found in told.values()}),
      ['a Control-LoRA', 'a ControlLLLite', 'a ControlNet', 'a T2I-Adapter', 'an IP-Adapter'])
check('and the model it is for, where its layers tell',
      {name: told[name].preset for name in ('v11_sd15', 'diffusers_sdxl_union', 'control_lora', 'lllite', 'flux_xlabs')},
      {'v11_sd15': 'sd', 'diffusers_sdxl_union': 'xl', 'control_lora': 'xl', 'lllite': 'xl', 'flux_xlabs': 'flux'})
check('told before Forge\'s detector is asked: a ControlNet it took for an SDXL UNet is still one',
      file_identity.identify_shapes(shapes_of('diffusers_sdxl_canny'), forge_takes_it).file_type, 'Controlnet')
check('the type is one the Type filter lists, filed in ControlNet\'s folder',
      ('Controlnet' in file_identity.FILE_TYPES, model_dirs.FOLDER_FOR_FILE_TYPE.get('Controlnet')),
      (True, 'Controlnet'))

# What shares a name or two with them is not one: an ESRGAN upscaler's body.N
# blocks, a checkpoint Forge takes, a LoRA.
esrgan = {'conv_first.weight': (64, 3, 3, 3), 'body.0.rdb1.conv1.weight': (32, 64, 3, 3),
          'conv_body.weight': (64, 64, 3, 3), 'conv_last.weight': (3, 64, 3, 3)}
check('an ESRGAN upscaler is not taken for a T2I-Adapter',
      file_identity.identify_shapes({n: (s, 'F16') for n, s in esrgan.items()}, not_forge).file_type, 'Upscaler')
unet = {'input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight': (320, 768),
        'middle_block.1.proj_in.weight': (1280, 1280, 1, 1)}
check('a bare UNet with no ControlNet\'s layers is still a Checkpoint',
      file_identity.identify_shapes({n: (s, 'F16') for n, s in unet.items()}, not_forge).file_type, 'Checkpoint')

# ------------------------------------------------------------ where it goes
db, facts = fixtures.build(WORK)
dbmod._db_instance = db
models = facts['models_dir']
paths.models_path = models


def write_header(path, name):
    """A file holding only the header of fixture file `name` - enough to read what it is."""
    header = {n: {'dtype': 'F16', 'shape': list(s), 'data_offsets': [0, 0]}
              for n, (s, _) in shapes_of(name).items()}
    raw = json.dumps(header).encode()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'wb') as f:
        f.write(struct.pack('<Q', len(raw)) + raw)


real_guess = architecture._forge_guess
architecture._forge_guess = not_forge
in_controlnet = os.path.join(model_dirs.download_dir('Controlnet'), '_SDXL', 'Union', 'union.safetensors')
write_header(in_controlnet, 'diffusers_sdxl_union')
progress = DownloadProgress(version_id=1)
check('a downloaded ControlNet stays in ControlNet\'s folder',
      (DownloadService._file_by_what_it_is(in_controlnet, progress), progress.filed), (in_controlnet, None))
check('and nothing was put in Stable-diffusion',
      os.path.exists(os.path.join(model_dirs.download_dir('Checkpoint'), '_SDXL', 'Union', 'union.safetensors')), False)

# Something UNet-shaped this does not know - here a bare UNet, landed in Lora:
# Forge did not take it as a checkpoint, so it is not one Forge could load
# from Stable-diffusion either. It stays where it landed.
in_lora = os.path.join(model_dirs.download_dir('LORA'), 'unet_shaped.safetensors')
os.makedirs(os.path.dirname(in_lora), exist_ok=True)
header = json.dumps({n: {'dtype': 'F16', 'shape': list(s), 'data_offsets': [0, 0]} for n, s in unet.items()}).encode()
io.open(in_lora, 'wb').write(struct.pack('<Q', len(header)) + header)
progress = DownloadProgress(version_id=2)
check('a Checkpoint known only by its layer names is not moved',
      (DownloadService._file_by_what_it_is(in_lora, progress), progress.filed), (in_lora, None))
architecture._forge_guess = real_guess


def place(folder, name, file_type, model_class=None):
    """A file in a folder, read by a scan as `file_type`, of Forge's `model_class` if it took it."""
    path = os.path.join(models, folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, 'wb').write(b'\0' * 32)
    db.upsert_version({'file_path': path, 'file_name': name, 'file_extension': os.path.splitext(name)[1],
                       'has_civitai_data': False})
    store_architecture(db, path, Architecture('xl', model_class, False, False, file_type, 'read for the test'),
                       file_modified(path))
    return path


controlnet = place('ControlNet', 'canny.safetensors', 'Controlnet')
moved_before = place(os.path.join('Stable-diffusion', '_SDXL'), 'depth.safetensors', 'Controlnet')
layered = place('Lora', 'unet_shaped.safetensors', 'Checkpoint', model_class=None)
taken = place('Lora', 'real_checkpoint.safetensors', 'Checkpoint', model_class='SDXL')
listed = {f['path']: f['to'] for f in misplaced_files(db)}
check('Scan Disk does not list a ControlNet in its folder as misplaced', controlnet in listed, False)
check('but one an earlier version moved into Stable-diffusion goes back to ControlNet\'s',
      listed.get(moved_before), os.path.join(models, 'ControlNet', '_SDXL', 'depth.safetensors'))
check('a Checkpoint known only by its layer names is not listed', layered in listed, False)
check('one Forge\'s detector took is, as before', listed.get(taken),
      os.path.join(models, 'Stable-diffusion', 'real_checkpoint.safetensors'))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
