"""
The long jobs - a sync, a restamp of stored image levels - that run on a
thread and are watched.

At most one job of each kind runs at a time. A kind is a name ("sync",
"restamp"); a metadata sync is a "sync", as it shares the sync's endpoints.
A new kind of job is a new name, not new state.

What a job reports is its service's own progress, and only that. A job that
raises marks that progress finished, with its error: it used to write the
error into a record of its own the progress endpoint never read, so the page
showed the job running for ever.
"""
import threading
from typing import Any, Callable, Dict, Optional
from .console import say_failure


class _Job(object):
    def __init__(self, service: Any, thread: threading.Thread):
        self.service = service
        self.thread = thread


class Jobs(object):
    """The running and last-run job of each kind."""

    def __init__(self):
        self._jobs: Dict[str, _Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, make: Callable[[], Any], run: Callable[[Any], Any],
              again: bool = False) -> bool:
        """
        Make a service and run `run(service)` on a thread, unless a job of
        this kind is running - then nothing is made, and it returns False.

        With `again`, a start while one runs is not lost: the running service
        is asked again(), which is True when it will run once more after, and
        False when it has just finished - then a new job is started, as if
        none were running. A restamp asked for during one has words the
        running pass did not see. Either way it returns True.

        The service has a `progress` with a `fail(message)`, and a `cancel()`.
        """
        with self._lock:
            if self._running(kind):
                if not again:
                    return False
                if self._jobs[kind].service.again():
                    return True
            service = make()
            thread = threading.Thread(target=self._run, args=(kind, service, run), daemon=True)
            self._jobs[kind] = _Job(service, thread)
        thread.start()
        return True

    @staticmethod
    def _run(kind: str, service: Any, run: Callable[[Any], Any]):
        try:
            run(service)
        except Exception as e:
            say_failure(f"{kind} failed: {e}")
            service.progress.fail(str(e))

    def _running(self, kind: str) -> bool:
        job = self._jobs.get(kind)
        return job is not None and job.thread.is_alive()

    def running(self, kind: str) -> bool:
        with self._lock:
            return self._running(kind)

    def progress(self, kind: str) -> Optional[Any]:
        """The progress of the running or last job of this kind; None if none ran."""
        with self._lock:
            job = self._jobs.get(kind)
        return job.service.progress if job else None

    def cancel(self, kind: str) -> bool:
        """Ask the job of this kind to stop. False if none was started."""
        with self._lock:
            job = self._jobs.get(kind)
        if job is None:
            return False
        job.service.cancel()
        return True

    def join(self, timeout: Optional[float] = None):
        """Wait for every running job to end - for tests."""
        with self._lock:
            threads = [job.thread for job in self._jobs.values()]
        for thread in threads:
            thread.join(timeout)

    def service(self, kind: str) -> Optional[Any]:
        """The service of the running or last job of this kind - for tests."""
        with self._lock:
            job = self._jobs.get(kind)
        return job.service if job else None

    def reset(self):
        """Forget every job - for tests."""
        with self._lock:
            self._jobs.clear()


#: The one registry of the process.
jobs = Jobs()
