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
- **Civitai's `nsfw` search parameter has two states, not three.** `true`
  gives both kinds (42 of 100 newest LoRAs NSFW), `false` or left out the
  safe ones alone: there is no "NSFW only". Every model payload carries
  `nsfw` (300 of 300); a thin sidecar may not (8 of 1,032 here), and the flag
  is then stored as not said (#141).
