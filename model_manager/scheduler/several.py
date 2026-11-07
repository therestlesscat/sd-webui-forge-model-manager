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
    """
    try:
        asked = json.loads(raw or "{}")
    except (TypeError, ValueError):
        asked = {}
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
            selected_family: Optional[str], found: Any = None) -> Dict[str, Any]:
    """
    One name's run: its VAE / text encoders - the selection on screen for a
    checkpoint of the selected one's family, else what Send picks for its own,
    a family missing a kind refused before anything more is asked - and its
    usual settings: none for the one your settings were set up for, what the
    task held for it, or what Send works out for it. {modules, same, usual}.
    `found`: what the file is, read already (a send_plan.SendModel), for
    family_pick to take; without it, family_pick reads it as it always has.
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
    if plan.yours is not None and file_key == plan.yours:
        usual = None
    elif name in plan.held:
        usual = (plan.held[name] or {}).get("usual")
    elif file_key in plan.held_files:
        usual = (plan.held_files[file_key] or {}).get("usual")
    else:
        usual = chosen(db, {**plan.image, "usual": True, "use_checkpoint": name})
    return {"modules": modules, "same": same, "usual": usual}


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
