"""
The Civitai Browser tab's markup.

Static HTML only: every row, card and panel is filled in by
javascript/civitai_browser.js against the API. Gradio is used for the shell
so the tab appears in the right place, and for nothing else.
"""
import gradio as gr


def create_civitai_browser_ui():
    """Create the Civitai Browser tab UI."""
    with gr.Blocks(analytics_enabled=False) as civitai_browser_tab:
        gr.HTML("""
            <div id="civitai_browser_app">
                <!-- Header -->
                <div class="cb-header">
                    <h2>Civitai Browser</h2>
                </div>

                <!-- Shown only when Civitai cannot be asked properly -->
                <div id="cb_api_key_warning" class="mm-banner" style="display: none;">
                    <span class="mm-banner-icon">!</span>
                    <span>
                        <strong>No Civitai API key.</strong>
                        Searches are limited to 0.5 requests per second instead of 6,
                        image prompts cannot be fetched at all, and some models refuse
                        to download.
                        Set one in <strong>Settings &rarr; Model Manager &rarr; Civitai API Key</strong>.
                    </span>
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
                            <label>Checkpoint</label>
                            <select id="cb_checkpoint_type" title="Only applies when Type is Checkpoint">
                                <option value="">All</option>
                                <option value="Trained">Trained</option>
                                <option value="Merge">Merge</option>
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
                            <div class="filter-group filter-group-wide">
                                <label>Sort</label>
                                <select id="cb_sort">
                                    <option value="Most Downloaded">Most Downloaded</option>
                                    <option value="Highest Rated">Highest Rated</option>
                                    <option value="Most Liked">Most Liked</option>
                                    <option value="Most Collected">Most Collected</option>
                                    <option value="Most Discussed">Most Discussed</option>
                                    <option value="Most Images">Most Images</option>
                                    <option value="Newest">Newest</option>
                                    <option value="Oldest">Oldest</option>
                                </select>
                            </div>
                        </div>
                    </div>
                    <div class="filter-row">
                        <div class="filter-group filter-group-half">
                            <label>Search</label>
                            <input type="text" id="cb_search" placeholder="Search models...">
                        </div>
                        <div class="filter-group" title="Size of the latest version's primary file. Civitai cannot filter on this, so results are checked here - a narrow range can take a few searches to fill a page.">
                            <label>File Size (GB)</label>
                            <div class="filter-range">
                                <input type="number" id="cb_min_size" min="0" step="0.1" placeholder="Min">
                                <span>-</span>
                                <input type="number" id="cb_max_size" min="0" step="0.1" placeholder="Max">
                            </div>
                        </div>
                        <div class="filter-group filter-group-half">
                            <label>Tag</label>
                            <div class="cb-tag-container">
                                <input type="text" id="cb_tag_input" placeholder="Type to search tags..." autocomplete="off">
                                <div class="cb-tag-dropdown" id="cb_tag_dropdown"></div>
                            </div>
                        </div>
                        <div class="filter-group">
                            <!-- Every group is a caption over its controls, so
                                 the row lines up without being told to. -->
                            <label>Options</label>
                            <div class="filter-checkboxes">
                                <label class="cb-checkbox-label">
                                    <input type="checkbox" id="cb_nsfw"> Include NSFW
                                </label>
                                <label class="cb-checkbox-label" title="Only show models whose images have a prompt plus steps/sampler/CFG. Slower: each model is checked against Civitai.">
                                    <input type="checkbox" id="cb_require_prompt"> Only with usable prompts
                                </label>
                            </div>
                        </div>
                    </div>
                    <!-- The same row the Model Manager puts its actions on. -->
                    <div class="filter-buttons-row">
                        <button type="button" id="cb_search_btn" class="cb-btn primary" onclick="window.cbSearch && window.cbSearch()" oncontextmenu="window.cbClearSearchCache && window.cbClearSearchCache(); return false;" title="Right-click to clear pagination cache">Search</button>
                        <button type="button" id="cb_resume_btn" class="cb-btn" onclick="window.cbResumePage && window.cbResumePage()" style="display: none;">Resume</button>
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
