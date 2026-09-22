# Working on this extension

A model manager for SD WebUI Forge: it lists what is on disk, enriches it with
Civitai metadata, and lets you browse and download more.

This file is about the shape of the codebase — what each part is *for*, and
which of its rules were learned the hard way. It is not a file listing; `ls`
does that better.

## Layout

```
scripts/model_manager_ui.py   the entry point Forge loads
model_manager/                the extension proper
javascript/                   the two tabs, and what they share
style.css                     picked up by filename; see "The WebUI's rules"
tests/                        see tests/README.md
```

### `model_manager/`

| | |
|---|---|
| `db/` | everything that touches SQLite. A facade (`database.py`) over one module per job: `models_ops`, `images_ops`, `browse_cache_ops`, `query`, `migrations` |
| `civitai/` | talking to Civitai: `client` (auth, rate limiting, retries), `prompt_filter`, `licensing` |
| `sync_service.py` | identifying files and refreshing their metadata |
| `scan_service.py` | reading the disk and the sidecars beside it |
| `download_service.py` | fetching a model and filing it |
| `hashing.py` | working out what a file is |
| `nsfw.py` | how explicit something is — **the only place that decides** |
| `storage.py` | reading and writing `.civitai.info` |
| `api/` | the HTTP endpoints, one module per area, each with `register(app)` |
| `ui/` | settings, and the markup for each tab |

## What the pieces assume about each other

**`nsfw.py` is the single source of truth.** There were once three
implementations giving two different answers. If you need a level, ask it; if
the rule is wrong, it is wrong in one place. `javascript/shared/common.mjs`
mirrors the per-image rule for the browser, and the two are checked against the
same cases.

**Absent is not empty.** Both `upsert_version` and `upsert_civitai_model` keep
what they hold when handed `NULL`, `'[]'`, `0` or Unknown. A scan reading a
thin `.civitai.info` cannot tell "this model has no trigger words" from "this
file does not mention any", and it used to write the second over the first —
blanking trigger words, dates, licences, vote counts and stored hashes. Adding
a column means adding it in four places: the INSERT list, the VALUES tuple, the
`DO UPDATE SET` list, and that no-clobber rule.

**Deleting rows needs evidence.** Two kinds, and they are not equally safe.
*Direct*: this file was about to be refreshed and is not there — sound in any
scope. *By diff*: these rows name files a walk never found — sound only when
the walk covered the whole disk, so it runs before any target filter, never
with an explicit path list, and never when the walk came back empty (that is an
unmounted drive, not an emptied library).

**Civitai's model type is not the file's role.** A checkpoint model can ship a
VAE as one of its versions, and that file inherits "Checkpoint". The folder is
the better signal, and `_infer_model_type` knows it — but only for files with
no Civitai data.

**`checkpointType` is inferred, not read.** Civitai accepts it as a filter and
returns it on neither the model nor the version. `get_checkpoint_types()` asks
which ids are Trained, then which are Merge, and takes the answer from set
membership — discarding any batch whose answer does not partition the request,
because that would mean the assumption no longer holds.

## The WebUI's rules, which are not obvious

- `javascript/*.js` become classic scripts, `*.mjs` become
  `<script type="module">`, **in filename order**. Subdirectories are not
  scanned: `list_scripts` uses `os.listdir`.
- `style.css` is found by name and concatenated with every other extension's.
- Both are stamped with the file's mtime **once, at startup**, so a change
  needs a WebUI restart to reach the browser — not just a page reload.
- Nothing versions `javascript/shared/`. The tab scripts therefore import it
  with their own `?mtime` propagated from `import.meta.url`; a plain import
  resolves to a URL that never changes, browsers cache it forever, and a newly
  exported name becomes a link error that kills the entire tab.
- Gradio re-renders a `gr.HTML` block wholesale, and inline styles set on
  anything inside it do not survive. Anything set from script has to be
  reasserted from `onAfterUiUpdate`.

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
  something shared.
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

## Known gaps

- **Local-only models cannot be bookmarked.** They have a row now, but
  bookmarking is keyed on a `civitai_models` id and they have none.
- **They also show as blank cards** — the grid takes previews only from the
  cached Civitai images, and never looks at the `.preview.png` beside the file,
  though the delete path knows about it.
- **`checkpointType` is only known for models Civitai still serves.** Anything
  delisted stays Unknown; nothing can recover it.
- Usage history, manual collections, and a "newer version available" check are
  all unimplemented.

## Before you push

```
python tests/run.py
```

Seventeen suites and three static checks, about fifteen seconds. See
`tests/README.md` for what they cover and how to add one.
