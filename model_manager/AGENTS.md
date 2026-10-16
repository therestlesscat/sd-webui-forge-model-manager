# `model_manager/`: the extension's Python

The rules for the Python package: what each module is for, and what its
parts assume of each other. The root `AGENTS.md` holds the working
agreement and what spans the whole repository. `db/`, `civitai/` and `api/`
have files of their own; read them too before working there.

## Layout

### `model_manager/`

| | |
|---|---|
| `db/` | everything that touches SQLite. A facade (`database.py`) over one module per job: `models_ops`, `images_ops`, `generations_ops`, `tasks_ops` (the generation queue), `downloads_ops` (the download queue, across a restart), `query`, `migrations`; `library` the one read of a file with its version (`LIBRARY`); the grid's filters, sort and page travel as one `GridQuery` (`query.py`), read from the request once |
| `civitai/` | talking to Civitai: `client` (auth, rate limiting, retries), `prompt_filter`, `size_filter` (filtering a search by download size), `licensing`, `ownership` (which paid versions the key's account bought), `random_draw` (I'm feeling lucky: a page drawn at random from what Civitai's own filters allow, leaving out the models earlier draws showed under the same filters and those the library has - #191) |
| `forge_host.py` | what the extension asks of the WebUI it runs in, and the one module that asks (with `ui/settings.py`, which registers the settings; `tests/tools/check_forge_imports.py`): its settings, with one table of their defaults (`DEFAULTS`) that registration and every read take; Forge's options, folders, checkpoints, modules, presets and samplers; which Forge it is, and where Neo and the original Forge keep a thing apart |
| `tabs.py` | which tabs are on (#41), the one place that says: each tab's switch (`TABS`), what several share, on while any of them is (`SERVICES`: downloads, Send, the restamp), and which tabs this start created (`built`, for the page). Every route names its area on the line under its own (`api/common.gate`) and answers 403 while it is off - `tab_switches_test.py` holds all 84 to a table; startup work and the recorder ask it too |
| `sync_service.py` | identifying files and refreshing their metadata, after the walk of the library every sync from the dialog starts with (`walk_library`): new files given a row and their header read, sizes brought up to date, files gone forgotten with what only they kept, files in another type's folder moved when asked |
| `sync_estimates.py` | what a sync would cost and cover, before it starts: the sync dialog's request estimate, its staleness-window counts, and the files every sync will hash (`files_to_hash`) |
| `model_dirs.py` | where models live: one table of the folders a sync walks and a download files into, the walk itself (`find_model_files`), when a walk may forget a row, and where a file of each type belongs - with the files in another type's folder, and moving them (`misplaced_files`, `move_misplaced_files`); and what "held" means (`held_here`): a library file on disk, in a folder this WebUI loads from - Owned in the Civitai Browser, left out of a draw, not downloaded again (#188) |
| `jobs.py` | the long jobs - a sync, a restamp of image levels - one of each kind at a time: which runs, its progress, and a failure reported on it |
| `download_service.py` | fetching a model and filing it: its own queue, pause and resume, and what to resume after a restart |
| `scheduler/` | the generation queue (#17): `capture` (the Queue button beside Generate: what Generate would be sent, named and kept as a task), `values` (a value as a task keeps it - images, arrays, objects - and back) |
| `install.py` | which install of the extension this is, one per WebUI (`INSTALL_KEY`): what only one of two WebUIs sharing a database can act on - a download it was making, a task it queued - is kept under its key |
| `hashing.py` | the hashes that tell Civitai which file this is, and how stored ones are read: `read_hashes` / `hash_key` fold either case, and `tests/tools/check_hash_access.py` keeps every reader on them; when stored ones are the file's own (`fingerprint`, kept as `hashes_checked`) |
| `gallery.py` | a gallery's pages, for every gallery: their size, a refresh's size and fetch (`refresh_size`, `fetch_gallery`), and what its two switches hide (`switch_counts`, `filter_images`) |
| `nsfw.py` | how explicit something is — **the only place that decides**, the prompt words and the prompt model included |
| `prompt_rules.py` | what a prompt is worth - worth reading, enough to make the image again - for Python and the SQL that filters and counts with it alike |
| `prompt_levels.py` | restamping stored image levels when the prompt words change |
| `generations.py` | recording the images you generate: what each of Forge's hooks can see, and when |
| `image_sync.py` | Sync images (#233): the images already in Forge's result folders added as generations - the walk and what it skips, the presses rebuilt from the text, the images with no text grouped by their names and a gap learnt from the library, and the job |
| `thumbnails.py` | thumbnails of your generations (#5): where each goes - a folder, or `.thumbnails` beside its image - making one, 450 px tall, as WebP; which images need one; forgetting them when their image's row goes. Made by Sync images when asked, and by the recorder with the setting on; recorded in `generation_thumbnails` by the image's path |
| `image_text.py` | what an image file says: its generation text, read with PIL, the text's last line by Forge's own pattern, and its name read back by Forge's naming settings (`NamePattern`) |
| `file_identity.py` | what a file is (Checkpoint, LORA, LoCon, Controlnet, VAE, Text Encoder, ...) and which model it is for, from its own tensors; a text encoder's or VAE's kind, which `forge_modules` picks by |
| `identity_store.py` | what `file_identity` found, kept on the file's row, and when a file has to be read again |
| `architecture.py` | reading headers (safetensors, GGUF, and pickles without running them) and asking Forge's detector about checkpoints |
| `forge_modules.py` | the text encoders and VAE a model needs, picked from what Forge offers |
| `send_plan.py` | which model Send to txt2img sets Forge up for, and the image's checkpoint a send from any other gallery cannot go without (#134) |
| `resources.py` | which local file, or which version on Civitai, an image's resources are: for the chips under a prompt (the library alone, and Forge's rule for which file `<lora:name>` loads), the Resources dialog, and what a missing one will be called once downloaded |
| `payload_rows.py` | what a Civitai payload says about a model and a version, as database rows - for both kinds of sync, and a sidecar read for a model Civitai no longer has |
| `storage.py` | reading and writing `.civitai.info` |
| `update_check.py` | whether a newer version is out: `version.json` read from GitHub, on this copy's branch, every 12 hours unless turned off |
| `release_notes.py` | notes to the user per release - what is new, what to do after updating: which an install sees, and dismissing them |
| `version.py` | the version this copy is (`VERSION`), and its build, counted from the history; see the root `AGENTS.md`, "Versions" |
| `console.py` | what the extension writes to the console: every "[ModelManager]" line goes through `say()` - a failure with its trace through `say_failure()` - which prints it and keeps the last 2,000 for the sync's log panel (`/model-manager/sync/progress?since=`); `console_test.py` fails on a print of its own |
| `remembered.py` | answers kept in memory - Civitai's about versions, file hashes, SFW verdicts, versions an account bought: a map with a bound, under a lock; how old an answer may be stays its caller's |
| `data/` | files that ship with the code: `nsfw_prompt_words.txt`, the bundled prompt words, and `nsfw_prompt_model.json.gz`, the prompt model, trained from a pull of Civitai by `tools/train_nsfw_from_civitai.py`; `release_notes.json`, the notes to the user |
| `api/` | the HTTP endpoints, one module per area, each with `register(app)`: `models`, `images`, `generations` (your own images: a model's gallery of them, and the Generations tab), `jobs`, `civitai`, `webui`, `settings` (the settings window's), `notes` (notes to the user). Beside them, three helpers: `common` (what every endpoint module shares - the card-size parser, the answer to a failure, the gate every route passes), and for the Civitai endpoints `annotations` (marking up search results with what the library holds) and `prompts` (whether a model's images are worth opening) |
| `ui/` | settings, and the markup for each tab: Queue, Generations, Model Manager, Civitai Browser, in that order - building the Queue tab also wires the Queue buttons; `header.py` what they draw alike - the version and the settings gear, the downloads panel |

## What the pieces assume about each other

### Where each rule lives

**`nsfw.py` is the single source of truth.** There were once three
implementations giving two different answers. If you need a level, ask it; if
the rule is wrong, it is wrong in one place. The browser does not judge: every
image it is sent passes through the server, which stamps `mm_level` (and
`mm_level_from_prompt`, for the "X · prompt" badge) on it - with
`nsfw.stamp_levels()` for Civitai's images, from the stored level for your
generations (`api/generations.py`) - and the page reads that. It used to keep
a copy of the rule in `common.mjs`, fed by the words fetched from the server -
two implementations to keep in step. A new endpoint that hands images to the
page stamps them too; an image without a stamp reads as Unknown, and is hidden
wherever NSFW is.

**Two rules for one thing drift, so each lives once, its SQL beside it.**
`nsfw.py` (a level, with `model_level_sql`), `prompt_rules.py` (a prompt
worth reading, with `readable_sql`), `gallery.switch_counts` (what a gallery's
switches hide), `payload_rows.py` (a Civitai payload as rows),
`hashing.read_hashes` (stored hashes, either case), `forge_host.DEFAULTS` (a
setting's default), `tabs.py` (whether a tab is on), `model_dirs.held_here` (whether the library holds a file - with `library_files`, the one read behind it: three rules had grown, by row, by model and by file, #188). Each found a second copy that had already begun to
disagree - or, for the settings, thirty-odd that still agreed; tests hold the Python
to the SQL (`switch_counts_test`, `prompt_rules_test`, `model_level_test` -
every combination of a model's three ratings, #146) and registration to the
table (`forge_host_test`), and `check_hash_access.py` keeps readers on the
facade. What
the page must have before any answer could come, it keeps a copy of: the NSFW
levels, once (`nsfw.mjs`); the setting keys, where each is read.
`page_constants_test.py` holds both to the server's (#86).

**Everything the extension says, it says through `console.say`.** The sync's
log panel shows the console's lines from where the sync began - every one, a
gallery opened meanwhile included - so a `print` of its own would reach the
console and never the panel. The migrations keep theirs: they shipped so, and
run at startup. So does a failure's trace: `say_failure` says the message
and the trace as one line, from inside an `except` - `traceback.print_exc`
wrote it to stderr alone, at eleven places, and the panel showed only their
one-line errors (#143). `console_test.py` fails on a `print_exc` outside the migrations.

### The library: files, versions and rows

**A path is shown from where Forge was told to look.** Under a folder the
WebUI was given on the command line, by that option (`--lora-dir\x`); else
from the WebUI's own folder (`models\text_encoder\y`); else whole - the
other WebUI's file, in a folder this one was not given, which it cannot load
(`model_dirs.shown_roots`, `shownPath` in `ui_options.mjs`). Cut at
`\models\` alone, an embedding - not under it - showed its whole path, and
the other WebUI's file read as this one's.

**Deleting rows needs evidence.** Two kinds, and they are not equally safe.
*Direct*: this file was about to be refreshed and is not there, or another has
just been moved onto its path, where nothing was (`move_version`, #126) —
sound in any scope. *By diff*: these rows name files a walk never found —
sound only when the walk covered the whole disk, so it runs before any target
filter, never with an explicit path list, and never when the walk came back
empty (that is an unmounted drive, not an emptied library). And only for a
file that is not on disk (`model_dirs.gone_from_disk`): a walk looks for model
files in the library's folders, and a download can land elsewhere - a
wildcard's `.zip`, a folder template pointing outside. Every folder a download
files into is one the library walks; both come from one table in
`model_dirs.py`. A cancelled walk forgets nothing: Scan Disk once forgot every
file it had not reached, so a cancelled scan dropped the rest of the library.
What only the forgotten files named - models, images - goes with them
(`prune_orphans`), where Scan Disk left it orphaned.

### Civitai: sync and downloads

**Civitai is the source; a sidecar is written, not read.** A sync and a
download write `.civitai.info` beside a file, for other tools; nothing takes
from one what Civitai can say. A sidecar is read in one case: Civitai answers
404 for the file's SHA-256, no other hash finds it, and the model the sidecar
names is a 404 too - deleted, most likely (`SyncService._identify_by_sidecar`).
And "Civitai does not know" means a 404, never an error: an outage used to
mark every file looked up during it "not on Civitai", and every sync after
skipped them. An error on the SHA-256 is asked again at the sync's end; on a
later kind it counts as a miss. Another tool's `.cm-info.json` was asked
with until 0.53.6 (#140): its hashes filled the kinds the file's read
lacked - in the original Forge, which has no `blake3` package, its BLAKE3
for every file Civitai did not know - though 11 of 157 in one library were
another file's. Scan Disk read every sidecar as a source, and wrote its hashes as the
file's; it is gone (0.48.3), and the walk every sync from the dialog starts
with (`walk_library`) does the rest of what it did. A model's Sync and a
download's sync do not walk.

**A file's hashes are read once.** Stored with them is what the file was then
(`hashes_checked`: size and modified time to the nanosecond, never local
time, which a time zone moves). While the file is as it was, Civitai is asked
with them; a force sync reads every file again, and any sync reads again a
file changed since (`files_to_identify`). `force` and `rehash` are two
things: `force` skips the already-synced check, `rehash` reads the file again.
The dialog's Force sync passes both; a model's Sync, `force` alone. The mark
is written only with the hashes (`with_hashes`): a writer passing it alone is
ignored. A download's hashes carry it - Civitai's list, the bytes having
matched its SHA-256. Hashes written without the mark - a sidecar's, or stored
before v33 - are never trusted, and never make a file look changed: no
library has to be synced again for them. A read is for SHA-256 first
(`ModelHasher.calculate_first`), with AutoV1 and AutoV2, which come free;
AutoV3, BLAKE3 and CRC32 cost about as much again, and are read (`complete`)
only when none of those is known to Civitai, or Civitai's list for the file
does not say them. Found by its SHA-256, the file is Civitai's byte for byte,
and the list's other kinds are its own (`_adopt_listed_hashes`); found by
AutoV1 or AutoV2 it may not be. AutoV3 is needed whatever the lookup: images
name LoRAs by it - of 80 image hashes that matched a local file, 59 were
AutoV3, 9 AutoV2 and 12 Civitai's 12-character `sha256_12` / `sshs_12`, none
BLAKE3 or CRC32. Every kind up front ran at half the disk's speed (1.90
against 3.66 GB/s, four threads, NVMe).

**Civitai's model type is not the file's role.** A checkpoint model can ship a
VAE as one of its versions, and that file inherits "Checkpoint"; text encoders
arrive as "LORA", and a file Civitai does not know has no type at all. So the
file is asked: `file_identity.py` reads its tensor names and shapes, and the
Type filter uses that, falling back to Civitai's type only for a file no sync
has read yet. The folder was once used as a guess; removing it exposed two
bugs it had been hiding - a sidecar format read wrongly, and a scan that died
on one bad file. A fallback can hide a bug. A download's folder is chosen
before the file exists, so from Civitai's type; once it has arrived its header
is read, and a file of another type is moved to that type's folder
(`_file_by_what_it_is`) - never over a file. Files already in another type's
folder are listed in the sync dialog and moved only when its own box is
ticked - never by a note's button, which ticks "Read every file's header
again" - with their row, pin and generations (`move_version`), or put back
when the row cannot follow (#126). A Checkpoint is moved only when Forge's
detector took it (`model_dirs.filed_as`): one known by its layer names alone
is something UNet-shaped Forge did not take, which it could not load from
Stable-diffusion either - a ControlNet was, and is now told first (#118).

**A model's version list is Civitai's, as of the last sync.**
`models.versions` holds every version Civitai lists, local or not, so
the details panel can offer the rest for download without asking Civitai. A
sync replaces it; a sidecar only adds to it, and not at all once a sync has
written it - a sidecar is as old as its file, and would bring back a version
Civitai deleted. A library synced before the column existed has it asked of
Civitai the first time the panel asks.

**A refresh replaces a gallery whole, as many images as it is asked for.**
A model's Sync button, the metadata sync "with images" and a force sync
fetch either the first page (the gallery page size) or as many images as
the version has stored - the person chooses, told what each costs and how
many stored images the first would delete (#103; `refresh_size`,
`fetch_gallery`) - and replace every stored image of the version with them,
in one transaction (`db.replace_first_page`): Civitai's order changes, so old
pages kept beside a fresh first one would duplicate and leave gaps. Pages past
what was fetched come again when someone pages there. A download's sync takes
the first page: nothing is stored to keep.

**What Civitai fails on during a sync is tried again at its end, patiently.**
A model's details are stored before its gallery is fetched, so a gallery
Civitai cannot serve costs only the gallery - 21 files of one force sync had
kept their old details and levels when it cost both. Once every file has had
its turn, what failed is asked again under `CivitaiClient.patiently()` - six
retries, waiting 2, 4, 8, 8, 8 and 8 seconds, on that thread alone: the whole
model where Civitai could not say what the file is, its images alone where
only they failed (`SyncResult.civitai_failed`, `.images_error`). What fails
the second time is an error, and a gallery that failed keeps the stored one.
A refused key is never asked again: it would refuse again. A metadata sync
tries again only its galleries; a models fetch that fails is not tried again.

**A version's stored NSFW level is Civitai's rating** - or, for a model
Civitai no longer has, its sidecar's rating for the version. Scan Disk stored
the higher of that and the worst showcase image, so the level meant two
things (#104); rows it wrote keep that until a sync refreshes them. The grid
judges live from the model, the version and the worst stored image
(`nsfw.model_level_sql`), so it is right either way.

**A long job is one of its kind, in `jobs.py`.** A sync (full or metadata)
and a restamp of stored image levels each run one at a time; what the
page polls is the service's own progress, and a job that raises calls
`fail()` on it. It used to write the error where the poll never read, and the
job showed as running for ever. A restamp asked for while one runs is not
refused but run once more after (`again`): a settings save made meanwhile has
words the running pass did not see. And a long job says on the page what it
is doing as it does it - the console's lines in a log, a count while it has
no total, what a cancel still waits for, errors, and how it ended - never a
"0/0" or a silent wait (0.48.5).

**The download queue is the service's own.** `DownloadService` runs as many
as the setting says (Downloads at once, 2 unless changed, #279) - a change
applies at once, and a lower number stops nothing - and when a place frees up
starts the first waiting one from the top; Start now runs one over the limit.
A version asked for again while on its way - queued, coming, being added,
paused - is answered with the download it has, never
started over (`ON_ITS_WAY`); a finished one is queued afresh. The page keeps
the same rule (`onItsWay` in `downloads.mjs`): a Resources row or a chip for
a version already coming follows it, and asks nothing (#119). Pause keeps the `.partial` and frees the place;
Resume asks Civitai's download address again (its storage link is signed and
expires) with `Range: bytes=<size>-`, carries the SHA-256 on from what is
there, and checks the finished file as ever. What is not over - running,
paused or waiting - is kept in the `downloads` table, one row each in the
list's order, under this install's key (`INSTALL_KEY`): a restart or a crash
leaves it paused, and a WebUI sharing the database never takes it up. Each
save replaces the install's rows whole (`_save`), so the table cannot miss a
change: from 0.43.0 (7a01e81) only a download with a `.partial` was kept, in
`schema_info`, and a restart forgot every one still waiting (#187). A kept
download whose file the library has by then - its Civitai file id, on disk,
in this WebUI's folders (`_held`) - is not brought back, and a resumed one is
asked again before anything is fetched. Never by its version alone: a
version's other file is not this one.

**A Download that names its model and version is queued by its ids** (0.59.2,
#223) - the job a restart brings back - and Civitai is asked at its turn
(`_fetch_job`): paid, no file and gone are Error rows there, with Retry,
which waits again at the end of the queue and asks afresh. Asking first cost
each press 333 to 484 ms, median 416: ten queued in 4.2 s, now 129 ms. Only
the Resources dialog's `newer_if_gone`, and a version without its model,
still ask first: the page follows a row by its version id, and a substitute's
is known only once Civitai answers. The library check alone stays at the
press - it reads the database. While its turn fetches, 0.3 to 0.7 s, a
running download still reads `pending`, with no place in the queue: its row
says "Waiting...".

### The page

**A gallery switch's number holds when it is flipped.** An image both the NSFW
and the prompt filter hide is counted apart (`hidden_both`), not credited to
either: credited to NSFW, "Show NSFW" said 51 while hiding and 49 once ticked.
The NSFW switch says what it alone hides; the prompt switch every image with an
unusable prompt (`promptless_total`). The database's counts, a page's, the
Civitai Browser's and your generations' are kept to the same meanings.

### Your generations

**A generation's result is known by the object Forge hands every script.**
`postprocess_image_after_composite` gives each script the same
`PostprocessImageArgs`, and Forge saves the image it holds once they are all
done - not necessarily the image our hook saw: forge-helpers' hires cap
replaces it. So the object is kept, and a save matched to it in
`on_image_saved`. Masks, grids, ControlNet's maps and the "before" copies
never match. The prompts are read in `before_process`, before styles are
merged and Dynamic Prompts overwrites `p.prompt`; the LoRAs per iteration,
since Forge loads only the first prompt's for a whole batch. Nothing is
recorded when Forge saved nothing ("Always save all generated images" off),
or for a video (#8). See `model_manager/generations.py`.

**A synced image is the recorder's second witness** (#233, v38). Sync images
reads what Forge wrote into the file, so a synced generation has a
`source_id` and lacks what only the recorder sees - the script arguments,
the inputs. The recorder wins: saving a file a sync holds replaces the
synced row. The presses are rebuilt by settings alike, seed +1 and running
number +1: 630 of 630 recorded generations came out exactly. A delete that
keeps the file puts it on `generation_images_removed`, with its size and time, or the
next sync brings it back. A checkpoint the library lacks is kept by its
name, a resource row with no path: Send stops on it and opens Resources.
A sync skips every image it holds, so a fix to reading or matching reaches
old images only through Force sync ("Read every image again", #246): each
chunk's synced rows are rebuilt in one transaction, and what the person
added is carried over by path - a rating, and the level an image without
infotext got at its first sync - while what came from the image is
replaced. A file name is read back by *this* WebUI's naming settings: a
folder named by another WebUI's joined none of its 12,871 images without
infotext, where the WebUI that saved them joined them into 639 (#247). An
image without infotext has nothing for Send to paste: its Send is disabled,
saying why - it was enabled, and did nothing.

**A thumbnail belongs to its image's path, never its id** (#5, v39). Force
sync and the recorder write an image's row anew, with a new id; the path
stays, so `generation_thumbnails` is keyed by it, and a thumbnail survives both.
Its row holds the image's size and time when it was made: a changed image
is offered its full file until a sync makes it again. A thumbnail goes only
with the last row naming its path - every removal the app makes calls
`thumbnails.forget` with the paths a delete hands back. Nothing is made
unasked: a sync makes them when its box is ticked, the recorder only with
the setting on.

## Two WebUIs: everything has to work in both

- **No `blake3` package in the original Forge.** BLAKE3 is never read there
  (`hashing.BLAKE3_AVAILABLE`): a file's BLAKE3 comes from Neo, or from
  Civitai's list once the file is found. Until #140 another tool's
  `.cm-info.json` BLAKE3 was asked of Civitai in its place.
- **The detector's helpers moved.** Neo keeps `convert_diffusers_mmdit` in
  `modules_forge.packages.comfy.utils`, the original Forge in
  `huggingface_guess.detection`. Asking only Neo's place failed there, the
  failure was caught as "not recognised", and every checkpoint scanned in the
  original Forge was stored as unknown - for Neo too, since they share a
  database. `forge_host.diffusers_converter` tries both.

**A shared library holds the other WebUI's files.** Its sync files them in
the same `files`; this WebUI may not have been given their folders and
cannot load them. Anything that acts on a file - Send's choice of a version's
file, the chips' "in library" - takes one in this WebUI's folders
(`model_dirs.folder_of`; the chips by `lora_folders`, the folders Forge loads
LoRAs from); anything that shows one says whose it is (a whole path).

## Known gaps

- **Local-only models cannot be bookmarked.** They have a row now, but
  bookmarking is keyed on a `models` id and they have none. They can be
  pinned: a pin names the file's path.
- **They also show as blank cards** — the grid takes previews only from the
  cached Civitai images, and never looks at the `.preview.png` beside the file,
  though the delete path knows about it.
- **`checkpointType` is only known for models Civitai still serves.** Anything
  delisted stays Unknown; nothing can recover it.
- Usage history and manual collections are unimplemented.
- **Sort by "Scanned At" means first found or last synced.** Scan Disk stamped
  every row at each scan (`scanned_at`); the walk stamps nothing.

## Learned the hard way

### The data

- **Civitai's labels are the uploader's.** VAEs and text encoders filed as
  "Checkpoint" or "LORA"; SDXL files labelled Anima; an image's `baseModel` is
  every resource's base model run together ("OtherAnima"); versions get
  deleted and 404; other tools write the version payload into `.civitai.info`
  instead of the model payload (`storage.as_model_payload`).
- **The file is the reliable witness.** Tensor names and shapes identified
  1,254 of a 1,262-file library; the rest were families Forge Neo cannot run.
- **A rule measured on one library knows only what it holds.** That library
  had no ControlNets, and its folder was not walked until 0.44.1: a ControlNet
  - shaped like the UNet it steers, refused by Forge's checkpoint detector -
  read as a bare diffusion model, and from 0.44.10 a download of one was
  moved into Stable-diffusion (#118). Found by comparing the code before and
  after the 0.44 round, not by any suite. Twelve of nineteen published
  ControlNet-folder files were taken for checkpoints; their headers are now
  a fixture (`tests/controlnet_headers.json.gz`).
- **A model trained on a library forgives that library's mistakes.** Trained on every
  image, the NSFW prompt model raised 25 of the library's 33,730 PG/PG-13 images at the
  "2%" setting, not 670: it had learned the under-rated explicit ones as PG. Out-of-fold
  scores (each image by a model that never saw its post) showed the real behaviour, and
  leaving the ones they flag out of the final training fixed it - 669 raised. Measure a
  model on its own training data before believing a number it gives there.
- **Civitai's storage now and then ignores a byte range.** With an API key, 1
  of 8 resumes got the whole file (`200`) where the rest was asked for; asked
  again, through a fresh redirect, it answers `206`. A resume asks up to three
  times before starting over.
- **Images key their hashes in either case.** `hashes` holds `"lora:name"` and
  `"LORA:name"` (5,561 of one library's keys, and 35 `"EMBED:"`); reading the
  first only lost those hashes, and a LoRA came out as two chips.
- **Civitai's image ratings miss some.** 256 of 31,745 PG/PG-13 images in one
  library had explicit prompts; Civitai rates 95% of the images using those
  words X or XXX.
- **Civitai's CRC32 is not always in zlib's byte order.** For `supe10` its list
  gives `8EAD4C97` where zlib gives `974CAD8E` (2 of 1,190 files compared; the
  other one's sidecar was another tool's). A CRC32 lookup misses such a file;
  SHA-256 finds it.
- **A version Civitai allows only for generating on its site says so in
  one place.** Its `usageControl` comes with `/model-versions/{id}` and the
  by-hash lookup, not with a search or `/models/{id}`; any value but
  `Download` makes its download answer 401, "The creator of this asset has
  disabled downloads on this file". Our 401 branch
  (`download_service.py`, since 2220995) blamed a missing API key whatever
  Civitai said (#224). A sample of about 2,000 versions found none to test
  with (#226).

### The code

- **An import inside a function hides a cycle; it does not break it.**
  `architecture` imported `file_identity` that way while `file_identity`
  imported it at the top: one moved line from failing at startup. The cut was
  in the wrong place - the database part sat in the header reader - and
  `tests/tools/check_import_cycles.py` now counts every import, wherever it is.
- **A bool is an int.** An enum checked `isinstance(value, int)` before
  `bool`, so a model's `nsfw: true` read as bitmask 1 - PG - and its own
  branch for booleans never ran. Test for `bool` first.
- **Forge Neo:** T5 and UMT5 files load only in Hugging Face's layout; switching
  a UI preset brings back that preset's checkpoint; Flux.1 and Flux.2 share
  block names and differ in MLP width, which a LoRA's shapes show. It lists
  VAEs and text encoders by file name (`refresh_models`,
  `modules_forge/main_entry.py`): a name in two folders shows once. It writes
  `Module N` as the file's stem, untrimmed, and its parser strips the value:
  `sdxl-vae-fp16-fix .safetensors` became `sdxl-vae-fp16-fix`, which matched
  nothing - Neo's own paste misses it too - and 9 synced generations lost
  their VAE until names were compared trimmed (#246).

### The environment

- To run Neo's detector outside the WebUI, put Neo's root and its
  `modules_forge/packages` on `sys.path`: with the packages alone, every
  checkpoint came out without a class.

## Kept elsewhere, and true here too

Rules whose main code is in another folder, which this folder's code must
keep as well:

- `model_manager/db/AGENTS.md`, "A version is one row; its files are rows of
  their own".
- `model_manager/db/AGENTS.md`, "A file is known by its path".
- `model_manager/db/AGENTS.md`, "Absent is not empty".
- `model_manager/db/AGENTS.md`, "Forge and the library spell one path two
  ways".
- `model_manager/civitai/AGENTS.md`, "`checkpointType` is inferred, not read".
- `model_manager/civitai/AGENTS.md`, "Civitai's `nsfw` search parameter has two
  states".
- `javascript/AGENTS.md`, "Markup names what it does, the same way".
- `javascript/shared/AGENTS.md`, "A gallery's Send sets up its own model
  first".
- `model_manager/api/AGENTS.md`, "A check in one route and an act in another
  race".
