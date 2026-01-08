# Civitai Browser Feature Plan

## Overview
Add a new tab "Civitai Browser" for browsing and downloading models directly from Civitai, with local ownership detection and image caching.

---

## 1. Database Changes

### Schema v9: Add civitai_browser_cache table

```sql
CREATE TABLE civitai_browser_cache (
    model_id INTEGER NOT NULL,
    version_id INTEGER NOT NULL,
    type TEXT NOT NULL,           -- "image" or "cursor"
    data_id TEXT NOT NULL,        -- image_id or "cursor"
    cached_at TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (version_id, type, data_id)
)

CREATE INDEX idx_browser_cache_version_type ON civitai_browser_cache(version_id, type)
```

**Files:**
- `model_manager/models_db.py` - Add migration, SCHEMA_VERSION = 9

---

## 2. Settings

Add to `scripts/model_manager_ui.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `model_manager_civitai_page_size` | 10 | Models per page in Civitai Browser |
| `model_manager_civitai_folder_template` | `_{baseModel}/{modelName}` | Subfolder template for downloads |

**Template placeholders:**
- `{baseModel}` - SD 1.5, SDXL, Pony, Flux, etc.
- `{modelName}` - Model name from Civitai
- `{creator}` - Creator username
- `{modelId}` - Civitai model ID

---

## 3. Backend API Endpoints

### New endpoints in `model_manager/api.py`:

#### Search/Browse
```
GET /model-manager/civitai/models
    ?query=          # Search text
    &types=          # Comma-separated: Checkpoint,LORA,etc
    &baseModels=     # Comma-separated: SD 1.5,SDXL,etc
    &nsfw=           # true/false or level
    &sort=           # Most Downloaded, Highest Rated, Newest
    &period=         # AllTime, Year, Month, Week, Day
    &tags=           # Comma-separated tags
    &page=           # Page number
    &limit=          # Page size (from settings)

Returns: { models: [...], metadata: { totalCount, currentPage, pageSize } }
Each model includes: owned_locally (bool), owned_versions (list of version_ids)
```

#### Get Model Details
```
GET /model-manager/civitai/models/{model_id}

Returns: Full model data with all versions, local ownership status per version
```

#### Load More Images
```
GET /model-manager/civitai/versions/{version_id}/images
    ?cursor=         # Optional, for pagination

Returns: { images: [...], nextCursor: string|null }
- Checks cache first
- Fetches from Civitai if not cached
- Stores in civitai_browser_cache
- Updates cursor in cache
```

#### Get Cached Images
```
GET /model-manager/civitai/versions/{version_id}/images/cached

Returns: { images: [...], cursor: string|null }
- Returns only cached data, no API call
```

#### Download Model
```
POST /model-manager/civitai/download
    version_id: int
    file_id: int (optional, for specific file)

- Determines model type folder from WebUI config
- Applies folder template from settings
- Downloads file to target location
- Syncs to database after download
- Returns: { success, file_path, message }
```

---

## 4. Cache Operations

### New file: `model_manager/_browser_cache_ops.py`

```python
class BrowserCacheOps:
    def get_cached_images(version_id: int) -> List[Dict]
    def store_images(model_id: int, version_id: int, images: List[Dict])
    def get_cursor(version_id: int) -> Optional[str]
    def store_cursor(model_id: int, version_id: int, cursor: str)
    def clear_version_cache(version_id: int)
```

---

## 5. Download Logic

### File: `model_manager/download_service.py`

```python
class DownloadService:
    def get_model_type_folder(model_type: str) -> str
        """Get WebUI folder for model type (Lora, Stable-diffusion, etc)"""

    def apply_folder_template(template: str, model_data: Dict) -> str
        """Replace {baseModel}, {modelName}, {creator}, {modelId}"""

    def download_version(version_id: int, file_id: Optional[int]) -> DownloadResult
        """
        1. Fetch version info from Civitai
        2. Determine target folder
        3. Download file with progress
        4. Download metadata (.civitai.info)
        5. Sync to database
        """
```

---

## 6. Frontend

### New file: `javascript/civitai_browser.js`

#### Layout
- Tab: "Civitai Browser" (alongside Model Manager)
- Filter bar at top (all Civitai filters)
- Cards stacked and centered (not grid)
- Fixed page size from settings

#### Model Card
- Thumbnail image
- Model name, type, base model
- Creator name
- Stats (downloads, rating)
- **"Owned" indicator** - border highlight + badge if locally owned

#### Model Detail View
- Model info (name, description, tags)
- Version selector dropdown
- Version details (base model, trained words)
- Images from version object (initial, no API call)
- "Load More Images" button (fetches 10, caches)
- **Download button** - shows progress, triggers download

#### Pagination
- Previous / Next buttons
- Page indicator (Page X of Y)

### New file: `style/civitai_browser.css`
- Card styles (stacked, centered)
- Owned indicator styles
- Download progress styles

---

## 7. Local Ownership Detection

When fetching models from Civitai API:
1. Get list of model_ids and version_ids from response
2. Query local database:
   ```sql
   SELECT model_id, id as version_id FROM model_versions
   WHERE model_id IN (?) OR id IN (?)
   ```
3. Attach `owned_locally` and `owned_versions` to each model in response

---

## 8. Implementation Order

### Phase 1: Foundation
1. [x] Schema v9 migration (cache table)
2. [x] Add settings (page size, folder template)
3. [x] Create `_browser_cache_ops.py`

### Phase 2: API
4. [x] Civitai search endpoint with ownership detection
5. [x] Model details endpoint
6. [x] Images endpoint with caching
7. [x] Download endpoint

### Phase 3: Download Service
8. [x] Model type folder detection
9. [x] Folder template processing
10. [x] File download with progress (aria2c + requests fallback)
11. [x] Post-download sync

### Phase 4: Frontend
12. [x] Tab and basic layout
13. [x] Filter bar
14. [x] Model cards with owned indicator
15. [x] Model detail view
16. [x] Image loading with "Load More"
17. [x] Download UI with progress
18. [x] Pagination

---

## 9. Civitai API Reference

### Search Models
```
GET https://civitai.com/api/v1/models
    ?query=
    &types=
    &baseModels=
    &sort=Highest Rated|Most Downloaded|Newest
    &period=AllTime|Year|Month|Week|Day
    &nsfw=true|false
    &tag=
    &limit=
    &page=
```

### Get Model
```
GET https://civitai.com/api/v1/models/{id}
```

### Get Version Images
```
GET https://civitai.com/api/v1/images
    ?modelVersionId=
    &limit=
    &cursor=
```

### Download
```
GET https://civitai.com/api/download/models/{versionId}
    ?type=Model|VAE|Training Data
    &format=SafeTensor|PickleTensor
```
