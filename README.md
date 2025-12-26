# SD WebUI Forge Model Manager

A model management extension for Stable Diffusion WebUI Forge that provides browsing, filtering, and organization of local models using Civitai metadata.

## Features

- **Model Grid View**: Browse all your models with thumbnails
- **Filter Bar**: Filter by type, base model, NSFW level, tags, and more
- **Sort Options**: Sort by name, file size, date, rating, downloads
- **Model Details**: View full metadata, trigger words, and tags
- **Civitai Integration**: Fetch and cache model metadata from Civitai
- **Duplicate Detection**: Find multiple versions of the same model
- **On-Demand Loading**: Apply filters then load - no startup slowdown

## Installation

1. Open SD WebUI Forge
2. Go to **Extensions** tab
3. Go to **Install from URL**
4. Paste: `https://github.com/YOUR_USERNAME/sd-webui-forge-model-manager`
5. Click **Install**
6. Restart the WebUI

## Usage

1. Navigate to the **Model Manager** tab
2. Set your filters (or leave as default)
3. Click **Load Models**
4. Click any model card to view details

## Settings

| Setting | Description |
|---------|-------------|
| Civitai API Key | Optional. Higher rate limits for API requests |
| Default NSFW Filter | Maximum NSFW level to show by default |

## NSFW Levels

The extension uses Civitai's NSFW levels: PG, PG-13, R, X, XXX

The effective NSFW level for a model is the maximum of:
- Model-level NSFW rating
- Version-level NSFW rating
- Highest image NSFW rating

## License

MIT License
