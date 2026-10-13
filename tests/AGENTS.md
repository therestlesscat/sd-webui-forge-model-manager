# `tests/`: proving a change with a check

How a check is written so that it proves something, and how the tests are
run here. `tests/README.md` says what each suite covers and how to write
one; the root `AGENTS.md` says how a change is proven beyond a check.

## Learned the hard way

### Proving a change

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
  new. Read a list line by line (`while IFS= read -r f`).
- **A break must fail a check, not crash the suite.** `ORDER BY 0` is an
  SQLite error, not an order, and a check that sliced a list by what it
  assumed raised a `ValueError`: both "failed" without showing which check the
  break reached. Compare whole values, and break with a valid alternative -
  `(1 = 1)` for the order.
- **A break that fails nothing is a finding.** Of 0.58.3's breaks, two failed
  nothing: one removed a line that turned out redundant - the line went -
  and one hit a guard a second layer covers (the walk never hands a recorded
  file to the write); breaking that layer failed the check. Find out which
  before calling a check proven.
  And a check can sit where the break draws the same thing: #240's hidden-tab
  check hid the grid while it was at the top, where a wrong redraw draws the
  same rows. Scrolled 20,000 px first, it failed on the break.
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

### The code

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

## Testing

- Every `.py` in `tests/tools/` runs as a check in `--all`. A tool run by
  hand - a measurement, a trainer - lives in `tools/`.

## Kept elsewhere, and true here too

Rules whose main code is in another folder, which this folder's code must
keep as well:

- `javascript/shared/AGENTS.md`, "Send sets a field through Forge's paste
  wherever the paste has one".
