# Project: SD WebUI Forge Model Manager

A model management extension for Stable Diffusion WebUI Forge that provides browsing, filtering, and organization of local models using Civitai metadata.

## Critical Claude Tooling Instructions

**IMPORTANT: These instructions address known tool behavior issues that MUST be followed to avoid failures.**

### File Editing - Read and Edit in Same Message

When editing files, the Read and Edit tools MUST be called together in the same message block. Calling them in separate messages causes state loss and results in:
- Edit failing with "File has been unexpectedly modified"
- Write failing with "File has not been read yet"

**CORRECT - Both tools in same message:**
```
Message 1:
  [Read file_path="/path/to/file"]
  [Edit file_path="/path/to/file" old_string="..." new_string="..."]
```

**INCORRECT - Tools in separate messages:**
```
Message 1:
  [Read file_path="/path/to/file"]

Message 2:
  [Edit file_path="/path/to/file" ...]  <- WILL FAIL
```

This applies to both Edit and Write tools. Always read and modify files in a single response.

## Project Overview

### Purpose
Provide a comprehensive model management interface that:
- Displays all local models with thumbnails and metadata
- Fetches and caches Civitai metadata for models
- Allows filtering and sorting by various criteria
- Shows model details and example images
- Enables sending image generation parameters to txt2img/img2img

### Key Features (V1)
- Model grid view with thumbnails
- Filter bar (type, base model, NSFW level, tags, dates, etc.)
- Sort options (name, size, date, rating, downloads)
- Model details panel with full metadata
- Image gallery with generation parameters
- Duplicate/version detection and grouping
- On-demand loading (user applies filters, clicks Load)

### Data Storage
Compatible with existing Civitai browser extensions:
```
model.safetensors
model.civitai.info     <- Model + version metadata (JSON)
model.images.json      <- Image metadata with generation params (our format)
model.preview.png      <- Thumbnail image
```

### NSFW Levels
Civitai uses: PG, PG-13, R, X, XXX, Banned
Model NSFW = max(model.nsfw, version.nsfw, max(images[].nsfw))

## Architecture

### Backend (Python)
- `scripts/model_manager_ui.py` - Gradio UI, settings, tab registration
- `model_manager/scanner.py` - Scan model directories, find models
- `model_manager/civitai_api.py` - Civitai API client, rate limiting
- `model_manager/models.py` - Data classes for models, images, metadata
- `model_manager/storage.py` - Read/write JSON files

### Frontend (JavaScript)
- `javascript/model_manager.js` - Grid rendering, interactions, image gallery

## Development Rules

- When operator asks a question, understand clearly before jumping to conclusions
- Do not make code changes unless explicitly asked
- Always ask for confirmation before making changes
- Honor the current folder structure
- Commit frequently at logical checkpoints
- Never create workflow-specific modules - keep everything generic

## Backlog (Future Features)

- Favorites/Bookmarks - mark frequently used models
- Usage History - track recently used, sort by usage
- Groups/Collections - manual grouping
- Inter-extension with Task Scheduler - submit tasks for model groups
- Missing File Detection - civitai data exists but model deleted
- Version Check - show if newer version available on Civitai
