"""
The options page, under Settings -> Model Manager.

Anything a person sets once and expects to persist: the API key, page sizes,
where the database lives, how fast to call Civitai, card dimensions. Filters
belong to the tabs, not here - these are preferences, not a query. What each
setting is called, says and belongs to is the registry's
(`settings_registry.py`, #320); this registers it with Forge.
"""
import os

import gradio as gr
from modules import shared

from ..forge_host import DEFAULTS
from ..gallery import OLD_PAGE_SIZE_SETTING, PAGE_SETTINGS
from ..generations import GENERATIONS_HIDE_NSFW
from ..image_sync import FOLDERS_OFF_SETTING, FOLDERS_SETTING
from .. import prompt_levels
from ..scheduler import QUEUE_ENABLED
from ..settings_registry import CATEGORY, all_settings, section
from ..update_check import SETTING as CHECK_UPDATES, check_soon
from ..forge_modules import (CLASS_FILES, CLASS_LABELS, FILES, HF, MODULE_PRESETS,
                             SETTING_PREFIX, preset_classes, preset_files)


def on_ui_settings():
    """
    Register extension settings: each from the registry (#320), under its
    page name and description, in its group's section of the Model Manager
    category.
    """
    data = shared.opts.data
    carry_over_page_sizes(data)
    # This one setting used to decide the gallery as well, so whoever turned
    # it off for newer thumbnails also got explicit images in every gallery.
    # Split, the gallery starts from what the old setting said - once: after
    # that the value is saved with the rest, and the two are independent. The
    # Generations tab followed the gallery's setting, and starts from it so.
    carried = carry_over_gallery_nsfw(data)
    carried_generations = carry_over_generations_nsfw(data)

    try:
        from modules.options import categories
        categories.register_category(*CATEGORY)
    except ImportError:            # a stand-in WebUI, in the suites
        pass

    changed = {
        QUEUE_ENABLED: _queue_enabled_changed,
        # The queue follows a new number at once (#279).
        "model_manager_downloads_at_once": _downloads_at_once_changed,
        CHECK_UPDATES: _check_updates_changed,
        "model_manager_nsfw_prompt_words": _prompt_words_changed,
        "model_manager_nsfw_detection": _prompt_words_changed,
        "model_manager_nsfw_prompt_model_percent": _prompt_words_changed,
    }
    presets = {SETTING_PREFIX + preset: note for preset, _, note in MODULE_PRESETS}
    for s in all_settings():
        if s.key == SETTING_PREFIX + MODULE_PRESETS[0][0]:
            _add_modules_explanation(section(s))
        args = {"type": "password"} if s.control == "password" else {
            k: list(v) if k == "choices" else v for k, v in s.args.items()}
        text = s.description
        if s.key in presets:
            preset = s.key[len(SETTING_PREFIX):]
            args, text = {"placeholder": _module_example(preset)}, _module_help(preset, presets[s.key])
        shared.opts.add_option(s.key, shared.OptionInfo(
            default=DEFAULTS[s.key],
            label=s.page_name,
            component=COMPONENTS[s.control],
            component_args=args,
            onchange=changed.get(s.key),
            section=section(s),
            category_id=CATEGORY[0],
        ).info(text))

    if carried is not None:
        data[GALLERY_HIDE_NSFW] = carried
    if carried_generations is not None:
        data[GENERATIONS_HIDE_NSFW] = carried_generations

    # Sync images (#233): the two folder lists are its dialog's to change - a
    # folder typed here as text breaks too easily - so they are kept out of
    # every settings page: Forge skips a setting whose section starts with None.
    hidden = (None, "Model Manager")
    for key in (FOLDERS_SETTING, FOLDERS_OFF_SETTING):
        shared.opts.add_option(key, shared.OptionInfo(default=DEFAULTS[key], label=key, section=hidden))


COMPONENTS = {"checkbox": gr.Checkbox, "slider": gr.Slider, "number": gr.Number, "dropdown": gr.Dropdown,
              "radio": gr.Radio, "textbox": gr.Textbox, "password": gr.Textbox}


def _add_modules_explanation(where):
    """What the text encoders and VAE settings are for, at their head in Send's section."""
    explanation = shared.OptionHTML(
        "<b>Send: text encoders and VAE.</b> Sending an image from a "
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
    explanation.section = where
    explanation.category_id = CATEGORY[0]
    shared.opts.add_option("model_manager_modules_explanation", explanation)


GALLERY_HIDE_NSFW = "model_manager_gallery_hide_nsfw"



def carry_over_page_sizes(data):
    """
    The page sizes' first values (#230), from the one setting they were split
    out of: each with no value of its own takes the old one's, once; then the
    old one goes from the saved settings, so the next save does not write it
    back. Someone who had 50 has 50 in all four.

    Args:
        data: the saved settings, as `shared.opts.data` holds them - changed in place.
    """
    if OLD_PAGE_SIZE_SETTING not in data:
        return
    old = data.pop(OLD_PAGE_SIZE_SETTING)
    for key in PAGE_SETTINGS:
        data.setdefault(key, old)


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


def carry_over_generations_nsfw(data):
    """
    The Generations tab's first value: the image gallery setting it used to
    follow, as that would read now; None once it has one of its own.

    Args:
        data: the saved settings, as `shared.opts.data` holds them.
    """
    if GENERATIONS_HIDE_NSFW in data:
        return None
    gallery = carry_over_gallery_nsfw(data)
    return bool(data.get(GALLERY_HIDE_NSFW, True)) if gallery is None else gallery


def _queue_enabled_changed():
    # Off, a running queue stops: its tab and its buttons are gone.
    from ..scheduler import queue_enabled, runner
    if not queue_enabled():
        runner.stop()


def _downloads_at_once_changed():
    # The queue follows the new number at once (#279) - only a queue already
    # made: making one here would restore the kept downloads before any tab
    # asked for them.
    from ..download_service import configured_downloads_at_once, current_download_service
    service = current_download_service()
    if service is not None:
        service.set_limit(configured_downloads_at_once())


def _check_updates_changed():
    # Turned on, check now rather than in up to 12 hours; off, the next
    # check asks nothing.
    check_soon()


def _prompt_words_changed():
    """Judge stored images again with the new words, in the background."""
    prompt_levels.start_in_background()


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
