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

**0.69 - Pick one type, or several.** The Type filter, in the Model Manager and the Civitai
Browser, picks one type as before; tick Select several, at the bottom of its list, to pick any
number, such as LoRAs and embeddings together. Combine LoRA kinds, in the settings' Pages and
cards, shows LORA, LoCon, LoHa, LoKr, DoRA and LyCORIS Full as one entry.

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
- **Filters**: search, type (one, or several with Select several), base model, NSFW level
  (max or contains mode), Civitai data present, bookmarked, minimum version count, file
  size, and licence terms (commercial use, derivatives, different licence). **Save Search** keeps them, in the database, and
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
| Queue Tab | on | When on, a Queue button appears beside Generate in txt2img and img2img. It saves the generation as a task instead of running it, and the Queue tab runs the saved tasks. When off, the tab and the buttons disappear at once and a running queue stops; from the next start of the WebUI they are not created at all. Your saved tasks are kept, and come back when you turn this on again. |
| Generations Tab | on | When on, every txt2img and img2img image saved to disk is recorded with all the settings that made it. Recorded images show in the Generations tab, and in the gallery of each model they used. When off, nothing new is recorded, and the Generations tab and each model's Your generations disappear at once; from the next start of the WebUI the Generations tab is not created at all. What was recorded is kept, and comes back when you turn this on again. |
| Civitai Images Tab | off | When on, the Civitai Images tab shows the Civitai images stored for the models in your library, in an order set by its seed. When off, the tab disappears at once and stops, and from the next start of the WebUI it is not created at all. |
| Model Manager Tab | on | When on, the Model Manager tab shows your models with their details and galleries, and syncs them with Civitai. When off, the tab disappears at once and stops, and from the next start of the WebUI it is not created at all. A sync that is already running finishes. Your library is kept, and downloads still add to it. |
| Civitai Browser Tab | on | When on, the Civitai Browser tab lets you search Civitai and download from it. When off, the tab disappears at once and stops, and from the next start of the WebUI it is not created at all. Downloads that are already running finish. |

**Civitai account**

| Setting | Default | What it does |
|---------|---------|--------------|
| Civitai API key | empty | Optional. With your Civitai API key, Civitai allows more requests to its API before it starts turning them away. |
| Requests per second | 6 | How many requests per second the extension sends to Civitai's API while an API key is set. A higher number is faster, but makes it more likely that Civitai turns requests away. A change applies to the next search, download or sync; one already running keeps its speed. Applies once an API key is set. |
| How many gallery images load in parallel | 64 | When a model's gallery or the Civitai Images tab shows Civitai's images, your browser fetches each picture or video from Civitai's image server. This sets how many it fetches at the same time. The others wait their turn, and those nearest the screen go first. Civitai makes its resized copies at about 10 to 16 a second and queues the rest; when hundreds were asked for at once, many failed to load. It does not change how many images a page holds: each tab has its own setting for that. |

**Downloads**

| Setting | Default | What it does |
|---------|---------|--------------|
| How many downloads in parallel | 2 | How many downloads run at the same time. The others wait their turn in the queue. A fast connection may want more; a hard disk, a network drive or a slow connection may want 1. Start now still starts a waiting download, even above this number. A change applies at once: a lower number lets the running downloads finish, and starts no new one until fewer are running. |
| Download large files in parts | on | When on, a large file is downloaded from Civitai over several connections at once, each fetching a part of it. Civitai's storage limits each connection to about 60 MB/s, so a faster line gets large files sooner. When off, every file downloads over one connection. A change applies to the next download, and to a paused one when it resumes. |
| Connections per file | 4 | How many connections a large file is downloaded over. Each part is at least 32 MB, so a smaller file uses fewer connections. A change applies to the next download, and to a paused one when it resumes. |
| Download folder | `_{baseModel}/{modelName}` | Where a downloaded model is saved, inside the folder Forge uses for its type: Stable-diffusion for checkpoints, Lora for LoRAs, and so on. Write a path, and add any of these to fill in the model's details: {baseModel} for its base model, {modelName} for its name, {creator} for its creator's user name and {modelId} for its Civitai id. A model's details can contain spaces, or characters Windows does not allow in a folder name, such as : or ?. Each of those becomes an underscore: the base model SDXL 1.0 becomes the folder SDXL_1.0. The default, _{baseModel}/{modelName}, saves an SDXL LoRA named My Style in Lora/_SDXL_1.0/My_Style. Leave it empty to save every model straight into its type's folder. |

**Pages and cards**

| Setting | Default | What it does |
|---------|---------|--------------|
| Full-size images on model cards | off | When on, model cards load each picture as it was uploaded to Civitai, instead of a copy Civitai's image server resizes to the card. Uploads are much larger: on 20 images, a card-sized copy was 54 KB on average and the upload 3.6 MB, 66 times as much. Even so, a copy is often slower the first time, because Civitai seldom has it ready: in one test it had 1 copy in 34, against 15 uploads in 33, and took about half a second to make each copy. Videos always load as copies, because an upload can be a GIF that cannot play. This applies to the cards in both the Model Manager and the Civitai Browser. |
| Play videos on model cards | on | When on, a model card whose cover is a video plays it. When off, the card shows a still from the video with a play button in its corner, and the video loads only when you press it. Galleries and the image viewer are not affected. |
| Full-size images in galleries | off | When on, galleries load each image as it was uploaded to Civitai, instead of a copy Civitai's image server resizes to fit. Uploads are much larger: on 20 images, a card-sized copy was 54 KB on average and the upload 3.6 MB, 66 times as much. Even so, a copy is often slower the first time, because Civitai seldom has it ready: in one test it had 1 copy in 34, against 15 uploads in 33, and took about half a second to make each copy. Videos always load as copies, because an upload can be a GIF that cannot play. The image viewer shows the upload either way. This applies to model galleries and the Civitai Images tab. |
| Scrolling in long grids (Generations Tab) | Smooth: only nearby tiles | How the Generations tab handles a long grid of tiles as you scroll. Either way, tiles load 100 at a time as you near the end. Smooth, the default, keeps on the page only the tiles within about 3,000 px of what you see, and draws the others again as you scroll back to them: scrolling to the end of 75,685 images never froze for more than 50 ms. Keep every tile leaves all the tiles loaded so far on the page, so the browser's Find (Ctrl+F) can search them all, but the page gets slower the further you scroll: at the end of 75,684 images it froze for up to 42 seconds at a time. |
| Read tiles in one pass (Generations Tab) *Alpha* | on | How the Generations tab reads your images to build its tiles. When on, it reads them once, into a temporary table in memory, and builds every tile from it: grouped by base model, 75,684 images took 0.28 s instead of 1.47 s. When off, it reads them again for each tile's previews, checkpoint and LoRAs, as it did before. This is still being tested: if tiles look wrong or a set of tiles does not load, turn it off and report it. |
| Scrolling in long grids (Civitai Images Tab) | Smooth: only nearby tiles | How the Civitai Images tab handles a long grid of tiles as you scroll. Either way, tiles load 100 at a time as you near the end. Smooth, the default, keeps on the page only the tiles within about 3,000 px of what you see, and draws the others again as you scroll back to them: scrolling to the end of 75,685 images never froze for more than 50 ms. Keep every tile leaves all the tiles loaded so far on the page, so the browser's Find (Ctrl+F) can search them all, but the page gets slower the further you scroll: at the end of 75,684 images it froze for up to 42 seconds at a time. |
| Models per page (Model Manager Tab) | 20 | How many models a page of the Model Manager shows. |
| Civitai images per page (Model Manager Tab) | 100 | How many images each press of Load More adds to a model's Civitai images. The count includes the images the NSFW and prompt switches then hide. |
| Generations per page (Model Manager Tab) | 100 | How many images each press of Load More adds to a model's Your generations. The Generations tab does not use it, because it loads more as you scroll. |
| Card size (Model Manager Tab) | 200x280 | The size of the model cards, as width x height in pixels. |
| Least explicit image as cover (Model Manager Tab) | on | When on, each model card shows the model's least explicit image as its cover. When off, it shows the most recent one. Whether galleries hide explicit images is a separate setting, Hide explicit images by default. |
| Models per page (Civitai Browser Tab) | 20 | How many models a page of the Civitai Browser shows. |
| Images per page (Civitai Browser Tab) | 100 | How many images each press of Load More adds to a model's images in the Civitai Browser, fetched from Civitai. The count includes the images the NSFW and prompt switches then hide. |
| Card size (Civitai Browser Tab) | 200x280 | The size of the model cards, as width x height in pixels. |

**What is hidden**

| Setting | Default | What it does |
|---------|---------|--------------|
| Hide explicit images by default | on | Whether explicit images are hidden when a gallery of Civitai's images opens: a model's gallery in the Model Manager or the Civitai Browser, and the Civitai Images tab. A model's Your generations follows it too; the Generations tab has its own setting. The Show NSFW switch above the images shows them in that gallery. The Civitai Browser's Include NSFW models is separate: it decides which models are listed, not which of their images are shown. |
| How to catch explicit images rated PG | Trained model | Civitai rates some explicit images PG or PG-13. This chooses how the extension finds them. The trained model reads each image's prompts and the resources it used, and catches most of them, but it judges by what it has learned: now and then it flags an image that is fine, or misses one that is not. The word list treats an image as X only when its prompt uses one of the listed words, so every decision can be checked. When this changes, your stored images are judged again in the background. |
| PG images the model may flag, in % | 2.0 | How readily the trained model flags images. The number is the percentage of PG and PG-13 images the model may treat as X, measured on the images it was trained on. A higher number catches more explicit images, and wrongly hides more that are fine; a lower one hides fewer, and misses more. At 2, the default, it caught about 94 in 100 X and XXX prompts in a library it had never seen, and flagged 2.2% of that library's PG and PG-13 images. 0 turns the model off, and only the word list is used. When this changes, your stored images are judged again in the background. |
| Additional words to detect NSFW prompts | empty | Words that mark a prompt as explicit, separated by commas. An image Civitai rates PG or PG-13 whose prompt uses one of them is treated as X everywhere: hidden from grid previews, galleries and the SFW filters. Words match whole, in any case. They add to the list that comes with the extension, in model_manager/data/nsfw_prompt_words.txt. When this changes, your stored images are judged again in the background. |
| Hide images with no prompt by default | on | Whether images with no prompt are hidden when a model's gallery opens, in the Model Manager and the Civitai Browser. About a tenth of Civitai's images carry no prompt at all, so they cannot be read or made again. You can show them for one model with the switch above its images. The Civitai Images tab always shows every image. |
| Hide explicit images by default (Generations Tab) | on | Whether explicit images are hidden when the Generations tab opens. The Show NSFW switch above the images shows them until the tab is opened again. A model's Your generations, in the Model Manager, follows the other Hide explicit images by default, under Shared across tabs. |
| How many images with a prompt a model needs to count as usable (Civitai Browser Tab) | 1 | Used by the Civitai Browser's Only with usable prompts filter. A model is listed only if at least this many of its first 20 images have a usable prompt: a prompt with its steps, sampler and CFG scale. |
| Fill each page with models when hiding NSFW models (Civitai Browser Tab) *Not recommended* | off | Used when Only Show Models with SFW images is ticked in the Civitai Browser. Normally a page stops after checking a few dozen models, and can come back with fewer than a full page. When this is on, it keeps searching until the page is full. Most Civitai models have NSFW images, so one page can take hundreds of requests and several minutes, and Civitai is likely to start turning requests away. A page still stops when Civitai does. |
| Mark on-site-only versions (Civitai Browser Tab) | off | Some creators allow a version only for generating on Civitai's site, and Civitai refuses to download it. When this is on, the Civitai Browser marks those versions on its cards and in a model's panel. To know them, it asks Civitai once per page and once per model you open; the answer is often under a megabyte, sometimes a few. The Model Manager marks them whatever this says, from what a sync stored. |

**Send**

| Setting | Default | What it does |
|---------|---------|--------------|
| Use the image's Clip skip | on | When on, and an image was made with a clip skip other than your Clip Skip setting, Send adds the image's value to the tab's Override settings and says so, so the image can be made again as it was. It applies to the images you generate while it is there; your own setting does not change, and the next Send replaces it. Flux images are left alone, because clip skip changes nothing there. When off, clip skip is left to Forge's own paste, which Forge Neo ignores. |
| Highest Clip skip | 6 | When an image's clip skip is above this number, Send leaves it out of Override settings, your own Clip Skip applies, and Send's notice says so. Most models are made for 1 or 2. |
| *Preset* text encoders and VAE | empty | One per Forge Neo preset: Flux.1 / Chroma, Flux.2 Klein, Lumina Image 2.0, Z-Image, Anima, Wan, Qwen-Image, Krea 2, ERNIE-Image, PiD. File names to select for that preset's models, comma-separated. Empty picks the highest-precision file installed; name an fp8 or GGUF file to use a smaller one. Each setting says what the model needs and links to the files |

**Generations**

| Setting | Default | What it does |
|---------|---------|--------------|
| Delete files by default when deleting generations | off | Whether the box "also delete the image files" starts ticked when you delete generations. You can still untick it for one delete. |
| Keep img2img source images and masks (Generations Tab) | on | When on, each img2img generation that is recorded also keeps the picture it started from, and what you painted over it: the mask, or the strokes. Send can then put them back in img2img, and the image viewer shows them. Each picture is kept once, however many generations started from it, and deleted with the last of them. When off, nothing more is kept; what was kept before stays. |
| NSFW level for images without infotext (Generations Tab) | Unknown | The level the Sync images dialog has picked when it opens; the dialog saves the level you pick there for next time. Sync images gives that level to each image it adds that has no infotext, so the image is hidden or shown like any other at that level. A rating you give an image later always wins. |
| Group images without infotext by name (Generations Tab) | on | Whether the Sync images dialog starts with this ticked; the dialog saves your choice for next time. When ticked, images without infotext are put together into batches, as if one press of Generate made them, when they sit in the same folder, their file names show the same settings with running numbers in order, and they were saved close together in time. |

**Files and folders**

| Setting | Default | What it does |
|---------|---------|--------------|
| Database file *Needs restart* | empty | The full path of the database file, with its name. Leave it empty to use the default file, in the extension's folder. Two WebUIs can share one database file. |
| Make thumbnails by default | on | When on, a thumbnail is made for each image you generate, and the Sync images dialog starts with Make thumbnails ticked; a sync with it ticked makes one for every image that has none. Tiles then load a small copy, 450 pixels tall, instead of the full file. The image viewer still shows the full file, and an image without a thumbnail shows its full file. |
| Where thumbnails are kept | In a folder | In a folder keeps every thumbnail in the Thumbnail folder below. Beside each image keeps each one in a .thumbnails folder next to its image, which Sync images skips. A change applies to thumbnails made from then on; those made before keep working where they are. |
| Thumbnail folder | empty | The full path of the folder thumbnails are kept in. Leave it empty to use a folder named thumbnails beside the database file, which two WebUIs sharing the database share too. It is safe to delete: a sync makes the thumbnails again. |
| How many thumbnails generated in parallel | 0 | How many thumbnails are made at the same time. 0 uses as many as the machine has processors, because making a thumbnail is mostly processor work. Use a lower number for a hard disk or a network drive, or to keep the machine free while a sync makes them. |
| Folder for queued tasks' images (Queue Tab) | empty | Where a queued task keeps the images it was given, such as an img2img source and mask or ControlNet's images, one folder per task, until the task is deleted. Leave it empty to use a folder named queue-inputs in the WebUI's folder, beside outputs. Tasks keep the full paths of their files, so a change applies only to tasks queued after it. |
| Folder for img2img source images (Generations Tab) | empty | The full path of the folder where img2img source images and masks are kept. Leave it empty to use a folder named generation-inputs beside the database file, which two WebUIs sharing the database share too. Generations keep the full paths of their files, so a change applies only to generations recorded after it. |

**Sync and queue**

| Setting | Default | What it does |
|---------|---------|--------------|
| Ask before generating more images than (Queue Tab) | 0 | When you press Generate for more images than this number (batch count times batch size), you are asked first: generate them now, queue them to run later from the Queue tab, or cancel. The question has a "Don't ask again in this browser" box. 0 means Generate never asks. It asks only while the Queue tab is on. |
| Files hashed at once (Model Manager Tab) | 4 | How many model files a sync hashes at the same time when it identifies them. Each file is read in full, so the drive usually sets the pace. For a hard disk or a network drive, use 1 or 2, as more makes it slower; for a SATA SSD, 2 to 4; for an NVMe drive, 4 to 8, or more on a processor with many cores. Lower it if a sync slows the machine down. |
| Number of images stored per version by default at sync | 100 | How many of each version's Civitai images a sync fetches and keeps, whether it runs from the sync dialog, a model's Sync button or a download. The dialog's "First N images" uses this number. Keeping fewer means less to judge and show: a model's NSFW level counts its worst stored image, and the Civitai Images tab shows stored images only. |

**Updates**

| Setting | Default | What it does |
|---------|---------|--------------|
| Check for a new version | on | When on, the extension reads the version.json file in its GitHub repository after the WebUI starts and every 12 hours. It reads only the version number, and each tab's header says when a newer version is out. When off, GitHub is never asked. |

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
