"""
Which folders this WebUI loads from, type by type (#195).

An option either adds a folder to its type's own one under models, or
replaces it. --lora-dir, --controlnet-dir and the original Forge's
--hypernetwork-dir replace it in both WebUIs; --esrgan-models-path replaces
it in Neo and adds to it in the original Forge; the plural options add.
"Held here" counted the type's own folder always, so a file there read as
held - Owned in the Civitai Browser - where this WebUI could not load it. It
is ignored instead, and says which option replaced its folder.

What is checked: held_here per option and per WebUI, the reason
ignored_because gives, that the walk and a folder's type stay as they were,
and that Send takes the copy this WebUI loads.
"""
import os
import shutil
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

from model_manager import model_dirs                    # noqa: E402
from model_manager import send_plan                     # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


WORK = os.path.join(TESTS, 'work', 'loaded_folders')
shutil.rmtree(WORK, ignore_errors=True)
MODELS = os.path.join(WORK, 'webui', 'models')
SHARED = os.path.join(WORK, 'z_shared')               # given by options; sorts after webui\models
AWAY = os.path.join(WORK, 'away')                     # a folder this WebUI was not given


def model_file(*parts):
    path = os.path.join(*parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'weights')
    return path


own_upscaler = model_file(MODELS, 'ESRGAN', '4x_own.pth')
shared_upscaler = model_file(SHARED, 'ESRGAN', '4x_shared.pth')
own_lora = model_file(MODELS, 'Lora', 'own.safetensors')
shared_lora = model_file(SHARED, 'Lora', 'shared.safetensors')
own_controlnet = model_file(MODELS, 'ControlNet', 'own_cn.safetensors')
own_hypernetwork = model_file(MODELS, 'hypernetworks', 'own_hn.pt')
away_lora = model_file(AWAY, 'away.safetensors')


def neo(**options):
    """Neo's options: its singular ones carry their default when not given."""
    values = {'ckpt_dirs': [], 'lora_dirs': [], 'vae_dirs': [], 'text_encoder_dirs': [], 'controlnet_dirs': [],
              'lora_dir': os.path.join(MODELS, 'Lora'), 'controlnet_dir': os.path.join(MODELS, 'ControlNet'),
              'esrgan_models_path': os.path.join(MODELS, 'ESRGAN'),
              'embeddings_dir': os.path.join(MODELS, 'embeddings')}
    values.update(options)
    return SimpleNamespace(**values)


def original(**options):
    """The original Forge's: --ckpt-dir and the like are None when not given."""
    values = {'ckpt_dir': None, 'vae_dir': None, 'text_encoder_dir': None, 'controlnet_dir': None,
              'lora_dir': os.path.join(MODELS, 'Lora'), 'hypernetwork_dir': os.path.join(MODELS, 'hypernetworks'),
              'esrgan_models_path': os.path.join(MODELS, 'ESRGAN'),
              'embeddings_dir': os.path.join(WORK, 'webui', 'embeddings')}
    values.update(options)
    return SimpleNamespace(**values)


def as_neo(is_neo):
    # The rule asks which WebUI this is; outside one, the test says.
    model_dirs.is_neo = lambda: is_neo


def held(path, opts):
    return model_dirs.held_here(path, opts, MODELS)


def ignored(path, opts):
    find = getattr(model_dirs, 'ignored_because', None)
    return find(path, opts, MODELS) if find else 'no ignored_because'


# ---------------------------------------------------------------- upscalers
as_neo(True)
neo_esrgan = neo(esrgan_models_path=os.path.join(SHARED, 'ESRGAN'))
check('Neo, --esrgan-models-path given: its own ESRGAN folder is not loaded, so not held',
      held(own_upscaler, neo_esrgan), False)
check('and says which option replaced the folder',
      ignored(own_upscaler, neo_esrgan), '--esrgan-models-path')
check('the option\'s folder is held', held(shared_upscaler, neo_esrgan), True)
check('and is not ignored', ignored(shared_upscaler, neo_esrgan), None)
check('Neo, no option given: its own ESRGAN folder is held', held(own_upscaler, neo()), True)

as_neo(False)
original_esrgan = original(esrgan_models_path=os.path.join(SHARED, 'ESRGAN'))
check('the original Forge adds the option\'s folder: its own ESRGAN stays held',
      (held(own_upscaler, original_esrgan), held(shared_upscaler, original_esrgan)), (True, True))
check('and nothing is ignored', ignored(own_upscaler, original_esrgan), None)

# --------------------------------------------------------------------- LoRAs
for name, webui, is_neo in (('Neo', neo, True), ('the original Forge', original, False)):
    as_neo(is_neo)
    opts = webui(lora_dir=os.path.join(SHARED, 'Lora'))
    check('%s, --lora-dir given: models\\Lora is not loaded, so not held' % name, held(own_lora, opts), False)
    check('%s: --lora-dir is the reason' % name, ignored(own_lora, opts), '--lora-dir')
    check('%s: the option\'s folder is held' % name, held(shared_lora, opts), True)

as_neo(True)
adds = neo(lora_dirs=[os.path.join(SHARED, 'Lora')])
check('Neo, --lora-dirs alone adds: both LoRA folders are held',
      (held(own_lora, adds), held(shared_lora, adds)), (True, True))
check('a folder this WebUI was not given is neither held nor ignored: the other WebUI\'s',
      (held(away_lora, adds), ignored(away_lora, adds)), (False, None))

# ----------------------------------------------------- ControlNet, hypernetworks
opts = neo(controlnet_dir=os.path.join(SHARED, 'ControlNet'))
check('Neo, --controlnet-dir given: models\\ControlNet is not held', held(own_controlnet, opts), False)
check('--controlnet-dir is the reason', ignored(own_controlnet, opts), '--controlnet-dir')
check('Neo has no --hypernetwork-dir: models\\hypernetworks stays held', held(own_hypernetwork, neo()), True)
as_neo(False)
opts = original(hypernetwork_dir=os.path.join(SHARED, 'hypernetworks'))
check('the original Forge, --hypernetwork-dir given: models\\hypernetworks is not held',
      held(own_hypernetwork, opts), False)

# ------------------------------------------------------- what stays as it was
as_neo(True)
check('a folder\'s type is the walk\'s, loaded or not',
      model_dirs.folder_of(own_upscaler, neo_esrgan, MODELS)[0], 'Upscaler')
walked = [os.path.normcase(d) for d in model_dirs.library_dirs(neo_esrgan, MODELS)]
check('and the walk still covers the ignored folder',
      os.path.normcase(os.path.join(MODELS, 'ESRGAN')) in walked, True)
gone = os.path.join(MODELS, 'ESRGAN', 'deleted_by_hand.pth')
check('a file gone from disk is not ignored, only not held', ignored(gone, neo_esrgan), None)

# ------------------------------------- the ControlNet setting's folder (#197)
# Both WebUIs' ControlNet also loads from the folder Settings -> ControlNet
# names (control_net_models_path), which the walk never knew of.
SETTING_CN = os.path.join(WORK, 'cn_setting')
setting_controlnet = model_file(SETTING_CN, 'from_setting.safetensors')
settings = {}
model_dirs.forge_setting = lambda key: settings.get(key)
walk = lambda opts: [os.path.normcase(f) for f in model_dirs.find_model_files(model_dirs.library_dirs(opts, MODELS))]
for name, webui, is_neo in (('Neo', neo, True), ('the original Forge', original, False)):
    as_neo(is_neo)
    settings['control_net_models_path'] = SETTING_CN
    check('%s: the folder the ControlNet setting names is walked, its file held, of its kind' % name,
          (os.path.normcase(setting_controlnet) in walk(webui()), held(setting_controlnet, webui()),
           model_dirs.folder_of(setting_controlnet, webui(), MODELS)[0]), (True, True, 'Controlnet'))
    check('%s: a ControlNet download goes where it went, never the setting\'s folder' % name,
          os.path.normcase(model_dirs.download_dir('Controlnet', webui(), MODELS)),
          os.path.normcase(os.path.join(MODELS, 'ControlNet')))
    settings['control_net_models_path'] = ''
    check('%s: the setting empty, nothing more is walked' % name,
          os.path.normcase(setting_controlnet) in walk(webui()), False)
    settings['control_net_models_path'] = os.path.join(WORK, 'no_such_folder')
    check('%s: nor when its folder is not there' % name, held(setting_controlnet, webui()), False)
settings.clear()

# ------------------------------------- the original Forge's other upscalers (#198)
# The original Forge loads every Upscaler subclass, each from its option and
# its own folder under models; Neo loads ESRGAN alone.
real_esrgan = model_file(MODELS, 'RealESRGAN', 'RealESRGAN_x4plus_anime_6B.pth')
hat = model_file(MODELS, 'HAT', 'HAT_SRx4.pth')
scunet = model_file(MODELS, 'ScuNET', 'ScuNET.pth')
dat_given = model_file(SHARED, 'DAT', 'DAT_x4.pth')
as_neo(False)
dat_opts = original(dat_models_path=os.path.join(SHARED, 'DAT'))
check('the original Forge walks models\\RealESRGAN and models\\HAT, and holds their files',
      ([os.path.normcase(f) in walk(original()) for f in (real_esrgan, hat)],
       held(real_esrgan, original()), held(hat, original())), ([True, True], True, True))
check('given --dat-models-path, its folder too, beside models\\DAT',
      (os.path.normcase(dat_given) in walk(dat_opts), held(dat_given, dat_opts)), (True, True))
check('an upscaler in models\\ScuNET is in its kind\'s folder, never another type\'s',
      model_dirs.folder_of(scunet, original(), MODELS)[0], 'Upscaler')
check('an upscaler download still goes to ESRGAN',
      os.path.normcase(model_dirs.download_dir('Upscaler', original(), MODELS)),
      os.path.normcase(os.path.join(MODELS, 'ESRGAN')))
as_neo(True)
check('Neo, which loads ESRGAN alone, neither walks nor holds them',
      (os.path.normcase(real_esrgan) in walk(neo()), held(real_esrgan, neo())), (False, False))

# ---------------------------------------------------------------------- Send
# A version with a copy in each LoRA folder: the one models\Lora sorts first,
# and with --lora-dir given it is the copy Forge does not load.
opts = neo(lora_dir=os.path.join(SHARED, 'Lora'))
real_folders = model_dirs.model_folders
model_dirs.model_folders = lambda: (opts, MODELS)
try:
    chosen = send_plan.send_files([
        {'id': 7, 'file_path': own_lora, 'file_type': 'LORA'},
        {'id': 7, 'file_path': shared_lora, 'file_type': 'LORA'},
    ])
finally:
    model_dirs.model_folders = real_folders
check('Send takes the copy this WebUI loads', chosen, {shared_lora})

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
