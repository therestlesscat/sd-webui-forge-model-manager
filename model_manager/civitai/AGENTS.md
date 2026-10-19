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
- **Civitai's `nsfw` search parameter has two states, not three, and
  neither is "every model".** `true` leaves out the models Civitai marks
  `minor` (4 of 4 seen); left out, or `false`, it returns only models whose
  `nsfwLevel` has the PG bit (56 of 100 random models, every level odd),
  whatever their `nsfw` flag - not "the safe ones alone", as this said. There
  is no "NSFW only". A batch by `ids` also leaves out some models for no known
  reason: absent is not deleted, only a 404 from `/models/<id>` is (#262). The
  same with an API key and without; rapid single lookups get 429 after about
  30. Every model payload carries `nsfw` (300 of 300); a thin sidecar may not
  (8 of 1,032 here), and the flag is then stored as not said (#141).
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
