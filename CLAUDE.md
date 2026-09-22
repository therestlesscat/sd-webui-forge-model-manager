# CLAUDE.md

**Read [AGENTS.md](AGENTS.md) first.** It describes the codebase, the
assumptions its parts make about each other, and the WebUI behaviours that are
not obvious. This file is only the working agreement on top of it.

The architecture used to be described here as well, and drifted: it named three
modules that no longer exist. One description, in one place.

## How to work here

- Understand the question before answering it. If the ask is ambiguous, say
  which reading you took.
- **Do not make code changes unless asked.** Suggest improvements only when
  invited to.
- Ask before changing anything, and say what you are about to change.
- Honour the existing structure rather than reorganising in passing.
- Commit at logical checkpoints, with a message that says what was wrong.
- Keep everything generic. No module exists to serve one workflow.

## Getting it right

- **Never guess at an import or a function name.** Read the module. A name
  that looks obvious is how `get_max_nsfw_level` returned `UNKNOWN` without
  importing it.
- **Verify before asserting, especially about your own effects.** "I only work
  on copies" was said in this repository while a test was overwriting 747 real
  sidecars and applying migrations to the live database. If you have not
  checked, say you have not checked.
- **Run a new check against the broken code and watch it fail.** A check that
  has never failed has not been shown to check anything. Three separate
  attempts at one fix passed a suite that could not have caught the bug.
- **Stop guessing after the second try.** Ask for a screenshot, a console line,
  a number. Every long detour in this repository ended with one observation
  that reasoning had not produced.
- When showing an edit, name the enclosing method or class so it can be found.

## This is Windows

Paths are case-insensitive. `claude.md` and `CLAUDE.md` are one file, and
deleting the "duplicate" deletes the original — which is how this file had to
be written twice.

## Leave nothing running

Kill any server, watcher or background job you start, in the turn you use it.
Two test servers were once left running for twenty-three hours.

## Before handing back

```
python tests/run.py
```
