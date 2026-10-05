"""
The queue's runner (#151-#155): this install's pending tasks, one at a time,
each through Generate's own function - a job of its own kind in jobs.py.

A task runs as Generate would run it. Generate's own click function
(wrap_gradio_gpu_call around txt2img or img2img) is called with the task's
inputs, rebuilt for the UI as it is now (replay.py), and an id of the
queue's own: task(mmq-<task>-<time>). Forge's lock then runs it and the
person's own Generate one at a time; its progress, selectable scripts (X/Y/Z
plot) and saving all follow.

That id is how the rest of a run knows it is the queue's: while the run
holds Forge's lock it is Forge's progress.current_task, in every hook. A
flag of our own would mislink - set before the call, it would be set while
the person's Generate, holding the lock, still runs. So:
  - the hooks (scripts/model_manager_queue.py) act only on our id: before
    each process the task's checkpoint and modules join the run's override
    settings, which Forge applies inside its lock and restores after (#154),
    and a Stop asked for while the task waited ends it at once (#152); after
    each, whether it was interrupted - Generate's wrapper clears it;
  - the recorder links each generation it writes to the task (#150).

A run ends as: Failed, with Forge's text, when Generate's last output is an
error block; Stopped, keeping what it made, when it was interrupted -
Forge's own Interrupt too, after which the queue goes on; else Completed,
with the first run's seed from its generation info (#161). Then the next,
until none is left, and the queue stops by itself.

The queue's state lives in memory: a restart leaves it stopped, and the
tasks it left running are marked stopped at startup (recover, #155).
"""
import html
import json
import os
import re
import threading
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from .. import forge_host
from ..console import say
from ..db import get_models_db
from ..install import INSTALL_KEY
from ..jobs import jobs
from . import capture, replay

KIND = "queue"
_JOB = re.compile(r"^task\(mmq-(\d+)-\d+\)$")
_ERROR = re.compile(r"<div class='error'>(.*?)</div>", re.S)

# The running queue, or the last one: its progress is what the page polls.
_queue: Optional["Queue"] = None


class Progress(object):
    """The queue's state, and the task it is on."""

    def __init__(self):
        self.state = "running"          # running, pausing, paused, stopping, stopped
        self.task_id: Optional[int] = None
        self.job: Optional[str] = None  # Forge's id for the run: its progress is asked by it
        self.completed = 0
        self.failed = 0
        self.stopped = 0
        self.notes: List[str] = []      # the running task's inputs that took their default
        self.error: Optional[str] = None

    def fail(self, message: str) -> None:
        self.error = message
        self.state = "stopped"

    def to_dict(self) -> Dict[str, Any]:
        return dict(vars(self))


class Queue(object):
    """A run of the queue: jobs.py's service for it."""

    def __init__(self):
        self.progress = Progress()
        self.run_now: Optional[Dict[str, Any]] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._paused = False

    def cancel(self) -> None:
        self.stop()

    def stop(self) -> None:
        """
        Start no other task, and end the running one. Interrupted only while
        it is the generation Forge runs: still waiting for Forge's lock, the
        person's own Generate holds it, and an Interrupt would stop that.
        The hook ends ours as it starts instead.
        """
        self._stop.set()
        self._wake.set()
        run = self.run_now
        if run is not None:
            run["stop"] = True
            self.progress.state = "stopping"
            if forge_host.current_job() == run["job"]:
                forge_host.interrupt()

    def pause(self) -> None:
        """Let the running task finish, then start no other until resumed (#153)."""
        self._paused = True
        self.progress.state = "pausing" if self.run_now else "paused"

    def resume(self) -> None:
        self._paused = False
        self._wake.set()
        if self.progress.state in ("pausing", "paused"):
            self.progress.state = "running"

    def run(self) -> None:
        db = get_models_db()
        while not self._stop.is_set():
            if self._paused:
                self.progress.state = "paused"
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            task = db.next_pending_task(INSTALL_KEY)
            if task is None:
                break
            self._run_task(db, task)
        self.progress.state = "stopped"

    def _run_task(self, db, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        if not db.start_task(task_id):
            return
        run = {"task": task, "job": f"task(mmq-{task_id}-{int(time.time() * 1000)})",
               "stop": False, "interrupted": False}
        self.run_now = run
        self.progress.task_id, self.progress.job, self.progress.notes = task_id, run["job"], []
        say(f"Queue: task {task_id} ({task['mode']}) starting")
        try:
            status, error, seed = self._generate(task, run)
        except replay.TaskError as e:
            status, error, seed = "failed", str(e), None
        except Exception as e:
            traceback.print_exc()
            status, error, seed = "failed", f"{type(e).__name__}: {e}", None
        finally:
            self.run_now = None
        db.finish_task(task_id, status, error, seed)
        setattr(self.progress, status, getattr(self.progress, status) + 1)
        self.progress.task_id = self.progress.job = None
        self.progress.notes = []
        if self.progress.state == "pausing":
            self.progress.state = "paused"
        say(f"Queue: task {task_id} {status}" + (f": {error}" if error else ""))

    def _generate(self, task: Dict[str, Any], run: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[int]]:
        problem = files_problem(task)
        if problem:
            return "failed", problem, None
        own = capture.generate_click(task["mode"])
        if own is None:
            raise replay.TaskError(f"{task['mode']}'s Generate was not found")
        values, notes = replay.rebuild(task["mode"], list(own.inputs), task["inputs"])
        self.progress.notes = notes
        for note in notes:
            say(f"Queue: task {task['id']}: {note}")
        if run["stop"]:
            return "stopped", None, None
        import gradio as gr
        outputs = own.fn(run["job"], gr.Request(username=task.get("username")), *values[1:])
        return read_result(own, outputs, run)


def files_problem(task: Dict[str, Any]) -> Optional[str]:
    """
    Why a task cannot run in this WebUI, if a file it names is not here: it
    fails, rather than run on whatever Forge has loaded (#154).
    """
    checkpoint = task.get("checkpoint")
    if checkpoint and not forge_host.checkpoint_listed(checkpoint):
        return f"The checkpoint is not in this WebUI: {checkpoint}"
    offered = {os.path.normcase(os.path.abspath(path)) for path in forge_host.installed_modules().values()}
    for path in task.get("modules") or []:
        if os.path.normcase(os.path.abspath(path)) not in offered:
            return f"A VAE or text encoder is not in this WebUI: {path}"
    return None


def read_result(own, outputs: Any, run: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[int]]:
    """How a run ended, from what Generate's function gave back: (status, error, first seed)."""
    outputs = list(outputs) if isinstance(outputs, (list, tuple)) else [outputs]
    for output in outputs:
        found = _ERROR.search(output) if isinstance(output, str) else None
        if found:
            return "failed", html.unescape(found.group(1)).strip() or forge_host.last_error(), None
    seed = None
    for component, output in zip(own.outputs or [], outputs):
        if str(getattr(component, "elem_id", "") or "").startswith("generation_info") and isinstance(output, str):
            try:
                seed = json.loads(output).get("seed")
            except (ValueError, AttributeError):
                seed = None
            seed = seed if isinstance(seed, int) and not isinstance(seed, bool) else None
    if run["stop"] or run["interrupted"]:
        return "stopped", None, seed
    return "completed", None, seed


# ------------------------------------------------------------------ hooks

def _run_of_now() -> Optional[Dict[str, Any]]:
    """The queue's run, if it is the generation Forge is running now."""
    queue = _queue
    run = queue.run_now if queue is not None else None
    if run is None or forge_host.current_job() != run["job"]:
        return None
    return run


def on_before_process(p) -> None:
    """Before each process of a queue's run: its task's files, or its Stop."""
    run = _run_of_now()
    if run is None:
        return
    if run["stop"]:
        forge_host.stop_this_run()
        return
    task = run["task"]
    overrides = getattr(p, "override_settings", None)
    if overrides is None:
        overrides = p.override_settings = {}
    if task.get("checkpoint"):
        overrides["sd_model_checkpoint"] = task["checkpoint"]
    overrides["forge_additional_modules"] = list(task.get("modules") or [])


def on_postprocess(p, processed) -> None:
    """After each process of a queue's run: whether it was interrupted."""
    run = _run_of_now()
    if run is not None and forge_host.was_interrupted():
        run["interrupted"] = True


def queued_task(job: Optional[str] = None) -> Optional[int]:
    """The queue's task a generation is a run of: by Forge's id for it, the
    one running now by default. None for the person's own Generate."""
    found = _JOB.match((job if job is not None else forge_host.current_job()) or "")
    return int(found.group(1)) if found else None


# -------------------------------------------------------------- the queue

def missing_extensions() -> List[Dict[str, Any]]:
    """Each pending task that uses a script this WebUI no longer has, and which."""
    found = []
    tasks, _total = get_models_db().list_tasks(INSTALL_KEY, "active")
    for task in tasks:
        if task["status"] != "pending":
            continue
        missing = replay.missing_scripts(task["mode"], task["inputs"])
        if missing:
            found.append({"task": task["id"], "prompt": (task["inputs"].get("fixed") or {}).get("prompt"),
                          "missing": missing})
    return found


def _make() -> Queue:
    global _queue
    _queue = Queue()
    return _queue


def start(force: bool = False) -> Dict[str, Any]:
    """
    Start the queue. Unless forced, not while a pending task uses a script
    that is gone: those come back, for the page to ask whether to run them
    without it. Extensions change only with a restart, so one check covers
    the whole run.
    """
    if not force:
        missing = missing_extensions()
        if missing:
            return {"started": False, "missing": missing}
    return {"started": jobs.start(KIND, _make, lambda queue: queue.run()), "missing": []}


def _running() -> Optional[Queue]:
    return _queue if jobs.running(KIND) else None


def stop() -> bool:
    queue = _running()
    if queue is not None:
        queue.stop()
    return queue is not None


def pause() -> bool:
    queue = _running()
    if queue is not None:
        queue.pause()
    return queue is not None


def resume() -> bool:
    queue = _running()
    if queue is not None:
        queue.resume()
    return queue is not None


def status() -> Dict[str, Any]:
    """The queue's state and progress, and how many tasks have each status."""
    return {"running": jobs.running(KIND),
            "progress": _queue.progress.to_dict() if _queue is not None else None,
            "counts": get_models_db().count_tasks(INSTALL_KEY)}


def recover() -> int:
    """
    At startup: this install's tasks left running by a restart or a crash
    become stopped (#155). Not while a queue runs: Settings -> Reload UI
    starts the page again in the same process, with the queue still on.
    """
    if jobs.running(KIND):
        return 0
    count = get_models_db().stop_running_tasks(INSTALL_KEY)
    if count:
        say(f"Queue: {count} task(s) left running by a restart are now stopped")
    return count
