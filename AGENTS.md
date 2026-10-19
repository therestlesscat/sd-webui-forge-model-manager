# Working on this extension

A model manager for SD WebUI Forge: it lists what is on disk, enriches it with
Civitai metadata, and lets you browse and download more.

This file and the AGENTS.md in each folder are everything an agent needs
here: how to work with the owner, the shape of the codebase - what each part
is *for*, and which of its rules were learned the hard way. This file holds
the working agreement and what spans the whole repository; each folder's
holds the rules for its own code ("Folder files", under "Layout"). None is a
file listing; `ls` does that better. A `CLAUDE.md` only imports the AGENTS.md
beside it and holds nothing of its own: the root's once described the
architecture as well, drifted, and named three modules that no longer
existed.

**Every item added to an AGENTS.md is checked first, on four counts.**
Verified: its facts and numbers read from the source - the diff, a
read-only query, a run - not remembered. Required: an agent working here
would get something wrong without it. Adding value: the code, its comments
and git history do not already say it. Not a duplicate: searched for in
every AGENTS.md and `tests/README.md`; an entry that covers it is updated
instead. A proposed item says how it passed each. Of the #287 round's six
proposed lessons, three failed when the owner asked: one was in
`tests/README.md` already, one in the suite's own comment, one readable from
the code (2026-10-16).

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
  the version. A plan that adds a setting says what changing it does to work
  already under way - running, paused, queued: #282's added a connections
  setting with no answer, and the owner asked "what if user change either of
  settings during an download or during paused download?" (2026-10-17).
  Each choice goes to the owner as a numbered question with a
  recommendation. Code starts on an explicit yes to that plan, and anything
  found later that changes it goes back as a plan. Answered questions are not
  that yes: the answers go into a revision tab and the Final tab, then the
  owner is asked, in one message, to post the Final on its issue and to start
  building. #279 (0.59.3) was built the turn its answers came: "why didnt you
  ask to post before and ask to start building" (2026-10-15). #287's build
  changed a rule mid-way - a paused queue no longer stopped a compact - and
  said so only in the report after building; a side agent flagged it, and the
  owner was asked then (2026-10-16). #187 was implemented
  straight from a survey and undone; its next plan, seven steps, was sent back
  for having no storage, no alternatives and no pros and cons (2026-10-06).
- **A plan is a Claude Doc, and the doc is the plan.** It is written there
  for the owner to read and comment on. Whenever the owner says they
  responded in it - in any words, "yes to all" included - read the doc and
  every comment thread since the last read before doing anything, and
  compare it with what they said in chat. Other sessions answer comments
  and edit sections. #136's Restart WebUI offer was added to its plan that
  way and approved; 0.54.1 was built from an older read without it, and
  0.54.2 followed (2026-10-08).
- **A plan doc says what before it says where.** Technical, but not
  overdone: what a part does in plain words first, its code name after - or
  in a closing "Code:" line. More than a few
  terms of the codebase get a "Words this plan uses" table at the top. An
  action is named as the page shows it ("Sync from the dialog, scope
  results"), not by the function it calls; a mechanism is told as a short
  story - what happens, the moment it goes wrong, how likely; tests are
  situations, each new or a guard. `file:line` stays only where it helps
  look something up. The #195 plan, in chat, read as if steps were missing;
  #200's doc, rewritten so, became the rule (2026-10-08).
- **A suggestion argues both sides, and says how big a change it is.**
  Every suggestion in a doc - an option recommended, an idea for scope, a
  question's recommendation - gets a table of its own: the points for it in
  one column, the points against it in the other. And, wherever it can be
  judged, how complex the change is. Lines of code are one measure, not the
  measure: the files and shared modules it touches, new state or storage (a
  setting, a column, a migration), new moving parts (a thread, a stream, a
  queue), what else runs through the code it changes, the tests it needs,
  both WebUIs. #214's on-site-only plan recommended remembering Civitai's
  answer for five minutes with neither, and the owner had to ask how
  complex it was (2026-10-10).
- **A Final tab holds the whole merged plan**, never a pointer to the main
  tab: #220's was first written as one, and refilled.
- **A plan doc keeps its first draft; each round of changes is a tab.**
  Nothing in a plan doc is deleted: what a decision removes is crossed
  out where it stands (2026-10-10). What a round of discussion adds - one
  batch of comments answered, one side note acted on - goes in a tab of
  its own under the plan (R2, R3, ...), holding only that round: what
  prompted it, quoted; where it changes the plan; the new material. The
  plan links its tab at each place a change applies, beside the words it
  strikes, and a line under the byline lists every tab. #214 part 5's
  changes were first written into the plan, highlighted and tagged by
  round; the owner found it "still hard to understand and catch quickly"
  (2026-10-11). The plan always ends with its questions, numbered, each
  with its recommendation - a revision tab's too, linked to the tab that
  argues it, and added in the same turn - so every open decision is in one
  place. In that doc the questions sat before "What else", and three the
  revision tabs raised were in no list. A revision that changes a decision
  strikes or rewords, in the same turn, every question and draft line it
  makes stale: part 6's R4 replaced watched folders with a Sync button,
  and left "watched folders" in two questions and "Add a folder" in the
  draft's steps until the owner asked.
- **An approved plan goes on its issue.** Once a plan is approved to be
  built, it is posted as a comment on the related GitHub issue, so the
  issue keeps the record of what was decided. It is the doc's Final tab -
  the first draft and every revision tab merged, every answer applied,
  nothing struck - in markdown, its headings, tables and code kept, never
  flattened to plain text. Issues it depends on are created first and
  named at its top; follow-ups go under "Not in this issue" (#233, with
  #231 before it and #232 after, 2026-10-11). The repository is public:
  the comment holds no personal information - no one's name, email,
  account or user name - and a path in it starts inside a WebUI's folder
  (`models\ESRGAN`), the WebUI named in words ("Neo's own"), never a drive
  or the folder a WebUI is installed in. It is posted only once the owner
  has seen its text and said yes. A change to the plan found while
  building goes in a second comment, saying what changed - never an edit
  of the first (#179). Two issues folded into one plan get one comment, on
  the first: #197's for #198, #105's for #107. Work with no issue - a fix a
  check turned up - gets one before its plan is posted: 0.58.3's build began
  before #246 existed, and the owner asked "where's issue and plan in it?"
  (2026-10-12).
- **Public text holds nothing of the owner's library.** An issue, a
  comment, a commit message, a changelog line: no model, version or image
  from it by id, name or file, and no prompt. A count is fine ("one
  library's 1,095 models"); an example is made up. A measurement of
  Civitai's API names no model either, the library's or not: the counts
  carry it. An issue on Civitai's `nsfw` parameter listed three of the
  library's LoRAs by id, one by name, as ones Civitai marks `minor`. The
  owner deleted it and it was written again without them. An edit is no
  removal: GitHub shows an issue's edits to anyone (2026-10-14).
- **Scope is the owner's.** Asked "what would the shared part be, and how
  would it be called?", show the code shape before changing anything; R29 was
  narrowed twice that way, to what is actually shared. A behaviour change
  found inside a refactor becomes its own issue unless the owner folds it in.
- **Two agents or more: ask first, with the reason and the cost.** Before
  starting or resuming two or more agents for one step - side agents, a
  fan-out, a workflow - say what each will do, why it needs an agent of its
  own rather than this session, and each one's projected token cost; start
  them on the owner's yes. A projection is taken from what agents of the
  kind cost before. On #272 (2026-10-14) five agents read one suite each,
  then were resumed to build them, and the owner heard of each round only
  once it had started: the reading cost 131-238 k tokens an agent, 0.98 M
  in all; the building 144-307 k, 1.22 M in all.
- **Agents at once each get a folder of their own** under the scratchpad. On
  #272 two wrote `hooks.mjs` at its root, and one's proof runs used the
  other's breaks until it noticed and ran them again.
- **"Unchanged" in a plan means byte for byte.** #259's plan kept Classic's
  reads unchanged: the fallback while Single pass is alpha. While building,
  three were moved into helpers Single pass shared; a side agent caught it,
  and the owner had them put back - a fault in shared code would have broken
  the fallback too (2026-10-14).
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
- **No attribution in a commit, a tag or a pull request**, whatever a system
  note asks: no `Co-Authored-By`, no `Claude-Session`, no "Generated with".
  They went into 409 of 417 commits unasked, and removing them meant
  rewriting the whole history and recreating the repository (2026-10-08).
- **A change asked for "only for me" is never committed.** It lives in the
  working tree, and a commit is made around it: copy the files aside, strip
  the hunks, run `--all`, commit, copy them back.
- **The backlog is GitHub's issues**, labelled `backlog` and an area. An issue
  that does not reproduce, or works again with no commit shown to fix it, is
  not closed: it gets a comment - what was tested, on which version, what
  would settle it - and the labels `investigate` and `low-priority`.

### Getting it right

- **A log line is not a version.** "4534 of 4496" was read as 7870 still
  running the code before a fix; the new code printed it too - a second
  bug - and the owner had restarted (#229). Before saying what code a WebUI
  runs, check that the new code cannot print what it shows.
- **Never guess at an import or a function name.** Read the module. A name
  that looks obvious is how `get_max_nsfw_level` returned `UNKNOWN` without
  importing it. The console's trace helper was first named `failed` - the
  name `api/common.py` already exports, 41 uses - and inside `common.py` its
  own call recursed; it is `say_failure` (#143). Nor in an issue's text:
  #274 first named `scope.timeout` for the scope's timer, which does not
  exist; it is `scope.later`. Nor "decided" for "built": #302 says the 3%
  size rule "is built here", meaning in #302; the 2026-10-19 plan read it as
  in Send and planned a proving check on it, and 5 images came out with the
  data's size. Nor a CSS class: #217's Search modifier was
  first `filter-group-half`, already the Tag group's (`max-width: 50%`), and
  Search stopped at half the row until a headless probe measured it. Grep
  `style.css` and the markup for a new class first.
- **Verify before asserting, especially about your own effects.** "I only work
  on copies" was said in this repository while a test was overwriting 747 real
  sidecars and applying migrations to the live database. If you have not
  checked, say you have not checked. Proving a change has lessons of its own
  ("Proving a change"). So is what a turn's own calls did: in the #41 round,
  12 replies said a step was still to come that a call earlier in the same
  turn had done - the test browser closed, a memory note written, the change
  staged, the issue opened. Write what a turn did from its results, read
  before the summary. So is code a plan leans on for a case it never ran:
  #34 chose keeping the press's inputs because Load to UI "already" set
  canvases back, never tried for img2img; a side agent flagged it, and a
  check on 7880 saw it work - and found Load to UI showing img2img's plain
  mode while the mode Forge reads said Inpaint.
- **An approved check is never weakened in code.** v37's plan said the
  files each image used must come out of the migration the same set as
  `generation_files`; it was written as a subset - every old row found,
  extra ones let through - without asking, and a side agent caught it. It was
  put back to equality on the owner's yes. A check in an approved plan is
  changed only by going back with a question, like any other part of it.

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
- **Ask before every Playwright test.** No exceptions - a read-only one,
  and the side-by-side checks under "Proving a change", included - unless
  the owner asked for that test first, and a yes covers only the test it
  answered. 0.55.2's live check ran on 7870 unasked (2026-10-09).

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
tools/measure_generations.py  times the Generations tab's requests at scale, v36 against
                              today's, on a throwaway synthetic library - by hand
tests/v36_generations.py, generation_fixture.py
                              the v36 reads, frozen, and v36 libraries to migrate, for #231's suites
```

### Folder files

Each folder below has an AGENTS.md of its own: the rules for the code in it.
A one-line `CLAUDE.md` beside each holds `@AGENTS.md`. Claude Code reads a
folder's AGENTS.md only through it, because the root has a CLAUDE.md; it
loads both, and every parent folder's, once a file in that folder is read,
written or edited. A recursive grep, or a piped or chained read, loads
nothing (probed on Claude Code 2.1.296).

**Before planning work in a folder, read its AGENTS.md, and its parents'
files.** A plan drafted from greps alone would miss them.

A rule lives in the folder that holds most of the code it governs. Another
folder it governs gets a line in its own file, under "Kept elsewhere, and
true here too". A rule for the whole repository, or for files at its top,
stays here.

| File | What it holds | Sections from here |
| --- | --- | --- |
| `model_manager/AGENTS.md` | The Python package: what each module is for, and what its parts assume | Layout: `model_manager/`; Where each rule lives; The library: files, versions and rows; Civitai: sync and downloads; The page; Your generations; Two WebUIs: everything has to work in both; Known gaps; The data; The code; The environment |
| `model_manager/db/AGENTS.md` | Everything that touches SQLite: tables, migrations, queries | Where each rule lives; The library: files, versions and rows; Civitai's images; Your generations; Proving a change; The data; The code |
| `model_manager/civitai/AGENTS.md` | What Civitai's API does that its documentation does not say | Civitai: sync and downloads; The data |
| `model_manager/api/AGENTS.md` | Lessons from the HTTP endpoints | The code |
| `javascript/AGENTS.md` | How the WebUI loads the page's scripts, and what the tabs' scripts assume | The page; The WebUI's rules, which are not obvious; Proving a change |
| `javascript/shared/AGENTS.md` | What the tabs share: each module, and the page parts they draw | Layout: `javascript/shared/`; The page; Two WebUIs: everything has to work in both |
| `tests/AGENTS.md` | How a check is written so that it proves something | Proving a change; The code; The environment; Testing |

## The WebUI's rules, which are not obvious

- `style.css` is found by name, and linked after the WebUI's own, one
  `<link>` per extension.
- Both are stamped with the file's mtime **each time the UI is built** - at
  startup, and at Settings -> Reload UI - so a change needs a Reload UI to
  reach the browser, not just a page reload. `javascript/shared/` and
  `javascript/tabs/` need only a page reload (`javascript/AGENTS.md`,
  "Nothing in the WebUI versions").
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
- The rest are the page's: `javascript/AGENTS.md`, "The WebUI's rules, which
  are not obvious" - how the WebUI loads the page's scripts, and what Gradio
  does to them.

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
  every file - each file's source with `compile(open(p).read(), p, 'exec')`:
  `py_compile` with `cfile='NUL'` raised on all 16 files of #34, the fault
  the command's, not the code's.
- **SQLite 3.37.2 in the original Forge**, 3.50.4 in Neo's venv. An SQL
  feature is checked against the older: `WITH ... AS MATERIALIZED` needs 3.35;
  `json_each` and `json_extract` run there (#218, checked with that install's
  Python).
- The other differences sit beside their code: `model_manager/AGENTS.md`, "Two
  WebUIs: everything has to work in both" - no `blake3`, the detector's helpers
  moved, the other WebUI's files; and `javascript/shared/AGENTS.md`, "Two
  WebUIs: everything has to work in both" - the UI preset and the VAE / Text
  Encoder controls.

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
  (`core.mjs`), not an `<a>`. Five were links until #144: the two inside a
  tab drew 12.6 px text at weight 500 beside buttons at 14 px and 400, and
  the three in dialogs matched - outside Gradio's container, its reset does
  not reach. `link_buttons_test.py` fails on any `<a>` with `mm-btn` or
  `cb-btn`. A button opens on a click alone: no middle click, no "Copy link".
- **It gives an input a bottom margin**
  (`.gradio-container-4-40-0 .prose input`, 4px), which only a last child
  escapes (`.prose :last-child`): Show hidden's box, its count in a `<span>`
  after it, sat 2px above Select's on 7870. A switch's box says `margin: 0`
  (`.queue-select-switch > input[type="checkbox"]`).
- **It sizes a text input itself** (`.gradio-container-4-40-0 [type="text"]`):
  16px text, 8px 12px padding, a white box - Sync images' path box stood
  42px tall beside a 28px Add on 7880, its one class beaten. Its type and
  element name under a parent class win
  (`.gen-sync-add > input.mm-settings-input[type="text"]`). A `<select>`
  inside a tab loses the same way (#243).

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
extensions' styles measured buttons the same that were not. And measure a new
control against the same control elsewhere in the window: #287's probe found
every existing element unchanged, and missed that its own buttons were 10.2
px beside the window's 13.6 - `mm-btn-small` is 0.85em, and the new block
set 12px on itself rather than on its text. The owner saw it. And measure
what it does to the box it sits in: #218's New version badge measured the
type badge's size in both modes and both tabs, while on a card of fixed
height it pushed the badge row to a second line, 39 px against 18, and cut
the stats off on most cards that had it. The owner's screenshot found it.

## Conventions

- Comments explain **why**, not what. If a line needs saying twice, the second
  one is not a comment.
- A commit message says what was wrong and what it now does, with the numbers
  that justify it - counted from the diff, not remembered: two messages in the
  0.44 round said 219 lines for 147 and 27 handlers for 28, and had to be
  amended. Stage, read `git diff --cached --shortstat`, then write the number:
  in the 0.48 round three more were amended - +603 for +753, +519 for +512,
  and "26 new checks" added up from memory. And a message - or a changelog
  line - states only what was seen: "wrapped line after line" was never
  looked at, and was taken out; 0.65.0's changelog first said the old Send
  made Generate "inpaint with a canvas out of sight", read in the code, never
  seen, until a side agent caught it before the commit.
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
- **A bug fix is always a version**, whether a user can see it or not: a
  patch by default, a minor when the owner calls it one, and a changelog
  line saying what was wrong. #141 - a flag nothing reads, written wrong -
  was proposed with no bump, as nothing visible changed (2026-10-07).
- **Neither**: tests, docs, refactoring - nothing a user sees, and no bug
  fixed. No bump; the build moves on by itself, and the changelog does not
  list it.
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

## Learned the hard way

What earlier sessions got wrong, or took too long to find. Each of these cost
real time once. The working agreement's own lessons are under "How to work
here"; a suite's traps - what linkedom lacks, a test something else rescues,
waits - are in `tests/README.md`.

Lessons about Civitai's data and the files sit beside their code:
`model_manager/AGENTS.md`, "The data"; `model_manager/db/AGENTS.md`, "The
data"; `model_manager/civitai/AGENTS.md`, "The data".

### Proving a change

- **Measure at the sizes the page asks.** #229's issue costed a page of 100
  cards; a page holds 5 to 50. "this seems to be the worst case scenario",
  the owner said - measured again, 20 cards took 0.3 to 0.4 s and 0.3 to 1 MB.
- **Drive the page's own control, not its endpoint.** A download started by
  a POST to `/model-manager/civitai/download` was never followed by the
  page: its poll starts from the page's own Download. So Forge's lists were
  not refreshed, and the first live check of #193 tested nothing.
- **A live check uses a case only the new code handles.** #179's first
  LoRA check sent an image whose `<lora:>` tag named the gallery's own
  LoRA: its chip merged into the gallery's, which the old code drew too, so
  the check showed nothing new - "what was purpose of your last tests for
  lora?", the owner asked. Pick the image, the file, the setting the old
  code gets wrong, as a suite's check has to fail on the old code. And a
  live check that does not reproduce the failure shows the change runs, not
  that it fixes: #213's uncapped run loaded 763 images of 763. Say so in
  the commit, and ask for the observation that would settle it.
- **Reproduce the slow case.** Fast's break of the 64-at-once cap did not
  show while Civitai had its copies ready: 3 in flight at most. Each Civitai
  answer held 2 s in the test browser (`page.route`) showed 214. A check of a
  load limit holds the answers. Runs that scroll the same images get copies
  the run before had made: a fixed hold outweighs that, and the count in
  flight is weighed before the times.
- **An empty grid: read what it asked the server.** The Model Manager's
  grid draws nothing until Load Models, and its filters are kept in the
  browser. On 7880 a LoRA was missing because Type was saved as
  Checkpoint; it was blamed on the NSFW maximum "Unknown", which hides
  nothing - the server answered 391 models with it.
- **Measure; do not estimate.** A restamp guessed at 10-20 s took 3-6. The grid
  was 1.3 s because one step ranked 100,651 images to pick 20 previews - found
  by timing each part of the query, not by reading it. And check what a timed
  call returned, not only how long it took.
- **A prototype times the whole answer.** #231's prototype timed the query
  that picks a part, 7 to 82 ms - the plan said the tiles came on top. They
  were most of it: a group's tile reads every image of the group for its
  previews, its shared checkpoint and its LoRAs, and the real requests took
  0.4 to 2.8 s at 76,000 images. `tools/measure_generations.py` found it
  before the commit.
- **Synthetic data takes the real data's shape: read it first, read-only.**
  #231's made-up library had one distinct prompt per 13 images, the live one
  one per 3; with the real mix, search went from 43 ms to 164.
- **A refactor is checked on real data, before and after.** Run every real
  sidecar (about 1,160 here) through the old code and the new, read-only, and
  compare every field: R13 found the enum it removed had been wrong for 25 of
  25 models; R18 found nothing changed. Then make one deliberate change and
  see the comparison catch it (a rating rounded differently: 395 differ) - a
  comparison that cannot fail proves nothing. A schema change the same way:
  HEAD's package beside the tree's, on an in-memory copy of the live tables,
  the migration's backup pointed at memory (a script kept locally, under the
  git-ignored `tests/work/r133/`). It found what every suite passed (see
  `model_manager/db/AGENTS.md`, "Saying nothing is not a value").
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
  A fresh test browser already gets the working tree's scripts: Gradio's
  file route reads the disk, and `asset-version` is their newest mtime. A
  route is needed for HEAD's files, and for what the server's Python - the
  old code until a restart - answers: 0.55.2's live check added its new
  setting to ui-options in the test browser alone. Near a destructive
  button, route its endpoint to abort as a net: each delete question was
  opened and cancelled, 100 tiles before and after. A glob nets more than
  the button: `**/model-manager/civitai/download**` also aborted the
  downloads panel's poll (`download/progress`), and each #217 live check
  logged two console errors, "Download poll error". Route the POST alone.
- **Read the run's result before committing.** A commit chained after the
  run with `;` went in over "1 failed", and which suite could not be
  recovered. The runner now names failing suites in its last line and keeps
  their output in `tests/work/last_failures.log`.
- **Scripted edits anchor on whole top-level lines.** A substring match put an
  import inside a function, twice (the match was an indented copy); a "cut
  to the next method" took a module's tail with the last method, and a cut
  from one `def` to the next takes the next one's decorator: restoring three
  methods from HEAD dropped `@contextmanager` from `scope_level`, 7 suites
  failed, and a comparison of method bodies by AST had passed - the decorator
  lies outside the body's lines (#259). After any
  scripted edit, parse every changed file and compare its function count.
  A rename by regex: grep for the old name afterwards, in every quoting - one
  that kept off a JSON key of the same name skipped `_upsert("civitai_versions")`,
  and 45 suites failed. A template's end is not its first backtick: a nested
  `${`...`}` ends there. #292's script, turning three windows' outer `<div>`
  into `<dialog>`, took the first backtick for the end and changed an inner
  `</div>` in 2 of 3; Resources drew only its header, until the suites caught it.
  A hand-formatted JSON file is edited as text, never loaded and dumped:
  adding two notes to `release_notes.json` through `json.dump` changed 199
  lines for 39.
- **Compare a round of changes as a whole, after it.** Every refactor of the
  0.44 round passed its suites. Comparing the code before the round (57ae3c0)
  with after it (b529f30), with seven reviewers in parallel, found nine
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
  measure it over several loads. #144 said five links dressed as buttons
  looked wrong; measured on 7870, two did - the ones inside Gradio's
  container. And measure again after the change: the owner asks for it, and
  the second run is what confirmed all five. A difference against data is
  checked against what this machine has: 21 of 25 "VAE not selected" named
  files this WebUI lacks, and a side agent caught it before the issue was
  filed. A copy of the code's rule, run over the library to count, is first
  checked against what the page showed: Send's sampler matching, copied to
  count 104,204 images, agreed on 276 of 279 Sends - the 3 it missed were
  Neo's own `Undefined` fix.
- **A stress test compares the page with the source data, never with the
  code's own plan.** The Send test of 2026-10-18 checked Forge against
  Send's plan: 488 Sends passed, #303's Flux VAE on three Illustrious images
  among them, found only by reading the log. The test of 2026-10-19 read 14
  fields against the image's stored data, with Forge's own paste of the
  file's infotext as a second witness (156 of 200 originals carry one): 406
  tries, eight kinds of difference, #306-#313. A difference the code makes on
  purpose is listed too, to be judged. And such a test cannot see data that
  contradicts itself: #303's images name both the Illustrious checkpoint and
  the Flux VAE.
- **A sample drawn through a lookup cannot measure what the lookup
  misses.** #262's 100 random models entered only if a batch returned them,
  so a model every batch leaves out could never enter, and 99 of 100
  overstated it. A side agent caught it.
- **A live check says what it did not press.** #263's clicked the tab's
  button, not Send, which writes; the owner then hit a Send crash and asked
  "did you test this". It was old (#266), but the report had not said Send
  went untested.
- **A slowdown in a long session: the same action in a fresh tab first.**
  In 2026-10-18's Send test, sends that kept the preset went from 520 ms to
  about 880 ms over some 460 sends in one page. A freshly loaded tab took
  about 800 ms too, with the machine at 36% CPU from another VM, and later
  rounds came back to about 610 ms: the load, not the page.
- Writing a check: `tests/AGENTS.md`, "Proving a change". Timing SQL:
  `model_manager/db/AGENTS.md`, "Proving a change". A delay on the page:
  `javascript/AGENTS.md`, "Proving a change".

### The code

- **Search the page too before saying the extension does not do something.**
  "Nothing refreshes Forge's checkpoint list after a download" was said from
  a search of the Python alone; `downloads.mjs` presses Forge's own refresh
  once a batch of downloads lands - since #193 its extra networks' hidden one
  too, and after a delete or a sync that changed files
  (`refreshWebUiModelLists`).
- The other lessons sit beside their code: `model_manager/AGENTS.md`, "The
  code"; `model_manager/db/AGENTS.md`, "The code";
  `model_manager/api/AGENTS.md`, "The code"; `tests/AGENTS.md`, "The code".

### The environment

- **Windows Python's printed lines end in `\r`.** A `while read` loop handed
  them to `curl.exe` with it, and the request broke: `tr -d '\r'` first
  (#230).
- **This is Windows: paths are case-insensitive.** `claude.md` and
  `CLAUDE.md` are one file, and deleting the "duplicate" deletes the
  original - which is how `CLAUDE.md` once had to be written twice.
- The WebUI may not be on the default port. From WSL it cannot be reached
  directly; Windows' own `curl.exe` can.
- The project's hook ("Testing") reads the text of every Bash command, so it
  also refuses one that ends in the runner's path - a `cat`, a `grep`, a line
  of a commit message. Put the path in a variable (`F=tests/ru; F=${F}n.py`),
  or run a script file.
- WSL's shell here is zsh: `noclobber` is on - a refused `>` leaves the old
  file in place to be read: an issue listing read an earlier session's
  `issues.json` and gave 83 open issues for 65 - `cp` asks before overwriting
  (see `tests/AGENTS.md`, "Make sure the old code is what ran") and `rm`
  before deleting - a chained `rm` waited for an answer that never came,
  until the task was stopped: write `command rm -f` - and `echo`
  turns a Windows
  path's backslashes into escapes - keep a path in a variable, or use
  `printf`. A word starting with `=` is looked up as a command: `echo ======`
  fails ("= not found"); use `printf -- '-----\n'`. A colon after a
  variable is a modifier: `"refs/tags/$t:refs/tags/$t"` read `$t:r`, mangled
  318 refspecs, and aborted a push - write `${t}:`.
- **7880's copy of the extension is its own**: a git clone with files copied
  over it - not a link to this working tree - so its version is the last
  copy's (0.61.0 on 2026-10-16, its database at v43). A change reaches it
  by copying the changed files there, then a restart (`POST
  /model-manager/restart`). It is not always running: when its port does not
  listen, a live check waits for the owner to start it. A restart's first answers can come from the old
  process: wait for the port's PID to change, then for
  `/model-manager/asset-version` to answer - a 404 until the extension's
  routes are added. 0.59.2's first live check restarted 7880 onto the old
  code. An extension that fails to load cannot restart itself -
  `/model-manager/restart` is its own route - but Forge's Extensions ->
  Apply and restart UI can. Debug code goes in from a file and is parsed
  before the restart: a heredoc turned a `\n` inside a string into a
  newline, and 7880's extension failed to load (#299).
- WSL's git reads a Windows checkout's line endings as changes: 7880's clone
  showed 318 files modified, and 0 with `-c core.autocrlf=true` or Windows'
  `git.exe`. Ask the latter before calling a clone dirty.
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
- Running the tests: `tests/AGENTS.md`, "The environment". Running Neo's
  detector outside the WebUI: `model_manager/AGENTS.md`, "The environment".

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
  empty commit (1c22c0b) had to name them for `main` to close them. A fix
  for two issues names both: #129, fixed by 1ccc8e3 under "Fixes #11", needed
  an empty commit too (217e29d).
- **Whenever `main` is updated, `dev` is updated at the same time, to the
  same commit** - one push, never one without the other, and every tag with
  it: `git push origin dev dev:main --tags`. A release on `main` alone leaves
  every `dev` install behind and told of nothing; on `dev` alone, new installs
  miss it and its issues stay open.
- **"Push to dev/main" means everything: both branches and every tag.** The
  tags are lightweight, so `--follow-tags` leaves them behind. Pushes of the
  branches alone left 52 tags local (v0.44.0-v0.48.6), pushed apart later.
- **The history was rewritten on 2026-10-08**, without its attribution lines,
  and every hash changed. Hashes from before - the `fixed-in-rc` comments,
  older notes - name the old history, kept in the private
  `sd-webui-forge-model-manager-old`. Forge installs followed unaided: an
  update runs `fetch --all`, then `reset --hard origin/<branch>` - tested on
  scratch clones, and seen on 7880.

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
- What runs as a check, and where a tool run by hand lives: `tests/AGENTS.md`,
  "Testing".

`--all` runs every suite, twelve at a time and the slowest first, in about
22 s; `tests/README.md` says why no wider, what each suite covers, how the
choice is made, and how to write one.

**A test run takes a minute at most; one that needs longer is asked for
first.** That is the owner's rule. Start every run under a time limit
(`timeout 60`), and if it would need more, ask before running it. After a run
that was stopped, look for what it left running and stop only that.
