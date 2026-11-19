"""
ComfyUI's graph, read into plain fields (#232): one reader, for Sync images
and for Civitai's stored images alike.

ComfyUI saves a workflow in two versions. The run version - the graph it
actually runs, a PNG's `prompt` chunk, Civitai's `comfy` -> `prompt` - names
each node's class (`class_type`) and its inputs by name, a wire written as
`[node, output]`. That is what `read` reads. The editor version - the canvas
as drawn, a PNG's `workflow` chunk - holds each node's settings as an unnamed
list in the node's own order; `turn` gives it the run version's shape, and
`read_editor` reads it so (see `turn`). `read_either` reads the run version
where there is one, the editor version only where there is not.

A read finds the node that saved the picture (`SaveImage`, else
`PreviewImage`) and follows the picture back to a sampler: through the nodes
in `_PICTURE`, and through any other node with one wired picture input - a
detailer, a sharpen, an upscale on the picture - which works on a picture an
earlier node made. A node with two (a blend) or none ends the way. Where that
chain passes several samplers - a hires pass, an upscale - the image's
settings are the first pass's: the sampler whose latent comes from an empty
latent, or in an img2img graph, which has none, the sampler farthest back.
Save nodes that lead to no sampler (a mask, a loaded picture) are passed
over; the rest must lead back to one first pass, or nothing is read. Every
field is then followed from that sampler, each only where a wire leads to a
value: a node not on this module's lists ends that field's walk, and nothing
is guessed.

A graph is untrusted data. A whole number longer than 20 digits is no value
(Neo's Python refuses one past 4,300 digits and the original Forge's does
not, so one file would read two ways); JSON nested deeper than Python allows
is no graph; each walk is a loop that keeps the nodes it has seen and stops at
a repeat, and a graph over `NODE_LIMIT` nodes is not read.

The answer is one dict under the reader's own names - `prompt`, `negative`,
`sampler`, `scheduler`, `steps`, `cfg`, `seed`, `distilled_cfg`, `shift`,
`width`, `height`, `checkpoint`, `vae`, `text_encoders`, `loras` and
`source` - each present only where read. Sampler and schedule type are kept
as ComfyUI names them (`dpmpp_2m`, `karras`): Send matches them to Forge's.

A Civitai image's data is filled from its graph where Civitai left a field
out (`fill`): where it is shown and sent always, and where it is judged,
stored and searched once the switch is on (`judged`).
"""
import hashlib
import json
import math
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# The largest graph among one library's 4,826 is 243 nodes; a graph many times
# that is not a workflow worth walking.
NODE_LIMIT = 2000

# Longer whole numbers are no value: a wire's output index and a seed (ComfyUI's
# runs to 2^64 - 1, 20 digits) fit.
_DIGITS = 20

_SAVE = ("SaveImage",)
_PREVIEW = ("PreviewImage",)

# What the picture's way back passes, each by the input it follows: the decoder,
# an upscale of the picture and one of the latent, an encoder of a picture.
_PICTURE = {
    "VAEDecode": "samples", "VAEDecodeTiled": "samples",
    "ImageUpscaleWithModel": "image", "ImageScale": "image", "ImageScaleBy": "image",
    "LatentUpscale": "samples", "LatentUpscaleBy": "samples",
    "VAEEncode": "pixels", "VAEEncodeTiled": "pixels",
}
# Any other node is passed by its one wired input of these names.
_PICTURE_INPUTS = ("image", "images", "pixels", "samples")
_DECODERS = ("VAEDecode", "VAEDecodeTiled")
_EMPTY_LATENTS = ("EmptyLatentImage", "EmptySD3LatentImage")

_K_SAMPLERS = ("KSampler", "KSamplerAdvanced")
_CUSTOM_SAMPLERS = ("SamplerCustom", "SamplerCustomAdvanced")
_SAMPLERS = _K_SAMPLERS + _CUSTOM_SAMPLERS

# A text encoder's text, by the first of these inputs it has: SDXL's `text_g`,
# Flux's and SD3's `t5xxl`.
_ENCODER_TEXT = ("text", "text_g", "t5xxl", "clip_l", "clip_g")
# Nodes that pass one conditioning on unchanged, by the input they follow; a
# ControlNet apply and the like follow the side they are on.
_CONDITIONING = ("FluxGuidance", "ConditioningSetArea", "ConditioningSetAreaPercentage",
                 "ConditioningSetAreaStrength", "ConditioningSetMask", "ConditioningSetTimestepRange",
                 "ControlNetApply", "ControlNetApplyAdvanced", "ControlNetApplySD3")
_ZERO = ("ConditioningZeroOut",)

# What the model's way passes: LoRA loaders, read as it passes them, and patches
# that change no file loaded.
_LORA_LOADERS = ("LoraLoader", "LoraLoaderModelOnly")
_POWER_LORA = ("Power Lora Loader (rgthree)",)
_MODEL_PATCHES = ("ModelSamplingFlux", "ModelSamplingSD3", "ModelSamplingAuraFlow", "ModelSamplingDiscrete",
                  "RescaleCFG", "DifferentialDiffusion", "PatchModelAddDownscale", "FreeU", "FreeU_V2",
                  "CFGNorm", "SkipLayerGuidanceDiT", "PerturbedAttentionGuidance", "TorchCompileModel")
_SHIFTS = ("ModelSamplingSD3", "ModelSamplingAuraFlow")
_CHECKPOINTS = {"CheckpointLoaderSimple": "ckpt_name", "UNETLoader": "unet_name", "UnetLoaderGGUF": "unet_name"}
_CLIP_PASS = ("CLIPSetLastLayer",)
_CLIP_LOADERS = {"CLIPLoader": ("clip_name",), "DualCLIPLoader": ("clip_name1", "clip_name2"),
                 "TripleCLIPLoader": ("clip_name1", "clip_name2", "clip_name3")}

# Nodes that hand on text: a concatenation, joined with its own separator.
_CONCAT = {"StringConcatenate": ("string_a", "string_b", "delimiter")}

_TOO_LONG = object()

# The editor version's settings, by place, for the core nodes the reader
# follows: each list a length the class is written with - an extension adds a
# widget, an older frontend leaves `device` out - read from one library's 4,240
# records holding both versions. `_` is a place nothing is read from. A list of
# any other length gives its node no settings.
_WIDGETS = {
    "KSampler": [["seed", "_", "steps", "cfg", "sampler_name", "scheduler", "denoise"]],
    "KSamplerAdvanced": [["add_noise", "noise_seed", "_", "steps", "cfg", "sampler_name", "scheduler",
                          "start_at_step", "end_at_step", "return_with_leftover_noise"]],
    "SamplerCustom": [["add_noise", "noise_seed", "_", "cfg"]],
    "KSamplerSelect": [["sampler_name"]],
    "BasicScheduler": [["scheduler", "steps", "denoise"]],
    "RandomNoise": [["noise_seed", "_"]],
    "CFGGuider": [["cfg"]],
    "FluxGuidance": [["guidance"]],
    "CheckpointLoaderSimple": [["ckpt_name"], ["ckpt_name", "_"]],
    "UNETLoader": [["unet_name", "weight_dtype"]],
    "UnetLoaderGGUF": [["unet_name"]],
    "VAELoader": [["vae_name"], ["vae_name", "_"]],
    "CLIPLoader": [["clip_name", "type"], ["clip_name", "type", "device"]],
    "DualCLIPLoader": [["clip_name1", "clip_name2", "type"], ["clip_name1", "clip_name2", "type", "device"]],
    "TripleCLIPLoader": [["clip_name1", "clip_name2", "clip_name3"]],
    "CLIPSetLastLayer": [["stop_at_clip_layer"]],
    "LoraLoader": [["lora_name", "strength_model", "strength_clip"]],
    "LoraLoaderModelOnly": [["lora_name", "strength_model"]],
    "CLIPTextEncode": [["text"], ["text", "_"]],
    "CLIPTextEncodeSDXL": [["width", "height", "crop_w", "crop_h", "target_width", "target_height",
                            "text_g", "text_l"]],
    "CLIPTextEncodeFlux": [["clip_l", "t5xxl", "guidance"], ["clip_l", "t5xxl", "guidance", "_", "_"]],
    "EmptyLatentImage": [["width", "height", "batch_size"]],
    "EmptySD3LatentImage": [["width", "height", "batch_size"]],
    "ModelSamplingSD3": [["shift"]],
    "ModelSamplingAuraFlow": [["shift"], ["shift", "_"]],
    "ModelSamplingFlux": [["max_shift", "base_shift", "width", "height"]],
    "StringConcatenate": [["string_a", "string_b", "delimiter"]],
    "PrimitiveStringMultiline": [["value"], ["value", "_"]],
    "PrimitiveInt": [["value", "_"]],
    "PrimitiveFloat": [["value"]],
    # Nodes holding one value, as the graphs measured hold them.
    "Seed (rgthree)": [["seed", "_", "_", "_"], ["seed", "_", "_", "_", "_"]],
    "Seed String": [["seed", "_"]], "SeedNode": [["seed", "_"]], "Seed Generator": [["seed", "_"]],
    "Seed Everywhere": [["seed", "_"]], "easy seed": [["seed", "_", "_"]],
    "Int": [["value"]], "ImpactInt": [["value"]],
    "Text Multiline": [["text"], ["text", "_"]], "CR Prompt Text": [["prompt"], ["prompt", "_"]],
    "CR Text": [["text"], ["text", "_"]], "String Literal": [["string"]], "ttN text": [["text"]],
}
# The editor's own nodes, which ComfyUI resolves before it runs a graph; and
# KJNodes' named wires, a SetNode taking a wire and each GetNode of its name
# giving it on, which its page resolves the same way.
_REROUTE = "Reroute"
_SET, _GET = "SetNode", "GetNode"
_PRIMITIVE = "PrimitiveNode"
_MUTED, _BYPASSED = 2, 4
# A choice ComfyUI's page resolves before it runs a prompt, `{red|blue}`: the
# editor version keeps the choice, the run version the pick.
_CHOICE = re.compile(r"\{[^{}]*\|[^{}]*\}")


def loads(text: Any) -> Optional[Dict[str, Any]]:
    """A graph handed as text, parsed: a whole number past 20 digits kept as no
    value, JSON nested too deep or not an object as no graph. A dict is taken
    as it is."""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return None
    try:
        value = json.loads(text, parse_int=lambda d: int(d) if len(d.lstrip("-")) <= _DIGITS else _TOO_LONG)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def stem(name: Any) -> Optional[str]:
    """A file's name without its folder or extension, the folder split on
    either slash: a file saved on Windows (`SDXL\\model.safetensors`) reads the
    same under Linux."""
    base = file_name(name)
    if not base:
        return None
    dot = base.rfind(".")
    return base[:dot] if dot > 0 else base


def file_name(name: Any) -> Optional[str]:
    """A file's name without its folder, split on either slash."""
    if not isinstance(name, str) or not name.strip():
        return None
    return name.replace("\\", "/").rsplit("/", 1)[-1].strip() or None


class _Graph:
    """One run graph: its nodes by id, and the walks over them."""

    def __init__(self, nodes: Dict[str, Any]):
        self.nodes = {str(k): v for k, v in nodes.items() if isinstance(v, dict)}
        self._nested: Dict[int, str] = {}

    def node(self, wire: Any) -> Optional[Dict[str, Any]]:
        """The node a wire leads to, or None for a value or a broken wire. Some
        of Civitai's copies write a wire as the node itself, nested in place
        (`{"class_type": ..., "inputs": {...}}`): that node is the one."""
        if isinstance(wire, list) and len(wire) == 2 and isinstance(wire[1], int):
            return self.nodes.get(str(wire[0]))
        if isinstance(wire, dict) and "class_type" in wire:
            return wire
        return None

    def at(self, wire: Any) -> Optional[tuple]:
        """The node a wire leads to with its id, or None. A nested node is known
        by its content: JSON shares no object, so each way to one node holds a
        copy of it, and two copies of one sampler are one first pass."""
        node = self.node(wire)
        if node is None:
            return None
        if isinstance(wire, list):
            return str(wire[0]), node
        key = self._nested.get(id(node))
        if key is None:
            text = json.dumps(node, sort_keys=True, default=str)
            key = "nested:" + hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
            self._nested[id(node)] = key
            self.nodes.setdefault(key, node)
        return key, node

    @staticmethod
    def kind(node: Optional[Dict[str, Any]]) -> Optional[str]:
        """A node's class, where it is text: any other is no class the reader
        knows, never an error."""
        kind = node.get("class_type") if node else None
        return kind if isinstance(kind, str) else None

    @staticmethod
    def inputs(node: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        found = node.get("inputs") if node else None
        return found if isinstance(found, dict) else {}

    # -------------------------------------------------------------- values

    def value(self, raw: Any, want: str) -> Any:
        """A setting's value: written straight into the node, or a wire to a
        node holding one value of the kind wanted and nothing else. `want` is
        "int", "number" or "text"."""
        if self.node(raw) is not None:
            held = [v for v in self.inputs(self.node(raw)).values()]
            if len(held) != 1 or self.node(held[0]) is not None:
                return None
            raw = held[0]
        if raw is _TOO_LONG or isinstance(raw, bool):
            return None
        if want == "text":
            return raw if isinstance(raw, str) else None
        if isinstance(raw, int):
            return raw if abs(raw) < 10 ** _DIGITS else None
        if want == "number" and isinstance(raw, float):
            return raw if math.isfinite(raw) else None
        return None

    def text(self, raw: Any) -> Optional[str]:
        """A prompt's text: written in, a wire to a node holding one text, or a
        concatenation of such, joined with its own separator. Worked through as
        a loop, not a recursion, and bounded: a concatenation that leads back
        into itself, or one asking more than four reads a node, gives none."""
        results: List[Optional[str]] = []
        work: List[tuple] = [("read", raw)]
        steps = 0
        while work:
            steps += 1
            if steps > 4 * NODE_LIMIT:
                return None
            task = work.pop()
            if task[0] == "join":
                _, joint, count = task
                parts = results[-count:]
                del results[-count:]
                results.append(None if any(p is None for p in parts)
                               else joint.join(p for p in parts if p is not None))
                continue
            _, wire = task
            hit = self.at(wire)
            parts = _CONCAT.get(self.kind(hit[1])) if hit else None
            if not parts:
                results.append(self.value(wire, "text"))
                continue
            inputs = self.inputs(hit[1])
            joint = self.value(inputs.get(parts[-1], ""), "text") or ""
            work.append(("join", joint, len(parts) - 1))
            for name in reversed(parts[:-1]):
                work.append(("read", inputs.get(name)))
        return results[-1] if results else None

    # ------------------------------------------------- the picture's way back

    def saves(self) -> List[Dict[str, Any]]:
        found = [n for n in self.nodes.values() if self.kind(n) in _SAVE]
        return found or [n for n in self.nodes.values() if self.kind(n) in _PREVIEW]

    def picture_input(self, node: Dict[str, Any]) -> Optional[str]:
        """The input a picture's way back follows through a node: its own in
        _PICTURE, else its one wired picture input; None for two or none."""
        follow = _PICTURE.get(self.kind(node))
        if follow:
            return follow
        wired = [k for k in _PICTURE_INPUTS if self.node(self.inputs(node).get(k)) is not None]
        return wired[0] if len(wired) == 1 else None

    def back_to_sampler(self, wire: Any, seen: Set[str]) -> Optional[str]:
        """The sampler a picture's or a latent's wire leads back to, by its id;
        None where a node ends the way (picture_input)."""
        while True:
            hit = self.at(wire)
            if hit is None or hit[0] in seen:
                return None
            key, node = hit
            seen.add(key)
            if self.kind(node) in _SAMPLERS:
                return key
            follow = self.picture_input(node)
            if not follow:
                return None
            wire = self.inputs(node).get(follow)

    def decoder_on_way(self, wire: Any) -> Optional[Dict[str, Any]]:
        """The first decoder on a picture's way back, for its VAE."""
        seen: Set[str] = set()
        while True:
            hit = self.at(wire)
            if hit is None or hit[0] in seen or self.kind(hit[1]) in _SAMPLERS:
                return None
            key, node = hit
            seen.add(key)
            if self.kind(node) in _DECODERS:
                return node
            follow = self.picture_input(node)
            if not follow:
                return None
            wire = self.inputs(node).get(follow)

    def first_pass(self, sampler: str) -> Dict[str, Any]:
        """From a sampler back along its latent: the first pass - the sampler fed
        by an empty latent, with that latent node, whatever passes it on between
        (a batch repeat) - or, where none is, the sampler farthest back, with
        none."""
        seen = {sampler}
        wire = self.inputs(self.nodes[sampler]).get("latent_image")
        while True:
            hit = self.at(wire)
            if hit is None or hit[0] in seen:
                return {"sampler": sampler, "latent": None}
            key, node = hit
            seen.add(key)
            if self.kind(node) in _EMPTY_LATENTS:
                return {"sampler": sampler, "latent": node}
            if self.kind(node) in _SAMPLERS:
                sampler, wire = key, self.inputs(node).get("latent_image")
                continue
            follow = self.picture_input(node)
            if not follow:
                return {"sampler": sampler, "latent": None}
            wire = self.inputs(node).get(follow)

    # ------------------------------------------------------- the sampler's way

    def walk(self, wire: Any, step) -> Any:
        """Follow a wire node by node: `step(node)` answers ("done", value),
        ("next", wire) or ("stop", None). A repeat stops it."""
        seen: Set[str] = set()
        while True:
            hit = self.at(wire)
            if hit is None or hit[0] in seen:
                return None
            key, node = hit
            seen.add(key)
            what, found = step(node)
            if what == "done":
                return found
            if what != "next":
                return None
            wire = found


def read(graph: Any) -> Dict[str, Any]:
    """The fields a run graph gives, under the reader's own names; {} where
    it gives none. `graph` is the graph as text or as a dict."""
    nodes = loads(graph)
    if not nodes or len(nodes) > NODE_LIMIT:
        return {}
    g = _Graph(nodes)
    passes, decoders = set(), []
    for save in g.saves():
        wire = g.inputs(save).get("images")
        sampler = g.back_to_sampler(wire, set())
        if sampler is None:
            continue
        passes.add(sampler)
        decoders.append(g.decoder_on_way(wire))
    firsts = {g.first_pass(s)["sampler"] for s in passes}
    if len(firsts) != 1:
        return {}
    first = g.first_pass(next(iter(firsts)))
    found: Dict[str, Any] = {"source": "run"}
    _sampler_fields(g, g.nodes[first["sampler"]], found)
    latent = g.inputs(first["latent"])
    for name in ("width", "height"):
        value = g.value(latent.get(name), "int")
        if isinstance(value, int) and value > 0:
            found[name] = value
    # The VAE, where every decoder on the way to a save names the same one.
    vaes = {_vae(g, g.inputs(d).get("vae")) for d in decoders}
    if len(vaes) == 1:
        found["vae"] = vaes.pop()
    return {k: v for k, v in found.items() if v not in (None, [], "")}


def _sampler_fields(g: _Graph, sampler: Dict[str, Any], found: Dict[str, Any]) -> None:
    kind, inputs = g.kind(sampler), g.inputs(sampler)
    model, positive, negative = inputs.get("model"), inputs.get("positive"), inputs.get("negative")
    if kind in _K_SAMPLERS:
        found["seed"] = g.value(inputs.get("seed" if kind == "KSampler" else "noise_seed"), "int")
        found["steps"] = g.value(inputs.get("steps"), "int")
        found["cfg"] = g.value(inputs.get("cfg"), "number")
        found["sampler"] = g.value(inputs.get("sampler_name"), "text")
        found["scheduler"] = g.value(inputs.get("scheduler"), "text")
    else:
        if kind == "SamplerCustom":
            found["seed"] = g.value(inputs.get("noise_seed"), "int")
            found["cfg"] = g.value(inputs.get("cfg"), "number")
        else:
            noise = g.node(inputs.get("noise"))
            if g.kind(noise) == "RandomNoise":
                found["seed"] = g.value(g.inputs(noise).get("noise_seed"), "int")
            guider = g.node(inputs.get("guider"))
            guided = g.inputs(guider)
            if g.kind(guider) == "CFGGuider":
                found["cfg"] = g.value(guided.get("cfg"), "number")
                model, positive, negative = guided.get("model"), guided.get("positive"), guided.get("negative")
            elif g.kind(guider) == "BasicGuider":
                model, positive, negative = guided.get("model"), guided.get("conditioning"), None
            else:
                model = positive = negative = None
        select = g.node(inputs.get("sampler"))
        if g.kind(select) == "KSamplerSelect":
            found["sampler"] = g.value(g.inputs(select).get("sampler_name"), "text")
        sigmas = g.node(inputs.get("sigmas"))
        if g.kind(sigmas) == "BasicScheduler":
            found["scheduler"] = g.value(g.inputs(sigmas).get("scheduler"), "text")
            found["steps"] = g.value(g.inputs(sigmas).get("steps"), "int")
    prompt = _conditioning(g, positive, "positive", found)
    found["prompt"] = prompt.get("text")
    if prompt.get("clip") is not None:
        _clip(g, prompt["clip"], found)
    found["negative"] = _conditioning(g, negative, "negative", {}).get("text")
    _model(g, model, found)


def _conditioning(g: _Graph, wire: Any, side: str, found: Dict[str, Any]) -> Dict[str, Any]:
    """A side's text encoder, through nodes that pass a conditioning on: its
    text and its clip wire. FluxGuidance's guidance on the way goes into
    `found`. A zeroed conditioning, or a node not listed, gives nothing."""
    def step(node):
        kind, inputs = g.kind(node), g.inputs(node)
        if kind in _ZERO:
            return "stop", None
        if kind and "TextEncode" in kind:
            raw = next((inputs[k] for k in _ENCODER_TEXT if k in inputs), None)
            return "done", {"text": g.text(raw), "clip": inputs.get("clip")}
        if kind in _CONDITIONING:
            # The one nearest the sampler is applied last, and wins.
            if kind == "FluxGuidance" and "distilled_cfg" not in found:
                found["distilled_cfg"] = g.value(inputs.get("guidance"), "number")
            return "next", inputs.get(side) if side in inputs else inputs.get("conditioning")
        return "stop", None
    return g.walk(wire, step) or {}


def _model(g: _Graph, wire: Any, found: Dict[str, Any]) -> None:
    """The model's way back: each LoRA with its strengths, a sampling shift, and
    the checkpoint or diffusion model loaded, by its stem."""
    loras: List[Dict[str, Any]] = []

    def step(node):
        kind, inputs = g.kind(node), g.inputs(node)
        if kind in _CHECKPOINTS:
            return "done", stem(g.value(inputs.get(_CHECKPOINTS[kind]), "text"))
        if kind in _LORA_LOADERS:
            name = stem(g.value(inputs.get("lora_name"), "text"))
            if name:
                loras.append({"name": name, "strength_model": g.value(inputs.get("strength_model"), "number"),
                              "strength_clip": g.value(inputs.get("strength_clip"), "number")})
            return "next", inputs.get("model")
        if kind in _POWER_LORA:
            for key in sorted((k for k in inputs if re.fullmatch(r"(?i)lora_\d+", k)), key=lambda k: int(k[5:])):
                entry = inputs[key]
                if isinstance(entry, dict) and entry.get("on") is True and stem(entry.get("lora")):
                    strength = g.value(entry.get("strength"), "number")
                    # No strengthTwo, or a null one, is the model's strength for CLIP too.
                    second = entry.get("strengthTwo")
                    two = g.value(entry.get("strength") if second is None else second, "number")
                    loras.append({"name": stem(entry.get("lora")), "strength_model": strength,
                                  "strength_clip": two})
            return "next", inputs.get("model")
        if kind in _MODEL_PATCHES:
            if kind in _SHIFTS and "shift" not in found:
                found["shift"] = g.value(inputs.get("shift"), "number")
            return "next", inputs.get("model")
        return "stop", None

    found["checkpoint"] = g.walk(wire, step)
    found["loras"] = loras


def _clip(g: _Graph, wire: Any, found: Dict[str, Any]) -> None:
    """The prompt encoder's text encoders, through CLIP Set Last Layer and LoRA
    loaders; none where the checkpoint brings its own."""
    def step(node):
        kind, inputs = g.kind(node), g.inputs(node)
        if kind in _CLIP_LOADERS:
            names = [file_name(g.value(inputs.get(k), "text")) for k in _CLIP_LOADERS[kind]]
            return "done", [n for n in names if n]
        if kind in _CLIP_PASS or kind in _LORA_LOADERS or kind in _POWER_LORA:
            return "next", inputs.get("clip")
        return "stop", None
    found["text_encoders"] = g.walk(wire, step) or []


def _vae(g: _Graph, wire: Any) -> Optional[str]:
    """The VAE a decoder's input loads, by its file name; None for a
    checkpoint's own."""
    node = g.node(wire)
    if g.kind(node) == "VAELoader":
        return file_name(g.value(g.inputs(node).get("vae_name"), "text"))
    return None


# ------------------------------------------------------------ the editor version

def turn(workflow: Any) -> Optional[Dict[str, Any]]:
    """
    The editor version given the run version's shape, as text or as a dict;
    None where it is no editor version. A node's wired inputs come from the
    graph's links - written as lists, `[link, from node, from slot, to node,
    to slot, type]`, or as objects in ComfyUI's newer schema - and its settings
    from `widgets_values`, named by `_WIDGETS`; a setting turned into a wire is
    the wire. What only the editor draws is resolved as ComfyUI resolves it
    before running: a Reroute passes its wire on, a PrimitiveNode gives its
    value to what it feeds, KJNodes' GetNode gives on what the SetNode of its
    name was wired, a muted node is not there, and a bypassed one passes on
    its input of the type wanted. A subgraph or a group node is a
    class the reader does not know, and ends any walk through it.
    """
    graph = loads(workflow)
    if isinstance(graph, dict) and "nodes" not in graph and isinstance(graph.get("workflow"), dict):
        graph = graph["workflow"]       # Endless writes it wrapped once, then bare
    if not isinstance(graph, dict):
        return None
    nodes = [n for n in _list(graph.get("nodes")) if isinstance(n, dict) and _key(n.get("id")) is not None]
    if not nodes or len(nodes) > NODE_LIMIT:
        return None
    by_id = {str(n["id"]): n for n in nodes}
    named = {}
    for n in nodes:
        values = n.get("widgets_values")
        if n.get("type") == _SET and n.get("mode") not in (_MUTED, _BYPASSED) and isinstance(values, list) \
                and values and isinstance(values[0], str):
            named.setdefault(values[0], n)
    links: Dict[Any, tuple] = {}
    for link in _list(graph.get("links")):
        if isinstance(link, list) and len(link) >= 5 and _key(link[0]) is not None:
            links[link[0]] = (str(link[1]), link[2])
        elif isinstance(link, dict) and _key(link.get("id")) is not None:
            links[link["id"]] = (str(link.get("origin_id")), link.get("origin_slot"))
    turned = {}
    for n in nodes:
        kind = n.get("type") if isinstance(n.get("type"), str) else None
        if kind in (_REROUTE, _PRIMITIVE, _SET, _GET) or n.get("mode") in (_MUTED, _BYPASSED):
            continue
        inputs: Dict[str, Any] = dict(_widgets(kind, n.get("widgets_values")))
        for entry in _list(n.get("inputs")):
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                continue
            if _key(entry.get("link")) is None:
                continue
            # A link that resolves to nothing - a node the editor cannot see
            # through - gives no value: the widget's own is stale, and reading
            # it read 43 more prompts unlike the run's over one library.
            found = _origin(entry.get("link"), entry.get("type"), links, by_id, named)
            if found is None:
                inputs.pop(entry["name"], None)
            else:
                inputs[entry["name"]] = found
        turned[str(n["id"])] = {"class_type": kind, "inputs": inputs}
    return turned


def _list(value: Any) -> List[Any]:
    """A part of an editor version that must be a list; an empty one where
    it is anything else."""
    return value if isinstance(value, list) else []


def _key(value: Any) -> Any:
    """A node's or a link's id, where it is one: a whole number or a text."""
    return value if isinstance(value, (int, str)) and not isinstance(value, bool) else None


def _widgets(kind: Optional[str], values: Any) -> Dict[str, Any]:
    """A node's settings by name, where its list has a length its class is
    written with; none for any other. rgthree's Power Lora Loader keeps one
    object per LoRA among its widgets, each named as the run version names it."""
    if not isinstance(values, list):
        return {}
    if kind in _POWER_LORA:
        entries = [v for v in values if isinstance(v, dict) and "lora" in v]
        return {"lora_%d" % i: entry for i, entry in enumerate(entries, 1)}
    for names in _WIDGETS.get(kind or "", []):
        if len(names) == len(values):
            return {name: value for name, value in zip(names, values) if name != "_"}
    return {}


def _origin(link: Any, wanted: Any, links: Dict[Any, tuple], by_id: Dict[str, Any],
            named: Dict[str, Any]) -> Any:
    """What a link brings once the editor's own nodes are resolved: a wire
    `[node, output]` - to a muted node too, which `turn` leaves out, so a walk
    ends there - a PrimitiveNode's value, or None: a broken link, a GetNode
    with no SetNode of its name, a loop."""
    seen: Set[Any] = set()
    while True:
        if link in seen or link not in links:
            return None
        seen.add(link)
        node_id, slot = links[link]
        origin = by_id.get(node_id)
        if origin is None:
            return None
        kind = origin.get("type")
        if kind == _PRIMITIVE:
            values = origin.get("widgets_values")
            return values[0] if isinstance(values, list) and values else None
        if kind == _GET:
            values = origin.get("widgets_values")
            setter = named.get(values[0]) if isinstance(values, list) and values and isinstance(values[0], str) \
                else None
            entries = [e for e in _list((setter or {}).get("inputs")) if isinstance(e, dict)
                       and _key(e.get("link")) is not None]
            if not entries:
                return None
            link = entries[0].get("link")
            continue
        if kind == _REROUTE or origin.get("mode") == _BYPASSED:
            # A reroute's one input. A bypassed node's input as ComfyUI's page
            # picks it: the one at the place of the output the wire leaves,
            # where its type is the one wanted, else the first of that type.
            entries = [e if isinstance(e, dict) else {} for e in _list(origin.get("inputs"))]
            if kind == _REROUTE:
                chosen = next((e for e in entries if _key(e.get("link")) is not None), None)
            else:
                outputs = _list(origin.get("outputs"))
                out_type = outputs[slot].get("type") if isinstance(slot, int) and 0 <= slot < len(outputs) \
                    and isinstance(outputs[slot], dict) else None
                want = wanted if isinstance(wanted, str) and wanted != "*" else out_type
                order = ([slot] if isinstance(slot, int) and 0 <= slot < len(entries) else []) + \
                    list(range(len(entries)))
                chosen = next((entries[i] for i in order if entries[i].get("type") == want
                               and _key(entries[i].get("link")) is not None), None)
            if chosen is None:
                return None
            link = chosen.get("link")
            continue
        return [node_id, slot] if isinstance(slot, int) else None


def read_editor(workflow: Any) -> Dict[str, Any]:
    """The fields an editor version gives (`turn`, then `read`). A prompt
    holding a `{a|b}` choice is none: the run resolved it, the editor kept the
    choice."""
    turned = turn(workflow)
    if not turned:
        return {}
    found = read(turned)
    if not found:
        return {}
    found["source"] = "editor"
    for name in ("prompt", "negative"):
        if isinstance(found.get(name), str) and _CHOICE.search(found[name]):
            del found[name]
    return found


def read_either(run: Any, editor: Any) -> Dict[str, Any]:
    """A file's or a record's fields: from its run version where it has one,
    from its editor version only where it has not."""
    graph = loads(run)
    if graph:
        return read(graph)
    return read_editor(editor)


# ------------------------------------------------- a Civitai image's data, filled

# The reader's fields under the names Civitai's data gives them; the sampler
# and schedule type, and the checkpoint, go by rules of their own (fill).
_CIVITAI_NAMES = (("prompt", "prompt"), ("negative", "negativePrompt"), ("steps", "steps"), ("cfg", "cfgScale"),
                  ("seed", "seed"), ("distilled_cfg", "Distilled CFG Scale"), ("shift", "Shift"))


def _graphs(meta: Any) -> tuple:
    """A Civitai record's `comfy`: its run version and its editor version, as
    given (text or an object), or (None, None)."""
    comfy = loads(meta.get("comfy")) if isinstance(meta, dict) else None
    if not isinstance(comfy, dict):
        return None, None
    return comfy.get("prompt"), comfy.get("workflow")


def has_graph(meta: Any) -> bool:
    """Whether a Civitai image's data holds a ComfyUI graph to read: a run or
    an editor version that is not empty. An empty `comfy` (`{}`) is none."""
    return any(loads(version) for version in _graphs(meta))


def _missing(value: Any) -> bool:
    # Absent, None, or text that says nothing. A number Civitai gives - 0
    # included - is never missing: a seed of 0 is a seed (#409).
    return value is None or (isinstance(value, str) and not value.strip())


def _names_checkpoint(meta: Dict[str, Any]) -> bool:
    """Whether the page finds a checkpoint for the image without the fill -
    imageCheckpoint (send.mjs): its Model, Model hash, a `model` resource with
    a hash, or a checkpoint in civitaiResources with a version id - so the
    fill and the page never disagree on it. The page's rule is in JavaScript
    and this one here: a change to either is made to both, and
    comfy_fill_test holds each of the four."""
    if not _missing(meta.get("Model")) or not _missing(meta.get("Model hash")):
        return True
    resources = meta.get("resources") if isinstance(meta.get("resources"), list) else []
    if any(isinstance(r, dict) and r.get("type") == "model" and r.get("hash") for r in resources):
        return True
    listed = meta.get("civitaiResources") if isinstance(meta.get("civitaiResources"), list) else []
    return any(isinstance(r, dict) and str(r.get("type") or "").lower() == "checkpoint" and r.get("modelVersionId")
               for r in listed)


# One request judges an image up to three times and fills it to show once
# (filter_images, stamp_levels, fill_images): each would read its graph
# again. So fill keeps its last answers, by the data object itself - held,
# so its id is never another's - and only for data holding a graph, which is
# what costs: records holding one ran 39 KB on average and up to 961 KB on
# one library, so a page's worth (200) is kept, not more.
_ANSWERS_KEPT = 200
_answers: "OrderedDict[int, Tuple[Any, Any]]" = OrderedDict()
_answers_lock = threading.Lock()
# How many times a graph was read to fill: for the suites, which count it.
reads = 0


def fill(meta: Any) -> Any:
    """
    A copy of a Civitai image's data with the fields Civitai left out filled
    from its ComfyUI graph (#232): where the image is shown and sent always,
    and where it is judged, stored and searched while the switch is on
    (judged). A field Civitai gives is never changed; what is missing is a
    key absent, None, or text empty or only spaces. The sampler and schedule
    type are filled together, and only where Civitai gives no sampler: one
    folded into Civitai's sampler name ("DPM++ 2M Karras") is never
    overridden by a filled `scheduler`. `Model`, the checkpoint's file stem,
    only where the page finds no checkpoint for the image
    (_names_checkpoint). LoRAs are not added: Civitai's resources are the
    image's. Where anything was filled, its Read from says so - "Civitai,
    workflow". The data as it is where there is no graph, or nothing to
    fill; never the same object once anything is filled. The same answer
    for the same object, which is never to be changed in place after.
    """
    if not isinstance(meta, dict):
        return meta
    with _answers_lock:
        kept = _answers.get(id(meta))
        if kept is not None and kept[0] is meta:
            _answers.move_to_end(id(meta))
            return kept[1]
    if not has_graph(meta):
        return meta
    answer = _fill_now(meta)
    with _answers_lock:
        _answers[id(meta)] = (meta, answer)
        while len(_answers) > _ANSWERS_KEPT:
            _answers.popitem(last=False)
    return answer


def _fill_now(meta: Dict[str, Any]) -> Any:
    """fill(), read from the graph."""
    global reads
    reads += 1
    found = read_either(*_graphs(meta))
    if not found:
        return meta
    filled: Dict[str, Any] = {}
    for mine, theirs in _CIVITAI_NAMES:
        if mine in found and _missing(meta.get(theirs)):
            filled[theirs] = found[mine]
    if _missing(meta.get("sampler")) and found.get("sampler"):
        filled["sampler"] = found["sampler"]
        if found.get("scheduler") and _missing(meta.get("scheduler")):
            filled["scheduler"] = found["scheduler"]
    if found.get("checkpoint") and not _names_checkpoint(meta):
        filled["Model"] = found["checkpoint"]
    if not filled:
        return meta
    return {**meta, **filled, "Read from": "Civitai, workflow"}


def fill_images(images: Any) -> Any:
    """Each image's data filled (fill), in place, as stamp_levels and
    stamp_readings stamp theirs: called between them, after every filter
    and level has judged it (judged), before the card reads its sampler and
    schedule type. Answers the images."""
    for image in images or []:
        if isinstance(image, dict) and isinstance(image.get("meta"), dict):
            image["meta"] = fill(image["meta"])
    return images


# ------------------------------------------------- the switch: judged filled

# The reader's version (#232): raised by a reader that reads more, and the
# Fill notice offers Fill again to libraries filled with an older one.
READER = 1

# The switch, as two values in schema_info, kept by every WebUI sharing the
# database: JUDGED is "1" once stored images are judged by their filled
# data, written when Fill starts and when a database is made; FILLED is the
# READER Fill last finished with.
JUDGED_KEY = "comfy_judged"
FILLED_KEY = "comfy_fill"

# How often the copy in memory is read again: the other WebUI sharing the
# database turns the switch, and Fill waits this long before its scan.
SWITCH_SECONDS = 5.0

# The copy in memory. A rule runs inside storing's transaction, where a read
# through the database's own connection would commit it half-done; so the
# rules read this copy alone, and the database hands in a reader of its own
# connection (set_switch_reader). With none - the rule suites - it is off.
_switch: Dict[str, Any] = {"judged": False, "filled": None, "read_at": None, "reader": None}
_switch_lock = threading.Lock()


def switch_from(values: Dict[str, Any]) -> Tuple[bool, Optional[int]]:
    """(judged, filled) from schema_info's values by key, as stored."""
    filled = values.get(FILLED_KEY)
    return values.get(JUDGED_KEY) == "1", int(filled) if str(filled or "").isdigit() else None


def set_switch_reader(reader: Optional[Callable[[], Tuple[bool, Optional[int]]]]) -> None:
    """Hand in what reads the switch - (judged, the READER Fill last finished
    with) - and read it now. None forgets it: the switch reads off."""
    with _switch_lock:
        _switch.update(reader=reader, read_at=None, judged=False, filled=None)
    judging_filled()


def set_switch(judged: bool, filled: Optional[int] = None) -> None:
    """This process's copy, set at once - by whatever has just written the
    switch to the database, so nothing here waits for the next read."""
    with _switch_lock:
        _switch.update(judged=bool(judged), filled=filled, read_at=time.monotonic())


def switch() -> Tuple[bool, Optional[int]]:
    """(judged, filled), as this process holds them now."""
    judging_filled()
    with _switch_lock:
        return _switch["judged"], _switch["filled"]


def judging_filled() -> bool:
    """Whether stored images are judged by their filled data: the copy in
    memory, read again through the database's reader at most every
    SWITCH_SECONDS. A read that fails keeps what was held, and never raises."""
    with _switch_lock:
        reader, read_at = _switch["reader"], _switch["read_at"]
        due = reader is not None and (read_at is None or time.monotonic() - read_at >= SWITCH_SECONDS)
        if due:
            _switch["read_at"] = time.monotonic()
    if due:
        try:
            judged, filled = reader()
        except Exception:
            pass
        else:
            with _switch_lock:
                _switch.update(judged=bool(judged), filled=filled)
    with _switch_lock:
        return _switch["judged"]


def judged(meta: Any, filled: Optional[bool] = None) -> Any:
    """A Civitai image's data as it is judged - its level, whether its prompt
    is worth reading, its stored rows: filled from its graph while the switch
    is on, Civitai's alone while off. `filled` decides instead of the switch:
    storing reads the switch before its transaction, Fill judges filled, and
    the Civitai Browser's live images, never stored, are judged filled."""
    if filled is None:
        filled = judging_filled()
    return fill(meta) if filled else meta


def judged_image(image: Any, filled: Optional[bool] = None) -> Any:
    """An image (a record) with its data as judged (judged); the image itself
    where nothing changes."""
    if not isinstance(image, dict) or not isinstance(image.get("meta"), dict):
        return image
    meta = judged(image["meta"], filled)
    return image if meta is image["meta"] else {**image, "meta": meta}
