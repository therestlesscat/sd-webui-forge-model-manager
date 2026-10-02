# Working on this extension

A model manager for SD WebUI Forge: it lists what is on disk, enriches it with
Civitai metadata, and lets you browse and download more.

This file is about the shape of the codebase — what each part is *for*, and
which of its rules were learned the hard way. It is not a file listing; `ls`
does that better.

## Layout

```
scripts/model_manager_ui.py   the entry point Forge loads
scripts/model_manager_generations.py
                              the always-on script that records your generations
model_manager/                the extension proper
javascript/                   the three tabs, and what they share
style.css                     picked up by filename; see "The WebUI's rules"
tests/                        see tests/README.md
tools/train_nsfw_model.py     trains the NSFW prompt model from a library, read-only
tools/train_nsfw_from_civitai.py, run_nsfw_training.sh
                              the same, from a pull of Civitai itself, paced at 5 req/s
```

### `model_manager/`

| | |
|---|---|
| `db/` | everything that touches SQLite. A facade (`database.py`) over one module per job: `models_ops`, `images_ops`, `generations_ops`, `query`, `migrations`; the grid's filters, sort and page travel as one `GridQuery` (`query.py`), read from the request once |
| `civitai/` | talking to Civitai: `client` (auth, rate limiting, retries), `prompt_filter`, `size_filter` (filtering a search by download size), `licensing` |
| `forge_host.py` | what the extension asks of the WebUI it runs in, and the one module that asks (with `ui/settings.py`, which registers the settings; `tests/tools/check_forge_imports.py`): its settings, with one table of their defaults (`DEFAULTS`) that registration and every read take; Forge's options, folders, checkpoints, modules, presets and samplers; which Forge it is, and where Neo and the original Forge keep a thing apart |
| `sync_service.py` | identifying files and refreshing their metadata |
| `sync_estimates.py` | what a sync would cost and cover, before it starts: the sync dialog's request estimate and its staleness-window counts |
| `scan_service.py` | reading the disk and the sidecars beside it |
| `model_dirs.py` | where models live: one table of the folders a scan walks and a download files into, when a walk may forget a row, and where a file of each type belongs |
| `jobs.py` | the long jobs - a sync, a scan, a restamp of image levels - one of each kind at a time: which runs, its progress, and a failure reported on it |
| `download_service.py` | fetching a model and filing it: its own queue, pause and resume, and what to resume after a restart |
| `hashing.py` | the hashes that tell Civitai which file this is, and how stored ones are read: `read_hashes` / `hash_key` fold either case, and `tests/tools/check_hash_access.py` keeps every reader on them |
| `nsfw.py` | how explicit something is — **the only place that decides**, the prompt words and the prompt model included |
| `prompt_rules.py` | what a prompt is worth - worth reading, enough to make the image again - for Python and the SQL that filters and counts with it alike |
| `prompt_levels.py` | restamping stored image levels when the prompt words change |
| `generations.py` | recording the images you generate: what each of Forge's hooks can see, and when |
| `file_identity.py` | what a file is (Checkpoint, LORA, LoCon, VAE, Text Encoder, ...) and which model it is for, from its own tensors; a text encoder's or VAE's kind, which `forge_modules` picks by |
| `identity_store.py` | what `file_identity` found, kept on the file's row, and when a file has to be read again |
| `architecture.py` | reading headers (safetensors, GGUF, and pickles without running them) and asking Forge's detector about checkpoints |
| `forge_modules.py` | the text encoders and VAE a model needs, picked from what Forge offers |
| `send_plan.py` | which model Send to txt2img sets Forge up for |
| `resources.py` | which local file, or which version on Civitai, an image's resources are: for the chips under a prompt (the library alone, and Forge's rule for which file `<lora:name>` loads), the Resources dialog, and what a missing one will be called once downloaded |
| `payload_rows.py` | what a Civitai payload says about a model and a version, as database rows - for the scan and both kinds of sync alike |
| `storage.py` | reading and writing `.civitai.info` |
| `update_check.py` | whether a newer version is out: `version.json` read from GitHub, on this copy's branch, every 12 hours unless turned off |
| `release_notes.py` | notes to the user per release - what is new, what to do after updating: which an install sees, and dismissing them |
| `models.py` | the data classes `storage.py` reads `.civitai.info` into |
| `remembered.py` | answers kept in memory - Civitai's about versions, file hashes, SFW verdicts, versions an account bought: a map with a bound, under a lock; how old an answer may be stays its caller's |
| `data/` | files that ship with the code: `nsfw_prompt_words.txt`, the bundled prompt words, and `nsfw_prompt_model.json.gz`, the prompt model, trained from a pull of Civitai by `tools/train_nsfw_from_civitai.py`; `release_notes.json`, the notes to the user |
| `api/` | the HTTP endpoints, one module per area, each with `register(app)`: `models`, `images`, `generations` (your own images: a model's gallery of them, and the Generations tab), `jobs`, `civitai`, `webui`, `settings` (the settings window's), `notes` (notes to the user). Beside them, two helpers the Civitai endpoints use: `annotations` (marking up search results with what the library holds) and `prompts` (whether a model's images are worth opening) |
| `ui/` | settings, and the markup for each tab: Generations, Model Manager, Civitai Browser, in that order |

### `javascript/shared/`

What the tabs share, one module per job (#93), each asked for under one
version (see "The WebUI's rules"):

| | |
|---|---|
| `calls` | what one part of the page offers the rest, by name: `provide`, `ready`, `call` |
| `tabs` | the WebUI's tabs by id: `showTab` (resolves once Gradio shows it), `tabButton`, `tabShowing` |
| `core` | what every part uses: `TIMING`, `apiCall`, `escapeHtml` (the one escape), `setText` / `setTitle`, `safeId` / `safeUrl`, `sanitizeHtml`; numbers, sizes and dates as a person reads them |
| `ui_options` | the server's ui-options, asked once a page: the API-key banner, which judges NSFW, how a gallery opens, whether your generations are shown |
| `notes` | notes to the user, at the top of each tab |
| `jobs` | the long jobs, Sync with Civitai and Scan Disk: their dialogs, starting, following and cancelling one, and finding one still running; the Model Manager connects them to its status line and grid (`connectJobs`), a note's button opens them (`showSyncDialog`, `showScanDialog`) |
| `update_notice` | "vX available" beside each tab's version |
| `nsfw` | an image's level as the server stamped it, its badge, and the levels one can rate |
| `media` | Civitai's images and videos: the copy for a width, the fallback, loading them as they come into view |
| `grid` | cards, the grid and its page strip, its rows kept even, and the card size the server gave a tab (`createCardSize`) |
| `image_card` | a Civitai image's card and its Show All window, the same in both tabs; your generations' cards show its text |
| `samplers` | Forge's samplers and schedulers, from the one ui-options answer, and an image's sampler text read by them |
| `gallery` | a gallery's loading bar, filter banner and page notes, and its pages - kept, drawn and paged through by one object per gallery (`createPagedGallery`), each tab keeping only how it fetches a page; and scrolling to a gallery's top |
| `filters` | what both filter bars share: base models in order, the size boxes, a saved search and Save Search's flash, the checkpoint-type filter greyed while Type is not Checkpoint |
| `generations` | your generations, as a model's gallery and the Generations tab both show them: a thumbnail, the rating and delete requests, a shift-click's range, the select bar and bulk delete, the rating row. Each tab draws its own cards or tiles |
| `downloads` | a version's Download button, and the downloads panel both tabs show |
| `send` | Send to txt2img / img2img, from any tab: Forge's VAE / Text Encoder control, its UI preset and the server's send plan, samplers, the infotext and the paste, an image-to-video model's start frame (`sendGalleryImage`, `sendInfotext`) |
| `chips` | an image's LoRAs and embeddings as chips under the prompt, after a send: their rules, and the chips on the page |
| `resources` | an image's resources and the Resources dialog every gallery opens, each passing the version its gallery is of (`exclude`): which Civitai versions they are, whether the library has each, and a Download into it - through the downloads list, which polls for it, as for every download |
| `wan` | a video's frames and size as Wan makes them |
| `settings`, `viewer` | the settings window, and the image viewer every gallery opens - with the modal the metadata and Resources windows open in |

## What the pieces assume about each other

**A generation's result is known by the object Forge hands every script.**
`postprocess_image_after_composite` gives each script the same
`PostprocessImageArgs`, and Forge saves the image it holds once they are all
done - not necessarily the image our hook saw: forge-helpers' hires cap
replaces it. So the object is kept, and a save matched to it in
`on_image_saved`. Masks, grids, ControlNet's maps and the "before" copies
never match. The prompts are read in `before_process`, before styles are
merged and Dynamic Prompts overwrites `p.prompt`; the LoRAs per iteration,
since Forge loads only the first prompt's for a whole batch. See
`model_manager/generations.py`.

**`nsfw.py` is the single source of truth.** There were once three
implementations giving two different answers. If you need a level, ask it; if
the rule is wrong, it is wrong in one place. The browser does not judge: every
image it is sent passes through the server, which stamps `mm_level` (and
`mm_level_from_prompt`, for the "X · prompt" badge) on it with
`nsfw.stamp_levels()`, and the page reads that. It used to keep a copy of the
rule in `common.mjs`, fed by the words fetched from the server - two
implementations to keep in step. A new endpoint that hands images to the page
stamps them too; an image without a stamp reads as Unknown, and is hidden.

**Absent is not empty.** Both `upsert_version` and `upsert_civitai_model` keep
what they hold when handed `NULL`, `'[]'`, `0` or Unknown. A scan reading a
thin `.civitai.info` cannot tell "this model has no trigger words" from "this
file does not mention any", and it used to write the second over the first —
blanking trigger words, dates, licences, vote counts and stored hashes. Both
are generated from one list per table (`MODEL_COLUMNS`, `VERSION_COLUMNS` in
`db/models_ops.py`), each column with how an update treats it - overwritten,
kept when the new value says nothing, or a rule of its own - and given its
value by name. Adding a column means an entry there, or in the list of
columns written elsewhere; `upsert_columns_test.py` fails on one in neither.
It used to be four places by hand, and a column missed from the `SET` list
was written once and never updated.

**A model's version list is Civitai's, as of the last sync.**
`civitai_models.versions` holds every version Civitai lists, local or not, so
the details panel can offer the rest for download without asking Civitai. A
sync replaces it; a sidecar only adds to it, and not at all once a sync has
written it - a sidecar is as old as its file, and would bring back a version
Civitai deleted. A library synced before the column existed is filled from a
sidecar the first time the panel asks.

**Calls between files go through `shared/calls.mjs`.** A tab that offers
something to the others - the Model Manager's `modelManager.showModel`, the
settings window's `settings.open`, a tab's `cardPreview.<setting key>` -
provides it by name; the others `call` it, and ask `ready` first where they
tell the user that tab has not loaded. They reached each other through window
globals (`window.mmShowModel`), and a caller found out what was missing its
own way, or not at all. What markup calls stays on `window` - an inline
handler reaches only globals - and is the tab's own: `check_js_references.mjs`
fails on a file that reads another's window global, and on a call to a name
nothing provides. Events stay window events (`mm-settings-saved` and three
more).

**One downloads list for both tabs.** `downloads()` in
`javascript/shared/downloads.mjs` polls once and draws into each tab's panel. It
is module state: the tabs share one copy of the module (see "The WebUI's
rules"), and so do the notes, the update notice, the Your generations switch
and the settings window - none of them on `window` since #93. The list's order is the server's - the order downloads were added in, which ↑/↓
change - and a state never moves a row; the page keeps that order apart
(`sequence`), as an object's number keys come out sorted. It asks for the list
when the page loads, and draws it again once Gradio has drawn the panel: a
paused download polls nothing, and the panel used to stay hidden after a
restart.

**The download queue is the service's own.** `DownloadService` runs up to two,
and when a place frees up starts the first waiting one from the top; Start now
runs one over the limit. Pause keeps the `.partial` and frees the place;
Resume asks Civitai's download address again (its storage link is signed and
expires) with `Range: bytes=<size>-`, carries the SHA-256 on from what is
there, and checks the finished file as ever. What is running or paused is kept
in `schema_info` under a key for this install (`RESUMABLE_KEY`), so a restart
or a crash leaves it paused, and a WebUI sharing the database never takes it
up.

**A gallery switch's number holds when it is flipped.** An image both the NSFW
and the prompt filter hide is counted apart (`hidden_both`), not credited to
either: credited to NSFW, "Show NSFW" said 51 while hiding and 49 once ticked.
The NSFW switch says what it alone hides; the prompt switch every image with an
unusable prompt (`promptless_total`). The database's counts, a page's, the
Civitai Browser's and your generations' are kept to the same meanings.

**A card shows one version, chosen in one fixed order:** newest published, then
Civitai's own order (`index` in `civitai_models.versions`, whose first its page
shows), then version id and file (`SHOWN_ORDER` in `db/query.py`). Versions
share a date to the millisecond, or have none; without the tie-break SQLite
returned either, and a cover changed between loads. Anything that picks one of
several needs an order that cannot tie.

**Deleting rows needs evidence.** Two kinds, and they are not equally safe.
*Direct*: this file was about to be refreshed and is not there — sound in any
scope. *By diff*: these rows name files a walk never found — sound only when
the walk covered the whole disk, so it runs before any target filter, never
with an explicit path list, and never when the walk came back empty (that is an
unmounted drive, not an emptied library). And only for a file that is not on
disk (`model_dirs.gone_from_disk`): a walk looks for model files in the
library's folders, and a download can land elsewhere - a wildcard's `.zip`, a
folder template pointing outside. Every folder a download files into is one
the library walks; both come from one table in `model_dirs.py`.

**Civitai's model type is not the file's role.** A checkpoint model can ship a
VAE as one of its versions, and that file inherits "Checkpoint"; text encoders
arrive as "LORA", and a file Civitai does not know has no type at all. So the
file is asked: `file_identity.py` reads its tensor names and shapes, and the
Type filter uses that, falling back to Civitai's type only for a file no scan
has read yet. The folder was once used as a guess; removing it exposed two
bugs it had been hiding. A download's folder is chosen before the file exists,
so from Civitai's type; once it has arrived its header is read, and a file of
another type is moved to that type's folder (`_file_by_what_it_is`) - never
over a file. Files already in another type's folder are listed in Scan Disk's
dialog and moved only when its own box is ticked - never by a note's button,
which ticks "Re-evaluate file headers" - with their row, pin and generations
(`move_version`).

**`checkpointType` is inferred, not read.** Civitai accepts it as a filter and
returns it on neither the model nor the version. `get_checkpoint_types()` asks
which ids are Trained, then which are Merge, and takes the answer from set
membership — discarding any batch whose answer does not partition the request,
because that would mean the assumption no longer holds.

**A refresh replaces a gallery with Civitai's first page.** Resync Images, a
sync of one model and the metadata sync "with images" fetch one batch (the
gallery page size, 100) and replace every stored image of the version with it,
in one transaction (`db.replace_first_page`): Civitai's order changes, so old
pages kept beside a fresh first one would duplicate and leave gaps. Pages past
the first are fetched again when someone pages there. #103 asks a refresh to
keep as many images as the gallery had.

**A version's stored NSFW level means two things.** After a sync it is
Civitai's rating; after Scan Disk, which stores no images, the higher of that
and the worst showcase image (`ScanService._calculate_nsfw_level`). The grid
judges live from the model, the version and the worst stored image
(`nsfw.model_level_sql`), so it is right either way; the details panel's
"Version:" row is not consistent. #104.

**A long job is one of its kind, in `jobs.py`.** A sync (full or metadata), a
scan and a restamp of stored image levels each run one at a time; what the
page polls is the service's own progress, and a job that raises calls
`fail()` on it. It used to write the error where the poll never read, and the
job showed as running for ever. A restamp asked for while one runs is not
refused but run once more after (`again`): a settings save made meanwhile has
words the running pass did not see.

**A migration does not import today's rules.** v14 once imported the live
`nsfw.image_level`, which later learnt to read the person's settings: it
applied a rule it was not written with, during startup, and renaming the
function would have broken every older database. It carries a frozen copy.
An index is a migration too (v30), versioned like any other - and harmless to
an older copy sharing the database, which never touches it.

**Two rules for one thing drift, so each lives once, its SQL beside it.**
`nsfw.py` (a level, with `model_level_sql`), `prompt_rules.py` (a prompt
worth reading, with `readable_sql`), `gallery.switch_counts` (what a gallery's
switches hide), `payload_rows.py` (a Civitai payload as rows),
`hashing.read_hashes` (stored hashes, either case), `forge_host.DEFAULTS` (a
setting's default). Each found a second copy that had already begun to
disagree - or, for the settings, thirty-odd that still agreed; tests hold the Python
to the SQL (`switch_counts_test`, `prompt_rules_test`) and registration to the
table (`forge_host_test`), and `check_hash_access.py` keeps readers on the
facade.

## The WebUI's rules, which are not obvious

- `javascript/*.js` become classic scripts, `*.mjs` become
  `<script type="module">`, **in filename order**. Subdirectories are not
  scanned: `list_scripts` uses `os.listdir`.
- `style.css` is found by name and concatenated with every other extension's.
- Both are stamped with the file's mtime **once, at startup**, so a change
  needs a WebUI restart to reach the browser — not just a page reload.
- Nothing in the WebUI versions `javascript/shared/`, and Gradio's file route
  sends no `Cache-Control`, so a browser may keep a copy without asking. A
  plain import resolves to a URL that never changes, and a newly exported name
  becomes a link error that kills the entire tab. The tabs used their own
  `?mtime` - which stayed the same when only a shared file changed (15 of 60
  releases that touched shared/). They now ask `/model-manager/asset-version`
  for the newest mtime among the shared files, once a page (`window.
  mmSharedVersion`), and import every shared module with it: one URL, so each
  shared module also **runs once**, not once per tab. Without an answer, the
  tab's own version, as before - then one copy per tab, page state included.
  A shared module that needs another imports it the same way, under its own
  `import.meta.url`'s version. Both go through one line, `const shared =
  (name) => import(...)`, and `await shared('core.mjs')`: a plain `import` is
  a URL without the version, and a second copy (`page_state_test.mjs` records
  every URL a shared module is asked for under, and fails on a second).
  `check_js_references.mjs` holds what is taken through it to what the module
  exports. A tab asks for every module it needs at once (`SHARED_MODULES`),
  then awaits each: awaited in turn, each module waited a round trip before
  the next was asked for. The check holds the list to the awaits.
- Gradio re-renders a `gr.HTML` block wholesale, and inline styles set on
  anything inside it do not survive. Anything set from script has to be
  reasserted from `onAfterUiUpdate`.
- **A tab is found by its id, never its label or place.** Gradio 4 gives a
  tab's panel the id it registers with (`tab_<id>`: `tab_txt2img`,
  `tab_model_manager_tab`) and its button that id and `-button`, the same in
  both WebUIs. Labels are translated by a localization and the tab bar can be
  reordered; the label lookups and "img2img is the second button" broke on
  both. Gradio shows a tab by setting its panel's display as it draws, and a
  hidden tab's grid measures nothing: `showTab` (`shared/tabs.mjs`) resolves
  once the panel shows, where a fixed 100 ms wait searched a hidden tab on a
  slow machine. A tab asked to show a model switches to itself and waits; the
  caller only calls.
- **Gradio draws the tabs after the scripts have run.** A module's top level
  finds none of its tab's markup; something drawn from there - an answer that
  comes back at load - is drawn again once the container is there, from
  `onAfterUiUpdate` (the downloads panel, the notes).
- **Settings -> Reload UI runs the scripts again in the same process**, with
  the extension already imported, after clearing every callback; Extensions
  -> Apply and restart UI is a new process. So every callback is registered
  by the script (`scripts/model_manager_ui.py` registers the API's
  `app_started` itself), never at import - and nothing deletes the extension's
  modules to "reload" them: that once left two copies running, the recording
  script and the settings on one, the API on the other. Edited Python needs a
  real restart, as the scripts and the stylesheet do.
- **`onAfterUiUpdate` runs 250 ms after any change to the page**
  (`scheduleAfterUiUpdateCallbacks` in the WebUI's `script.js`). A callback
  that writes even the same text again changes the page and schedules itself:
  four of ours did, and every extension's callbacks ran four times a second,
  without end. Write only what differs - `setText` / `setTitle` in
  `core.mjs` - and `quiet_updates_test.mjs` finds any that does not.

## Two WebUIs: everything has to work in both

The extension runs in **Forge Neo** and in **the original Forge**
(lllyasviel's, installed at `F:\webui_forge_cu121_torch231`: Python 3.10.6,
Gradio 4.40.0, torch 2.3.1). Everything should work in both. A feature one of
them lacks - Neo's newer presets, Wan video - is skipped there, never an
error, and never a wrong answer written to the database.

Where they differ, and what the extension does about it - on the server, in
`forge_host.py`, the one module that asks Forge anything:

- **Python 3.10 in the original Forge.** Nothing newer than 3.10 syntax or
  library. Check with that install's `system\python\python.exe`, compiling
  every file.
- **The detector's helpers moved.** Neo keeps `convert_diffusers_mmdit` in
  `modules_forge.packages.comfy.utils`, the original Forge in
  `huggingface_guess.detection`. Asking only Neo's place failed there, the
  failure was caught as "not recognised", and every checkpoint scanned in the
  original Forge was stored as unknown - for Neo too, since they share a
  database. `forge_host.diffusers_converter` tries both.
- **The UI preset control.** Neo's is a dropdown; the original Forge's a row
  of radio buttons (`sd`, `xl`, `flux`, `all`). `switchForgePreset`
  (`send.mjs`) presses the matching radio; typing into it as a dropdown
  cleared the first radio's value.
- **The VAE / Text Encoder control.** Neo's has the id `setting_sd_modules`;
  the original Forge's has none, and is found by its label. Every change to
  it is a request of Forge's own carrying the whole selection, and they can
  land out of order: after a clear-and-reselect, Neo sometimes loaded an
  Anima model with no VAE while the control showed it. So Send patches it -
  takes out only what is extra, adds only what is missing, touches nothing
  when nothing differs - and then asks the server what Forge's setting
  (`forge_additional_modules`) actually holds.

**They can share one database** (Settings -> Model Manager -> database
path), and do here: Neo's setting points at the file in the original Forge's
copy of the extension. The two copies of the extension must then be at the
same version. An older copy does not migrate a newer database - it runs its
old queries and writes against the newer schema, without the fixes since.
Update both before starting either.

To see the original Forge's behaviour without starting it, run the code under
its Python with its packages on `sys.path` (`webui`,
`webui\repositories\huggingface_guess`, `webui\packages_3rdparty`): that is
how the detector break was reproduced, and the fix shown to work on real SDXL,
Flux and SD 1.5 files.

## One stylesheet, one definition

Both tabs share `style.css`, and both draw the same things: a filter bar, a
grid of cards, a details panel, a pagination strip, buttons. They were built
separately, each with its own class prefix, so for a long time each of those
had two definitions.

They drifted, and the drift was expensive. The Civitai Browser carried a
parallel filter bar scoped to `.cb-filters` — the row, the group, the label,
the bordered box, the control box — at the same specificity as the shared
rules and later in the file, so every one of them won. Fixing the shared rule
changed nothing in that tab, twice in a row, and the cause was invisible from
the rule being edited.

So:

- **A component is defined once.** If both tabs draw it, one rule names both
  classes: `.mm-btn, .cb-btn { ... }`. Do not scope a copy to a tab.
- **A `cb-` or `mm-` class is for something only that tab has** — the
  browser's downloads panel, the manager's sync dialog. Not for a variation on
  something shared, nor for a state both have: a disabled filter is
  `.filter-disabled` in either (#84).
- **A tab that needs a variation extends the shared rule**, with a modifier
  class and a variable where there is one (`--mm-btn-height`, `--mm-btn-bg`),
  rather than restating the box.
- **State what decides a box; never let it be derived.** A `<select>`, an
  `<input>` and a `<div>` compute three different heights from the same
  padding, and Gradio's preflight resets `margin` and `background` on every
  button inside a `gr.HTML` block at a specificity one class cannot beat.

`tests/py/css_test.py` fails when a `cb-` rule and an `mm-` rule say the same
thing, so the next component that would have been copied has to be shared.

## Conventions

- Comments explain **why**, not what. If a line needs saying twice, the second
  one is not a comment.
- A commit message says what was wrong and what it now does, with the numbers
  that justify it.
- Tests assert what the code does, never what someone's library happens to
  contain. Four suites had to be fixed for exactly this.

## Versions

`MAJOR.MINOR.PATCH.BUILD`, as `model_manager/version.py` explains. The build
is the commit's place in the history and is never written down; the rest is.

**Before each commit**, decide which it is:

- **A minor version**: a feature that means something on its own, even inside
  an existing tab - the settings window, the trained NSFW model. Bump MINOR,
  PATCH to 0.
- **A patch**: any other change a user can see - a fix, an improvement, an
  addition to the latest feature or to any other. Bump PATCH. A patch belongs
  to no feature; it only comes after the latest minor version.
- **Neither**: tests, docs, refactoring - nothing a user sees. No bump; the
  build moves on by itself, and the changelog does not list it.
- **A major version** is the owner's call, when the extension is ready.

Then, in the same commit:

1. `VERSION` in `model_manager/version.py`, and the same in `version.json` at
   the root: installs read that file from GitHub to learn a newer version is
   out (`model_manager/update_check.py`), so it has to say the version the
   branch now holds - and its `build`, the same number as the changelog line
   below, which the header's notice shows. Its `note` is kept for later and
   shown nowhere yet. `tests/py/version_test.py` fails when any of them
   differ.
2. `CHANGELOG.md`: a line under the latest minor version's heading, newest
   first - `- **0.20.3** (build 203) - What changed.` - where the build is
   the commit's count once committed (`git rev-list --count HEAD`, plus one).
   A minor version starts a new heading, with two or three sentences on what
   it gives the user.
3. `README.md`, for a minor or major version only: its "What's new" keeps the
   latest few features, a short paragraph each.
4. `model_manager/data/release_notes.json`, when a user needs to know or do
   something: a note, shown at the top of the tab it concerns (see
   `model_manager/release_notes.py`). A feature worth finding is
   `"audience": "everyone"`; something to do after updating - Scan Disk once,
   update the other copy before a migration - is `"update"`, which a fresh
   install skips. A note that concerns some installs only names a condition
   (`"when"`, one of `CONDITIONS` - `custom_database` for two WebUIs sharing
   one database), so everyone else is not told it. What everyone should read
   is `"important": true` - first in the pile, headed [Important]. A note
   asking again for what an earlier one asked - Scan Disk once more - names
   it in `"replaces"`, so it is asked once. A button, if one helps,
   names an action the page knows (`NOTE_ACTIONS` in
   `javascript/shared/notes.mjs`). Most releases need none.

After committing, tag it `vMAJOR.MINOR.PATCH`. Tags, like commits, are pushed
only by the owner.

## Known gaps

- **Local-only models cannot be bookmarked.** They have a row now, but
  bookmarking is keyed on a `civitai_models` id and they have none.
- **They also show as blank cards** — the grid takes previews only from the
  cached Civitai images, and never looks at the `.preview.png` beside the file,
  though the delete path knows about it.
- **`checkpointType` is only known for models Civitai still serves.** Anything
  delisted stays Unknown; nothing can recover it.
- Usage history and manual collections are unimplemented.

## Learned the hard way

What earlier sessions got wrong, or took too long to find. Each of these cost
real time once.

### Working with the person who owns this

- **Commit only when asked; push only when asked.** The repository is public,
  so a push publishes.
- **Commit only as the project's own identity**, set repo-locally. A global git
  identity on the same machine belongs to someone else; local `pre-commit` and
  `pre-push` hooks refuse any other author or committer. Never bypass them.
- **The live database is read in place, read-only** (`sqlite3` with
  `mode=ro`), never opened through `ModelsDatabase` - its migrations and
  writes would run - and never copied to a file. An in-memory copy of the
  columns a measurement needs is fine when agreed.
- **Explicit words are masked** in anything shown in the conversation - word
  lists, prompts, sample data. Put the raw data in a git-ignored file under
  `tests/work/` for the person to open.
- **After two wrong guesses, ask** for a console line, a screenshot, a number.
- **A proposal needs an explicit yes.** "Go ahead?" answered by moving on to
  something else is not one; an implementation started on that was undone.
- **Scope is the owner's.** Asked "what would the shared part be, and how
  would it be called?", show the code shape before changing anything; R29 was
  narrowed twice that way, to what is actually shared. A behaviour change
  found inside a refactor becomes its own issue unless the owner folds it in.
- **"mm" means the Model Manager tab**, not the `model_manager/` package.
- **"dev" on its own is GitHub's `dev`.** Asked for a copy of it, `main` was
  made from the local `dev`, which held commits not yet pushed, and had to be
  put back.

### Proving a change

- **A new check has to fail on the old code.** Swap the file for
  `git show HEAD:<file>`, run the check, restore it. One check - "the page
  query never scans the images table" - passed on the old code too: the old
  query read every image through an index, so the plan looked innocent. What
  told them apart was work: SQLite's virtual machine steps before and after
  adding images the page does not show.
- **Clear `__pycache__` after swapping files.** Python reuses bytecode when the
  source's mtime (to the second) and size match. `SCHEMA_VERSION = 23` to `24`
  is the same size, a swap reproduced the timestamp, and the stale bytecode
  kept version 23: the v24 migration silently never ran, through two restarts.
  If a change "does not take effect", compare the cached `.pyc` with a fresh
  compile before suspecting anything else.
- **Measure; do not estimate.** A restamp guessed at 10-20 s took 3-6. The grid
  was 1.3 s because one step ranked 100,651 images to pick 20 previews - found
  by timing each part of the query, not by reading it.
- **Check what a timed call returned**, not only how long it took.
- **The test DOM is not the WebUI.** linkedom runs no inline handlers: a tick's
  `onclick="event.stopPropagation()"` kept every click from the page's
  listener, and the suite never saw it - it now runs that handler itself. It
  has no layout. The harness reads a tab's markup straight from its `.py`, so
  markup a `.replace()` adds is not there (build it in the page). And the
  markup is there before the script, where in the WebUI it comes after: a
  test passed while the real panel never showed. Its MutationObserver misses
  a change made through `element.style`, which a browser reports - so
  `showTab` looks at the panel each frame rather than observing it. When a
  suite passes and the page does not, look for what the suite set up that the
  WebUI does not.
- **A test passes for the wrong reason when something else rescues it.** The
  downloads test had a running download, whose poll redrew the panel; the
  bug was a panel of paused downloads only, which nothing polls.
- **No test reaches a database.** A service that saves through
  `get_models_db()` takes a store the test can set
  (`DownloadService.store`), and saves nothing when there is nothing to keep.
- **A refactor is checked on real data, before and after.** Run every real
  sidecar (about 1,160 here) through the old code and the new, read-only, and
  compare every field: R13 found the enum it removed had been wrong for 25 of
  25 models; R18 found nothing changed. Then make one deliberate change and
  see the comparison catch it (a rating rounded differently: 395 differ) - a
  comparison that cannot fail proves nothing.
- **A test that pins an incidental fact breaks on every change.** "The schema
  is at 29" failed the moment v30 came; assert what the test is about.
- **A check that fails once is run twenty times on HEAD before it is blamed
  on the change.** One download test asserted which of two threads started at
  once recorded itself last: the scheduler's choice, 1 run in 20.
- **Read the run's result before committing.** A commit chained after the
  run with `;` went in over "1 failed", and which suite could not be
  recovered. The runner now names failing suites in its last line and keeps
  their output in `tests/work/last_failures.log`.
- **Scripted edits anchor on whole top-level lines.** A substring match put an
  import inside a function, twice (the match was an indented copy); a "cut
  to the next method" took a module's tail with the last method. After any
  scripted edit, parse every changed file and compare its function count.
- **A swallowed error looks like an unrelated failure.** A test's own helper
  named `usable` shadowed the imported `usable`; the paging code caught the
  recursion and reported "no models kept".
- **Gate what is costly on the case that needs it.** The tie-break read
  Civitai's order from JSON: for every version, +13.6 ms a grid query;
  counting ties with a window, +25 ms; asked only where an indexed `EXISTS`
  finds a tie, +3 ms. Time each part.

### The data

- **Civitai's labels are the uploader's.** VAEs and text encoders filed as
  "Checkpoint" or "LORA"; SDXL files labelled Anima; an image's `baseModel` is
  every resource's base model run together ("OtherAnima"); versions get
  deleted and 404; other tools write the version payload into `.civitai.info`
  instead of the model payload (`storage.as_model_payload`).
- **The file is the reliable witness.** Tensor names and shapes identified
  1,254 of a 1,262-file library; the rest were families Forge Neo cannot run.
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
- **Forge and the library spell one path two ways** - case, which Windows
  ignores and SQL does not. Compare paths with `COLLATE NOCASE`
  (`library_spelling`), never `=`.
- **Civitai's image ratings miss some.** 256 of 31,745 PG/PG-13 images in one
  library had explicit prompts; Civitai rates 95% of the images using those
  words X or XXX.

### The code

- **An import inside a function hides a cycle; it does not break it.**
  `architecture` imported `file_identity` that way while `file_identity`
  imported it at the top: one moved line from failing at startup. The cut was
  in the wrong place - the database part sat in the header reader - and
  `tests/tools/check_import_cycles.py` now counts every import, wherever it is.
- **A fallback can hide a bug.** The folder-path type guess masked a sidecar
  format read wrongly and a scan that died on one bad file.
- **Delete what is gone, not what was not seen.** Scan Disk once forgot every
  file it had not reached - a cancelled scan dropped the rest of the library -
  and left orphaned models and images behind.
- **Stamp what SQL filters on.** A per-image check is cheap in the browser, on
  a page of images; across the grid's queries it was 2.7 s against 4 ms.
- **Choose the page, then look up its details.** Filter, group, sort and limit
  first; per-row lookups after. With an index in the order the lookups read.
- **A bool is an int.** An enum checked `isinstance(value, int)` before
  `bool`, so a model's `nsfw: true` read as bitmask 1 - PG - and its own
  branch for booleans never ran. Test for `bool` first.
- **Whatever a ticked box does, a note's button must not do by accident.** A
  release note's button ticks "Re-evaluate file headers"; moving files into
  their type's folder got a box of its own, never ticked for anyone.
- **`check_python_references.py` does not model `@staticmethod`** called on an
  instance; make such a helper a plain method rather than leave a red check.
- **Forge Neo:** T5 and UMT5 files load only in Hugging Face's layout; switching
  a UI preset brings back that preset's checkpoint; Flux.1 and Flux.2 share
  block names and differ in MLP width, which a LoRA's shapes show.

### The environment

- The WebUI may not be on the default port. From WSL it cannot be reached
  directly; Windows' own `curl.exe` can.
- Run the tests with the WebUI's own Python - it has FastAPI and torch - and
  Windows `node.exe` for the browser suites.

## Branches

- **`main`** is the default branch: what "Install from URL" clones, where a
  commit's "Fixes #N" closes the issue, and whose `version.json` installs of
  `main` read for a new version.
- **`dev`** is where the work is committed, and what every install from
  before `main` existed follows - Forge updates a copy from its own branch
  (`origin/<branch>`), so they stay on `dev`.
- **`rc`** is for trying a release before it goes out; it is pushed first.
- **Whenever `main` is updated, `dev` is updated at the same time, to the
  same commit** - one push, never one without the other:
  `git push origin dev dev:main`. A release on `main` alone leaves every
  `dev` install behind and told of nothing; on `dev` alone, new installs
  miss it and its issues stay open.

## Before you push

```
python tests/run.py --all
```

Sixty-seven Python suites, sixty-two browser suites and six static checks, run
four at a time: about a minute. Not wider - each is a process of its own, and
32 at once beside two running WebUIs left Windows out of memory. While working,
`--changed` runs only the suites the uncommitted changes need. See
`tests/README.md` for what they cover, how the choice is made, and how to add
one.

**A test run takes a minute at most; one that needs longer is asked for
first.** That is the owner's rule. Start every run under a time limit
(`timeout 60`), and if it would need more, ask before running it. A suite
waits in seconds, never in thousands of tries: a `waitFor` of 4,000 tries is
200 s, and two of them in one suite ran a whole run past ten minutes, leaving
the suite's process behind. After a run that was stopped, look for what it
left running and stop only that.
