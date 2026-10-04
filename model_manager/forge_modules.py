"""
The text encoders and VAE a model needs, picked from what is installed.

An image's generation data names the checkpoint and, sometimes, a VAE. It
never names a Flux model's CLIP-L and T5-XXL, or a Qwen-Image model's
Qwen2.5-VL: whoever made it had them loaded already. So Send to txt2img
looks up what the model's architecture needs (NEEDS, from Forge's own model
classes), leaves out what the file bundles (architecture.py), and finds the
rest among the modules Forge offers in its "VAE / Text Encoder" control.

Those are told apart by what they are, not by name (file_identity.classify):
a text encoder by its token embedding - vocabulary by width - and whether it
has a vision tower; a VAE by its latent channels, or the Wan-style layout
Qwen-Image's uses. The files named for a preset in the extension's settings
come first, then Forge's saved choice for the preset - each only when it is
the right kind: on the library this was written against, the "sd" preset
held the Flux modules and the "qwen" preset held Z-Image's text encoder.
Otherwise the finest weights win, which is not always what a machine can
load: a person with less memory names the fp8 file in the settings.

What Forge offers, holds and remembers is asked through forge_host.py; the
rest is worked out here, so the tests can hand it any of those.
"""
import os
from typing import Dict, List, NamedTuple, Optional, Tuple

from .architecture import PRESET_BY_CLASS
from .forge_host import DEFAULTS, saved_modules, setting

HF = "https://huggingface.co/"


class ModuleFile(NamedTuple):
    """A text encoder or VAE a model needs: its kind, as
    file_identity.classify() names it, what to call it, and where to get
    it - (name, Hugging Face path)."""
    kind: str
    label: str
    links: Tuple[Tuple[str, str], ...]


# The files models need. A kind is a shape, and two files of one shape are
# not always one file: Wan's VAE and Qwen-Image's share a layout, and PiD's
# Gemma is Lumina's, instruction-tuned. So a model's needs are named by file,
# and file_identity.classify(), which sees only shapes, matches them by kind.
# The links are from Forge Neo's Download Models page.
_KLEIN = "Comfy-Org/vae-text-encorder-for-flux-klein-9b/blob/main/split_files/"
_WAN = "Comfy-Org/Wan_2.1_ComfyUI_repackaged/blob/main/split_files/"
_QWEN = "Comfy-Org/Qwen-Image_ComfyUI/blob/main/split_files/"
_QWEN3_4B = (("qwen_3_4b", "Comfy-Org/z_image_turbo/blob/main/split_files/text_encoders/qwen_3_4b.safetensors"),
             ("qwen3_4b fp8", "jiangchengchengNLP/qwen3-4b-fp8-scaled/blob/main/qwen3_4b_fp8_scaled.safetensors"))
FILES: Dict[str, ModuleFile] = {
    "clip_l": ModuleFile("clip_l", "CLIP-L", (
        ("clip_l", "comfyanonymous/flux_text_encoders/blob/main/clip_l.safetensors"),)),
    "t5xxl": ModuleFile("t5xxl", "T5-XXL", (
        ("t5xxl fp16", "comfyanonymous/flux_text_encoders/blob/main/t5xxl_fp16.safetensors"),
        ("t5xxl fp8", "comfyanonymous/flux_text_encoders/blob/main/t5xxl_fp8_e4m3fn_scaled.safetensors"))),
    "ae": ModuleFile("vae_ae", "Flux VAE (ae)", (
        ("ae", "Comfy-Org/Lumina_Image_2.0_Repackaged/blob/main/split_files/vae/ae.safetensors"),)),
    "qwen3_4b": ModuleFile("qwen3_4b", "Qwen3 4B", _QWEN3_4B),
    "qwen3_8b": ModuleFile("qwen3_8b", "Qwen3 8B", (
        ("qwen_3_8b", _KLEIN + "text_encoders/qwen_3_8b.safetensors"),
        ("qwen_3_8b fp8", _KLEIN + "text_encoders/qwen_3_8b_fp8mixed.safetensors"))),
    "flux2_vae": ModuleFile("vae_flux2", "Flux.2 VAE", (
        ("flux2-vae", _KLEIN + "vae/flux2-vae.safetensors"),)),
    "gemma2_2b": ModuleFile("gemma2_2b", "Gemma 2 2B", (
        ("gemma_2_2b", "duongve/NetaYume-Lumina-Image-2.0/blob/main/Text_Encoder/gemma_2_2b_fp16.safetensors"),)),
    "gemma2_2b_it": ModuleFile("gemma2_2b", "Gemma 2 2B IT", (
        ("gemma_2_2b_it bf16", "Comfy-Org/PixelDiT/blob/main/text_encoders/gemma_2_2b_it_elm_bf16.safetensors"),
        ("gemma_2_2b_it fp8", "Comfy-Org/PixelDiT/blob/main/text_encoders/gemma_2_2b_it_elm_fp8_scaled.safetensors"))),
    "qwen3_06b": ModuleFile("qwen3_06b", "Qwen3 0.6B", (
        ("qwen_3_06b_base", "circlestone-labs/Anima/blob/main/split_files/text_encoders/qwen_3_06b_base.safetensors"),)),
    "qwen_image_vae": ModuleFile("vae_wan21", "Qwen-Image VAE", (
        ("qwen_image_vae", _QWEN + "vae/qwen_image_vae.safetensors"),)),
    "umt5xxl": ModuleFile("umt5xxl", "UMT5-XXL", (
        ("umt5_xxl fp16", _WAN + "text_encoders/umt5_xxl_fp16.safetensors"),
        ("umt5_xxl fp8", _WAN + "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"))),
    "wan21_vae": ModuleFile("vae_wan21", "Wan 2.1 VAE", (
        ("wan_2.1_vae", _WAN + "vae/wan_2.1_vae.safetensors"),)),
    "qwen25_7b": ModuleFile("qwen25_7b", "Qwen2.5-VL 7B", (
        ("qwen_2.5_vl_7b fp16", _QWEN + "text_encoders/qwen_2.5_vl_7b.safetensors"),
        ("qwen_2.5_vl_7b fp8", _QWEN + "text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"))),
    "qwen3vl_4b": ModuleFile("qwen3vl_4b", "Qwen3-VL 4B", (
        ("qwen3vl_4b bf16", "Comfy-Org/Krea-2/blob/main/text_encoders/qwen3vl_4b_bf16.safetensors"),
        ("qwen3vl_4b fp8", "Comfy-Org/Krea-2/blob/main/text_encoders/qwen3vl_4b_fp8_scaled.safetensors"))),
    "ministral3_3b": ModuleFile("ministral3_3b", "Ministral 3 3B", (
        ("ministral-3-3b", "Comfy-Org/ERNIE-Image/blob/main/text_encoders/ministral-3-3b.safetensors"),)),
}

# What each of Forge's model classes needs besides the diffusion model, from
# each class's clip_target() and its reference repo's model_index.json. PiD's
# VAE is its own, and no installed file is known to be one, so it is not
# looked for.
CLASS_FILES: Dict[str, Tuple[str, ...]] = {
    "Flux": ("clip_l", "t5xxl", "ae"),
    "FluxSchnell": ("clip_l", "t5xxl", "ae"),
    "Chroma": ("t5xxl", "ae"),
    "Flux2K4B": ("qwen3_4b", "flux2_vae"),
    "Flux2K9B": ("qwen3_8b", "flux2_vae"),
    "Lumina2": ("gemma2_2b", "ae"),
    "ZImage": ("qwen3_4b", "ae"),
    "Anima": ("qwen3_06b", "qwen_image_vae"),
    "WAN21_T2V": ("umt5xxl", "wan21_vae"),
    "WAN21_I2V": ("umt5xxl", "wan21_vae"),
    "QwenImage": ("qwen25_7b", "qwen_image_vae"),
    "Krea2": ("qwen3vl_4b", "qwen_image_vae"),
    "ErnieImage": ("ministral3_3b", "flux2_vae"),
    "PiD": ("gemma2_2b_it",),
}

# The same, as the kinds pick() looks for: (text encoders, VAE).
NEEDS: Dict[str, Tuple[Tuple[str, ...], Optional[str]]] = {
    cls: (tuple(FILES[f].kind for f in files if not FILES[f].kind.startswith("vae")),
          next((FILES[f].kind for f in files if FILES[f].kind.startswith("vae")), None))
    for cls, files in CLASS_FILES.items()
}

# What a person calls each class, where a preset covers several.
CLASS_LABELS = {
    "Flux": "Flux.1", "FluxSchnell": "Flux.1 Schnell", "Chroma": "Chroma",
    "Flux2K4B": "Klein 4B", "Flux2K9B": "Klein 9B", "Lumina2": "Lumina Image 2.0",
    "ZImage": "Z-Image", "Anima": "Anima", "WAN21_T2V": "Wan text to video",
    "WAN21_I2V": "Wan image to video", "QwenImage": "Qwen-Image", "Krea2": "Krea 2",
    "ErnieImage": "ERNIE-Image", "PiD": "PiD",
}

# The presets whose modules the settings name: (preset, what it runs, a note).
MODULE_PRESETS = (
    ("flux", "Flux.1 / Chroma", ""),
    ("klein", "Flux.2 Klein", ""),
    ("lumina", "Lumina Image 2.0", ""),
    ("zit", "Z-Image", ""),
    ("anima", "Anima", ""),
    ("wan", "Wan", "UMT5-XXL loads only in the Hugging Face layout these links have."),
    ("qwen", "Qwen-Image", ""),
    ("krea", "Krea 2", ""),
    ("ernie", "ERNIE-Image", ""),
    ("pid", "PiD", "Its VAE depends on the model, and is left to you."),
)


def preset_classes(preset: str) -> List[str]:
    """The model classes a preset runs, that need modules."""
    return [cls for cls, p in PRESET_BY_CLASS.items() if p == preset and cls in CLASS_FILES]


def preset_files(preset: str) -> List[Tuple[str, List[str]]]:
    """(file, the classes needing it), for a preset, in the order they come."""
    files: Dict[str, List[str]] = {}
    for cls in preset_classes(preset):
        for f in CLASS_FILES[cls]:
            files.setdefault(f, []).append(cls)
    return list(files.items())

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


def match_vae(name: str, labels) -> Optional[str]:
    """
    The installed module an image's VAE name means, as Forge lists it.

    Generation data usually carries the bare name while Forge lists the file,
    so "vae-ft-mse-840000" has to find "vae-ft-mse-840000-ema-pruned.safetensors":
    the file itself first, then one named the same without its extension, then
    one whose name starts with it. Case does not matter.
    """
    if not name:
        return None
    labels = list(labels)
    if name in labels:
        return name
    wanted = name.lower()
    exact = _match(name, labels)
    if exact:
        return exact
    return next((label for label in labels if label.lower().startswith(wanted)), None)


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
    """The files the settings name for a UI preset, as written there - none
    for a preset the settings have no list for (sd, xl)."""
    if not preset or SETTING_PREFIX + preset not in DEFAULTS:
        return []
    return parse_file_names(setting(SETTING_PREFIX + preset))


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
         saved: List[str], preferred: List[str] = (),
         own: Optional[str] = None, own_vae: bool = False) -> Dict[str, object]:
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
        own: the label of the gallery's own file, sent from a VAE's or a
            text encoder's gallery (#134): it takes its place whatever else
            would - a VAE (own_vae) the VAE's, of whatever kind, since it is
            the one asked for; a text encoder its kind's - and is selected
            beside the rest where it has no place.

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

    own_kind = modules.get(own, (None, 0))[0] if own else None
    select, missing = [], []
    for kind in needed:
        if own and own not in select and (kind == own_kind or (own_vae and kind.startswith("vae"))):
            select.append(own)
            continue
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
        select += [label for label in unknown if label not in select]
        missing = []
    if own and own not in select:
        select.append(own)
    return {"needed": needed, "select": select, "missing": missing, "not_found": not_found}


# ------------------------------------------------------------------ settings
# The settings window's table: for each preset, each file it needs, what is
# installed that could be it, what Send to txt2img would pick unasked, and
# which the settings name.

PRECISION_NAMES = {0: "GGUF", 1: "fp8", 2: "full"}


def describe_presets(presets: Optional[List[str]],
                     modules: Dict[str, Tuple[Optional[str], int]],
                     settings: Dict[str, str],
                     saved_for=saved_modules) -> List[Dict[str, object]]:
    """
    Each preset's files, for the settings window.

    Args:
        presets: the presets this WebUI has; None for every one.
        modules: label -> (kind, precision), for everything installed.
        settings: preset -> the setting's text, as it stands.
        saved_for: the labels Forge remembers for a preset.

    Returns:
        Per preset: its rows - one per file, with the installed candidates
        of its kind, the automatic pick (pick() with nothing named) and the
        one the setting names - and `kept`: names in the setting that no row
        takes, which the window keeps as they are.
    """
    answer = []
    for preset, label, note in MODULE_PRESETS:
        if presets is not None and preset not in presets:
            continue
        saved = saved_for(preset)
        automatic: Dict[str, str] = {}
        for cls in preset_classes(preset):
            for chosen in pick(cls, preset, False, False, modules, saved)["select"]:
                automatic.setdefault(modules[chosen][0], chosen)

        rows = []
        for f, classes in preset_files(preset):
            kind = FILES[f].kind
            rows.append({
                "file": f, "label": FILES[f].label, "kind": kind,
                "used_by": [CLASS_LABELS[c] for c in classes],
                "candidates": sorted(
                    ({"label": m, "precision": PRECISION_NAMES.get(p, "")}
                     for m, (k, p) in modules.items() if k == kind),
                    key=lambda c: c["label"].lower()),
                "automatic": automatic.get(kind),
                "selected": None,
                "links": [[name, HF + path] for name, path in FILES[f].links],
            })

        kept = []
        for name in parse_file_names(settings.get(preset, "")):
            found = _match(name, modules)
            row = next((r for r in rows if found and r["kind"] == modules[found][0]
                        and r["selected"] is None), None)
            if row:
                row["selected"] = found
            else:
                kept.append({"name": name, "why": (
                    "not installed" if found is None
                    else "not identified" if modules[found][0] is None
                    else "not a file this preset needs")})

        answer.append({"preset": preset, "label": label, "note": note,
                       "setting": SETTING_PREFIX + preset,
                       "classes": [CLASS_LABELS[c] for c in preset_classes(preset)],
                       "rows": rows, "kept": kept})
    return answer
