"""
The generation queue (#17): set up a generation, press Queue, run it later.

  capture.py    the Queue button: what Generate would be sent, kept as a task
  values.py     a value as a task keeps it - images, arrays, objects - and back
  replay.py     a task's inputs back into what Generate takes now
  runner.py     the queue itself: this install's tasks, one at a time
  tasks.py      a task as the Queue tab shows it, and what Retry makes of one
  load.py       Load to UI: a task set back into its tab

Tasks are stored through the database facade (db/tasks_ops.py); the Queue
tab's endpoints are api/scheduler.py.

The whole of it is one switch, as "Your generations" is: off, no Queue
button is made and no Queue tab built at the next start, the page hides both
at once, and a running queue stops. The tasks are kept.
"""
from ..tabs import TABS, on

# The Queue tab's switch (tabs.py), registered in ui/settings.py; its default
# is forge_host.DEFAULTS'.
QUEUE_ENABLED = TABS["queue"]


def queue_enabled() -> bool:
    """Whether the queue is on: a setting that cannot be read is on, as by default."""
    return on("queue")
