"""
The Model Manager tab's markup.

Static HTML only, the same as the browser tab: the filter bar, the toolbar,
the progress panels and the empty containers the grid, details and image list
are rendered into by javascript/model_manager.js.
"""
import gradio as gr


def create_ui():
    """Create the Model Manager tab UI."""
    with gr.Blocks(analytics_enabled=False) as model_manager_tab:
        # The entire UI is rendered by JavaScript using API calls
        # This provides the container and triggers JS initialization
        gr.HTML("""
            <div id="model_manager_app">
                <!-- Header -->
                <div class="model-manager-header">
                    <h2>Model Manager</h2>
                </div>

                <!-- Filter bar -->
                <div class="model-manager-filters">
                    <div class="filter-row">
                        <div class="filter-group">
                            <label>Type</label>
                            <select id="mm_type">
                                <option value="">All</option>
                                <option value="Checkpoint" selected>Checkpoint</option>
                                <option value="LORA">LORA</option>
                                <option value="TextualInversion">Embedding</option>
                                <option value="VAE">VAE</option>
                                <option value="Controlnet">ControlNet</option>
                                <option value="Upscaler">Upscaler</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>Has Civitai Data</label>
                            <select id="mm_civitai">
                                <option value="">All</option>
                                <option value="Yes">Yes</option>
                                <option value="No">No</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>Base Model</label>
                            <select id="mm_base_model">
                                <option value="">All</option>
                                <option value="Flux">Flux</option>
                                <option value="Flux.1 D">Flux.1 D</option>
                                <option value="Flux.1 S">Flux.1 S</option>
                                <option value="HiDream">HiDream</option>
                                <option value="Illustrious">Illustrious</option>
                                <option value="NoobAI">NoobAI</option>
                                <option value="Pony">Pony</option>
                                <option value="Qwen">Qwen</option>
                                <option value="SD 1.4">SD 1.4</option>
                                <option value="SD 1.5">SD 1.5</option>
                                <option value="SD 1.5 Hyper">SD 1.5 Hyper</option>
                                <option value="SD 2.1">SD 2.1</option>
                                <option value="SDXL">SDXL</option>
                                <option value="SDXL 1.0">SDXL 1.0</option>
                                <option value="SDXL 1.0 LCM">SDXL 1.0 LCM</option>
                                <option value="SDXL Lightning">SDXL Lightning</option>
                                <option value="Wan Video 2.2 I2V-A14B">Wan Video 2.2 I2V-A14B</option>
                                <option value="Wan Video 2.2 T2V-A14B">Wan Video 2.2 T2V-A14B</option>
                                <option value="ZImageTurbo">ZImageTurbo</option>
                                <option value="Other">Other</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>NSFW Levels</label>
                            <div class="mm-multiselect" id="mm_nsfw_dropdown">
                                <div class="mm-multiselect-display" onclick="window.mmToggleNsfwDropdown()">
                                    <span id="mm_nsfw_display">PG, PG-13</span>
                                    <span class="mm-multiselect-arrow">▼</span>
                                </div>
                                <div class="mm-multiselect-panel" id="mm_nsfw_panel">
                                    <label class="mm-multiselect-item"><input type="checkbox" value="PG" checked> PG</label>
                                    <label class="mm-multiselect-item"><input type="checkbox" value="PG-13" checked> PG-13</label>
                                    <label class="mm-multiselect-item"><input type="checkbox" value="R"> R</label>
                                    <label class="mm-multiselect-item"><input type="checkbox" value="X"> X</label>
                                    <label class="mm-multiselect-item"><input type="checkbox" value="XXX"> XXX</label>
                                    <label class="mm-multiselect-item"><input type="checkbox" value="Blocked"> Blocked</label>
                                    <label class="mm-multiselect-item"><input type="checkbox" value="Unknown"> Unknown</label>
                                    <div class="mm-multiselect-divider"></div>
                                    <label class="mm-multiselect-item"><input type="checkbox" id="mm_nsfw_use_max" checked> Use max level</label>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="filter-row">
                        <div class="filter-group">
                            <label>Bookmarked</label>
                            <select id="mm_is_bookmarked">
                                <option value="">All</option>
                                <option value="true">Yes</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>Min Versions</label>
                            <input type="number" id="mm_min_versions" min="1" placeholder="Any" style="width: 70px;">
                        </div>
                        <div class="filter-group">
                            <label>Model Preview</label>
                            <label class="mm-checkbox-label">
                                <input type="checkbox" id="mm_preview_least_nsfw"> Hide NSFW
                            </label>
                        </div>
                        <div class="filter-group-bordered">
                            <div class="filter-group">
                                <label>Sort By</label>
                                <select id="mm_sort_by">
                                    <option value="name">Name</option>
                                    <option value="file_size">File Size</option>
                                    <option value="file_modified">File Modified</option>
                                    <option value="published_at">Published At</option>
                                    <option value="scanned_at">Scanned At</option>
                                    <option value="downloaded_at" selected>Downloaded At</option>
                                    <option value="updated_at">Updated At</option>
                                    <option value="rating">Rating</option>
                                    <option value="download_count">Download Count</option>
                                </select>
                            </div>
                            <div class="filter-group">
                                <label>Order</label>
                                <select id="mm_sort_order">
                                    <option value="asc">Ascending</option>
                                    <option value="desc" selected>Descending</option>
                                </select>
                            </div>
                        </div>
                    </div>
                    <div class="filter-row">
                        <div class="filter-group">
                            <label>Commercial Use</label>
                            <div class="mm-multiselect" id="mm_commercial_dropdown">
                                <div class="mm-multiselect-display" onclick="window.mmToggleCommercialDropdown()">
                                    <span id="mm_commercial_display">All</span>
                                    <span class="mm-multiselect-arrow">▼</span>
                                </div>
                                <div class="mm-multiselect-panel" id="mm_commercial_panel">
                                    <label class="mm-multiselect-item"><input type="checkbox" value="None" checked> None (No commercial)</label>
                                    <label class="mm-multiselect-item"><input type="checkbox" value="Image" checked> Image (Sell images)</label>
                                    <label class="mm-multiselect-item"><input type="checkbox" value="Rent" checked> Rent (Gen services)</label>
                                    <label class="mm-multiselect-item"><input type="checkbox" value="RentCivit" checked> RentCivit (Civitai gen)</label>
                                    <label class="mm-multiselect-item"><input type="checkbox" value="Sell" checked> Sell (Sell model)</label>
                                </div>
                            </div>
                        </div>
                        <div class="filter-group">
                            <label>Allow Derivatives</label>
                            <select id="mm_allow_derivatives" title="Unknown covers models with no Civitai data, which have no licence to read">
                                <option value="" selected>Any</option>
                                <option value="true">Yes</option>
                                <option value="false">No</option>
                                <option value="unknown">Unknown</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>Allow Different License</label>
                            <select id="mm_allow_different_license" title="Unknown covers models with no Civitai data, which have no licence to read">
                                <option value="" selected>Any</option>
                                <option value="true">Yes</option>
                                <option value="false">No</option>
                                <option value="unknown">Unknown</option>
                            </select>
                        </div>
                    </div>
                    <div class="filter-row">
                        <div class="filter-group" style="flex: 1;">
                            <label>Search</label>
                            <input type="text" id="mm_search" placeholder="Search by name or trigger words, or target one model: model:123 / version:456 / hash:ABC / file:name" title="Prefixed searches match exactly: model:&lt;id&gt;, version:&lt;id&gt;, hash:&lt;any hash&gt;, file:&lt;filename&gt;">
                        </div>
                    </div>
                    <div class="filter-buttons-row">
                        <button id="mm_load_btn" class="mm-btn primary">Load Models</button>
                        <button id="mm_save_search_btn" class="mm-btn secondary" title="Save current filters. Right-click to clear saved filters.">Save Search</button>
                    </div>
                    <div class="filter-buttons-row">
                        <div class="mm-button-group" title="Fetch data from Civitai">
                            <button id="mm_sync_btn" class="mm-btn secondary" title="Choose which models to refresh, and how much of each">Sync with Civitai...</button>
                            <button id="mm_sync_cancel_btn" class="mm-btn danger" style="display:none;">Cancel</button>
                        </div>
                        <div class="mm-button-group" title="Rescan the model directories on disk">
                            <button id="mm_refresh_btn" class="mm-btn secondary" title="Scan model directories and refresh database">Refresh DB</button>
                            <button id="mm_scan_cancel_btn" class="mm-btn danger" style="display:none;">Cancel</button>
                        </div>
                    </div>
                </div>

                <!-- Sync dialog: what to refresh, and what that will cost -->
                <div id="mm_sync_dialog" class="mm-dialog-backdrop" style="display: none;">
                    <div class="mm-dialog" role="dialog" aria-modal="true" aria-labelledby="mm_sync_dialog_title">
                        <h3 id="mm_sync_dialog_title">Sync with Civitai</h3>

                        <div class="mm-dialog-section">
                            <div class="mm-dialog-heading">Models</div>
                            <label class="mm-dialog-option">
                                <input type="radio" name="mm_sync_scope" value="all" checked>
                                <span>All models</span>
                                <span class="mm-dialog-count" id="mm_scope_all"></span>
                            </label>
                            <label class="mm-dialog-option">
                                <input type="radio" name="mm_sync_scope" value="results">
                                <span>These search results</span>
                                <span class="mm-dialog-count" id="mm_scope_results"></span>
                            </label>
                            <label class="mm-dialog-option">
                                <input type="radio" name="mm_sync_scope" value="stale">
                                <span>Not synced in</span>
                                <select id="mm_sync_stale_days" class="mm-dialog-select"></select>
                            </label>
                            <label class="mm-dialog-option">
                                <input type="radio" name="mm_sync_scope" value="downloaded">
                                <span>Downloaded in</span>
                                <select id="mm_sync_downloaded_days" class="mm-dialog-select"></select>
                            </label>
                        </div>

                        <div class="mm-dialog-section">
                            <div class="mm-dialog-heading">Include</div>
                            <label class="mm-dialog-option" title="Descriptions, tags, stats, licences. Always included.">
                                <input type="checkbox" checked disabled>
                                <span>Metadata</span>
                                <span class="mm-dialog-cost" id="mm_cost_metadata"></span>
                            </label>
                            <label class="mm-dialog-option" title="Refetch each model's example images">
                                <input type="checkbox" id="mm_sync_images">
                                <span>Example images</span>
                                <span class="mm-dialog-cost" id="mm_cost_images"></span>
                            </label>
                            <label class="mm-dialog-option" id="mm_sync_prompts_row" title="The prompt and settings behind each image. Civitai serves these one small batch at a time, so this is most of a full sync.">
                                <input type="checkbox" id="mm_sync_prompts" checked disabled>
                                <span>Image prompts</span>
                                <span class="mm-dialog-cost" id="mm_cost_prompts"></span>
                            </label>
                            <label class="mm-dialog-option" title="Read every byte of every model file to identify it again. Only needed for files Civitai has never matched.">
                                <input type="checkbox" id="mm_sync_rehash">
                                <span>Re-identify by hashing</span>
                                <span class="mm-dialog-cost">hours</span>
                            </label>
                            <label class="mm-dialog-option mm-dialog-sub" id="mm_sync_force_row" style="display: none;" title="Re-download data even where it already exists">
                                <input type="checkbox" id="mm_sync_force">
                                <span>Force refresh</span>
                            </label>
                        </div>

                        <div class="mm-dialog-estimate" id="mm_sync_estimate">Estimating...</div>

                        <div class="mm-dialog-actions">
                            <button id="mm_sync_dialog_cancel" class="mm-btn secondary">Cancel</button>
                            <button id="mm_sync_dialog_start" class="mm-btn primary">Start</button>
                        </div>
                    </div>
                </div>

                <!-- Scan Progress -->
                <div id="mm_scan_progress" class="model-manager-sync-progress" style="display: none;">
                    <div class="sync-progress-bar">
                        <div class="sync-progress-fill" id="mm_scan_fill"></div>
                    </div>
                    <div class="sync-progress-text" id="mm_scan_text">Preparing...</div>
                </div>

                <!-- Sync Progress -->
                <div id="mm_sync_progress" class="model-manager-sync-progress" style="display: none;">
                    <div class="sync-progress-bar">
                        <div class="sync-progress-fill" id="mm_sync_fill"></div>
                    </div>
                    <div class="sync-progress-text" id="mm_sync_text">Preparing...</div>
                </div>

                <!-- Status -->
                <div id="mm_status" class="model-manager-status">
                    Ready. Click 'Load Models' to browse.
                </div>

                <!-- Model Grid -->
                <div id="mm_grid" class="model-grid">
                    <div class="model-grid-empty">Click 'Load Models' to browse your models.</div>
                </div>

                <!-- Model Details (shown when model selected) -->
                <div id="mm_details" class="model-details" style="display: none;">
                    <!-- Details populated by JS -->
                </div>

                <!-- Model Images (shown when model selected) -->
                <div id="mm_images" class="model-images" style="display: none;">
                    <!-- Images populated by JS -->
                </div>
            </div>
        """, elem_id="model_manager_container")

    return [(model_manager_tab, "Model Manager", "model_manager_tab")]
