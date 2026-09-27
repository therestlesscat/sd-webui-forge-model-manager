"""
The settings window's two endpoints: what the settings are, and saving them.

The settings themselves are the WebUI's, registered in ui/settings.py and kept
in shared.opts. The window is a second way to edit them, not a copy: what it
shows is read from the WebUI's own registry - label, help text, default, range
- and a save goes through opts.set() and opts.save(), as the Settings page's
does, so onchange still runs (the NSFW settings judge stored images again).

The API key is never sent to the page. It says only whether one is set, and a
key typed into the window replaces it.
"""
import html
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

SECTION_ID = "model_manager"
SECRET = "model_manager_civitai_api_key"
DATABASE_PATH = "model_manager_database_path"

# Values the type alone does not check. "200x280", and nothing else, is a card
# size: anything else was read as the default without a word.
_CARD_SIZE = re.compile(r"^\s*\d{2,4}\s*[xX]\s*\d{2,4}\s*$")
_FORMATS = {
    "model_manager_card_size": (_CARD_SIZE, "a size such as 200x280"),
    "model_manager_civitai_card_size": (_CARD_SIZE, "a size such as 200x280"),
}

_TAG = re.compile(r"<[^>]+>")


def _plain(markup: str) -> str:
    """The help text the Settings page shows, without its markup or brackets."""
    text = html.unescape(_TAG.sub("", markup or "")).strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text


def _kind(info) -> Tuple[str, Dict[str, Any]]:
    """
    What sort of control a setting is, and what bounds it, from the component
    the Settings page draws it with.
    """
    args = info.component_args
    if callable(args):
        args = args()
    args = dict(args or {})
    name = getattr(info.component, "__name__", "") if info.component else ""

    if name == "Checkbox" or (not name and isinstance(info.default, bool)):
        return "bool", {}
    if name == "Radio":
        choices = [list(c) if isinstance(c, (tuple, list)) else [str(c), c]
                   for c in args.get("choices", [])]
        return "choice", {"choices": choices}
    if name in ("Slider", "Number") or (not name and isinstance(info.default, (int, float))):
        bounds = {k: args[k] for k in ("minimum", "maximum", "step") if k in args}
        return "number", bounds
    if args.get("type") == "password":
        return "secret", {}
    extra = {"lines": int(args["lines"])} if args.get("lines") else {}
    if args.get("placeholder"):
        extra["placeholder"] = args["placeholder"]
    return "text", extra


def _ours() -> List[Tuple[str, Any]]:
    """This extension's settings, in the order they were registered."""
    from modules import shared
    found = []
    for key, info in shared.opts.data_labels.items():
        section = getattr(info, "section", None) or ()
        if not section or section[0] != SECTION_ID or getattr(info, "do_not_save", False):
            continue
        found.append((key, info))
    return found


def _describe() -> Dict[str, Any]:
    from modules import shared
    settings = {}
    for key, info in _ours():
        kind, extra = _kind(info)
        value = getattr(shared.opts, key, info.default)
        entry = {"label": info.label, "info": _plain(getattr(info, "comment_after", "")),
                 "kind": kind, "default": info.default, **extra}
        if kind == "secret":
            entry["has_value"] = bool(str(value or "").strip())
            entry["default"] = ""
        else:
            entry["value"] = value
        settings[key] = entry

    answer = {"success": True, "settings": settings, "order": list(settings)}
    # The file in use now. The setting names the one the next start will
    # open; the window says so when the two differ.
    try:
        from ..db import get_models_db
        answer["database_in_use"] = get_models_db().db_path
    except Exception:
        answer["database_in_use"] = None
    # How many words ship with the extension, for "these add to N".
    try:
        from .. import nsfw
        with open(nsfw.PROMPT_WORDS_FILE, encoding="utf-8") as f:
            answer["bundled_nsfw_words"] = len(nsfw.parse_words(f.read()))
    except Exception:
        answer["bundled_nsfw_words"] = None
    return answer


def check_value(key: str, info, value: Any) -> Tuple[Optional[str], Any]:
    """
    Whether a value may be saved to a setting, as the Settings page would
    have it and a little stricter: in range, one of the choices, in format.

    Returns:
        (the reason it may not, None) or (None, the value to save).
    """
    kind, extra = _kind(info)
    if kind == "bool":
        if not isinstance(value, bool):
            return "must be on or off", None
        return None, value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "must be a number", None
        if "minimum" in extra and value < extra["minimum"]:
            return "must be at least %g" % extra["minimum"], None
        if "maximum" in extra and value > extra["maximum"]:
            return "must be at most %g" % extra["maximum"], None
        # An int setting stays an int: the Settings page's slider would
        # otherwise read 20.0 back.
        if isinstance(info.default, int) and float(value).is_integer():
            value = int(value)
        return None, value
    if kind == "choice":
        allowed = [c[1] for c in extra["choices"]]
        if value not in allowed:
            return "must be one of %s" % ", ".join(map(str, allowed)), None
        return None, value
    if not isinstance(value, str):
        return "must be text", None
    if kind == "secret":
        value = value.strip()
    rule = _FORMATS.get(key)
    if rule and value.strip() and not rule[0].match(value):
        return "must be %s" % rule[1], None
    if rule:
        value = value.strip().lower().replace(" ", "")
    return None, value


def save(values: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check every value first, then set them all and write the file - so a save
    is all or nothing, as the dialog presents it.
    """
    from modules import shared
    ours = dict(_ours())
    errors, checked = {}, {}
    for key, value in (values or {}).items():
        info = ours.get(key)
        if info is None:
            errors[key] = "is not a Model Manager setting"
            continue
        reason, value = check_value(key, info, value)
        if reason:
            errors[key] = reason
        else:
            checked[key] = value
    if errors:
        return {"success": False, "errors": errors}

    changed = [key for key, value in checked.items() if shared.opts.set(key, value)]
    if changed:
        shared.opts.save(shared.config_filename)
    answer = _describe()
    answer["changed"] = changed
    return answer


# A model to show a folder template with. Not a real one: the window says
# what a download would be filed under, and any name shows that.
_SAMPLE_MODEL = {"name": "Example Model", "id": 12345, "creator": {"username": "someone"}}
_SAMPLE_VERSION = {"baseModel": "SDXL 1.0"}
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def folder_example(template: str) -> Dict[str, Any]:
    """
    Where a download of the sample model would go under a template, by the
    code a download uses - and any placeholder it does not know, which a
    download would leave in the path as written.
    """
    from ..download_service import DownloadService
    # apply_folder_template reads nothing from the service; it is a method
    # only by where it lives, and a service would start its workers.
    subfolder = DownloadService.apply_folder_template(
        None, template or "", _SAMPLE_MODEL, _SAMPLE_VERSION)
    return {"success": True, "subfolder": subfolder,
            "unknown": sorted(set(_PLACEHOLDER.findall(subfolder)))}


def modules_table(drafts: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    The settings window's text encoder and VAE table: forge_modules'
    description of each preset this WebUI has, from what is installed and
    the settings - or, for a preset in `drafts`, the text the window holds.
    """
    from modules import shared
    from ..forge_modules import (SETTING_PREFIX, available_presets, classify_file,
                                 describe_presets, installed_modules)
    modules = {label: classify_file(path) for label, path in installed_modules().items()}
    texts = {}
    for key, _ in _ours():
        if key.startswith(SETTING_PREFIX):
            preset = key[len(SETTING_PREFIX):]
            texts[preset] = str(getattr(shared.opts, key, "") or "")
    texts.update(drafts or {})
    return {"success": True, "presets": describe_presets(available_presets(), modules, texts)}


def register(app: FastAPI):
    """Attach this module's endpoints to the app."""
    @app.get("/model-manager/settings")
    async def get_settings():
        """Every Model Manager setting: its value, default, label and bounds."""
        try:
            return JSONResponse(_describe())
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/settings/folder-example")
    async def get_folder_example(template: str = ""):
        """Where the sample model would be filed under a folder template."""
        try:
            return JSONResponse(folder_example(template))
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/settings/modules")
    def get_modules_table(drafts: str = ""):
        """
        Each preset's text encoders and VAE: what is installed, what would be
        picked, what the settings name. A plain `def`: it reads file headers.
        `drafts` is a JSON object of preset -> setting text, to describe
        instead of what is saved.
        """
        try:
            return JSONResponse(modules_table(json.loads(drafts) if drafts else None))
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.post("/model-manager/settings")
    async def save_settings(values: Dict[str, Any] = Body(..., embed=True)):
        """Save the settings given, all or none; answers what they are now."""
        try:
            answer = save(values)
            return JSONResponse(answer, status_code=200 if answer["success"] else 400)
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)
