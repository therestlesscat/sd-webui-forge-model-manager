"""
The settings window's stand-in answer for the browser suites (#320).

The window draws every setting from what the server says - its group, name,
tab heading, tags, badges and the switch it sits under - so a suite that
makes up that answer by hand tests a window no server would draw. This
writes the real one, at every default: every setting registered as Forge
registers it (ui/settings.on_ui_settings, against stand-ins for Forge's
option types, as settings_api_test does), then api.settings.described().

Run by hand, with the WebUI's Python, after a setting is added or changed:

    python tools/settings_answer.py

It writes tests/js/settings_answer.json; tests/py/settings_registry_test.py
fails while that file says something else.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
OUT = os.path.join(TESTS, "js", "settings_answer.json")


class OptionInfo(object):
    def __init__(self, default=None, label="", component=None, component_args=None, onchange=None,
                 section=None, refresh=None, comment_before="", comment_after="", infotext=None,
                 restrict_api=False, category_id=None):
        self.default, self.label, self.component = default, label, component
        self.component_args, self.onchange, self.section = component_args, onchange, section
        self.category_id, self.do_not_save = category_id, False
        self.comment_before, self.comment_after = comment_before, comment_after

    def info(self, info):
        self.comment_after += "<span class='info'>(%s)</span>" % info
        return self


class OptionHTML(OptionInfo):
    def __init__(self, text):
        super().__init__(str(text).strip(), label="")
        self.do_not_save = True


class Options(object):
    def __init__(self):
        object.__setattr__(self, "data", {})
        object.__setattr__(self, "data_labels", {})

    def __getattr__(self, key):
        if key in self.data:
            return self.data[key]
        if key in self.data_labels:
            return self.data_labels[key].default
        raise AttributeError(key)

    def add_option(self, key, info):
        self.data_labels[key] = info
        if key not in self.data and not info.do_not_save:
            self.data[key] = info.default


def build():
    """The answer, as the server would give it with every setting at its default."""
    for path in (ROOT, TESTS):
        if path not in sys.path:
            sys.path.insert(0, path)
    import webui_stub
    webui_stub.install()
    from modules import shared
    shared.opts, shared.OptionInfo, shared.OptionHTML = Options(), OptionInfo, OptionHTML
    from model_manager.ui import settings as ui_settings
    from model_manager.api import settings as api_settings
    ui_settings.on_ui_settings()
    return api_settings.described()


def text(answer):
    return json.dumps(answer, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


if __name__ == "__main__":
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text(build()))
    print("wrote", OUT)
