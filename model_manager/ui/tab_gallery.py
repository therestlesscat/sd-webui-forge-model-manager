"""
The Gallery tab's markup (#209): the Civitai images stored for the models in
the library, laid out as the Generations tab lays out your own, in an order a
sorting seed picks.

Static HTML only, as the other tabs: javascript/tabs/gallery.mjs fills the grid
from the API. It draws the Generations tab's grid, so it takes its classes
(gen-), and the stylesheet names both tabs in each rule; its own ids are gal_.
"""
import gradio as gr

from ..scheduler.load import wire_send_buttons
from .header import header_actions


def create_gallery_ui():
    """Create the Gallery tab UI."""
    with gr.Blocks(analytics_enabled=False) as gallery_tab:
        gr.HTML("""
            <div id="gallery_app">
                <div class="gen-header">
                    <h2>Gallery</h2>
                    <!-- actions -->
                </div>

                <!-- Notes to the user per release: filled by shared/notes.mjs -->
                <div id="gal_notes" class="mm-notes"></div>

                <!-- Held at the top while the grid scrolls: the seed, Group by, Back, the banner -->
                <div class="gen-sticky-head">
                <div class="gen-toolbar">
                    <!-- The seed: typed, it is kept and the grid starts again in its order -->
                    <label class="gen-view-switch" title="The same seed always gives the same order; another seed, another order">
                        Seed
                        <input type="number" id="gal_seed" class="gen-search gal-seed" min="1" max="2147483647" step="1"
                               data-action="gallery.seed" aria-label="Sorting seed">
                    </label>
                    <button type="button" class="mm-btn secondary" id="gal_new_seed" data-action="gallery.newSeed"
                            title="A new seed, at random: the images in a new order">New seed</button>
                    <!-- Group by: a menu, filled by gallery.mjs -->
                    <span class="gen-view-switch gen-group-menu" title="Gather the images that share something">
                        Group by
                        <span class="gen-group-anchor">
                            <button type="button" id="gal_group_by" class="gen-group-button"
                                    aria-haspopup="true" aria-expanded="false">Nothing</button>
                            <div class="gen-group-list gen-menu-panel" hidden></div>
                        </span>
                    </span>
                    <span class="gen-toolbar-fill"></span>
                    <button type="button" class="mm-btn secondary" id="gal_refresh_btn"
                            data-action="gallery.refresh">Refresh</button>
                </div>

                <!-- Inside a group: Back, and which group -->
                <div id="gal_path"></div>
                <!-- The banner: what is stored, and the NSFW switch -->
                <div id="gal_banner"></div>
                </div>
                <div id="gal_grid" class="gen-grid"></div>
                <div id="gal_status" class="gen-status"></div>
                <!-- Scrolled near, it loads the next part -->
                <div id="gal_sentinel" class="gen-sentinel"></div>
            </div>
        """.replace("<!-- actions -->", header_actions("gallery")), elem_id="gallery_container")
        # Send's hidden buttons, if this is the first of our tabs built (#7).
        wire_send_buttons()

    return gallery_tab
