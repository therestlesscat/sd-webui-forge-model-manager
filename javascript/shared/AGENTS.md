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
| `tabs` | the WebUI's tabs by id: `showTab` (resolves once Gradio shows it), `tabButton`, `tabShowing` |
| `core` | what every part uses: `TIMING`, `apiCall`, `escapeHtml` (the one escape), `dataAttributes` (what an action reads), `holdPage` (the page held still while the viewer, a dialog or the settings window is open over it - the one place that sets `mm-modal-open`), `setText` / `setTitle`, `safeId` / `safeUrl`, `sanitizeHtml`; numbers, sizes and dates as a person reads them |
| `ui_options` | the server's ui-options, asked once a page: the API-key banner, which judges NSFW, how a gallery opens, whether your generations are shown |
| `notes` | notes to the user, at the top of each tab; a button is drawn only while what it opens is there - a Sync, while the Model Manager is available |
| `jobs` | the long job, Sync with Civitai: its dialog, starting, following and cancelling one, and finding one still running; the Model Manager connects it to its status line and grid (`connectJobs`), a note's button opens its dialog by name (`sync.showDialog`, offered once the Model Manager starts it) |
| `update_notice` | "vX available" beside each tab's version |
| `nsfw` | an image's level as the server stamped it, its badge, and the levels one can rate; the page's one table of levels and their names (`NSFW_LEVELS`), a copy of `nsfw.py`'s held to it by `page_constants_test.py` |
| `media` | Civitai's images and videos: the copy for a width - or an image's upload, where the settings say so (`asUploaded`, #192; a video stays a copy) - the fallback, loading them as they come into view |
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

### The page

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
field the paste knows goes in the infotext (`buildInfotext`: the upscaler,
ADetailer's switch, a video's frames), which sets it hidden or not, and
turns Hires fix on only with `Denoising strength` too. Send presses an
option itself (`chooseOption`) only for a control the paste does not cover
and that is always shown - the UI preset, the VAE / Text Encoder control,
the scheduler - and gives up, the text as it was, when no list opens. A
suite's stand-in has to behave so: a plain `<input>` stood in for the
upscaler, and the suites passed while it was never set.

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
  (`forge_additional_modules`) actually holds.

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
