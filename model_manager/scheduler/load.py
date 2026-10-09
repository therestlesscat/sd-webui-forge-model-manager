"""
Setting a tab's controls back from what we keep - one hidden button per tab,
whose outputs are Generate's own inputs, for three kinds of request:

  a task          Load to UI (#160): a queued task, to change it or run it
                  by hand;
  a generation    Send on one of your own generations (#7): what its press
                  was sent, as a task keeps it, with the chosen image's own
                  seed and prompts;
  an infotext     Send on a Civitai image, or a generation recorded before
                  its press was kept (#7): Forge's own paste, run here, with
                  what Neo's paste gets wrong set right.

Not by pasting an infotext into the page. Forge sets some controls from which
keys a text holds - Hires fix is ticked when "Denoising strength" and "Hires
upscale" are there - so a task with Hires off, its values still kept, came
back with it on; and a key left out leaves its control as it is on screen.
Instead the button's function hands each control its value, rebuilt as for
a run (replay.rebuild), as Forge's own paste hands it a pasted one - hidden
controls too, which a press on the page cannot reach.

An infotext goes through Forge's own paste function (capture.paste_click),
so every key it knows, extensions' included, is set as Forge sets it - in
the same event, so nothing of the paste lands after what is corrected. What
Neo's paste loses is corrected: it reads a checkpoint as `name [hash]` where
its hires and refiner controls list paths, and drops every "Hires Module"
key. A record's own paths are used where it has them, with its refiner CFG,
which no infotext carries. Its outputs are the paste's controls besides
Generate's: Forge wires the paste after our tabs are built, so the function
is looked for when asked; not found, the page pastes as Forge does.

A control Generate takes only as a state - ControlNet's units - cannot be
shown that way, nor a value its control does not take: each keeps what is on
screen, and the answer names them for the page to say - a state only when
the task's differs from its default: three units left off, named on every
load, said nothing was lost. The checkpoint and the VAE / text encoders are
Forge's settings, not Generate's inputs: the page sets them as Send does,
from the send plan.

The page asks with JSON in a hidden textbox - what to load and a nonce - and
is answered in another, with the same nonce. The buttons are built with the
first of our tabs that Send serves (wire_send_buttons), not with the Queue
tab alone: a Send needs them with the queue off.
"""
import copy
import dataclasses
import enum
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..console import say
from ..db import get_models_db
from ..forge_host import (checkpoint_choice, generate_names, installed_modules,
                          parse_generation_parameters, paste_outputs)
from ..install import INSTALL_KEY
from ..tabs import on
from . import capture, replay

ASKED = "mm_load_{tab}_asked"
ANSWER = "mm_load_{tab}_answer"
BUTTON = "mm_load_{tab}"

# Whether this build of the UI has its hidden buttons yet: the first of our
# tabs built wires them, inside its Blocks.
_wired = False


class NoPaste(Exception):
    """Forge's paste function was not found, or did not answer as expected."""


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


def _values_for(tab: str, named: Dict[str, Any], skip: Any) -> Tuple[List[Any], List[str], List[str]]:
    """
    What each of Generate's inputs but the first - the id Forge gives a run
    - is set to for these named inputs: its value, or `skip` for a control
    that keeps what is on screen.

    Returns:
        (the values, the names of the controls skipped, the notes on inputs
        that took their default)
    """
    own = capture.generate_click(tab)
    if own is None:
        raise replay.TaskError(f"{tab}'s Generate was not found")
    components = list(own.inputs)
    values, notes = replay.rebuild(tab, components, named)
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


def task_values(tab: str, task_id: int, skip: Any = None) -> Tuple[List[Any], List[str], List[str]]:
    """A queued task's values for its tab: see _values_for."""
    task = get_models_db().get_task(task_id)
    if task is None or task.get("install") != INSTALL_KEY:
        raise replay.TaskError(f"No task #{task_id} in this WebUI")
    if task["mode"] != tab:
        raise replay.TaskError(f"Task #{task_id} is an {task['mode']} task")
    return _values_for(tab, task["inputs"], skip)


def for_image(tab: str, named: Dict[str, Any], image: Dict[str, Any]) -> Dict[str, Any]:
    """
    A generation's named inputs as one of its images was made: its own seed
    and subseed, its prompts as Forge ran them - styles merged in, wildcards
    chosen, so the styles are cleared - and a batch of one.
    """
    named = copy.deepcopy(named)
    fixed = named.setdefault("fixed", {})
    for key in ("prompt", "negative_prompt", "hr_prompt", "hr_negative_prompt"):
        if key in fixed and image.get(key) is not None:
            fixed[key] = image[key]
    if "prompt_styles" in fixed:
        fixed["prompt_styles"] = []
    for key in ("n_iter", "batch_size"):
        if key in fixed:
            fixed[key] = 1
    seeds = {f"{tab}_seed": image.get("seed"), f"{tab}_subseed": image.get("subseed")}
    for controls in (named.get("scripts") or {}).values():
        for control in controls:
            if control.get("id") in seeds and seeds[control["id"]] is not None:
                control["value"] = seeds[control["id"]]
    return named


def respelled(tab: str, named: Dict[str, Any], components: List[Any]) -> Tuple[Dict[str, Any], List[Tuple[Any, str]]]:
    """
    A generation's hires and refiner checkpoints as this WebUI's controls
    list them (#7). Two WebUIs sharing a database each see the other's
    generations, and spell a checkpoint differently - Neo by its folder and
    file, the original Forge by `name [hash]` - so the other's spelling set
    as it was left the control blank, read as "use the same".

    Returns:
        (the named inputs, respelled; each (control, name) of a checkpoint
        this WebUI does not have)
    """
    named = copy.deepcopy(named)
    gone: List[Tuple[Any, str]] = []

    def respell(control, value):
        if control is None or not isinstance(value, str) or not value or value == "None" \
                or value.startswith("Use same"):
            return value
        choice = checkpoint_choice(getattr(control, "choices", None) or [], name=value)
        if choice is None:
            gone.append((control, value))
            return value
        return choice

    fixed = named.get("fixed") or {}
    by_name = dict(zip(generate_names(tab), components))
    if "hr_checkpoint_name" in fixed:
        fixed["hr_checkpoint_name"] = respell(by_name.get("hr_checkpoint_name"), fixed["hr_checkpoint_name"])
    refiner = next((c for c in components if getattr(c, "elem_id", None) == f"{tab}_checkpoint"), None)
    for controls in (named.get("scripts") or {}).values():
        for entry in controls:
            if entry.get("id") == f"{tab}_checkpoint":
                entry["value"] = respell(refiner, entry.get("value"))
    return named, gone


def generation_values(tab: str, generation_id: int, image_id: Optional[int],
                      skip: Any = None) -> Tuple[List[Any], List[str], List[str]]:
    """
    One image of a generation of your own, for its tab: see _values_for. A
    checkpoint this WebUI does not have keeps what is on screen, and is named.
    """
    generation = get_models_db().get_generation(generation_id)
    if generation is None:
        raise replay.TaskError(f"No generation #{generation_id}")
    if generation.get("mode") != tab:
        raise replay.TaskError(f"Generation #{generation_id} is an {generation.get('mode')} generation")
    if not generation.get("inputs"):
        raise replay.TaskError(f"Generation #{generation_id} kept no inputs")
    images = generation.get("images") or []
    image = next((i for i in images if i.get("id") == image_id), images[0] if images else {})
    own = capture.generate_click(tab)
    components = list(own.inputs) if own is not None else []
    named, gone = respelled(tab, for_image(tab, generation["inputs"], image), components)
    shown, skipped, notes = _values_for(tab, named, skip)
    for control, name in gone:
        at = next((n for n, c in enumerate(components[1:]) if c is control), None)
        if at is not None:
            shown[at] = skip
            skipped.append(f"{getattr(control, 'label', None) or 'Checkpoint'}: {name} is not in this WebUI")
    return shown, skipped, notes


# ------------------------------------------------------------- an infotext

# A "Hires Module N" key of an infotext's settings line: Neo's paste drops
# them all, so they are read here.
_HIRES_MODULE = re.compile(r'(?:^|,\s*)Hires Module \d+: ("(?:[^"\\]|\\.)*"|[^,\n]*)')


def _module_labels(names: List[str], by_file: bool) -> Tuple[List[str], List[str]]:
    """The labels Forge offers for these modules - files, or names as an
    infotext writes them - and those it does not offer."""
    labels = list(installed_modules())
    found, missing = [], []
    for name in names:
        key = os.path.basename(name) if by_file else name
        match = next((l for l in labels if (l == key if by_file else os.path.splitext(l)[0] == key)), None)
        if match:
            found.append(match)
        else:
            missing.append(key)
    return found, missing


def corrections(tab: str, infotext: str, record: Optional[Dict[str, Any]],
                controls: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    What Neo's paste gets wrong, by control id: the hires checkpoint and VAE /
    text encoders, the refiner's checkpoint, and - from a record - its CFG
    scale. From a record's own paths where it kept them, else from the names
    the infotext gives. A value already right comes out the same. A file
    this WebUI lacks is named, and its control keeps what is on screen (None).

    Returns:
        ({control id: value, or None to keep}, the names of the files missing)
    """
    record = record or {}
    params = parse_generation_parameters(infotext or "")
    settings_line = (infotext or "").strip().split("\n")[-1]
    fixes: Dict[str, Any] = {}
    missing: List[str] = []

    def checkpoint(control_id: str, path: Optional[str], name: Optional[str]) -> None:
        control = controls.get(control_id)
        if control is None or not (path or name):
            return
        choice = checkpoint_choice(getattr(control, "choices", None) or [], name=name, path=path)
        fixes[control_id] = choice
        if choice is None:
            missing.append(os.path.basename(path) if path else name)

    named_hr = params.get("Hires checkpoint")
    if named_hr and str(named_hr).startswith("Use same"):
        named_hr = None
    checkpoint("hr_checkpoint", record.get("hr_checkpoint_path"), named_hr)
    checkpoint(f"{tab}_checkpoint", record.get("refiner_path"), params.get("Refiner"))

    if "hr_vae_te" in controls:
        if record.get("hr_modules") is not None:
            labels, gone = _module_labels(record["hr_modules"], by_file=True)
        else:
            written = [v.strip().strip('"') for v in _HIRES_MODULE.findall(settings_line)]
            if not written:
                labels, gone = None, []
            elif written[0] == "Use same choices":
                labels, gone = ["Use same choices"], []
            elif written[0] == "Built-in":
                labels, gone = [], []
            else:
                labels, gone = _module_labels(written, by_file=False)
        if labels is not None:
            fixes["hr_vae_te"] = labels
            missing += gone

    refiner_cfg = (record.get("params") or {}).get("refiner_cfg")
    if f"{tab}_cfg" in controls and record.get("refiner_path") and refiner_cfg is not None:
        fixes[f"{tab}_cfg"] = refiner_cfg
    return fixes, missing


def paste_values(tab: str, infotext: str, generation_id: Optional[int], outputs: List[Any],
                 skip: Any = None) -> Tuple[List[Any], List[str]]:
    """
    Forge's own paste of an infotext, for these outputs, corrected: each
    output's value, or `skip`. A generation's own paths correct it where
    the generation is named.

    Returns:
        (the values, the names of the files this WebUI does not have)
    """
    dep = capture.paste_click(tab)
    if dep is None:
        raise NoPaste(f"Forge's paste for {tab} was not found")
    updates = dep.fn(infotext)
    pasted = list(dep.outputs or [])
    if not isinstance(updates, (list, tuple)) or len(updates) != len(pasted):
        raise NoPaste(f"Forge's paste for {tab} answered {type(updates).__name__}, "
                      f"not a value for each of its {len(pasted)} controls")
    record = get_models_db().get_generation(int(generation_id)) if generation_id else None
    controls = {getattr(c, "elem_id", None): c for c in pasted if getattr(c, "elem_id", None)}
    fixes, missing = corrections(tab, infotext, record, controls)
    by_component = {id(c): u for c, u in zip(pasted, updates)}
    for control_id, value in fixes.items():
        by_component[id(controls[control_id])] = skip if value is None else value
    unset = [c for c in pasted if id(c) not in {id(o) for o in outputs}]
    if unset:
        say(f"Send: {len(unset)} of the controls Forge's paste sets on {tab} are not ours to set")
    return [by_component.get(id(o), skip) for o in outputs], missing


# -------------------------------------------------------------- the button

def _loader(tab: str, count: int, extras: List[Any] = ()) -> Callable:
    """The hidden button's function: `count` outputs of Generate's, then `extras`."""
    import gradio as gr
    outputs = None

    def load(asked: str):
        nonlocal outputs
        try:
            request = json.loads(asked or "{}")
        except ValueError:
            request = {}
        answer: Dict[str, Any] = {"nonce": request.get("nonce")}
        rest = [gr.update()] * len(extras)
        try:
            if request.get("paste") is not None:
                if outputs is None:
                    own = capture.generate_click(tab)
                    outputs = list(own.inputs[1:]) + list(extras)
                values, missing = paste_values(tab, request["paste"], request.get("generation"),
                                               outputs, skip=gr.update())
                answer.update({"pasted": True, "missing": missing})
                return [*values, json.dumps(answer)]
            if request.get("generation") is not None:
                answer["generation"] = request.get("generation")
                values, skipped, notes = generation_values(tab, int(request["generation"]),
                                                           request.get("image"), skip=gr.update())
            else:
                answer["task"] = request.get("task")
                values, skipped, notes = task_values(tab, int(request.get("task")), skip=gr.update())
            answer.update({"skipped": skipped, "notes": notes})
            return [*values, *rest, json.dumps(answer)]
        except NoPaste as e:
            say(f"Send: {e}; Forge's own paste is used")
            answer.update({"error": str(e), "no_paste": True})
        except Exception as e:
            what = "task" if "task" in answer else ("generation" if "generation" in answer else "infotext")
            say(f"Could not load the {what} into {tab}: {e}")
            answer["error"] = str(e)
        return [*([gr.update()] * count), *rest, json.dumps(answer)]

    return load


def wire_load_buttons() -> None:
    """
    For each tab whose Generate was found, the hidden button that sets its
    controls back: Generate's inputs, then the other controls Forge's paste
    sets. Called inside a Blocks our tabs build.
    """
    import gradio as gr
    for tab in capture.TABS:
        own = capture.generate_click(tab)
        if own is None:
            continue
        outputs = list(own.inputs[1:])
        taken = {id(c) for c in outputs}
        try:
            extras = [c for c in paste_outputs(tab) if id(c) not in taken]
        except Exception as e:
            say(f"Send: Forge's paste fields for {tab} could not be read: {e}")
            extras = []
        asked = gr.Textbox(visible=False, elem_id=ASKED.format(tab=tab))
        answer = gr.Textbox(visible=False, elem_id=ANSWER.format(tab=tab))
        button = gr.Button(visible=False, elem_id=BUTTON.format(tab=tab))
        button.click(fn=_loader(tab, len(outputs), extras), inputs=[asked],
                     outputs=outputs + extras + [answer], show_progress="hidden")


def new_build() -> None:
    """The UI is being built again - at start, or Settings -> Reload UI."""
    global _wired
    _wired = False


def wire_send_buttons() -> None:
    """
    What Send needs beside Generate, once per build, inside the first of our
    tabs built: the hidden loaders, and - while generations are recorded -
    our listener that keeps each press's inputs (capture.py).
    """
    global _wired
    if _wired:
        return
    _wired = True
    wire_load_buttons()
    if on("generations"):
        capture.wire_generate_record()
