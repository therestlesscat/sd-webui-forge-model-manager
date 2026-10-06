"""
The Generations tab's markup: every image you have generated, newest first.

Static HTML only, as the other tabs: javascript/tabs/generations.mjs fills the
grid from the API. A tile per generation - its first images, and how many it
has - or per group of images, "Group by" says what; a click on one opens it
in a grid of its own, with Back. A search narrows them to the images whose
prompts hold its words, or that a task of the Queue made.
"""
import gradio as gr

from .header import header_actions


def create_generations_ui():
    """Create the Generations tab UI."""
    with gr.Blocks(analytics_enabled=False) as generations_tab:
        gr.HTML("""
            <div id="generations_app">
                <div class="gen-header">
                    <h2>Generations</h2>
                    <!-- actions -->
                </div>

                <!-- Notes to the user per release: filled by shared/notes.mjs -->
                <div id="gen_notes" class="mm-notes"></div>

                <!-- Held at the top while the grid scrolls, as the other
                     tabs' banners are: the switches, Back, the banner. -->
                <div class="gen-sticky-head">
                <div class="gen-toolbar">
                    <!-- Search: Enter searches; emptied, it shows everything again -->
                    <input type="search" id="gen_search" class="gen-search" data-action="generations.search"
                           placeholder="Search prompts, or task:17" aria-label="Search your generations"
                           title="Every word must be in an image's prompt or negative prompt; a &quot;quoted phrase&quot; as one. task:17 - the images task 17 of the Queue made.">
                    <!-- Group by: a menu, each grouping with a "then by" list beside
                         it, filled by generations.mjs -->
                    <span class="gen-view-switch gen-group-menu" title="Gather images that share something, whatever generation they are of">
                        Group by
                        <!-- The list opens under the button, from its left edge -->
                        <span class="gen-group-anchor">
                            <button type="button" id="gen_group_by" class="gen-group-button"
                                    aria-haspopup="true" aria-expanded="false">Nothing</button>
                            <div class="gen-group-list gen-menu-panel" hidden></div>
                        </span>
                    </span>
                    <label class="gen-view-switch" title="Every tile the same size, strictly newest first: wide images are cropped to a single column rather than a later tile filling in beside them">
                        <input type="checkbox" id="gen_preserve_order" data-action="generations.preserveOrder">
                        Preserve order
                    </label>
                    <label class="gen-view-switch" title="Rate each image's NSFW level: a row of levels under every image">
                        <input type="checkbox" id="gen_rate" data-action="generations.rating">
                        Rate
                    </label>
                    <label class="gen-view-switch" title="Tick batches and images, then delete them all at once. A batch's tick is the whole generation">
                        <input type="checkbox" id="gen_select" data-action="generations.selecting">
                        Select
                    </label>
                    <span id="gen_select_bar" class="mm-select-bar" hidden></span>
                    <span class="gen-toolbar-fill"></span>
                    <button type="button" class="mm-btn secondary" id="gen_refresh_btn"
                            data-action="generations.refresh">Refresh</button>
                </div>

                <!-- Inside a group or a batch: Back, and where it is -->
                <div id="gen_path"></div>
                <!-- The banner: what is stored, and the NSFW switch -->
                <div id="gen_banner"></div>
                </div>
                <div id="gen_grid" class="gen-grid"></div>
                <div id="gen_status" class="gen-status"></div>
                <!-- Scrolled near, it loads the next part -->
                <div id="gen_sentinel" class="gen-sentinel"></div>
            </div>
        """.replace("<!-- actions -->", header_actions("generations")), elem_id="generations_container")

    return generations_tab
