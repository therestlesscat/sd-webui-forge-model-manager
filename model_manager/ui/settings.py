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
            default=10,
            label="Models per page",
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
