"""
The Generations tab's markup: every image you have generated, newest first.

Static HTML only, as the other tabs: javascript/tabs/generations.mjs fills the
grid from the API. A tile per generation - its first images, and how many it
has - or per group of images, "Group by" says what; a click on one opens it
in a grid of its own, with Back. A search narrows them to the images whose
prompts hold its words, or that a task of the Queue made.
"""
import gradio as gr

from ..scheduler.load import wire_send_buttons
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
                    <button type="button" class="mm-btn secondary" id="gen_sync_btn"
                            data-action="generations.syncImages"
                            title="Add the images already in Forge's result folders, and folders you add, to this tab. The files stay where they are.">Sync images</button>
                    <button type="button" class="mm-btn secondary" id="gen_refresh_btn"
                            data-action="generations.refresh">Refresh</button>
                </div>

                <!-- Sync images, while it runs and once it has ended: filled by generations.mjs -->
                <div id="gen_sync_panel" class="model-manager-sync-progress gen-sync-panel" hidden>
                    <div class="sync-progress-bar"><div class="sync-progress-fill" id="gen_sync_fill"></div></div>
                    <div class="gen-sync-line">
                        <span class="sync-progress-text" id="gen_sync_text"></span>
                        <button type="button" class="mm-btn mm-btn-small secondary" id="gen_sync_cancel"
                                data-action="generations.cancelSync">Cancel</button>
                        <button type="button" class="mm-btn mm-btn-small secondary" id="gen_sync_close"
                                data-action="generations.closeSyncPanel" hidden>Close</button>
                    </div>
                    <details id="gen_sync_errors" class="mm-misplaced" hidden>
                        <summary id="gen_sync_errors_summary"></summary>
                        <ul id="gen_sync_errors_list"></ul>
                    </details>
                </div>

                <!-- Inside a group or a batch: Back, and where it is -->
                <div id="gen_path"></div>
                <!-- The banner: what is stored, and the NSFW switch -->
                <div id="gen_banner"></div>
                </div>
                <div id="gen_grid" class="gen-grid"></div>
                <!-- Sync images' dialog: the folders, what is new in each, and how -->
                <div id="gen_sync_dialog" class="mm-dialog-backdrop" style="display: none;"
                     data-action="generations.syncDialogBackdrop">
                    <div class="mm-dialog" role="dialog" aria-modal="true" aria-labelledby="gen_sync_dialog_title">
                        <h3 id="gen_sync_dialog_title">Sync images</h3>
                        <div class="mm-dialog-note">Adds the images already in these folders to this tab, as
                            generations. The files stay where they are. Images already here are left as they are.</div>
                        <div class="mm-dialog-section">
                            <div class="mm-dialog-heading">Folders</div>
                            <div id="gen_sync_folders"></div>
                            <div class="gen-sync-add">
                                <input type="text" id="gen_sync_add_path" class="mm-settings-input"
                                       placeholder="Another folder: its full path" autocomplete="off">
                                <button type="button" class="mm-btn mm-btn-small secondary" id="gen_sync_add"
                                        data-action="generations.addSyncFolder" disabled
                                        title="Type a folder's full path first">Add</button>
                            </div>
                            <div class="mm-dialog-note" id="gen_sync_add_note" hidden></div>
                        </div>
                        <div class="mm-dialog-section">
                            <div class="mm-dialog-heading">Images without infotext</div>
                            <label class="mm-dialog-option" title="Images in one folder whose file names say the same settings, saved close together, become one batch, as one press of Generate made them.">
                                <input type="checkbox" id="gen_sync_group">
                                <span>Group images with similar file names into one batch</span>
                            </label>
                            <label class="mm-dialog-option" title="Given to the images without infotext this sync brings, and kept with them. A rating you give an image wins.">
                                <span>Default NSFW level for images without infotext</span>
                                <select id="gen_sync_level" class="mm-dialog-select"></select>
                            </label>
                        </div>
                        <div class="mm-dialog-estimate" id="gen_sync_estimate"></div>
                        <div class="mm-dialog-actions">
                            <button type="button" class="mm-btn secondary" data-action="generations.closeSyncDialog">Cancel</button>
                            <button type="button" class="mm-btn primary" id="gen_sync_start"
                                    data-action="generations.startSync">Start</button>
                        </div>
                    </div>
                </div>
                <div id="gen_status" class="gen-status"></div>
                <!-- Scrolled near, it loads the next part -->
                <div id="gen_sentinel" class="gen-sentinel"></div>
            </div>
        """.replace("<!-- actions -->", header_actions("generations")), elem_id="generations_container")
        # Send's hidden buttons, if this is the first of our tabs built (#7).
        wire_send_buttons()

    return generations_tab
