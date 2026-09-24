# SD WebUI Forge Model Manager

A model management extension for Stable Diffusion WebUI Forge. It indexes your local
models, enriches them with Civitai metadata, and adds a Civitai browser you can download
from without leaving the WebUI.

Two tabs are added: **Model Manager** and **Civitai Browser**.

## Model Manager

Browse and organize the models already on disk.

- **Grid view** with thumbnails, configurable card size, and paginated loading
- **Filters**: search, type, base model, NSFW level (max or contains mode), Civitai data
  present, bookmarked, minimum version count, and licence terms (commercial use,
  derivatives, different licence)
- **Sort** by name, file size, file modified, published, scanned, downloaded, updated,
  rating, or download count
- **Version grouping**: versions of the same model are grouped, with a version selector
  in the details panel
- **Details panel**: trigger words, tags, description, creator, rating, per-level NSFW
  breakdown, licence terms, and the full Civitai image gallery with generation parameters
- **Send to txt2img / img2img** from any gallery image, including sampler, scheduler, VAE,
  and resource matching against your installed models
- **Bookmarks**, per-model force re-sync, and model deletion (removes the model plus its
  sidecar metadata and preview files)
- **Scan** finds new model files on disk; **Sync** fetches Civitai metadata by file hash

## Civitai Browser

Search Civitai and download directly into the right model folder.

- Search by query, type, base model, tag, period, and sort order, with results streamed
  in as they are found
- **Ownership detection**: models you already have are marked as owned, with a
  "Show in Model Manager" jump
- **Usable-prompt filter**: only show models whose images carry a prompt plus
  steps/sampler/CFG
- Image gallery with pagination and cached results
- **Downloads**: parallel queue with progress, configurable destination folder template,
  automatic metadata sync when the download finishes, and a WebUI model-list refresh

## Installation

1. Open SD WebUI Forge
2. Go to **Extensions** -> **Install from URL**
3. Paste: `https://github.com/therestlesscat/sd-webui-forge-model-manager.git`
4. Click **Install**
5. Restart the WebUI

`blake3` is installed automatically on first run; it is optional and only used as a hash
fallback.

## Usage

1. Open the **Model Manager** tab
2. Click **Scan** to index the models on disk, then **Sync** to fetch Civitai metadata
3. Set your filters and click **Load Models**
4. Click any model card to open its details

## Settings

Found under **Settings -> Model Manager**.

| Setting | Default | Description |
|---------|---------|-------------|
| Civitai API Key | empty | Optional. Higher rate limits for Civitai API requests |
| Model Manager: Models per page | 20 | Model Manager page size |
| Custom Database Path | empty | Full path to the database file. Empty uses the extension folder. Requires restart |
| Preview: Use least NSFW image | on | Off shows the most recent image instead |
| Civitai Browser: Models per page | 20 | Civitai Browser page size |
| Civitai Browser: Download folder template | `_{baseModel}/{modelName}` | Placeholders: `{baseModel}`, `{modelName}`, `{creator}`, `{modelId}` |
| Civitai: Requests per second | 6 | API call rate when an API key is set. Requires restart |
| Civitai Browser: Minimum images with usable prompt | 1 | Threshold for the usable-prompt filter |
| Model Manager: Card size | `200x280` | Card size in pixels, `WIDTHxHEIGHT` |
| Civitai Browser: Card size | `200x280` | Card size in pixels, `WIDTHxHEIGHT` |

## Data storage

Metadata lives in a SQLite database (`models.db` in the extension folder by default).
Sidecar files written next to each model stay compatible with other Civitai extensions:

```
model.safetensors
model.civitai.info     <- model + version metadata
model.preview.png      <- thumbnail
```

## NSFW levels

The extension uses Civitai's NSFW levels: PG, PG-13, R, X, XXX, Blocked.

The effective level for a model is the maximum of:

- Model-level NSFW rating
- Version-level NSFW rating
- Highest image NSFW rating

## License

MIT License
