# SD WebUI Forge Model Manager

A model management extension for Stable Diffusion WebUI Forge - both Forge Neo and the
original Forge. It indexes your local models, enriches them with Civitai metadata, keeps
every image you generate, and adds a Civitai browser you can download from without
leaving the WebUI.

Three tabs are added: **Generations**, **Model Manager** and **Civitai Browser**.
Generations can be turned off in the settings, and is then not created at all.

https://github.com/user-attachments/assets/7d7a97c0-7513-42da-a954-bf23b3f74a96

[Watch it in better quality on YouTube](https://youtu.be/HCHe44Yp-QU)

## What's new

**0.68 - Settings named by what they do.** Every setting now has a name that says what it
does, in ten groups by what the settings are for. Inside a group, a setting for one tab sits
under that tab's heading, and one that depends on a switch sits under it, greyed while the
switch is off. Forge's Settings page lists them in the same groups, under Model Manager.
The window lists the groups beside the settings, each with its count; a tab's gear opens on
that tab's settings, Changed lists what differs from its default, the search finds a setting
by any of its words, and a notice that names a setting opens the window at it.

**0.67 - Send, decided in one place.** What Send sets for an image is moving to one place on the
server, starting with Civitai's images. Such an image now goes in at its picture's size when its
data gives another shape, and a Send that changes Forge's UI preset is about half a second quicker.

**0.66 - Send any image into img2img.** An image's ⋯ menu, in the Generations and the Civitai
Images tabs, sends the picture itself into img2img, Sketch, Inpaint, Inpaint sketch or Inpaint
upload, with its settings, ready to inpaint or redraw. A Civitai image comes at full size.

**0.65 - Send an inpaint back as it was.** An img2img generation now keeps the picture it
started from and the mask or strokes painted over it. Send puts both back, on the mode the
generation was made in, and the viewer shows them beside the result. The settings' Generations
section turns it off.

**0.64 - Large downloads, several times faster.** A large file from Civitai now downloads over
several connections at once, each fetching a part of it. Civitai holds each connection to about
60 MB/s, so a fast line gets a checkpoint several times sooner. Download large files in parts, in
the settings' Downloads, turns it off; Connections per file says how many.

**0.63 - Hide the models you already have.** In the Civitai Browser, Hide models in my library,
under Post-processing Options, leaves out every model marked Owned and fills the page from the
rest, so what is new to you is easy to spot. It costs Civitai no request.

**0.62 - Give back the space your database no longer uses.** Updates and deletes leave space
inside the database file, and each update that reshapes it leaves a full copy beside it. Under
Database file in the settings, Compact database gives the space back, and Old backups lists the
copies with the version each holds, to delete the ones you no longer need.

**0.61 - Versions Civitai allows only on its site.** A creator can allow a version only for
generating on Civitai, and Civitai then refuses its download. The Model Manager now marks such a
version - a sign on its pill, and Download saying "On-site only" - from what a sync stores; the
Civitai Browser can mark it on its cards and in a model's panel, with its setting on.

**0.60 - Search Civitai's images.** The Civitai Images tab can be searched by prompt, as the
Generations tab is, and grouped by each image's prompt, its LoRAs or the day it was made - and two
deep, a grouping inside another. Each Civitai image is now stored once, whatever galleries show it.

**0.59 - Download several at once.** In the Civitai Browser, tick Select and click the models you
want, on any page of your search or across I'm feeling lucky's draws, then press Download selected: each one's newest version joins the
downloads queue. Before that, a download asks your library first, so a file you already have - moved
into a subfolder of your own, say - is never fetched again.

**0.58 - Your generations, ready for tens of thousands.** The tables behind the Generations
tab and each model's Your generations are rebuilt for libraries of tens of thousands of images:
the tab asks for one scroll's worth at a time instead of reading every image you ever recorded.
Nothing is lost in the move - every value is checked before the old tables go.

**0.57 - Civitai Images, your library's images from Civitai.** A new tab, Civitai Images, shows the Civitai images stored for every model in your library, laid out as the Generations tab lays out your own, in an order a sorting seed picks - the same seed, the same order; a new one, a new shuffle. Group them by model, base model, type or size. The tab is off until you turn it on in Settings -> Tabs.

**0.56 - Send sets your generation back as it was made.** Send on an image you generated
sets every control back as it was when you pressed Generate - the hires fix's own checkpoint
and VAE, the refiner and its CFG scale, hidden controls included - with that image's own seed
and prompts. A Civitai image's Send gets the hires and refiner checkpoints right too.

**0.55 - Chips for what a prompt names alone.** After a Send, a LoRA named only in a
`<lora:...>` tag, and a library embedding written only as a word, get a chip under the prompt
too, found as Forge would find them. An embedding Forge would skip with the model being sent -
an SD 1.x one under an SDXL checkpoint - says so, instead of showing as ready.

**0.54 - Files your WebUI ignores say so.** Some command-line options replace a model type's
own folder instead of adding to it - `--lora-dir`, `--controlnet-dir`, and in Forge Neo
`--esrgan-models-path`. A file left in the replaced folder is now tagged "Ignored by Neo" or
"Ignored by Forge", with the option that replaced its folder, and is no longer Owned: the
Civitai Browser offers a download your WebUI will load.

**0.53 - I'm feeling lucky shows you something new.** Each Draw leaves out the models the
draws before it showed, under the same filters, and every model already in your library -
so a draw brings models you have not seen. Start over, beside Draw, forgets what was shown;
changing the filters or restarting the WebUI starts afresh too.

**0.52 - The download queue survives a restart.** Downloads waiting in the queue are kept,
as running and paused ones were: after a restart, or a crash, every download not finished
is back in the list, paused, in its place, to be resumed. One you have downloaded
meanwhile - by hand, or in the other WebUI - is not brought back.

**0.51 - Turn off the tabs you do not use.** Each of the extension's tabs - the Queue,
Generations, the Model Manager and the Civitai Browser - has a switch, together in the
settings window's new Tabs section. A tab switched off does nothing at all: it is hidden at
once, its requests are refused, from the next start it is not even loaded, and the buttons
in the other tabs that lead to it are greyed, saying why. Turned back on, it returns at
once, or after a page reload or Reload UI, which a popup offers - with Restart WebUI for
the cleanest slate. Nothing you have is deleted.

**0.50 - A queue for your generations.** Press Queue beside Generate, in txt2img or
img2img, and the generation is kept as a task instead of run: its checkpoint, VAE and text
encoders, its scripts and ControlNet units, and the images it was given. The new Queue tab
runs the tasks one at a time, in the order they were queued, while you go on working - with
the page closed too, and a restart keeps them. A task opens to everything it holds; Load to
UI sets its tab up with it again, and Retry, Delete, Pause and Stop are there. The
Generations tab gains a search, which also shows the images a task made.

**0.48 - Sync reads your model folders.** Every sync starts by reading your model folders,
whichever models it refreshes: files you have added join the library and are looked up on
Civitai, files you have deleted leave it - so Scan Disk is gone. The sync dialog says how
many new files it will read before you start, and can read every file's header again or
move files sitting in another type's folder into their own. A model's details always come
from Civitai; a `.civitai.info` beside a file is read only for a model Civitai no longer has.

**0.47 - Send sets up the gallery's model.** Send to txt2img from a LoRA's, a VAE's or an
embedding's gallery loads the checkpoint the image was made with, where Forge used to keep
whatever it had; one your library lacks opens the image's Resources instead, to download it
there. From a VAE's or a text encoder's gallery, that file is the one selected.

**0.46 - One version, its files under it.** A Civitai version is one version in the
library, however many of its files you have - an fp16 and an fp32, a `.safetensors` and a
`.pt`. A model's details show it as one pill, with a list of its files and which one Send
uses; its card counts it once, and a sync fetches its gallery once.

**0.45 - I'm feeling lucky.** The Civitai Browser can show you what you would never have
searched for: tick "I'm feeling lucky" and Search becomes Draw - a page of models picked at
random from all of Civitai, every model your filters allow as likely as any other. Type,
base model, tag, period and NSFW still apply; what a draw cannot use is greyed out while
the box is ticked.

Every change, version by version, is in [CHANGELOG.md](CHANGELOG.md).

## A look around

### Your library, at a glance

Every model on disk in one grid, with its Civitai preview. Filter by type, base model,
NSFW level, file size, licence terms and more, then sort by name, size, rating, downloads
or date. Pin the models you come back to: they get a tab of their own above the grid.
Save Search keeps the filters, and the tab opens with them next time.

![Model Manager grid with filters](docs/images/mm-grid.png)

### Everything about a model, in one panel

Click a card for its trigger words, tags, description, creator, licence terms and the
NSFW breakdown of its gallery. Versions of the same model are grouped, and a selector
switches between them - including the versions you have not downloaded, as Civitai listed
them at the last sync, each with a Download.

![Model details panel](docs/images/mm-details.png)

### Example images you can reuse

The model's Civitai gallery, with each image's prompt and settings. One click sends them
to txt2img, with the sampler, scheduler and VAE matched against what you have installed,
and the image's LoRAs and embeddings laid out as chips under the prompts: click one to
put it in the prompt or take it out, or to download it if you do not have it. A banner
says how many images are hidden as NSFW, for having no usable prompt, or both, with a
switch for each.

![Image gallery with generation parameters](docs/images/mm-gallery.png)

### Every image you generate

The **Generations** tab has every image you have generated and saved, newest first,
whatever model made it. A batch is one tile, opening onto its images; a click opens an
image large, with its prompt and settings, and the arrow keys step through them all.
**Group by** gathers images that share something - the prompt, as written or as
generated, the base model, the model, the LoRAs, the size, the day - or two of them: by
model, then prompt, each model is a row with its prompts under it. **Rate** sets an
image's NSFW level where the prompt got it wrong; **Select** ticks batches and images to
delete at once, the files too if you choose. Send puts an image back in txt2img or
img2img with the preset, checkpoint, text encoders and VAE it was made with.

![Generations tab: batches and images, newest first, with the toolbar and NSFW banner](docs/images/generations-grid.png)

![Generations tab grouped by model](docs/images/generations-grouped.png)

### Your own generations, by model

Beside a model's Civitai images, a tab of the images you have generated with it - with
the checkpoint, or with any LoRA, text encoder or VAE it used. Each generation is one
card: its image, or its batch as a grid, with the settings from its infotext. Send puts
them back in txt2img or img2img as Forge's PNG Info would; Delete, or Select for several,
removes the record, and the image files too if you tick the box beside it. Recording
starts once the extension is installed, and can be turned off in its settings.

![A model's Your generations tab: a card per generation](docs/images/mm-your-generations.png)

### Generations, queued for later

Press **Queue** beside Generate, in txt2img or img2img, and what Generate would run is
kept as a task: the checkpoint, VAE and text encoders, every setting, the scripts and their
arguments - an X/Y/Z plot, ControlNet's units with their images - and the images it was
given. The **Queue** tab runs the tasks one at a time, in the order they were queued, each
with its own checkpoint, while you go on working; it carries on with the page closed, and a
restart keeps the tasks. A bar along the running task shows how far along it is. **Pause**
lets it finish and starts no other; **Stop** ends it, keeping what it made. A click on a
task shows everything it holds, and **Load to UI** sets its tab up with it again; **Show
images** opens the Generations tab on the images it made. **Retry** queues a copy, with the
same seed or a random one, and **Select** ticks several to retry or delete at once.

![Queue tab: the running task with its progress bar, the tasks waiting, and History](docs/images/queue.png)

### Keeping it in sync

**Sync with Civitai** reads your model folders - adding new files, forgetting deleted ones -
identifies new files by hash and fetches their Civitai metadata, and says what it is about to
do before it does it.

![Sync dialog](docs/images/mm-sync.png)

### Finding new models

Search Civitai without leaving the WebUI, by name, type, base model, tag and file size.
Models you already have are marked **Owned**, with a jump to them in the Model Manager.
Three checks Civitai cannot make are done here: **Only Show Models with SFW images** leaves out models
whose first example images include anything NSFW, **Only with usable prompts** keeps
only models whose images have a prompt worth reusing, and **Hide models in my library** leaves
out the ones marked Owned. Results stream in as they are found.
Save Search keeps the search, and runs it the first time the tab is opened.

![Civitai Browser search results](docs/images/cb-search.png)

### Downloads you control

Downloads land in the folder for their model type, are checked against Civitai's
SHA-256, and are complete once the model is in your library, so it can be opened in the
Model Manager straight away. Two run at a time, each with its speed and the time it has
left. A waiting download can be started now, moved up or down, or cancelled; a running one
paused, and resumed from where it stopped - after a WebUI restart too. The list keeps its
order whatever each download is doing.

![Downloads panel: two downloading with speed and time left, two waiting with Start now and up / down](docs/images/downloads.png)

### Notes, and what is new

Each tab says, at its top, what is new since your last update and what to do about it -
a button does it where one helps, such as opening the sync dialog with the right box ticked.
Each tab also has an introduction, with buttons for its first steps. One click dismisses a note;
the settings window's **What's new** keeps them all. When a newer version is out, each
tab's header says so beside the version.

![A tab's notes: an introduction, with buttons for its steps, on a pile of six](docs/images/notes.png)

## Model Manager

Browse and organize the models already on disk.

- **Grid view** with thumbnails, configurable card size, and paginated loading
- **Filters**: search, type, base model, NSFW level (max or contains mode), Civitai data
  present, bookmarked, minimum version count, file size, and licence terms (commercial
  use, derivatives, different licence). **Save Search** keeps them, in the database, and
  the tab opens with them; a right-click on it forgets them
- **Pins**: pinned models get a **Pinned** tab above the grid, the rest an **Unpinned**
  one; a pin is kept by the model, or by the file for one Civitai does not know
- **Type from the file itself**: a sync reads each file's tensor names and shapes, so a
  VAE shared on Civitai as a "Checkpoint" is filed as a VAE, LoRA formats are told apart
  (LORA, LoCon, LoHa, LoKr, DoRA, LyCORIS Full), and files Civitai does not know get a
  type too. `.ckpt` and `.pt` files are read without running anything in them. Until a
  file has been read, its Civitai type is used
- **Sort** by name, file size, file modified, published, scanned, downloaded, updated,
  rating, or download count
- **Version grouping**: versions of the same model are grouped, with a version selector
  in the details panel. A card shows the newest you have; where two share a date, the one
  Civitai lists first. It lists every version Civitai has, as of the last sync, with the
  ones you have marked; one you do not have shows its details and a Download, followed in
  the same downloads panel as the Civitai Browser's
- **Details panel**: trigger words, tags, description, creator, rating, per-level NSFW
  breakdown, licence terms, and the full Civitai image gallery with generation parameters
- **Send to txt2img** from any gallery image, including sampler, scheduler, VAE,
  and resource matching against your installed models. For Flux, Qwen-Image, Wan and
  Forge Neo's other newer models it also switches the UI preset and selects the text
  encoders and VAE the model needs, read from the model file itself. In a LoRA's or a
  VAE's gallery that model is the image's own checkpoint when you have it, else the
  LoRA's, else the image's checkpoint as Civitai describes it (asked once, remembered)
- **Videos**: a Wan text-to-video example is sent with its frame count and size, read
  from the video. An image-to-video model goes to img2img instead, starting from the
  video's first frame (or the still, in its gallery), with denoising at 1
- **LoRA and embedding chips**: after a send, the image's LoRAs, LoCons and embeddings
  appear under the negative prompt, named as your files are - one chip per LoRA, however
  many ways the image names it. A click puts one in at the
  image's weight (0.5 when it gives none) or takes it out at any weight; an embedding
  goes to the prompt the image used it in. A LoRA the prompt names differently from
  your file is renamed to it. **Clear** removes the chips and leaves the prompts alone
- **Missing resources** can be downloaded from their chip or from the image's
  **Resources** dialog: the version the image used, or the model's newest if Civitai no
  longer has it. Resources Civitai does not know are shown as such, with nothing to click
- **Bookmarks**, per-model force re-sync, and model deletion (removes the model plus its
  sidecar metadata and preview files)
- **Sync** finds new model files on disk, and fetches their Civitai metadata by file hash

## Generations

Every image you generate, in one place. Recorded as Forge saves it, with the prompt as you
typed it and as each image was made, the infotext, every setting, and the LoRAs each
image of a batch used.

- **Grid** of batches and images, newest first, loading on as you scroll; **Preserve
  order** keeps every tile one column, strictly newest first
- **Search** the prompts and negative prompts, as generated or as typed: every word must be
  there, and a quoted phrase counts as one; `task:17` shows what task 17 of the queue made
- **Group by** prompt (as written or as generated), base model, model, LoRA combination,
  size or day - or two at once, from the menu's "then by" list: the first grouping is a
  row across the grid, the second its groups under it
- **Viewer**: the image large, its prompt and settings beside it, the arrow keys or the
  wheel through every image
- **Rate** an image's NSFW level, or a whole batch's, where its prompt misled the filter
- **Select** batches and images - shift-click for a range, Select all loaded - and delete
  them at once, asked once, the files too if you choose
- **Send** to txt2img or img2img, with the preset, checkpoint, text encoders and VAE the
  image was made with; **Show model in Model Manager**, from a tile's ⋯ menu, opens it there

## Queue

Generations kept to run later, one at a time, while you go on working.

- **Queue**, beside Generate in txt2img and img2img: what Generate would run, kept as a
  task - the checkpoint, VAE and text encoders, every setting, the scripts and their
  arguments, ControlNet's units with their images, and the images it was given
- **Start** runs the pending tasks in the order they were queued, each with its own
  checkpoint, VAE and text encoders, through Forge's own Generate: its progress, scripts and
  saving all apply. A task whose checkpoint or VAE is gone fails rather than run on another.
  The queue carries on with the page closed; a restart leaves it stopped, the tasks kept
- **Pause** lets the running task finish and starts no other until **Resume**; **Stop**
  ends it, keeping the images it made. Forge's own Interrupt stops the task, and the queue
  goes on
- **Active** and **History**: what each task asks for - checkpoint, VAE, size and hires
  fix, sampler, steps, batch - and how many images it made; the running one has a bar
  showing how far along it is
- A click on a task shows everything it holds; **Load to UI** sets its tab up with it
  again, checkpoint and VAE included; **Show images** opens the Generations tab on what it
  made
- **Retry** queues a copy, with the first run's seed or a random one; **Delete** removes a
  task, with the images it made or without; **Select** ticks several, shift-click for a
  range; **Clear history** hides the ended tasks
- A task that uses an extension no longer installed asks before it runs: without it, or
  not at all
- **Generate asks first** when it would make more than 4 images - batch count times batch
  size, a setting: generate, queue the run instead, or cancel
- Your own generations go first: the queue waits for them before each task
- Two WebUIs sharing one database each keep a queue of their own

## Civitai Browser

Search Civitai and download directly into the right model folder.

- Search by query, type, base model, tag, period, file size and sort order, with results
  streamed in as they are found; **Save Search** keeps the search, and runs it the first
  time the tab is opened
- **Ownership detection**: models you already have are marked as owned, with a
  "Show in Model Manager" jump
- **Usable-prompt filter**: only show models whose images carry a prompt plus
  steps/sampler/CFG
- **Hide models in my library**: leave out the models marked Owned, the page filled from
  the rest
- Image gallery read live from Civitai, a page at a time, with Load More
- **Downloads**, shared with the Model Manager: as many at a time as the settings say -
  two unless changed - with progress, speed and time left; a waiting one started now,
  moved up or down, or cancelled; a running one paused and resumed from where it
  stopped, after a restart too; Pause all and Resume all.
  A configurable destination folder template, a SHA-256 check against Civitai's, the
  model added to your library before the download counts as complete, and a WebUI
  model-list refresh

## Installation

1. Open SD WebUI Forge
2. Go to **Extensions** -> **Install from URL**
3. Paste: `https://github.com/therestlesscat/sd-webui-forge-model-manager.git`
4. Click **Install**
5. Restart the WebUI

`blake3` is installed automatically on first run; it is optional and only used as a hash
fallback.

**Updating**: each tab's header says when a newer version is out, beside the version.
Update from **Extensions -> Check for updates**, then **Apply and restart UI**. A note at
the top of a tab says if an update asks for anything - a sync with every header read again, say. If
Forge Neo and the original Forge share one database, update the extension in both before
starting either.

## Usage

1. Open the **Model Manager** tab. Its introduction, at the top, walks you through the
   first steps, with buttons for them
2. Click **Sync** to read the models on disk and fetch their Civitai metadata
3. Set your filters and click **Load Models**
4. Click any model card to open its details
5. Generate as usual: the images appear in the **Generations** tab, and under each model
   they used

## Settings

In the settings window - the gear at the top right of each tab - or under **Settings ->
Model Manager**, in ten groups by what the settings are for. Both edit the same values; each
setting is named there by what it does, and on Forge's page by a name that stands alone.
Inside a group, a setting for one tab sits under that tab's heading, and one that depends
on a switch sits under it, greyed while the switch is off. The window lists the groups on
the left, each with the count of settings it shows; pressing one shows it alone. A tab's gear
opens on that tab's settings, beside All settings; All / Changed lists only the settings
that differ from their default, each with Reset; the search finds a setting by every word
typed, in its names, its description and its tabs. Each tab's switch comes first,
in the Tabs group: a tab switched off does nothing at all, and the window shows only the
settings of the tabs that are on. One switched back on that
needs a page reload or Reload UI to return says so, and offers it - beside **Restart WebUI**,
which starts the server and the page afresh for the cleanest slate, where the WebUI was
started by its own script. With every tab off, the window goes with them: the switches come
first under **Settings -> Model Manager** too.

**Tabs**

| Setting | Default | What it does |
|---------|---------|--------------|
| Queue Tab | on | On: a Queue button beside Generate, in txt2img and img2img, keeps the generation as a task, and the Queue tab runs the tasks. Off: the tab and the buttons are hidden at once, and a running queue stops; from the next start neither is created at all. The tasks are kept, and come back when this is on again. |
| Generations Tab | on | On: every txt2img and img2img result saved to disk is recorded with all its settings, and shown in the Generations tab and the gallery of each model it used. Off: nothing is recorded, and the Generations tab and each model's Your generations are hidden at once; from the next start the Generations tab is not created at all. What was recorded is kept, and comes back when this is on again. |
| Civitai Images Tab | off | On: the Civitai Images tab - the Civitai images stored for the models in your library, in an order its seed picks. Off: the tab is hidden at once and stops, and from the next start it is not created at all. |
| Model Manager Tab | on | On: the Model Manager tab - your models, their details and galleries, and the sync with Civitai. Off: the tab is hidden at once and stops, and from the next start it is not created at all; a sync already running finishes. Your library is kept, and downloads still add to it. |
| Civitai Browser Tab | on | On: the Civitai Browser tab - searching Civitai, and downloading from it. Off: the tab is hidden at once and stops, and from the next start it is not created at all; downloads already running finish. |

**Civitai account**

| Setting | Default | What it does |
|---------|---------|--------------|
| API key | empty | Optional. Gives higher rate limits for requests to Civitai's API. |
| Requests per second | 6 | How fast to call Civitai's API when an API key is set. Higher is faster but more likely to be rate limited. Applies to the next search, download or sync; one already running keeps its rate. Applies once an API key is set. |
| Images loading at once | 64 | How many of Civitai's images the galleries load at once; the rest wait until one has loaded, nearest the screen first. Civitai makes resized copies at about 10 to 16 a second and queues the rest, and images asked for hundreds at once failed to load. Not a page size: a page still holds as many images as its tab's setting says. |

**Downloads**

| Setting | Default | What it does |
|---------|---------|--------------|
| Downloads at once | 2 | How many downloads run at the same time; the rest wait their turn in the queue. A fast connection may want more; a hard disk, a network drive or a slow connection may want 1. Start now still starts a waiting download over this number. Applies at once: a lower number lets the running downloads finish, and starts no new one until fewer run. |
| Download large files in parts | on | Fetches a large file from Civitai over several connections at once, each fetching a part of it. Civitai's storage holds each connection to about 60 MB/s, so a faster line gets large files sooner. Off, every file downloads over one connection, as before. Applies to the next download, and to a paused one when it resumes. |
| Connections per file | 4 | How many connections a large file is fetched over. A part is at least 32 MB, so smaller files use fewer. Applies to the next download, and to a paused one when it resumes. |
| Download folder | `_{baseModel}/{modelName}` | The folder a download is filed into, inside its type's folder. Placeholders: {baseModel}, {modelName}, {creator}, {modelId}. |

**Pages and cards**

| Setting | Default | What it does |
|---------|---------|--------------|
| Full-size images on model cards | off | Civitai's image server sends a copy the size it is drawn; this asks for the upload instead. Measured on 20 images: a card's copy 54 KB on average, the upload 3.6 MB - 66 times as much. But a copy is usually slower the first time a gallery is opened: Civitai seldom has it ready (1 image in 34, against 15 in 33 uploads, in one test) and takes about half a second to make each. Videos load as copies whatever this says: an upload can be a GIF that cannot play. For the cards of both tabs' grids. |
| Play videos on model cards | on | On, a model card whose cover is a video plays it. Off, the card shows the video's still, with a play button in its corner; the video loads only when pressed. Galleries and the viewer are not changed. |
| Full-size images in galleries | off | Civitai's image server sends a copy the size it is drawn; this asks for the upload instead. Measured on 20 images: a card's copy 54 KB on average, the upload 3.6 MB - 66 times as much. But a copy is usually slower the first time a gallery is opened: Civitai seldom has it ready (1 image in 34, against 15 in 33 uploads, in one test) and takes about half a second to make each. Videos load as copies whatever this says: an upload can be a GIF that cannot play. The image viewer shows the upload either way. For model galleries and the Civitai Images tab. |
| Tiles kept on the page (Generations Tab) | Only those near the view | Only those near the view: draws only the rows near what you see, and stays smooth at 75,000 images. All of them: puts every tile on the page. The browser's find then sees them all, but a grid of thousands freezes for seconds. |
| Read tiles in one pass (Generations Tab) *Alpha* | on | How the Generations tab reads your images for each set of tiles. On: reads them once, into a temporary table in memory, and builds every tile from it - grouped by base model, 75,684 images took 0.28 s instead of 1.47. Off: reads them again for each tile's previews, checkpoint and LoRAs, as before. If tiles look wrong or a level does not load, turn it off and report it. |
| Tiles kept on the page (Civitai Images Tab) | Only those near the view | Only those near the view: draws only the rows near what you see, and stays smooth at 75,000 images. All of them: puts every tile on the page. The browser's find then sees them all, but a grid of thousands freezes for seconds. |
| Models per page (Model Manager Tab) | 20 | How many models a page of the Model Manager shows. |
| Civitai images per page (Model Manager Tab) | 100 | How many images Load More adds in a model's Civitai images - counted before the NSFW and prompt switches. |
| Generations per page (Model Manager Tab) | 100 | How many generations Load More adds in a model's Your generations. Not used by the Generations tab: it loads as you scroll. |
| Card size (Model Manager Tab) | 200x280 | The size of the model cards, as width x height in pixels. |
| Least explicit image as cover (Model Manager Tab) | on | On: each card shows the model's least explicit image. Off: its most recent one. Whether galleries hide explicit images is a setting of its own: Hide explicit images at first. |
| Models per page (Civitai Browser Tab) | 20 | How many models a page of the Civitai Browser shows. |
| Images per page (Civitai Browser Tab) | 100 | How many images Load More adds in a model's images, fetched from Civitai - counted before the NSFW and prompt switches. |
| Card size (Civitai Browser Tab) | 200x280 | The size of the model cards, as width x height in pixels. |

**What is hidden**

| Setting | Default | What it does |
|---------|---------|--------------|
| Hide explicit images at first | on | How Civitai's images open: a model's image gallery, in the Model Manager and the Civitai Browser, and the Civitai Images tab - and a model's Your generations; the Generations tab has its own. The Show NSFW switch above the images shows them there. The Civitai Browser's Include NSFW models decides which models are listed, not which of their images are shown. |
| Find explicit PG images with | Trained model | The trained model reads each image's prompts and the resources it used, and catches most of the explicit images Civitai under-rates - but it judges by what it learned, and sometimes raises an image that is fine or misses one that is not. The word list treats an image as X only when its prompt uses one of the words: nothing else, and nothing you cannot check. Stored images are judged again in the background when this changes. |
| Share treated as X | 2.0 | Civitai rates some explicit images PG or PG-13. A model trained on image prompts - their words, word pairs, negative, ADetailer and hires prompts, and the resources used - finds them, and this is how far it goes: the share of PG and PG-13 prompts it may treat as X, in percent. 2 (default) caught about 94% of X/XXX prompts on a library it had never seen. 1 is stricter, 3 or more catches more at more cost. 0 turns the model off, leaving only the words. Stored images are judged again in the background when this changes. |
| Extra NSFW words | empty | An image Civitai rates PG or PG-13 whose prompt uses one of these words is treated as X everywhere - hidden from the grid previews, the galleries and the SFW filters. Whole words, any case. These add to the list that comes with the extension, in model_manager/data/nsfw_prompt_words.txt. Stored images are judged again in the background when this changes. |
| Hide images with no prompt at first | on | About a tenth of Civitai's images carry no prompt at all, and they cannot be read or reused. Can be turned back on per model from the panel above the images. Model galleries only, in the Model Manager and the Civitai Browser: the Civitai Images tab shows every image. |
| Hide explicit images at first (Generations Tab) | on | How the Generations tab opens. The Show NSFW switch above the images shows them until the tab is opened again. A model's Your generations, in the Model Manager, follows the other Hide explicit images at first, in Shared across tabs. |
| Images with a prompt a model needs (Civitai Browser Tab) | 1 | For the Only with usable prompts filter: a model must have at least this many images, of its first 20, carrying a prompt and its steps, sampler and CFG. |
| Fill pages while hiding NSFW models (Civitai Browser Tab) *Not recommended* | off | Normally a page with Only Show Models with SFW images stops after checking a few dozen models and can come back short. With this on, it keeps searching until the page holds the full Models per page. Most Civitai models have NSFW images, so one page can take hundreds of requests and several minutes, and makes Civitai's rate limit likely. A page still stops if Civitai starts refusing requests. |
| Mark on-site-only versions (Civitai Browser Tab) | off | Marks the versions whose creator allows them only for generating on Civitai - Civitai refuses their download - on the cards and in a model's panel. Asks Civitai once per page and once per model opened; its answer is often under a megabyte, and can be a few. The Model Manager marks them whatever this says, from what a sync stored. |

**Send**

| Setting | Default | What it does |
|---------|---------|--------------|
| Use the image's Clip skip | on | On: where an image gives a clip skip other than your Clip Skip setting, Send adds it to the tab's Override settings, and says so - so the image can be made again as it was. It applies to the generations made while it is there; your setting is not changed, and the next Send replaces it. Not for Flux, where clip skip changes nothing. Off: left to Forge's paste, which in Forge Neo ignores it. |
| Highest Clip skip | 6 | An image's clip skip above this is left out of Override settings, and your Clip Skip applies; Send's notice says so. Most models are made for 1 or 2. |
| *Preset* text encoders and VAE | empty | One per Forge Neo preset: Flux.1 / Chroma, Flux.2 Klein, Lumina Image 2.0, Z-Image, Anima, Wan, Qwen-Image, Krea 2, ERNIE-Image, PiD. File names to select for that preset's models, comma-separated. Empty picks the highest-precision file installed; name an fp8 or GGUF file to use a smaller one. Each setting says what the model needs and links to the files |

**Generations**

| Setting | Default | What it does |
|---------|---------|--------------|
| Tick "also delete the files" | off | Ticks the box in the delete question. It can still be unticked for one delete. |
| Keep img2img start images (Generations Tab) | on | On: each img2img generation recorded keeps the picture in its mode's canvas and what was painted over it - the mask, or the strokes - so Send puts them back and the viewer shows them. One file per picture, however many generations started from it, deleted with the last of them. Off: nothing more is kept; what was kept stays. |
| NSFW level for images without infotext (Generations Tab) | Unknown | What the Sync images dialog starts from. The level picked there is given to the images without infotext that sync brings, and kept with them. A rating you give an image wins. |
| Group images without infotext by name (Generations Tab) | on | What the Sync images dialog starts from. Images in one folder whose file names say the same settings, saved close together, become one batch, as one press of Generate made them. |

**Files and folders**

| Setting | Default | What it does |
|---------|---------|--------------|
| Database file *Needs restart* | empty | Full path to the database file, with its name. Empty: the default, in the extension's folder. Two WebUIs can share one. |
| Make thumbnails | on | Ticks Make thumbnails in the Sync images dialog, and makes one for each image you generate. A sync with it ticked makes one for every image without one. Tiles then load a small copy, 450 pixels tall, instead of the full file; the viewer still shows the full file. An image without one shows its full file. |
| Where thumbnails are kept | In a folder | In a folder: the Thumbnail folder below. Beside each image: in a .thumbnails folder next to it, which Sync images skips. A change applies to thumbnails made from then on; those made before keep working where they are. |
| Thumbnail folder | empty | Its full path. Empty: a folder named thumbnails beside the database, which two WebUIs sharing the database share too. Deleting it is safe: a sync makes them again. |
| Thumbnails made at once | 0 | 0: as many as the machine has processors - making one is mostly processor work. Lower it for a hard disk or a network drive, or to keep the machine free while a sync makes them. |
| Folder for queued tasks' images (Queue Tab) | empty | A queued task keeps the images it was given here - an img2img source and mask, ControlNet's images - until it is deleted, one folder per task. Empty: queue-inputs in the WebUI's folder, beside outputs. Tasks keep their files' full paths, so a change applies to tasks queued after it. |
| Folder for start images (Generations Tab) | empty | Its full path. Empty: a folder named generation-inputs beside the database, which two WebUIs sharing the database share too. Generations keep their files' full paths, so a change applies to generations recorded after it. |

**Sync and queue**

| Setting | Default | What it does |
|---------|---------|--------------|
| Ask before generating more than (Queue Tab) | 0 | Batch count times batch size. Above it, Generate asks whether to generate, queue it instead, or cancel; the question can be turned off in each browser. 0: Generate never asks. |
| Files hashed at once (Model Manager Tab) | 4 | How many model files to hash at once when a sync identifies them. Each file is read in full, so the drive usually sets the pace. Hard disk or network drive: 1-2 - more make it slower. SATA SSD: 2-4. NVMe: 4-8, or more on a CPU with many cores. Lower it if a sync makes the machine slow. |
| Images kept per version | 100 | How many of each version's Civitai images a sync fetches and keeps - from the sync dialog, a model's Sync, a download. The dialog's "First N images" is this number. A model's NSFW level counts its worst stored image, and the Civitai Images tab shows stored images only: fewer kept, less to judge and show. |

**Updates**

| Setting | Default | What it does |
|---------|---------|--------------|
| Check for a new version | on | On: after the WebUI starts, and every 12 hours, the extension reads the version.json file on its GitHub repository - the version it holds, nothing else - and each tab's header says when a newer one is out. Off: GitHub is never asked. |

### Text encoders and VAEs for newer models

Flux, Qwen-Image, Wan and the other newer models Forge Neo runs need text encoders and a
VAE that an image's generation data never names. Put text encoders in
`models/text_encoder` and VAEs in `models/VAE`. Forge Neo's
[Download Models](https://github.com/Haoming02/sd-webui-forge-classic/wiki/Download-Models)
page lists them all.

| Preset | Needs |
|--------|-------|
| Flux.1 / Chroma | CLIP-L, T5-XXL, Flux VAE (`ae`). Chroma: T5-XXL and `ae` only |
| Flux.2 Klein | Qwen3 4B (4B) or Qwen3 8B (9B), Flux.2 VAE |
| Lumina Image 2.0 | Gemma 2 2B, Flux VAE (`ae`) |
| Z-Image | Qwen3 4B, Flux VAE (`ae`) |
| Anima | Qwen3 0.6B, Qwen-Image VAE |
| Wan | UMT5-XXL (Hugging Face layout), Wan 2.1 VAE |
| Qwen-Image | Qwen2.5-VL 7B, Qwen-Image VAE |
| Krea 2 | Qwen3-VL 4B, Qwen-Image VAE |
| ERNIE-Image | Ministral 3 3B, Flux.2 VAE |
| PiD | Gemma 2 2B IT; the VAE depends on the model |

When nothing is set, Send to txt2img uses Forge's saved choice for the preset if it is
the right kind of file, and otherwise the file with the highest precision. A file named in
the settings comes before both. A missing module, or a named file Forge does not list, is
reported in a notice.

## Data storage

Metadata lives in a SQLite database (`models.db` in the extension folder by default),
with your generations, your pins and saved searches, the downloads waiting to be resumed,
the queue's tasks, and which notes you have dismissed. The images a queued task was given
are files in `queue-inputs`, in the WebUI's folder unless the settings name another, and
are deleted with the task.
Before an update that rebuilds one of its tables, a copy is written beside it
(`models.db.backup_<date>_<time>`). Forge Neo and the original Forge can share one
database; keep the extension at the same version in both. Sidecar files written next to
each model stay compatible with other Civitai extensions:

```
model.safetensors
model.civitai.info     <- model + version metadata
model.preview.png      <- thumbnail
```

## NSFW levels

The extension uses Civitai's NSFW levels: PG, PG-13, R, X, XXX, Blocked.

The effective level for a model is the maximum of:

- Model-level NSFW rating
- Version-level NSFW rating
- Highest image NSFW rating

Civitai's raters miss some images. An image rated PG or PG-13 whose prompt reads as
explicit is treated as X everywhere: grid previews, both galleries, and the SFW filters.
Its badge reads "X · prompt". Two things decide it - or, with **NSFW detection** set to
Word list, the words alone:

- **A prompt model**, trained on image prompts - their words, pairs of words, negative,
  ADetailer and hires prompts, and the resources they used - to tell the prompts of images
  Civitai rates X or XXX from PG or PG-13 ones. It was trained on 762,000 prompts from the
  thousand Civitai models with the most images. The setting says how far it goes, as the
  share of PG/PG-13 prompts it may raise: at the default 2 it caught about 94% of X/XXX
  prompts on a library it had never seen, where a word list caught 81%. It ships as
  `model_manager/data/nsfw_prompt_model.json.gz`, which holds no words, only their hashes;
  `tools/run_nsfw_training.sh` trains it again from Civitai, and `tools/train_nsfw_model.py`
  from a library.
- **A short list of explicit words**, in `model_manager/data/nsfw_prompt_words.txt`, plus
  any you add in the settings. Only the positive prompt is read, and only whole words.

Stored images are judged again in the background whenever the words, the model or its
setting change, from the prompts already stored, so no sync is needed. An image whose
prompt was never fetched keeps Civitai's rating.

## License

MIT License - see [LICENSE](LICENSE).
