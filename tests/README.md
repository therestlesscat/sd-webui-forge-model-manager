# Tests

```
python tests/run.py --all           the offline suites and the static checks
python tests/run.py --changed       only the suites the uncommitted changes need
python tests/run.py --online        those, plus the ones that call Civitai
python tests/run.py --tools         those, plus the suites of tools run by hand (TOOLS: the NSFW trainer)
python tests/run.py nsfw hash       only suites matching these words
python tests/run.py -j 8            at most 8 at a time (default: 4)
python tests/py/hash_test.py        any suite, on its own, always
python tests/coverage.py            line coverage, by hand: tests/work/coverage/report.txt
```

The suites run side by side, each in its own process with its own folder under
`tests/work/`, four at a time: about 35 s for all of them. Not one per CPU:
32 processes beside two running WebUIs left Windows out of memory. A failing suite's tail is
printed after the list, its name in the last line, and its whole output kept
in `tests/work/last_failures.log` until the next run.

**--changed** compares the working tree with the last commit and runs the
suites that use a changed file, a changed suite itself, and the static checks.
Which files a suite uses is recorded by every `--all` run in
`tests/work/test_map.json`: the extension's functions a Python suite called
(`trace_run.py`), the scripts whose functions a browser suite ran (Node's
coverage), and the files either read - the tab markup, the stylesheet, the
changelog. Importing is not using: nearly every suite imports the whole
package. Code no recorded run used runs every suite that could use it, and a
change to `harness.mjs`, `fixtures.py` or `webui_stub.py` runs every suite of
that kind - not yet for `harness.mjs`, whose path the runner has wrong (#137).
`runner_test.py` covers the rules.

A page setting that waits or polls reads `TIMING` in `core.mjs`; a browser
suite shortens them with `window.mmTiming` before loading the page, and waits
for what it is waiting on (`whenSendSettled()` in `send.mjs`, a condition) rather than
for a fixed time. Node is needed for the JavaScript suites; most of them also
want a DOM, linkedom, through `harness.mjs`, and `check_js_references.mjs`
parses the modules with acorn. Without acorn it fails, saying so:

```
npm install --prefix tests
```

## How a suite is written

Each file is a script that prints its own failures and exits non-zero. There is
no framework, and no runner is required to read one — that is deliberate. A
suite you can run, read and edit by itself is a suite people actually run.

```python
fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))
```

Whose a listener or a timer is, a suite reads from the stack.
`service_stop_test` wraps `addEventListener` and the timers and names the
file of ours that asked - past the loading module, whose scopes add for the
tabs and services - so what a stop leaves behind says whose it is.

## The library they run against

`fixtures.py` builds one from nothing: twelve models, fourteen linked versions,
three files Civitai has never heard of, a spread of NSFW levels, one model that
refuses every licence and one that says nothing about any. Small enough that
every number in a test can be written down, varied enough that the queries have
something to discriminate between.

They used to run against whichever database the author had, and it cost four
suites: a count that was right last week, three rows marked by a later sync, a
filter that found two models until the library grew. **Assert what the code
does, not what a library happens to contain.** Nor an incidental fact: "the
schema is at 29" failed the moment v30 came.

Everything goes in through the real `ModelsDatabase`, so a fixture exercises
the migrations on the way and cannot drift from the schema. **No suite reaches
the live database.** A service that saves through `get_models_db()` is given a
store of the test's own (`DownloadService.store`), or the test's database is
set as `model_manager.db.database._db_instance` before anything runs, and a
service saves nothing when there is nothing to keep. A before/after harness is
a test too: it sets `_db_instance` first - the settings window's GET asks
`get_models_db()` for the file in use, and run on a copy of HEAD it once
created a `models.db`.

## What a browser suite cannot see

`harness.mjs` gives a tab its markup and the WebUI's globals in linkedom, which
is close to a browser and not one:

- **No inline handlers run.** The page's markup has none (#95): it names an
  action in `data-action`, and a
  suite presses what the page draws - `act(name, data)`, `tick(name, on)`,
  `choose(name, value)`, `press(element)` in `harness.mjs` - which dispatches a
  real click or change to the page's one listener (`shared/calls.mjs`) and
  gives back what the action answered. What linkedom never showed is a stop
  in markup: `onclick="event.stopPropagation()"` on the metadata window kept
  Copy JSON's click from its listener for three releases. Headless Edge
  showed it ("Probes").
- **No capture phase.** A listener for the way down runs with the ones on the
  way up, and an event that does not bubble - an image's load error - reaches
  none on the document: a suite calls `fallBack` (`shared/media.mjs`) itself.
  A hold on the way down - Generate's question, #166 - is checked with the
  held listener on the document after the page's (`queue_ask_test.mjs`), and
  proven in headless Edge ("Probes").
- **No `KeyboardEvent`.** A key press is a plain `Event` with its keys
  assigned (`queue_ask_test.mjs`).
- **No layout.** Widths and positions are 0; a suite checks the stylesheet's
  rule instead.
- **Its MutationObserver misses a change made through `element.style`**, which
  a browser reports - so `showTab` looks at the panel each frame rather than
  observing it.
- **The markup is read from the tab's `.py`**, as written (`tabMarkup`), with
  the header's version and gear and the downloads panel filled in from
  `ui/header.py`'s templates; any other markup Python adds with `.replace()`
  is not there - build it in the page. A check that reads a template rather
  than the tab as drawn passes on what the drawing gets wrong: the
  Generations gear said "TAB" in 0.44.21 under one. `tab_markup_test.py`
  draws the tabs as Gradio is handed them.
- **The markup is there before the script runs.** In the WebUI, Gradio draws
  it after, and a suite passed while the real panel never showed. A suite
  that matters for that removes the container, loads the page, then puts it
  back (`download_controls_test.mjs`).
- **`onAfterUiUpdate` does nothing** unless the suite collects the callbacks
  and runs them (`quiet_updates_test.mjs`).

When a suite passes and the page does not, look for what the suite set up
that the WebUI does not - and ask a real browser ("Probes").

## Traps suites fell into

- **A `{ once: true }` listener goes without a `removeEventListener`.** A suite
  that tracks listeners by wrapping `addEventListener` drops one when it
  fires: `service_stop_test` counted core's `DOMContentLoaded` as left behind
  until it did.
- **Wait for what is shown, not what is drawn.** A closed list keeps its
  items: `tag_chip_test` waited for three suggestions in the markup, found the
  last round's, and pressed Esc before the answer came - the fix looked
  broken. Wait on what says shown (`.show`). And a synthetic event bubbles
  only if told to: the suite's `key()` sends a keydown no page listener hears.
- **A suite waits in seconds, never in thousands of tries.** `waitFor` looks
  every 50 ms: 4,000 tries is 200 s, and two such waits in one suite ran a
  whole run past ten minutes, leaving the suite's process behind. Seven still
  allow 4,000 or more (#145).
- **A shortened poll stays slower than `waitFor`'s look (50 ms).** With the
  restamp poll at 25 ms, a state went by between two looks, and a check that
  reads each state missed it.
- **A line the page rewrites later is recorded, not read.** The grid reloads
  500 ms after a sync and replaces the status line; a check that read it
  after a busy moment failed 3 runs in 10. `dialog_test` records every status
  shown (`statusSeen`). The estimate, asked again once the new-file count has
  come, is waited for, not settled.
- **A test passes for the wrong reason when something else rescues it.** The
  downloads test had a running download, whose poll redrew the panel; the
  bug was a panel of paused downloads only, which nothing polls. And a sync
  test listed one of a model's two versions, so the first file was refiled as
  the second: it counted two galleries only because galleries were fetched
  per file - the bug #133 fixed - and failed once they were not.
- **A stand-in server answers with copies.** One that hands the page the
  test's own objects lets the page's changes - renaming a card's file after a
  delete - rewrite the test's fixtures; a fetch never shares objects. Answer
  with `structuredClone`.
- **An action a suite presses returns its promise.** `deleteFile` did not, so
  `press` went on at once and the checks read the panel before the delete was
  done; one passed by the request alone.
- **`progress_test.js` runs `pollSyncProgress`'s body in a vm sandbox.** A name
  the poll starts using is given there too, or the poll throws inside its own
  `try` and does nothing.
- **A crash hides a suite's earlier failures.** `checker()` prints them at
  `done()`: a TypeError at line 588 of a browser suite hid the failures of the
  section above it. Read the crash, then run again.

## What is here

**Static checks** (`tools/`) run first, because they fail fastest.

| | |
|---|---|
| `check_python_references.py` | relative imports name real attributes; facade methods exist with matching arity; call sites fit the signatures they call |
| `check_js_references.mjs` | every imported and destructured name is exported; every name read or called is created where it is used - its function, a block around it, or the file - imported, or a known global, the modules parsed with acorn (`check_references_test.mjs` runs it on made-up modules); no `window.*` read but never assigned; no file reads a `window.*` another file defines, and every name called through `shared/calls.mjs` is provided; a tab's `SHARED_MODULES` is what it awaits; markup holds no inline handler, and every action it names - in the modules and the tabs' Python - is provided; no file defines a `window.*` global but the shared modules' version |
| `check_api_contract.py` | the Sync dialog's requests are what its endpoints declare, and its reads what the estimate returns |
| `check_forge_imports.py` | nothing in the package but `forge_host.py` (and `ui/settings.py`) imports Forge, or reaches it by name |
| `check_hash_access.py` | stored hashes are read only through `hashing.read_hashes` / `hash_key`, either case |
| `check_import_cycles.py` | the extension's package imports without a cycle, counting imports inside functions |

**Suites** (`py/`, `js/`) cover, roughly: hashing and its one-read guarantee;
trusting stored hashes while a file is unchanged; the walk every sync starts
with; the no-clobber rule on both tables; what a sync may and may not delete;
what Civitai fails on, tried again at a sync's end; the console and the sync's
log; trained-versus-merged inference; the NSFW rule and the licence filters;
the not-found memo; the sync dialog, driven through the shipped module against
the markup the tab actually serves.

Three groups are skipped by default and the runner says so:

- **online** — they check our reading of Civitai against Civitai. Worth
  running when the API might have changed, not on every commit.
- **historical** — they compare against a specific commit to show a refactor
  changed nothing. They did their job; they are kept for the record.
- **tools** — the suites of tools run by hand (the NSFW trainer), with
  `--tools`.

## Adding one

Put it in `py/` or `js/`, have it exit non-zero on failure, and build any data
it needs with `fixtures.build(directory)`. The runner will find it: every
`.py`, `.js` and `.mjs` there is run as a suite, so a helper goes in `tests/`
itself, or is a `.cjs` - `harness.mjs` is run as one today (#137).

One habit worth keeping: after writing a check, run it against the code as it
was **before** your fix and watch it fail. A check that has never failed has
not been shown to check anything — `MM_ROOT` on the JavaScript suites exists
for exactly this, so they can be pointed at a worktree. From WSL, running
Windows' `node.exe`, set `WSLENV=MM_ROOT` as well: WSL passes a Windows program
only the variables named there, and without it the suite quietly runs against
the current code and passes.

## Probes

What a suite cannot see, a probe can. They live under `tests/work/`, which is
git-ignored: a probe is local, and written again when needed.

- **Headless Edge** for a real browser: `msedge --headless
  --allow-file-access-from-files --virtual-time-budget=5000 --dump-dom
  file:///...` on a page under `tests/work/`, with its own `--user-data-dir`.
  For styles, load what the WebUI loads (AGENTS.md, "Seen in both modes").
- **A whole tab module over HTTP.** From `file://`, `queue.mjs` never finished
  loading: `shared/send.mjs` stayed pending, even alone, though each of its
  imports loaded. Served by Windows' `python -m http.server 8765 --bind
  127.0.0.1` from the repository, under `timeout`, it loaded, with `fetch`
  stubbed in a classic script before the import. Stop the server after, by its
  PID from `netstat.exe -ano`, its command line checked first.
- **A Node probe exits by itself, or never.** One that loads the shared modules
  or a tab keeps their timers alive - the update notice's, the downloads
  poll's. End it with `process.exit(0)`, run it under `timeout 30`, in a call
  of its own: one chained before a full run hung for seven minutes, and the
  run then overlapped a second one. If one hangs, find it by its command line
  and stop only that process - other programs run `node.exe` too.
