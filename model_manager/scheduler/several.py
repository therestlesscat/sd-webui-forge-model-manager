"""
A press of Queue for N checkpoints (#400): the rows of a task that makes one
generation with each of several checkpoints, decided here, on the server,
from the names the page picked and where its list came from.

Every name first, in the order picked:
  - Forge must list it, by exactly that name (forge_host.checkpoint_listed);
  - its file is read where no sync has read it (send_plan.picked_model), and
    read without storing where the library holds no row for it - one put in
    a folder since the last sync - as Send reads a file (send.plan_for), so
    every family is known before anything else is decided: a file that
    cannot be read refuses the press.
Then each name's row:
  - its VAE / text encoders: the selection on screen for a checkpoint of the
    family of the one Forge has selected, else what Send picks for its own
    family (send.family_pick), as paths - a family missing a kind refuses the
    press rather than run with none;
  - its usual settings (#378), as Send works them out for one pick
    (usual_settings.chosen): against the image Send was given, its own
    checkpoint or the same file runs as made and takes none; against a task
    Load to UI loaded, a name the task held - or the file it named, renamed
    by Forge since - keeps what it ran with there. A
    task deleted since holds nothing: each name takes its usual settings,
    and the press says so (gone_task). With neither - a list ticked in
    txt2img with Several checkpoints… - the checkpoint Forge has selected
    runs with your settings, as an image's own runs as made, and each other
    takes its usual settings.

A refusal names what is wrong and saves nothing: Refused.

Change's window asks the same of a list before it is pressed (#406,
runs_preview): each name decided as the press decides it (_Plan, _decide),
its family read from the library's row alone, so no checkpoint of the list
is read; what the press would refuse is said on the name, not raised.
"""
import json
import os
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

from .. import forge_host


class Refused(Exception):
    """The press cannot be queued as asked: the text says why."""


def read_asked(raw: Any) -> Tuple[List[Any], Any]:
    """
    The names and the source a press hands over - the strip's data-checkpoints,
    `{names, source}` as JSON - each taken as none where it is not that shape:
    text that is not JSON, or not an object, or names that are not a list.
    Change's window's route hands the same, already parsed from its body.
    """
    if raw is None or isinstance(raw, (str, bytes, bytearray)):
        try:
            asked = json.loads(raw or "{}")
        except (TypeError, ValueError):
            asked = {}
    else:
        asked = raw
    if not isinstance(asked, dict):
        asked = {}
    names = asked.get("names")
    return (names if isinstance(names, list) else []), asked.get("source")


def checkpoint_rows(db, names: List[str], source: Optional[Dict[str, Any]],
                    selected: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    The task's checkpoint rows, a {checkpoint, modules, settings} each.

    Args:
        names: the checkpoints by Forge's name, in the order they run.
        source: where the list came from - {"image": <Send's usual source>}
            or {"task": <task id>} - or none: a list ticked in txt2img.
        selected: what Forge has selected now (forge_host.selected_models).
    """
    from ..send_plan import picked_model

    names = [n for n in dict.fromkeys(names or []) if isinstance(n, str) and n]
    if not names:
        raise Refused("No checkpoint to queue for.")
    plan = _Plan.of(db, source)

    for name in names:
        if not forge_host.checkpoint_listed(name):
            raise Refused(f"Forge does not list the checkpoint {name}: refresh its list, or pick another.")
    paths = {name: forge_host.checkpoint_file(name) or "" for name in names}
    found = {}
    for name in names:
        found[name] = _found(db, picked_model, paths[name])
        if not found[name].preset:
            raise Refused(f"Could not read {os.path.basename(paths[name])}, so its family is not known.")
    plan = plan.selecting(selected)
    selected_family = _found(db, picked_model, plan.selected_path).preset if plan.selected_path else None

    rows = []
    for name in names:
        # What each file is, as read here, is what its VAE / text encoders are
        # picked for: read again from the library's row alone, a file no sync
        # has given a row came out as no family, and was queued with none.
        run = _decide(db, plan, name, paths[name], found[name].preset, selected_family, found[name])
        settings: Dict[str, Any] = {}
        if run["usual"]:
            settings["usual"] = run["usual"]
        if not run["same"]:
            settings["another_family"] = True
        rows.append({"checkpoint": name, "modules": run["modules"], "settings": settings or None})
    return rows


@dataclass
class _Plan:
    """
    What a list's runs are decided from, worked out without reading any model
    file: where it came from and what the task held (`of`), then Forge's
    selection (`selecting`), looked up once every name's file is read.
    """
    image: Dict[str, Any]
    # The task's rows by name, and by the file each names: Forge adds a file's
    # hash to its name the first time it loads it, and Load to UI hands the name
    # it lists the file under now, so a name the task held may come back renamed.
    held: Dict[str, Optional[Dict[str, Any]]]
    held_files: Dict[str, Optional[Dict[str, Any]]]
    has_task: bool
    selected_path: str = ""
    selected_modules: List[str] = field(default_factory=list)
    # No image and no task behind the list: the selected checkpoint is the one
    # your settings were set up for, and keeps them.
    yours: Optional[str] = None

    @classmethod
    def of(cls, db, source: Any) -> "_Plan":
        source = source if isinstance(source, dict) else {}
        held = _task_rows(db, source.get("task"))
        held_files: Dict[str, Optional[Dict[str, Any]]] = {}
        for held_name, held_settings in held.items():
            held_path = forge_host.checkpoint_file(held_name)
            if held_path:
                held_files.setdefault(os.path.normcase(held_path), held_settings)
        image: Dict[str, Any] = source["image"] if isinstance(source.get("image"), dict) else {}
        return cls(image=image, held=held, held_files=held_files, has_task=source.get("task") is not None)

    def selecting(self, selected: Dict[str, Any]) -> "_Plan":
        """This plan with what Forge has selected now (forge_host.selected_models)."""
        selected_path = forge_host.checkpoint_file(selected.get("checkpoint") or "") or ""
        yours = os.path.normcase(selected_path) if selected_path and not self.image and not self.has_task else None
        return replace(self, selected_path=selected_path, selected_modules=list(selected.get("modules") or []),
                       yours=yours)


def _decide(db, plan: _Plan, name: str, path: str, family: Optional[str],
            selected_family: Optional[str], found: Any = None, ask: Any = None) -> Dict[str, Any]:
    """
    One name's run: its VAE / text encoders - the selection on screen for a
    checkpoint of the selected one's family, else what Send picks for its own,
    a family missing a kind refused before anything more is asked - and its
    usual settings: none for the one your settings were set up for, what the
    task held for it, or what Send works out for it. {modules, same, usual,
    kept}: `kept` "yours" or "held" where the usual settings were not asked.
    `found`: what the file is, read already (a send_plan.SendModel), for
    family_pick to take; without it, family_pick reads it as it always has.
    `ask`: what asks for the usual settings, usual_settings.chosen's way;
    Change's window passes its own, to tell why none came (runs_preview).
    Imported here, not at the top, so a suite's stand-ins for them are the
    ones called.
    """
    from ..send import family_pick
    from ..usual_settings import chosen

    same = family == selected_family
    if same:
        modules = list(plan.selected_modules)
    else:
        labels, missing = family_pick(db, path) if found is None else family_pick(db, path, found)
        if missing:
            raise Refused(f"{name} needs {_listed([_kind_name(kind) for kind in missing])}, "
                          f"which this WebUI does not have.")
        installed = forge_host.installed_modules()
        modules = [installed[label] for label in labels if label in installed]
    file_key = os.path.normcase(path) if path else None
    kept = None
    if plan.yours is not None and file_key == plan.yours:
        usual, kept = None, "yours"
    elif name in plan.held:
        usual, kept = (plan.held[name] or {}).get("usual"), "held"
    elif file_key in plan.held_files:
        usual, kept = (plan.held_files[file_key] or {}).get("usual"), "held"
    else:
        usual = (ask or chosen)(db, {**plan.image, "usual": True, "use_checkpoint": name})
    return {"modules": modules, "same": same, "usual": usual, "kept": kept}


def runs_preview(db, names: List[Any], source: Any, selected: Dict[str, Any]) -> Dict[str, Any]:
    """
    What each checkpoint of a list would run with, were it pressed now: what
    Change's window shows (#406). The press's own decision (_Plan, _decide),
    with each family read from the library's row alone (send_plan.row_model):
    no checkpoint of the list is read. From an image, the files of the image's
    own checkpoint may be, as the Resources dialog's usual settings read them:
    each whose header was not read at its modified time now is read and
    stored (usual_settings.usual -> send_plan.local_checkpoint); nothing else
    is written. What the press would refuse is said on the name, in the press's
    own words; nothing is raised.

    Returns:
        runs: {name: {how, usual, family, family_state, another_family,
            problem}}. `how`: "yours" (the one your settings were set up
            for), "as_made" (the image's own), "held" (what the task held for
            it), "usual" (its usual settings found), "thin" (too few uses
            record them), "plain" (none apply: an image's generation gone
            since, or a pick Forge no longer lists), "error" (they could not
            be read: it runs with yours); None where a problem stops it.
            `usual`: the values it runs with, {key: value}, or None.
            `family_state`: send_plan's READ, NOT_READ or UNRECOGNISED - for
            the last two the press reads the file again, and its family is
            told only then.
            `another_family`: True or False, or None where it cannot be told
            without reading a file: this name's row, or the selected one's,
            not READ.
        selected: {name, state} - Forge's selected checkpoint, and what its
            row says: READ, NOT_READ, UNRECOGNISED, or None where Forge has
            none selected, or does not list it.
        gone_task: the task a list from Load to UI came from, when deleted
            since; else None.
    """
    from ..send_plan import READ, row_model
    from ..usual_settings import applied, usual

    names = [n for n in dict.fromkeys(names or []) if isinstance(n, str) and n]
    plan = _Plan.of(db, source).selecting(selected)
    chosen_name = selected.get("checkpoint") or None
    selected_model, selected_state = row_model(db, plan.selected_path) if plan.selected_path else (None, None)
    selected_family = selected_model.preset if selected_state == READ else None

    runs: Dict[str, Dict[str, Any]] = {}
    for name in names:
        entry: Dict[str, Any] = {"how": None, "usual": None, "family": None, "family_state": None,
                                 "another_family": None, "problem": None}
        runs[name] = entry
        if not forge_host.checkpoint_listed(name):
            entry["problem"] = f"Forge does not list the checkpoint {name}: refresh its list, or pick another."
            continue
        path = forge_host.checkpoint_file(name) or ""
        found, state = row_model(db, path)
        entry["family_state"] = state
        family = found.preset if state == READ else None
        entry["family"] = family
        # Another family, as the press judges it: against the selected one's
        # family, and every name where Forge has none selected - or one it
        # does not list - whatever each is. Where the selected one's row, or
        # this name's, is not read at the file's modified time now, or was
        # read and not recognised, the press reads the file again and may
        # find a family: it is not told, and neither is a VAE or text encoder
        # missing, which only a name of another family can lack - the two are
        # handed as one family, so _decide picks nothing.
        if selected_state is None:
            entry["another_family"] = True
            compare_with = None if state == READ else family
        elif selected_state != READ or state != READ:
            compare_with = family
        else:
            compare_with = selected_family
            entry["another_family"] = family != selected_family
        asked: Dict[str, Any] = {}

        def ask(db_, asking, asked=asked):
            try:
                answer = usual(db_, asking["use_checkpoint"], asking)
            except Exception as e:
                # As chosen() does: the press runs it with your settings.
                from ..console import say_failure
                say_failure(f"Change's window: the usual settings could not be read: {e}")
                asked["how"] = "error"
                return None
            values = applied(answer)
            if not answer.get("applies"):
                asked["how"] = "as_made" if answer.get("kind") in ("own", "same") else "plain"
            else:
                asked["how"] = "usual" if values else "thin"
            return values

        try:
            run = _decide(db, plan, name, path, family, compare_with, found, ask)
        except Refused as e:
            entry["problem"] = str(e)
            continue
        entry["usual"] = run["usual"]
        entry["how"] = run["kept"] or asked.get("how")
    return {"runs": runs, "selected": {"name": chosen_name if plan.selected_path else None, "state": selected_state},
            "gone_task": gone_task(db, source)}


def _found(db, picked_model, path: str) -> Any:
    """
    What a checkpoint is (a send_plan.SendModel), its family its UI preset:
    from the library's row, its file read and stored where no sync has read
    it; else, for a file the library holds no row for, read without storing -
    as send.plan_for reads one.
    """
    found = picked_model(db, path)
    if not found.preset and path and os.path.isfile(path):
        from ..file_identity import identify
        from ..send_plan import SendModel
        read = identify(path)
        found = SendModel(preset=read.preset, model_class=read.model_class,
                          bundled_text_encoder=bool(read.bundled_text_encoder),
                          bundled_vae=bool(read.bundled_vae), source="picked")
    return found


def _kind_name(kind: str) -> str:
    """A kind of module as the page names it (forge_modules.FILES): T5-XXL, not t5xxl."""
    from ..forge_modules import FILES
    return next((f.label for f in FILES.values() if f.kind == kind), kind)


def _listed(words: List[str]) -> str:
    """Words as a sentence lists them: A, B and C."""
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def gone_task(db, source: Any) -> Optional[int]:
    """
    The task a list Load to UI loaded, by its id, when this install holds it
    no more - deleted since the list was loaded: its rows' settings went with
    it, and each name takes its usual settings. None for any other source.
    """
    task_id = source.get("task") if isinstance(source, dict) else None
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        return None
    return None if _task(db, task_id) else task_id


def _task(db, task_id: Any) -> Optional[Dict[str, Any]]:
    """A task this install queued, or None."""
    if task_id in (None, ""):
        return None
    from ..install import INSTALL_KEY
    try:
        task = db.get_task(int(task_id))
    except (TypeError, ValueError):
        return None
    return task if task and task.get("install") == INSTALL_KEY else None


def _task_rows(db, task_id: Any) -> Dict[str, Optional[Dict[str, Any]]]:
    """A queued task's settings by checkpoint, for a list Load to UI loaded; none for no task."""
    task = _task(db, task_id)
    return {row.get("checkpoint"): row.get("settings") for row in (task or {}).get("checkpoints") or []}
