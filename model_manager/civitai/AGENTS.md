# `model_manager/civitai/`: talking to Civitai

What Civitai's API does that its documentation does not say. The sync and
the downloads that use it are in `model_manager/AGENTS.md`.

## What the pieces assume about each other

### Civitai: sync and downloads

**`checkpointType` is inferred, not read.** Civitai accepts it as a filter and
returns it on neither the model nor the version. `get_checkpoint_types()` asks
which ids are Trained, then which are Merge, and takes the answer from set
membership — discarding any batch whose answer does not partition the request,
because that would mean the assumption no longer holds.

## Learned the hard way

### The data

- **`image.civitai.com` answers each address with one redirect**: a 301 to
  an absolute `https://blobs-b2.civitai.com/...`, no query, no `%` (18 of 18
  real images and videos, 2026-11-10). A fetch that stops following
  redirects breaks the video stills and the img2img sends; a rule held to
  today's host names breaks the day Civitai moves its storage - the owner
  turned one down for S4 for that reason.
- **Civitai's search has no random order, and pages by cursor alone** - `page`
  is ignored. A fair random draw goes by model ids (`random_draw.py`): `ids`
  takes about 4,000 in one request, bounded by the URL's length (some 32 KB),
  not their number - so its commas go unencoded, as `%2C` they made 3,500 ids
  35 KB and a 431. Civitai's own filters apply to the ids; a text query
  ignores them. More than 100 matches come back as the first 100 by the sort,
  with a cursor: a draw that kept only those favoured the most downloaded.
- **A search answers every version of a model**, in Civitai's order: 139 of
  139 and 58 of 58 versions on two models, the same as `/models/{id}` and as
  a sync's stored list (2026-10-16). A card can be judged from the search
  answer alone (#218).
- **Civitai's `nsfw` search parameter has two states, not three, and neither
  is "every model".** `true` leaves out models Civitai keeps out of its NSFW
  lists (4 of 4 seen); left out, or `false`, it returns only models whose
  `nsfwLevel` has the PG bit (56 of 100 random models, every level odd),
  whatever their `nsfw` flag - not "the safe ones alone", as this said. There
  is no "NSFW only". A batch by `ids` also leaves out some models for no known
  reason: absent is not deleted, only a 404 from `/models/<id>` is (#262).
  Which existing models a batch leaves out changes from moment to moment: one
  library's 130, asked in batches of 100 and 30, lost 31 (30 of them
  existing), and 20 minutes later only the 1 deleted one, with an API key and
  without (#262). Rapid single lookups get 429 after about 30. Every model
  payload carries `nsfw` (300 of 300); a thin sidecar may not (8 of 1,032
  here), and the flag is then stored as not said (#141).
- **A text search with `nsfw=true` comes back in short pages, and is no
  superset of one without.** With `query`, Civitai's cursor is a count of
  matches (`"20"`, `"40"`): it takes `limit` matches, leaves out the models
  it keeps out of its NSFW lists, and does not fill the gap. One search at
  20 a page answered 11, 14, 17, 19, 18, 19, 17, 20, 18, 18; "dragon",
  "castle" and "elf" 18 of 20 each. A tag search, or none, pages by another
  kind of cursor (`537055|13496|1811313`) and came full. The two lists are a
  swap: one search gave 154 models with `nsfw` left out and 189 with `true`;
  26 of the 154 never came with `true`, every one a model Civitai keeps out
  of those lists, and 61 came only with it, most rated R or above. Asked
  twice, each cursor gave the same models in the same order (36 of 36,
  2026-11-12): the fill's resume mark relies on it (#424,
  `model_manager_civitai_nsfw_fill_page`).
- **Every `CivitaiClient.from_settings()` opens a new `requests.Session`**, so
  its first request pays a new connection: `/models/{id}` took a median of 333
  to 340 ms with a new one, 63 ms with one reused - the same ten models, timed
  read-only (2026-10-15). A client made per press pays it each time; 0.59.2
  moved the request off the press rather than share a session across threads.
- **Civitai's image data can lack what the code reads.** Of 122,802 stored
  Civitai images, 13,597 had `meta: null`, and 14 of 480,615
  `civitaiResources` entries a version id with no model id. Send threw on the
  first (#266); View asks the server for the second (#260).
- **Whether a version may be downloaded has one bulk answer.** `POST
  /api/v1/model-versions/by-hash` takes up to 100 SHA-256s and answers each
  matching version whole, `usageControl` included (#229); the search,
  `/models/{id}`, `mini/{id}` and `by-hash/ids` leave it out. A version comes
  back once per file a hash matches, so one sharing a file with another
  returns in a later request too: the log first said 4,534 "of 4,496". Its
  answer is `/model-versions/{id}`'s, the same size: a median of 14 and 15 KB
  a version on two samples of 100, nearly all of it the images' generation
  data; the 5 largest of 100 carried 43 to 47% of the bytes, the largest 1.6
  MB. Say the median and the spread: "77 KB a version" was a mean, and made
  one panel sound like megabytes. 2 of the 50 newest versions had no SHA-256
  on any file, and cannot be asked.
- **On-site only is per version, not in the licence.** The model's licence
  fields (`allowCommercialUse` and the rest) are the model's, and set apart;
  `usageControl` is each version's. Setting it takes a Gold membership or a
  permission (Civitai's `model-version-usage-control.ts`), which is why it is
  rare.
- **An image's size comes as `Size`, or as `width` and `height`.** Of one
  library's 120,104 stored images, 17,672 had both, and they always agreed;
  24,315 had `width`/`height` alone - 14,416 the picture's own size, 8,932
  the same shape scaled (a Hires fix), 472 another shape, 495 unreadable
  (read-only, 2026-10-18). They are the metadata's size, not noise; a rule
  for the size reads both (#302).
- **Whether the lookup by hash answers a deleted version's file is not
  known.** #205 needed it to tie an image's `<lora:>` tag to a version
  Civitai deleted; one library had no fair case (root `AGENTS.md`, "A sample
  drawn through a lookup"). The 2 deleted files that were Civitai's own
  bytes - their record beside them lists their SHA-256 - belong to models
  deleted whole, and their hash lookups answered 404 (2026-10-31).
- **A version can list the same bytes twice, under two names.** Of 1,467
  LoRA versions in three searches, 59 list two or more files with a
  SHA-256, and 5 of those repeat one (2026-11-01). A match by hash took the
  first file for both until 0.73.1; the file's name decides now
  (`payload_rows.file_row`, #375). Check a test version's hashes before a live
  check of two files: #374's first one picked such a version, and showed
  #375 instead of the change.
- **Civitai's answer for many models at once can name a file otherwise.**
  `/models?ids=`, which the metadata sync asks, gave a version's second file
  an older name (made up: `b_bf16.safetensors` for `b.safetensors`), where
  `/models/{id}`, `/model-versions/{id}` and the lookup by hash gave the name
  a download saves it under (2026-11-02). One library's two stored answers
  (`version_records`' `listed` and `looked_up`) disagree on the name of 717
  of 5,653 listed files. So a match by name in the metadata sync reads the
  stored lookup's names (#375).
