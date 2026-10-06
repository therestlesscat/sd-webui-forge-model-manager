"""
The Queue tab's markup (#156): where the generation queue is managed.

Static HTML only, as the other tabs: javascript/tabs/queue.mjs fills it from the
queue's endpoints (api/scheduler.py). A status line with the queue's
controls, then the Active list, in the order the tasks will run, and History,
newest first.

Building it also wires the Queue buttons beside each Generate
(scheduler/capture.py), and the hidden buttons that load a task back into
its tab (scheduler/load.py): a click must be wired inside a Blocks the page
renders, and this tab is ours, built after Forge has wired Generate.
"""
import gradio as gr

from ..scheduler.capture import wire_queue_buttons
from ..scheduler.load import wire_load_buttons
from .header import header_actions


def create_queue_ui():
    """Create the Queue tab UI, and wire the Queue and Load buttons."""
    with gr.Blocks(analytics_enabled=False) as queue_tab:
        gr.HTML("""
            <div id="queue_app">
                <div class="queue-header">
                    <h2>Queue</h2>
                    <!-- actions -->
                </div>

                <!-- Notes to the user per release: filled by shared/notes.mjs -->
                <div id="queue_notes" class="mm-notes"></div>

                <!-- The queue's state, the task it is on, and its controls -->
                <div class="queue-bar">
                    <span id="queue_state" class="queue-state" data-state="stopped" title="What the queue is doing">Stopped</span>
                    <span id="queue_task" class="queue-now"></span>
                    <span id="queue_counts" class="queue-counts"></span>
                    <span class="queue-bar-fill"></span>
                    <button type="button" class="mm-btn primary" id="queue_start" data-action="queue.start"
                            title="Run the pending tasks, one at a time, in the order they were queued">Start</button>
                    <button type="button" class="mm-btn secondary" id="queue_pause" data-action="queue.pause"
                            title="Let the running task finish, then start no other" hidden>Pause</button>
                    <button type="button" class="mm-btn secondary" id="queue_resume" data-action="queue.resume"
                            title="Go on with the next pending task" hidden>Resume</button>
                    <button type="button" class="mm-btn danger" id="queue_stop" data-action="queue.stop"
                            title="End the running task, and start no other. It keeps the images it made"
                            disabled>Stop</button>
                    <button type="button" class="mm-btn secondary" data-action="queue.refresh"
                            title="Read both lists again">Refresh</button>
                </div>
                <!-- What the queue is saying: an error, inputs that ran at their defaults -->
                <div id="queue_message" class="queue-message" hidden></div>
                <!-- How the last Retry, Delete or Clear history went -->
                <div id="queue_report" class="queue-report" role="status" hidden></div>

                <!-- Each list: its count, Select, and the bar of what to do with the ticked -->
                <div class="queue-list-head">
                    <h3 class="queue-list-title">Active <span id="queue_active_count" class="queue-list-count"></span></h3>
                    <label class="queue-select-switch" title="Tick waiting tasks, then run them next, cancel or delete them at once. A running task cannot be ticked">
                        <input type="checkbox" id="queue_active_select" data-action="queue.selecting" data-list="active">
                        Select
                    </label>
                    <span id="queue_active_select_bar" class="mm-select-bar" hidden></span>
                </div>
                <div id="queue_active" class="queue-list"><div class="queue-empty">Loading…</div></div>

                <div class="queue-list-head">
                    <h3 class="queue-list-title">History <span id="queue_history_count" class="queue-list-count"></span></h3>
                    <label class="queue-select-switch" title="Tick ended tasks, then retry, unhide or delete them at once">
                        <input type="checkbox" id="queue_history_select" data-action="queue.selecting" data-list="history">
                        Select
                    </label>
                    <!-- The tasks Clear history hid, shown among the rest: their count is the queue's -->
                    <label class="queue-select-switch" title="Show the tasks Clear history hid, among the rest, to retry, unhide or delete them">
                        <input type="checkbox" id="queue_history_hidden" data-action="queue.showHidden" disabled>
                        <span id="queue_hidden_label">Show hidden</span>
                    </label>
                    <span id="queue_history_select_bar" class="mm-select-bar" hidden></span>
                    <span class="queue-bar-fill"></span>
                    <button type="button" class="mm-btn secondary mm-btn-small" id="queue_clear_history"
                            data-action="queue.clearHistory"
                            title="Hide every task in History. Nothing is deleted: the tasks, their images and their files stay">Clear history</button>
                </div>
                <div id="queue_history" class="queue-list"><div class="queue-empty">Loading…</div></div>
            </div>
        """.replace("<!-- actions -->", header_actions("queue")), elem_id="queue_container")
        wire_queue_buttons()
        wire_load_buttons()
    return queue_tab
