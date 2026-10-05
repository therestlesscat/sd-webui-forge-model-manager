"""
Load to UI (#160): a task's inputs set back into txt2img or img2img, to
change it or run it by hand.

Not by pasting an infotext. Forge sets some controls from which keys a text
holds - Hires fix is ticked when "Denoising strength" and "Hires upscale" are
there - so a task with Hires off, its values still kept, came back with it
on; and a key left out leaves its control as it is on screen. Instead a
hidden button in the Queue tab has Generate's own inputs as its outputs: its
function hands each control the task's value, rebuilt as for a run
(replay.rebuild), as Forge's own paste hands it a pasted one.

A control Generate takes only as a state - ControlNet's units - cannot be
shown that way, nor a value its control does not take: each keeps what is on
screen, and the answer names them for the page to say - a state only when
the task's differs from its default: three units left off, named on every
load, said nothing was lost. The checkpoint and
the VAE / text encoders are Forge's settings, not Generate's inputs: the
page sets them as Send does, from the task's send plan.

The page asks with JSON in a hidden textbox - the task and a nonce - and is
answered in another, with the same nonce.
"""
import dataclasses
import enum
import json
from typing import Any, Callable, List, Tuple

from ..console import say
from ..db import get_models_db
from ..install import INSTALL_KEY
from . import capture, replay

ASKED = "queue_load_{tab}_task"
ANSWER = "queue_load_{tab}_answer"
BUTTON = "queue_load_{tab}"


def _shown(component, value: Any) -> Any:
    """A rebuilt value as its control shows it: an index as its choice."""
    if not replay.is_index(component) or value is None:
        return value
    if isinstance(value, list):
        return [_shown(component, v) for v in value]
    choice = component.choices[value]
    return choice[1] if isinstance(choice, (tuple, list)) else choice


def _canon(value: Any) -> Any:
    """
    A value as compared: an enum as what it stands for, a dataclass by its
    fields. A script's default holds enums - ControlNet's unit,
    ResizeMode.INNER_FIT - where what the page sent back holds their text,
    "Crop and Resize": equal, they compared unequal.
    """
    if isinstance(value, enum.Enum):
        return _canon(value.value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return tuple((f.name, _canon(getattr(value, f.name))) for f in dataclasses.fields(value))
    if isinstance(value, (list, tuple)):
        return tuple(_canon(v) for v in value)
    if isinstance(value, dict):
        return tuple((k, _canon(v)) for k, v in sorted(value.items(), key=lambda item: str(item[0])))
    return value


def _same(value: Any, other: Any) -> bool:
    """Whether two values say the same; not, when they cannot say - arrays."""
    try:
        return bool(_canon(value) == _canon(other))
    except Exception:
        return False


def _takes(component, value: Any) -> bool:
    """Whether a control can be handed this value: Gradio's own conversion for it, tried."""
    try:
        component.postprocess(value)
        return True
    except Exception:
        return False


def task_values(tab: str, task_id: int, skip: Any = None) -> Tuple[List[Any], List[str], List[str]]:
    """
    What each of Generate's inputs but the first - the id Forge gives a run
    - is set to for a task: its value, or `skip` for a control that keeps
    what is on screen.

    Returns:
        (the values, the names of the controls skipped, the notes on inputs
        that took their default)
    """
    task = get_models_db().get_task(task_id)
    if task is None or task.get("install") != INSTALL_KEY:
        raise replay.TaskError(f"No task #{task_id} in this WebUI")
    if task["mode"] != tab:
        raise replay.TaskError(f"Task #{task_id} is an {task['mode']} task")
    own = capture.generate_click(tab)
    if own is None:
        raise replay.TaskError(f"{tab}'s Generate was not found")
    components = list(own.inputs)
    values, notes = replay.rebuild(tab, components, task["inputs"])
    names = replay.input_names(tab, components)
    shown, skipped = [], []
    for at in range(1, len(components)):
        component = components[at]
        value = _shown(component, values[at])
        if type(component).__name__ == "State":
            shown.append(skip)
            if not _same(value, replay.default(component)):
                skipped.append(names[at])
        elif not _takes(component, value):
            shown.append(skip)
            skipped.append(names[at])
        else:
            shown.append(value)
    return shown, skipped, notes


def _loader(tab: str, count: int) -> Callable:
    import gradio as gr

    def load(asked: str):
        try:
            request = json.loads(asked or "{}")
        except ValueError:
            request = {}
        answer = {"nonce": request.get("nonce"), "task": request.get("task")}
        try:
            values, skipped, notes = task_values(tab, int(request.get("task")), skip=gr.update())
            answer.update({"skipped": skipped, "notes": notes})
        except Exception as e:
            say(f"Queue: could not load task {request.get('task')} into {tab}: {e}")
            values = [gr.update()] * count
            answer["error"] = str(e)
        return [*values, json.dumps(answer)]

    return load


def wire_load_buttons() -> None:
    """
    For each tab whose Generate was found, the hidden button that loads a
    task into it. Called inside a Blocks our tabs build, as the Queue
    buttons are wired.
    """
    import gradio as gr
    for tab in capture.TABS:
        own = capture.generate_click(tab)
        if own is None:
            continue
        outputs = list(own.inputs[1:])
        asked = gr.Textbox(visible=False, elem_id=ASKED.format(tab=tab))
        answer = gr.Textbox(visible=False, elem_id=ANSWER.format(tab=tab))
        button = gr.Button(visible=False, elem_id=BUTTON.format(tab=tab))
        button.click(fn=_loader(tab, len(outputs)), inputs=[asked], outputs=outputs + [answer],
                     show_progress="hidden")
