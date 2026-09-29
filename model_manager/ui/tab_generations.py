"""
The Generations tab's markup: every image you have generated, newest first.

Static HTML only, as the other tabs: javascript/generations.mjs fills the
grid from the API. A tile per generation - its first images, and how many it
has - which opens out into all of them.
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

                <div class="gen-toolbar">
                    <label class="gen-view-switch" title="Every tile the same size, strictly newest first: wide images are cropped to a single column rather than a later tile filling in beside them">
                        <input type="checkbox" id="gen_preserve_order" onchange="window.genSetPreserveOrder(this.checked)">
                        Preserve order
                    </label>
                    <span class="gen-toolbar-fill"></span>
                    <button type="button" class="mm-btn secondary" id="gen_refresh_btn"
                            onclick="window.genRefresh()">Refresh</button>
                </div>

                <!-- The banner: what is stored, and the NSFW switch -->
                <div id="gen_banner"></div>
                <div id="gen_grid" class="gen-grid"></div>
                <div id="gen_status" class="gen-status"></div>
                <!-- Scrolled near, it loads the next part -->
                <div id="gen_sentinel" class="gen-sentinel"></div>
            </div>
        """.replace("<!-- actions -->", header_actions()), elem_id="generations_container")

    return generations_tab
