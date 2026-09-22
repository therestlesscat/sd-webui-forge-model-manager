# Tests

```
python tests/run.py                 the offline suites and the static checks
python tests/run.py --online        those, plus the ones that call Civitai
python tests/run.py nsfw hash       only suites matching these words
python tests/py/hash_test.py        any suite, on its own, always
```

About fifteen seconds. Node is needed for the JavaScript suites; one of them
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
the migrations on the way and cannot drift from the schema.

## What is here

**Static checks** (`tools/`) run first, because they fail fastest.

| | |
|---|---|
| `check_python_references.py` | relative imports name real attributes; facade methods exist with matching arity; call sites fit the signatures they call |
| `check_js_references.mjs` | every imported and destructured name is exported; every called name is declared; no `window.*` read but never assigned |
| `check_api_contract.py` | the parameters the browser sends are the ones the endpoints declare, both directions |

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
for exactly this, so they can be pointed at a worktree.
