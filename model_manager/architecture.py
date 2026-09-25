"""
Which Forge architecture a model file is, read from the file itself.

Send to txt2img has to switch Forge Neo's UI preset to the model's
architecture and load the text encoders and VAE it needs - which an image's
generation data never names, since whoever made it had them loaded already.
Civitai's baseModel says roughly what a model is, but it is typed by the
uploader, and says nothing about the file: a Flux checkpoint can carry its
CLIP-L, T5-XXL and VAE inside it, or be the diffusion model alone.

So the file is asked. A .safetensors file opens with a JSON header naming
every tensor and its shape; a .gguf file keeps the same in its tensor table.
That is read - kilobytes, not the weights - and handed to the detector Forge
itself uses when it loads a checkpoint (huggingface_guess), as tensors with
a shape and no data. Measured on a library of 530 checkpoints and 3 GGUF
files: 525 recognised, the slowest in about half a second. What was not is
what Forge Neo cannot load either (SD3), or not a checkpoint at all.

Forge's modules are imported only when a file is actually looked at, so the
rest of the extension - and its tests - work where they are not installed.
Anything that goes wrong here is "not recognised", never an error: the
caller then falls back to Civitai's baseModel, and failing that to what
Send to txt2img did before.
"""
import json
import os
import struct
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

# Forge's model classes (huggingface_guess.model_list), by the UI preset
# (modules_forge.presets.PresetArch) that runs them.
PRESET_BY_CLASS = {
    "SD15": "sd",
    "SDXL": "xl",
    "SDXLRefiner": "xl",
    "Mugen": "xl",
    "Flux": "flux",
    "FluxSchnell": "flux",
    "Chroma": "flux",
    "Flux2K4B": "klein",
    "Flux2K9B": "klein",
    "Lumina2": "lumina",
    "ZImage": "zit",
    "Anima": "anima",
    "WAN21_T2V": "wan",
    "WAN21_I2V": "wan",
    "QwenImage": "qwen",
    "Krea2": "krea",
    "ErnieImage": "ernie",
    "PiD": "pid",
}

# The fallback, when the file says nothing Forge recognises: Civitai's
# baseModel, by prefix, first match wins. Pony, Illustrious and NoobAI are
# SDXL underneath. HiDream, Kolors, SD3 and the rest have no Forge Neo
# preset, and so no entry.
PRESET_BY_BASE_MODEL = (
    ("SD 1", "sd"),
    ("SDXL", "xl"),
    ("Pony", "xl"),
    ("Illustrious", "xl"),
    ("NoobAI", "xl"),
    ("Flux.1 Krea", "flux"),
    ("Flux.1", "flux"),
    ("Flux.2", "klein"),
    ("Chroma", "flux"),
    ("Krea 2", "krea"),
    ("Qwen", "qwen"),
    ("ZImage", "zit"),
    ("Z-Image", "zit"),
    ("Lumina", "lumina"),
    ("Anima", "anima"),
    ("Wan Video", "wan"),
)

# safetensors dtype names, as torch dtypes by attribute name. Resolved when
# torch is imported, which only happens when a file is looked at.
_DTYPES = {
    "F16": "float16", "BF16": "bfloat16", "F32": "float32", "F64": "float64",
    "F8_E4M3": "float8_e4m3fn", "F8_E5M2": "float8_e5m2",
    "I8": "int8", "U8": "uint8", "I16": "int16", "I32": "int32", "I64": "int64",
    "BOOL": "bool",
}

# A safetensors header larger than this is not a header.
_MAX_HEADER = 200 * 1024 * 1024


@dataclass
class Architecture:
    """What a model file is, and what it brings with it."""
    preset: str                   # Forge Neo UI preset: "flux", "qwen", ...
    model_class: str              # Forge's model class: "Flux", "QwenImage", ...
    bundled_text_encoder: bool    # its text encoder(s) are inside the file
    bundled_vae: bool             # its VAE is inside the file


def preset_for_base_model(base_model: Optional[str]) -> Optional[str]:
    """The UI preset Civitai's baseModel points to, or None."""
    if not base_model:
        return None
    for prefix, preset in PRESET_BY_BASE_MODEL:
        if base_model.startswith(prefix):
            return preset
    return None


def read_safetensors_shapes(path: str) -> Optional[Dict[str, Tuple[Tuple[int, ...], str]]]:
    """
    A .safetensors file's tensors, as name -> (shape, dtype), from its header.

    The file starts with the header's length (8 bytes, little-endian) and the
    header itself, JSON. Nothing past it is read.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read(8)
            if len(raw) != 8:
                return None
            length = struct.unpack("<Q", raw)[0]
            if not 0 < length <= _MAX_HEADER:
                return None
            header = json.loads(f.read(length))
    except (OSError, ValueError):
        return None
    header.pop("__metadata__", None)
    return {name: (tuple(info.get("shape", ())), info.get("dtype", "F16"))
            for name, info in header.items() if isinstance(info, dict)}


def read_gguf_shapes(path: str) -> Optional[Dict[str, Tuple[Tuple[int, ...], str]]]:
    """
    A .gguf file's tensors, as name -> (shape, dtype), with Forge's reader.

    As Forge reads them for loading: the shape saved by the quantizer when
    there is one, else the tensor's own, reversed into torch order.
    """
    try:
        import gguf                     # Forge's copy, on its package path
        reader = gguf.GGUFReader(path)
    except Exception:
        return None
    shapes = {}
    for tensor in reader.tensors:
        name = str(tensor.name)
        field = reader.get_field(f"comfy.gguf.orig_shape.{name}")
        if field is not None:
            shape = tuple(int(field.parts[i][0]) for i in field.data)
        else:
            shape = tuple(int(v) for v in reversed(tensor.shape))
        shapes[name] = (shape, "F16")
    return shapes


def read_shapes(path: str) -> Optional[Dict[str, Tuple[Tuple[int, ...], str]]]:
    """A model file's tensors, name -> (shape, dtype), or None if unreadable."""
    lower = path.lower()
    if lower.endswith((".safetensors", ".sft")):         # .sft: the same format
        return read_safetensors_shapes(path)
    if lower.endswith(".gguf"):
        return read_gguf_shapes(path)
    return None


def _forge_guess(shapes: Dict[str, Tuple[Tuple[int, ...], str]]):
    """
    Forge's own answer for a state dict of these shapes, as its loader asks.

    Tensors on the meta device have a shape and a dtype and no data, which is
    all the detector looks at. The steps are split_state_dict's: prefix a
    bare diffusion model, guess, and failing that convert from diffusers'
    layout and guess again.

    Returns (Forge's model config, the state dict it was judged on).
    """
    import torch
    import huggingface_guess
    from modules_forge.packages.comfy.utils import convert_diffusers_mmdit

    def dtype(name):
        return getattr(torch, _DTYPES.get(name, "float16"), torch.float16)

    sd = {name: torch.empty(shape, dtype=dtype(kind), device="meta")
          for name, (shape, kind) in shapes.items()}

    def prefixed(state_dict):
        if not any(k.startswith(("model.diffusion_model.", "net.")) for k in state_dict):
            return {f"model.diffusion_model.{k}": v for k, v in state_dict.items()}
        return state_dict

    try:
        judged = prefixed(sd)
        return huggingface_guess.guess(judged), judged
    except ModuleNotFoundError:
        converted = convert_diffusers_mmdit(sd, "")
        if converted is None:
            raise
        judged = prefixed(converted)
        return huggingface_guess.guess(judged), judged


def detect(path: str,
           guess: Callable[[Dict[str, Tuple[Tuple[int, ...], str]]], Any] = None
           ) -> Optional[Architecture]:
    """
    What architecture a model file is, or None if Forge does not recognise it.

    Args:
        path: The model file.
        guess: Stands in for Forge's detector - for tests. Takes the shapes,
            returns (config, judged state dict) as _forge_guess() does.
    """
    if not path or not os.path.isfile(path):
        return None
    shapes = read_shapes(path)
    if not shapes:
        return None
    try:
        config, judged = (guess or _forge_guess)(shapes)
    except Exception:
        return None

    model_class = type(config).__name__
    preset = PRESET_BY_CLASS.get(model_class)
    if not preset:
        return None

    vae_prefixes = tuple(getattr(config, "vae_key_prefix", None) or ())
    return Architecture(
        preset=preset,
        model_class=model_class,
        bundled_text_encoder=_bundles_text_encoder(config, judged),
        bundled_vae=bool(vae_prefixes) and any(k.startswith(vae_prefixes) for k in judged),
    )


def _bundles_text_encoder(config, judged) -> bool:
    """
    Whether the file carries its text encoder(s).

    Asked the way Forge's loader finds them: each model class's
    process_clip_state_dict() knows its own layout, and keeps only the text
    encoder tensors. A class's declared prefix is not enough - SDXL keeps
    its encoders under conditioner.embedders., which no prefix it declares
    names. The prefix is the fallback, for a class whose method cannot run
    on tensors with no data.
    """
    process = getattr(config, "process_clip_state_dict", None)
    if process is not None:
        try:
            return bool(process(dict(judged)))
        except Exception:
            pass
    prefixes = tuple(getattr(config, "text_encoder_key_prefix", None) or ())
    return bool(prefixes) and any(k.startswith(prefixes) for k in judged)


def file_modified(path: str) -> Optional[str]:
    """A file's modified time, as the database stores it (see scan_service)."""
    from datetime import datetime
    try:
        return datetime.fromtimestamp(os.stat(path).st_mtime).isoformat()
    except OSError:
        return None


def needs_check(db, path: str) -> Optional[str]:
    """
    The file's modified time if its architecture should be read, else None.

    A file already read at this modified time is skipped - including one
    Forge did not recognise, which is stored as None so it is not read again
    until it changes. A file with no row yet is read: its row is about to be
    written.
    """
    modified = file_modified(path)
    if modified is None:
        return None
    row = db.get_version(path)
    if row and row.get("architecture_checked") == modified:
        return None
    return modified


def store_architecture(db, path: str, found: Optional[Architecture],
                       modified: Optional[str]) -> None:
    """Store what detect() found for a file - None for not recognised."""
    db.set_architecture(
        path,
        found.preset if found else None,
        found.model_class if found else None,
        found.bundled_text_encoder if found else False,
        found.bundled_vae if found else False,
        modified,
    )


def record_architecture(db, path: str, force: bool = False) -> Optional[Architecture]:
    """
    Read a model file's architecture and store it, unless already done.

    `force` reads it even when unchanged since last time: a forced sync and a
    download use it, being when a file is new or its contents may no longer
    be what was read.

    Returns what was found, or None for unrecognised, unchanged or absent.
    """
    modified = file_modified(path) if force else needs_check(db, path)
    if modified is None or not db.get_version(path):
        return None
    found = detect(path)
    store_architecture(db, path, found, modified)
    return found
