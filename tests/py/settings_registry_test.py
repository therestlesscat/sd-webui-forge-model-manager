"""
Every setting declared once (#320): model_manager/settings_registry.py.

- the registry holds every setting Forge is given, each whole: a group, both
  names, a description, tags, a default from DEFAULTS, a switch it sits under
  that is a setting;
- every name keeps the naming rules, and each rule broken once is caught;
- Forge's page gets each in its group's section, under the Model Manager
  category, by its page name and description;
- saved values come through registration as they were, every choice's among
  its choices;
- the browser suites' stand-in answer (tests/js/settings_answer.json) is the
  registry's as it is now.
"""
import os
import sys
import types
from dataclasses import replace

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS, os.path.join(ROOT, 'tools')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()
try:
    import gradio                                       # noqa: F401
except ImportError:
    print('gradio is not installed; run this with the WebUI\'s python')
    sys.exit(0)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ------------------------------------------- the stand-in answer is current
# First, before anything here changes the stand-in WebUI.
import settings_answer                                   # noqa: E402  (tools/)
with open(settings_answer.OUT, encoding='utf-8') as f:
    on_disk = f.read()
check('tests/js/settings_answer.json is the registry\'s answer now - else run tools/settings_answer.py',
      on_disk == settings_answer.text(settings_answer.build()), True)

from model_manager import settings_registry as reg        # noqa: E402
from model_manager.forge_host import DEFAULTS             # noqa: E402

# ------------------------------------------------------------ the registry
settings = reg.all_settings()
keys = [s.key for s in settings]
HIDDEN = {'model_manager_image_folders', 'model_manager_image_folders_off'}    # Sync images' own lists
check('every setting with a default is in the registry, but the two Sync images keeps out of every page',
      sorted(set(DEFAULTS) - set(keys)), sorted(HIDDEN))
check('and the registry holds no other', sorted(set(keys) - set(DEFAULTS)), [])
check('each once', len(keys), len(set(keys)))
group_ids = [g.id for g in reg.GROUPS]
check('each in a group the window has', [s.key for s in settings if s.group not in group_ids], [])
check('every group holds a setting', sorted({s.group for s in settings}), sorted(group_ids))
check('each with both names', [s.key for s in settings if not s.name or not s.page_name], [])
check('each with a description, but the presets, whose Forge builds from forge_modules',
      [s.key for s in settings if not s.description and not s.key.startswith('model_manager_modules_')], [])
check('each with a control Forge has', sorted({s.control for s in settings}),
      sorted(['checkbox', 'slider', 'number', 'dropdown', 'radio', 'textbox', 'password']))
check('each tagged with the tabs it acts in, by their ids',
      [s.key for s in settings if not s.tags or set(s.tags) - set(reg.TAG_LABELS)], [])
check('a setting it sits under is a setting', [s.key for s in settings if s.under and s.under[0] not in keys], [])
check('badges the window knows', [s.key for s in settings if set(s.badges) - set(reg.BADGES)], [])
choice_values = {s.key: [c[1] if isinstance(c, (tuple, list)) else c for c in s.args.get('choices', ())]
                 for s in settings}
check('a choice drawn as a switch: its two values are its choices',
      [s.key for s in settings if s.switch and list(s.switch) != choice_values[s.key]], [])
check('a value a setting sits under is one of that setting\'s, or on',
      [s.key for s in settings if s.under and s.under[1] is not True
       and s.under[1] not in choice_values[s.under[0]]], [])
check('defaults are DEFAULTS\', and a choice\'s among its choices',
      [s.key for s in settings if choice_values[s.key] and DEFAULTS[s.key] not in choice_values[s.key]], [])
check('the window\'s headings: one tab, its own; several, shared',
      [reg.by_key()[k].heading for k in ('model_manager_page_size', 'model_manager_card_videos_play',
                                         'model_manager_send_clip_skip')],
      ['Model Manager Tab', 'Shared across tabs', 'Shared across tabs'])

# ----------------------------------------------------------- the naming rules
check('every name keeps the rules', [p for s in settings for p in reg.naming_problems(s)], [])
base = reg.by_key()['model_manager_page_size']
BREAKS = {
    'a prefix': replace(base, name='Model Manager: models per page'),
    'a parenthesis': replace(base, page_name='Card size (WIDTHxHEIGHT)'),
    'Title Case': replace(base, name='Models Per Page'),
    'a tab named without "Tab"': replace(base, page_name='Models per page in the Model Manager tab'),
    'a window name over 65 characters': replace(base, name='Models per page ' + 'x' * 55),
    'a page name over 60 characters': replace(base, page_name='Models per page in the Model Manager Tab ' + 'x' * 30),
}
for rule, broken in BREAKS.items():
    check('the naming check catches %s' % rule, bool(reg.naming_problems(broken)), True)
check('and passes a name of its own inside one: "Clip skip", "Send", a tab', reg.naming_problems(
    replace(base, name='Highest Clip skip', page_name='Highest Clip skip Send takes in the Queue Tab')), [])

# -------------------------------------------------------------- Forge's page
from modules import shared                               # noqa: E402  (the stub's)


class Info(object):
    def __init__(self, default=None, label='', component=None, component_args=None, onchange=None,
                 section=None, category_id=None, **kwargs):
        self.default, self.label, self.component, self.component_args = default, label, component, component_args
        self.section, self.category_id, self.onchange, self.text = section, category_id, onchange, ''

    def info(self, text):
        self.text = text
        return self


class Html(Info):
    def __init__(self, text):
        super().__init__(text)


class Registry(object):
    def __init__(self, data=None):
        self.data, self.options = dict(data or {}), {}

    def add_option(self, key, info):
        self.options[key] = info
        self.data.setdefault(key, info.default)


registered_categories = []
fake_options = types.ModuleType('modules.options')
fake_options.categories = types.SimpleNamespace(register_category=lambda *a: registered_categories.append(a))
from model_manager.ui import settings as ui_settings     # noqa: E402


def register(data=None):
    registry = Registry(data)
    saved = shared.opts, getattr(shared, 'OptionInfo', None), getattr(shared, 'OptionHTML', None)
    shared.opts, shared.OptionInfo, shared.OptionHTML = registry, Info, Html
    sys.modules['modules.options'] = fake_options
    try:
        ui_settings.on_ui_settings()
    finally:
        shared.opts, shared.OptionInfo, shared.OptionHTML = saved
        sys.modules.pop('modules.options', None)
    return registry


page = register()
check('the Model Manager category is registered', registered_categories, [reg.CATEGORY])
check('every setting, in the registry\'s order', [k for k in page.options if k in keys], keys)
check('each in its group\'s section, under the category',
      [k for k in keys if (page.options[k].section, page.options[k].category_id)
       != (reg.section(reg.by_key()[k]), 'model_manager')], [])
check('ten sections, one per group', len({page.options[k].section for k in keys}), len(reg.GROUPS))
check('each by its page name', [k for k in keys if page.options[k].label != reg.by_key()[k].page_name], [])
check('with its description', [k for k in keys if not k.startswith('model_manager_modules_')
                               and page.options[k].text != reg.by_key()[k].description], [])
check('a choice in words, saved by its value', page.options['model_manager_generations_grid'].component_args['choices'],
      [('Smooth: only nearby tiles', 'Fast'), ('Keep every tile', 'Classic')])
check('the presets\' explanation heads Send\'s section', (
    page.options['model_manager_modules_explanation'].section,
    list(page.options).index('model_manager_modules_explanation')
    < list(page.options).index('model_manager_modules_flux')), (reg.section(reg.by_key()['model_manager_send_clip_skip']), True))
check('Sync images\' folder lists kept out of every page', [page.options[k].section for k in sorted(HIDDEN)],
      [(None, 'Model Manager')] * 2)
check('the change hooks follow their settings', sorted(k for k in keys if page.options[k].onchange),
      sorted(['model_manager_queue_enabled', 'model_manager_downloads_at_once', 'model_manager_check_updates',
              'model_manager_nsfw_prompt_words', 'model_manager_nsfw_detection',
              'model_manager_nsfw_prompt_model_percent']))

# ------------------------------------------------------------- saved values
# A config.json with every setting saved, each away from its default where it
# can be: registration reads it, and changes none of it.
def other(s):
    d = DEFAULTS[s.key]
    if isinstance(d, bool):
        return not d
    if choice_values[s.key]:
        return next((v for v in choice_values[s.key] if v != d), d)
    if isinstance(d, (int, float)):
        return d + 1 if s.args.get('maximum') is None or d + 1 <= s.args['maximum'] else d - 1
    return d + 'x' if isinstance(d, str) else d


saved_config = {s.key: other(s) for s in settings}
after = register(saved_config).data
check('every saved value read as it was saved', [k for k in keys if after[k] != saved_config[k]], [])
check('every saved choice is one of its choices',
      [k for k in keys if choice_values[k] and after[k] not in choice_values[k]], [])

# ------------------------------------------------- links into the window
# Every group and setting the page opens the window at - a link's
# data-section or data-focus, a call's section or focus, a note's section, a
# setting a text links to - is the registry's. 0.68.0 renamed the groups, and
# three links in the tabs' markup kept the old ids: they opened nothing (#320).
import glob                                             # noqa: E402
import re                                               # noqa: E402

NAMED = [(r'data-section="([a-z_]+)"', 'group'), (r'data-focus="([a-z_]+)"', 'key'),
         (r"settings\.open', \{[^}]*\bsection: '([a-z_]+)'", 'group'),
         (r"settings\.open', \{[^}]*\bfocus: '([a-z_]+)'", 'key'),
         (r'"section": "([a-z_]+)"', 'group'), (r"settingLink\('([a-z_]+)'", 'key'),
         (r"_SETTING = '([a-z_]+)'", 'key')]
sources = sorted(glob.glob(os.path.join(ROOT, 'model_manager', 'ui', '*.py'))
                 + glob.glob(os.path.join(ROOT, 'javascript', '**', '*.mjs'), recursive=True)
                 + [os.path.join(ROOT, 'model_manager', 'data', 'release_notes.json')])
named, unknown = 0, []
for path in sources:
    with open(path, encoding='utf-8') as f:
        text = f.read()
    for pattern, kind in NAMED:
        for value in re.findall(pattern, text):
            named += 1
            if value not in (group_ids if kind == 'group' else keys):
                unknown.append('%s: %s %s' % (os.path.relpath(path, ROOT), kind, value))
check('every group and setting a link or a note opens the window at is the registry\'s', unknown, [])
check('and the search found them: the three banners\' links, the notes, the links in text', named > 30, True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
