"""
A queued task as the queue's page shows it, and what Retry and Delete do
with one (#158, #159, #161, #162). Read from the inputs capture.py kept, by
name; the endpoints are api/scheduler.py's.

A row says what was set, as it was set. Hires fix's size is the scale or
the resize asked for, not the size it makes: the two WebUIs work that out
differently (calculate_target_resolution), and a copy of either would drift.
"""
import copy
import os
from typing import Any, Dict, List, Optional, Tuple

from .capture import LABEL

# Retry copies a task that has ended; one pending or running is still to run.
ENDED = ("completed", "stopped", "failed")

# What a list's row says of a task besides its inputs (#158).
ROW_FIELDS = ("id", "mode", "status", "checkpoint", "modules", "username", "created_at",
              "started_at", "finished_at", "error", "first_seed", "retry_of", "retried_as",
              "generations")

# A kept value the page cannot draw as it is: a file, an object, a value not
# kept. Marked by "__kind__", which no kept value holds.
_FILES = (("__image__", "image"), ("__array__", "array"), ("__file__", "file"))


def _entry(inputs: Dict[str, Any], elem_id: str) -> Optional[Dict[str, Any]]:
    """A script control's kept entry, found by its id in whichever script has it."""
    for controls in (inputs.get("scripts") or {}).values():
        for entry in controls:
            if entry.get("id") == elem_id:
                return entry
    return None


def shown(value: Any) -> Any:
    """
    A kept value as the page shows it: a label as itself, a file by its
    name, an object by its class and fields - JSON the page escapes.
    """
    if isinstance(value, list):
        return [shown(v) for v in value]
    if not isinstance(value, dict):
        return value
    if LABEL in value:
        return value[LABEL] if value[LABEL] is not None else value.get("index")
    for mark, kind in _FILES:
        if mark in value:
            return {"__kind__": kind, "name": os.path.basename(str(value[mark]))}
    if "__missing__" in value:
        return {"__kind__": "missing", "name": value["__missing__"]}
    if "__enum__" in value:
        return shown(value.get("value"))
    if "__dataclass__" in value:
        return {"__kind__": "object", "name": str(value["__dataclass__"]).rpartition(":")[2],
                "fields": {k: shown(v) for k, v in (value.get("fields") or {}).items()}}
    if "__tuple__" in value:
        return shown(value["__tuple__"])
    if "__dict__" in value:
        return {k: shown(v) for k, v in value["__dict__"].items()}
    return {k: shown(v) for k, v in value.items()}


def _hires(fixed: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Hires fix as it was set - a scale, or a resize where 0 follows the
    image's shape - or None when it is off."""
    if not fixed.get("enable_hr"):
        return None
    x, y = fixed.get("hr_resize_x") or 0, fixed.get("hr_resize_y") or 0
    if x or y:
        return {"resize": [x, y]}
    return {"scale": fixed.get("hr_scale")}


def summary(task: Dict[str, Any]) -> Dict[str, Any]:
    """A task's row in the Active or History list (#158)."""
    inputs = task.get("inputs") or {}
    fixed = inputs.get("fixed") or {}
    mode = task.get("mode")
    row = {field: task.get(field) for field in ROW_FIELDS}
    row.update({
        "prompt": fixed.get("prompt") or "",
        "script": inputs.get("script"),
        "width": fixed.get("width"),
        "height": fixed.get("height"),
        "hires": _hires(fixed),
        # img2img's "Resize by" scales the image it is given.
        "scale_by": fixed.get("scale_by") if fixed.get("selected_scale_tab") == 1 else None,
        "batch_size": fixed.get("batch_size"),
        "n_iter": fixed.get("n_iter"),
    })
    for name, item in (("sampler", "sampling"), ("scheduler", "scheduler"), ("steps", "steps")):
        entry = _entry(inputs, f"{mode}_{item}")
        row[name] = shown(entry["value"]) if entry else None
    return row


def details(task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Everything a task holds (#159): Generate's own inputs by name, the
    selected script, and each script's controls under its title, with
    their labels.
    """
    inputs = task.get("inputs") or {}
    return {
        "fixed": [{"name": name, "value": shown(value)}
                  for name, value in (inputs.get("fixed") or {}).items()],
        "script": inputs.get("script"),
        "scripts": [{"title": title,
                     "controls": [{"id": c.get("id"), "label": c.get("label"), "value": shown(c.get("value"))}
                                  for c in controls]}
                    for title, controls in (inputs.get("scripts") or {}).items()],
        "loose": [{"at": e.get("at"), "value": shown(e.get("value"))} for e in inputs.get("loose") or []],
    }


def retried(task: Dict[str, Any], seed: str) -> Dict[str, Any]:
    """
    The copy Retry queues (#161): the task as it was queued, with the first
    run's seed - the same images again - or a random one (-1). A task that
    never got a seed keeps the one it was queued with.
    """
    if seed not in ("first", "random"):
        raise ValueError(f"no seed choice {seed!r}")
    inputs = copy.deepcopy(task.get("inputs") or {})
    entry = _entry(inputs, f"{task.get('mode')}_seed")
    new = -1 if seed == "random" else task.get("first_seed")
    if entry is not None and new is not None:
        # The Seed control can be a textbox, which sends text.
        entry["value"] = str(new) if isinstance(entry.get("value"), str) else new
    copied = {column: task.get(column) for column in ("install", "forge", "mode", "checkpoint",
                                                      "modules", "username")}
    return {**copied, "inputs": inputs, "retry_of": task["id"]}


def delete_inputs(paths: List[str]) -> Tuple[int, List[Dict[str, str]]]:
    """
    Delete files a deleted task kept (#149), then each folder they leave
    empty: a task's own, made for its files.

    Returns:
        how many files went, and those that could not, with why.
    """
    deleted, failed = 0, []
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
            deleted += 1
        except OSError as e:
            failed.append({"path": path, "error": str(e)})
    for folder in {os.path.dirname(p) for p in paths}:
        try:
            os.rmdir(folder)
        except OSError:
            pass  # not empty, or gone
    return deleted, failed
