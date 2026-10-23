"""
Every setting of the extension, declared once (#320).

A setting was spelled in five places - Forge's registration, and the
settings window's keys, names, groups and nesting - and they drifted: two
names for one setting in 32 of 45, and a new setting with no group fell
under "Other". Here each has its group, a name for the settings window and
one for Forge's Settings page, its description, the tabs it acts in, the
setting it sits under, and its badges. Forge's page (`ui/settings.py`) and
the window (`api/settings.py`, then `settings.mjs`) are drawn from it, and
`naming_problems` holds every name to the rules.

The keys are Forge's, unchanged, so saved values carry over; defaults stay
in `forge_host.DEFAULTS`.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .gallery import MAX_PAGE_SIZE, MIN_PAGE_SIZE


@dataclass(frozen=True)
class Group:
    id: str
    label: str


# In the window's order. On Forge's page each is a section under the
# "Model Manager" category, which Forge sorts by name.
GROUPS = (
    Group("tabs", "Tabs"),
    Group("civitai_account", "Civitai account"),
    Group("downloads", "Downloads"),
    Group("pages_and_cards", "Pages and cards"),
    Group("hidden", "What is hidden"),
    Group("send", "Send"),
    Group("your_generations", "Generations"),
    Group("files", "Files and folders"),
    Group("sync_and_queue", "Sync and queue"),
    Group("updates", "Updates"),
)
CATEGORY = ("model_manager", "Model Manager")
SECTION_PREFIX = "model_manager_"

# The tabs a setting can act in, by tabs.TABS' ids, in the WebUI's order, and
# how a name says each. Send is no tab: it goes from any of them.
TAB_LABELS = {
    "queue": "Queue Tab",
    "generations": "Generations Tab",
    "gallery": "Civitai Images Tab",
    "model_manager": "Model Manager Tab",
    "civitai_browser": "Civitai Browser Tab",
}
SEND = "send"
TAG_LABELS = {**TAB_LABELS, SEND: "Send"}
SHARED_HEADING = "Shared across tabs"

BADGES = {"alpha": "Alpha", "not_recommended": "Not recommended", "restart": "Needs restart"}

Q, GEN, CI, MM, CB = "queue", "generations", "gallery", "model_manager", "civitai_browser"


@dataclass(frozen=True)
class Setting:
    key: str
    group: str
    control: str                    # checkbox, slider, number, dropdown, radio, textbox, password
    name: str                       # in the settings window
    page_name: str                  # on Forge's Settings page
    description: str
    tags: Tuple[str, ...]           # the tabs it acts in; SEND for any
    under: Optional[Tuple[str, Any]] = None   # (key, value) that turns it on; True for "a key is set"
    badges: Tuple[str, ...] = ()
    args: Dict[str, Any] = field(default_factory=dict)
    # The tabs whose switch has to be on for it to be shown; none: always.
    # Read from the tags where not given.
    needs: Optional[Tuple[str, ...]] = None
    # A choice the window draws as a switch: its (on, off) values.
    switch: Optional[Tuple[Any, Any]] = None

    @property
    def shown_with(self) -> Tuple[str, ...]:
        if self.needs is not None:
            return self.needs
        return tuple(t for t in self.tags if t in TAB_LABELS)

    @property
    def heading(self) -> str:
        """The tab heading it sits under inside its group: the one tab it acts in, else shared."""
        tabs = [t for t in self.tags if t in TAB_LABELS]
        return TAB_LABELS[tabs[0]] if len(tabs) == 1 else SHARED_HEADING


_GRID = (("Only those near the view", "Fast"), ("All of them", "Classic"))
_GRID_TEXT = ("Only those near the view: draws only the rows near what you see, and stays smooth at 75,000 "
              "images. All of them: puts every tile on the page. The browser's find then sees them all, but a "
              "grid of thousands freezes for seconds.")
_PAGE = {"minimum": MIN_PAGE_SIZE, "maximum": MAX_PAGE_SIZE, "step": 5}
_ORIGINALS = ("Civitai's image server sends a copy the size it is drawn; this asks for the upload instead. "
              "Measured on 20 images: a card's copy 54 KB on average, the upload 3.6 MB - 66 times as much. But "
              "a copy is usually slower the first time a gallery is opened: Civitai seldom has it ready (1 image "
              "in 34, against 15 in 33 uploads, in one test) and takes about half a second to make each. Videos "
              "load as copies whatever this says: an upload can be a GIF that cannot play.")

SETTINGS: Tuple[Setting, ...] = (
    # ------------------------------------------------------------- Tabs
    Setting("model_manager_queue_enabled", "tabs", "checkbox", "Queue Tab",
            "Show the Queue Tab and its button beside Generate",
            "On: a Queue button beside Generate, in txt2img and img2img, keeps the generation as a task, and the "
            "Queue tab runs the tasks. Off: the tab and the buttons are hidden at once, and a running queue stops; "
            "from the next start neither is created at all. The tasks are kept, and come back when this is on again.",
            (Q,), needs=()),
    Setting("model_manager_record_generations", "tabs", "checkbox", "Generations Tab",
            "Record your generations and show the Generations Tab",
            "On: every txt2img and img2img result saved to disk is recorded with all its settings, and shown in the "
            "Generations tab and the gallery of each model it used. Off: nothing is recorded, and the Generations tab "
            "and each model's Your generations are hidden at once; from the next start the Generations tab is not "
            "created at all. What was recorded is kept, and comes back when this is on again.",
            (GEN,), needs=()),
    Setting("model_manager_gallery_tab", "tabs", "checkbox", "Civitai Images Tab", "Show the Civitai Images Tab",
            "On: the Civitai Images tab - the Civitai images stored for the models in your library, in an order its "
            "seed picks. Off: the tab is hidden at once and stops, and from the next start it is not created at all.",
            (CI,), needs=()),
    Setting("model_manager_model_manager_enabled", "tabs", "checkbox", "Model Manager Tab", "Show the Model Manager Tab",
            "On: the Model Manager tab - your models, their details and galleries, and the sync with Civitai. Off: the "
            "tab is hidden at once and stops, and from the next start it is not created at all; a sync already running "
            "finishes. Your library is kept, and downloads still add to it.",
            (MM,), needs=()),
    Setting("model_manager_civitai_browser_enabled", "tabs", "checkbox", "Civitai Browser Tab",
            "Show the Civitai Browser Tab",
            "On: the Civitai Browser tab - searching Civitai, and downloading from it. Off: the tab is hidden at once "
            "and stops, and from the next start it is not created at all; downloads already running finish.",
            (CB,), needs=()),

    # -------------------------------------------------- Civitai account
    Setting("model_manager_civitai_api_key", "civitai_account", "password", "API key", "Civitai API key",
            "Optional. Gives higher rate limits for requests to Civitai's API.",
            (MM, CB, SEND), needs=()),
    Setting("model_manager_civitai_requests_per_second", "civitai_account", "slider", "Requests per second",
            "Requests to Civitai per second",
            "How fast to call Civitai's API when an API key is set. Higher is faster but more likely to be rate "
            "limited. Applies to the next search, download or sync; one already running keeps its rate.",
            (MM, CB, SEND), under=("model_manager_civitai_api_key", True), args={"minimum": 1, "maximum": 10, "step": 1},
            needs=()),
    Setting("model_manager_civitai_images_at_once", "civitai_account", "number", "Images loading at once",
            "Civitai images loading at once",
            "How many of Civitai's images the galleries load at once; the rest wait until one has loaded, nearest the "
            "screen first. Civitai makes resized copies at about 10 to 16 a second and queues the rest, and images "
            "asked for hundreds at once failed to load. Not a page size: a page still holds as many images as its "
            "tab's setting says.",
            (MM, CB, CI), args={"minimum": 1, "step": 1, "precision": 0}),

    # -------------------------------------------------------- Downloads
    Setting("model_manager_downloads_at_once", "downloads", "slider", "Downloads at once", "Downloads running at once",
            "How many downloads run at the same time; the rest wait their turn in the queue. A fast connection may "
            "want more; a hard disk, a network drive or a slow connection may want 1. Start now still starts a "
            "waiting download over this number. Applies at once: a lower number lets the running downloads finish, "
            "and starts no new one until fewer run.",
            (MM, CB, SEND), args={"minimum": 1, "maximum": 10, "step": 1}, needs=()),
    Setting("model_manager_download_in_parts", "downloads", "checkbox", "Download large files in parts",
            "Download large files in parts",
            "Fetches a large file from Civitai over several connections at once, each fetching a part of it. "
            "Civitai's storage holds each connection to about 60 MB/s, so a faster line gets large files sooner. Off, "
            "every file downloads over one connection, as before. Applies to the next download, and to a paused one "
            "when it resumes.",
            (MM, CB, SEND), needs=()),
    Setting("model_manager_connections_per_file", "downloads", "slider", "Connections per file",
            "Connections per file, for files downloaded in parts",
            "How many connections a large file is fetched over. A part is at least 32 MB, so smaller files use fewer. "
            "Applies to the next download, and to a paused one when it resumes.",
            (MM, CB, SEND), under=("model_manager_download_in_parts", True),
            args={"minimum": 2, "maximum": 16, "step": 1}, needs=()),
    Setting("model_manager_civitai_folder_template", "downloads", "textbox", "Download folder",
            "Folder a download is filed into",
            "The folder a download is filed into, inside its type's folder. Placeholders: {baseModel}, {modelName}, "
            "{creator}, {modelId}.",
            (MM, CB, SEND), args={"placeholder": "_{baseModel}/{modelName}"}, needs=()),

    # -------------------------------------------------- Pages and cards
    Setting("model_manager_card_originals", "pages_and_cards", "checkbox", "Full-size images on model cards",
            "Load model cards' images full size, not resized",
            _ORIGINALS + " For the cards of both tabs' grids.", (MM, CB)),
    Setting("model_manager_card_videos_play", "pages_and_cards", "checkbox", "Play videos on model cards",
            "Play videos on model cards",
            "On, a model card whose cover is a video plays it. Off, the card shows the video's still, with a play "
            "button in its corner; the video loads only when pressed. Galleries and the viewer are not changed.",
            (MM, CB)),
    Setting("model_manager_gallery_originals", "pages_and_cards", "checkbox", "Full-size images in galleries",
            "Load gallery images full size, not resized",
            _ORIGINALS + " The image viewer shows the upload either way. For model galleries and the Civitai Images "
            "tab.", (MM, CB, CI)),
    Setting("model_manager_generations_grid", "pages_and_cards", "dropdown", "Tiles kept on the page",
            "Tiles the Generations Tab keeps on the page", _GRID_TEXT, (GEN,), args={"choices": _GRID}),
    Setting("model_manager_generations_reading", "pages_and_cards", "dropdown", "Read tiles in one pass",
            "Read Generations Tab tiles in one pass, alpha",
            "How the Generations tab reads your images for each set of tiles. On: reads them once, into a temporary "
            "table in memory, and builds every tile from it - grouped by base model, 75,684 images took 0.28 s "
            "instead of 1.47. Off: reads them again for each tile's previews, checkpoint and LoRAs, as before. If "
            "tiles look wrong or a level does not load, turn it off and report it.",
            (GEN,), badges=("alpha",), args={"choices": (("One pass", "Single pass"), ("Per tile, as before", "Classic"))},
            switch=("Single pass", "Classic")),
    Setting("model_manager_gallery_grid", "pages_and_cards", "dropdown", "Tiles kept on the page",
            "Tiles the Civitai Images Tab keeps on the page", _GRID_TEXT, (CI,), args={"choices": _GRID}),
    Setting("model_manager_page_size", "pages_and_cards", "slider", "Models per page",
            "Models per page in the Model Manager Tab", "How many models a page of the Model Manager shows.",
            (MM,), args={"minimum": 5, "maximum": 50, "step": 5}),
    Setting("model_manager_mm_images_per_page", "pages_and_cards", "slider", "Civitai images per page",
            "Civitai images per page in a model's gallery",
            "How many images Load More adds in a model's Civitai images - counted before the NSFW and prompt "
            "switches.", (MM,), args=_PAGE),
    Setting("model_manager_mm_generations_per_page", "pages_and_cards", "slider", "Generations per page",
            "Generations per page in a model's Your generations",
            "How many generations Load More adds in a model's Your generations. Not used by the Generations tab: it "
            "loads as you scroll.", (MM,), args=_PAGE),
    Setting("model_manager_card_size", "pages_and_cards", "textbox", "Card size", "Card size in the Model Manager Tab",
            "The size of the model cards, as width x height in pixels.", (MM,), args={"placeholder": "200x280"}),
    Setting("model_manager_preview_least_nsfw", "pages_and_cards", "checkbox", "Least explicit image as cover",
            "Use a model's least explicit image as its card's cover",
            "On: each card shows the model's least explicit image. Off: its most recent one. Whether galleries hide "
            "explicit images is a setting of its own: Hide explicit images at first.", (MM,)),
    Setting("model_manager_civitai_page_size", "pages_and_cards", "slider", "Models per page",
            "Models per page in the Civitai Browser Tab", "How many models a page of the Civitai Browser shows.",
            (CB,), args={"minimum": 5, "maximum": 50, "step": 5}),
    Setting("model_manager_cb_images_per_page", "pages_and_cards", "slider", "Images per page",
            "Images per page in the Civitai Browser Tab",
            "How many images Load More adds in a model's images, fetched from Civitai - counted before the NSFW and "
            "prompt switches.", (CB,), args=_PAGE),
    Setting("model_manager_civitai_card_size", "pages_and_cards", "textbox", "Card size",
            "Card size in the Civitai Browser Tab", "The size of the model cards, as width x height in pixels.",
            (CB,), args={"placeholder": "200x280"}),

    # --------------------------------------------------- What is hidden
    Setting("model_manager_gallery_hide_nsfw", "hidden", "checkbox", "Hide explicit images at first",
            "Hide explicit images when a gallery opens",
            "How Civitai's images open: a model's image gallery, in the Model Manager and the Civitai Browser, and the "
            "Civitai Images tab - and a model's Your generations; the Generations tab has its own. The Show NSFW switch "
            "above the images shows them there. The Civitai Browser's Include NSFW models decides which models are "
            "listed, not which of their images are shown.", (MM, CB, CI)),
    Setting("model_manager_nsfw_detection", "hidden", "radio", "Find explicit PG images with",
            "How to find explicit images Civitai rated PG or PG-13",
            "The trained model reads each image's prompts and the resources it used, and catches most of the explicit "
            "images Civitai under-rates - but it judges by what it learned, and sometimes raises an image that is fine "
            "or misses one that is not. The word list treats an image as X only when its prompt uses one of the words: "
            "nothing else, and nothing you cannot check. Stored images are judged again in the background when this "
            "changes.", (MM, CB, CI, GEN), args={"choices": (("Trained model", "model"), ("Word list", "words"))}),
    Setting("model_manager_nsfw_prompt_model_percent", "hidden", "number", "Share treated as X",
            "Share of PG and PG-13 prompts the trained model treats as X",
            "Civitai rates some explicit images PG or PG-13. A model trained on image prompts - their words, word "
            "pairs, negative, ADetailer and hires prompts, and the resources used - finds them, and this is how far it "
            "goes: the share of PG and PG-13 prompts it may treat as X, in percent. 2 (default) caught about 94% of "
            "X/XXX prompts on a library it had never seen. 1 is stricter, 3 or more catches more at more cost. 0 turns "
            "the model off, leaving only the words. Stored images are judged again in the background when this changes.",
            (MM, CB, CI, GEN), under=("model_manager_nsfw_detection", "model"),
            args={"minimum": 0, "maximum": 20, "step": 0.25}),
    Setting("model_manager_nsfw_prompt_words", "hidden", "textbox", "Extra NSFW words",
            "Extra words that mark a prompt explicit",
            "An image Civitai rates PG or PG-13 whose prompt uses one of these words is treated as X everywhere - "
            "hidden from the grid previews, the galleries and the SFW filters. Whole words, any case. These add to the "
            "list that comes with the extension, in model_manager/data/nsfw_prompt_words.txt. Stored images are judged "
            "again in the background when this changes.",
            (MM, CB, CI, GEN), args={"placeholder": "comma-separated words", "lines": 2}),
    Setting("model_manager_hide_promptless_images", "hidden", "checkbox", "Hide images with no prompt at first",
            "Hide images with no prompt when a gallery opens",
            "About a tenth of Civitai's images carry no prompt at all, and they cannot be read or reused. Can be turned "
            "back on per model from the panel above the images. Model galleries only, in the Model Manager and the "
            "Civitai Browser: the Civitai Images tab shows every image.", (MM, CB)),
    Setting("model_manager_generations_hide_nsfw", "hidden", "checkbox", "Hide explicit images at first",
            "Hide explicit images when the Generations Tab opens",
            "How the Generations tab opens. The Show NSFW switch above the images shows them until the tab is opened "
            "again. A model's Your generations, in the Model Manager, follows the other Hide explicit images at first, "
            "in Shared across tabs.", (GEN,)),
    Setting("model_manager_civitai_min_prompt_images", "hidden", "slider", "Images with a prompt a model needs",
            "Images with a usable prompt a model needs to be shown",
            "For the Only with usable prompts filter: a model must have at least this many images, of its first 20, "
            "carrying a prompt and its steps, sampler and CFG.", (CB,), args={"minimum": 1, "maximum": 20, "step": 1}),
    Setting("model_manager_civitai_sfw_fill_page", "hidden", "checkbox", "Fill pages while hiding NSFW models",
            "Fill each page while only SFW models show, not recommended",
            "Normally a page with Only Show Models with SFW images stops after checking a few dozen models and can "
            "come back short. With this on, it keeps searching until the page holds the full Models per page. Most "
            "Civitai models have NSFW images, so one page can take hundreds of requests and several minutes, and makes "
            "Civitai's rate limit likely. A page still stops if Civitai starts refusing requests.",
            (CB,), badges=("not_recommended",)),
    Setting("model_manager_civitai_on_site_marks", "hidden", "checkbox", "Mark on-site-only versions",
            "Mark versions Civitai allows only on its site",
            "Marks the versions whose creator allows them only for generating on Civitai - Civitai refuses their "
            "download - on the cards and in a model's panel. Asks Civitai once per page and once per model opened; its "
            "answer is often under a megabyte, and can be a few. The Model Manager marks them whatever this says, from "
            "what a sync stored.", (CB,)),

    # -------------------------------------------------------------- Send
    Setting("model_manager_send_clip_skip", "send", "checkbox", "Use the image's Clip skip",
            "Send uses the image's Clip skip",
            "On: where an image gives a clip skip other than your Clip Skip setting, Send adds it to the tab's "
            "Override settings, and says so - so the image can be made again as it was. It applies to the generations "
            "made while it is there; your setting is not changed, and the next Send replaces it. Not for Flux, where "
            "clip skip changes nothing. Off: left to Forge's paste, which in Forge Neo ignores it.", (SEND,)),
    Setting("model_manager_send_clip_skip_max", "send", "slider", "Highest Clip skip",
            "Highest Clip skip Send takes from an image",
            "An image's clip skip above this is left out of Override settings, and your Clip Skip applies; Send's "
            "notice says so. Most models are made for 1 or 2.",
            (SEND,), under=("model_manager_send_clip_skip", True), args={"minimum": 1, "maximum": 12, "step": 1}),

    # ------------------------------------------------------- Generations
    Setting("model_manager_generations_delete_files", "your_generations", "checkbox", "Tick \"also delete the files\"",
            "Tick \"also delete the image files\" when deleting generations",
            "Ticks the box in the delete question. It can still be unticked for one delete.", (GEN, MM), needs=(GEN,)),
    Setting("model_manager_generations_keep_inputs", "your_generations", "checkbox", "Keep img2img start images",
            "Keep the image and mask an img2img generation started from",
            "On: each img2img generation recorded keeps the picture in its mode's canvas and what was painted over it - "
            "the mask, or the strokes - so Send puts them back and the viewer shows them. One file per picture, however "
            "many generations started from it, deleted with the last of them. Off: nothing more is kept; what was kept "
            "stays.", (GEN, SEND)),
    Setting("model_manager_image_sync_level", "your_generations", "dropdown", "NSFW level for images without infotext",
            "NSFW level Sync images gives images without infotext",
            "What the Sync images dialog starts from. The level picked there is given to the images without infotext "
            "that sync brings, and kept with them. A rating you give an image wins.",
            (GEN,), args={"choices": ("PG", "PG-13", "R", "X", "XXX", "Unknown")}),
    Setting("model_manager_group_no_text", "your_generations", "checkbox", "Group images without infotext by name",
            "Sync images groups images without infotext by file name",
            "What the Sync images dialog starts from. Images in one folder whose file names say the same settings, "
            "saved close together, become one batch, as one press of Generate made them.", (GEN,)),

    # -------------------------------------------------- Files and folders
    Setting("model_manager_database_path", "files", "textbox", "Database file", "Database file, needs a restart",
            "Full path to the database file, with its name. Empty: the default, in the extension's folder. Two WebUIs "
            "can share one.",
            (Q, GEN, CI, MM, CB), badges=("restart",), args={"placeholder": "e.g., F:\\shared\\models.db"}, needs=()),
    Setting("model_manager_thumbnails", "files", "checkbox", "Make thumbnails", "Make thumbnails of your generations",
            "Ticks Make thumbnails in the Sync images dialog, and makes one for each image you generate. A sync with it "
            "ticked makes one for every image without one. Tiles then load a small copy, 450 pixels tall, instead of "
            "the full file; the viewer still shows the full file. An image without one shows its full file.",
            (GEN, MM), needs=(GEN,)),
    Setting("model_manager_thumbnails_place", "files", "radio", "Where thumbnails are kept",
            "Where thumbnails of your generations are kept",
            "In a folder: the Thumbnail folder below. Beside each image: in a .thumbnails folder next to it, which Sync "
            "images skips. A change applies to thumbnails made from then on; those made before keep working where they "
            "are.", (GEN, MM), under=("model_manager_thumbnails", True), needs=(GEN,),
            args={"choices": ("In a folder", "Beside each image")}),
    Setting("model_manager_thumbnails_folder", "files", "textbox", "Thumbnail folder",
            "Folder for thumbnails, when kept in one",
            "Its full path. Empty: a folder named thumbnails beside the database, which two WebUIs sharing the database "
            "share too. Deleting it is safe: a sync makes them again.",
            (GEN, MM), under=("model_manager_thumbnails_place", "In a folder"), needs=(GEN,),
            args={"placeholder": "Empty: a thumbnails folder beside the database"}),
    Setting("model_manager_thumbnail_threads", "files", "slider", "Thumbnails made at once", "Thumbnails made at once",
            "0: as many as the machine has processors - making one is mostly processor work. Lower it for a hard disk "
            "or a network drive, or to keep the machine free while a sync makes them.",
            (GEN, MM), under=("model_manager_thumbnails", True), needs=(GEN,),
            args={"minimum": 0, "maximum": 64, "step": 1}),
    Setting("model_manager_queue_inputs_dir", "files", "textbox", "Folder for queued tasks' images",
            "Folder for the images queued tasks need",
            "A queued task keeps the images it was given here - an img2img source and mask, ControlNet's images - until "
            "it is deleted, one folder per task. Empty: queue-inputs in the WebUI's folder, beside outputs. Tasks keep "
            "their files' full paths, so a change applies to tasks queued after it.",
            (Q,), args={"placeholder": "e.g., D:\\queue-inputs"}),
    Setting("model_manager_generations_inputs_dir", "files", "textbox", "Folder for start images",
            "Folder for the images img2img generations started from",
            "Its full path. Empty: a folder named generation-inputs beside the database, which two WebUIs sharing the "
            "database share too. Generations keep their files' full paths, so a change applies to generations recorded "
            "after it.",
            (GEN, SEND), under=("model_manager_generations_keep_inputs", True),
            args={"placeholder": "Empty: a generation-inputs folder beside the database"}),

    # ---------------------------------------------------- Sync and queue
    Setting("model_manager_queue_ask_above", "sync_and_queue", "slider", "Ask before generating more than",
            "Ask before Generate makes more than this many images",
            "Batch count times batch size. Above it, Generate asks whether to generate, queue it instead, or cancel; "
            "the question can be turned off in each browser. 0: Generate never asks.",
            (Q,), args={"minimum": 0, "maximum": 100, "step": 1}),
    Setting("model_manager_hash_threads", "sync_and_queue", "slider", "Files hashed at once", "Files a sync hashes at once",
            "How many model files to hash at once when a sync identifies them. Each file is read in full, so the drive "
            "usually sets the pace. Hard disk or network drive: 1-2 - more make it slower. SATA SSD: 2-4. NVMe: 4-8, or "
            "more on a CPU with many cores. Lower it if a sync makes the machine slow.",
            (MM,), args={"minimum": 1, "maximum": 16, "step": 1}),
    Setting("model_manager_sync_images_per_version", "sync_and_queue", "slider", "Images kept per version",
            "Civitai images a sync keeps per version",
            "How many of each version's Civitai images a sync fetches and keeps - from the sync dialog, a model's Sync, "
            "a download. The dialog's \"First N images\" is this number. A model's NSFW level counts its worst stored "
            "image, and the Civitai Images tab shows stored images only: fewer kept, less to judge and show.",
            (MM, CB, SEND), args=_PAGE, needs=()),

    # ----------------------------------------------------------- Updates
    Setting("model_manager_check_updates", "updates", "checkbox", "Check for a new version",
            "Check for a new version of the Model Manager",
            "On: after the WebUI starts, and every 12 hours, the extension reads the version.json file on its GitHub "
            "repository - the version it holds, nothing else - and each tab's header says when a newer one is out. "
            "Off: GitHub is never asked.",
            (Q, GEN, CI, MM, CB), needs=()),
)


def module_settings() -> Tuple[Setting, ...]:
    """
    Send's text encoders and VAE, one setting per Neo preset (forge_modules).
    Their descriptions, with links, are Forge's page's (ui/settings.py); the
    window draws them as its table.
    """
    from .forge_modules import MODULE_PRESETS, SETTING_PREFIX
    return tuple(Setting(SETTING_PREFIX + preset, "send", "textbox", f"{label} text encoders and VAE",
                         f"Text encoders and VAE Send picks for {label}", "", (SEND,))
                 for preset, label, _ in MODULE_PRESETS)


def all_settings() -> Tuple[Setting, ...]:
    """Every setting, in the window's order: the presets' after Send's own."""
    send_end = max(i for i, s in enumerate(SETTINGS) if s.group == "send") + 1
    return SETTINGS[:send_end] + module_settings() + SETTINGS[send_end:]


def by_key() -> Dict[str, Setting]:
    return {s.key: s for s in all_settings()}


def group_of(setting: Setting) -> Group:
    return next(g for g in GROUPS if g.id == setting.group)


def section(setting: Setting) -> Tuple[str, str]:
    """Its section on Forge's page: one per group."""
    group = group_of(setting)
    return (SECTION_PREFIX + group.id, group.label)


# ------------------------------------------------------------ the naming rules
WINDOW_NAME_MOST = 40
PAGE_NAME_MOST = 60
_PREFIX = re.compile(r"^[^:]{2,40}: ")
# A tab named as "the Generations tab" in a name; a prefix ("Generations:") is caught above.
_BARE_TAB = re.compile(r"\b(Queue|Generations|Civitai Images|Model Manager|Civitai Browser) tab\b")
# Words that are names of their own, capitals and all.
_PROPER = re.compile(r"\b(Queue Tab|Generations Tab|Civitai Images Tab|Model Manager Tab|Civitai Browser Tab|Civitai|"
                     r"Forge|Generate|Send|Clip Skip|Clip skip|API|NSFW|PG-13|PG|SFW|VAE|X|Model Manager|"
                     r"Flux\.1|Chroma|Flux\.2|Klein|Lumina|Image|Z-Image|Anima|Wan|Qwen-Image|Krea|ERNIE-Image|"
                     r"PiD|Your generations|Sync images|Hide explicit images at first)\b")


def naming_problems(setting: Setting) -> List[str]:
    """What breaks the rules in a setting's two names (#320); none, an empty list."""
    problems = []
    for which, name, most in (("window name", setting.name, WINDOW_NAME_MOST),
                              ("page name", setting.page_name, PAGE_NAME_MOST)):
        if _PREFIX.match(name):
            problems.append(f"{which} starts with a prefix: {name!r}")
        if "(" in name or ")" in name:
            problems.append(f"{which} has a parenthesis: {name!r}")
        if len(name) > most:
            problems.append(f"{which} is over {most} characters: {name!r}")
        # Sentence case: past its first word, a capital belongs only to a
        # name of its own (a tab, Civitai, Forge, NSFW...).
        rest = _PROPER.sub("", name)
        words = rest.split()[1:] if rest[:1].isupper() else rest.split()
        title = [w for w in words if w[:1].isupper()]
        if title:
            problems.append(f"{which} is not sentence case ({', '.join(title)}): {name!r}")
        if _BARE_TAB.search(name):
            problems.append(f"{which} names a tab without \"Tab\": {name!r}")
    return problems
