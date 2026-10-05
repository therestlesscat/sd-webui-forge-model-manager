"""
Queue: what Generate would be sent, kept as a task to run later (#148, #149).

A Queue button is made beside each Generate (on_component) and wired while
our own tabs are built (wire_queue_buttons): by then Forge has wired
Generate, and the page is not yet launched. Its click is given the inputs of
Generate's own click - every value Generate would be sent, in its order -
and runs nothing: the values are named and stored as a task.

Generate's own click is the listener whose function is named for the tab
(`txt2img`, `img2img`). Other extensions listen on the same click:
ControlNet, three times a tab, to refresh its units' state just before
Generate reads it. Queue runs those listeners too, so what it keeps is what
Generate would get (#165).

How the values are named:
  fixed     the inputs before the scripts', by Forge's own signature for
            the tab (forge_host.generate_names) - the same in both WebUIs;
  script    the selected script's title, or None;
  scripts   per script title, each control in order: its elem_id, label
            and value - matched again by id, else by place, when it runs;
  loose     any script input no script claims, by its place.
A control that sends an index - the Script dropdown, X/Y/Z's axis types,
img2img's radios - is kept as its label ({"__label__": ...}): a list that
grows shifts an index, never a label. Images, arrays, objects and uploads
are kept by values.py, in a folder of the task's own.
"""
import os
import shutil
import traceback
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..console import say
from ..db import get_models_db
from ..forge_host import (forge_name, generate_names, script_runner, selected_models,
                          setting, webui_root)
from ..install import INSTALL_KEY
from .values import Keeper

TABS = ("txt2img", "img2img")
LABEL = "__label__"
INPUTS_SETTING = "model_manager_queue_inputs_dir"

# Per tab, as the UI is built: the Blocks it is built in, Generate, Queue.
_found: Dict[str, Dict[str, Any]] = {}


# ------------------------------------------------------------- the buttons

def on_component(component, **kwargs) -> None:
    """Forge's after-component callback: a Queue button beside each Generate."""
    elem_id = kwargs.get("elem_id") or getattr(component, "elem_id", None)
    for tab in TABS:
        if elem_id == f"{tab}_generate":
            import gradio as gr
            from gradio.context import Context
            queue = gr.Button("Queue", elem_id=f"{tab}_queue", variant="secondary")
            _found[tab] = {"root": Context.root_block, "generate": component, "queue": queue}


def generate_listeners(root, generate) -> Tuple[Optional[Any], List[Any]]:
    """
    The listeners on a Generate button's click: Generate's own - its
    function named for the tab - and every other one.
    """
    listeners = [dep for dep in root.fns.values()
                 if any(target[0] == generate._id and target[1] == "click" for target in dep.targets)]
    own = next((dep for dep in listeners if getattr(dep.fn, "__name__", None) in TABS), None)
    return own, [dep for dep in listeners if dep is not own]


def queue_inputs(own, others) -> List[Any]:
    """Generate's inputs, then whatever else its other listeners read."""
    inputs = list(own.inputs)
    seen = {id(c) for c in inputs}
    for dep in others:
        for component in dep.inputs:
            if id(component) not in seen:
                seen.add(id(component))
                inputs.append(component)
    return inputs


def wire_queue_buttons() -> None:
    """
    Give each Queue button Generate's inputs. Called inside a Blocks our
    tabs build, which renders into the page with them.
    """
    for tab, found in _found.items():
        if found.get("root") is None:
            continue
        own, others = generate_listeners(found["root"], found["generate"])
        if own is None:
            say(f"Queue: {tab}'s Generate was not found; its Queue button does nothing")
            continue
        inputs = queue_inputs(own, others)
        found["queue"].click(fn=_handler(tab, own, others, inputs), inputs=inputs, outputs=[],
                             show_progress="hidden")


def _handler(tab: str, own, others, inputs) -> Callable:
    import gradio as gr

    def queue(request: gr.Request, *values):
        try:
            _task_id, prompt = capture(tab, own, others, inputs, values,
                                       getattr(request, "username", None))
        except Exception as e:
            say(f"Queue: could not queue {tab}: {e}")
            traceback.print_exc()
            gr.Warning(f"Could not queue: {e}")
            return
        prompt = " ".join(str(prompt or "").split())
        gr.Info(f"Queued: {prompt[:60] + '…' if len(prompt) > 60 else prompt or '(no prompt)'}")

    return queue


# ------------------------------------------------------------ the capture

def inputs_folder() -> str:
    """Where tasks keep their files: the setting, else the WebUI's queue-inputs."""
    return str(setting(INPUTS_SETTING) or "").strip() or os.path.join(webui_root(), "queue-inputs")


def capture(tab: str, own, others, inputs: List[Any], values, username: Optional[str]) -> Tuple[int, str]:
    """
    Store what Generate would be sent as a pending task.

    Returns:
        (the task's id, its prompt)
    """
    by_component = {id(c): v for c, v in zip(inputs, values)}
    _refresh(others, by_component)
    keeper = Keeper(os.path.join(inputs_folder(), datetime.now().strftime("%Y%m%d-%H%M%S-")
                                 + uuid.uuid4().hex[:8]))
    try:
        named = name_inputs(tab, own.inputs, [by_component[id(c)] for c in own.inputs], keeper)
        models = selected_models()
        task_id = get_models_db().add_task({
            "install": INSTALL_KEY, "forge": forge_name(), "mode": tab, "inputs": named,
            "checkpoint": models["checkpoint"], "modules": models["modules"], "username": username,
        })
    except Exception:
        shutil.rmtree(keeper.folder, ignore_errors=True)
        raise
    return task_id, named["fixed"].get("prompt") or ""


def _refresh(others, by_component: Dict[int, Any]) -> None:
    """
    Run Generate's other listeners whose outputs are states Generate reads,
    as its click would - ControlNet's units are refreshed so (#165). A
    listener that fails leaves the state as it was.
    """
    for dep in others:
        outputs = list(dep.outputs or [])
        if getattr(dep, "js", None) or not outputs \
                or any(type(c).__name__ != "State" for c in outputs) \
                or not any(id(c) in by_component for c in outputs):
            continue
        try:
            result = dep.fn(*[by_component[id(c)] for c in dep.inputs])
        except Exception as e:
            say(f"Queue: a listener on Generate failed ({getattr(dep.fn, '__name__', dep.fn)}): {e}")
            continue
        results = [result] if len(outputs) == 1 else list(result)
        for component, value in zip(outputs, results):
            if id(component) in by_component:
                by_component[id(component)] = value


def name_inputs(tab: str, components: List[Any], values: List[Any], keeper: Keeper) -> Dict[str, Any]:
    """Generate's values by name, as a task keeps them."""
    names = generate_names(tab)
    runner = script_runner(tab)
    first_script = len(components) - len(runner.inputs)
    if first_script != len(names):
        raise RuntimeError(f"{tab}'s Generate sends {first_script} inputs before the scripts', "
                           f"and Forge's signature names {len(names)}")
    if any(a is not b for a, b in zip(components[first_script:], runner.inputs)):
        raise RuntimeError(f"{tab}'s Generate does not send its scripts' inputs in their order")

    fixed = {name: _keep(component, value, keeper, name)
             for name, component, value in zip(names, components, values) if name != "id_task"}

    script_values = values[first_script:]
    selected = _keep(runner.inputs[0], script_values[0], keeper, "script")
    title = selected.get(LABEL) if isinstance(selected, dict) else None

    scripts: Dict[str, List[Dict[str, Any]]] = {}
    claimed = {0}
    for script in sorted(runner.scripts, key=lambda s: getattr(s, "args_from", None) or 0):
        start, end = getattr(script, "args_from", None), getattr(script, "args_to", None)
        if start is None or end is None or start >= end:
            continue
        key = _unique(script_title(script), scripts)
        controls = []
        for at in range(start, end):
            component = runner.inputs[at]
            controls.append({"id": getattr(component, "elem_id", None) or None,
                             "label": getattr(component, "label", None) or None,
                             "value": _keep(component, script_values[at], keeper, f"{key}-{at - start}")})
            claimed.add(at)
        scripts[key] = controls
    loose = [{"at": at, "value": _keep(runner.inputs[at], script_values[at], keeper, f"input-{at}")}
             for at in range(len(runner.inputs)) if at not in claimed]

    named = {"fixed": fixed, "script": None if title in (None, "None") else title, "scripts": scripts}
    if loose:
        named["loose"] = loose
    return named


def script_title(script) -> str:
    try:
        return str(script.title())
    except Exception:
        return type(script).__name__


def _unique(title: str, taken: Dict[str, Any]) -> str:
    key, n = title, 2
    while key in taken:
        key, n = f"{title} ({n})", n + 1
    return key


def _keep(component, value: Any, keeper: Keeper, name: str) -> Any:
    """A value as a task keeps it, by what its control is."""
    if getattr(component, "type", None) == "index" and getattr(component, "choices", None) is not None:
        return _label(component.choices, value)
    if type(component).__name__ in ("File", "Files", "Gallery"):
        return _keep_uploads(value, keeper, name)
    return keeper.keep(value, name)


def _label(choices, value: Any) -> Any:
    """The label an index points at, or the index itself if it is out of range."""
    if value is None:
        return None
    if isinstance(value, list):
        return [_label(choices, v) for v in value]
    if isinstance(value, int) and 0 <= value < len(choices):
        choice = choices[value]
        return {LABEL: choice[0] if isinstance(choice, (tuple, list)) else choice}
    return {LABEL: None, "index": value}


def _keep_uploads(value: Any, keeper: Keeper, name: str) -> Any:
    """Files Gradio uploaded are copied: its own copies do not outlive it."""
    if isinstance(value, str) and os.path.isfile(value):
        return keeper.keep_file(value)
    if isinstance(value, (list, tuple)):
        kept = [_keep_uploads(v, keeper, f"{name}-{i}") for i, v in enumerate(value)]
        return kept if isinstance(value, list) else {"__tuple__": kept}
    return keeper.keep(value, name)
