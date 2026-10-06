"""
Keeping stored image levels in step with the NSFW prompt words.

An image's level is stamped when it is stored (images_ops.store_images), and
every view filters on the stamp - in SQL, over the whole library, which is
why it is stamped rather than judged each time (2.7 s a query against 4 ms).
So when the words change - an update to the bundled list, or an edit in the
settings - the stamps are redone, once, from the payloads already stored:
about three seconds for 100,000 images, and nothing asked of Civitai.

The words' fingerprint is kept in the metadata table once a pass finishes.
A pass that is cut short is run again at the next start.

How far a pass has got is kept for the page, which shows it after a save
that changed how images are judged: progress(). A pass is one of the long
jobs (model_manager.jobs), as a sync is.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .jobs import jobs
from .nsfw import generated_level, prompt_words_fingerprint
from .console import say
from .tabs import on

FINGERPRINT_KEY = "nsfw_prompt_words"
KIND = "restamp"


@dataclass
class RestampProgress:
    """
    What the page is told: "running" - with judged and total once the
    images are read - then "done" with what changed, or "failed" with why.
    `changed` is None when the stored levels already matched and nothing was
    judged. Before any pass, progress() says "idle".
    """
    state: str = "running"
    judged: Optional[int] = None
    total: Optional[int] = None
    changed: Optional[int] = None
    started: float = field(default_factory=time.time)
    error: Optional[str] = None
    finished: Optional[float] = None

    def report(self, judged: int, total: int) -> None:
        self.judged, self.total = judged, total

    def restart(self) -> None:
        """Another pass: nothing judged of it yet."""
        self.judged = self.total = self.changed = None

    def finish(self) -> None:
        self.state, self.error, self.finished = "done", None, time.time()

    def fail(self, message: str) -> None:
        """Finished by an error."""
        self.state, self.error, self.finished = "failed", message, time.time()

    def to_dict(self) -> Dict[str, Any]:
        found = {"state": self.state, "judged": self.judged, "total": self.total,
                 "changed": self.changed, "started": self.started}
        if self.state != "running":
            found.update(error=self.error, finished=self.finished)
        return found


class Restamp(object):
    """
    A pass over every stored image, and one more after it if one is asked
    for meanwhile - with the words as they are then. Never two at once.
    """

    def __init__(self):
        self.progress = RestampProgress()
        self._lock = threading.Lock()
        self._again = False
        self._ended = False

    def again(self) -> bool:
        """
        Asked for while running: one more pass after this one - False once
        this has ended, and a new job is started instead. Said at once, so a
        page asking straight after the save that asked never sees the last
        pass's numbers.
        """
        with self._lock:
            if self._ended:
                return False
            self._again = True
            self.progress.restart()
            self.progress.started = time.time()
            return True

    def cancel(self) -> None:
        """Nothing offers to: a pass takes seconds."""

    def run(self) -> None:
        while True:
            error = None
            try:
                from .db import get_models_db
                bring_up_to_date(get_models_db(), self.progress)
            except Exception as e:
                error = str(e)
                say(f"Could not apply the NSFW prompt words: {e}")
            with self._lock:
                if not self._again:
                    self._ended = True
                    if error:
                        self.progress.fail(error)
                    else:
                        self.progress.finish()
                    return
                self._again = False
                self.progress.restart()


def progress() -> Dict[str, Any]:
    """Where the latest pass is, for the page."""
    found = jobs.progress(KIND)
    return found.to_dict() if found else {"state": "idle"}


def bring_up_to_date(db, progress: Optional[RestampProgress] = None) -> Optional[int]:
    """
    Restamp every stored image if the words changed since the last pass.

    Returns:
        How many images changed level, or None if nothing needed doing.
    """
    fingerprint = prompt_words_fingerprint()
    if db.get_info(FINGERPRINT_KEY) == fingerprint:
        return None
    changed, total, covers = db.restamp_image_levels(progress=progress.report if progress else None)
    # Your own generations are judged by their prompts alone, so a change to
    # the words moves them too.
    generated, generated_total = db.restamp_generation_levels(generated_level)
    if generated:
        say(f"NSFW prompt words: {generated} of {generated_total} "
              f"generated images judged again")
    if progress:
        progress.changed, progress.total = changed, total
    db.set_info(FINGERPRINT_KEY, fingerprint)
    say(f"NSFW prompt words: {changed} of {total} images judged again"
          + (f", {covers} safe covers cleared" if covers else ""))
    return changed


def start_in_background() -> None:
    """
    A pass, as one of the long jobs, so neither the WebUI's start nor a
    settings save waits for it. Asked again while one runs, it runs once more
    afterwards, with the words as they are then. None while every tab that
    shows stored images is off (tabs.py): the fingerprint stays, and the
    first start with one on runs the pass.
    """
    if not on("restamp"):
        return
    jobs.start(KIND, Restamp, lambda restamp: restamp.run(), again=True)
