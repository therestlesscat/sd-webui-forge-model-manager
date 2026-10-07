# Working on this extension

A model manager for SD WebUI Forge: it lists what is on disk, enriches it with
Civitai metadata, and lets you browse and download more.

This file is everything an agent needs here, in one place: how to work with
the owner, the shape of the codebase - what each part is *for*, and which of
its rules were learned the hard way. It is not a file listing; `ls` does that
better. `CLAUDE.md` only imports it and holds nothing of its own: it once
described the architecture as well, drifted, and named three modules that no
longer existed.

## How to work here

### Asking, and changing

- Understand the question before answering it. If the ask is ambiguous, say
  which reading you took.
- **Do not make code changes unless asked.** Suggest improvements only when
  invited to. Ask before changing anything, and say what you are about to
  change.
- **A proposal needs an explicit yes.** "Go ahead?" answered by moving on to
  something else is not one; an implementation started on that was undone.
- **No change without an approved plan. This is a hard rule.** "Start on #N"
  asks for a plan, not for code, and an issue's own "What" is not one. A plan
  is not a list of steps. It says where each thing lives and how it is
  stored; what each change does, function by function, before and after; the
  alternatives, with their pros and cons side by side; what is old and what
  this work makes new; what it costs - a migration, the other WebUI, the live
  database; how it is tested, each check failing on the old code first; and
  the version. Each choice goes to the owner as a numbered question with a
  recommendation. Code starts on an explicit yes to that plan, and anything
  found later that changes it goes back as a plan. #187 was implemented
  straight from a survey and undone; its next plan, seven steps, was sent back
  for having no storage, no alternatives and no pros and cons (2026-10-06).
- **Scope is the owner's.** Asked "what would the shared part be, and how
  would it be called?", show the code shape before changing anything; R29 was
  narrowed twice that way, to what is actually shared. A behaviour change
  found inside a refactor becomes its own issue unless the owner folds it in.
- Honour the existing structure rather than reorganising in passing.
- Keep everything generic. No module exists to serve one workflow.
- **Stop guessing after the second try.** Ask for a screenshot, a console
  line, a number. Every long detour in this repository ended with one
  observation that reasoning had not produced.
- When showing an edit, name the enclosing method or class so it can be found.
- **"mm" means the Model Manager tab**, not the `model_manager/` package.
- **"dev" on its own is GitHub's `dev`.** Asked for a copy of it, `main` was
  made from the local `dev`, which held commits not yet pushed, and had to be
  put back.

### Commits, pushes and issues

- **A commit is prepared at each logical checkpoint, and made only on the
  owner's yes.** Prepared means `--all` passed, in its own call ("Testing");
  the version bumped if a user can see the change ("Versions"); and a message
  that says what was wrong, its numbers read from the staged diff
  ("Conventions"). Then ask. Never commit without asking.
- **Push only when asked.** The repository is public, so a push publishes.
  "Push to dev/main" means both branches and every tag ("Branches").
- **Commit only as the project's own identity**, set repo-locally. A global git
  identity on the same machine belongs to someone else; local `pre-commit` and
  `pre-push` hooks refuse any other author or committer. Never bypass them.
- **A change asked for "only for me" is never committed.** It lives in the
  working tree, and a commit is made around it: copy the files aside, strip
  the hunks, run `--all`, commit, copy them back.
- **The backlog is GitHub's issues**, labelled `backlog` and an area. An issue
  that does not reproduce, or works again with no commit shown to fix it, is
  not closed: it gets a comment - what was tested, on which version, what
  would settle it - and the labels `investigate` and `low-priority`.

### Getting it right

- **Never guess at an import or a function name.** Read the module. A name
  that looks obvious is how `get_max_nsfw_level` returned `UNKNOWN` without
  importing it.
- **Verify before asserting, especially about your own effects.** "I only work
  on copies" was said in this repository while a test was overwriting 747 real
  sidecars and applying migrations to the live database. If you have not
  checked, say you have not checked. Proving a change has lessons of its own
  ("Proving a change"). So is what a turn's own calls did: in the #41 round,
  12 replies said a step was still to come that a call earlier in the same
  turn had done - the test browser closed, a memory note written, the change
  staged, the issue opened. Write what a turn did from its results, read
  before the summary.

### The live data, and the WebUI running

- **The live database is read in place, read-only** (`sqlite3` with
  `mode=ro`), never opened through `ModelsDatabase` - its migrations and
  writes would run - and never copied to a file. An in-memory copy of the
  columns a measurement needs is fine when agreed.
- **The owner restarts the WebUI on the working tree, mid-task.** Neo loads
  this folder, and the database is the live one, shared: a migration not yet
  committed runs on it at the next restart (v32 did, three times, in #133).
  Say so before a schema change; once it has run, a further change to that
  migration reaches the live database only from its backup - delete the
  `-wal` and `-shm` beside it first, or the old log is replayed into the
  restored file. Before saying a restore is needed, read the live schema
  (`mode=ro`): one was asked for after the owner had already done it.
- **Explicit words are masked** in anything shown in the conversation - word
  lists, prompts, sample data. Put the raw data in a git-ignored file under
  `tests/work/` for the person to open.
- **This library is one of many.** The repository is public and has users.
  A count from the live database says how this library is, not how much a
  bug matters: #131 was ranked down for touching 0 of 1,196 sidecars here,
  and is a bug in every library where another tool wrote stubs. Weigh a bug
  by what it does where the case exists, and fix what it has already written
  into those databases, not only what it would write next - a user does not
  read the issue, or know to Force sync. So is this machine one of many: on
  its NVMe and 32 cores 8 hash threads ran 3.58 GB/s against 2.02 at 4, but a
  hard disk or a network drive gets slower with more, and the default stayed
  4. A fallback this library never needs is reordered, not removed: BLAKE3
  and CRC32 lookups stayed, last.
- **Leave nothing running.** Kill any server, watcher or background job you
  start, in the turn you use it. Two test servers were once left running for
  twenty-three hours.

## Layout

```
scripts/model_manager_ui.py   the entry point Forge loads
scripts/model_manager_generations.py
                              the always-on script that records your generations
model_manager/                the extension proper
javascript/loader.mjs         the one script the WebUI loads: the version, then the loading module
javascript/tabs/              the four tabs' scripts, loaded only while on (shared/loading.mjs)
javascript/shared/            what they share
style.css                     picked up by filename; see "The WebUI's rules"
tests/                        see tests/README.md
tools/train_nsfw_model.py     trains the NSFW prompt model from a library, read-only
tools/train_nsfw_from_civitai.py, run_nsfw_training.sh
                              the same, from a pull of Civitai itself, paced at 5 req/s
```

### `model_manager/`

| | |
|---|---|
| `db/` | everything that touches SQLite. A facade (`database.py`) over one module per job: `models_ops`, `images_ops`, `generations_ops`, `tasks_ops` (the generation queue), `downloads_ops` (the download queue, across a restart), `query`, `migrations`; `library` the one read of a file with its version (`LIBRARY`); the grid's filters, sort and page travel as one `GridQuery` (`query.py`), read from the request once |
| `civitai/` | talking to Civitai: `client` (auth, rate limiting, retries), `prompt_filter`, `size_filter` (filtering a search by download size), `licensing`, `ownership` (which paid versions the key's account bought), `random_draw` (I'm feeling lucky: a page drawn at random from what Civitai's own filters allow) |
| `forge_host.py` | what the extension asks of the WebUI it runs in, and the one module that asks (with `ui/settings.py`, which registers the settings; `tests/tools/check_forge_imports.py`): its settings, with one table of their defaults (`DEFAULTS`) that registration and every read take; Forge's options, folders, checkpoints, modules, presets and samplers; which Forge it is, and where Neo and the original Forge keep a thing apart |
| `tabs.py` | which tabs are on (#41), the one place that says: each tab's switch (`TABS`), what several share, on while any of them is (`SERVICES`: downloads, Send, the restamp), and which tabs this start created (`built`, for the page). Every route names its area on the line under its own (`api/common.gate`) and answers 403 while it is off - `tab_switches_test.py` holds all 72 to a table; startup work and the recorder ask it too |
| `sync_service.py` | identifying files and refreshing their metadata, after the walk of the library every sync from the dialog starts with (`walk_library`): new files given a row and their header read, sizes brought up to date, files gone forgotten with what only they kept, files in another type's folder moved when asked |
| `sync_estimates.py` | what a sync would cost and cover, before it starts: the sync dialog's request estimate, its staleness-window counts, and the files every sync will hash (`files_to_hash`) |
| `model_dirs.py` | where models live: one table of the folders a sync walks and a download files into, the walk itself (`find_model_files`), when a walk may forget a row, and where a file of each type belongs - with the files in another type's folder, and moving them (`misplaced_files`, `move_misplaced_files`) |
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
| `version.py` | the version this copy is (`VERSION`), and its build, counted from the history; see "Versions" |
| `console.py` | what the extension writes to the console: every "[ModelManager]" line goes through `say()`, which prints it and keeps the last 2,000 for the sync's log panel (`/model-manager/sync/progress?since=`); `console_test.py` fails on a print of its own |
| `remembered.py` | answers kept in memory - Civitai's about versions, file hashes, SFW verdicts, versions an account bought: a map with a bound, under a lock; how old an answer may be stays its caller's |
| `data/` | files that ship with the code: `nsfw_prompt_words.txt`, the bundled prompt words, and `nsfw_prompt_model.json.gz`, the prompt model, trained from a pull of Civitai by `tools/train_nsfw_from_civitai.py`; `release_notes.json`, the notes to the user |
| `api/` | the HTTP endpoints, one module per area, each with `register(app)`: `models`, `images`, `generations` (your own images: a model's gallery of them, and the Generations tab), `jobs`, `civitai`, `webui`, `settings` (the settings window's), `notes` (notes to the user). Beside them, three helpers: `common` (what every endpoint module shares - the card-size parser, the answer to a failure, the gate every route passes), and for the Civitai endpoints `annotations` (marking up search results with what the library holds) and `prompts` (whether a model's images are worth opening) |
| `ui/` | settings, and the markup for each tab: Queue, Generations, Model Manager, Civitai Browser, in that order - building the Queue tab also wires the Queue buttons; `header.py` what they draw alike - the version and the settings gear, the downloads panel |

### `javascript/shared/`

What the tabs share, one module per job (#93), each asked for under one
version (see "The WebUI's rules"). None does anything as it is imported: one
with work - a listener, a hook, a request, an action offered - does it in its
`start(scope)`, once for the page, and a tab starts what it uses (`STARTS`, #182).
The scope is the loading module's, as a tab's is, and stops with the last tab
that uses the service (#186): with the Model Manager off, the sync still asked
for its progress whenever the page came back into view. One that only relies
on others names them in a `STARTS` of its own (`send`, `image_card`).
A module imported for another's sake starts nothing: the notes once imported
the sync's module, and the Queue alone asked for the sync's progress
(`import_work_test.mjs`, `queue_alone_test.mjs`):

| | |
|---|---|
| `loading` | the loading module (#183): which tabs run - `boot()` loads only the tabs that are on and built, and follows their switches, saved in the settings window or on the WebUI's Settings page (`onOptionsChanged`: the way back with every tab off) - and each tab's scope, which takes back all it added when it stops (`createScope`); what a tab's script declares to do once started (`tabWork`); and the only way between tabs (#184) - `available(tab)`, `open(tab, entry)` at what a tab's script `entries` offers, `linkTo` for a link to one; the shared services, each started once with a scope of its own and stopped with the last tab that uses it (`useServices`, `leaveServices`, #186); and the popup when a switch cannot fully take effect in the page - Restart WebUI, the cleanest slate, beside a page reload, or Settings -> Reload UI for a tab this start did not build (#185, #186) - the tab showing kept for the new page |
| `calls` | what one part of the page offers the rest, by name: `provide`, `ready`, `call`, `withdraw`; and the page's one listener calling what markup names in `data-action` |
| `tabs` | the WebUI's tabs by id: `showTab` (resolves once Gradio shows it), `tabButton`, `tabShowing` |
| `core` | what every part uses: `TIMING`, `apiCall`, `escapeHtml` (the one escape), `dataAttributes` (what an action reads), `holdPage` (the page held still while the viewer, a dialog or the settings window is open over it - the one place that sets `mm-modal-open`), `setText` / `setTitle`, `safeId` / `safeUrl`, `sanitizeHtml`; numbers, sizes and dates as a person reads them |
| `ui_options` | the server's ui-options, asked once a page: the API-key banner, which judges NSFW, how a gallery opens, whether your generations are shown |
| `notes` | notes to the user, at the top of each tab; a button is drawn only while what it opens is there - a Sync, while the Model Manager is available |
| `jobs` | the long job, Sync with Civitai: its dialog, starting, following and cancelling one, and finding one still running; the Model Manager connects it to its status line and grid (`connectJobs`), a note's button opens its dialog by name (`sync.showDialog`, offered once the Model Manager starts it) |
| `update_notice` | "vX available" beside each tab's version |
| `nsfw` | an image's level as the server stamped it, its badge, and the levels one can rate; the page's one table of levels and their names (`NSFW_LEVELS`), a copy of `nsfw.py`'s held to it by `page_constants_test.py` |
| `media` | Civitai's images and videos: the copy for a width, the fallback, loading them as they come into view |
| `grid` | cards, the grid and its page strip, its rows kept even, and the card size the server gave a tab (`createCardSize`) |
| `image_card` | a Civitai image's card and its Show All window, the same in both tabs; your generations' cards show its text |
| `samplers` | Forge's samplers and schedulers, from the one ui-options answer, and an image's sampler text read by them |
| `gallery` | a gallery's loading bar, filter banner and page notes, and its pages - kept, drawn and paged through by one object per gallery (`createPagedGallery`), each tab keeping only how it fetches a page; and scrolling to a gallery's top |
| `filters` | what both filter bars share: base models in order, the size boxes, a saved search and Save Search's flash, the checkpoint-type filter greyed while Type is not Checkpoint |
| `generations` | your generations, as a model's gallery and the Generations tab both show them: a thumbnail, the rating and delete requests, a shift-click's range, the select bar and bulk delete, the rating row. Each tab draws its own cards or tiles |
| `downloads` | a version's Download button, and the downloads panel both tabs show; the list runs once a tab that downloads starts it, and stops with the last; Send's Resources and chips offer Download only while it runs |
| `send` | Send to txt2img / img2img, from any tab: Forge's VAE / Text Encoder control, its UI preset and the server's send plan, samplers, the infotext and the paste, an image-to-video model's start frame (`sendGalleryImage`, `sendInfotext`) |
| `chips` | an image's LoRAs and embeddings as chips under the prompt, after a send: their rules, and the chips on the page |
| `resources` | an image's resources and the Resources dialog every gallery opens, each passing the version its gallery is of (`exclude`): which Civitai versions they are, whether the library has each, and a Download into it - through the downloads list, which polls for it, as for every download |
| `wan` | a video's frames and size as Wan makes them |
| `settings`, `viewer` | the settings window, and the image viewer every gallery opens - with the modal the metadata and Resources windows open in |

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
setting's default), `tabs.py` (whether a tab is on). Each found a second copy that had already begun to
disagree - or, for the settings, thirty-odd that still agreed; tests hold the Python
to the SQL (`switch_counts_test`, `prompt_rules_test`) and registration to the
table (`forge_host_test`), and `check_hash_access.py` keeps readers on the
facade. No test yet holds `model_level_sql` to `model_level()` (#146). What
the page must have before any answer could come, it keeps a copy of: the NSFW
levels, once (`nsfw.mjs`); the setting keys, where each is read.
`page_constants_test.py` holds both to the server's (#86).

**A migration does not import today's rules.** v14 once imported the live
`nsfw.image_level`, which later learnt to read the person's settings: it
applied a rule it was not written with, during startup, and renaming the
function would have broken every older database. It carries a frozen copy.
An index is a migration too (v30), versioned like any other. Since v32 an
older copy refuses a newer database ("Two WebUIs"), so any migration means
updating both copies.

**Everything the extension says, it says through `console.say`.** The sync's
log panel shows the console's lines from where the sync began - every one, a
gallery opened meanwhile included - so a `print` of its own would reach the
console and never the panel. The migrations keep theirs: they shipped so, and
run at startup. A traceback (`traceback.print_exc`) still reaches stderr
alone, not the panel (#143).

### The library: files, versions and rows

**A version is one row; its files are rows of their own** (#133).
`versions` holds a Civitai version once - its details, its gallery's cursor
- and `files` each file, naming its version by `version_id`, NULL for a file
Civitai does not know, which has no row anywhere else: no table is named for
Civitai (`models`, `versions`, `files`). `model_versions` held
both in one row per file: a version with an fp16 and an fp32 was fetched,
counted and read as two, and the copies drifted - 26 of one library's 36
such versions disagreed on their gallery's cursor, and the gallery read
whichever copy came first. Reads that want a file with its version go
through `db/library.py`'s `LIBRARY`, which gives the row `model_versions`
did; writes go to the table that holds the column. What is per version -
a gallery, its cursor, a card's count - is done once per version: a sync
over several files fetches a version's gallery once (`galleries_fetched`),
and the page draws one pill per version, with a Files list under it to read,
not to pick from. Which of a version's files Send uses is decided by what each
is and where it is (`send_plan.send_files`), and the list says which.

**A file is known by its path; Civitai's id for it is a fact about it.**
`files` is keyed by `file_path`: what Forge loads, what a sync walks, and what
`pins` and `generation_files` name - on purpose, so a pin or a generation's
link outlives the file going and coming back. `civitai_file_id` (with
Civitai's type for the file, fp, size, format, primary) is matched by hash,
else by name (`payload_rows.file_row`), by every sync and a download.
It is no key: a file Civitai does not know has none, one Civitai file can be
on disk twice (in both WebUIs' folders), and it is learned late and can be
corrected - a key that changes is rewritten wherever it is named.

**A path is shown from where Forge was told to look.** Under a folder the
WebUI was given on the command line, by that option (`--lora-dir\x`); else
from the WebUI's own folder (`models\text_encoder\y`); else whole - the
other WebUI's file, in a folder this one was not given, which it cannot load
(`model_dirs.shown_roots`, `shownPath` in `ui_options.mjs`). Cut at
`\models\` alone, an embedding - not under it - showed its whole path, and
the other WebUI's file read as this one's.

**Absent is not empty.** Both `upsert_version` and `upsert_civitai_model` keep
what they hold when handed `NULL`, `'[]'`, `0` or Unknown. Scan Disk, reading
a thin `.civitai.info`, could not tell "this model has no trigger words" from
"this file does not mention any", and it used to write the second over the first —
blanking trigger words, dates, licences, vote counts and stored hashes. Both
are generated from one list per table (`MODEL_COLUMNS`, `VERSION_COLUMNS`,
`FILE_COLUMNS` in `db/models_ops.py`), each column with how an update treats it - overwritten,
kept when the new value says nothing, or a rule of its own - and given its
value by name. Adding a column means an entry there, or in the list of
columns written elsewhere; `upsert_columns_test.py` fails on one in neither.
It used to be four places by hand, and a column missed from the `SET` list
was written once and never updated. A payload without `nsfw` still writes 0
over a stored 1 (#141).

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

**A card shows one version, chosen in one fixed order:** newest published, then
Civitai's own order (`index` in `models.versions`, whose first its page
shows), then version id and file (`SHOWN_ORDER` in `db/query.py`). Versions
share a date to the millisecond, or have none; without the tie-break SQLite
returned either, and a cover changed between loads. Anything that picks one of
several needs an order that cannot tie.

### Civitai: sync and downloads

**Civitai is the source; a sidecar is written, not read.** A sync and a
download write `.civitai.info` beside a file, for other tools; nothing takes
from one what Civitai can say. A sidecar is read in one case: Civitai answers
404 for the file's SHA-256, no other hash finds it, and the model the sidecar
names is a 404 too - deleted, most likely (`SyncService._identify_by_sidecar`).
And "Civitai does not know" means a 404, never an error: an outage used to
mark every file looked up during it "not on Civitai", and every sync after
skipped them. An error on the SHA-256 is asked again at the sync's end; on a
later kind it counts as a miss. Another tool's `.cm-info.json` is still asked
with once every hash read from the file has missed - against this rule
(#140). Scan Disk read every sidecar as a source, and wrote its hashes as the
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

**`checkpointType` is inferred, not read.** Civitai accepts it as a filter and
returns it on neither the model nor the version. `get_checkpoint_types()` asks
which ids are Trained, then which are Merge, and takes the answer from set
membership — discarding any batch whose answer does not partition the request,
because that would mean the assumption no longer holds.

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

**The download queue is the service's own.** `DownloadService` runs up to two,
and when a place frees up starts the first waiting one from the top; Start now
runs one over the limit. A version asked for again while on its way - queued,
coming, being added, paused - is answered with the download it has, never
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
change: from 0.43.0 (48ad567) only a download with a `.partial` was kept, in
`schema_info`, and a restart forgot every one still waiting (#187). A kept
download whose file the library has by then - its Civitai file id, on disk,
in this WebUI's folders (`_held`) - is not brought back, and a resumed one is
asked again before anything is fetched. Never by its version alone: a
version's other file is not this one.

### The page

**Calls between files go through `shared/calls.mjs`.** A shared module that
offers something to the page - the settings window's `settings.open`, a
tab's `cardPreview.<setting key>` - provides it by name; the others `call`
it. They reached each other through window globals (`window.mmShowModel`),
and a caller found out what was missing its own way, or not at all.
`check_js_references.mjs` fails on a file that reads another's window
global, and on a call to a name nothing provides. Events stay window events
(`mm-settings-saved` and the others named `mm-`).

**A tab reaches another only through the loading module** (#184):
`available(tab)` - on, and started in this page - and `open(tab, entry,
...)`, which shows it and calls one of what its script `entries` offers
(the Model Manager's `showModel`, `showFile`, `showVersion`,
`showSyncDialog`). Tabs called each other's actions by name, each checking
`ready()` its own way, and drew a link whether its tab was there or not. A
link to another tab is disabled, saying why, while that tab is not
available - `linkTo(tab, title)` draws it so, and the loading module keeps
every `data-needs-tab` element so after each update. `check_js_references.mjs`
fails on a tab, or a shared module but the loading module and `tabs.mjs`,
naming another tab's area in `call`, `ready`, `provide`, `showTab`,
`tabButton` or `tabShowing`, or importing its script.

**Markup names what it does, the same way** (#95):
`data-action="modelManager.selectModel"`, with what it needs in `data-*`,
which one listener for the page calls - a field on its change, anything else
on a click, the innermost action alone, with the element's data, the element
and the event. Inline handlers reached window globals by names in strings, in
the modules' templates and the tabs' Python, and no check followed them
across: `check_js_references.mjs` fails on markup with an inline handler and
on an action name nothing provides, in the JavaScript and the Python alike -
within an area some file provides: a misspelt area passes (#147) - and on any
window global but `mmSharedVersion`, which every tab needs before
the registry has loaded. A suite presses what the page draws (`act`, `tick`,
`press` in `tests/js/harness.mjs`), through the real listener.
The listener stops nothing, and no action does: a stop in the metadata window
once kept Copy JSON's click from the listener that copies. Listeners outside
the actions stop their own events - a gallery's selection mode takes a tile's
click in the capture phase. An action runs as the click reaches the
document, after anything around its element has heard it - an inline handler
ran first: the viewer, which closes on Send, closes once the click is done.

**One downloads list for both tabs.** `downloads()` in
`javascript/shared/downloads.mjs` polls once and draws into each tab's panel -
started by the Model Manager and the Civitai Browser, null before. It
is module state: the tabs share one copy of the module (see "The WebUI's
rules"), and so do the notes, the update notice, the Your generations switch
and the settings window - none of them on `window` since #93. The list's order is the server's - the order downloads were added in, which ↑/↓
change - and a state never moves a row; the page keeps that order apart
(`sequence`), as an object's number keys come out sorted. It asks for the list
when the page loads, and draws it again once Gradio has drawn the panel: a
paused download polls nothing, and the panel used to stay hidden after a
restart.

**A gallery's Send sets up its own model first** (#134). The gallery's file
is the primary: a checkpoint is loaded, a VAE or text encoder takes its kind's
place (`pick(own=)`), an upscaler becomes Hires fix's, a LoRA or embedding a
chip. The rest is picked as before, never over it. The image's checkpoint is
the one thing Send cannot go without: one the library lacks, or this WebUI
cannot load, stops the send and opens the image's Resources, whose own Send
works once the server says it can (`checkpoint_problem`). An image that names
no checkpoint has Send disabled outside a checkpoint's gallery (`cannotSend`).
Before, a LoRA's or VAE's gallery left Forge on whatever it had loaded.

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

## The WebUI's rules, which are not obvious

- `javascript/*.js` become classic scripts, `*.mjs` become
  `<script type="module">`, **in filename order**. Subdirectories are not
  scanned: `list_scripts` uses `os.listdir`. So there is one, `loader.mjs`:
  the tabs' scripts are in `javascript/tabs/`, where the WebUI loaded each of
  them, whatever its switch said, until #183; the loading module
  (`shared/loading.mjs`) loads those that are on. A tab's script does nothing
  as it is imported: it declares what it will do (`tabWork`) and exports
  `start(scope)`, and all it adds outside its own markup - a listener on the
  document or the window, a timer, a hook, an observer, an action - goes
  through the scope, which takes it back when the tab is switched off
  (`tab_stop_test.mjs`), as each service's scope does with the last tab that
  uses it (`service_stop_test.mjs`). Back on in the same page, a tab built at
  this start and never started starts at once - unless a service it needs has
  stopped; one that ran here comes back only in a new page: a reload, or
  Restart WebUI (`POST /model-manager/restart`, the WebUI's own
  `restart_program`), which the popup offers. Only a new page is sure to hold
  nothing a stop missed; restarting a tab in place was weighed and dropped
  (#186). Restart WebUI is offered only where `is_restartable()`: started any
  other way than by `webui.bat` or `webui.sh`, the WebUI would exit and stay
  down.
- `style.css` is found by name, and linked after the WebUI's own, one
  `<link>` per extension.
- Both are stamped with the file's mtime **each time the UI is built** - at
  startup, and at Settings -> Reload UI - so a change needs a Reload UI to
  reach the browser, not just a page reload. `javascript/shared/` and
  `javascript/tabs/` need only a page reload (next).
- Nothing in the WebUI versions `javascript/shared/`, and Gradio's file route
  sends no `Cache-Control`, so a browser may keep a copy without asking. A
  plain import resolves to a URL that never changes, and a newly exported name
  becomes a link error that kills the entire tab. The tabs used their own
  `?mtime` - which stayed the same when only a shared file changed (15 of 60
  releases that touched shared/). They now ask `/model-manager/asset-version`
  for the newest mtime among the shared files and the tabs' scripts, once a
  page, in the loader (`window.mmSharedVersion`) - an area of `tabs.py`'s
  `ALWAYS`, like ui-options: gated `any`, it refused with every tab off -
  and import every module with it: one URL, so each also **runs once**, not once per tab. It is asked until it
  answers: both WebUIs serve the page, then add their own routes (the
  `/internal/ping` a restarted page waits on), and only then run the
  extensions' `app_started`, which adds ours - a page reloaded by "Apply and
  restart UI" asked too early, fell back to each tab's own version, and ran a
  copy of every shared module per tab, page state and all, for the session
  (#121). A 404 or no connection is waited out; any other answer is taken, one
  without a version as the loader's own. A wait that ended
  on any answer without a version once hung four suites, whose fetch
  stand-ins answer `{success: true}`, until their processes were killed.
  A shared module that needs another imports it the same way, under its own
  `import.meta.url`'s version. Both go through one line, `const shared =
  (name) => import(...)`, and `await shared('core.mjs')`: a plain `import` is
  a URL without the version, and a second copy (`page_state_test.mjs` records
  every URL a shared module is asked for under, and fails on a second).
  `check_js_references.mjs` holds what is taken through it to what the module
  exports. A tab asks for every module it needs at once (`SHARED_MODULES`),
  then awaits each: awaited in turn, each module waited a round trip before
  the next was asked for. The check holds the list to the awaits. What it
  uses that has a `start()` it names in `STARTS`, which the loading module
  starts before it (#182).
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
  `onAfterUiUpdate` (the downloads panel, the notes). A tab is started once
  its markup is there (`scope.markup`, in the loading module): the Civitai
  Browser's start did not wait, and in one load of three on Neo it bound Save
  Search, Enter and the Type box to nothing (#128).
- **A click on a tab's button never reaches the document from it.** Gradio's
  Tabs replace the button clicked with a selected one first, so a listener
  on the document sees a detached target (seen 3 of 3 on Neo). Watch for the
  tab showing - `tabShowing` from `onAfterUiUpdate` - not the click (#128).
- **Settings -> Reload UI runs the scripts again in the same process**, with
  the extension already imported, after clearing every callback; Extensions
  -> Apply and restart UI is a new process. So every callback is registered
  by the script (`scripts/model_manager_ui.py` registers the API's
  `app_started` itself), never at import - and nothing deletes the extension's
  modules to "reload" them: that once left two copies running, the recording
  script and the settings on one, the API on the other. Edited Python needs a
  real restart; the scripts and the stylesheet, a Reload UI. A Reload UI
  keeps the package imported, so a script that imports a name added since the
  start fails: 0.50.8 added `queue_enabled` to `scheduler/__init__.py` at
  15:42, and 7870, started at 15:23 and reloaded, failed with an ImportError
  in `model_manager_ui.py`. A real restart cleared it. Its button interrupts
  a running generation first: `request_restart` calls
  `shared.state.interrupt()` (Neo's `modules/shared_state.py`).
- **A page reload starts on the first tab, every field as the UI was built.**
  A prompt typed in txt2img was gone after one on 7870. So a popup that
  offers a reload says unsaved input is lost, and the loading module brings
  the page back to the tab that showed (`mm-return-to` in sessionStorage,
  #186).
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

Where they differ, and what the extension does about it - on the server in
`forge_host.py`, the one module that asks Forge anything; in the page in
`send.mjs`:

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
same version. An older copy does not migrate a newer database - it ran its
old queries and writes against the newer schema, without the fixes since. From
v32 a copy refuses a database newer than it knows (`_init_db`), and v32
dropped `model_versions` and renamed `civitai_models` to `models`, so a copy
from before it fails rather than writes the old shape. v33 is a fence too: a
copy that still has Scan Disk refuses the database. Update both before
starting either.

**A shared library holds the other WebUI's files.** Its sync files them in
the same `files`; this WebUI may not have been given their folders and
cannot load them. Anything that acts on a file - Send's choice of a version's
file, the chips' "in library" - takes one in this WebUI's folders
(`model_dirs.folder_of`; the chips by `lora_folders`, the folders Forge loads
LoRAs from); anything that shows one says whose it is (a whole path).

To see the original Forge's behaviour without starting it, run the code under
its Python with its packages on `sys.path` (`webui`,
`webui\repositories\huggingface_guess`, `webui\packages_3rdparty`): that is
how the detector break was reproduced, and the fix shown to work on real SDXL,
Flux and SD 1.5 files. Import nothing that reaches its `modules`:
`forge_host.available()`, with its `webui` on `sys.path`, imports its
`modules.shared`, CUDA and all. Check which files exist instead.

## One stylesheet, one definition

All three tabs share `style.css`, and draw the same things: a filter bar, a
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
- **A `cb-`, `mm-` or `gen-` class is for something only that tab has** — the
  manager's sync dialog and its log. Not for a variation on
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
thing, so the next component that would have been copied has to be shared. It
does not yet look at `gen-` rules.

### Light and dark, every style

**Every style covers light mode and dark mode. No exceptions.** A colour, a
background, a border, a shade, a shadow: each is decided for both, and seen
in both before it is done. Until 0.45.7 the tabs were drawn for dark mode
alone, and light mode had black text boxes, grey cards, dark dropdowns, and
ticked checkboxes that looked empty.

- **Take the theme's colour where there is one** - `--body-text-color`,
  `--background-fill-primary`, `--border-color-primary`,
  `--checkbox-background-color-selected` - with a fallback. Where it does
  not do in one mode, give that mode its own rule. This theme leaves
  `--input-background-fill` white even in dark mode, which is why the dark
  was once set outright, for both.
- **A colour of its own for one mode goes under `.dark`**: the light rule
  first, `.dark .x { ... }` after it. A `.dark` rule outweighs a later
  `:hover`, `.active` or `[data-state]` rule of the same weight, so it goes
  before them, or names the state itself (`.dark .x:hover`).
- **A shade is not a colour.** `rgba(0, 0, 0, 0.2)` darkens a dark page and
  greys a light one: a light mode gets a lighter shade (0.03-0.06), and the
  dark one moves under `.dark`.
- **Text on a dark badge over an image** - a date, a count, a button on a
  tile - is dark in both modes, and says its own text colour.

**What the WebUI does to our markup, and what wins against it:**

- **Gradio colours every element in an HTML block** -
  `.gradio-container-4-40-0 .prose * { color: var(--body-text-color) }` -
  at a weight one class cannot beat. A colour of ours is set with
  `!important`, and so is every state rule that sets a colour on the same
  element, so their order among themselves holds. Without it, a white date
  on a dark badge was black in light mode, and a blue type badge showed the
  theme's text colour in both.
- **Gradio's form reset draws every checkbox in its container itself**
  (`appearance: none`, and once ticked a white tick) with no fill: a ticked
  box is filled in our tabs (`#model_manager_app [type="checkbox"]:checked`
  and the other two roots). The settings window and the dialogs are added to
  the page's body, outside the container, and keep native controls.
- **It resets a `<button>`'s font, and not a link's.** A link dressed as a
  button did not look like the buttons beside it, and two CSS fixes did not
  make it: a button that opens a page is a `<button data-open-url>`
  (`core.mjs`), not an `<a>`. Five links still break it (#144).
- **It gives an input a bottom margin**
  (`.gradio-container-4-40-0 .prose input`, 4px), which only a last child
  escapes (`.prose :last-child`): Show hidden's box, its count in a `<span>`
  after it, sat 2px above Select's on 7870. A switch's box says `margin: 0`
  (`.queue-select-switch > input[type="checkbox"]`).

**Seen in both modes, in a real browser, before it is done.** linkedom has
no layout and no cascade worth the name: headless Edge (`tests/README.md`,
"Probes") on a page that loads what the WebUI
loads - Gradio's `assets/index-*.css`, **the running theme** (Windows'
`curl.exe http://127.0.0.1:<port>/theme.css`), the WebUI's `style.css` and
**every extension's**, in the page's order (the page's own `<link>`s list
them) - with one copy of the markup in light mode and one under `.dark`.
Measure what the change is about with `getComputedStyle`, against the
stylesheet before it (`git show HEAD:style.css`): what should not move, in
either mode, must come out the same. A probe without the theme or the other
extensions' styles measured buttons the same that were not.

## Conventions

- Comments explain **why**, not what. If a line needs saying twice, the second
  one is not a comment.
- A commit message says what was wrong and what it now does, with the numbers
  that justify it - counted from the diff, not remembered: two messages in the
  0.44 round said 219 lines for 147 and 27 handlers for 28, and had to be
  amended. Stage, read `git diff --cached --shortstat`, then write the number:
  in the 0.48 round three more were amended - +603 for +753, +519 for +512,
  and "26 new checks" added up from memory. And a message states only what was
  seen: "wrapped line after line" was never looked at, and was taken out.
- Tests assert what the code does, never what someone's library happens to
  contain. Four suites had to be fixed for exactly this.
- **A stop needs a way back.** A dialog that blocks an action offers that
  action again once its cause is fixed: the Resources dialog's Send works once
  the server says the checkpoint is there (0.47.3).
- **Text that tells the user what another part does is read against that
  part's code.** The restart popup said downloads "pause, and resume after";
  `restore()` brought them back paused, and forgot one never started (#187).
  A side agent's review found it after the commit, and two patches (0.51.7,
  0.51.8) followed - the first one's wording unclear in turn.

## Versions

`MAJOR.MINOR.PATCH.BUILD`, as `model_manager/version.py` explains. The build
is the commit's place in the history and is never written down; the rest is.

**Before each commit**, decide which it is:

- **A minor version**: a feature that means something on its own, even inside
  an existing tab - the settings window, the trained NSFW model. Bump MINOR,
  PATCH to 0. A change to what a core action does - Send, Sync, a download -
  is one too: #134's Send change was retagged from 0.46.1 to 0.47.0. Unsure,
  propose a minor and say why.
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
   `"audience": "everyone"`; something to do after updating - a sync with every header read again,
   update the other copy before a migration - is `"update"`, which a fresh
   install skips; a tab's introduction is `"new"`, for a first install
   alone. A note that concerns some installs only names a condition
   (`"when"`, one of `CONDITIONS` - `custom_database` for two WebUIs sharing
   one database), so everyone else is not told it. What everyone should read
   is `"important": true` - first in the pile, headed [Important]. A note
   asking again for what an earlier one asked - another sync like it - names
   it in `"replaces"`, so it is asked once. A button, if one helps,
   names an action the page knows (`NOTE_ACTIONS` in
   `javascript/shared/notes.mjs`). Most releases need none.

After committing, tag it `vMAJOR.MINOR.PATCH`. Tags, like commits, are pushed
only when the owner asks - and every push to `dev` and `main` takes them all
(see "Branches").

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

What earlier sessions got wrong, or took too long to find. Each of these cost
real time once. The working agreement's own lessons are under "How to work
here"; a suite's traps - what linkedom lacks, a test something else rescues,
waits - are in `tests/README.md`.

### Proving a change

- **A new check has to fail on the old code.** A check that has never failed
  has not been shown to check anything: three separate attempts at one fix
  passed a suite that could not have caught the bug. Swap the file for
  `git show HEAD:<file>`, run the check, restore it. One check - "the page
  query never scans the images table" - passed on the old code too: the old
  query read every image through an index, so the plan looked innocent. What
  told them apart was work: SQLite's virtual machine steps before and after
  adding images the page does not show.
- **Make sure the old code is what ran.** In WSL's zsh a swap failed without a
  word - `noclobber` refused `git show HEAD:<file> > <file>`, and an
  interactive `cp` waited for an answer that never came - and the "old code"
  run passed, on the new code. Write with `>|` and `command cp -f`, and see
  `git diff --stat` show the file back at HEAD before reading the run. An
  unquoted variable holding a list is one word in zsh: a loop over `$FILES`
  ran once, on all nineteen names as one, and the "old code" run passed on the
  new. Read a list line by line (`while IFS= read -r f`).
- **A break must fail a check, not crash the suite.** `ORDER BY 0` is an
  SQLite error, not an order, and a check that sliced a list by what it
  assumed raised a `ValueError`: both "failed" without showing which check the
  break reached. Compare whole values, and break with a valid alternative -
  `(1 = 1)` for the order.
- **Clear `__pycache__` after swapping files.** Python reuses bytecode when the
  source's mtime (to the second) and size match. `SCHEMA_VERSION = 23` to `24`
  is the same size, a swap reproduced the timestamp, and the stale bytecode
  kept version 23: the v24 migration silently never ran, through two restarts.
  If a change "does not take effect", compare the cached `.pyc` with a fresh
  compile before suspecting anything else.
- **Measure; do not estimate.** A restamp guessed at 10-20 s took 3-6. The grid
  was 1.3 s because one step ranked 100,651 images to pick 20 previews - found
  by timing each part of the query, not by reading it. And check what a timed
  call returned, not only how long it took.
- **A trace settles a delay.** #112's viewer "closed late": the owner's
  DevTools trace (Performance, Save profile: a `.json.gz`) showed our click
  handler at 3.0 ms and the frame on screen 8.2 ms after the release - the
  65 ms was the button held. Event Timing's `duration` runs from the input to
  the frame on screen. A trace may open with a focusing click: anchor on the
  input being measured. Esc, read the same way, was 19.6 ms.
- **A refactor is checked on real data, before and after.** Run every real
  sidecar (about 1,160 here) through the old code and the new, read-only, and
  compare every field: R13 found the enum it removed had been wrong for 25 of
  25 models; R18 found nothing changed. Then make one deliberate change and
  see the comparison catch it (a rating rounded differently: 395 differ) - a
  comparison that cannot fail proves nothing. A schema change the same way:
  HEAD's package beside the tree's, on an in-memory copy of the live tables,
  the migration's backup pointed at memory (a script kept locally, under the
  git-ignored `tests/work/r133/`). It found what every suite passed (see
  "Saying nothing is not a value").
- **A visual claim is measured, not eyeballed** - the owner's screenshot, pixel
  by pixel. "Cancel looks taller" measured 36 px against 36 px: the disabled
  Sync beside it, at opacity 0.6, read as the smaller.
- **Old code and new, side by side on the live page, with nothing written.**
  Playwright's `page.route` serves a file of our own to the test browser
  alone - HEAD's from `git archive HEAD javascript`, or the working tree's
  past a stale copy - while the WebUI, its database and the owner's browser
  stay as they are; no Reload UI. With `page.addInitScript`, a probe runs
  before the page's scripts and watches what they cannot: #128's click
  reaching the document from a detached button, its markup drawn after
  `init()`. Run each side several times: a race shows in some loads only.
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
  A rename by regex: grep for the old name afterwards, in every quoting - one
  that kept off a JSON key of the same name skipped `_upsert("civitai_versions")`,
  and 45 suites failed.
- **A swallowed error looks like an unrelated failure.** A test's own helper
  named `usable` shadowed the imported `usable`; the paging code caught the
  recursion and reported "no models kept".
- **Look at what a run leaves behind.** Node's coverage reports were never
  removed: 9,429 of them, 4.6 GB. Every `--all` parsed them all, and two
  modules deleted long ago stayed "used" in `test_map.json` (92 entries). With
  a tracer that hooked every call, `--all` had grown to 72-83 s; it takes 31
  s since both were fixed. Time a run plain and traced before guessing why
  it is slow.
- **Gate what is costly on the case that needs it.** The tie-break read
  Civitai's order from JSON: for every version, +13.6 ms a grid query;
  counting ties with a window, +25 ms; asked only where an indexed `EXISTS`
  finds a tie, +3 ms. Time each part. A window sorts every row it numbers,
  with every column: numbering a version's files in the grid's wide rows took
  a 50-card page from 40 ms to 70; the same count from a narrow grouped CTE,
  joined, to 43.
- **Compare a round of changes as a whole, after it.** Every refactor of the
  0.44 round passed its suites. Comparing the code before the round (dc67df9)
  with after it (cce6e8f), with seven reviewers in parallel, found nine
  regressions none had caught - a ControlNet filed as a checkpoint, a
  resource's Download refused as "already downloading", a reloaded page
  running two copies of its shared modules (#118-#126).
- **A finding is a claim until it is surveyed.** Of those nine, six were
  fixed; three were closed once read against the code and the library: a
  re-download that could not happen (#124), a click that now closes a dropdown
  as every other click did (#123), and a level that concerned no file of 1,196
  sidecars and was not hidden by the default filter (#125). Survey each - the
  code, a count from the real data - and put it to the owner with a
  recommendation. #128's cause, read from Gradio's Tabs bundle (the clicked
  button replaced before the click reaches the document), was set aside when
  a click on the tab ran the saved search (2026-10-04) - and was right: a
  probe on the live page saw the click reach the document from a detached
  button, 3 loads of 3 (2026-10-06). One success does not clear a race;
  measure it over several loads.

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
- **Forge and the library spell one path two ways** - case, which Windows
  ignores and SQL does not. Compare paths with `COLLATE NOCASE`
  (`library_spelling`), never `=`. A version's row by its path goes through
  `_stored_spelling` (`db/models_ops.py`) - the exact spelling first, then
  ignoring case: 0.44.8 did that for the upserts alone, and every other read
  and write by path missed a file a walk spelt another way, which a sync then
  hashed and looked up on every run (#120).
- **Civitai's search has no random order, and pages by cursor alone** - `page`
  is ignored. A fair random draw goes by model ids (`random_draw.py`): `ids`
  takes about 4,000 in one request, bounded by the URL's length (some 32 KB),
  not their number - so its commas go unencoded, as `%2C` they made 3,500 ids
  35 KB and a 431. Civitai's own filters apply to the ids; a text query
  ignores them. More than 100 matches come back as the first 100 by the sort,
  with a cursor: a draw that kept only those favoured the most downloaded.
- **Civitai's image ratings miss some.** 256 of 31,745 PG/PG-13 images in one
  library had explicit prompts; Civitai rates 95% of the images using those
  words X or XXX.
- **Civitai's CRC32 is not always in zlib's byte order.** For `supe10` its list
  gives `8EAD4C97` where zlib gives `974CAD8E` (2 of 1,190 files compared; the
  other one's sidecar was another tool's). A CRC32 lookup misses such a file;
  SHA-256 finds it.

### The code

- **An import inside a function hides a cycle; it does not break it.**
  `architecture` imported `file_identity` that way while `file_identity`
  imported it at the top: one moved line from failing at startup. The cut was
  in the wrong place - the database part sat in the header reader - and
  `tests/tools/check_import_cycles.py` now counts every import, wherever it is.
- **Stamp what SQL filters on.** A per-image check is cheap in the browser, on
  a page of images; across the grid's queries it was 2.7 s against 4 ms.
- **Choose the page, then look up its details.** Filter, group, sort and limit
  first; per-row lookups after. With an index in the order the lookups read.
- **A table holding another source's facts is built from that source's
  fields, not from the old table's columns.** v32 split `model_versions` into
  what it held, and Civitai's own id for each file - which a sync, a download
  and a scan all had in hand - was found missing only once a column wanted it.
- **Saying nothing is not a value, in a merge or a view.** v32's merge of a
  version's copies took "the first that says something", and a version whose
  only copy said Unknown came out NULL - read as PG; `LIBRARY` defaulted every
  NULL stat to 0, meant only for a file with no version. Where no copy says
  more, keep what they hold; default only the rows the default is for.
- **A bool is an int.** An enum checked `isinstance(value, int)` before
  `bool`, so a model's `nsfw: true` read as bitmask 1 - PG - and its own
  branch for booleans never ran. Test for `bool` first.
- **`check_python_references.py` does not model `@staticmethod`** called on an
  instance; make such a helper a plain method rather than leave a red check.
- **`check_js_references.mjs` reads a regex literal as code**: in
  `/\b(error)/` it saw a call to `b`. Build such a pattern from a string,
  `new RegExp('\\b(error)', 'i')`.
- **Search the page too before saying the extension does not do something.**
  "Nothing refreshes Forge's checkpoint list after a download" was said from
  a search of the Python alone; `downloads.mjs` presses Forge's own refresh
  (`refreshWebUiModelList`) once a batch of downloads lands.
- **Forge Neo:** T5 and UMT5 files load only in Hugging Face's layout; switching
  a UI preset brings back that preset's checkpoint; Flux.1 and Flux.2 share
  block names and differ in MLP width, which a LoRA's shapes show. It lists
  VAEs and text encoders by file name (`refresh_models`,
  `modules_forge/main_entry.py`): a name in two folders shows once.

### The environment

- **This is Windows: paths are case-insensitive.** `claude.md` and
  `CLAUDE.md` are one file, and deleting the "duplicate" deletes the
  original - which is how `CLAUDE.md` once had to be written twice.
- The WebUI may not be on the default port. From WSL it cannot be reached
  directly; Windows' own `curl.exe` can.
- Run the tests with the WebUI's own Python - it has FastAPI and torch - and
  Windows `node.exe` for the browser suites. Neo's venv is Python 3.13
  (`sys.monitoring`; comprehensions inlined, no frame of their own); the
  original Forge's is 3.10, so the tracer keeps a profile-hook fallback.
- The project's hook ("Testing") reads the text of every Bash command, so it
  also refuses one that ends in the runner's path - a `cat`, a `grep`, a line
  of a commit message. Put the path in a variable (`F=tests/ru; F=${F}n.py`),
  or run a script file.
- WSL's shell here is zsh: `noclobber` is on and `cp` asks before overwriting
  (see "Make sure the old code is what ran"), and `echo` turns a Windows
  path's backslashes into escapes - keep a path in a variable, or use
  `printf`. A word starting with `=` is looked up as a command: `echo ======`
  fails ("= not found"); use `printf -- '-----\n'`.
- Windows' Python cannot lock a SQLite file on a WSL path: a throwaway
  database goes under `tests/work/`, on the Windows drive.
- To run Neo's detector outside the WebUI, put Neo's root and its
  `modules_forge/packages` on `sys.path`: with the packages alone, every
  checkpoint came out without a class.
- `gh` is Windows' `gh.exe`, and cannot tell the repository from `origin`,
  which goes through an SSH host alias: pass `--repo
  therestlesscat/sd-webui-forge-model-manager`.
- **Neo's `webui.bat` calls `webui.settings.bat` first, when there is one**,
  and 7870's arguments are there: `webui-user.bat`'s are overridden, and were
  once read as the real ones. What a running WebUI was given: ui-options'
  `path_roots`.
- **A WebUI that dies without a traceback: read Windows' event log.** One Neo
  died in `c10.dll` (0xc0000005) five seconds after System's
  Resource-Exhaustion-Detector (id 2004) named it at 55.1 GB of commit,
  against a 110 GB limit, while another program held 61 GB. Application's id
  1000 has the crash; neither reaches the console.

## Branches

- **`main`** is the default branch: what "Install from URL" clones, where a
  commit's "Fixes #N" closes the issue, and whose `version.json` installs of
  `main` read for a new version.
- **`dev`** is where the work is committed, and what every install from
  before `main` existed follows - Forge updates a copy from its own branch
  (`origin/<branch>`), so they stay on `dev`.
- **`rc`** is for trying a release before it goes out; it is pushed first.
  GitHub acts on "Fixes #N" only on `main`, so a push to `rc` labels each
  open issue a commit there fixes `fixed-in-rc`, with a comment naming the
  commit (`.github/workflows/fixed-in-rc.yml`): an open issue with the label
  is done and waiting for a release, and closes when it reaches `main`.
  "Refs #N" names an issue without either, and each issue needs its own
  word - `Fixes #84, fixes #85`: four refactor issues said "Refs", and an
  empty commit (7f9e228) had to name them for `main` to close them. A fix
  for two issues names both: #129, fixed by f769b6f under "Fixes #11", needed
  an empty commit too (581c84a).
- **Whenever `main` is updated, `dev` is updated at the same time, to the
  same commit** - one push, never one without the other, and every tag with
  it: `git push origin dev dev:main --tags`. A release on `main` alone leaves
  every `dev` install behind and told of nothing; on `dev` alone, new installs
  miss it and its issues stay open.
- **"Push to dev/main" means everything: both branches and every tag.** The
  tags are lightweight, so `--follow-tags` leaves them behind. Pushes of the
  branches alone left 52 tags local (v0.44.0-v0.48.6), pushed apart later.

## Testing

Test what a change needs, not everything.

- **While working:** `python tests/run.py --changed` runs only the suites the
  uncommitted changes need, chosen from a record of which files each suite
  uses, and says why it chose each. Add words to narrow it further
  (`python tests/run.py --changed chips`), or name suites alone.
- **Before a commit:** `python tests/run.py --all` - everything, which also
  records afresh which files each suite uses. Run it in its own call, and
  read its last line before committing.
- A hook in this project's Claude Code settings (`.claude/`, local and
  git-ignored) refuses the runner with no `--changed`, `--all` or suite name
  after it - `--online` or `--tools` alone included - so a full run is always
  one asked for with `--all`.

`--all` runs every suite, four at a time, in about 35 s; `tests/README.md`
says why no wider, what each suite covers, how the choice is made, and how to
write one.

**A test run takes a minute at most; one that needs longer is asked for
first.** That is the owner's rule. Start every run under a time limit
(`timeout 60`), and if it would need more, ask before running it. After a run
that was stopped, look for what it left running and stop only that.
