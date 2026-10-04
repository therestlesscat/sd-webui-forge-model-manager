# Tests

```
python tests/run.py --all           the offline suites and the static checks
python tests/run.py --changed       only the suites the uncommitted changes need
python tests/run.py --online        those, plus the ones that call Civitai
python tests/run.py --tools         those, plus the suites of tools run by hand (TOOLS: the NSFW trainer)
python tests/run.py nsfw hash       only suites matching these words
python tests/run.py -j 8            at most 8 at a time (default: 4)
python tests/py/hash_test.py        any suite, on its own, always
```

The suites run side by side, each in its own process with its own folder under
`tests/work/`, four at a time: under 40 s for all of them. Not one per CPU:
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
that kind. `runner_test.py` covers the rules.

A page setting that waits or polls reads `TIMING` in `core.mjs`; a browser
suite shortens them with `window.mmTiming` before loading the page, and waits
for what it is waiting on (`whenSendSettled()` in `send.mjs`, a condition) rather than
for a fixed time. Node is needed for the JavaScript suites; one of them
also wants a DOM:

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

## The library they run against

`fixtures.py` builds one from nothing: twelve models, fourteen linked versions,
three files Civitai has never heard of, a spread of NSFW levels, one model that
refuses every licence and one that says nothing about any. Small enough that
every number in a test can be written down, varied enough that the queries have
something to discriminate between.

They used to run against whichever database the author had, and it cost four
suites: a count that was right last week, three rows marked by a later sync, a
filter that found two models until the library grew. **Assert what the code
does, not what a library happens to contain.**

Everything goes in through the real `ModelsDatabase`, so a fixture exercises
the migrations on the way and cannot drift from the schema. Nothing else opens
a database: a service that saves through `get_models_db()` is given a store of
the test's own (`DownloadService.store`), so no suite can reach a real
`models.db`.

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
  showed it (`msedge --headless --allow-file-access-from-files
  --virtual-time-budget=5000 --dump-dom file:///...` on a page under
  `tests/work/`, with its own `--user-data-dir`).
- **No capture phase.** A listener for the way down runs with the ones on the
  way up, and an event that does not bubble - an image's load error - reaches
  none on the document: a suite calls `fallBack` (`shared/media.mjs`) itself.
- **No layout.** Widths and positions are 0; a suite checks the stylesheet's
  rule instead.
- **The markup is read from the tab's `.py`**, as written (`tabMarkup`), with
  the header's version and gear and the downloads panel filled in from
  `ui/header.py`'s templates; any other markup Python adds with `.replace()`
  is not there. `tab_markup_test.py` draws the tabs as Gradio is handed them.
- **The markup is there before the script runs.** In the WebUI, Gradio draws
  it after; a suite that matters for that removes the container, loads the
  page, then puts it back (`download_controls_test.mjs`).
- **`onAfterUiUpdate` does nothing** unless the suite collects the callbacks
  and runs them (`quiet_updates_test.mjs`).

## What is here

**Static checks** (`tools/`) run first, because they fail fastest.

| | |
|---|---|
| `check_python_references.py` | relative imports name real attributes; facade methods exist with matching arity; call sites fit the signatures they call |
| `check_js_references.mjs` | every imported and destructured name is exported; every called name is declared; no `window.*` read but never assigned; no file reads a `window.*` another file defines, and every name called through `shared/calls.mjs` is provided; a tab's `SHARED_MODULES` is what it awaits; markup holds no inline handler, and every action it names - in the modules and the tabs' Python - is provided; no file defines a `window.*` global but the shared modules' version |
| `check_api_contract.py` | the parameters the browser sends are the ones the endpoints declare, both directions |
| `check_forge_imports.py` | nothing in the package but `forge_host.py` (and `ui/settings.py`) imports Forge, or reaches it by name |
| `check_import_cycles.py` | the extension's package imports without a cycle, counting imports inside functions |

**Suites** (`py/`, `js/`) cover, roughly: hashing and its one-read guarantee;
the no-clobber rule on both tables; what a sync may and may not delete;
trained-versus-merged inference; the NSFW rule and the licence filters; the
not-found memo; the sync dialog, driven through the shipped module against the
markup the tab actually serves.

Two groups are skipped by default and the runner says so:

- **online** — they check our reading of Civitai against Civitai. Worth
  running when the API might have changed, not on every commit.
- **historical** — they compare against a specific commit to show a refactor
  changed nothing. They did their job; they are kept for the record.

## Adding one

Put it in `py/` or `js/`, have it exit non-zero on failure, and build any data
it needs with `fixtures.build()`. The runner will find it.

One habit worth keeping: after writing a check, run it against the code as it
was **before** your fix and watch it fail. A check that has never failed has
not been shown to check anything — `MM_ROOT` on the JavaScript suites exists
for exactly this, so they can be pointed at a worktree. From WSL, running
Windows' `node.exe`, set `WSLENV=MM_ROOT` as well: WSL passes a Windows program
only the variables named there, and without it the suite quietly runs against
the current code and passes.
