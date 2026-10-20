# `javascript/shared/`: what the tabs share

Each shared module, and the rules for the parts of the page they draw.
`javascript/AGENTS.md` applies here too; Claude Code loads it with this one.

## Layout

### `javascript/shared/`

What the tabs share, one module per job (#93), each asked for under one
version (see `javascript/AGENTS.md`, "The WebUI's rules, which are not
obvious"). None does anything as it is imported: one
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
| `tabs` | the WebUI's tabs by id: `showTab` (resolves once Gradio shows it), `tabButton`, `tabShowing`; and `goToTab`, the one way a jump shows a tab (#263) - at its tab bar at once, then a place, an element, or what an entry answers, unless the person scrolls meanwhile |
| `core` | what every part uses: `TIMING`, `apiCall`, `escapeHtml` (the one escape), `dataAttributes` (what an action reads), `holdPage` (the page held still while the viewer, a dialog or the settings window is open over it - the one place that sets `mm-modal-open`), `setText` / `setTitle`, `safeId` / `safeUrl`, `sanitizeHtml`; numbers, sizes and dates as a person reads them |
| `ui_options` | the server's ui-options, asked once a page: the API-key banner, which judges NSFW, how a gallery opens, whether your generations are shown |
| `notes` | notes to the user, at the top of each tab; a button is drawn only while what it opens is there - a Sync, while the Model Manager is available |
| `jobs` | the long job, Sync with Civitai: its dialog, starting, following and cancelling one, and finding one still running; the Model Manager connects it to its status line and grid (`connectJobs`), a note's button opens its dialog by name (`sync.showDialog`, offered once the Model Manager starts it) |
| `update_notice` | "vX available" beside each tab's version |
| `nsfw` | an image's level as the server stamped it, its badge, and the levels one can rate; the page's one table of levels and their names (`NSFW_LEVELS`), a copy of `nsfw.py`'s held to it by `page_constants_test.py` |
| `media` | Civitai's images and videos: the copy for a width - or an image's upload, where the settings say so (`asUploaded`, #192; a video stays a copy) - the fallback, loading them as they come into view |
| `grid` | cards, the grid and its page strip, its rows kept even, and the card size the server gave a tab (`createCardSize`) |
| `image_card` | a Civitai image's card and its Show All window, the same in both tabs; your generations' cards show its text; the card's text, `imageDetailsHtml`, which the Civitai Images viewer draws too (#267); its sampler and schedule type as the server stamps them beside the level (`mm_sampler`, `mm_scheduler`, `send.stamp_readings`, #302) |
| `gallery` | a gallery's loading bar, filter banner and page notes, and its pages - kept, drawn and paged through by one object per gallery (`createPagedGallery`), each tab keeping only how it fetches a page; and scrolling to a gallery's top |
| `filters` | what both filter bars share: base models in order, the size boxes, a saved search and Save Search's flash, the checkpoint-type filter greyed while Type is not Checkpoint |
| `tiles` | the tile grid the Generations and Civitai Images tabs draw (#209): a wide image's columns, a level's header and Back, the next part as the end nears; and how the tiles are placed, a setting per tab (#240) - Classic, the browser's grid, or Fast, the default: the tab places each tile by the browser's own dense rule (`placeTiles`) and keeps on the page only the rows within 3,000 px of the view (`placedGrid`) |
| `grouping` | Group by and search for the tabs of tiles, the Generations and the Civitai Images tabs alike (#283): what a Group by value groups by, one grouping or two; its menu, each grouping with what to group its groups by then; the search box as it starts. Each tab says its groupings and what a choice does; neither imports the other's script |
| `generations` | your generations, as a model's gallery and the Generations tab both show them: a thumbnail, the rating and delete requests, a shift-click's range, the select bar and bulk delete, the rating row. Each tab draws its own cards or tiles |
| `downloads` | a version's Download button, and the downloads panel both tabs show; the list runs once a tab that downloads starts it, and stops with the last; Send's Resources and chips offer Download only while it runs |
| `send` | Send to txt2img / img2img, from any tab: Forge's VAE / Text Encoder control, its UI preset, the one send plan (`/model-manager/send/plan`, `send.py`) and the source it hands the tab's loader, which builds the infotext on the server and sets the schedule type and Hires fix in the paste's own event (#302), an image-to-video model's start frame (`sendGalleryImage`, `sendInfotext`); and, with `into`, the picture itself into one of img2img's modes (#299, `IMG2IMG_SENDS`, the ⋯ menu's items) - put in by a canvas button of the mode's own, never the settings' loader (an answer that leaves a canvas as it is breaks it for the session: `scheduler/load.py`), its layer emptied, a missing checkpoint said rather than a stop |
| `chips` | an image's LoRAs and embeddings as chips under the prompt, after a send: their rules, and the chips on the page |
| `resources` | an image's resources and the Resources dialog every gallery opens, each passing the version its gallery is of (`exclude`): which Civitai versions they are, whether the library has each, and a Download into it - through the downloads list, which polls for it, as for every download |
| `wan` | a video's frames and size as Wan makes them |
| `dialog` | every question the page asks, and the container any dialog opens in (#292): the browser's <dialog> opened as modal - above everything, the page behind held and out of reach, Esc and a click beside it closing the top one alone and going no further, focus in and back - with what the caller may turn off (`openDialog`); a question laid out from parts handed as data, never markup, its buttons by type, `primary`, `secondary` or `danger` (`ask`); the progress popup (`showProgress`); whether a dialog is showing (`dialogShowing`). No templates: each caller lays out its own question, Cancel first and the main action last by convention, so the default focus - the first button - is the safe one. Every window is in the container too, its content its own: the settings window, both Sync windows (their <dialog> in the tab's markup), and Show All, Resources and a task's details (`openMetaModal`, which draws an open one again in place) |
| `menu` | the ⋯ menu a tile opens, in the Generations and the Civitai Images tabs (#298): drawn from items each tab hands it, measured, and placed inside the window - below its button, else above; growing left, else right; moved in, and capped with a scroll of its own, where neither fits (`placeMenu`, numbers in and out); closed by a click outside it, Esc - caught on the document's way down, so neither tab's keys nor the WebUI's interrupt hear it - a scroll of the page, a resize, or its own ⋯ again (`closeMenuOf`, which each tab's action asks first: the click-away listener closed it, and the same click opened it again); one for the page, its listeners through the opening tab's scope; and an item to another tab, greyed while that tab is not available (`tabItem`). Placed by its right edge alone before, it ran past the window's left edge and below its bottom |
| `settings`, `viewer` | the settings window, and the image viewer every gallery opens - with the modal the metadata and Resources windows open in |
| `previous_position` | Previous Position (#250): the place a tab's action noted before it took the page to another tab - a Send, a link to the Model Manager or the Civitai Browser - and the button back to it, in the Model Manager, the Generations and the Civitai Images tabs. Noted by the action, never by scrolling: the way up to the tab bar would be noted too. Each keeps it in the browser's storage, so it survives a reload (the tile tabs since #264). In the tile tabs the place is the tile left, not a height, and the button says ↓ Back to image (#264): the Generations tab lists the newest first, and each batch generated after a Send pushed every tile down. It is named by what it shows - the image, its batch, the groups opened to reach it - and the button looks for it in the grid shown, the image or the batch or group that holds it: through the parts loaded, then loading more up to 20 (`SEEK_PARTS`), then on only if the person says so; while it loads, the button reads Looking... and a press stops it; not found, the page stays (`seek`, over the grid each tab hands it). They forget it as their grid starts again - Refresh, a group opened, Back, a search - but not as the tab starts after a reload |

## What the pieces assume about each other

### The page

**A stopped Send's Resources dialog offers what the library holds** through
the `useInstalled` the Send hands it: another file of the image's version
when one is held, else the model's other versions - a tick for one, a
dropdown for several (#278). Until #278 only your generations' Send handed
it, and a Civitai image's offered nothing.

**The settings window holds every section's fields, and shows those of the
tab it was opened from.** Opened from the Model Manager, the Civitai
Browser's page-size field was hidden and a Playwright fill timed out; another
section's setting is saved through `POST /model-manager/settings` (#230).

**One downloads list for both tabs.** `downloads()` in
`javascript/shared/downloads.mjs` polls once and draws into each tab's panel -
started by the Model Manager and the Civitai Browser, null before. It
is module state: the tabs share one copy of the module (see
`javascript/AGENTS.md`, "The WebUI's rules, which are not obvious"), and so do
the notes, the update notice, the Your generations switch
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

**Send sets a field through Forge's paste wherever the paste has one** (#138).
Gradio 4's dropdown takes a value only from a choice pressed in its open
list: writing its text and firing its events changes nothing, and Gradio
puts the text back once the field loses focus. A control in a closed
accordion is hidden, takes no focus and opens no list - Hires fix's upscaler
sits in one, and pressed there it was never set, the text left blank. So a
field the paste knows goes in the infotext the server builds
(`send.civitai_infotext`: the upscaler, ADetailer's switch, a video's
frames), which sets it hidden or not, and turns Hires fix on only with
`Denoising strength` too. Send presses an option itself (`chooseOption`)
only for a control the paste does not cover and that is always shown - the
UI preset, the VAE / Text Encoder control - and gives up, the text as it
was, when no list opens. The schedule type the loader sets in the paste's
own event (#302); the page presses it only where Forge's own paste button
pasted instead. A
suite's stand-in has to behave so: a plain `<input>` stood in for the
upscaler, and the suites passed while it was never set.

**Forge's paste reads the infotext by its own rules.** The last line is
read as settings only when it holds 3 or more `key: value` fields;
otherwise it becomes part of the prompt (Neo's `modules/infotext_utils.py`,
line 365). And `, width:` and `, height:` are rewritten to `Size-1` and
`Size-2` (line 389), so a metadata `width`/`height` the infotext passes on,
as it does every field it has no rule for, overrides its `Size`: a 2304 x
1664 picture whose metadata said 512 x 512 went in at 512 x 512. Since
0.67.0 the size rule leaves the data's width and height out where their
shape is not the picture's (`send.civitai_meta`, #302). A line of two
fields became prompt text, so a short one writes `Size-1` and `Size-2`, and a
value with a line break is quoted as Forge quotes it (0.67.5, #313). A sampler
Forge does not know becomes its first, DPM++ 2M, without a word
(`get_sampler_and_scheduler`): Send matches by Forge's own names - aliases and
k-diffusion function names (0.67.6, #309) - and names what this WebUI lacks,
setting nothing (0.67.7, #307). Both parsers turn `Sampler: Undefined` into
Euler; the original Forge's writes `Schedule type: Automatic` where the text
gives none - no schedule type given. Neo's drops `Clip skip` from every paste
(`e447ffe1`, no reason given), where the original Forge makes it an Override
settings entry, but for Civitai's Flux images. An Override settings entry
applies to each generation and is put back after (`processing.py`, 802-846):
setting Forge's Clip Skip itself carried one image's value into later
generations, other models' included, so Send adds the entry (#318). And Neo's
Apply settings sends every field the Settings page shows (`run_settings`): a
setting changed on the server, and not on the page, is written back.

**A grid placed by the tab (#240) has the browser's habits to reckon with.**
Fast (`tiles.mjs`, `placedGrid`) keeps only the rows within 3,000 px of the
view on the page, and that changed four things the browser's grid never
showed:

- **A removed image keeps downloading.** The browser does not stop a
  download for an image taken off the page. `media.mjs` freed its place among
  the 64 loading at once (#213) as it was removed, and with Civitai's answers
  held 2 s a fast scroll had 214 in flight. A place now frees at the image's
  own load or error, or after 30 s.
- **The browser's scroll anchoring stays on.** `overflow-anchor: none` on the
  grid made the browser anchor on what is below it - the grid's end - and
  follow it as each part made the grid taller, which brought the end near and
  loaded the next: 145,153 px when the drag stopped, 2,195,453 px a minute
  later. No suite can see it; the test pages have no anchoring.
- **Measuring a collapsed grid pulls the page back.** A reset collapsed the
  grid, and placing measures it: Rate at 6,000 px down put the page at 0. A
  redraw of the same tiles (`reset({ keepHeight: true })`) keeps the height
  until they are placed again; new data still collapses it.
- **`display: contents` has no box.** A tile's set is one, so
  `scrollIntoView` on it scrolled nothing, and closing the viewer left the
  Classic grid where it was (#253): `showTile` asks the tile itself.

## Two WebUIs: everything has to work in both

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
  (`forge_additional_modules`) actually holds. It is the patch of several
  changes that fails: over 488 Civitai sends (2026-10-18), 4 of 13 sends that
  made 2 or 3 changes ended with Forge holding a state from partway through,
  against 0 of 88 single changes (#3).

## Kept elsewhere, and true here too

Rules whose main code is in another folder, which this folder's code must
keep as well:

- `model_manager/AGENTS.md`, "`nsfw.py` is the single source of truth".
- `model_manager/AGENTS.md`, "Two rules for one thing drift".
- `model_manager/AGENTS.md`, "A path is shown from where Forge was told to
  look".
- `model_manager/AGENTS.md`, "A refresh replaces a gallery whole".
- `model_manager/AGENTS.md`, "A long job is one of its kind".
- `model_manager/AGENTS.md`, "The download queue is the service's own".
- `model_manager/AGENTS.md`, "A gallery switch's number holds when it is
  flipped".
- `model_manager/AGENTS.md`, "A synced image is the recorder's second witness".
- `model_manager/AGENTS.md`, "A shared library holds the other WebUI's files".
