"""
The options page, under Settings -> Model Manager.

Anything a person sets once and expects to persist: the API key, page sizes,
where the database lives, how fast to call Civitai, card dimensions. Filters
belong to the tabs, not here - these are preferences, not a query.
"""
import os

import gradio as gr
from modules import shared

from ..forge_host import DEFAULTS
from ..gallery import (CB_IMAGES_SETTING, GENERATIONS_SETTING, MAX_PAGE_SIZE, MIN_PAGE_SIZE, MM_IMAGES_SETTING,
                       OLD_PAGE_SIZE_SETTING, PAGE_SETTINGS, SYNC_IMAGES_SETTING)
from ..generations import GENERATIONS_DELETE_FILES, GENERATIONS_HIDE_NSFW, RECORD_GENERATIONS
from ..grids import CHOICES as GRID_CHOICES, GALLERY_GRID, GENERATIONS_GRID
from ..tile_reading import CHOICES as READING_CHOICES, SETTING as READING_SETTING
from ..image_sync import FOLDERS_OFF_SETTING, FOLDERS_SETTING, GROUP_SETTING, LEVEL_SETTING
from ..nsfw import LEVEL_TO_NAME, UNKNOWN, USER_LEVELS
from .. import prompt_levels, thumbnails
from ..scheduler import QUEUE_ENABLED
from ..tabs import TABS
from ..update_check import SETTING as CHECK_UPDATES, check_soon
from ..forge_modules import (CLASS_FILES, CLASS_LABELS, FILES, HF, MODULE_PRESETS,
                             SETTING_PREFIX, preset_classes, preset_files)

EXTENSION_NAME = "Model Manager"
GALLERY_ENABLED = TABS["gallery"]
MODEL_MANAGER_ENABLED = TABS["model_manager"]
CIVITAI_BROWSER_ENABLED = TABS["civitai_browser"]


def on_ui_settings():
    """Register extension settings."""
    section = ("model_manager", EXTENSION_NAME)
    carry_over_page_sizes(shared.opts.data)

    # Each tab's switch, first, in the order of the tabs (tabs.py, #185).
    shared.opts.add_option(
        QUEUE_ENABLED,
        shared.OptionInfo(
            default=DEFAULTS[QUEUE_ENABLED],
            label="Queue",
            component=gr.Checkbox,
            onchange=_queue_enabled_changed,
            section=section,
        ).info("On: a Queue button beside Generate, in txt2img and img2img, keeps the "
               "generation as a task, and the Queue tab runs the tasks. Off: the tab and the "
               "buttons are hidden at once, and a running queue stops; from the next start "
               "neither is created at all. The tasks are kept, and come back when this is on "
               "again.")
    )

    shared.opts.add_option(
        RECORD_GENERATIONS,
        shared.OptionInfo(
            default=DEFAULTS[RECORD_GENERATIONS],
            label="Generations",
            component=gr.Checkbox,
            section=section,
        ).info("On: every txt2img and img2img result saved to disk is recorded with all its "
               "settings, and shown in the Generations tab and the gallery of each model it "
               "used. Off: nothing is recorded, and the Generations tab and each model's Your "
               "generations are hidden at once; from the next start the Generations tab is not "
               "created at all. What was recorded is kept, and comes back when this is on again.")
    )

    shared.opts.add_option(
        GALLERY_ENABLED,
        shared.OptionInfo(
            default=DEFAULTS[GALLERY_ENABLED],
            label="Civitai Images tab",
            component=gr.Checkbox,
            section=section,
        ).info("On: the Civitai Images tab - the Civitai images stored for the models in your library, "
               "in an order its seed picks. Off: the tab is hidden at once and stops, and from "
               "the next start it is not created at all.")
    )

    shared.opts.add_option(
        MODEL_MANAGER_ENABLED,
        shared.OptionInfo(
            default=DEFAULTS[MODEL_MANAGER_ENABLED],
            label="Model Manager tab",
            component=gr.Checkbox,
            section=section,
        ).info("On: the Model Manager tab - your models, their details and galleries, and the "
               "sync with Civitai. Off: the tab is hidden at once and stops, and from the next "
               "start it is not created at all; a sync already running finishes. Your library "
               "is kept, and downloads still add to it.")
    )

    shared.opts.add_option(
        CIVITAI_BROWSER_ENABLED,
        shared.OptionInfo(
            default=DEFAULTS[CIVITAI_BROWSER_ENABLED],
            label="Civitai Browser tab",
            component=gr.Checkbox,
            section=section,
        ).info("On: the Civitai Browser tab - searching Civitai, and downloading from it. Off: "
               "the tab is hidden at once and stops, and from the next start it is not created "
               "at all; downloads already running finish.")
    )

    shared.opts.add_option(
        "model_manager_civitai_api_key",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_civitai_api_key"],
            label="Civitai API Key",
            component=gr.Textbox,
            component_args={"type": "password"},
            section=section,
        ).info("Optional. Provides higher rate limits for Civitai API requests.")
    )

    shared.opts.add_option(
        "model_manager_page_size",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_page_size"],
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
    _page_size_option(MM_IMAGES_SETTING, "Model Manager: Civitai images per page",
                      "How many images Load More adds in a model's Civitai images in the Model Manager - "
                      "counted before the NSFW and prompt switches.", section)
    _page_size_option(GENERATIONS_SETTING, "Your generations: generations per page",
                      "How many generations Load More adds in a model's Your generations. Not used by the "
                      "Generations tab: it loads as you scroll.", section)

    shared.opts.add_option(
        "model_manager_database_path",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_database_path"],
            label="Custom Database Path",
            component=gr.Textbox,
            component_args={"placeholder": "e.g., F:\\shared\\models.db"},
            section=section,
        ).info("Full path to database file (including filename). Leave empty to use default location in extension folder. Requires restart to take effect.")
    )

    shared.opts.add_option(
        "model_manager_preview_least_nsfw",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_preview_least_nsfw"],
            label="Model Manager: card thumbnail is the least explicit image",
            component=gr.Checkbox,
            section=section,
        ).info("If enabled, each card shows the model's least explicit image. If disabled, "
               "its most recent one. Whether galleries hide explicit images is a setting "
               "of its own: Shared: hide explicit images by default.")
    )

    # This one setting used to decide the gallery as well, so whoever turned
    # it off for newer thumbnails also got explicit images in every gallery.
    # Split, the gallery starts from what the old setting said - once: after
    # that the value is saved with the rest, and the two are independent.
    carried = carry_over_gallery_nsfw(shared.opts.data)
    shared.opts.add_option(
        GALLERY_HIDE_NSFW,
        shared.OptionInfo(
            default=DEFAULTS[GALLERY_HIDE_NSFW],
            label="Shared: hide explicit images by default",
            component=gr.Checkbox,
            section=section,
        ).info("How Civitai's images open: a model's image gallery, in the Model Manager and "
               "the Civitai Browser, and the Civitai Images tab - and a model's Your "
               "generations; the Generations tab has its own. The Show NSFW switch above "
               "the images shows them there. "
               "The Civitai Browser's Include NSFW models decides which models are listed, "
               "not which of their images are shown.")
    )
    if carried is not None:
        shared.opts.data[GALLERY_HIDE_NSFW] = carried

    # Civitai Browser settings
    shared.opts.add_option(
        "model_manager_civitai_page_size",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_civitai_page_size"],
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
    _page_size_option(CB_IMAGES_SETTING, "Civitai Browser: images per page",
                      "How many images Load More adds in a model's images in the Civitai Browser, fetched from "
                      "Civitai - counted before the NSFW and prompt switches.", section)

    shared.opts.add_option(
        "model_manager_hide_promptless_images",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_hide_promptless_images"],
            label="Model galleries: hide images with no prompt by default",
            component=gr.Checkbox,
            section=section,
        ).info("About a tenth of Civitai's images carry no prompt at all, and "
               "they cannot be read or reused. Can be turned back on per model "
               "from the panel above the images. Model galleries only, in the Model Manager "
               "and the Civitai Browser: the Civitai Images tab shows every image.")
    )

    shared.opts.add_option(
        "model_manager_gallery_originals",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_gallery_originals"],
            label="Galleries and Civitai Images: load as uploaded, not resized",
            component=gr.Checkbox,
            section=section,
        ).info("Civitai's image server sends a copy the size it is drawn; this asks for the upload instead. Measured on 20 images: a card's copy 54 KB on average, the upload 3.6 MB - 66 times as much. But a copy is usually slower the first time a gallery is opened: Civitai seldom has it ready (1 image in 34, against 15 in 33 uploads, in one test) and takes about half a second to make each. Videos load as copies whatever this says: an upload can be a GIF that cannot play. The image viewer shows the upload either way. For model galleries and the Civitai Images tab.")
    )

    shared.opts.add_option(
        "model_manager_card_originals",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_card_originals"],
            label="Model cards: load as uploaded, not resized",
            component=gr.Checkbox,
            section=section,
        ).info("Civitai's image server sends a copy the size it is drawn; this asks for the upload instead. Measured on 20 images: a card's copy 54 KB on average, the upload 3.6 MB - 66 times as much. But a copy is usually slower the first time a gallery is opened: Civitai seldom has it ready (1 image in 34, against 15 in 33 uploads, in one test) and takes about half a second to make each. Videos load as copies whatever this says: an upload can be a GIF that cannot play. For the cards of both tabs' grids.")
    )
    shared.opts.add_option(
        "model_manager_card_videos_play",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_card_videos_play"],
            label="Model cards: play videos",
            component=gr.Checkbox,
            section=section,
        ).info("On, a model card whose cover is a video plays it. Off, the card shows the video's still, with a "
               "play button in its corner; the video loads only when pressed. Galleries and the viewer are not "
               "changed.")
    )


    # The Generations tab followed the image gallery's setting; it starts from
    # what that said - once - and the two are independent after.
    carried_generations = carry_over_generations_nsfw(shared.opts.data)
    shared.opts.add_option(
        GENERATIONS_HIDE_NSFW,
        shared.OptionInfo(
            default=DEFAULTS[GENERATIONS_HIDE_NSFW],
            label="Generations: hide explicit images by default",
            component=gr.Checkbox,
            section=section,
        ).info("How the Generations tab opens. The Show NSFW switch above the images shows "
               "them until the tab is opened again. A model's Your generations, in the Model "
               "Manager, follows Shared: hide explicit images by default.")
    )
    if carried_generations is not None:
        shared.opts.data[GENERATIONS_HIDE_NSFW] = carried_generations

    shared.opts.add_option(
        GENERATIONS_DELETE_FILES,
        shared.OptionInfo(
            default=DEFAULTS[GENERATIONS_DELETE_FILES],
            label="Generations: deleting also deletes the image files, by default",
            component=gr.Checkbox,
            section=section,
        ).info("Ticks the box in the delete question. It can still be unticked for one delete.")
    )

    # How each tab places its grid (#240): Fast, the tab's own, or Classic.
    grid_info = ("Fast draws only the rows near the view, and stays smooth at 75,000 images. "
                 "Classic puts every tile on the page. The browser's find then sees them all, "
                 "but a grid of thousands freezes for seconds.")
    shared.opts.add_option(
        GENERATIONS_GRID,
        shared.OptionInfo(
            default=DEFAULTS[GENERATIONS_GRID],
            label="Generations: grid",
            component=gr.Dropdown,
            component_args={"choices": list(GRID_CHOICES)},
            section=section,
        ).info(grid_info)
    )

    # How the Generations tab reads a level's images (#259): Single pass,
    # once per request, or Classic, again for each read.
    shared.opts.add_option(
        READING_SETTING,
        shared.OptionInfo(
            default=DEFAULTS[READING_SETTING],
            label="Generations: how tiles are read (alpha)",
            component=gr.Dropdown,
            component_args={"choices": list(READING_CHOICES)},
            section=section,
        ).info("How the Generations tab reads your images for each set of tiles. Single pass reads them "
               "once, into a temporary table in memory, and builds every tile from it: grouped by base "
               "model, 75,684 images took 0.28 s instead of 1.47. Classic reads them again for each "
               "tile's previews, checkpoint and LoRAs, as before. Single pass is new: if tiles look "
               "wrong or a level does not load, choose Classic and report it.")
    )

    # Sync images (#233): what its dialog starts from. The two folder lists
    # are the dialog's to change - a folder typed here as text breaks too
    # easily - so they are kept out of every settings page: Forge skips a
    # setting whose section starts with None.
    shared.opts.add_option(
        LEVEL_SETTING,
        shared.OptionInfo(
            default=DEFAULTS[LEVEL_SETTING],
            label="Sync images: default NSFW level for images without infotext",
            component=gr.Dropdown,
            component_args={"choices": [LEVEL_TO_NAME[level] for level in (*USER_LEVELS, UNKNOWN)]},
            section=section,
        ).info("What the Sync images dialog starts from. The level picked there is given to "
               "the images without infotext that sync brings, and kept with them. A rating you "
               "give an image wins.")
    )
    shared.opts.add_option(
        GROUP_SETTING,
        shared.OptionInfo(
            default=DEFAULTS[GROUP_SETTING],
            label="Sync images: group images without infotext with similar file names into one batch",
            component=gr.Checkbox,
            section=section,
        ).info("What the Sync images dialog starts from. Images in one folder whose file names "
               "say the same settings, saved close together, become one batch, as one press of "
               "Generate made them.")
    )
    # Thumbnails (#5): on, in a folder, unless turned off. Sync images'
    # dialog shows and saves the first three too.
    shared.opts.add_option(
        thumbnails.ENABLED_SETTING,
        shared.OptionInfo(
            default=DEFAULTS[thumbnails.ENABLED_SETTING],
            label="Generations: make thumbnails",
            component=gr.Checkbox,
            section=section,
        ).info("Ticks \"Make thumbnails\" in the Sync images dialog, and makes one for each image "
               "you generate. A sync with it ticked makes one for every image without one. Tiles "
               "then load a small copy, 450 pixels tall, instead of the full file; the viewer still "
               "shows the full file. An image without one shows its full file.")
    )
    shared.opts.add_option(
        thumbnails.PLACE_SETTING,
        shared.OptionInfo(
            default=DEFAULTS[thumbnails.PLACE_SETTING],
            label="Generations: where thumbnails are kept",
            component=gr.Radio,
            component_args={"choices": list(thumbnails.PLACES)},
            section=section,
        ).info("In a folder: the folder below. Beside each image: in a .thumbnails folder next to "
               "it, which Sync images skips. A change applies to thumbnails made from then on; "
               "those made before keep working where they are.")
    )
    shared.opts.add_option(
        thumbnails.FOLDER_SETTING,
        shared.OptionInfo(
            default=DEFAULTS[thumbnails.FOLDER_SETTING],
            label="Generations: thumbnail folder",
            component=gr.Textbox,
            component_args={"placeholder": "Empty: a thumbnails folder beside the database"},
            section=section,
        ).info("Its full path. Empty: a folder named thumbnails beside the database, which two "
               "WebUIs sharing the database share too. Deleting it is safe: a sync makes them again.")
    )
    shared.opts.add_option(
        thumbnails.THREADS_SETTING,
        shared.OptionInfo(
            default=DEFAULTS[thumbnails.THREADS_SETTING],
            label="Generations: thumbnails made at once",
            component=gr.Slider,
            component_args={"minimum": 0, "maximum": 64, "step": 1},
            section=section,
        ).info("0: as many as the machine has processors - making one is mostly processor work. "
               "Lower it for a hard disk or a network drive, or to keep the machine free while "
               "a sync makes them.")
    )
    hidden = (None, "Model Manager")
    for key in (FOLDERS_SETTING, FOLDERS_OFF_SETTING):
        shared.opts.add_option(key, shared.OptionInfo(default=DEFAULTS[key], label=key, section=hidden))

    shared.opts.add_option(
        GALLERY_GRID,
        shared.OptionInfo(
            default=DEFAULTS[GALLERY_GRID],
            label="Civitai Images: grid",
            component=gr.Dropdown,
            component_args={"choices": list(GRID_CHOICES)},
            section=section,
        ).info(grid_info)
    )

    shared.opts.add_option(
        "model_manager_civitai_folder_template",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_civitai_folder_template"],
            label="Civitai Browser: Download folder template",
            component=gr.Textbox,
            component_args={"placeholder": "_{baseModel}/{modelName}"},
            section=section,
        ).info("Subfolder template for downloads. Placeholders: {baseModel}, {modelName}, {creator}, {modelId}")
    )

    shared.opts.add_option(
        "model_manager_civitai_requests_per_second",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_civitai_requests_per_second"],
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

    # The same top as Requests per second (#279); changed, the queue follows
    # at once (_downloads_at_once_changed).
    shared.opts.add_option(
        "model_manager_downloads_at_once",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_downloads_at_once"],
            label="Downloads: how many at once",
            component=gr.Slider,
            component_args={
                "minimum": 1,
                "maximum": 10,
                "step": 1,
            },
            onchange=_downloads_at_once_changed,
            section=section,
        ).info("How many downloads run at the same time; the rest wait their turn in the queue. "
               "A fast connection may want more; a hard disk, a network drive or a slow connection "
               "may want 1. Start now still starts a waiting download over this number. Applies at once: "
               "a lower number lets the running downloads finish, and starts no new one until fewer run.")
    )

    # A box with no maximum, so the settings window draws no slider (#213).
    shared.opts.add_option(
        "model_manager_civitai_images_at_once",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_civitai_images_at_once"],
            label="Civitai: images loading at once, at most",
            component=gr.Number,
            component_args={"minimum": 1, "step": 1, "precision": 0},
            section=section,
        ).info("How many of Civitai's images the galleries load at once; the rest wait "
               "until one has loaded, nearest the screen first. Civitai makes resized copies at about "
               "10 to 16 a second and queues the rest, and images asked for hundreds at once failed "
               "to load. Not a page size: a page still holds as many images as its tab's setting says.")
    )

    shared.opts.add_option(
        "model_manager_hash_threads",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_hash_threads"],
            label="Sync: Hashing threads",
            component=gr.Slider,
            component_args={
                "minimum": 1,
                "maximum": 16,
                "step": 1,
            },
            section=section,
        ).info("How many model files to hash at once when a sync identifies them. "
               "Each file is read in full, so the drive usually sets the pace. "
               "Hard disk or network drive: 1-2 - more make it slower. "
               "SATA SSD: 2-4. NVMe: 4-8, or more on a CPU with many cores. "
               "Lower it if a sync makes the machine slow.")
    )
    _page_size_option(SYNC_IMAGES_SETTING, "Sync: images kept per version",
                      "How many of each version's Civitai images a sync fetches and keeps - from the sync dialog, "
                      "a model's Sync, a download. The dialog's \"First N images\" is this number. A model's NSFW "
                      "level counts its worst stored image, and the Civitai Images tab shows stored images only: "
                      "fewer kept, less to judge and show.", section)

    shared.opts.add_option(
        "model_manager_civitai_min_prompt_images",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_civitai_min_prompt_images"],
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
            default=DEFAULTS["model_manager_civitai_sfw_fill_page"],
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
            default=DEFAULTS["model_manager_card_size"],
            label="Model Manager: Card size (WIDTHxHEIGHT)",
            component=gr.Textbox,
            component_args={"placeholder": "200x280"},
            section=section,
        ).info("Size of model cards in Model Manager. Format: WIDTHxHEIGHT in pixels.")
    )

    shared.opts.add_option(
        "model_manager_civitai_card_size",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_civitai_card_size"],
            label="Civitai Browser: Card size (WIDTHxHEIGHT)",
            component=gr.Textbox,
            component_args={"placeholder": "200x280"},
            section=section,
        ).info("Size of model cards in Civitai Browser. Format: WIDTHxHEIGHT in pixels.")
    )

    shared.opts.add_option(
        "model_manager_nsfw_prompt_words",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_nsfw_prompt_words"],
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
            default=DEFAULTS["model_manager_nsfw_detection"],
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
            default=DEFAULTS["model_manager_nsfw_prompt_model_percent"],
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

    shared.opts.add_option(
        CHECK_UPDATES,
        shared.OptionInfo(
            default=DEFAULTS[CHECK_UPDATES],
            label="Check for a new version",
            component=gr.Checkbox,
            onchange=_check_updates_changed,
            section=section,
        ).info("On: after the WebUI starts, and every 12 hours, the extension reads the "
               "version.json file on its GitHub repository - the version it holds, nothing "
               "else - and each tab's header says when a newer one is out. Off: GitHub is "
               "never asked.")
    )


    shared.opts.add_option(
        "model_manager_queue_inputs_dir",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_queue_inputs_dir"],
            label="Queue: folder for the images a task needs",
            component=gr.Textbox,
            component_args={"placeholder": "e.g., D:\\queue-inputs"},
            section=section,
        ).info("A queued task keeps the images it was given here - an img2img source "
               "and mask, ControlNet's images - until it is deleted, one folder per task. "
               "Empty: queue-inputs in the WebUI's folder, "
               "beside outputs. Tasks keep their files' full paths, so a change applies to "
               "tasks queued after it.")
    )

    shared.opts.add_option(
        "model_manager_queue_ask_above",
        shared.OptionInfo(
            default=DEFAULTS["model_manager_queue_ask_above"],
            label="Queue: ask \"Generate N images?\" above this many images",
            component=gr.Slider,
            component_args={"minimum": 0, "maximum": 100, "step": 1},
            section=section,
        ).info("Batch count times batch size. Above it, Generate asks whether to generate, "
               "queue it instead, or cancel; the question can be turned off in each browser. "
               "0: Generate never asks.")
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
                default=DEFAULTS[SETTING_PREFIX + preset],
                label=f"Send to txt2img: {label} text encoders and VAE",
                component=gr.Textbox,
                component_args={"placeholder": _module_example(preset)},
                section=section,
            ).info(_module_help(preset, note))
        )


GALLERY_HIDE_NSFW = "model_manager_gallery_hide_nsfw"



def _page_size_option(key, label, info, section):
    """A page size or a sync's count (#230): a slider, as every one of them is."""
    shared.opts.add_option(key, shared.OptionInfo(
        default=DEFAULTS[key], label=label, component=gr.Slider,
        component_args={"minimum": MIN_PAGE_SIZE, "maximum": MAX_PAGE_SIZE, "step": 5},
        section=section).info(info))


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
