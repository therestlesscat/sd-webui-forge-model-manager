"""
The settings window's text encoder and VAE table, as the server describes it.

For each preset the WebUI has: a row per file its models need, the installed
files of that kind to choose from, what Send to txt2img would pick unasked,
and which the setting names - with anything the setting names that no row
can take kept, and said why.

A kind is a shape, and two files of one shape are not always one file: Wan's
VAE and Qwen-Image's share a layout. So the rows are files, and the window
fills a choice in only for the same file.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                       # noqa: E402

webui_stub.install()

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import gradio                                       # noqa: F401
except ImportError:
    print('fastapi or gradio is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import model_manager.forge_modules as fm                 # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# What classify_file would say of each installed file: (kind, precision).
INSTALLED = {
    'clip_l.safetensors': ('clip_l', 2),
    't5xxl_fp16.safetensors': ('t5xxl', 2),
    't5xxl_fp8_e4m3fn_scaled.safetensors': ('t5xxl', 1),
    'ae.safetensors': ('vae_ae', 2),
    'ae_fp8.safetensors': ('vae_ae', 1),
    'qwen_image_vae.safetensors': ('vae_wan21', 2),
    'wan_2.1_vae.safetensors': ('vae_wan21', 2),
    'qwen_3_4b.gguf': ('qwen3_4b', 0),
    'mystery.safetensors': (None, 0),
}


def rows_of(table, preset):
    return {r['file']: r for p in table if p['preset'] == preset for r in p['rows']}


def preset_of(table, preset):
    return next(p for p in table if p['preset'] == preset)


# ------------------------------------------------------------- the file list
check('each file a preset needs is one of the files, of a kind classify() names',
      all(f in fm.FILES for files in fm.CLASS_FILES.values() for f in files), True)
check('every class a preset runs has its files listed',
      sorted(c for p, _, _ in fm.MODULE_PRESETS for c in fm.preset_classes(p)) == sorted(fm.CLASS_FILES), True)
check('Wan\'s VAE and Qwen-Image\'s are one shape and two files',
      [fm.FILES['wan21_vae'].kind == fm.FILES['qwen_image_vae'].kind, 'wan21_vae' != 'qwen_image_vae'], [True, True])

# -------------------------------------------------------------- a description
table = fm.describe_presets(None, INSTALLED, {
    'flux': 't5xxl_fp8_e4m3fn_scaled, missing.safetensors, mystery, qwen_image_vae',
}, saved_for=lambda preset: [])
flux = rows_of(table, 'flux')
check('with no list of presets, every one is described', [p['preset'] for p in table],
      [p for p, _, _ in fm.MODULE_PRESETS])
check('a row per file the preset\'s models need, in order', list(flux), ['clip_l', 't5xxl', 'ae'])
check('saying which of its models use each', flux['t5xxl']['used_by'], ['Flux.1', 'Flux.1 Schnell', 'Chroma'])
check('offering the installed files of that kind, with their precision',
      flux['t5xxl']['candidates'], [{'label': 't5xxl_fp16.safetensors', 'precision': 'full'},
                                    {'label': 't5xxl_fp8_e4m3fn_scaled.safetensors', 'precision': 'fp8'}])
check('Automatic is what pick() takes unasked: the finer weights', flux['t5xxl']['automatic'], 't5xxl_fp16.safetensors')
check('a name in the setting, without its extension, is that row\'s choice',
      flux['t5xxl']['selected'], 't5xxl_fp8_e4m3fn_scaled.safetensors')
check('rows the setting says nothing of are on Automatic', [flux['clip_l']['selected'], flux['ae']['selected']], [None, None])
check('names no row takes are kept, each with why', preset_of(table, 'flux')['kept'], [
    {'name': 'missing.safetensors', 'why': 'not installed'},
    {'name': 'mystery', 'why': 'not identified'},
    {'name': 'qwen_image_vae', 'why': 'not a file this preset needs'},
])
check('Qwen-Image\'s automatic VAE is its own, by name, among files of Wan\'s shape',
      rows_of(table, 'qwen')['qwen_image_vae']['automatic'], 'qwen_image_vae.safetensors')
check('and Wan\'s is Wan\'s', rows_of(table, 'wan')['wan21_vae']['automatic'], 'wan_2.1_vae.safetensors')
klein = rows_of(table, 'klein')
check('a file nothing installed is: no choice, and where to get it',
      [klein['qwen3_8b']['candidates'], klein['qwen3_8b']['automatic'], klein['qwen3_8b']['links'][0][1]],
      [[], None, fm.HF + fm.FILES['qwen3_8b'].links[0][1]])
check('Forge\'s saved choice for a preset counts, as it does for Send to txt2img',
      rows_of(fm.describe_presets(['flux'], INSTALLED, {}, saved_for=lambda p: ['ae_fp8.safetensors']),
              'flux')['ae']['automatic'], 'ae_fp8.safetensors')

# --------------------------------------------------- the original Forge
check('in the original Forge, whose presets are sd, xl, flux and all, only Flux is described',
      [p['preset'] for p in fm.describe_presets(['sd', 'xl', 'flux', 'all'], INSTALLED, {},
                                                saved_for=lambda p: [])], ['flux'])

# ------------------------------------------------------------ the endpoint
fm.installed_modules = lambda: {label: 'C:/models/' + label for label in INSTALLED}
fm.classify_file = lambda path: INSTALLED[os.path.basename(path)]
fm.available_presets = lambda: ['sd', 'xl', 'flux', 'zit']

from modules import shared                               # noqa: E402

shared.opts.model_manager_modules_zit = 'ae_fp8'
import model_manager.api.settings as settings_api        # noqa: E402

settings_api._ours = lambda: [('model_manager_modules_flux', None), ('model_manager_modules_zit', None)]
app = FastAPI()
settings_api.register(app)
client = TestClient(app)

answer = client.get('/model-manager/settings/modules').json()
check('the endpoint describes the presets this WebUI has', [p['preset'] for p in answer['presets']], ['flux', 'zit'])
check('from the settings as saved', rows_of(answer['presets'], 'zit')['ae']['selected'], 'ae_fp8.safetensors')
answer = client.get('/model-manager/settings/modules', params={'drafts': '{"zit": "ae"}'}).json()
check('or from text the window holds, for a preset edited as text',
      rows_of(answer['presets'], 'zit')['ae']['selected'], 'ae.safetensors')

# ----------------------------------------------------- the Settings page
from model_manager.ui import settings as ui_settings     # noqa: E402

for preset, _, note in fm.MODULE_PRESETS:
    text = ui_settings._module_help(preset, note)
    links = [fm.HF + path for f, _ in fm.preset_files(preset) for _, path in fm.FILES[f].links]
    check('the Settings page links every download for %s' % preset, all(link in text for link in links), True)
check('and says what each of a preset\'s models needs',
      ui_settings._module_help('klein', '').split(' Download:')[0],
      'Klein 4B needs Qwen3 4B and Flux.2 VAE; Klein 9B needs Qwen3 8B and Flux.2 VAE.')

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
