"""
The settings window's endpoints: what the settings are, and saving them; and
the database file's space and backups, which it shows under Database file
(#287).

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
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse
from .common import failed, gate

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
    # A dropdown is drawn as the radios are: Sync images' level was a text
    # box in the settings window, taking any word (#233).
    if name in ("Radio", "Dropdown"):
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
    """This extension's settings Forge holds, in the registry's order (#320)."""
    from ..forge_host import registered_options
    from ..settings_registry import all_settings
    options = registered_options()
    return [(s.key, options[s.key]) for s in all_settings()
            if s.key in options and not getattr(options[s.key], "do_not_save", False)]


def _placed(s) -> Dict[str, Any]:
    """Where the window draws a setting, and what it calls it (#320): from the registry."""
    return {"name": s.name, "group": s.group, "heading": s.heading, "tags": list(s.tags),
            "shown_with": list(s.shown_with), "under": list(s.under) if s.under else None,
            "badges": list(s.badges), "switch": list(s.switch) if s.switch else None}


def described() -> Dict[str, Any]:
    """
    Every setting as the settings window draws it, with the groups and the
    words for its tags and badges: what the window is told, but the files in
    use. The suites' stand-in answer is made from it (tools/settings_answer.py).
    """
    from ..forge_host import setting
    from ..settings_registry import BADGES, GROUPS, TAG_LABELS, by_key
    registry = by_key()
    settings = {}
    for key, info in _ours():
        kind, extra = _kind(info)
        value = setting(key)
        entry = {"label": info.label, "info": _plain(getattr(info, "comment_after", "")),
                 "kind": kind, "default": info.default, **extra, **_placed(registry[key])}
        if kind == "secret":
            entry["has_value"] = bool(str(value or "").strip())
            entry["default"] = ""
        else:
            entry["value"] = value
        settings[key] = entry
    return {"settings": settings, "order": list(settings),
            "groups": [{"id": g.id, "label": g.label} for g in GROUPS],
            "tag_labels": TAG_LABELS, "badge_labels": BADGES}


def _describe() -> Dict[str, Any]:
    answer = {"success": True, **described()}
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


def _database_path_reason(path: str) -> Optional[str]:
    """
    Why a database file may not be saved (#136): empty is the extension's
    own; else a file's whole path, in a folder that is there. The window's
    "In use: F:\\..." line, pasted with a path, was saved - and the next
    start would have opened no database at all.
    """
    if not path:
        return None
    if not os.path.isabs(path):
        return "must be a file's whole path, such as F:\\models\\models.db"
    if os.path.isdir(path):
        return "must be a file, not a folder"
    if not os.path.isdir(os.path.dirname(path)):
        return "must be in a folder that is there"
    return None


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
    if key == "model_manager_database_path":
        value = value.strip()
        reason = _database_path_reason(value)
        if reason:
            return reason, None
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
    from ..forge_host import store_settings
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

    changed = store_settings(checked)
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
    from ..download_service import apply_folder_template
    subfolder = apply_folder_template(template or "", _SAMPLE_MODEL, _SAMPLE_VERSION)
    return {"success": True, "subfolder": subfolder,
            "unknown": sorted(set(_PLACEHOLDER.findall(subfolder)))}


def modules_table(drafts: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    The settings window's text encoder and VAE table: forge_modules'
    description of each preset this WebUI has, from what is installed and
    the settings - or, for a preset in `drafts`, the text the window holds.
    """
    from ..file_identity import classify_file
    from ..forge_host import available_presets, installed_modules, setting
    from ..forge_modules import SETTING_PREFIX, describe_presets
    modules = {label: classify_file(path) for label, path in installed_modules().items()}
    texts = {}
    for key, _ in _ours():
        if key.startswith(SETTING_PREFIX):
            preset = key[len(SETTING_PREFIX):]
            texts[preset] = str(setting(key) or "")
    texts.update(drafts or {})
    return {"success": True, "presets": describe_presets(available_presets(), modules, texts)}


def test_key(typed: Optional[str] = None) -> Dict[str, Any]:
    """
    Whether Civitai takes an API key: the one typed into the window if there
    is one, so it can be tried before it is saved, else the saved one. The
    key is never part of the answer.

    Returns:
        result: "works" (with the username, where Civitai gives one),
        "refused", "unreachable" (with why), or "none" - no key to test.
        which: "typed" or "saved".
    """
    from ..civitai import CivitaiAPIError, CivitaiAuthError, CivitaiClient, api_key_from_settings

    which = "typed" if typed is not None else "saved"
    key = typed.strip() if typed is not None else (api_key_from_settings() or "")
    if not key:
        return {"success": True, "result": "none", "which": which}

    client = CivitaiClient(key)
    # One try, and not for long: someone is waiting on the answer, and a
    # refused key is refused however often it is asked.
    client.MAX_RETRIES = 0
    client.REQUEST_TIMEOUT = 15
    client.wait_on_rate_limit = False
    try:
        account = client.whoami()
    except CivitaiAuthError:
        return {"success": True, "result": "refused", "which": which}
    except CivitaiAPIError as e:
        return {"success": True, "result": "unreachable", "error": str(e), "which": which}
    username = account.get("username") if isinstance(account, dict) else None
    return {"success": True, "result": "works", "username": username, "which": which}


# A tab's saved search - its filters, as the tab reads and fills them - kept
# in the database: the same in every browser, and in both WebUIs when they
# share it. The tabs' Save Search buttons; one each.
SAVED_SEARCH_TABS = ("model_manager", "civitai_browser")
_SAVED_SEARCH_LIMIT = 20000       # characters: a set of filters, not a store


def _saved_search_key(tab: str) -> str:
    return f"saved_search:{tab}"


def register(app: FastAPI):
    """Attach this module's endpoints to the app."""
    @app.get("/model-manager/saved-search")
    @gate("saved_search")
    def get_saved_search(tab: str = ""):
        """A tab's saved search: `filters`, or null when none is saved."""
        if tab not in SAVED_SEARCH_TABS:
            return JSONResponse({"success": False, "error": f"no saved search for {tab!r}"}, status_code=400)
        from ..db import get_models_db
        raw = get_models_db().get_info(_saved_search_key(tab))
        try:
            filters = json.loads(raw) if raw else None
        except ValueError:
            filters = None
        return JSONResponse({"success": True, "filters": filters if isinstance(filters, dict) else None})

    @app.post("/model-manager/saved-search")
    @gate("saved_search")
    def set_saved_search(body: Dict[str, Any] = Body(...)):
        """Save a tab's search - {tab, filters} - or forget it, with filters null."""
        tab = body.get("tab")
        filters = body.get("filters")
        if tab not in SAVED_SEARCH_TABS:
            return JSONResponse({"success": False, "error": f"no saved search for {tab!r}"}, status_code=400)
        if filters is not None and not isinstance(filters, dict):
            return JSONResponse({"success": False, "error": "filters must be an object, or null"}, status_code=400)
        value = json.dumps(filters) if filters is not None else None
        if value is not None and len(value) > _SAVED_SEARCH_LIMIT:
            return JSONResponse({"success": False, "error": "too large for a saved search"}, status_code=400)
        from ..db import get_models_db
        get_models_db().set_info(_saved_search_key(tab), value)
        return JSONResponse({"success": True})

    @app.get("/model-manager/settings")
    @gate("any")
    def get_settings():
        """Every Model Manager setting: its value, default, label and bounds."""
        try:
            return JSONResponse(_describe())
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/settings/folder-example")
    @gate("any")
    async def get_folder_example(template: str = ""):
        """Where the sample model would be filed under a folder template."""
        try:
            return JSONResponse(folder_example(template))
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/settings/modules")
    @gate("any")
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

    @app.post("/model-manager/settings/test-key")
    @gate("any")
    def post_test_key(key: Optional[str] = Body(None, embed=True)):
        """
        Ask Civitai whether a key works. A plain `def`: it waits on Civitai.
        With no `key`, the saved one is tested.
        """
        try:
            return JSONResponse(test_key(key))
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/settings/nsfw-levels")
    @gate("any")
    async def get_nsfw_levels():
        """How far judging the stored images again has got, after a change
        to how they are judged. See prompt_levels.progress()."""
        from ..prompt_levels import progress
        return JSONResponse({"success": True, **progress()})

    @app.post("/model-manager/settings")
    @gate("any")
    def save_settings(values: Dict[str, Any] = Body(..., embed=True)):
        """Save the settings given, all or none; answers what they are now."""
        try:
            answer = save(values)
            return JSONResponse(answer, status_code=200 if answer["success"] else 400)
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    # ------------------------------------------- the database file (#287)

    @app.get("/model-manager/database/space")
    @gate("any")
    def database_space():
        """
        The database in use: its size, the space no row uses, what would stop
        a compact, the running or last compact, and the backups beside it.
        """
        from ..db import upkeep
        try:
            return JSONResponse({"success": True, **upkeep.space(upkeep.in_use())})
        except Exception as e:
            return failed(e, "Reading the database's space")

    @app.post("/model-manager/database/compact")
    @gate("any")
    def database_compact():
        """Start a compact of the database in use; 409 with why when it cannot."""
        from ..db import upkeep
        try:
            reason = upkeep.start(upkeep.in_use())
        except Exception as e:
            return failed(e, "Starting a compact")
        if reason:
            return JSONResponse({"success": False, "error": reason}, status_code=409)
        return JSONResponse({"success": True, "compact": upkeep.progress()})

    @app.get("/model-manager/database/compact")
    @gate("any")
    def database_compact_progress():
        """The running or last compact's progress, for the window's poll; null before any."""
        from ..db import upkeep
        return JSONResponse({"success": True, "compact": upkeep.progress()})

    @app.post("/model-manager/database/compact/cancel")
    @gate("any")
    def database_compact_cancel():
        """Interrupt the running compact: the database stays as it was."""
        from ..db import upkeep
        if not upkeep.cancel():
            return JSONResponse({"success": False, "error": "No compact is running."}, status_code=409)
        return JSONResponse({"success": True})

    @app.post("/model-manager/database/backups/delete")
    @gate("any")
    def database_backups_delete(names: List[str] = Body(..., embed=True)):
        """Delete backups beside the database, by their names alone; each name's end."""
        from ..db import upkeep
        try:
            answer = upkeep.delete_backups(upkeep.in_use(), names)
        except Exception as e:
            return failed(e, "Deleting database backups")
        return JSONResponse(answer, status_code=200 if answer["success"] else 409)
