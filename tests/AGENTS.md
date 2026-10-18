# `tests/`: proving a change with a check

How a check is written so that it proves something, and how the tests are
run here. `tests/README.md` says what each suite covers and how to write
one; the root `AGENTS.md` says how a change is proven beyond a check.

## Learned the hard way

### Proving a change

- **Read a failing suite's own output, not only the runner's list.** #220's
  run left two FAIL lines out of its list, "off: no video in the card"
  among them, and that check looked passed on the old code; `node.exe
  tests/js/<suite>` showed both.
- **A live check of a carried-over setting needs a saved value the new
  default does not equal.** 7880's saved 100 was the new default too: set
  to 30 before the restart, all four new settings read 30 (#230).
- **A guard is a claim too.** #213's plan named "every gallery's suite" as
  the guard that images still load. In those suites the harness's watcher
  never says an image came into view, so no image had ever loaded there; a
  side agent's review found it. Two suites now load a gallery through each
  tab (`mm_gallery_queue_test`, `cb_gallery_queue_test`). A guard row names
  its check, and the check is seen to fail on a break.
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
  new. Read a list line by line (`while IFS= read -r f`). And Windows' Python
  writes `\r\n` in text mode: a break script that rewrote two files with
  `open(path, 'w')` left them in CRLF. Read and write with `newline=''`, and
  `cmp` against a backup after. It cannot open a script under WSL's `/tmp`
  either: put one under `tests/work/`.
- **A new suite runs on the old code from a copy of HEAD.** `git archive HEAD
  | tar -x -C tests/work/<x>/head`, the suite copied into that tree: its
  paths come from its own place, so HEAD's package runs and the working tree
  is not touched - #285's server suite failed 12 of 19 checks there. A fake
  that calls through to the real function calls it as HEAD's is called:
  #285's passed a third argument HEAD's v42 did not take, and its thread
  crashed instead of failing a check.
- **A break must fail a check, not crash the suite.** `ORDER BY 0` is an
  SQLite error, not an order, and a check that sliced a list by what it
  assumed raised a `ValueError`: both "failed" without showing which check the
  break reached. Compare whole values, and break with a valid alternative -
  `(1 = 1)` for the order. Nor hang: the checker prints FAIL lines only at
  `done()`, so a break that leaves an awaited promise pending ends the suite
  silently, every failure hidden - two of #292's did, awaiting a close that
  waited on a check never answered. Await nothing a break could leave
  pending, and answer every question asked.
- **A break that fails nothing is a finding.** Of 0.58.3's breaks, two failed
  nothing: one removed a line that turned out redundant - the line went -
  and one hit a guard a second layer covers (the walk never hands a recorded
  file to the write); breaking that layer failed the check. Find out which
  before calling a check proven.
  And a check can sit where the break draws the same thing: #240's hidden-tab
  check hid the grid while it was at the top, where a wrong redraw draws the
  same rows. Scrolled 20,000 px first, it failed on the break.
- **A failure report the console cannot print hides the failure.** A check
  expecting the settings' ⚙ failed on HEAD, and printing it crashed the
  suite on Windows' console (cp1252) before any FAIL line; `download_test`
  writes with `sys.stdout.reconfigure(errors='backslashreplace')` (#224).
- **A suite HEAD cannot import is proven by breaks.** #229's server suite
  imports what HEAD lacks: 11 deliberate breaks of the new code each failed a
  check instead, and 3 of the page's. The late-answer check passed its break
  until it opened the panel - a redraw the break needed to show.
- **A work check takes the real request's shape.** At the suite's page of 4
  tiles, a part read 4 of 14 base-model groups, and Classic grew 5.3 steps
  per image and group - under the bound meant to catch it. At the tab's 100
  it grew 87.8, against Single pass's 0.7 (#259).
- **Clear `__pycache__` after swapping files.** Python reuses bytecode when the
  source's mtime (to the second) and size match. `SCHEMA_VERSION = 23` to `24`
  is the same size, a swap reproduced the timestamp, and the stale bytecode
  kept version 23: the v24 migration silently never ran, through two restarts.
  If a change "does not take effect", compare the cached `.pyc` with a fresh
  compile before suspecting anything else.
- **A check that fails once is run twenty times on HEAD before it is blamed
  on the change.** One download test asserted which of two threads started at
  once recorded itself last: the scheduler's choice, 1 run in 20.
- **A swallowed error looks like an unrelated failure.** A test's own helper
  named `usable` shadowed the imported `usable`; the paging code caught the
  recursion and reported "no models kept".
- **Look at what a run leaves behind.** Node's coverage reports were never
  removed: 9,429 of them, 4.6 GB. Every `--all` parsed them all, and two
  modules deleted long ago stayed "used" in `test_map.json` (92 entries). With
  a tracer that hooked every call, `--all` had grown to 72-83 s; it takes 31
  s since both were fixed. Time a run plain and traced before guessing why
  it is slow.
- **A slow run: wall time against CPU first.** The browser suites ran 95 s
  summed against 31 s of CPU: they waited, mostly on timers. More at once,
  4 to 12, took `--all` from 61.3 s to 27.6 s, and tracing for `--changed`
  cost nothing (#270). A probe charging each idle gap to the timer that ended
  it found which waits were the harness's own (#271) and which the suites'
  (#272). A saving across suites is the sum over the twelve at once: 13 s
  summed was about 1 s - a side agent caught a table that gave the sums.
- **Importing `model_manager/ui/settings.py` loads Gradio**, 2.6 s: a
  setting's `onchange` check in `download_test.py` took that suite from 0.9 s
  to 3.2 s. Such checks go in `settings_api_test.py`, which loads it already,
  and whose saves run `onchange` through Forge's own `opts.set` (#279).
- **A live check of a limit needs work slow enough to watch.** LoRAs
  downloaded in 2 to 6 s, and the settings window took longer than that to
  save: lowering 3 at once to 1 found one download still running, and showed
  nothing. Lowered through the window's own save route the moment 3 ran, none
  stopped and the next started only once none ran (#279).
- **cProfile inflates Python-level work.** `copy.deepcopy` profiled at 4.7 s
  of `generations_scale_test`, and took 0.74 s timed directly. Time a suspect
  on its own before planning around it.
- **A comparison of two ways cannot catch a wait too short.**
  `generations_grid_test` compared Classic with Fast after each control; with
  no wait at all both read 200 tiles of 250, alike, and it passed. Its waits
  now count to the whole level (#272): a wait is for what the check reads,
  never for a time that usually covers it.
- **A break can be made in memory.** A module hook (`module.registerHooks`,
  or an `--import` preload) rewrites a page module as Node loads it: no file
  is touched, and suites can be proven side by side - #272's five were, at
  once.

### The code

- **Page sizes in a suite:** one paging fewer items than the settings allow
  lowers `gallery.MIN_PAGE_SIZE`; one shrinking the two scrolling tabs' part
  sets `gallery.TILE_PART`. Both are read when asked; `page_sizes_test`
  holds the real range (#230).
- **`check_python_references.py` does not model `@staticmethod`** called on an
  instance; make such a helper a plain method rather than leave a red check.
- **A text search for names sees only what it was written for.**
  `check_js_references.mjs` looked for "word(": it took `/\b(error)/` for a
  call to `b`, and passed a name only read - #115's `[...currentImages]`,
  caught only because a browser suite ran that line. It parses the modules
  now (acorn, #116), and a name has to be created where it is used: its
  function, a block around it, or the file. Its other checks still read the
  text.

### The environment

- Run the tests with the WebUI's own Python - it has FastAPI and torch - and
  Windows `node.exe` for the browser suites. Neo's venv is Python 3.13
  (`sys.monitoring`; comprehensions inlined, no frame of their own); the
  original Forge's is 3.10, so the tracer keeps a profile-hook fallback.
- Windows' Python cannot lock a SQLite file on a WSL path: a throwaway
  database goes under `tests/work/`, on the Windows drive.
- **`timeout` from WSL does not stop a Windows `node.exe`.** It ends the WSL
  side; the suite runs on. Three hung copies of one suite kept running after
  their runs timed out. Find them by command line - `Get-CimInstance
  Win32_Process` with the suite's name in `CommandLine`, from `powershell.exe`
  - and stop only those (`taskkill.exe /F /PID`).
- **Windows' Node wakes an idle timer on its clock's tick, 15.5 ms apart.**
  Measured with `node.exe`: 0, 1 or 10 ms take 15.2-15.5 ms, 16 ms takes
  29.7, 50 ms takes 62.2. A look every 50 ms slept 62; a 20 ms sleep, 31.
  Linux Node in WSL reads `/mnt/f` over 9p and is slower still: measure with
  `node.exe`.

## Testing

- Every `.py` in `tests/tools/` runs as a check in `--all`. A tool run by
  hand - a measurement, a trainer - lives in `tools/`.

## Kept elsewhere, and true here too

Rules whose main code is in another folder, which this folder's code must
keep as well:

- `javascript/shared/AGENTS.md`, "Send sets a field through Forge's paste
  wherever the paste has one".
