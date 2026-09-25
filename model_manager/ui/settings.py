"""
The options page, under Settings -> Model Manager.

Anything a person sets once and expects to persist: the API key, page sizes,
where the database lives, how fast to call Civitai, card dimensions. Filters
belong to the tabs, not here - these are preferences, not a query.
"""
import gradio as gr
from modules import shared

EXTENSION_NAME = "Model Manager"


def on_ui_settings():
    """Register extension settings."""
    section = ("model_manager", EXTENSION_NAME)

    shared.opts.add_option(
        "model_manager_civitai_api_key",
        shared.OptionInfo(
            default="",
            label="Civitai API Key",
            component=gr.Textbox,
            component_args={"type": "password"},
            section=section,
        ).info("Optional. Provides higher rate limits for Civitai API requests.")
    )

    shared.opts.add_option(
        "model_manager_page_size",
        shared.OptionInfo(
            default=20,
            label="Model Manager: Models per page",
            component=gr.Slider,
            component_args={
                "minimum": 5,
                "maximum": 50,
                "step": 5,
            },
            section=section,
        ).info("Number of models to display per page.")
    )

    shared.opts.add_option(
        "model_manager_database_path",
        shared.OptionInfo(
            default="",
            label="Custom Database Path",
            component=gr.Textbox,
            component_args={"placeholder": "e.g., F:\\shared\\models.db"},
            section=section,
        ).info("Full path to database file (including filename). Leave empty to use default location in extension folder. Requires restart to take effect.")
    )

    shared.opts.add_option(
        "model_manager_preview_least_nsfw",
        shared.OptionInfo(
            default=True,
            label="Preview: Use least NSFW image",
            component=gr.Checkbox,
            section=section,
        ).info("If enabled, model previews show the least NSFW image. If disabled, shows the most recent image.")
    )

    # Civitai Browser settings
    shared.opts.add_option(
        "model_manager_civitai_page_size",
        shared.OptionInfo(
            default=20,
            label="Civitai Browser: Models per page",
            component=gr.Slider,
            component_args={
                "minimum": 5,
                "maximum": 50,
                "step": 5,
            },
            section=section,
        ).info("Number of models to display per page in Civitai Browser.")
    )

    shared.opts.add_option(
        "model_manager_hide_promptless_images",
        shared.OptionInfo(
            default=True,
            label="Example images: hide the ones with no prompt",
            component=gr.Checkbox,
            section=section,
        ).info("About a tenth of Civitai's images carry no prompt at all, and "
               "they cannot be read or reused. Can be turned back on per model "
               "from the panel above the images.")
    )

    shared.opts.add_option(
        "model_manager_image_browsing",
        shared.OptionInfo(
            default="continuous",
            label="Example images: how to move through them",
            component=gr.Radio,
            component_args={"choices": [
                ("Continuous - one list, with a button to show more", "continuous"),
                ("Pages - a page at a time, with page controls", "pages"),
            ]},
            section=section,
        ).info("Continuous keeps your place as more images appear. Pages jumps "
               "back to the top of the list each time a page is added.")
    )

    shared.opts.add_option(
        "model_manager_civitai_folder_template",
        shared.OptionInfo(
            default="_{baseModel}/{modelName}",
            label="Civitai Browser: Download folder template",
            component=gr.Textbox,
            component_args={"placeholder": "_{baseModel}/{modelName}"},
            section=section,
        ).info("Subfolder template for downloads. Placeholders: {baseModel}, {modelName}, {creator}, {modelId}")
    )

    shared.opts.add_option(
        "model_manager_civitai_requests_per_second",
        shared.OptionInfo(
            default=6,
            label="Civitai: Requests per second",
            component=gr.Slider,
            component_args={
                "minimum": 1,
                "maximum": 10,
                "step": 1,
            },
            section=section,
        ).info("How fast to call the Civitai API when an API key is set. Higher is faster but more likely to be rate limited. Requires restart.")
    )

    shared.opts.add_option(
        "model_manager_hash_threads",
        shared.OptionInfo(
            default=4,
            label="Sync: Hashing threads",
            component=gr.Slider,
            component_args={
                "minimum": 1,
                "maximum": 16,
                "step": 1,
            },
            section=section,
        ).info("How many model files to hash at once when identifying them. "
               "Identifying a file means reading all of it, so this is usually "
               "limited by the drive rather than the CPU, and past the point "
               "where the drive is saturated more threads buy nothing. Raise it "
               "for a fast NVMe or an array, lower it for a spinning disk, where "
               "parallel reads make the head seek, or if a sync makes the machine "
               "unresponsive.")
    )

    shared.opts.add_option(
        "model_manager_civitai_min_prompt_images",
        shared.OptionInfo(
            default=1,
            label="Civitai Browser: Minimum images with usable prompt",
            component=gr.Slider,
            component_args={
                "minimum": 1,
                "maximum": 20,
                "step": 1,
            },
            section=section,
        ).info("When 'Only with usable prompts' is enabled, a model must have at least this many images (out of the first 20) carrying a prompt plus steps/sampler/CFG.")
    )

    shared.opts.add_option(
        "model_manager_civitai_sfw_fill_page",
        shared.OptionInfo(
            default=False,
            label="Civitai Browser: Fill every page with 'Only Show Models with SFW images' (not recommended)",
            component=gr.Checkbox,
            section=section,
        ).info("Not recommended. Normally a page with 'Only Show Models with SFW images' stops after "
               "checking a few dozen models and can come back short. With this on, it "
               "keeps searching until the page holds the full Models per page. Most "
               "Civitai models have NSFW images, so one page can take hundreds of "
               "requests and several minutes, and makes Civitai's rate limit likely. "
               "A page still stops if Civitai starts refusing requests.")
    )

    # Card size settings
    shared.opts.add_option(
        "model_manager_card_size",
        shared.OptionInfo(
            default="200x280",
            label="Model Manager: Card size (WIDTHxHEIGHT)",
            component=gr.Textbox,
            component_args={"placeholder": "200x280"},
            section=section,
        ).info("Size of model cards in Model Manager. Format: WIDTHxHEIGHT in pixels.")
    )

    shared.opts.add_option(
        "model_manager_civitai_card_size",
        shared.OptionInfo(
            default="200x280",
            label="Civitai Browser: Card size (WIDTHxHEIGHT)",
            component=gr.Textbox,
            component_args={"placeholder": "200x280"},
            section=section,
        ).info("Size of model cards in Civitai Browser. Format: WIDTHxHEIGHT in pixels.")
    )

    shared.opts.add_option(
        "model_manager_nsfw_prompt_words",
        shared.OptionInfo(
            default="",
            label="NSFW: extra prompt words",
            component=gr.Textbox,
            component_args={"placeholder": "comma-separated words", "lines": 2},
            onchange=_prompt_words_changed,
            section=section,
        ).info("An image Civitai rates PG or PG-13 whose prompt uses one of these words is "
               "treated as X everywhere - hidden from the grid previews, the galleries and "
               "the SFW filters. Whole words, any case. These add to the list that comes "
               "with the extension, in model_manager/data/nsfw_prompt_words.txt. Stored "
               "images are judged again in the background when this changes.")
    )

    # The text encoders and VAE Send to txt2img selects, per Forge Neo preset
    explanation = shared.OptionHTML(
        "<b>Send to txt2img: text encoders and VAE.</b> Sending an image from a "
        "Flux, Qwen-Image, Wan or other newer model switches Forge Neo to that "
        "model's preset and selects the text encoders and VAE it needs. Left empty, "
        "each is picked from Forge's <i>VAE / Text Encoder</i> list automatically, "
        "preferring the highest-precision file. To use a particular file instead - "
        "an fp8 or GGUF version on a card with less memory - name it below: file "
        "names as Forge lists them, separated by commas, extension optional. A name "
        "is only used where it is the right kind of file, so one list can hold the "
        "files for every model of a preset. Text encoders go in "
        "<code>models/text_encoder</code>, VAEs in <code>models/VAE</code>. Forge "
        "Neo's <a href='" + DOWNLOAD_MODELS + "' target='_blank'>Download Models</a> "
        "page lists every file."
    )
    explanation.section = section
    shared.opts.add_option("model_manager_modules_explanation", explanation)
    for preset, label, needs, placeholder, links in MODULE_SETTINGS:
        shared.opts.add_option(
            f"model_manager_modules_{preset}",
            shared.OptionInfo(
                default="",
                label=f"Send to txt2img: {label} text encoders and VAE",
                component=gr.Textbox,
                component_args={"placeholder": placeholder},
                section=section,
            ).info(needs + ". Download: " + ", ".join(
                f"<a href='{HF}{path}' target='_blank'>{name}</a>" for name, path in links))
        )


def _prompt_words_changed():
    """Judge stored images again with the new words, in the background."""
    from ..prompt_levels import start_in_background
    start_in_background()


# Where each preset's files can be had. Forge Neo's own list, and the source
# of every link below.
DOWNLOAD_MODELS = "https://github.com/Haoming02/sd-webui-forge-classic/wiki/Download-Models"
HF = "https://huggingface.co/"

_CLIP_L = ("clip_l", "comfyanonymous/flux_text_encoders/blob/main/clip_l.safetensors")
_T5 = [("t5xxl fp16", "comfyanonymous/flux_text_encoders/blob/main/t5xxl_fp16.safetensors"),
       ("t5xxl fp8", "comfyanonymous/flux_text_encoders/blob/main/t5xxl_fp8_e4m3fn_scaled.safetensors")]
_AE = ("ae", "Comfy-Org/Lumina_Image_2.0_Repackaged/blob/main/split_files/vae/ae.safetensors")
_QWEN3_4B = [("qwen_3_4b", "Comfy-Org/z_image_turbo/blob/main/split_files/text_encoders/qwen_3_4b.safetensors"),
             ("qwen3_4b fp8", "jiangchengchengNLP/qwen3-4b-fp8-scaled/blob/main/qwen3_4b_fp8_scaled.safetensors")]
_FLUX2_VAE = ("flux2-vae", "Comfy-Org/vae-text-encorder-for-flux-klein-9b/blob/main/split_files/vae/flux2-vae.safetensors")
_QWEN_VAE = ("qwen_image_vae", "Comfy-Org/Qwen-Image_ComfyUI/blob/main/split_files/vae/qwen_image_vae.safetensors")
_KLEIN = "Comfy-Org/vae-text-encorder-for-flux-klein-9b/blob/main/split_files/text_encoders/"
_WAN = "Comfy-Org/Wan_2.1_ComfyUI_repackaged/blob/main/split_files/"
_QWEN = "Comfy-Org/Qwen-Image_ComfyUI/blob/main/split_files/text_encoders/"

# (preset, what it runs, what it needs, an example, download links)
MODULE_SETTINGS = [
    ("flux", "Flux.1 / Chroma",
     "Flux.1 needs CLIP-L, T5-XXL and the Flux VAE (ae); Chroma only T5-XXL and ae",
     "clip_l.safetensors, t5xxl_fp8_e4m3fn_scaled.safetensors, ae.safetensors",
     [_CLIP_L, *_T5, _AE]),
    ("klein", "Flux.2 Klein",
     "Klein 4B needs Qwen3 4B, Klein 9B needs Qwen3 8B; both need the Flux.2 VAE",
     "qwen_3_4b.safetensors, qwen_3_8b_fp8mixed.safetensors, flux2-vae.safetensors",
     [*_QWEN3_4B, ("qwen_3_8b", _KLEIN + "qwen_3_8b.safetensors"),
      ("qwen_3_8b fp8", _KLEIN + "qwen_3_8b_fp8mixed.safetensors"), _FLUX2_VAE]),
    ("lumina", "Lumina Image 2.0",
     "Needs Gemma 2 2B and the Flux VAE (ae)",
     "gemma_2_2b_fp16.safetensors, ae.safetensors",
     [("gemma_2_2b", "duongve/NetaYume-Lumina-Image-2.0/blob/main/Text_Encoder/gemma_2_2b_fp16.safetensors"), _AE]),
    ("zit", "Z-Image",
     "Needs Qwen3 4B and the Flux VAE (ae)",
     "qwen3_4b_fp8_scaled.safetensors, ae.safetensors",
     [*_QWEN3_4B, _AE]),
    ("anima", "Anima",
     "Needs Qwen3 0.6B and the Qwen-Image VAE",
     "qwen_3_06b_base.safetensors, qwen_image_vae.safetensors",
     [("qwen_3_06b_base", "circlestone-labs/Anima/blob/main/split_files/text_encoders/qwen_3_06b_base.safetensors"),
      _QWEN_VAE]),
    ("wan", "Wan",
     "Needs UMT5-XXL, in the Hugging Face layout these links have, and the Wan 2.1 VAE",
     "umt5_xxl_fp8_e4m3fn_scaled.safetensors, wan_2.1_vae.safetensors",
     [("umt5_xxl fp16", _WAN + "text_encoders/umt5_xxl_fp16.safetensors"),
      ("umt5_xxl fp8", _WAN + "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
      ("wan_2.1_vae", _WAN + "vae/wan_2.1_vae.safetensors")]),
    ("qwen", "Qwen-Image",
     "Needs Qwen2.5-VL 7B and the Qwen-Image VAE",
     "qwen_2.5_vl_7b_fp8_scaled.safetensors, qwen_image_vae.safetensors",
     [("qwen_2.5_vl_7b fp16", _QWEN + "qwen_2.5_vl_7b.safetensors"),
      ("qwen_2.5_vl_7b fp8", _QWEN + "qwen_2.5_vl_7b_fp8_scaled.safetensors"), _QWEN_VAE]),
    ("krea", "Krea 2",
     "Needs Qwen3-VL 4B and the Qwen-Image VAE",
     "qwen3vl_4b_fp8_scaled.safetensors, qwen_image_vae.safetensors",
     [("qwen3vl_4b bf16", "Comfy-Org/Krea-2/blob/main/text_encoders/qwen3vl_4b_bf16.safetensors"),
      ("qwen3vl_4b fp8", "Comfy-Org/Krea-2/blob/main/text_encoders/qwen3vl_4b_fp8_scaled.safetensors"),
      _QWEN_VAE]),
    ("ernie", "ERNIE-Image",
     "Needs Ministral 3 3B and the Flux.2 VAE",
     "ministral-3-3b.safetensors, flux2-vae.safetensors",
     [("ministral-3-3b", "Comfy-Org/ERNIE-Image/blob/main/text_encoders/ministral-3-3b.safetensors"), _FLUX2_VAE]),
    ("pid", "PiD",
     "Needs Gemma 2 2B IT; its VAE depends on the model and is left to you",
     "gemma_2_2b_it_elm_fp8_scaled.safetensors",
     [("gemma_2_2b_it bf16", "Comfy-Org/PixelDiT/blob/main/text_encoders/gemma_2_2b_it_elm_bf16.safetensors"),
      ("gemma_2_2b_it fp8", "Comfy-Org/PixelDiT/blob/main/text_encoders/gemma_2_2b_it_elm_fp8_scaled.safetensors")]),
]
