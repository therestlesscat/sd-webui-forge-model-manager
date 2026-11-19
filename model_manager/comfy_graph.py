"""
ComfyUI's graph, read into plain fields (#232): one reader, for Sync images
and for Civitai's stored images alike.

ComfyUI saves a workflow in two versions. The run version - the graph it
actually runs, a PNG's `prompt` chunk, Civitai's `comfy` -> `prompt` - names
each node's class (`class_type`) and its inputs by name, a wire written as
`[node, output]`. That is what `read` reads. (The editor version, the canvas
as drawn, is turned into this shape before it is read: a later part of #232.)

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
"""
import json
import math
from typing import Any, Dict, List, Optional, Set

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

    def node(self, wire: Any) -> Optional[Dict[str, Any]]:
        """The node a wire leads to, or None for a value or a broken wire."""
        if isinstance(wire, list) and len(wire) == 2 and isinstance(wire[1], int):
            return self.nodes.get(str(wire[0]))
        return None

    def at(self, wire: Any) -> Optional[tuple]:
        """The node a wire leads to with its id, or None."""
        node = self.node(wire)
        return (str(wire[0]), node) if node is not None else None

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
            for key in sorted(k for k in inputs if k.lower().startswith("lora_")):
                entry = inputs[key]
                if isinstance(entry, dict) and entry.get("on") is True and stem(entry.get("lora")):
                    strength = g.value(entry.get("strength"), "number")
                    two = g.value(entry.get("strengthTwo", entry.get("strength")), "number")
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
