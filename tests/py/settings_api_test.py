"""
The settings window's endpoints: what they say, and what a save does.

The window edits the WebUI's own settings, so the settings are registered here
exactly as the WebUI registers them - on_ui_settings() against an Options that
behaves as modules/options.py does: add_option, set() with its onchange, save()
to a file. What is checked:

- every Model Manager setting is described, from the WebUI's registry;
- the API key is never sent, only whether one is set;
- a save is all or nothing, checked against each setting's range and choices;
- it goes through opts.set(), so onchange runs (the NSFW settings restamp),
  and the settings file is written only when something changed.
"""
import json
import os
import sys
import types

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

from modules import shared                              # noqa: E402  (the stub's)

WORK = os.path.join(TESTS, 'work', 'settings_api')
os.makedirs(WORK, exist_ok=True)
CONFIG = os.path.join(WORK, 'config.json')
if os.path.exists(CONFIG):
    os.remove(CONFIG)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ------------------------------------------------ the WebUI's options, as it has them
class OptionInfo(object):
    def __init__(self, default=None, label="", component=None, component_args=None,
                 onchange=None, section=None, refresh=None, comment_before='',
                 comment_after='', infotext=None, restrict_api=False, category_id=None):
        self.default = default
        self.label = label
        self.component = component
        self.component_args = component_args
        self.onchange = onchange
        self.section = section
        self.do_not_save = False
        self.comment_before = comment_before
        self.comment_after = comment_after

    def info(self, info):
        self.comment_after += "<span class='info'>(%s)</span>" % info
        return self


class OptionHTML(OptionInfo):
    def __init__(self, text):
        super().__init__(str(text).strip(), label='')
        self.do_not_save = True


class Options(object):
    typemap = {int: float}

    def __init__(self):
        object.__setattr__(self, 'data', {})
        object.__setattr__(self, 'data_labels', {})
        object.__setattr__(self, 'saves', 0)

    def __getattr__(self, key):
        if key in self.data:
            return self.data[key]
        if key in self.data_labels:
            return self.data_labels[key].default
        raise AttributeError(key)

    def __setattr__(self, key, value):
        self.data[key] = value

    def add_option(self, key, info):
        self.data_labels[key] = info
        if key not in self.data and not info.do_not_save:
            self.data[key] = info.default

    def set(self, key, value, is_api=False, run_callbacks=True):
        oldval = self.data.get(key, None)
        if oldval == value:
            return False
        option = self.data_labels[key]
        if option.do_not_save:
            return False
        self.data[key] = value
        if run_callbacks and option.onchange is not None:
            option.onchange()
        return True

    def save(self, filename):
        object.__setattr__(self, 'saves', self.saves + 1)
        with open(filename, 'w', encoding='utf8') as f:
            json.dump(self.data, f, indent=4)

    def same_type(self, x, y):
        if x is None or y is None:
            return True
        return self.typemap.get(type(x), type(x)) == self.typemap.get(type(y), type(y))


opts = Options()
shared.opts = opts
shared.OptionInfo = OptionInfo
shared.OptionHTML = OptionHTML
shared.config_filename = CONFIG
# A setting from elsewhere in the WebUI, which the window must not show.
opts.add_option('sd_model_checkpoint', OptionInfo('x', 'Checkpoint', section=('sd', 'Stable Diffusion')))

from model_manager.ui import settings as ui_settings     # noqa: E402

ui_settings.on_ui_settings()

# The restamp onchange starts, counted rather than run.
import model_manager.prompt_levels as prompt_levels      # noqa: E402

restamps = []
prompt_levels.start_in_background = lambda: restamps.append(1)

import model_manager.db.database as dbmod                # noqa: E402
import fixtures                                          # noqa: E402

db, _facts = fixtures.build(os.path.join(WORK, 'db'))
dbmod._db_instance = db

from model_manager.api import setup_api                  # noqa: E402

app = FastAPI()
setup_api(app)
client = TestClient(app)

KEY = 'model_manager_civitai_api_key'
SECRET = 'abcd-secret-1234'


def get():
    return client.get('/model-manager/settings').json()


def post(values):
    r = client.post('/model-manager/settings', json={'values': values})
    return r.status_code, r.json()


# ------------------------------------------------------------- what is described
ours = [k for k, i in opts.data_labels.items()
        if i.section and i.section[0] == 'model_manager' and not i.do_not_save]
answer = get()
check('it answers', answer.get('success'), True)
check('with every Model Manager setting, in the order they were registered', answer['order'], ours)
check('and nothing from the rest of the WebUI', 'sd_model_checkpoint' in answer['settings'], False)
check('nor the explanation, which is not a setting',
      'model_manager_modules_explanation' in answer['settings'], False)

s = answer['settings']
check('a slider is a number with its bounds',
      {k: s['model_manager_page_size'].get(k) for k in ('kind', 'minimum', 'maximum', 'step', 'value')},
      {'kind': 'number', 'minimum': 5, 'maximum': 50, 'step': 5, 'value': 20})
check('a radio is a choice, with each choice\'s value',
      [s['model_manager_nsfw_detection']['kind'],
       [c[1] for c in s['model_manager_nsfw_detection']['choices']]],
      ['choice', ['model', 'words']])
check('a checkbox is on or off', s['model_manager_gallery_hide_nsfw']['kind'], 'bool')
check('the help text is the Settings page\'s, without its markup',
      s['model_manager_hash_threads']['info'].startswith('How many model files to hash at once'), True)
check('and no help text keeps a tag', any('<' in e['info'] for e in s.values()), False)
check('the database in use is named', answer.get('database_in_use'), db.db_path)
check('and how many words ship with the extension', isinstance(answer.get('bundled_nsfw_words'), int)
      and answer['bundled_nsfw_words'] > 0, True)

# ------------------------------------------------------------------ the API key
check('no key, and it says so', s[KEY].get('has_value'), False)
code, answer = post({KEY: '  %s  ' % SECRET})
check('a key can be saved', code, 200)
check('trimmed', opts.data[KEY], SECRET)
text = client.get('/model-manager/settings').text
check('and it is never sent back', SECRET in text, False)
check('only that there is one', get()['settings'][KEY], {
    'label': 'Civitai API Key', 'info': s[KEY]['info'], 'kind': 'secret', 'default': '',
    'has_value': True})
check('not even in the answer to the save', SECRET in json.dumps(answer), False)
code, answer = post({KEY: ''})
check('and an empty one removes it', (opts.data[KEY], answer['settings'][KEY]['has_value']), ('', False))

# ------------------------------------------------------------------- checking
before = dict(opts.data)
saves = opts.saves
code, answer = post({
    'model_manager_page_size': 25,                        # fine
    'model_manager_civitai_page_size': 55,                # over the slider's maximum
    'model_manager_card_size': 'big',                     # not a size
    'model_manager_nsfw_detection': 'guess',              # not a choice
    'model_manager_gallery_hide_nsfw': 'yes',             # not on or off
    'sd_model_checkpoint': 'y',                           # not ours
})
check('a save with a bad value is refused', (code, answer.get('success')), (400, False))
check('naming each bad value', sorted(answer.get('errors', {})), sorted([
    'model_manager_civitai_page_size', 'model_manager_card_size',
    'model_manager_nsfw_detection', 'model_manager_gallery_hide_nsfw', 'sd_model_checkpoint']))
check('and nothing is saved - not even the good one', (opts.data, opts.saves), (before, saves))

# --------------------------------------------------------------------- saving
code, answer = post({'model_manager_page_size': 30.0, 'model_manager_card_size': ' 240 X 320 ',
                     'model_manager_nsfw_prompt_model_percent': 2.5})
check('a good save succeeds', code, 200)
check('saying what changed', sorted(answer['changed']), sorted([
    'model_manager_page_size', 'model_manager_card_size', 'model_manager_nsfw_prompt_model_percent']))
check('a whole number stays an int, as the slider has it',
      (opts.data['model_manager_page_size'], type(opts.data['model_manager_page_size'])), (30, int))
check('a card size is written as the Settings page would read it', opts.data['model_manager_card_size'], '240x320')
check('a fraction stays one', opts.data['model_manager_nsfw_prompt_model_percent'], 2.5)
check('the settings file is written', json.load(open(CONFIG))['model_manager_page_size'], 30)
check('and the answer carries the new values', answer['settings']['model_manager_page_size']['value'], 30)
check('through opts.set: onchange ran for the NSFW setting', len(restamps), 1)

saves = opts.saves
code, answer = post({'model_manager_page_size': 30})
check('saving what is already there changes nothing', answer['changed'], [])
check('and does not write the file', opts.saves, saves)

restamps.clear()
post({'model_manager_nsfw_detection': 'words'})
check('changing the detection judges stored images again', len(restamps), 1)

# ---------------------------------------------------------------- testing a key
# A stand-in for Civitai's /me: one key it takes, one it refuses, and one for
# which it cannot be reached. What each client was made with is noted - the
# key, and whether it would retry.
from model_manager.civitai import CivitaiAPIError, CivitaiAuthError, CivitaiClient   # noqa: E402

tried = []


def whoami(self):
    tried.append((self.api_key, self.MAX_RETRIES))
    if self.api_key == 'good-key':
        return {'username': 'someone', 'tier': 'free'}
    if self.api_key == 'down-key':
        raise CivitaiAPIError('Connection error: no route to host')
    raise CivitaiAuthError(401)


CivitaiClient.whoami = whoami


def test(**body):
    r = client.post('/model-manager/settings/test-key', json=body)
    return r.status_code, r.json(), r.text


opts.data[KEY] = 'good-key'
code, answer, text = test()
check('with nothing typed, the saved key is tested',
      (code, answer.get('result'), answer.get('which'), tried[-1][0]), (200, 'works', 'saved', 'good-key'))
check('and who it belongs to is said', answer.get('username'), 'someone')
check('asked once, not with retries: someone is waiting', tried[-1][1], 0)
check('the key is not in the answer', 'good-key' in text, False)

code, answer, text = test(key='  bad-key  ')
check('a key typed in the window is tested instead, trimmed, before it is saved',
      (answer.get('result'), answer.get('which'), tried[-1][0]), ('refused', 'typed', 'bad-key'))
check('and is not in the answer either', 'bad-key' in text, False)
check('nor saved by being tested', opts.data[KEY], 'good-key')

code, answer, text = test(key='down-key')
check('Civitai not answering is not a refused key',
      (answer.get('result'), answer.get('error')), ('unreachable', 'Connection error: no route to host'))

tried.clear()
check('an empty key is not sent to Civitai', (test(key='')[1].get('result'), tried), ('none', []))
opts.data[KEY] = ''
check('nor is no saved key', (test()[1].get('result'), tried), ('none', []))

# ------------------------------------------------------------- folder template
def example(template):
    return client.get('/model-manager/settings/folder-example', params={'template': template}).json()

got = example('_{baseModel}/{modelName}')
check('a template is shown filled in, by the code a download uses',
      got['subfolder'].replace('\\', '/'), '_SDXL_1.0/Example_Model')
check('with nothing unknown', got['unknown'], [])
check('a placeholder a download would not fill is named',
      example('{basemodel}/{modelName}')['unknown'], ['{basemodel}'])
check('an empty template files a model straight in its type\'s folder', example('')['subfolder'], '')

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
