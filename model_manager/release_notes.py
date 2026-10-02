"""
Notes to the user, per release: what is new, and what to do after updating.

A changelog reaches the people who read it. Some changes need everyone who
updates to do something - run Scan Disk once to read files again, update the
copy of the extension in the other WebUI before a database migration - or
are features nobody would find alone. Each release that has one adds a note
to data/release_notes.json; the tabs show the notes that apply and have not
been dismissed, and the settings window's "What's new" lists them all.

A note is:

    id        stable, never reused: dismissing is kept by it
    version   the release that brought it; a note from a later version than
              this one is not shown
    kind      "feature", "action" (something to do), "warning", or "intro": a
              tab's introduction for someone new, first in its pile
    audience  "everyone"; "update": only for a database that existed before
              that version - a fresh install has nothing to redo; or "new":
              only for one created by that version or later - a first install
    tabs      where it shows: "model_manager", "civitai_browser", "generations"
    title, text
    actions   optional, several buttons, each as `action`
    action    optional {"id", "label", "section"}: a button that does it - the
              ids are the page's (NOTE_ACTIONS in javascript/shared/common.mjs);
              "settings" opens the settings window at `section`, one of its
              sections' ids (SECTIONS in javascript/shared/settings.mjs)
    when      optional: a condition of this install the note is only for, of
              CONDITIONS - "custom_database", the database file set in the
              settings, which two WebUIs sharing one database need
    important optional true: shown first, headed [Important] - for what
              everyone should read, not only what needs doing
    replaces  optional: ids of earlier notes this one makes needless - a
              second "run Scan Disk once" retires the first - which then
              leave the tabs; "What's new" still lists them

Dismissed notes are kept in the database, so a note is dismissed once for
every browser, and for both WebUIs when they share the database.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, Set

from .forge_host import setting
from .version import VERSION

NOTES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "release_notes.json")

KINDS = ("feature", "action", "warning", "intro")
AUDIENCES = ("everyone", "update", "new")
TABS = ("model_manager", "civitai_browser", "generations")
ACTIONS = ("reread_headers", "settings", "scan_disk", "sync_unidentified")


def _custom_database() -> bool:
    """Whether the settings name a database file - the only way two WebUIs share one."""
    return bool(str(setting("model_manager_database_path") or "").strip())


# Conditions a note can be for, by the name its "when" gives.
CONDITIONS = {"custom_database": _custom_database}

# schema_info keys: the version that created the database (db/database.py),
# and the notes dismissed there.
CREATED_BY = "created_by"
DISMISSED = "notes_dismissed"


def version_key(version: Optional[str]) -> tuple:
    """"0.40.11" as (0, 40, 11), to compare; the build, if any, is ignored."""
    return tuple(int(part) for part in re.findall(r"\d+", str(version or ""))[:3])


def load_notes(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every note in the file, newest version first; [] if it cannot be read."""
    try:
        with open(path or NOTES_FILE, encoding="utf-8") as f:
            notes = json.load(f)
    except (OSError, ValueError) as e:
        print(f"[ModelManager] Could not read the release notes: {e}")
        return []
    notes = [n for n in notes if isinstance(n, dict) and n.get("id") and n.get("version")]
    return sorted(notes, key=lambda n: version_key(n["version"]), reverse=True)


def applies(note: Dict[str, Any], created_by: Optional[str]) -> bool:
    """
    Whether a note is for this install: from this version or before, and -
    if it is for people updating - their database is older than the note.
    A database with no record of what created it is one from before notes
    were kept, and every note is for it - but those for a first install.
    """
    if version_key(note["version"]) > version_key(VERSION):
        return False
    when = note.get("when")
    if when and not (when in CONDITIONS and CONDITIONS[when]()):
        return False
    audience = note.get("audience")
    if audience == "new":
        return created_by is not None and version_key(created_by) >= version_key(note["version"])
    if audience != "update" or created_by is None:
        return True
    return version_key(created_by) < version_key(note["version"])


def dismissed(db) -> Set[str]:
    try:
        return set(json.loads(db.get_info(DISMISSED) or "[]"))
    except ValueError:
        return set()


def notes_for(db, tab: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    The notes that apply here, newest first, each with `dismissed`. With a
    tab, only that tab's that are not dismissed - what its panel shows;
    without, all of them - the settings window's "What's new".
    """
    created_by = db.get_info(CREATED_BY)
    gone = dismissed(db)
    out = []
    for note in load_notes():
        if not applies(note, created_by):
            continue
        if tab is not None and (tab not in (note.get("tabs") or []) or note["id"] in gone):
            continue
        out.append({**note, "dismissed": note["id"] in gone})
    if tab is not None:
        # A note replaced by a later one that applies here - in any tab, and
        # dismissed or not: asked once, not twice.
        replaced = {old for note in notes_for(db) for old in (note.get("replaces") or [])}
        out = [note for note in out if note["id"] not in replaced]
    return out


def dismiss(db, note_id: str) -> None:
    """Dismiss a note, here and wherever this database is used."""
    gone = dismissed(db)
    gone.add(str(note_id))
    db.set_info(DISMISSED, json.dumps(sorted(gone)))
