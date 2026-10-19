# `javascript/`: the page

How the WebUI loads the page's scripts, and what the tabs' scripts and the
shared modules assume of each other. `javascript/shared/` has a file of its
own; `javascript/tabs/` has none, and this one is its.

## What the pieces assume about each other

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

## The WebUI's rules, which are not obvious

- **Esc that reaches the page interrupts a generation.** The WebUI's
  `script.js` (line ~199) listens for Esc on the document and presses
  Interrupt while one runs - on 7870 it logs "Cannot read properties of null
  (reading 'style')" when its button is missing. So a dialog stops Esc at
  itself (`shared/dialog.mjs`) and keeps focus inside: with focus fallen to
  the page, Esc reached that handler (#292).
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
- **A tab switch keeps the page's one scroll.** A jump from deep in a gallery
  opened the other tab at that depth: its loading bar shrank the page to
  about 2,100 px, the view was clamped to its bottom, and Chrome's scroll
  anchoring carried it back to 3,730 as the images came in. The first visit
  lands at 0 only because the empty tab is one screen tall. Every jump goes
  through `goToTab` (`shared/tabs.mjs`, #263), and an entry answers where it
  lands.

## Learned the hard way

### Proving a change

- **A trace settles a delay.** #112's viewer "closed late": the owner's
  DevTools trace (Performance, Save profile: a `.json.gz`) showed our click
  handler at 3.0 ms and the frame on screen 8.2 ms after the release - the
  65 ms was the button held. Event Timing's `duration` runs from the input to
  the frame on screen. A trace may open with a focusing click: anchor on the
  input being measured. Esc, read the same way, was 19.6 ms.
- **After a sync, its log covers the Model Manager.** The grid and the
  details are `display: none` until the log's Hide (`mm_sync_log_hide`), and
  Playwright's clicks failed as "not visible" (#229). The bar's text keeps its
  last words ("Syncing: 8/8 - Preparing..."); the sync's end is in
  `mm_status`.
- **A count of listeners is no leak until it grows.** Neo's window holds
  234 `scroll` and 234 `resize` listeners from Gradio's bundle from the
  start: one pair per dropdown, 234 `.gradio-dropdown` (2026-10-18). Group
  them by the script and line that added them (CDP's
  `DOMDebugger.getEventListeners`, with `Debugger.scriptParsed` for the
  scripts), and count again later, before calling one a leak.

## Kept elsewhere, and true here too

Rules whose main code is in another folder, which this folder's code must
keep as well:

- `model_manager/db/AGENTS.md`, "A version is one row; its files are rows of
  their own".
