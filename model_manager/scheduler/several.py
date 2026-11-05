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
    Load to UI loaded, a name the task held keeps what it ran with there. A
    task deleted since holds nothing: each name takes its usual settings,
    and the press says so (gone_task).

A refusal names what is wrong and saves nothing: Refused.
"""
import os
from typing import Any, Dict, List, Optional

from .. import forge_host


class Refused(Exception):
    """The press cannot be queued as asked: the text says why."""


def checkpoint_rows(db, names: List[str], source: Optional[Dict[str, Any]],
                    selected: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    The task's checkpoint rows, a {checkpoint, modules, settings} each.

    Args:
        names: the checkpoints by Forge's name, in the order they run.
        source: where the list came from - {"image": <Send's usual source>}
            or {"task": <task id>} - or none.
        selected: what Forge has selected now (forge_host.selected_models).
    """
    from ..send import family_pick
    from ..send_plan import picked_model
    from ..usual_settings import chosen

    names = [n for n in dict.fromkeys(names or []) if isinstance(n, str) and n]
    if not names:
        raise Refused("No checkpoint to queue for.")
    source = source if isinstance(source, dict) else {}
    held = _task_rows(db, source.get("task"))
    image: Dict[str, Any] = source["image"] if isinstance(source.get("image"), dict) else {}

    for name in names:
        if not forge_host.checkpoint_listed(name):
            raise Refused(f"Forge does not list the checkpoint {name}: refresh its list, or pick another.")
    paths = {name: forge_host.checkpoint_file(name) or "" for name in names}
    families = {}
    for name in names:
        families[name] = _family(db, picked_model, paths[name])
        if not families[name]:
            raise Refused(f"Could not read {os.path.basename(paths[name])}, so its family is not known.")
    selected_path = forge_host.checkpoint_file(selected.get("checkpoint") or "")
    selected_family = _family(db, picked_model, selected_path) if selected_path else None

    rows = []
    for name in names:
        path = paths[name]
        same = families[name] == selected_family
        if same:
            modules = list(selected.get("modules") or [])
        else:
            labels, missing = family_pick(db, path)
            if missing:
                raise Refused(f"{name} needs {_listed([_kind_name(kind) for kind in missing])}, "
                              f"which this WebUI does not have.")
            installed = forge_host.installed_modules()
            modules = [installed[label] for label in labels if label in installed]
        if name in held:
            usual = (held[name] or {}).get("usual")
        else:
            usual = chosen(db, {**image, "usual": True, "use_checkpoint": name})
        settings: Dict[str, Any] = {}
        if usual:
            settings["usual"] = usual
        if not same:
            settings["another_family"] = True
        rows.append({"checkpoint": name, "modules": modules, "settings": settings or None})
    return rows


def _family(db, picked_model, path: str) -> Optional[str]:
    """
    A checkpoint's family, its UI preset: from the library's row, its file
    read and stored where no sync has read it; else, for a file the library
    holds no row for, read without storing - as send.plan_for reads one.
    """
    family = picked_model(db, path).preset
    if not family and path and os.path.isfile(path):
        from ..file_identity import identify
        family = identify(path).preset
    return family


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
