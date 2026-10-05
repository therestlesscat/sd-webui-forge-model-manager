"""
The Queue tab's markup (#156): where the generation queue is managed.

For now its frame alone. Building it also wires the Queue buttons beside
each Generate (scheduler/capture.py): a click must be wired inside a Blocks
the page renders, and this tab is ours, built after Forge has wired
Generate. Its page comes with the queue's endpoints.
"""
import gradio as gr

from ..scheduler.capture import wire_queue_buttons


def create_queue_ui():
    """Create the Queue tab UI, and wire the Queue buttons."""
    with gr.Blocks(analytics_enabled=False) as queue_tab:
        gr.HTML("""
            <div id="queue_app">
                <div class="queue-header">
                    <h2>Queue</h2>
                </div>
                <p class="queue-note">Tasks you queue with the Queue button beside Generate
                are kept. This page will list and run them.</p>
            </div>
        """, elem_id="queue_container")
        wire_queue_buttons()
    return queue_tab
