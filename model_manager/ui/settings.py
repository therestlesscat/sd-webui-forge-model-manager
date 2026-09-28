"""
The options page, under Settings -> Model Manager.

Anything a person sets once and expects to persist: the API key, page sizes,
where the database lives, how fast to call Civitai, card dimensions. Filters
belong to the tabs, not here - these are preferences, not a query.
"""
import os

import gradio as gr
from modules import shared

from ..generations import RECORD_GENERATIONS
from ..forge_modules import (CLASS_FILES, CLASS_LABELS, FILES, HF, MODULE_PRESETS,
                             SETTING_PREFIX, preset_classes, preset_files)

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
            label="Model Manager: card thumbnail is the least explicit image",
            component=gr.Checkbox,
            section=section,
        ).info("If enabled, each card shows the model's least explicit image. If disabled, "
               "its most recent one. Whether the image gallery hides explicit images is "
               "its own setting, below.")
    )

    # This one setting used to decide the gallery as well, so whoever turned
    # it off for newer thumbnails also got explicit images in every gallery.
    # Split, the gallery starts from what the old setting said - once: after
    # that the value is saved with the rest, and the two are independent.
    carried = carry_over_gallery_nsfw(shared.opts.data)
    shared.opts.add_option(
        GALLERY_HIDE_NSFW,
        shared.OptionInfo(
            default=True,
            label="Image gallery: hide explicit images by default",
            component=gr.Checkbox,
            section=section,
        ).info("How a model's image gallery opens, in the Model Manager and the Civitai "
               "Browser. The Show NSFW switch above the images shows them for that model. "
               "The Civitai Browser's Include NSFW models decides which models are listed, "
               "not which of their images are shown.")
    )
    if carried is not None:
        shared.opts.data[GALLERY_HIDE_NSFW] = carried

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
        RECORD_GENERATIONS,
        shared.OptionInfo(
            default=True,
            label="Your generations: record each image generated",
            component=gr.Checkbox,
            section=section,
        ).info("Every txt2img and img2img result that is saved to disk is recorded with "
               "all its settings, and shown in the gallery of each model it used. Only "
               "images generated while this is on are recorded; turning it off keeps "
               "what was recorded.")
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
        ).info("How fast to call the Civitai API when an API key is set. Higher is faster but more likely to be rate limited. Applies to the next search, download or sync; one already running keeps its rate.")
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

    shared.opts.add_option(
        "model_manager_nsfw_detection",
        shared.OptionInfo(
            default="model",
            label="NSFW detection: what finds explicit images Civitai rates PG or PG-13",
            component=gr.Radio,
            component_args={"choices": [
                ("Trained model - catches more, and is sometimes wrong", "model"),
                ("Word list - only the words below", "words"),
            ]},
            onchange=_prompt_words_changed,
            section=section,
        ).info("The trained model reads each image's prompts and the resources it used, and "
               "catches most of the explicit images Civitai under-rates - but it judges by "
               "what it learned, and sometimes raises an image that is fine or misses one that "
               "is not. The word list treats an image as X only when its prompt uses one of "
               "the words: nothing else, and nothing you cannot check. Stored images are "
               "judged again in the background when this changes.")
    )

    shared.opts.add_option(
        "model_manager_nsfw_prompt_model_percent",
        shared.OptionInfo(
            default=2.0,
            label="NSFW: trained model - % of PG/PG-13 prompts to treat as X",
            component=gr.Number,
            component_args={"minimum": 0, "maximum": 20, "step": 0.25},
            onchange=_prompt_words_changed,
            section=section,
        ).info("Civitai rates some explicit images PG or PG-13. A model trained on image "
               "prompts - their words, word pairs, negative, ADetailer and hires prompts, and "
               "the resources used - finds them, and this is how far it goes: the share of PG "
               "and PG-13 prompts it may treat as X. 2 (default) caught about 94% of X/XXX "
               "prompts on a library it had never seen. 1 is stricter, 3 or more catches more "
               "at more cost. 0 turns the model off, leaving only the words. Applies with NSFW "
               "detection set to Trained model. Stored images are judged again in the "
               "background when this changes.")
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
    for preset, label, note in MODULE_PRESETS:
        shared.opts.add_option(
            SETTING_PREFIX + preset,
            shared.OptionInfo(
                default="",
                label=f"Send to txt2img: {label} text encoders and VAE",
                component=gr.Textbox,
                component_args={"placeholder": _module_example(preset)},
                section=section,
            ).info(_module_help(preset, note))
        )


GALLERY_HIDE_NSFW = "model_manager_gallery_hide_nsfw"



def carry_over_gallery_nsfw(data):
    """
    The gallery setting's first value, from the setting it was split out of;
    None once it has one of its own.

    Args:
        data: the saved settings, as `shared.opts.data` holds them.
    """
    if GALLERY_HIDE_NSFW in data:
        return None
    return bool(data.get("model_manager_preview_least_nsfw", True))


def _prompt_words_changed():
    """Judge stored images again with the new words, in the background."""
    from ..prompt_levels import start_in_background
    start_in_background()


# Forge Neo's list of every module file, and the source of the links in
# forge_modules.FILES.
DOWNLOAD_MODELS = "https://github.com/Haoming02/sd-webui-forge-classic/wiki/Download-Models"


def _and(items):
    items = list(items)
    return items[0] if len(items) < 2 else ", ".join(items[:-1]) + " and " + items[-1]


def _module_help(preset: str, note: str) -> str:
    """What a preset's models need, and where to get it - from forge_modules,
    which the settings window's table reads too."""
    groups = {}
    for cls in preset_classes(preset):
        groups.setdefault(CLASS_FILES[cls], []).append(CLASS_LABELS[cls])
    needs = [_and(FILES[f].label for f in files) for files in groups]
    if len(groups) == 1:
        text = "Needs " + needs[0]
    else:
        text = "; ".join("%s %s %s" % (_and(classes), "need" if len(classes) > 1 else "needs", n)
                         for classes, n in zip(groups.values(), needs))
    links = []
    for f, _ in preset_files(preset):
        for name, path in FILES[f].links:
            link = f"<a href='{HF}{path}' target='_blank'>{name}</a>"
            if link not in links:
                links.append(link)
    return text + ". " + (note + " " if note else "") + "Download: " + ", ".join(links)


def _module_example(preset: str) -> str:
    """File names such a setting might hold: the last-listed, and smallest,
    download of each file the preset needs."""
    return ", ".join(os.path.basename(FILES[f].links[-1][1]) for f, _ in preset_files(preset))
