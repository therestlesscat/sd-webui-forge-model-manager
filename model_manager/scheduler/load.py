"""
Setting a tab's controls back from what we keep - one hidden button per tab,
whose outputs are Generate's own inputs. The page names a Send's source
(#302), and the button sets it back:

  a task          Load to UI (#160): a queued task, to change it or run it
                  by hand;
  a generation    Send on one of your own generations (#7): what its press
                  was sent, as a task keeps it, with the chosen image's own
                  seed and prompts - or, recorded before its press was kept
                  or not set back, its infotext pasted;
  a Civitai image the infotext the server builds from its stored record
                  (send.civitai_settings), pasted.

A text is pasted through Forge's own paste function, run here, with what
Neo's paste gets wrong set right, and the schedule type and Hires fix set
in the same event (after_paste).

Not by pasting an infotext into the page. Forge sets some controls from which
keys a text holds - Hires fix is ticked when "Denoising strength" and "Hires
upscale" are there - so a task with Hires off, its values still kept, came
back with it on; and a key left out leaves its control as it is on screen.
Instead the button's function hands each control its value, rebuilt as for
a run (replay.rebuild), as Forge's own paste hands it a pasted one - hidden
controls too, which a press on the page cannot reach.

img2img's canvases are set apart (#299): its button sets every other control,
and a button per mode that takes a picture sets that mode's canvases - a
picture sent in from the ⋯ menu (one of your generations' files, or a Civitai
original the server fetches), its layer emptied, or a press's or a task's
kept canvases (#34). `into`, on the first, names the mode a picture goes to.

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
import io
import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import generation_inputs
from ..civitai.images import is_image_address
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
    # The canvases of every img2img mode but the press's own keep what is on
    # screen, as Forge's own send buttons leave them (#34): nothing of them is
    # kept, and setting them meant emptying them.
    fixed_names = generate_names(tab)
    used = set(generation_inputs.mode_images(tab, named.get("fixed") or {}))
    others = {at for at, name in enumerate(fixed_names)
              if name in generation_inputs.CANVASES and name not in used}
    if others:
        left = tuple(f"{fixed_names[at]}:" for at in others)
        notes = [note for note in notes if not note.startswith(left)]
    shown, skipped = [], []
    for at in range(1, len(components)):
        component = components[at]
        value = _shown(component, values[at])
        if at in others:
            shown.append(skip)
        elif type(component).__name__ == "State":
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
        (the values, the names of the files this WebUI does not have, and
        what else the text names that it does not offer - `unavailable`)
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
    return [by_component.get(id(o), skip) for o in outputs], missing, unavailable(tab, infotext, controls)


def unavailable(tab: str, infotext: str, controls: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    What a pasted infotext names that this WebUI does not offer (#307), each
    with its kind: the sampler and schedule type by Send's matching
    (send.missing_names), Hires fix's upscaler and each ADetailer tab's
    detector by their dropdowns' choices, where this WebUI draws them. Only
    said: what Forge's paste set stays as it is - each changes the
    generation, and is the user's to choose.
    """
    from .. import send
    params = parse_generation_parameters(infotext or "")
    names = send.missing_names(params, *send.forge_lists())
    upscaler, given = controls.get(f"{tab}_hr_upscaler"), params.get("Hires upscaler")
    if upscaler is not None and given and not _offers(upscaler, given):
        names.append({"name": str(given), "kind": "Hires upscaler"})
    # ADetailer's tabs: `ad_model`, `ad_model_2nd`, ... read from
    # `ADetailer model`, `ADetailer model 2nd`, ... - an ordinal, not
    # `ad_model_classes`, its detector's classes.
    for control_id, control in controls.items():
        tab_of = re.fullmatch(rf"script_{tab}_adetailer_ad_model(?:_(\d+(?:st|nd|rd|th)))?", control_id or "")
        if tab_of:
            nth = tab_of.group(1)
            given = params.get("ADetailer model" + (f" {nth}" if nth else ""))
            if given and given != "None" and not _offers(control, given):
                names.append({"name": str(given), "kind": f"ADetailer {nth} detector" if nth else "ADetailer detector"})
    return names


def _offers(component, label: str) -> bool:
    """Whether a dropdown offers this choice, by its label or its value."""
    for choice in getattr(component, "choices", None) or []:
        pair = choice if isinstance(choice, (list, tuple)) else (choice, choice)
        if label in pair[:2]:
            return True
    return False


def after_paste(tab: str, values: List[Any], outputs: List[Any], names: List[Optional[str]],
                scheduler: str, hires: bool) -> None:
    """
    What a Civitai image's Send set after Forge's paste, set in the paste's
    own event (#302): the schedule type - the image's, else Automatic, where
    the dropdown offers it, as the page chose one only from its list - and,
    in txt2img, Hires fix off for an image made without it, which the paste
    leaves as it was on screen. `values` stands for `outputs`; `names` names
    the first of them, Generate's own.
    """
    at = next((n for n, c in enumerate(outputs) if getattr(c, "elem_id", None) == f"{tab}_scheduler"), None)
    if at is not None and _offers(outputs[at], scheduler):
        values[at] = scheduler
    if tab == "txt2img" and not hires and "enable_hr" in names:
        values[names.index("enable_hr")] = False


# ------------------------------------------------------- a picture sent in

# A Civitai original fetched for img2img (#299): at most this big, this long.
PICTURE_LIMIT = 50 * 1024 * 1024
PICTURE_SECONDS = 30


def _picture(asked: Dict[str, Any], get: Optional[Callable] = None):
    """
    The picture a send into img2img puts in its mode's canvas (#299): one of
    your generations' files, by its image's id, or a Civitai original by its
    address - Civitai's image server alone, over https, within 30 s and 50
    MB. As RGB, as Forge's own Send buttons hand one. Raises TaskError,
    saying why, when there is none to be had.
    """
    from PIL import Image
    if asked.get("generation_image") is not None:
        path = get_models_db().get_generation_image_path(int(asked["generation_image"]))
        if not path or not os.path.isfile(path):
            raise replay.TaskError("The image file is gone: deleted or moved")
        with Image.open(path) as image:
            image.load()
            picture = image.copy()
    else:
        url = str(asked.get("url") or "")
        if not is_image_address(url):
            raise replay.TaskError("Only Civitai's image server is asked for an image")
        if get is None:
            import requests
            get = requests.get
        until = time.monotonic() + PICTURE_SECONDS
        body = bytearray()
        try:
            with get(url, stream=True, timeout=PICTURE_SECONDS) as response:
                response.raise_for_status()
                for chunk in response.iter_content(1 << 16):
                    body += chunk
                    if len(body) > PICTURE_LIMIT:
                        raise replay.TaskError("The image is larger than 50 MB")
                    if time.monotonic() > until:
                        raise replay.TaskError(f"Civitai took more than {PICTURE_SECONDS} s to send the image")
        except replay.TaskError:
            raise
        except Exception as e:
            raise replay.TaskError(f"Could not fetch the image from Civitai: {e}")
        try:
            with Image.open(io.BytesIO(bytes(body))) as image:
                image.load()
                picture = image.copy()
        except Exception:
            raise replay.TaskError("What Civitai sent is not an image")
    return picture if picture.mode == "RGB" else picture.convert("RGB")


def _into(values: List[Any], names: List[Optional[str]], into: Dict[str, Any], sized: bool) -> int:
    """
    A send into img2img's mode (#299), over the settings button's values -
    `names` the input each stands for: `mode` that mode, and width and height
    the picture's, as the page gives them, when the settings gave none
    (`sized`). The picture itself goes in through the mode's canvas button.
    Returns the mode.
    """
    mode = int(into.get("mode"))
    if mode not in generation_inputs.MODE_IMAGES:
        raise replay.TaskError(f"img2img's mode {mode} takes no picture")
    at = {name: n for n, name in enumerate(names) if name}
    values[at["mode"]] = mode
    if not sized and into.get("width") and into.get("height"):
        values[at["width"]] = int(into["width"])
        values[at["height"]] = int(into["height"])
    return mode


# -------------------------------------------------------------- the buttons
# img2img's canvases are never among the settings button's outputs (#299):
# for each output it does not set, a button answers "leave as is", and for
# each such answer Gradio puts a copy of that control into the page's
# session, rebuilt from what it was made with. A canvas's copy reads
# pictures as arrays (numpy=True) where Forge made it with numpy=False, and
# the next picture any event handed it failed in Forge's canvas - this
# send's, #34's, Forge's own Send to img2img. A picture goes in through a
# button of its mode's own, which hands each of its canvases a value.

CANVAS_ASKED = "mm_load_img2img_canvas_asked"
CANVAS_ANSWER = "mm_load_img2img_canvas_answer"
CANVAS_BUTTON = "mm_load_img2img_canvas_{mode}"


def _input_names(tab: str, inputs: List[Any]) -> List[Optional[str]]:
    """The name of each of Generate's inputs but the first, in order: None for a script's."""
    names = generate_names(tab)
    return [names[n] if n < len(names) else None for n in range(1, len(inputs))]


def _canvas_answer(tab: str, request: Dict[str, Any]) -> Dict[str, Any]:
    """
    For img2img, the mode the press was made in - the page shows it, and
    asks its canvas button for the press's canvases - and whether its source
    is kept (#34).
    """
    db = get_models_db()
    if request.get("generation") is not None:
        named = (db.get_generation(int(request["generation"])) or {}).get("inputs")
    else:
        named = (db.get_task(int(request.get("task"))) or {}).get("inputs")
    fixed = (named or {}).get("fixed") or {}
    return {"mode": generation_inputs.mode_of(fixed), "source": generation_inputs.source_back(tab, named)}


def canvas_values(mode: int, request: Dict[str, Any]) -> List[Any]:
    """
    What a mode's canvases get - its picture, then its layer or mask - from
    a request to its canvas button: a picture sent in (#299), its layer
    empty; or the canvases a press of yours or a queued task kept (#34),
    each nothing where none was kept.
    """
    names = generation_inputs.MODE_IMAGES[mode]
    if request.get("picture") is not None:
        return [_picture(request["picture"])] + [None] * (len(names) - 1)
    db = get_models_db()
    if request.get("generation") is not None:
        named = (db.get_generation(int(request["generation"])) or {}).get("inputs") or {}
    else:
        task = db.get_task(int(request.get("task")))
        if task is None or task.get("install") != INSTALL_KEY:
            raise replay.TaskError(f"No task #{request.get('task')} in this WebUI")
        named = task.get("inputs") or {}
    opened = generation_inputs.from_files(named.get("fixed") or {}, names)
    return [opened.get(name) for name in names]


def _canvas_loader(mode: int) -> Callable:
    """A canvas button's function: its mode's canvases, then the answer - never "leave as is"."""
    count = len(generation_inputs.MODE_IMAGES[mode])

    def load(asked: str):
        try:
            request = json.loads(asked or "{}")
        except ValueError:
            request = {}
        answer: Dict[str, Any] = {"nonce": request.get("nonce"), "mode": mode}
        try:
            values = canvas_values(mode, request)
            answer["source"] = values[0] is not None
            return [*values, json.dumps(answer)]
        except Exception as e:
            say(f"Could not put the picture into img2img: {e}")
            answer["error"] = str(e)
        return [*([None] * count), json.dumps(answer)]

    return load


def _loader(tab: str, kept: List[int], extras: List[Any] = (), names: List[Optional[str]] = ()) -> Callable:
    """
    The settings button's function: Generate's outputs at `kept` - all of
    them for txt2img; for img2img all but its canvases - then `extras`.
    `names` names each kept output.
    """
    import gradio as gr
    outputs = None
    count = len(kept)

    def kept_only(values: List[Any]) -> List[Any]:
        return [values[n] for n in kept]

    def load(asked: str):
        nonlocal outputs
        try:
            request = json.loads(asked or "{}")
        except ValueError:
            request = {}
        answer: Dict[str, Any] = {"nonce": request.get("nonce")}
        rest = [gr.update()] * len(extras)
        into = request.get("into") if tab == "img2img" else None
        try:
            # A task's source is its id: set back from what it was queued with.
            if (request.get("source") or {}).get("kind") == "task":
                request = {**request, "task": request["source"].get("task")}
                request.pop("source")
            # A Civitai image's Send, or a generation's (#302): its text is
            # built here - a Civitai image's from its stored record, a
            # generation's its own with the chips' renames - and pasted, and
            # what the page set after the paste, the schedule type and Hires
            # fix off, in the same event. A generation's kept press (#7) is
            # replayed instead, and a replay that fails is pasted.
            if request.get("source") is not None:
                from ..send import renamed, settings
                source = request["source"]
                generation_id = int(source["generation"]) if source.get("kind") == "generation" else None
                found = settings(get_models_db(), source, bool(into))
                if found is None:
                    raise replay.TaskError(f"No generation #{generation_id}" if generation_id is not None
                                           else "The image is not in the library")
                if found.get("replay"):
                    try:
                        values, skipped, notes = generation_values(tab, generation_id, source.get("image"),
                                                                   skip=gr.update())
                        values = kept_only(values)
                        # The chips' renames, in the prompt the press is set back with.
                        at = list(names).index("prompt") if "prompt" in names else None
                        if at is not None and isinstance(values[at], str):
                            values[at] = renamed(values[at], source.get("renames"))
                        answer.update({"replayed": True, "generation": generation_id,
                                       "skipped": skipped, "notes": notes})
                        if into:
                            answer.update({"mode": _into(values, list(names), into, True)})
                        elif tab == "img2img":
                            answer.update(_canvas_answer(tab, {"generation": generation_id}))
                        return [*values, *rest, json.dumps(answer)]
                    except Exception as e:
                        say(f"Send: generation #{generation_id} could not be set back as it was; pasting: {e}")
                # For Forge's own paste button, where its paste function is missing.
                answer.update({"text": found["text"], "scheduler": found["scheduler"], "hires": found["hires"]})
                if not found["text"]:
                    # Nothing to paste - Forge's paste of an empty text pastes the
                    # last run's settings (params.txt): into img2img the picture
                    # alone goes in (#299).
                    values = [gr.update()] * count
                    if into:
                        answer.update({"mode": _into(values, list(names), into, False)})
                    else:
                        answer["empty"] = True
                    return [*values, *rest, json.dumps(answer)]
                if outputs is None:
                    own = capture.generate_click(tab)
                    outputs = kept_only(list(own.inputs[1:])) + list(extras)
                values, missing, lacking = paste_values(tab, found["text"], generation_id, outputs, skip=gr.update())
                after_paste(tab, values, outputs, list(names), found["scheduler"], found["hires"])
                answer.update({"pasted": True, "missing": missing, "unavailable": lacking})
                if into:
                    sized = "Size-1" in parse_generation_parameters(found["text"])
                    answer.update({"mode": _into(values, list(names), into, sized)})
                return [*values, json.dumps(answer)]
            # A task, set back from what it was queued with.
            answer["task"] = request.get("task")
            values, skipped, notes = task_values(tab, int(request.get("task")), skip=gr.update())
            values = kept_only(values)
            answer.update({"skipped": skipped, "notes": notes})
            if into:
                answer.update({"mode": _into(values, list(names), into, True)})
            elif tab == "img2img":
                answer.update(_canvas_answer(tab, request))
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
    controls back: Generate's inputs - for img2img, but its canvases - then
    the other controls Forge's paste sets. For img2img, a canvas button per
    mode that takes a picture. Called inside a Blocks our tabs build.
    """
    import gradio as gr
    for tab in capture.TABS:
        own = capture.generate_click(tab)
        if own is None:
            continue
        inputs = list(own.inputs[1:])
        names = _input_names(tab, list(own.inputs))
        kept = [n for n, name in enumerate(names) if name not in generation_inputs.CANVASES]
        taken = {id(c) for c in inputs}
        try:
            extras = [c for c in paste_outputs(tab) if id(c) not in taken]
        except Exception as e:
            say(f"Send: Forge's paste fields for {tab} could not be read: {e}")
            extras = []
        asked = gr.Textbox(visible=False, elem_id=ASKED.format(tab=tab))
        answer = gr.Textbox(visible=False, elem_id=ANSWER.format(tab=tab))
        button = gr.Button(visible=False, elem_id=BUTTON.format(tab=tab))
        button.click(fn=_loader(tab, kept, extras, [names[n] for n in kept]), inputs=[asked],
                     outputs=[inputs[n] for n in kept] + extras + [answer], show_progress="hidden")
        if tab != "img2img":
            continue
        by_name = {name: inputs[n] for n, name in enumerate(names) if name}
        canvas_asked = gr.Textbox(visible=False, elem_id=CANVAS_ASKED)
        canvas_answer = gr.Textbox(visible=False, elem_id=CANVAS_ANSWER)
        for mode, canvases in generation_inputs.MODE_IMAGES.items():
            if not all(name in by_name for name in canvases):
                continue
            canvas_button = gr.Button(visible=False, elem_id=CANVAS_BUTTON.format(mode=mode))
            canvas_button.click(fn=_canvas_loader(mode), inputs=[canvas_asked],
                                outputs=[by_name[name] for name in canvases] + [canvas_answer],
                                show_progress="hidden")


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
