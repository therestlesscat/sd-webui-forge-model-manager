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


_GRID = (("Smooth: only nearby tiles", "Fast"), ("Keep every tile", "Classic"))
_GRID_TEXT = ("Either way, tiles load 100 at a time as you near the end. Smooth, the default, keeps on the page "
              "only the tiles within about 3,000 px of what you see, and draws the others again as you scroll back "
              "to them: scrolling to the end of 75,685 images never froze for more than 50 ms. Keep every tile "
              "leaves all the tiles loaded so far on the page, so the browser's Find (Ctrl+F) can search them all, "
              "but the page gets slower the further you scroll: at the end of 75,684 images it froze for up to 42 "
              "seconds at a time.")
_PAGE = {"minimum": MIN_PAGE_SIZE, "maximum": MAX_PAGE_SIZE, "step": 5}
_ORIGINALS = ("Uploads are much larger: on 20 images, a card-sized copy was 54 KB on average and the upload 3.6 MB, "
              "66 times as much. Even so, a copy is often slower the first time, because Civitai seldom has it "
              "ready: in one test it had 1 copy in 34, against 15 uploads in 33, and took about half a second to "
              "make each copy. Videos always load as copies, because an upload can be a GIF that cannot play.")

SETTINGS: Tuple[Setting, ...] = (
    # ------------------------------------------------------------- Tabs
    Setting("model_manager_queue_enabled", "tabs", "checkbox", "Queue Tab",
            "Show the Queue Tab and its button beside Generate",
            "When on, a Queue button appears beside Generate in txt2img and img2img. It saves the generation as a "
            "task instead of running it, and the Queue tab runs the saved tasks. When off, the tab and the buttons "
            "disappear at once and a running queue stops; from the next start of the WebUI they are not created at "
            "all. Your saved tasks are kept, and come back when you turn this on again.",
            (Q,), needs=()),
    Setting("model_manager_record_generations", "tabs", "checkbox", "Generations Tab",
            "Record your generations and show the Generations Tab",
            "When on, every txt2img and img2img image saved to disk is recorded with all the settings that made it. "
            "Recorded images show in the Generations tab, and in the gallery of each model they used. When off, "
            "nothing new is recorded, and the Generations tab and each model's Your generations disappear at once; "
            "from the next start of the WebUI the Generations tab is not created at all. What was recorded is kept, "
            "and comes back when you turn this on again.",
            (GEN,), needs=()),
    Setting("model_manager_gallery_tab", "tabs", "checkbox", "Civitai Images Tab", "Show the Civitai Images Tab",
            "When on, the Civitai Images tab shows the Civitai images stored for the models in your library, in an "
            "order set by its seed. When off, the tab disappears at once and stops, and from the next start of the "
            "WebUI it is not created at all.",
            (CI,), needs=()),
    Setting("model_manager_model_manager_enabled", "tabs", "checkbox", "Model Manager Tab", "Show the Model Manager Tab",
            "When on, the Model Manager tab shows your models with their details and galleries, and syncs them with "
            "Civitai. When off, the tab disappears at once and stops, and from the next start of the WebUI it is "
            "not created at all. A sync that is already running finishes. Your library is kept, and downloads still "
            "add to it.",
            (MM,), needs=()),
    Setting("model_manager_civitai_browser_enabled", "tabs", "checkbox", "Civitai Browser Tab",
            "Show the Civitai Browser Tab",
            "When on, the Civitai Browser tab lets you search Civitai and download from it. When off, the tab "
            "disappears at once and stops, and from the next start of the WebUI it is not created at all. Downloads "
            "that are already running finish.",
            (CB,), needs=()),

    # -------------------------------------------------- Civitai account
    Setting("model_manager_civitai_api_key", "civitai_account", "password", "Civitai API key", "Civitai API key",
            "Optional. With your Civitai API key, Civitai allows more requests to its API before it starts turning "
            "them away.",
            (MM, CB, SEND), needs=()),
    Setting("model_manager_civitai_requests_per_second", "civitai_account", "slider", "Requests per second",
            "Requests to Civitai per second",
            "How many requests per second the extension sends to Civitai's API while an API key is set. A higher "
            "number is faster, but makes it more likely that Civitai turns requests away. A change applies to the "
            "next search, download or sync; one already running keeps its speed.",
            (MM, CB, SEND), under=("model_manager_civitai_api_key", True), args={"minimum": 1, "maximum": 10, "step": 1},
            needs=()),
    Setting("model_manager_civitai_images_at_once", "civitai_account", "number",
            "How many gallery images load in parallel", "How many gallery images load in parallel",
            "When a model's gallery or the Civitai Images tab shows Civitai's images, your browser fetches each "
            "picture or video from Civitai's image server. This sets how many it fetches at the same time. The "
            "others wait their turn, and those nearest the screen go first. Civitai makes its resized copies at "
            "about 10 to 16 a second and queues the rest; when hundreds were asked for at once, many failed to "
            "load. It does not change how many images a page holds: each tab has its own setting for that.",
            (MM, CB, CI), args={"minimum": 1, "step": 1, "precision": 0}),

    # -------------------------------------------------------- Downloads
    Setting("model_manager_downloads_at_once", "downloads", "slider", "How many downloads in parallel",
            "How many downloads in parallel",
            "How many downloads run at the same time. The others wait their turn in the queue. A fast connection "
            "may want more; a hard disk, a network drive or a slow connection may want 1. Start now still starts a "
            "waiting download, even above this number. A change applies at once: a lower number lets the running "
            "downloads finish, and starts no new one until fewer are running.",
            (MM, CB, SEND), args={"minimum": 1, "maximum": 10, "step": 1}, needs=()),
    Setting("model_manager_download_in_parts", "downloads", "checkbox", "Download large files in parts",
            "Download large files in parts",
            "When on, a large file is downloaded from Civitai over several connections at once, each fetching a "
            "part of it. Civitai's storage limits each connection to about 60 MB/s, so a faster line gets large "
            "files sooner. When off, every file downloads over one connection. A change applies to the next "
            "download, and to a paused one when it resumes.",
            (MM, CB, SEND), needs=()),
    Setting("model_manager_connections_per_file", "downloads", "slider", "Connections per file",
            "Connections per file, for files downloaded in parts",
            "How many connections a large file is downloaded over. Each part is at least 32 MB, so a smaller file "
            "uses fewer connections. A change applies to the next download, and to a paused one when it resumes.",
            (MM, CB, SEND), under=("model_manager_download_in_parts", True),
            args={"minimum": 2, "maximum": 16, "step": 1}, needs=()),
    Setting("model_manager_civitai_folder_template", "downloads", "textbox", "Download folder",
            "Folder a download is filed into",
            "Where a downloaded model is saved, inside the folder Forge uses for its type: Stable-diffusion for "
            "checkpoints, Lora for LoRAs, and so on. Write a path, and add any of these to fill in the model's "
            "details: {baseModel} for its base model, {modelName} for its name, {creator} for its creator's user "
            "name and {modelId} for its Civitai id. A model's details can contain spaces, or characters Windows "
            "does not allow in a folder name, such as : or ?. Each of those becomes an underscore: the base model "
            "SDXL 1.0 becomes the folder SDXL_1.0. The default, _{baseModel}/{modelName}, saves an SDXL LoRA named "
            "My Style in Lora/_SDXL_1.0/My_Style. Leave it empty to save every model straight into its type's "
            "folder.",
            (MM, CB, SEND), args={"placeholder": "_{baseModel}/{modelName}"}, needs=()),

    # -------------------------------------------------- Pages and cards
    Setting("model_manager_card_originals", "pages_and_cards", "checkbox", "Full-size images on model cards",
            "Load model cards' images full size, not resized",
            "When on, model cards load each picture as it was uploaded to Civitai, instead of a copy Civitai's "
            "image server resizes to the card. " + _ORIGINALS + " This applies to the cards in both the Model "
            "Manager and the Civitai Browser.", (MM, CB)),
    Setting("model_manager_card_videos_play", "pages_and_cards", "checkbox", "Play videos on model cards",
            "Play videos on model cards",
            "When on, a model card whose cover is a video plays it. When off, the card shows a still from the video "
            "with a play button in its corner, and the video loads only when you press it. Galleries and the image "
            "viewer are not affected.",
            (MM, CB)),
    Setting("model_manager_combine_lora_kinds", "pages_and_cards", "checkbox", "Combine LoRA kinds",
            "Combine every kind of LoRA into one type",
            "When on, the Type filter lists one entry for every kind of LoRA instead of one entry for each kind, so "
            "a single pick shows them all: a LoCon or a LoKr shows there together with ordinary LoRAs. When off, "
            "each kind has its own entry, as before. Model cards and a model's details still name the exact kind. "
            "This applies to the Type filter in both the Model Manager and the Civitai Browser.",
            (MM, CB)),
    Setting("model_manager_gallery_originals", "pages_and_cards", "checkbox", "Full-size images in galleries",
            "Load gallery images full size, not resized",
            "When on, galleries load each image as it was uploaded to Civitai, instead of a copy Civitai's image "
            "server resizes to fit. " + _ORIGINALS + " The image viewer shows the upload either way. This applies "
            "to model galleries and the Civitai Images tab.", (MM, CB, CI)),
    Setting("model_manager_generations_grid", "pages_and_cards", "dropdown", "Scrolling in long grids",
            "Scrolling in long grids of the Generations Tab",
            "How the Generations tab handles a long grid of tiles as you scroll. " + _GRID_TEXT,
            (GEN,), args={"choices": _GRID}),
    Setting("model_manager_generations_reading", "pages_and_cards", "dropdown", "Read tiles in one pass",
            "Read Generations Tab tiles in one pass, alpha",
            "How the Generations tab reads your images to build its tiles. When on, it reads them once, into a "
            "temporary table in memory, and builds every tile from it: grouped by base model, 75,684 images took "
            "0.28 s instead of 1.47 s. When off, it reads them again for each tile's previews, checkpoint and "
            "LoRAs, as it did before. This is still being tested: if tiles look wrong or a set of tiles does not "
            "load, turn it off and report it.",
            (GEN,), badges=("alpha",), args={"choices": (("One pass", "Single pass"), ("Per tile, as before", "Classic"))},
            switch=("Single pass", "Classic")),
    Setting("model_manager_gallery_grid", "pages_and_cards", "dropdown", "Scrolling in long grids",
            "Scrolling in long grids of the Civitai Images Tab",
            "How the Civitai Images tab handles a long grid of tiles as you scroll. " + _GRID_TEXT,
            (CI,), args={"choices": _GRID}),
    Setting("model_manager_page_size", "pages_and_cards", "slider", "Models per page",
            "Models per page in the Model Manager Tab", "How many models a page of the Model Manager shows.",
            (MM,), args={"minimum": 5, "maximum": 50, "step": 5}),
    Setting("model_manager_mm_images_per_page", "pages_and_cards", "slider", "Civitai images per page",
            "Civitai images per page in a model's gallery",
            "How many images each press of Load More adds to a model's Civitai images. The count includes the "
            "images the NSFW and prompt switches then hide.", (MM,), args=_PAGE),
    Setting("model_manager_mm_generations_per_page", "pages_and_cards", "slider", "Generations per page",
            "Generations per page in a model's Your generations",
            "How many images each press of Load More adds to a model's Your generations. The Generations tab does "
            "not use it, because it loads more as you scroll.", (MM,), args=_PAGE),
    Setting("model_manager_card_size", "pages_and_cards", "textbox", "Card size", "Card size in the Model Manager Tab",
            "The size of the model cards, as width x height in pixels.", (MM,), args={"placeholder": "200x280"}),
    Setting("model_manager_preview_least_nsfw", "pages_and_cards", "checkbox", "Least explicit image as cover",
            "Use a model's least explicit image as its card's cover",
            "When on, each model card shows the model's least explicit image as its cover. When off, it shows the "
            "most recent one. Whether galleries hide explicit images is a separate setting, Hide explicit images by "
            "default.", (MM,)),
    Setting("model_manager_civitai_page_size", "pages_and_cards", "slider", "Models per page",
            "Models per page in the Civitai Browser Tab", "How many models a page of the Civitai Browser shows.",
            (CB,), args={"minimum": 5, "maximum": 50, "step": 5}),
    Setting("model_manager_cb_images_per_page", "pages_and_cards", "slider", "Images per page",
            "Images per page in the Civitai Browser Tab",
            "How many images each press of Load More adds to a model's images in the Civitai Browser, fetched from "
            "Civitai. The count includes the images the NSFW and prompt switches then hide.", (CB,), args=_PAGE),
    Setting("model_manager_civitai_card_size", "pages_and_cards", "textbox", "Card size",
            "Card size in the Civitai Browser Tab", "The size of the model cards, as width x height in pixels.",
            (CB,), args={"placeholder": "200x280"}),

    # --------------------------------------------------- What is hidden
    Setting("model_manager_gallery_hide_nsfw", "hidden", "checkbox", "Hide explicit images by default",
            "Hide explicit images when a gallery opens",
            "Whether explicit images are hidden when a gallery of Civitai's images opens: a model's gallery in the "
            "Model Manager or the Civitai Browser, and the Civitai Images tab. A model's Your generations follows "
            "it too; the Generations tab has its own setting. The Show NSFW switch above the images shows them in "
            "that gallery. The Civitai Browser's Include NSFW models is separate: it decides which models are "
            "listed, not which of their images are shown.", (MM, CB, CI)),
    Setting("model_manager_nsfw_detection", "hidden", "radio", "How to catch explicit images rated PG",
            "How to catch explicit images rated PG",
            "Civitai rates some explicit images PG or PG-13. This chooses how the extension finds them. The trained "
            "model reads each image's prompts and the resources it used, and catches most of them, but it judges by "
            "what it has learned: now and then it flags an image that is fine, or misses one that is not. The word "
            "list treats an image as X only when its prompt uses one of the listed words, so every decision can be "
            "checked. When this changes, your stored images are judged again in the background.",
            (MM, CB, CI, GEN), args={"choices": (("Trained model", "model"), ("Word list", "words"))}),
    Setting("model_manager_nsfw_prompt_model_percent", "hidden", "number", "PG images the model may flag, in %",
            "PG images the model may flag, in %",
            "How readily the trained model flags images. The number is the percentage of PG and PG-13 images the "
            "model may treat as X, measured on the images it was trained on. A higher number catches more explicit "
            "images, and wrongly hides more that are fine; a lower one hides fewer, and misses more. At 2, the "
            "default, it caught about 94 in 100 X and XXX prompts in a library it had never seen, and flagged 2.2% "
            "of that library's PG and PG-13 images. 0 turns the model off, and only the word list is used. When "
            "this changes, your stored images are judged again in the background.",
            (MM, CB, CI, GEN), under=("model_manager_nsfw_detection", "model"),
            args={"minimum": 0, "maximum": 20, "step": 0.25}),
    Setting("model_manager_nsfw_prompt_words", "hidden", "textbox", "Additional words to detect NSFW prompts",
            "Additional words to detect NSFW prompts",
            "Words that mark a prompt as explicit, separated by commas. An image Civitai rates PG or PG-13 whose "
            "prompt uses one of them is treated as X everywhere: hidden from grid previews, galleries and the SFW "
            "filters. Words match whole, in any case. They add to the list that comes with the extension, in "
            "model_manager/data/nsfw_prompt_words.txt. When this changes, your stored images are judged again in "
            "the background.",
            (MM, CB, CI, GEN), args={"placeholder": "comma-separated words", "lines": 2}),
    Setting("model_manager_hide_promptless_images", "hidden", "checkbox", "Hide images with no prompt by default",
            "Hide images with no prompt when a gallery opens",
            "Whether images with no prompt are hidden when a model's gallery opens, in the Model Manager and the "
            "Civitai Browser. About a tenth of Civitai's images carry no prompt at all, so they cannot be read or "
            "made again. You can show them for one model with the switch above its images. The Civitai Images tab "
            "always shows every image.", (MM, CB)),
    Setting("model_manager_generations_hide_nsfw", "hidden", "checkbox", "Hide explicit images by default",
            "Hide explicit images when the Generations Tab opens",
            "Whether explicit images are hidden when the Generations tab opens. The Show NSFW switch above the "
            "images shows them until the tab is opened again. A model's Your generations, in the Model Manager, "
            "follows the other Hide explicit images by default, under Shared across tabs.", (GEN,)),
    Setting("model_manager_civitai_min_prompt_images", "hidden", "slider",
            "How many images with a prompt a model needs to count as usable",
            "Images with a prompt a model needs to count as usable",
            "Used by the Civitai Browser's Only with usable prompts filter. A model is listed only if at least this "
            "many of its first 20 images have a usable prompt: a prompt with its steps, sampler and CFG scale.",
            (CB,), args={"minimum": 1, "maximum": 20, "step": 1}),
    Setting("model_manager_civitai_sfw_fill_page", "hidden", "checkbox",
            "Fill each page with models when hiding NSFW models", "Fill each page with models when hiding NSFW models",
            "Used when Only Show Models with SFW images is ticked in the Civitai Browser. Normally a page stops "
            "after checking a few dozen models, and can come back with fewer than a full page. When this is on, it "
            "keeps searching until the page is full. Most Civitai models have NSFW images, so one page can take "
            "hundreds of requests and several minutes, and Civitai is likely to start turning requests away. A page "
            "still stops when Civitai does.",
            (CB,), badges=("not_recommended",)),
    Setting("model_manager_civitai_on_site_marks", "hidden", "checkbox", "Mark on-site-only versions",
            "Mark versions Civitai allows only on its site",
            "Some creators allow a version only for generating on Civitai's site, and Civitai refuses to download "
            "it. When this is on, the Civitai Browser marks those versions on its cards and in a model's panel. To "
            "know them, it asks Civitai once per page and once per model you open; the answer is often under a "
            "megabyte, sometimes a few. The Model Manager marks them whatever this says, from what a sync stored.",
            (CB,)),

    # -------------------------------------------------------------- Send
    Setting("model_manager_send_clip_skip", "send", "checkbox", "Use the image's Clip skip",
            "Send uses the image's Clip skip",
            "When on, and an image was made with a clip skip other than your Clip Skip setting, Send adds the "
            "image's value to the tab's Override settings and says so, so the image can be made again as it was. It "
            "applies to the images you generate while it is there; your own setting does not change, and the next "
            "Send replaces it. Flux images are left alone, because clip skip changes nothing there. When off, clip "
            "skip is left to Forge's own paste, which Forge Neo ignores.", (SEND,)),
    Setting("model_manager_send_clip_skip_max", "send", "slider", "Highest Clip skip",
            "Highest Clip skip Send takes from an image",
            "When an image's clip skip is above this number, Send leaves it out of Override settings, your own Clip "
            "Skip applies, and Send's notice says so. Most models are made for 1 or 2.",
            (SEND,), under=("model_manager_send_clip_skip", True), args={"minimum": 1, "maximum": 12, "step": 1}),

    # ------------------------------------------------------- Generations
    Setting("model_manager_generations_delete_files", "your_generations", "checkbox",
            "Delete files by default when deleting generations", "Delete files by default when deleting generations",
            "Whether the box \"also delete the image files\" starts ticked when you delete generations. You can "
            "still untick it for one delete.", (GEN, MM), needs=(GEN,)),
    Setting("model_manager_generations_keep_inputs", "your_generations", "checkbox",
            "Keep img2img source images and masks", "Keep img2img source images and masks",
            "When on, each img2img generation that is recorded also keeps the picture it started from, and what you "
            "painted over it: the mask, or the strokes. Send can then put them back in img2img, and the image "
            "viewer shows them. Each picture is kept once, however many generations started from it, and deleted "
            "with the last of them. When off, nothing more is kept; what was kept before stays.", (GEN, SEND)),
    Setting("model_manager_image_sync_level", "your_generations", "dropdown", "NSFW level for images without infotext",
            "NSFW level Sync images gives images without infotext",
            "The level the Sync images dialog has picked when it opens; the dialog saves the level you pick there "
            "for next time. Sync images gives that level to each image it adds that has no infotext, so the image "
            "is hidden or shown like any other at that level. A rating you give an image later always wins.",
            (GEN,), args={"choices": ("PG", "PG-13", "R", "X", "XXX", "Unknown")}),
    Setting("model_manager_group_no_text", "your_generations", "checkbox", "Group images without infotext by name",
            "Sync images groups images without infotext by file name",
            "Whether the Sync images dialog starts with this ticked; the dialog saves your choice for next time. "
            "When ticked, images without infotext are put together into batches, as if one press of Generate made "
            "them, when they sit in the same folder, their file names show the same settings with running numbers "
            "in order, and they were saved close together in time.", (GEN,)),

    # -------------------------------------------------- Files and folders
    Setting("model_manager_database_path", "files", "textbox", "Database file", "Database file, needs a restart",
            "The full path of the database file, with its name. Leave it empty to use the default file, in the "
            "extension's folder. Two WebUIs can share one database file.",
            (Q, GEN, CI, MM, CB), badges=("restart",), args={"placeholder": "e.g., F:\\shared\\models.db"}, needs=()),
    Setting("model_manager_thumbnails", "files", "checkbox", "Make thumbnails by default",
            "Make thumbnails by default",
            "When on, a thumbnail is made for each image you generate, and the Sync images dialog starts with Make "
            "thumbnails ticked; a sync with it ticked makes one for every image that has none. Tiles then load a "
            "small copy, 450 pixels tall, instead of the full file. The image viewer still shows the full file, and "
            "an image without a thumbnail shows its full file.",
            (GEN, MM), needs=(GEN,)),
    Setting("model_manager_thumbnails_place", "files", "radio", "Where thumbnails are kept",
            "Where thumbnails of your generations are kept",
            "In a folder keeps every thumbnail in the Thumbnail folder below. Beside each image keeps each one in a "
            ".thumbnails folder next to its image, which Sync images skips. A change applies to thumbnails made "
            "from then on; those made before keep working where they are.",
            (GEN, MM), under=("model_manager_thumbnails", True), needs=(GEN,),
            args={"choices": ("In a folder", "Beside each image")}),
    Setting("model_manager_thumbnails_folder", "files", "textbox", "Thumbnail folder",
            "Folder for thumbnails, when kept in one",
            "The full path of the folder thumbnails are kept in. Leave it empty to use a folder named thumbnails "
            "beside the database file, which two WebUIs sharing the database share too. It is safe to delete: a "
            "sync makes the thumbnails again.",
            (GEN, MM), under=("model_manager_thumbnails_place", "In a folder"), needs=(GEN,),
            args={"placeholder": "Empty: a thumbnails folder beside the database"}),
    Setting("model_manager_thumbnail_threads", "files", "slider", "How many thumbnails generated in parallel",
            "How many thumbnails generated in parallel",
            "How many thumbnails are made at the same time. 0 uses as many as the machine has processors, because "
            "making a thumbnail is mostly processor work. Use a lower number for a hard disk or a network drive, or "
            "to keep the machine free while a sync makes them.",
            (GEN, MM), under=("model_manager_thumbnails", True), needs=(GEN,),
            args={"minimum": 0, "maximum": 64, "step": 1}),
    Setting("model_manager_queue_inputs_dir", "files", "textbox", "Folder for queued tasks' images",
            "Folder for the images queued tasks need",
            "Where a queued task keeps the images it was given, such as an img2img source and mask or ControlNet's "
            "images, one folder per task, until the task is deleted. Leave it empty to use a folder named "
            "queue-inputs in the WebUI's folder, beside outputs. Tasks keep the full paths of their files, so a "
            "change applies only to tasks queued after it.",
            (Q,), args={"placeholder": "e.g., D:\\queue-inputs"}),
    Setting("model_manager_generations_inputs_dir", "files", "textbox", "Folder for img2img source images",
            "Folder for img2img source images",
            "The full path of the folder where img2img source images and masks are kept. Leave it empty to use a "
            "folder named generation-inputs beside the database file, which two WebUIs sharing the database share "
            "too. Generations keep the full paths of their files, so a change applies only to generations recorded "
            "after it.",
            (GEN, SEND), under=("model_manager_generations_keep_inputs", True),
            args={"placeholder": "Empty: a generation-inputs folder beside the database"}),

    # ---------------------------------------------------- Sync and queue
    Setting("model_manager_queue_ask_above", "sync_and_queue", "slider", "Ask before generating more images than",
            "Ask before generating more images than",
            "When you press Generate for more images than this number (batch count times batch size), you are asked "
            "first: generate them now, queue them to run later from the Queue tab, or cancel. The question has a "
            "\"Don't ask again in this browser\" box. 0 means Generate never asks. It asks only while the Queue tab "
            "is on.",
            (Q,), args={"minimum": 0, "maximum": 100, "step": 1}),
    Setting("model_manager_hash_threads", "sync_and_queue", "slider", "Files hashed at once", "Files a sync hashes at once",
            "How many model files a sync hashes at the same time when it identifies them. Each file is read in "
            "full, so the drive usually sets the pace. For a hard disk or a network drive, use 1 or 2, as more "
            "makes it slower; for a SATA SSD, 2 to 4; for an NVMe drive, 4 to 8, or more on a processor with many "
            "cores. Lower it if a sync slows the machine down.",
            (MM,), args={"minimum": 1, "maximum": 16, "step": 1}),
    Setting("model_manager_sync_images_per_version", "sync_and_queue", "slider",
            "Number of images stored per version by default at sync",
            "Number of images stored per version by default at sync",
            "How many of each version's Civitai images a sync fetches and keeps, whether it runs from the sync "
            "dialog, a model's Sync button or a download. The dialog's \"First N images\" uses this number. Keeping "
            "fewer means less to judge and show: a model's NSFW level counts its worst stored image, and the "
            "Civitai Images tab shows stored images only.",
            (MM, CB, SEND), args=_PAGE, needs=()),

    # ----------------------------------------------------------- Updates
    Setting("model_manager_check_updates", "updates", "checkbox", "Check for a new version",
            "Check for a new version of the Model Manager",
            "When on, the extension reads the version.json file in its GitHub repository after the WebUI starts and "
            "every 12 hours. It reads only the version number, and each tab's header says when a newer version is "
            "out. When off, GitHub is never asked.",
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
WINDOW_NAME_MOST = 65
PAGE_NAME_MOST = 60
_PREFIX = re.compile(r"^[^:]{2,40}: ")
# A tab named as "the Generations tab" in a name; a prefix ("Generations:") is caught above.
_BARE_TAB = re.compile(r"\b(Queue|Generations|Civitai Images|Model Manager|Civitai Browser) tab\b")
# Words that are names of their own, capitals and all.
_PROPER = re.compile(r"\b(Queue Tab|Generations Tab|Civitai Images Tab|Model Manager Tab|Civitai Browser Tab|Civitai|"
                     r"Forge|Generate|Send|Clip Skip|Clip skip|API|NSFW|PG-13|PG|SFW|VAE|LoRA|X|Model Manager|"
                     r"Flux\.1|Chroma|Flux\.2|Klein|Lumina|Image|Z-Image|Anima|Wan|Qwen-Image|Krea|ERNIE-Image|"
                     r"PiD|Your generations|Sync images|Hide explicit images by default)\b")


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
