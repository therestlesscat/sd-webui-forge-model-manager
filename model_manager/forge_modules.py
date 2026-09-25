"""
The text encoders and VAE a model needs, picked from what is installed.

An image's generation data names the checkpoint and, sometimes, a VAE. It
never names a Flux model's CLIP-L and T5-XXL, or a Qwen-Image model's
Qwen2.5-VL: whoever made it had them loaded already. So Send to txt2img
looks up what the model's architecture needs (NEEDS, from Forge's own model
classes), leaves out what the file bundles (architecture.py), and finds the
rest among the modules Forge offers in its "VAE / Text Encoder" control.

Those are told apart by what they are, not by name. A text encoder by its
token embedding - vocabulary by width - and whether it has a vision tower;
a VAE by its latent channels, or the Wan-style layout Qwen-Image's uses.
The files named for a preset in the extension's settings come first, then
Forge's saved choice for the preset - each only when it is the right kind:
on the library this was written against, the "sd" preset held the Flux
modules and the "qwen" preset held Z-Image's text encoder. Otherwise the
finest weights win, which is not always what a machine can load: a person
with less memory names the fp8 file in the settings.

Nothing here asks for Forge's modules by import at load time, so the rest of
the extension, and its tests, work without them.
"""
import os
import threading
from typing import Dict, List, Optional, Tuple

from .architecture import read_shapes

# What each of Forge's model classes needs besides the diffusion model:
# (text encoders, VAE), as the kinds classify() names. From each class's
# clip_target() and its reference repo's model_index.json. PiD's VAE is its
# own, and no installed file is known to be one, so it is not looked for.
NEEDS: Dict[str, Tuple[Tuple[str, ...], Optional[str]]] = {
    "Flux": (("clip_l", "t5xxl"), "vae_ae"),
    "FluxSchnell": (("clip_l", "t5xxl"), "vae_ae"),
    "Chroma": (("t5xxl",), "vae_ae"),
    "Flux2K4B": (("qwen3_4b",), "vae_flux2"),
    "Flux2K9B": (("qwen3_8b",), "vae_flux2"),
    "Lumina2": (("gemma2_2b",), "vae_ae"),
    "ZImage": (("qwen3_4b",), "vae_ae"),
    "Anima": (("qwen3_06b",), "vae_wan21"),
    "WAN21_T2V": (("umt5xxl",), "vae_wan21"),
    "WAN21_I2V": (("umt5xxl",), "vae_wan21"),
    "QwenImage": (("qwen25_7b",), "vae_wan21"),
    "Krea2": (("qwen3vl_4b",), "vae_wan21"),
    "ErnieImage": (("ministral3_3b",), "vae_flux2"),
    "PiD": (("gemma2_2b",), None),
}

# The class a preset stands for, when only the preset is known - from
# Civitai's baseModel, for a gallery that is not a checkpoint's own.
CLASS_FOR_PRESET = {
    "flux": "Flux", "klein": "Flux2K4B", "lumina": "Lumina2", "zit": "ZImage",
    "anima": "Anima", "wan": "WAN21_T2V", "qwen": "QwenImage", "krea": "Krea2",
    "ernie": "ErnieImage", "pid": "PiD",
}

# Among several files of the right kind, one named for the architecture is
# the likelier: Qwen-Image's VAE and Wan's share a layout.
NAME_HINTS = {
    "wan": ("wan",), "qwen": ("qwen",), "krea": ("qwen", "krea"),
    "anima": ("qwen", "anima"), "flux": ("ae", "flux"), "zit": ("ae", "flux"),
    "lumina": ("ae", "flux"), "klein": ("flux2", "klein"), "ernie": ("flux2",),
}

# A text encoder's token embedding, (vocabulary, width), and whether it has a
# vision tower -> its kind.
_EMBEDDINGS = {
    (49408, 768, False): "clip_l",
    (49408, 1280, False): "clip_g",
    (32128, 4096, False): "t5xxl",
    (256384, 4096, False): "umt5xxl",
    (151936, 1024, False): "qwen3_06b",
    (151936, 2560, False): "qwen3_4b",
    (151936, 2560, True): "qwen3vl_4b",
    (151936, 4096, False): "qwen3_8b",
    (152064, 3584, False): "qwen25_7b",
    (152064, 3584, True): "qwen25_7b",
    (256000, 2304, False): "gemma2_2b",
    (131072, 3072, False): "ministral3_3b",
}
_EMBEDDING_NAMES = ("embed_tokens.weight", "token_embedding.weight", "shared.weight",
                    "token_embd.weight")

# The keys Forge's loader looks for before taking a file as T5 or UMT5
# (backend/loader.py replace_state_dict): Hugging Face's layout, plain or
# quantized. The same encoder saved in Wan's own layout (blocks.N.attn.q,
# a top-level token_embedding) has the right shape and is not loaded.
_T5_LOADABLE = ("encoder.block.0.layer.0.SelfAttention.k.weight",
                "encoder.block.0.layer.0.SelfAttention.k.qweight")

# A VAE's latent channels, from its decoder's first convolution -> its kind.
_LATENT_CHANNELS = {4: "vae_sd", 16: "vae_ae", 32: "vae_flux2"}


def classify(shapes: Dict[str, Tuple[Tuple[int, ...], str]],
             loadable_only: bool = True) -> Optional[str]:
    """
    What kind of module a file is, from its tensor shapes - or None.

    A whole checkpoint is None: Forge lists files in its VAE folder as
    modules whatever they are, and a checkpoint loaded as one is not a VAE.
    `loadable_only=False` names a T5 or UMT5 even in a layout Forge cannot
    load - it is still a text encoder, just not one to pick.
    """
    names = list(shapes)
    if any(n.startswith(("model.diffusion_model.", "first_stage_model.", "conditioner."))
           for n in names):
        return None

    vision = any("visual" in n or "vision" in n for n in names)
    for name in names:
        if name.endswith(_EMBEDDING_NAMES):
            shape = shapes[name][0]
            if len(shape) == 2:
                kind = _EMBEDDINGS.get((shape[0], shape[1], vision)) \
                    or _EMBEDDINGS.get((shape[0], shape[1], False))
                if kind in ("t5xxl", "umt5xxl") and loadable_only \
                        and not any(k in shapes for k in _T5_LOADABLE):
                    return None         # right encoder, in a layout Forge cannot load
                if kind:
                    return kind

    conv_in = shapes.get("decoder.conv_in.weight")
    if conv_in and len(conv_in[0]) == 4:
        return _LATENT_CHANNELS.get(conv_in[0][1])
    if "decoder.middle.0.residual.0.gamma" in shapes:
        return "vae_wan21"
    return None


def _precision(path: str, shapes) -> int:
    """How faithful a file's weights are: full or half beats fp8 beats GGUF."""
    if path.lower().endswith(".gguf"):
        return 0
    kinds = {kind for _, kind in shapes.values()}
    if kinds & {"F16", "BF16", "F32"} and not any(k.startswith("F8") for k in kinds):
        return 2
    return 1


# Classified module files: path -> (modified time, kind, precision). A module
# folder is read once, then only what has changed.
_classified: Dict[str, Tuple[float, Optional[str], int]] = {}
_lock = threading.Lock()


def classify_file(path: str) -> Tuple[Optional[str], int]:
    """(kind, precision) of a module file, remembered until it changes."""
    try:
        modified = os.path.getmtime(path)
    except OSError:
        return None, 0
    with _lock:
        known = _classified.get(path)
    if known and known[0] == modified:
        return known[1], known[2]
    shapes = read_shapes(path) or {}
    result = (classify(shapes) if shapes else None, _precision(path, shapes) if shapes else 0)
    with _lock:
        _classified[path] = (modified, *result)
    return result


def installed_modules() -> Dict[str, str]:
    """
    The modules Forge offers in its VAE / Text Encoder control: label -> path.

    Forge's own list (modules_forge.main_entry.module_list), keyed by the
    file name it shows. Empty where Forge is not there to ask.
    """
    try:
        from modules_forge import main_entry
        return dict(main_entry.module_list)
    except Exception:
        return {}


def saved_modules(preset: str) -> List[str]:
    """The modules Forge remembers for a UI preset, as the labels it shows."""
    try:
        from modules import shared
        paths = getattr(shared.opts, f"forge_additional_modules_{preset}", None) or []
        return [os.path.basename(p) for p in paths]
    except Exception:
        return []


# The setting naming a preset's files: model_manager_modules_<preset>.
SETTING_PREFIX = "model_manager_modules_"


def parse_file_names(value) -> List[str]:
    """
    File names from a setting: comma- or line-separated, any folder dropped -
    Forge lists a module by its file name, wherever it sits.
    """
    names = []
    for part in str(value or "").replace("\n", ",").split(","):
        name = os.path.basename(part.strip().replace("\\", "/"))
        if name and name not in names:
            names.append(name)
    return names


def preferred_modules(preset: Optional[str]) -> List[str]:
    """The files the settings name for a UI preset, as written there."""
    if not preset:
        return []
    try:
        from modules import shared
        return parse_file_names(getattr(shared.opts, SETTING_PREFIX + preset, ""))
    except Exception:
        return []


def _match(name: str, labels) -> Optional[str]:
    """The installed module a file name from the settings means, if any.
    Case does not matter, nor a missing extension."""
    wanted = name.lower()
    for label in labels:
        lower = label.lower()
        if lower == wanted or os.path.splitext(lower)[0] == wanted:
            return label
    return None


def pick(model_class: Optional[str], preset: Optional[str],
         bundled_text_encoder: bool, bundled_vae: bool,
         modules: Dict[str, Tuple[Optional[str], int]],
         saved: List[str], preferred: List[str] = ()) -> Dict[str, object]:
    """
    The modules to select for a model, and what could not be found.

    Args:
        model_class: Forge's model class, if the file was read; else the one
            the preset stands for.
        preset: Forge's UI preset for the model.
        bundled_text_encoder, bundled_vae: what the file brings itself.
        modules: label -> (kind, precision), for everything installed.
        saved: the labels Forge remembers for this preset.
        preferred: the file names the settings give for this preset. One of
            a needed kind beats anything else of that kind; one of a kind
            not needed here is left out - a Flux setting's CLIP-L, for
            Chroma. One this cannot identify is selected anyway, the person
            knowing better, and then nothing is reported missing, since it
            may well be what is.

    Returns:
        needed: the kinds looked for; select: the labels to select, one per
        kind found; missing: the kinds nothing installed is; not_found: the
        preferred names no installed module has.
    """
    model_class = model_class or CLASS_FOR_PRESET.get(preset or "")
    encoders, vae = NEEDS.get(model_class or "", ((), None))
    needed = ([] if bundled_text_encoder else list(encoders)) \
        + ([vae] if vae and not bundled_vae else [])
    hints = NAME_HINTS.get(preset or "", ())

    chosen, not_found = [], []
    for name in preferred:
        label = _match(name, modules)
        if label is None:
            not_found.append(name)
        elif label not in chosen:
            chosen.append(label)
    unknown = [label for label in chosen if modules[label][0] is None]

    select, missing = [], []
    for kind in needed:
        candidates = [label for label, (k, _) in modules.items() if k == kind]
        if not candidates:
            missing.append(kind)
            continue
        candidates.sort(key=lambda label: (
            label not in chosen,                                  # the settings' choice
            label not in saved,                                   # Forge's saved choice
            not any(h in label.lower() for h in hints),           # named for it
            -modules[label][1],                                   # finer weights
            label.lower(),
        ))
        select.append(candidates[0])
    if needed and unknown:
        select += unknown
        missing = []
    return {"needed": needed, "select": select, "missing": missing, "not_found": not_found}
