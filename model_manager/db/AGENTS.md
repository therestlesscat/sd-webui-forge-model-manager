# `model_manager/db/`: the database

Everything that touches SQLite: the tables, the migrations, the queries.
`model_manager/AGENTS.md` applies here too; Claude Code loads it with this one.

## What the pieces assume about each other

### Where each rule lives

**A migration does not import today's rules.** v14 once imported the live
`nsfw.image_level`, which later learnt to read the person's settings: it
applied a rule it was not written with, during startup, and renaming the
function would have broken every older database. It carries a frozen copy.
An index is a migration too (v30), versioned like any other. Since v32 an
older copy refuses a newer database (the root `AGENTS.md`, "Two WebUIs"),
so any migration means updating both copies.

**A migration that reshapes tables keeps every value, and proves it.** "It
has to be lossless", the owner said of v37 (#231). Its first draft turned
each image's files into rows keyed by name, and lost a LoRA loaded twice in
one image (20 images in one library), the order of a generation's modules
(333 generations), and the difference between hires modules `NULL` ("Use
same") and `[]`. v37 keeps every list and path as Forge recorded them, makes
its index rows from them, and before dropping anything rebuilds every old
row from the new tables and compares each column, value and `typeof()`;
any difference raises, and the transaction leaves the old tables as they
were (`migration_v37_test`, a migration dropping a LoRA's `pass` among its
breaks).

### The library: files, versions and rows

**A version is one row; its files are rows of their own** (#133).
`versions` holds a Civitai version once - its details, its gallery's cursor
- and `files` each file, naming its version by `version_id`, NULL for a file
Civitai does not know, which has no row anywhere else: no table is named for
Civitai (`models`, `versions`, `files`). `model_versions` held
both in one row per file: a version with an fp16 and an fp32 was fetched,
counted and read as two, and the copies drifted - 26 of one library's 36
such versions disagreed on their gallery's cursor, and the gallery read
whichever copy came first. Reads that want a file with its version go
through `db/library.py`'s `LIBRARY`, which gives the row `model_versions`
did; writes go to the table that holds the column. What is per version -
a gallery, its cursor, a card's count - is done once per version: a sync
over several files fetches a version's gallery once (`galleries_fetched`),
and the page draws one pill per version, with a Files list under it to read,
not to pick from. Which of a version's files Send uses is decided by what each
is and where it is (`send_plan.send_files`), and the list says which.

**A table of your own images says so; Civitai's catalogue does not.** No
table is named for Civitai, as above. Your generations' tables each start
with `generation` - `generation_prompts`, `generation_thumbnails` and the rest
(v41, #284) - so `images` and `image_*` are Civitai's images alone. Until v41,
`prompts`, `image_details`, `image_thumbnails`, `image_sources` and
`removed_images` held yours beside `images`, and read as Civitai's.

**A file is known by its path; Civitai's id for it is a fact about it.**
`files` is keyed by `file_path`: what Forge loads, what a sync walks, and what
`pins` and `generation_resources` name - on purpose, so a pin or a generation's
link outlives the file going and coming back. `civitai_file_id` (with
Civitai's type for the file, fp, size, format, primary) is matched by hash,
else by name (`payload_rows.file_row`), by every sync and a download.
It is no key: a file Civitai does not know has none, one Civitai file can be
on disk twice (in both WebUIs' folders), and it is learned late and can be
corrected - a key that changes is rewritten wherever it is named.

**Absent is not empty.** Both `upsert_version` and `upsert_civitai_model` keep
what they hold when handed `NULL`, `'[]'`, `0` or Unknown. Scan Disk, reading
a thin `.civitai.info`, could not tell "this model has no trigger words" from
"this file does not mention any", and it used to write the second over the first —
blanking trigger words, dates, licences, vote counts and stored hashes. Both
are generated from one list per table (`MODEL_COLUMNS`, `VERSION_COLUMNS`,
`FILE_COLUMNS` in `db/models_ops.py`), each column with how an update treats it - overwritten,
kept when the new value says nothing, or a rule of its own - and given its
value by name. Adding a column means an entry there, or in the list of
columns written elsewhere; `upsert_columns_test.py` fails on one in neither.
It used to be four places by hand, and a column missed from the `SET` list
was written once and never updated. Nor is a value assumed where nobody said
one: a model's `nsfw` is true, false or NULL. A payload without it - a thin
sidecar's - wrote 0, over a stored 1 too, until #141; a model only sidecars
describe now takes a silent one's silence (`keep_once_civitai_said`).

**A card shows one version, chosen in one fixed order:** newest published, then
Civitai's own order (`index` in `models.versions`, whose first its page
shows), then version id and file (`SHOWN_ORDER` in `db/query.py`). Versions
share a date to the millisecond, or have none; without the tie-break SQLite
returned either, and a cover changed between loads. Anything that picks one of
several needs an order that cannot tie.

### Your generations

**Your images are narrow rows; their details are kept apart** (#231, v37).
Lists, groups and filters read `generations` and `generation_images`, about
45 bytes a row; `generation_details` and `generation_image_details` hold what one tile
or one Send reads, the lists and paths exactly as recorded; `generation_prompts` holds
each text once, with `grouped_as` - the row holding its text with its
spacing tidied, 0 when nothing is left - and its trimmed `length`.
`generation_resources` is an index made from the recorded lists - each file
an image used, by role and place, in the library's spelling, followed when
the sync moves a file - never the source. A read picks its part in SQL
(`Scope` in `db/generations_ops.py`) and only then reads its tiles. Rows of
33 KB a generation and 4 KB an image, as v36 had, cost a page each to read
whatever column a list wanted.

**A prompt row lives as long as something names it** (#248, v40): a
generation's or an image's prompt or negative prompt, or a prompt it heads.
Every delete collects the prompts its rows named and drops those left
unnamed, at the end of its own transaction (`drop_unused_prompts`) - after
Force sync's new rows are written, so a prompt they name again keeps its
number. Until 0.58.9 no delete did: a Remove folder of 75,618 images left
5,266. One index per naming column makes each look one lookup; without
them a Remove folder freeing 2,235 prompts took 36 s. A writer that looks a
prompt up takes the write lock first (`_write_lock`), or a delete between
the lookup and the write leaves a row naming nothing.

## Learned the hard way

### Proving a change

- **Measure on a database file, not in memory.** For #231, reading today's
  columns with indexes measured 37 to 153 ms on an in-memory copy and was
  recommended; on a file the same queries took 158 to 747 ms. A side agent
  caught it.
- **Gate what is costly on the case that needs it.** The tie-break read
  Civitai's order from JSON: for every version, +13.6 ms a grid query;
  counting ties with a window, +25 ms; asked only where an indexed `EXISTS`
  finds a tie, +3 ms. Time each part. A window sorts every row it numbers,
  with every column: numbering a version's files in the grid's wide rows took
  a 50-card page from 40 ms to 70; the same count from a narrow grouped CTE,
  joined, to 43.
  A subquery per row inside a `GROUP BY` runs again for each use: the
  Generations tab's LoRA combination took 4.5 s at 10,000 images, and 55 ms
  as a CTE joined once (#231).
- **A join order is fixed for a level, not case by case.** Grouped by base
  model, SQLite joined the part before each image's key was known, and
  looked the key up once per group of the part: 431 ms against 64 for the
  images alone, at 75,682 images in 14 groups. `CROSS JOIN` fixed that level
  (1,583 ms to 735) but took a part found by index from 1 ms to 136, and
  sectioned levels 21 to 47 ms slower. Asked "aren't there better answers?",
  the owner was right: four reads each worked the level out again, and one
  indexed pass replaced them (Single pass, #259).

### The data

- **Forge and the library spell one path two ways** - case, which Windows
  ignores and SQL does not. Compare paths with `COLLATE NOCASE`
  (`library_spelling`), never `=`. A version's row by its path goes through
  `_stored_spelling` (`db/models_ops.py`) - the exact spelling first, then
  ignoring case: 0.44.8 did that for the upserts alone, and every other read
  and write by path missed a file a walk spelt another way, which a sync then
  hashed and looked up on every run (#120).

### The code

- **Stamp what SQL filters on.** A per-image check is cheap in the browser, on
  a page of images; across the grid's queries it was 2.7 s against 4 ms.
- **Choose the page, then look up its details.** Filter, group, sort and limit
  first; per-row lookups after. With an index in the order the lookups read.
- **SQLite reads a row's whole page, whatever column is asked for.** Every
  image's level, from v36's 3 KB rows: 262 to 375 ms; with the small columns
  first in the row, 286; through an index holding it, 2.6; from a narrow
  table, 7. And it may pass over a covering index for a lookup by row id:
  each image's prompt looked up by id read the prompt's text row, 130 ms at
  76,000 images, and 26 with `INDEXED BY idx_generation_prompts_lookup` (#231).
- **A table holding another source's facts is built from that source's
  fields, not from the old table's columns.** v32 split `model_versions` into
  what it held, and Civitai's own id for each file - which a sync, a download
  and a scan all had in hand - was found missing only once a column wanted it.
- **Saying nothing is not a value, in a merge or a view.** v32's merge of a
  version's copies took "the first that says something", and a version whose
  only copy said Unknown came out NULL - read as PG; `LIBRARY` defaulted every
  NULL stat to 0, meant only for a file with no version. Where no copy says
  more, keep what they hold; default only the rows the default is for.
- **Temporary data is not in memory by default.** Both WebUIs' SQLite
  (`TEMP_STORE=1`, `cache_size=-2000`) keep 2 MB of a temporary table, a
  materialized CTE or a sort in memory and write the rest to a file in the
  system's temp folder: Single pass's table in a file was 21 to 26% slower
  than in memory (base model 343 ms against 272). `PRAGMA temp_store =
  MEMORY` is per connection; changing it deletes every temporary table and
  frees their memory (a held table, 73 MB of the process to 57), and setting
  the value it already has deletes nothing. "Temporary tables live only in
  memory" was said in #259 until a side agent checked.
- **A materialized CTE has no index.** Each read of it goes through all its
  rows: one statement holding a level's images lost to an indexed temporary
  table by 14 to 66 ms a level (#259).
- **Top N of each group: a cutoff through an index, not `IN (... LIMIT)`.**
  `lv.id IN (SELECT ... WHERE x.u = part.u ORDER BY sk DESC LIMIT 4)` read
  the table again for each part row: 3.8 s at the top level. `sk >= (SELECT
  sk ... ORDER BY sk DESC LIMIT 1 OFFSET 3)`, on an index on (u, sk): 1 ms
  (`_TableLevel.previews`).
