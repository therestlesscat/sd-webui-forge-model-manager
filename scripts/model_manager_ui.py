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
        "model_manager_nsfw_filter",
        shared.OptionInfo(
            default="PG-13",
            label="Default NSFW Filter",
            component=gr.Dropdown,
            component_args={
                "choices": ["PG", "PG-13", "R", "X", "XXX", "All"]
            },
            section=section,
        ).info("Default maximum NSFW level to show. 'All' shows everything.")
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
                            <label>Search</label>
                            <input type="text" id="mm_search" placeholder="Search by name, trigger words...">
                        </div>
                        <div class="filter-group">
                            <label>Type</label>
                            <select id="mm_type">
                                <option value="">All</option>
                                <option value="Checkpoint">Checkpoint</option>
                                <option value="LORA">LORA</option>
                                <option value="TextualInversion">Embedding</option>
                                <option value="VAE">VAE</option>
                                <option value="Controlnet">ControlNet</option>
                                <option value="Upscaler">Upscaler</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>Base Model</label>
                            <select id="mm_base_model">
                                <option value="">All</option>
                                <option value="SD 1.5">SD 1.5</option>
                                <option value="SDXL">SDXL</option>
                                <option value="Pony">Pony</option>
                                <option value="Flux">Flux</option>
                                <option value="Illustrious">Illustrious</option>
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
                                    <label class="mm-multiselect-item"><input type="checkbox" value="Unknown"> Unknown</label>
                                    <div class="mm-multiselect-divider"></div>
                                    <label class="mm-multiselect-item"><input type="checkbox" id="mm_nsfw_use_max"> Use max level</label>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="filter-row">
                        <div class="filter-group">
                            <label>Has Civitai Data</label>
                            <select id="mm_civitai">
                                <option value="">All</option>
                                <option value="Yes">Yes</option>
                                <option value="No">No</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>Sort By</label>
                            <select id="mm_sort_by">
                                <option value="name">Name</option>
                                <option value="file_size">File Size</option>
                                <option value="file_modified">Date Modified</option>
                                <option value="published_at">Date Published</option>
                                <option value="rating">Rating</option>
                                <option value="download_count">Downloads</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>Order</label>
                            <select id="mm_sort_order">
                                <option value="asc">Ascending</option>
                                <option value="desc">Descending</option>
                            </select>
                        </div>
                        <div class="filter-group filter-actions">
                            <button id="mm_load_btn" class="mm-btn primary">Load Models</button>
                            <button id="mm_refresh_btn" class="mm-btn secondary" title="Scan model directories and refresh database">Refresh DB</button>
                            <button id="mm_scan_cancel_btn" class="mm-btn danger" style="display:none;">Cancel</button>
                            <span class="filter-actions-divider">|</span>
                            <button id="mm_sync_btn" class="mm-btn secondary">Sync with Civitai</button>
                            <label class="mm-checkbox-label" title="Re-download data even if already exists">
                                <input type="checkbox" id="mm_sync_force"> Force
                            </label>
                            <button id="mm_sync_cancel_btn" class="mm-btn danger" style="display:none;">Cancel</button>
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


# Register callbacks
script_callbacks.on_ui_settings(on_ui_settings)
script_callbacks.on_ui_tabs(create_ui)

# Import API module to register endpoints
from model_manager import api

print("[ModelManager] Extension loaded")
