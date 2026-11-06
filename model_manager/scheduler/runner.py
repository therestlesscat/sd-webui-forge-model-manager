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

A task of several checkpoints (#400) is a run per checkpoint row, in order,
each under an id of its own in the same pattern, so the hooks and the
recorder know every one as the task's. A seed of -1 is drawn once before the
first, so every run has the same. Each run takes its row's settings - its
usual settings, Hires fix following them, and for another family Hires fix's
checkpoint "Use same" and the refiner off (load.for_run). A checkpoint gone
from Forge fails its row and the next runs; Stop or Forge's own Interrupt
ends the task Stopped, the rest not run; the person's own Generate goes
first between runs, as before a task. The task ends Completed when every row
did, Failed when any failed, its error naming each.

The person's own generations go first (#170): Forge's lock already keeps a
task and the person's Generate apart, but their Generate would wait behind a
long task. So before each task the queue waits while a run that is not the
queue's holds Forge's lock or waits for it, and a moment after, as Generate
forever presses Generate again half a second after each run. A task already
running finishes first.

Run next (#169) puts pending tasks before every other, in the order asked:
the running queue takes them after its task; a paused one runs them and
stays paused; with none running, a queue starts for them alone, and stops
after them - unless Start is pressed meanwhile. Pause holds those asked
before it too. Their order is not stored: the database runs tasks in the
order queued, and a column for it would be a migration that both WebUIs
sharing a database must take.

The queue's state lives in memory, Run next's order with it: a restart leaves
it stopped, and the tasks it left running are marked stopped at startup
(recover, #155).
"""
import copy
import html
import json
import os
import random
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .. import forge_host
from ..console import say, say_failure
from ..db import get_models_db
from ..install import INSTALL_KEY
from ..jobs import jobs
from . import capture, load, queue_enabled, replay

KIND = "queue"
# How long after the person's own run the queue waits before its next task:
# Generate forever presses Generate again half a second after each run (#170).
HOLD_GRACE = 2.0
_JOB = re.compile(r"^task\(mmq-(\d+)-\d+\)$")
_ERROR = re.compile(r"<div class='error'>(.*?)</div>", re.S)

# The running queue, or the last one: its progress is what the page polls.
_queue: Optional["Queue"] = None

# Run next's tasks, in the order asked (#169), and those asked since the last
# Pause - which run while the queue is paused. A queue deciding it is done
# looks at them under the same lock as Run next adds to them.
_first: List[int] = []
_go: Set[int] = set()
_first_lock = threading.Lock()


class Progress(object):
    """The queue's state, and the task it is on."""

    def __init__(self):
        self.state = "running"          # running, pausing, paused, stopping, stopped
        self.task_id: Optional[int] = None
        self.job: Optional[str] = None  # Forge's id for the run: its progress is asked by it
        self.run = 0                    # which of the task's runs, from 1, of `runs` (#400)
        self.runs = 0
        self.completed = 0
        self.failed = 0
        self.stopped = 0
        self.notes: List[str] = []      # the running task's inputs that took their default
        self.error: Optional[str] = None
        self.holding = False            # waiting for the person's own generation (#170)

    def fail(self, message: str) -> None:
        self.error = message
        self.state = "stopped"

    def to_dict(self) -> Dict[str, Any]:
        return dict(vars(self))


class Queue(object):
    """A run of the queue: jobs.py's service for it."""

    def __init__(self, only: bool = False, alone: Optional[List[int]] = None):
        self.progress = Progress()
        self.run_now: Optional[Dict[str, Any]] = None
        # Started by Run next: only its tasks, then stop - until Start.
        self.only = only
        # Started by Generate for N checkpoints (#400): only the tasks Run next
        # asks for from its start - its own, and any asked while it runs - not
        # those an earlier Run next left listed first, in a queue stopped
        # before them. None: every task Run next lists.
        self.alone: Optional[Set[int]] = set(alone) if alone is not None else None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._paused = False
        self._ending = False
        self._person_seen = 0.0

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
        """
        Let the running task finish, then start no other until resumed (#153)
        - nor one Run next asked for before.
        """
        with _first_lock:
            _go.clear()
        self._paused = True
        self.progress.state = "pausing" if self.run_now else "paused"

    def resume(self) -> None:
        self._paused = False
        self._wake.set()
        if self.progress.state in ("pausing", "paused"):
            self.progress.state = "running"

    def again(self) -> bool:
        """
        Run next, while this queue runs (jobs.start's `again`): True when it
        will take the tasks asked for - woken, if it is paused - and False
        when it has just decided it is done, or Stop ended it while it was
        paused; jobs.py then starts another.
        """
        with _first_lock:
            if self._ending or self._stop.is_set():
                return False
        self._wake.set()
        return True

    def run(self) -> None:
        db = get_models_db()
        while not self._stop.is_set():
            if not self._paused and self._hold():
                continue
            task = self._next(db)
            if task is not None:
                self._run_task(db, task)
            elif self._paused:
                self.progress.state = "paused"
                self._wake.wait(0.5)
                self._wake.clear()
            elif self._end():
                break
        self.progress.holding = False
        self.progress.state = "stopped"

    def _hold(self) -> bool:
        """
        Whether to wait before the next task: a run not the queue's holds
        Forge's lock or waits for it, or did within HOLD_GRACE (#170).
        """
        if person_busy():
            self._person_seen = time.time()
        self.progress.holding = time.time() - self._person_seen < HOLD_GRACE
        if self.progress.holding:
            self._wake.wait(0.5)
            self._wake.clear()
        return self.progress.holding

    def _next(self, db) -> Optional[Dict[str, Any]]:
        """
        The task to run now: Run next's first, a paused queue only those asked
        since the Pause; then, unless paused or started for Run next alone,
        the oldest pending one.
        """
        with _first_lock:
            for task_id in list(_first):
                task = db.get_task(task_id)
                if task is None or task["status"] != "pending" or task.get("install") != INSTALL_KEY:
                    _first.remove(task_id)
                    _go.discard(task_id)
                elif (not self._paused or task_id in _go) and (self.alone is None or task_id in self.alone):
                    return task
        if self._paused or self.only:
            return None
        return db.next_pending_task(INSTALL_KEY)

    def _end(self) -> bool:
        """Whether the queue is done: not if Run next asked for a task meanwhile that it takes."""
        with _first_lock:
            self._ending = not [t for t in _first if self.alone is None or t in self.alone]
            return self._ending

    def _run_task(self, db, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        if not db.start_task(task_id):
            return
        rows = task.get("checkpoints") or [{}]
        # Its first run's id is set before the run is published: the hook and
        # Stop match Forge's current id against it, and none would match
        # Forge's idle None (#400).
        run = {"task": task, "row": rows[0], "job": run_id(task_id, 0, len(rows)), "stop": False,
               "interrupted": False}
        self.run_now = run
        if self._paused:
            # A task Run next asked for while paused: the queue pauses again after it.
            self.progress.state = "pausing"
        self.progress.task_id, self.progress.notes = task_id, []
        self.progress.run, self.progress.runs = 0, len(rows)
        say(f"Queue: task {task_id} ({task['mode']}) starting" + (f", {len(rows)} checkpoints" if len(rows) > 1 else ""))
        ended: List[Tuple[Dict[str, Any], str, Optional[str], Optional[int]]] = []
        try:
            inputs = fixed_seeds(task["mode"], task["inputs"]) if len(rows) > 1 else task["inputs"]
            for place, row in enumerate(rows):
                if place:
                    # The person's own Generate goes first between runs too (#170).
                    while not run["stop"] and self._hold():
                        pass
                if run["stop"]:
                    break
                if place:
                    run["row"], run["job"] = row, run_id(task_id, place, len(rows))
                self.progress.job, self.progress.run = run["job"], place + 1
                try:
                    status, error, seed = self._generate(task, row, inputs, run)
                except replay.TaskError as e:
                    status, error, seed = "failed", str(e), None
                except Exception as e:
                    say_failure(f"Queue: task {task_id} failed: {type(e).__name__}: {e}")
                    status, error, seed = "failed", f"{type(e).__name__}: {e}", None
                try:
                    db.finish_checkpoint(task_id, row.get("place", place), status, error)
                except Exception as e:
                    # The row's status is the task's record of it; the task still ends.
                    say_failure(f"Queue: task {task_id}: could not record run {place + 1}: {e}")
                ended.append((row, status, error, seed))
                if status == "stopped":
                    break
        except Exception as e:
            say_failure(f"Queue: task {task_id} failed: {type(e).__name__}: {e}")
            ended.append(({}, "failed", f"{type(e).__name__}: {e}", None))
        finally:
            self.run_now = None
        # Stopped between two runs - while one waits for the person's Generate -
        # the rest never ran: the task is Stopped, not Completed.
        if run["stop"] and len(ended) < len(rows) and not any(s == "stopped" for _, s, _, _ in ended):
            ended.append(({}, "stopped", None, None))
        status, error, seed = task_end(ended, len(rows))
        db.finish_task(task_id, status, error, seed)
        setattr(self.progress, status, getattr(self.progress, status) + 1)
        self.progress.task_id = self.progress.job = None
        self.progress.run = self.progress.runs = 0
        self.progress.notes = []
        if self.progress.state == "pausing":
            self.progress.state = "paused"
        say(f"Queue: task {task_id} {status}" + (f": {error}" if error else ""))

    def _generate(self, task: Dict[str, Any], row: Dict[str, Any], inputs: Dict[str, Any],
                  run: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[int]]:
        problem = files_problem(row)
        if problem:
            return "failed", problem, None
        own = capture.generate_click(task["mode"])
        if own is None:
            raise replay.TaskError(f"{task['mode']}'s Generate was not found")
        named = load.for_run(task["mode"], inputs, row.get("settings"))
        values, notes = replay.rebuild(task["mode"], list(own.inputs), named)
        self.progress.notes = notes
        for note in notes:
            say(f"Queue: task {task['id']}: {note}")
        if run["stop"]:
            return "stopped", None, None
        import gradio as gr
        outputs = own.fn(run["job"], gr.Request(username=task.get("username")), *values[1:])
        return read_result(own, outputs, run)


def files_problem(row: Dict[str, Any]) -> Optional[str]:
    """
    Why a task's run cannot run in this WebUI, if a file its checkpoint row
    names is not here: it fails, rather than run on whatever Forge has loaded
    (#154).
    """
    checkpoint = row.get("checkpoint")
    if checkpoint and not forge_host.checkpoint_listed(checkpoint):
        return f"The checkpoint is not in this WebUI: {checkpoint}"
    offered = {os.path.normcase(os.path.abspath(path)) for path in forge_host.installed_modules().values()}
    for path in row.get("modules") or []:
        if os.path.normcase(os.path.abspath(path)) not in offered:
            return f"A VAE or text encoder is not in this WebUI: {path}"
    return None


# The Seed script's controls, by the tab: the same ids in both WebUIs
# (processing_scripts/seed.py).
_SEED, _SUBSEED, _STRENGTH = "{}_seed", "{}_subseed", "{}_subseed_strength"


def _random_seed(value: Any) -> bool:
    """Whether Forge would draw a seed for this value: -1, empty, or text that is no number."""
    if value in (None, ""):
        return True
    try:
        return int(value) == -1
    except (TypeError, ValueError):
        return True


def fixed_seeds(tab: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    A task's inputs with a seed of -1 drawn once, as Forge draws one
    (processing.get_fixed_seed), so each run of a task of several
    checkpoints has the same (#400); a variation seed too, when its strength
    is above 0. Written in the control's own type: Neo's Seed can be a
    textbox, which sends text. The task's own inputs are left as queued, so
    a Retry with a random seed draws again.
    """
    inputs = copy.deepcopy(inputs)
    entries = {entry.get("id"): entry for controls in (inputs.get("scripts") or {}).values() for entry in controls}
    strength = (entries.get(_STRENGTH.format(tab)) or {}).get("value") or 0
    names = [_SEED.format(tab)] + ([_SUBSEED.format(tab)] if _positive(strength) else [])
    for name in names:
        entry = entries.get(name)
        if entry is not None and _random_seed(entry.get("value")):
            drawn = int(random.randrange(4294967294))
            entry["value"] = str(drawn) if isinstance(entry.get("value"), str) else drawn
    return inputs


def _positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def run_id(task_id: int, place: int, runs: int) -> str:
    """
    Forge's id for a run of a task: the queue's pattern, its time, and for a
    task of several checkpoints the run's place too - two runs can start in
    one millisecond (#400). A task of one checkpoint's as ever.
    """
    stamp = f"{int(time.time() * 1000)}{place if runs > 1 else ''}"
    return f"task(mmq-{task_id}-{stamp})"


def task_end(ended: List[Tuple[Dict[str, Any], str, Optional[str], Optional[int]]],
             rows: int) -> Tuple[str, Optional[str], Optional[int]]:
    """
    How a task ended, from each run's (row, status, error, seed): Stopped
    when a run was, Failed when any failed - a task of one checkpoint with
    Forge's text as ever, one of several naming each - else Completed. Its
    first seed is the first run's that has one.
    """
    seed = next((s for _, _, _, s in ended if s is not None), None)
    if any(status == "stopped" for _, status, _, _ in ended):
        return "stopped", None, seed
    failed = [(row, error) for row, status, error, _ in ended if status == "failed"]
    if not failed:
        return ("completed" if ended else "stopped"), None, seed
    if rows == 1:
        return "failed", failed[0][1], seed
    named = "; ".join(_named_error(row, error) for row, error in failed)
    return "failed", f"{len(failed)} of {rows} failed: {named}", seed


def _named_error(row: Dict[str, Any], error: Optional[str]) -> str:
    """A failed run's error, its checkpoint named first unless the error names it already."""
    name = row.get("checkpoint") or "no checkpoint"
    return error if error and name in error else f"{name}: {error}"


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
    """Before each process of a queue's run: its checkpoint row's files, or its Stop."""
    run = _run_of_now()
    if run is None:
        return
    if run["stop"]:
        forge_host.stop_this_run()
        return
    row = run["row"]
    overrides = getattr(p, "override_settings", None)
    if overrides is None:
        overrides = p.override_settings = {}
    if row.get("checkpoint"):
        overrides["sd_model_checkpoint"] = row["checkpoint"]
    overrides["forge_additional_modules"] = list(row.get("modules") or [])


def on_postprocess(p, processed) -> None:
    """After each process of a queue's run: whether it was interrupted."""
    run = _run_of_now()
    if run is not None and forge_host.was_interrupted():
        run["interrupted"] = True


def person_busy() -> bool:
    """Whether Forge runs, or holds for its lock, a generation not the queue's (#170)."""
    return any(queued_task(job) is None for job in forge_host.forge_jobs())


def queued_task(job: Optional[str] = None) -> Optional[int]:
    """The queue's task a generation is a run of: by Forge's id for it, the
    one running now by default. None for the person's own Generate."""
    found = _JOB.match((job if job is not None else forge_host.current_job()) or "")
    return int(found.group(1)) if found else None


# -------------------------------------------------------------- the queue

def missing_extensions() -> List[Dict[str, Any]]:
    """Each pending task that uses a script this WebUI no longer has, and which."""
    tasks, _total = get_models_db().list_tasks(INSTALL_KEY, "active")
    return _missing([task for task in tasks if task["status"] == "pending"])


def _make(only: bool = False, alone: Optional[List[int]] = None) -> Queue:
    global _queue
    _queue = Queue(only, alone)
    return _queue


def _missing(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each of these tasks that uses a script this WebUI no longer has, and which."""
    found = []
    for task in tasks:
        missing = replay.missing_scripts(task["mode"], task["inputs"])
        if missing:
            found.append({"task": task["id"], "prompt": (task["inputs"].get("fixed") or {}).get("prompt"),
                          "missing": missing})
    return found


def start(force: bool = False) -> Dict[str, Any]:
    """
    Start the queue. Unless forced, not while a pending task uses a script
    that is gone: those come back, for the page to ask whether to run them
    without it. Extensions change only with a restart, so one check covers
    the whole run.
    """
    if not queue_enabled():
        return {"started": False, "missing": [], "off": True}
    if not force:
        missing = missing_extensions()
        if missing:
            return {"started": False, "missing": missing}
    queue = _running()
    if queue is not None and queue.only:
        # Started for Run next alone: it goes on with the rest - unless it
        # has just decided it is done, and a new queue starts.
        with _first_lock:
            if not queue._ending:
                queue.only = False
                queue.alone = None
                return {"started": True, "missing": []}
        return {"started": jobs.start(KIND, _make, lambda queue: queue.run(), again=True), "missing": []}
    return {"started": jobs.start(KIND, _make, lambda queue: queue.run()), "missing": []}


def run_next(task_ids: List[int], force: bool = False, alone: bool = False) -> Dict[str, Any]:
    """
    Run these pending tasks before any other, in the order they were queued
    (#169): after the running task, or now - a stopped queue starts for them
    alone, a paused one runs them and stays paused. Not while the queue is
    stopping: it would end before them. Unless forced, not when one uses a
    script that is gone, as Start. With `alone` (Generate for N checkpoints,
    #400), a stopped queue starts for these alone, not for tasks an earlier
    Run next left listed first; those stay listed, for Run next or Start.

    Returns:
        first: the tasks put first; after: the task they wait for, if one is
        running; skipped: each not, and why; missing: as Start's; `off` or
        `stopping` when nothing could be done.
    """
    answer: Dict[str, Any] = {"first": [], "after": None, "skipped": [], "missing": []}
    if not queue_enabled():
        return {**answer, "off": True}
    db = get_models_db()
    pending = []
    for task_id in task_ids:
        task = db.get_task(task_id)
        if task is None or task.get("install") != INSTALL_KEY:
            answer["skipped"].append({"id": task_id, "why": "not found"})
        elif task["status"] != "pending":
            answer["skipped"].append({"id": task_id, "why": f"already {task['status']}"})
        else:
            pending.append(task)
    pending.sort(key=lambda task: task["id"])
    if not force:
        answer["missing"] = _missing(pending)
        if answer["missing"]:
            return answer
    queue = _running()
    if queue is not None and queue.progress.state == "stopping":
        return {**answer, "stopping": True}
    if not pending:
        return answer
    ids = [task["id"] for task in pending]
    with _first_lock:
        _first.extend(task_id for task_id in ids if task_id not in _first)
        _go.update(ids)
        # A queue started for its own tasks takes these too, asked while it runs.
        if queue is not None and queue.alone is not None:
            queue.alone.update(ids)
    running = queue.run_now if queue is not None else None
    jobs.start(KIND, lambda: _make(only=True, alone=ids if alone else None), lambda queue: queue.run(), again=True)
    return {**answer, "first": ids, "after": running["task"]["id"] if running else None}


def first() -> List[int]:
    """Run next's tasks, in the order they will run: Active lists them so."""
    with _first_lock:
        return list(_first)


def unmoved() -> Set[int]:
    """
    The tasks Run next would not move: those a running queue takes before
    every other already - Run next's, and else the oldest waiting. Paused, a
    queue runs only those asked for since; stopped, Run next runs any task.
    The page disables Run next on them.
    """
    queue = _running()
    if queue is None or queue.progress.state == "stopping":
        return set()
    with _first_lock:
        found = {task_id for task_id in _first if (not queue._paused or task_id in _go)
                 and (queue.alone is None or task_id in queue.alone)}
    if not queue._paused and not queue.only:
        oldest = get_models_db().next_pending_task(INSTALL_KEY)
        if oldest is not None:
            found.add(oldest["id"])
    return found


def _running() -> Optional[Queue]:
    return _queue if jobs.running(KIND) else None


def working() -> bool:
    """
    Whether the queue runs a task or will take the next: a paused one, waiting
    for Resume, is not. A compact of the database waits for one that is (#287).
    """
    queue = _running()
    return queue is not None and queue.progress.state != "paused"


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
    starts the page again in the same process, with the queue still on. Nor
    while the queue is off: the first start with it on does it.
    """
    if not queue_enabled() or jobs.running(KIND):
        return 0
    count = get_models_db().stop_running_tasks(INSTALL_KEY)
    if count:
        say(f"Queue: {count} task(s) left running by a restart are now stopped")
    return count
