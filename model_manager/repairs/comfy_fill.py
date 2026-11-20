"""
Civitai images filled from their ComfyUI workflows (#232): the Fill notice.

A library from before 0.81.5 stored each Civitai image's derived rows - its
prompt rows, its settings row, its level - from Civitai's own fields alone,
so an image whose prompt or settings are only in the workflow Civitai keeps
beside them (`comfy`) is not found by that prompt, is hidden as having no
prompt, and is judged without it. Since 0.81.5 the rows are made from the
filled data once the switch is on (comfy_graph.judged), and a new library
is switched on from the start; this repair turns it on for a library from
before, when the person presses Fill, and rewrites the rows of the images
already stored.

Its check reads one value, scans nothing: work while `comfy_fill` is missing
or lower than this reader's version (comfy_graph.READER). A higher one was
written by a newer copy sharing the database: no work, and Fill refuses.

Fill is one of the long jobs (jobs.py). It waits for a restamp running in
this WebUI, turns the switch on, waits for the other WebUI sharing the
database to read it (comfy_graph.SWITCH_SECONDS), finds the records holding
a graph, rewrites their rows in batches (ImagesOps.fill_stored), clears the
safe covers now above PG-13, and stores this reader's version. A run cut
short stores none: the next press reads everything again, writing only what
still differs. The record is never written; nothing is deleted.
"""
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .. import comfy_graph
from ..console import say
from ..jobs import jobs

# Its area: on while either tab showing stored Civitai images is (tabs.SERVICES).
AREA = "comfy_fill"
KIND = "comfy_fill"
# Records rewritten per transaction: each holds the write lock while it runs.
BATCH = 200
# How often Fill looks whether a restamp running in this WebUI has ended.
RESTAMP_LOOK_SECONDS = 0.2


def stored_reader(db) -> Optional[int]:
    """The reader's version Fill last finished with here; None if never."""
    value = db.get_info(comfy_graph.FILLED_KEY)
    return int(value) if str(value or "").isdigit() else None


def newer_copy(db) -> bool:
    """Whether a newer copy sharing the database filled it with a reader this
    copy does not know: then there is nothing here to do, and Fill refuses."""
    filled = stored_reader(db)
    return filled is not None and filled > comfy_graph.READER


def needed(db) -> int:
    """1 while the library's images are not filled with this reader, else 0:
    one value read, so the page's many asks cost nothing."""
    filled = stored_reader(db)
    return 1 if filled is None or filled < comfy_graph.READER else 0


@dataclass
class FillProgress:
    """
    What the page is told: "running", in a step - "starting", "waiting" for a
    restamp running in this WebUI,
    "switching" while the other WebUI reads the switch, "finding" the records
    holding a graph, "filling" them with `done` of `total` - then "done" with
    what changed, or "failed" with why. Before any run, progress() says
    "idle".
    """
    state: str = "running"
    step: str = "starting"
    done: int = 0
    total: Optional[int] = None
    read: int = 0
    gained: int = 0
    prompts: int = 0
    levels: int = 0
    covers: int = 0
    started: float = field(default_factory=time.time)
    error: Optional[str] = None
    finished: Optional[float] = None

    def finish(self) -> None:
        self.state, self.error, self.finished = "done", None, time.time()

    def fail(self, message: str) -> None:
        """Finished by an error."""
        self.state, self.error, self.finished = "failed", message, time.time()

    def to_dict(self) -> Dict[str, Any]:
        found = {"state": self.state, "step": self.step, "done": self.done, "total": self.total,
                 "read": self.read, "gained": self.gained, "prompts": self.prompts,
                 "levels": self.levels, "covers": self.covers, "started": self.started}
        if self.state != "running":
            found.update(error=self.error, finished=self.finished)
        return found


class Fill(object):
    """One run of Fill. A second press while it runs joins it (jobs.start)."""

    def __init__(self):
        self.progress = FillProgress()

    def again(self) -> bool:
        """Never asked: a press while one runs joins it."""
        return False

    def cancel(self) -> None:
        """Nothing offers to: Close leaves it running, as a sync runs on."""


def run(fill: Fill, db) -> None:
    """Fill's steps, on the job's thread."""
    from .. import prompt_levels
    progress = fill.progress
    if newer_copy(db):
        raise RuntimeError("A newer copy of the extension sharing this database has filled it already. "
                           "Update this copy.")
    # A restamp started before the switch turns judges as it was; waited for,
    # it cannot write its levels over the ones Fill writes.
    while jobs.running(prompt_levels.KIND):
        progress.step = "waiting"
        time.sleep(RESTAMP_LOOK_SECONDS)
    progress.step = "switching"
    # This process's copy first: a restamp starting here from now on judges
    # filled, before the database's value is written, which can wait for the
    # write lock.
    comfy_graph.set_switch(True, stored_reader(db))
    db.set_info(comfy_graph.JUDGED_KEY, "1")
    # The other WebUI sharing the database reads the switch again within this
    # long: whatever either stores from here on is stored filled.
    time.sleep(comfy_graph.SWITCH_SECONDS)
    progress.step = "finding"
    ids = db.graph_record_ids()
    progress.total = len(ids)
    progress.step = "filling"
    for start in range(0, len(ids), BATCH):
        counts = db.fill_stored(ids[start:start + BATCH])
        progress.read += counts["read"]
        progress.gained += counts["gained"]
        progress.prompts += counts["prompts"]
        progress.levels += counts["levels"]
        progress.done = min(start + BATCH, len(ids))
    progress.covers = db.clear_unsafe_covers()
    # A newer copy that filled the database meanwhile keeps its version: this
    # copy's would offer the newer reader's Fill again there.
    if not newer_copy(db):
        db.set_info(comfy_graph.FILLED_KEY, str(comfy_graph.READER))
    comfy_graph.set_switch(True, max(comfy_graph.READER, stored_reader(db) or 0))
    say(f"Civitai images filled from their ComfyUI workflows: {progress.read} hold one, "
        f"{progress.gained} gained a field, {progress.prompts} a prompt; {progress.levels} judged at another level")
    progress.finish()


def progress() -> Dict[str, Any]:
    """Where the latest run is, for the page."""
    found = jobs.progress(KIND)
    return found.to_dict() if found else {"state": "idle"}


def start(db) -> Dict[str, Any]:
    """Start Fill, or join the run under way: its progress."""
    jobs.start(KIND, Fill, lambda fill: run(fill, db))
    return progress()


def state(db) -> Dict[str, Any]:
    """What the window opens on: whether there is work, whether a newer copy
    filled the database, and the latest run."""
    return {"needed": bool(needed(db)), "newer": newer_copy(db), "fill": progress()}


def register(app, common) -> None:
    """Its two routes, while either tab showing stored Civitai images is on:
    `common` is the API's (gate, failed), handed in - the repairs import
    nothing of the API."""
    from fastapi.responses import JSONResponse
    from ..db import get_models_db

    @app.get("/model-manager/repairs/comfy-fill")
    @common.gate(AREA)
    def get_comfy_fill():
        """Whether there is work, and the latest run's progress."""
        try:
            return JSONResponse({"success": True, **state(get_models_db())})
        except Exception as e:
            return common.failed(e, "Reading the Fill notice's state")

    @app.post("/model-manager/repairs/comfy-fill/start")
    @common.gate(AREA)
    def start_comfy_fill():
        """Fill pressed: started, or joined if it runs. Refused where a newer
        copy sharing the database filled it."""
        try:
            db = get_models_db()
            if newer_copy(db):
                return JSONResponse({"success": False, "newer": True, "error": "A newer copy of the extension "
                                     "sharing this database has filled it already. Update this copy."},
                                    status_code=409)
            # Filled already (a stale page, a second window): nothing to run.
            if not needed(db):
                return JSONResponse({"success": True, "fill": progress(), "needed": False})
            return JSONResponse({"success": True, "fill": start(db)})
        except Exception as e:
            return common.failed(e, "Starting Fill")
