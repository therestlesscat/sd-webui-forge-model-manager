"""
Model Manager UI - Main extension script.
Provides a tab for browsing and managing local models.
"""
import gradio as gr
from modules import script_callbacks, shared

# Extension info
EXTENSION_NAME = "Model Manager"
EXTENSION_ID = "model_manager"


def on_ui_settings():
    """Register extension settings."""
    section = ("model_manager", EXTENSION_NAME)

    shared.opts.add_option(
        "model_manager_civitai_api_key",
        shared.OptionInfo(
            default="",
            label="Civitai API Key",
            component=gr.Textbox,
            component_args={"type": "password"},
            section=section,
        ).info("Optional. Provides higher rate limits for Civitai API requests.")
    )

    shared.opts.add_option(
        "model_manager_page_size",
        shared.OptionInfo(
            default=10,
            label="Models per page",
            component=gr.Slider,
            component_args={
                "minimum": 5,
                "maximum": 50,
                "step": 5,
            },
            section=section,
        ).info("Number of models to display per page.")
    )

    shared.opts.add_option(
        "model_manager_database_path",
        shared.OptionInfo(
            default="",
            label="Custom Database Path",
            component=gr.Textbox,
            component_args={"placeholder": "e.g., F:\\shared\\models.db"},
            section=section,
        ).info("Full path to database file (including filename). Leave empty to use default location in extension folder. Requires restart to take effect.")
    )

    shared.opts.add_option(
        "model_manager_preview_least_nsfw",
        shared.OptionInfo(
            default=True,
            label="Preview: Use least NSFW image",
            component=gr.Checkbox,
            section=section,
        ).info("If enabled, model previews show the least NSFW image. If disabled, shows the most recent image.")
    )

    # Civitai Browser settings
    shared.opts.add_option(
        "model_manager_civitai_page_size",
        shared.OptionInfo(
            default=10,
            label="Civitai Browser: Models per page",
            component=gr.Slider,
            component_args={
                "minimum": 5,
                "maximum": 50,
                "step": 5,
            },
            section=section,
        ).info("Number of models to display per page in Civitai Browser.")
    )

    shared.opts.add_option(
        "model_manager_civitai_folder_template",
        shared.OptionInfo(
            default="_{baseModel}/{modelName}",
            label="Civitai Browser: Download folder template",
            component=gr.Textbox,
            component_args={"placeholder": "_{baseModel}/{modelName}"},
            section=section,
        ).info("Subfolder template for downloads. Placeholders: {baseModel}, {modelName}, {creator}, {modelId}")
    )

    shared.opts.add_option(
        "model_manager_civitai_min_prompt_images",
        shared.OptionInfo(
            default=1,
            label="Civitai Browser: Minimum images with usable prompt",
            component=gr.Slider,
            component_args={
                "minimum": 1,
                "maximum": 20,
                "step": 1,
            },
            section=section,
        ).info("When 'Only with usable prompts' is enabled, a model must have at least this many images (out of the first 20) carrying a prompt plus steps/sampler/CFG.")
    )

    # Card size settings
    shared.opts.add_option(
        "model_manager_card_size",
        shared.OptionInfo(
            default="200x280",
            label="Model Manager: Card size (WIDTHxHEIGHT)",
            component=gr.Textbox,
            component_args={"placeholder": "200x280"},
            section=section,
        ).info("Size of model cards in Model Manager. Format: WIDTHxHEIGHT in pixels.")
    )

    shared.opts.add_option(
        "model_manager_civitai_card_size",
        shared.OptionInfo(
            default="200x280",
            label="Civitai Browser: Card size (WIDTHxHEIGHT)",
            component=gr.Textbox,
            component_args={"placeholder": "200x280"},
            section=section,
        ).info("Size of model cards in Civitai Browser. Format: WIDTHxHEIGHT in pixels.")
    )


def create_civitai_browser_ui():
    """Create the Civitai Browser tab UI."""
    with gr.Blocks(analytics_enabled=False) as civitai_browser_tab:
        gr.HTML("""
            <div id="civitai_browser_app">
                <!-- Header -->
                <div class="cb-header">
                    <h2>Civitai Browser</h2>
                </div>

                <!-- Filter bar -->
                <div class="cb-filters">
                    <div class="filter-row">
                        <div class="filter-group">
                            <label>Type</label>
                            <select id="cb_type">
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
                            <label>Base Model</label>
                            <select id="cb_base_model">
                                <option value="">All</option>
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
                                <option value="SDXL 1.0">SDXL 1.0</option>
                                <option value="SDXL 1.0 LCM">SDXL 1.0 LCM</option>
                                <option value="SDXL Lightning">SDXL Lightning</option>
                                <option value="Wan Video 2.2 I2V-A14B">Wan Video 2.2 I2V-A14B</option>
                                <option value="Wan Video 2.2 T2V-A14B">Wan Video 2.2 T2V-A14B</option>
                                <option value="ZImageTurbo">ZImageTurbo</option>
                                <option value="Other">Other</option>
                            </select>
                        </div>
                        <div class="filter-group-bordered">
                            <div class="filter-group">
                                <label>Period</label>
                                <select id="cb_period">
                                    <option value="AllTime">All Time</option>
                                    <option value="Year">Year</option>
                                    <option value="Month">Month</option>
                                    <option value="Week">Week</option>
                                    <option value="Day">Day</option>
                                </select>
                            </div>
                            <div class="filter-group">
                                <label>Sort</label>
                                <select id="cb_sort">
                                    <option value="Most Downloaded">Most Downloaded</option>
                                    <option value="Highest Rated">Highest Rated</option>
                                    <option value="Newest">Newest</option>
                                </select>
                            </div>
                        </div>
                    </div>
                    <div class="filter-row">
                        <div class="filter-group filter-group-half">
                            <label>Search</label>
                            <input type="text" id="cb_search" placeholder="Search models...">
                        </div>
                        <div class="filter-group filter-group-half">
                            <label>Tag</label>
                            <div class="cb-tag-container">
                                <input type="text" id="cb_tag_input" placeholder="Type to search tags..." autocomplete="off">
                                <div class="cb-tag-dropdown" id="cb_tag_dropdown"></div>
                            </div>
                        </div>
                        <div class="filter-group">
                            <label class="cb-checkbox-label">
                                <input type="checkbox" id="cb_nsfw"> Include NSFW
                            </label>
                            <label class="cb-checkbox-label" title="Only show models whose images have a prompt plus steps/sampler/CFG. Slower: each model is checked against Civitai.">
                                <input type="checkbox" id="cb_require_prompt"> Only with usable prompts
                            </label>
                        </div>
                        <div class="filter-buttons-group">
                            <button type="button" id="cb_search_btn" class="cb-btn primary" onclick="window.cbSearch && window.cbSearch()" oncontextmenu="window.cbClearSearchCache && window.cbClearSearchCache(); return false;" title="Right-click to clear pagination cache">Search</button>
                            <button type="button" id="cb_resume_btn" class="cb-btn" onclick="window.cbResumePage && window.cbResumePage()" style="display: none;">Resume</button>
                        </div>
                    </div>
                </div>

                <!-- Status -->
                <div id="cb_status" class="cb-status">
                    Click 'Search' to browse Civitai models.
                </div>

                <!-- Model Grid -->
                <div id="cb_grid" class="model-grid">
                    <div class="model-grid-empty">Click 'Search' to browse Civitai models.</div>
                </div>

                <!-- Download Progress (fixed location between grid and details) -->
                <div id="cb_downloads" class="cb-downloads-inline" style="display: none;">
                    <div class="cb-downloads-header">
                        <h4>Downloads</h4>
                        <span class="cb-downloads-summary" id="cb_downloads_summary"></span>
                    </div>
                    <div id="cb_download_list" class="cb-downloads-list"></div>
                </div>

                <!-- Model Details (shown when model selected) -->
                <div id="cb_details" class="model-details" style="display: none;">
                    <!-- Details populated by JS -->
                </div>

                <!-- Model Images (shown when model selected) -->
                <div id="cb_images" class="model-images" style="display: none;">
                    <!-- Images populated by JS -->
                </div>
            </div>
        """, elem_id="civitai_browser_container")

    return civitai_browser_tab


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
                        <div class="filter-group-bordered">
                            <div class="filter-group">
                                <label>Sort By</label>
                                <select id="mm_sort_by">
                                    <option value="name">Name</option>
                                    <option value="file_size">File Size</option>
                                    <option value="file_modified">File Modified</option>
                                    <option value="published_at">Published At</option>
                                    <option value="scanned_at">Scanned At</option>
                                    <option value="downloaded_at">Downloaded At</option>
                                    <option value="updated_at">Updated At</option>
                                    <option value="rating">Rating</option>
                                    <option value="download_count">Download Count</option>
                                </select>
                            </div>
                            <div class="filter-group">
                                <label>Order</label>
                                <select id="mm_sort_order">
                                    <option value="asc">Ascending</option>
                                    <option value="desc">Descending</option>
                                </select>
                            </div>
                        </div>
                    </div>
                    <div class="filter-row">
                        <div class="filter-group" style="flex: 1;">
                            <label>Search</label>
                            <input type="text" id="mm_search" placeholder="Search by name, trigger words...">
                        </div>
                    </div>
                    <div class="filter-buttons-row">
                        <div class="filter-buttons-group">
                            <button id="mm_load_btn" class="mm-btn primary">Load Models</button>
                            <button id="mm_save_search_btn" class="mm-btn secondary" title="Save current filters. Right-click to clear saved filters.">Save Search</button>
                            <button id="mm_refresh_btn" class="mm-btn secondary" title="Scan model directories and refresh database">Refresh DB</button>
                            <button id="mm_scan_cancel_btn" class="mm-btn danger" style="display:none;">Cancel</button>
                        </div>
                        <div class="filter-buttons-group">
                            <button id="mm_sync_btn" class="mm-btn secondary">Sync with Civitai</button>
                            <button id="mm_sync_cancel_btn" class="mm-btn danger" style="display:none;">Cancel</button>
                            <label class="mm-checkbox-label" title="Re-download data even if already exists">
                                <input type="checkbox" id="mm_sync_force"> Force
                            </label>
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


def create_all_tabs():
    """Create all Model Manager tabs."""
    tabs = create_ui()
    civitai_tab = create_civitai_browser_ui()
    tabs.append((civitai_tab, "Civitai Browser", "civitai_browser_tab"))
    return tabs


# Register callbacks
script_callbacks.on_ui_settings(on_ui_settings)
script_callbacks.on_ui_tabs(create_all_tabs)

# Import API module to register endpoints
from model_manager import api

print("[ModelManager] Extension loaded")
