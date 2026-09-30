"""
Whether a newer version of the extension is out.

The repository's version.json says which version is current: data, not code.
It is read as JSON and nothing in it is run. It is asked of this copy's own
branch - dev, rc - since that is what the WebUI's "Check for updates" pulls;
a copy without git, or on a branch GitHub does not have, asks the default
branch. Once after the WebUI starts, then every 12 hours, and at once when
"Check for a new version" is turned on; while it is off, GitHub is asked
nothing. Offline, or on any failure, nothing is said beyond one line.

version.json holds {"version": "0.41.11", "note": ""}. The note is for later:
kept, not shown.
"""
import json
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

from .version import REPOSITORY, VERSION, _git

SETTING = "model_manager_check_updates"
INTERVAL = 12 * 60 * 60
THREAD_NAME = "model-manager-update-check"
_MAX_BYTES = 64 * 1024

_lock = threading.Lock()
_latest: Dict[str, object] = {"version": None, "note": "", "ref": None}


def parse_version(text) -> Optional[Tuple[int, ...]]:
    """(0, 41, 11) from "0.41.11"; None for anything that is not MAJOR.MINOR.PATCH."""
    parts = str(text or "").strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def is_newer(latest, current=VERSION) -> bool:
    """Whether `latest` is a later version than `current` - as numbers: 0.41.10 is after 0.41.9."""
    a, b = parse_version(latest), parse_version(current)
    return bool(a and b and a > b)


def enabled() -> bool:
    try:
        from modules import shared
        return bool(getattr(shared.opts, SETTING, True))
    except Exception:
        return True


def branches() -> List[str]:
    """The refs to ask, in order: the branch this copy pulls from, then the default branch."""
    refs = []
    upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream and "/" in upstream:
        refs.append(upstream.split("/", 1)[1])
    else:
        local = _git("rev-parse", "--abbrev-ref", "HEAD")
        if local and local != "HEAD":
            refs.append(local)
    refs.append("HEAD")
    return list(dict.fromkeys(refs))


def url_for(ref: str) -> str:
    return f"{REPOSITORY}/raw/{ref}/version.json"


def fetch(ref: str, opener: Callable = urllib.request.urlopen) -> Dict[str, object]:
    """version.json on `ref`, checked to hold a version; raises on anything else."""
    with opener(url_for(ref), timeout=10) as response:
        data = json.loads(response.read(_MAX_BYTES).decode("utf-8"))
    if not isinstance(data, dict) or parse_version(data.get("version")) is None:
        raise ValueError("version.json holds no version")
    note = data.get("note")
    return {"version": str(data["version"]).strip(), "note": note if isinstance(note, str) else ""}


def check_once(opener: Callable = urllib.request.urlopen) -> Optional[Dict[str, object]]:
    """Ask GitHub, unless the setting is off; what it said, or None."""
    if not enabled():
        return None
    for ref in branches():
        try:
            found = fetch(ref, opener)
        except urllib.error.HTTPError as e:
            if e.code == 404:          # a branch GitHub does not have: the default one
                continue
            print(f"[ModelManager] Could not check for a new version: {e}")
            return None
        except Exception as e:
            print(f"[ModelManager] Could not check for a new version: {e}")
            return None
        with _lock:
            _latest.update(found, ref=ref)
        if is_newer(found["version"]):
            print(f"[ModelManager] Version {found['version']} is available (this is {VERSION})")
        return found
    return None


def status() -> Dict[str, object]:
    """What the page shows: the version out, and whether it is newer than this one."""
    with _lock:
        latest = dict(_latest)
    on = enabled()
    return {
        "current": VERSION,
        "latest": latest["version"] if on else None,
        "newer": on and is_newer(latest["version"]),
        "note": latest["note"] if on else "",
    }


def _loop():
    while True:
        check_once()
        time.sleep(INTERVAL)


def start_in_background() -> None:
    """The 12-hourly check, once per process - Forge can import this module again."""
    if any(t.name == THREAD_NAME for t in threading.enumerate()):
        return
    threading.Thread(target=_loop, name=THREAD_NAME, daemon=True).start()


def check_soon() -> None:
    """Check now, without waiting: the setting has just been turned on."""
    if enabled():
        threading.Thread(target=check_once, name=THREAD_NAME + "-now", daemon=True).start()
