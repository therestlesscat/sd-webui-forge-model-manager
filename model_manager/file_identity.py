"""
What a model file is, and which model it is for - from the file alone.

Civitai files an upload under the type its uploader picked: a VAE shared as
a "Checkpoint", a text encoder as a "LORA", and a file Civitai does not know
has no type at all. The file itself says what it is. Its tensor names and
shapes, read from the header (architecture.read_shapes) and never the
weights, give:

    type          what the file is - Checkpoint, LORA, LoCon, LoHa, LoKr,
                  DoRA, LyCORIS Full, TextualInversion, Hypernetwork, VAE,
                  Text Encoder, Upscaler, or Unknown. Civitai's names where
                  Civitai has the type, the plain name where it does not.
    architecture  the Forge Neo preset it is for ("xl", "flux", ...), when
                  the file ties to exactly one. A VAE often does not: SD 1.x
                  and SDXL VAEs are shaped alike, and Qwen-Image, Wan, Anima
                  and Krea 2 share one.

A checkpoint is judged by Forge's own detector (architecture.detect_shapes),
a VAE or text encoder by the module reader (forge_modules.classify). The
rest is here: the LoRA family by the names of the layers it adapts, which
differ between architectures, and by their widths where names are shared -
SD 1.x and SDXL both have attn2, but its context is 768 wide in one and 2048
in the other. Measured on a library of 1,262 files: all but eight
identified, those eight being a type whose base model the file cannot tell
(SD3, HiDream, an 8-tensor LoRA on a block SD and SDXL share).
"""
import re
from typing import Callable, Dict, Optional, Tuple

from .architecture import (Architecture, PRESET_BY_CLASS, detect_shapes,
                           read_shapes)
from .forge_modules import NEEDS, classify as classify_module

Shapes = Dict[str, Tuple[Tuple[int, ...], str]]

# Every type, in the order the Type filter lists them.
FILE_TYPES = ("Checkpoint", "LORA", "LoCon", "LoHa", "LoKr", "DoRA", "LyCORIS Full",
              "TextualInversion", "Hypernetwork", "VAE", "Text Encoder", "Upscaler",
              "Unknown")

# The context width of an SD-family cross-attention -> preset. SD 2.x has no
# Forge Neo preset.
_CONTEXT = {768: "sd", 2048: "xl"}
_CONTEXT_NAMES = {768: "SD 1.x", 1024: "SD 2.x", 2048: "SDXL"}

# Weight names a LoRA-family file stores beside, or instead of, the layer.
_ADAPTER = re.compile(r"(lora_(up|down|A|B|mid)|hada_w|lokr_w|dora_scale|\.alpha$|\.diff(_b)?$)")

# A whole model's own prefixes - a checkpoint Forge's detector did not take.
_WHOLE_MODEL = ("model.diffusion_model.", "first_stage_model.", "conditioner.",
                "cond_stage_model.", "net.")


def identify(path: str, guess: Callable = None) -> Architecture:
    """What a model file is. Unreadable is Unknown, never an error."""
    shapes = read_shapes(path)
    if not shapes:
        return Architecture(None, None, False, False, "Unknown",
                            "not a format whose header can be read")
    return identify_shapes(shapes, guess)


def identify_shapes(shapes: Shapes, guess: Callable = None) -> Architecture:
    """identify(), for tensors already read."""
    names = list(shapes)

    found = detect_shapes(shapes, guess)
    if found:
        return found

    if any(_ADAPTER.search(n) for n in names):
        return _adapter(shapes)

    if any(n.startswith(_WHOLE_MODEL) for n in names):
        return _checkpoint_forge_refused(shapes)

    kind = classify_module(shapes, loadable_only=False)
    if kind:
        file_type = "VAE" if kind.startswith("vae") else "Text Encoder"
        return Architecture(_preset_for_module(kind), None, False, False, file_type,
                            f"a {kind} by its shapes")

    for found in (_embedding(shapes), _hypernetwork(shapes), _upscaler(names)):
        if found:
            return found

    preset, how = _layout(shapes)
    if preset:                      # a bare diffusion model Forge did not take
        return Architecture(preset, None, False, False, "Checkpoint", how)
    return Architecture(None, None, False, False, "Unknown", "no layout this knows")


def _preset_for_module(kind: str) -> Optional[str]:
    """The preset a VAE or text encoder serves, if it serves exactly one."""
    presets = {PRESET_BY_CLASS[cls] for cls, (encoders, vae) in NEEDS.items()
               if kind in encoders or kind == vae}
    return presets.pop() if len(presets) == 1 else None


def _checkpoint_forge_refused(shapes: Shapes) -> Architecture:
    """
    A whole checkpoint Forge's detector did not recognise: what it is, if a
    family Forge Neo cannot run, else what its layers say.
    """
    names = list(shapes)
    if any("joint_blocks" in n for n in names):
        return Architecture(None, None, False, False, "Checkpoint",
                            "SD3 / SD3.5 - Forge Neo has no preset for it")
    if any("double_stream_blocks" in n for n in names):
        return Architecture(None, None, False, False, "Checkpoint",
                            "HiDream - Forge Neo has no preset for it")
    preset, how = _layout(shapes)
    return Architecture(preset, None, False, False, "Checkpoint",
                        f"not recognised by Forge's detector; {how}")


def _adapter(shapes: Shapes) -> Architecture:
    """A LoRA-family file: its format from its weights, its model from its layers."""
    names = list(shapes)
    if any(n.endswith("dora_scale") for n in names):
        file_type = "DoRA"
    elif any(".hada_w" in n for n in names):
        file_type = "LoHa"
    elif any(".lokr_w" in n for n in names):
        file_type = "LoKr"
    elif any(re.search(r"\.diff$", n) for n in names) \
            and not any(re.search(r"\.lora_(up|down|A|B)\.", n) for n in names):
        file_type = "LyCORIS Full"
    elif any(re.search(r"\.(lora_down|lora_A)\.", n) and len(shapes[n][0]) == 4
             and shapes[n][0][2:] != (1, 1) for n in names):
        file_type = "LoCon"         # LoRA on the 3x3 convolutions as well
    else:
        file_type = "LORA"
    preset, how = _layout(shapes)
    return Architecture(preset, None, False, False, file_type, how)


def _layout(shapes: Shapes) -> Tuple[Optional[str], str]:
    """
    (preset, how it was told) from the names of the layers a file touches.

    Names are compared with dots and underscores alike - kohya writes
    lora_unet_double_blocks_0_img_attn_proj for double_blocks.0.img_attn.proj.
    Order matters where one family's names contain another's: Anima's
    self_attn.q_proj before Wan's self_attn.q.
    """
    flat = {n.replace(".", "_"): s[0] for n, s in shapes.items()}

    def has(pattern):
        return any(re.search(pattern, n) for n in flat)

    def width(pattern, axis=-1):
        # The largest: a LoRA splits a layer in two, and one half's side is
        # only the LoRA's rank.
        return max((s[axis] for n, s in flat.items() if re.search(pattern, n) and len(s) >= 2),
                   default=None)

    if has(r"text_fusion|txtfusion"):
        return "krea", "Krea 2's text fusion blocks"
    if has(r"double_blocks|single_blocks|single_transformer_blocks"):
        return _flux(flat, width)
    if has(r"transformer_blocks_\d+_(img_mlp|txt_mlp|img_mod|txt_mod)"):
        return "qwen", "Qwen-Image's image and text streams"
    if has(r"blocks_\d+_(self_attn_q_proj|mlp_layer1|adaln_modulation)|llm_adapter"):
        return "anima", "Anima's blocks"
    if has(r"blocks_\d+_(self_attn|cross_attn)_[qkvo](_|$)|blocks_\d+_ffn_\d"):
        return "wan", "Wan's attention and feed-forward blocks"
    if has(r"layers_\d+_mlp_linear_fc"):
        return "ernie", "ERNIE-Image's layers"
    if has(r"layers_\d+_attention_(to_[qkv]|qkv)|context_refiner|noise_refiner"):
        w = width(r"layers_\d+_attention_(to_k|to_q|qkv)")
        preset = {3840: "zit", 2304: "lumina"}.get(w)
        return preset, f"Lumina-style layers, {w} wide ({'Z-Image' if w == 3840 else 'Lumina 2' if w == 2304 else 'neither'})"
    if has(r"input_blocks|output_blocks|middle_block|down_blocks|up_blocks|mid_block|lora_te\d?_"):
        return _sd_family(flat, has)
    return None, "no layer names this knows"


def _flux(flat, width) -> Tuple[Optional[str], str]:
    """
    Flux.1 (and Chroma) or Flux.2 Klein: the same block names, told apart by
    their MLP. Flux.1's is 4x the hidden width. Flux.2's is 3x, and gated, so
    the layer into it is doubled. Whichever MLP-side layer a file touches
    gives the ratio:

        layer                        side     Flux.1   Flux.2
        single_blocks.N.linear1      out      7x       9x
        single_blocks.N.linear2      in       5x       4x
        double_blocks.N.img_mlp.0    out      4x       6x
        double_blocks.N.img_mlp.2    in       4x       3x
    """
    hidden = (width(r"double_blocks_\d+_(img|txt)_attn_proj")
              or width(r"single_blocks_\d+_linear2", axis=0)
              or width(r"single_blocks_\d+_linear1")
              or width(r"single_transformer_blocks_\d+_attn_to_q"))
    if not hidden:
        return None, "Flux-style blocks, their width not in the file"
    signals = (
        (width(r"single_blocks_\d+_linear1", axis=0), {7: "flux", 9: "klein"}),
        (width(r"single_blocks_\d+_linear2"), {5: "flux", 4: "klein"}),
        (width(r"double_blocks_\d+_(img|txt)_mlp_0", axis=0), {4: "flux", 6: "klein"}),
        (width(r"double_blocks_\d+_(img|txt)_mlp_2"), {4: "flux", 3: "klein"}),
    )
    for size, by_ratio in signals:
        if size and size % hidden == 0 and size // hidden in by_ratio:
            preset = by_ratio[size // hidden]
            return preset, (f"Flux-style blocks, {hidden} wide, "
                            f"{'Flux.1' if preset == 'flux' else 'Flux.2'} MLP")
    if hidden == 4096:
        return "klein", "Flux-style blocks, 4096 wide (Flux.2 Klein 9B)"
    return None, f"Flux-style blocks, {hidden} wide - Flux.1 or Flux.2 Klein 4B; no MLP layer to tell"


def _sd_family(flat, has) -> Tuple[Optional[str], str]:
    """SD 1.x, SD 2.x or SDXL: the cross-attention's context width decides."""
    context = next((s[-1] for n, s in flat.items() if re.search(r"attn2_to_[kv]", n)
                    and s and s[-1] in _CONTEXT_NAMES), None)
    if context:
        return _CONTEXT.get(context), f"cross-attention context {context} wide ({_CONTEXT_NAMES[context]})"
    if has(r"lora_te[12]_|label_emb|add_embedding|transformer_blocks_[1-9]"):
        return "xl", "layers only SDXL has"
    encoder = next((s[-1] for n, s in flat.items()
                    if re.search(r"lora_te_text_model_encoder_layers_\d+_self_attn_q_proj", n)
                    and s and s[-1] in (768, 1024)), None)
    if encoder:
        return _CONTEXT.get(encoder), f"text encoder {encoder} wide ({_CONTEXT_NAMES[encoder]})"
    return None, "SD-style layers, none that tell SD 1.x from SDXL"


def _embedding(shapes: Shapes) -> Optional[Architecture]:
    """A textual inversion: a few vectors, as wide as the text encoder."""
    if "clip_l" in shapes and "clip_g" in shapes:
        return Architecture("xl", None, False, False, "TextualInversion",
                            "CLIP-L and CLIP-G vectors (SDXL)")
    for name in ("emb_params", "string_to_param.*"):
        if name in shapes and len(shapes[name][0]) == 2:
            w = shapes[name][0][1]
            return Architecture(_CONTEXT.get(w), None, False, False, "TextualInversion",
                                f"vectors {w} wide ({_CONTEXT_NAMES.get(w, 'unknown')})")
    return None


def _hypernetwork(shapes: Shapes) -> Optional[Architecture]:
    """
    A hypernetwork: small networks keyed by the attention width they sit
    on - 768, 320, 640, 1280 for SD 1.x. The context width among them says
    which model.
    """
    widths = {int(n.split(".")[0]) for n in shapes if re.match(r"\d+\.\d+\.linear\.", n)}
    if not widths:
        return None
    context = next((w for w in (2048, 1024, 768) if w in widths), None)
    return Architecture(_CONTEXT.get(context), None, False, False, "Hypernetwork",
                        f"layers for widths {sorted(widths)} ({_CONTEXT_NAMES.get(context, 'unknown')})")


def _upscaler(names) -> Optional[Architecture]:
    """An ESRGAN-style upscaler - for any model, so no preset."""
    if "conv_first.weight" in names or ("model.0.weight" in names
                                        and any(n.startswith("model.1.sub.") for n in names)):
        return Architecture(None, None, False, False, "Upscaler", "an ESRGAN-style upscaler")
    return None
