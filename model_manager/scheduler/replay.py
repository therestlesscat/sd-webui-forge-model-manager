"""
A task's inputs back into what Generate is sent (#151): capture.name_inputs
the other way, against the inputs Generate has now.

The UI a task runs in may not be the one it was queued in. An extension
added since gives Generate inputs the task never had; one removed leaves
the task's values for it with nowhere to go; one updated may move or add a
control. So nothing is placed by position alone:
  - a fixed input by its name in Forge's signature;
  - a script's controls by the script's title, then by elem_id where it is
    unique in both, then by place when the script has as many controls as
    the task kept;
  - an index by its label, looked up in the choices offered now.
An input the task has no value for takes its control's default, and says
so. A label no longer offered fails the task, naming it: run anyway, the
script would take another choice in its place.

Scripts the task used that are gone are listed before the queue starts
(missing_scripts): the page asks whether to run without them.
"""
import copy
from typing import Any, Dict, List, Optional, Tuple

from ..forge_host import generate_names, script_runner
from .capture import LABEL, script_title, unique_key
from .values import MISSING, restore


class TaskError(Exception):
    """The task cannot run as it was queued: it fails, saying why."""


def is_index(component) -> bool:
    return getattr(component, "type", None) == "index" and getattr(component, "choices", None) is not None


def default(component) -> Any:
    """What a control would send untouched: its default, as Generate gets it."""
    value = getattr(component, "value", None)
    if type(component).__name__ == "State":
        # A state's default is one object, which a run may change.
        return copy.deepcopy(value)
    try:
        return component.preprocess(value)
    except Exception:
        return value


def _labels(component) -> List[Any]:
    return [c[0] if isinstance(c, (tuple, list)) else c for c in component.choices]


def _index(component, stored: Any, what: str) -> Any:
    """The index of a kept label among the choices offered now."""
    if stored is None:
        return None
    if isinstance(stored, list):
        return [_index(component, s, what) for s in stored]
    if isinstance(stored, dict) and LABEL in stored:
        if stored[LABEL] is None:
            return stored.get("index")
        labels = _labels(component)
        if stored[LABEL] not in labels:
            raise TaskError(f"{what}: \"{stored[LABEL]}\" is no longer offered")
        return labels.index(stored[LABEL])
    return stored


def _value(component, stored: Any, what: str, notes: List[str]) -> Any:
    if is_index(component):
        return _index(component, stored, what)
    value = restore(stored)
    if value is MISSING:
        notes.append(f"{what}: could not be restored; its default ran")
        return default(component)
    return value


def _place(controls: List[Any], kept: List[Dict[str, Any]]) -> List[Optional[Dict[str, Any]]]:
    """
    Each control's kept entry: by elem_id where it is unique in both; then,
    when the script has as many controls as the task kept, the rest in
    order - a control moved past one with an id still finds its value.
    """
    ids = [getattr(c, "elem_id", None) for c in controls]
    kept_ids = [entry.get("id") for entry in kept]
    placed: List[Optional[Dict[str, Any]]] = [None] * len(controls)
    used = set()
    for at, elem_id in enumerate(ids):
        if elem_id and ids.count(elem_id) == 1 and kept_ids.count(elem_id) == 1:
            placed[at] = kept[kept_ids.index(elem_id)]
            used.add(kept_ids.index(elem_id))
    if len(kept) == len(controls):
        rest = iter([entry for k, entry in enumerate(kept) if k not in used])
        for at in range(len(controls)):
            if placed[at] is None:
                placed[at] = next(rest)
    return placed


def _script_keys(runner) -> List[Tuple[str, int, int]]:
    """Each script with inputs, by the key capture kept it under: (key, from, to)."""
    keys: List[Tuple[str, int, int]] = []
    taken: Dict[str, bool] = {}
    for script in sorted(runner.scripts, key=lambda s: getattr(s, "args_from", None) or 0):
        start, end = getattr(script, "args_from", None), getattr(script, "args_to", None)
        if start is None or end is None or start >= end:
            continue
        key = unique_key(script_title(script), taken)
        taken[key] = True
        keys.append((key, start, end))
    return keys


def rebuild(tab: str, components: List[Any], named: Dict[str, Any]) -> Tuple[List[Any], List[str]]:
    """
    The values Generate's click takes now, in its order, from a task's
    named inputs; the first, the task id, is left for the caller.

    Returns:
        (the values, a note for each input that took its default)
    """
    names = generate_names(tab)
    runner = script_runner(tab)
    first_script = len(components) - len(runner.inputs)
    if first_script != len(names):
        raise TaskError(f"{tab}'s Generate takes {first_script} inputs before the scripts', "
                        f"and Forge's signature names {len(names)}")
    if any(a is not b for a, b in zip(components[first_script:], runner.inputs)):
        raise TaskError(f"{tab}'s Generate does not take its scripts' inputs in their order")

    notes: List[str] = []
    values: List[Any] = [None] * len(components)
    fixed = named.get("fixed") or {}
    for at, name in enumerate(names):
        if name == "id_task":
            continue
        if name in fixed:
            values[at] = _value(components[at], fixed[name], name, notes)
        else:
            values[at] = default(components[at])
            notes.append(f"{name}: not in the task; its default ran")

    script_values = [default(c) for c in runner.inputs]
    title = named.get("script")
    if title and title in _labels(runner.inputs[0]):
        script_values[0] = _labels(runner.inputs[0]).index(title)
    elif title:
        notes.append(f"Script \"{title}\" is gone; it did not run")
        script_values[0] = 0
    else:
        script_values[0] = 0

    kept_scripts = named.get("scripts") or {}
    for key, start, end in _script_keys(runner):
        kept = kept_scripts.get(key)
        if kept is None:
            notes.append(f"{key}: not in the task; its defaults ran")
            continue
        controls = runner.inputs[start:end]
        for offset, entry in enumerate(_place(controls, kept)):
            what = f"{key}: {(entry or {}).get('label') or getattr(controls[offset], 'label', None) or offset}"
            if entry is None:
                notes.append(f"{what}: not in the task; its default ran")
                continue
            script_values[start + offset] = _value(controls[offset], entry["value"], what, notes)

    for entry in named.get("loose") or []:
        at = entry.get("at")
        if isinstance(at, int) and 0 < at < len(runner.inputs):
            script_values[at] = _value(runner.inputs[at], entry.get("value"), f"input {at}", notes)

    values[first_script:] = script_values
    return values, notes


def missing_scripts(tab: str, named: Dict[str, Any]) -> List[str]:
    """The scripts a task used that this WebUI does not have now."""
    runner = script_runner(tab)
    present = {key for key, _start, _end in _script_keys(runner)}
    missing = sorted(key for key in (named.get("scripts") or {}) if key not in present)
    title = named.get("script")
    if title and title not in _labels(runner.inputs[0]) and title not in missing:
        missing.append(title)
    return missing
