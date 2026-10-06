"""
The generation queue (#151-#164, #169, #177, #178): its state, Start, Stop,
Pause and Resume; the Active and History lists and a task's details; Run
next, Cancel, Retry, Delete, Clear history, and the tasks it hid shown and
unhidden. The queue runs in scheduler/runner.py; scheduler/tasks.py says what
a task is, and what Retry and Delete make of one.

Only this install's tasks are listed or acted on: another WebUI sharing the
database queued its own, and runs them itself.

No image is sent with a task: a row says how many its run made, and the
Generations tab shows them, searched by the task (task:<id>). Deleted with
a task's data, they go as the Generations tab deletes them.
"""
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

from ..console import say
from ..db import get_models_db
from ..forge_host import checkpoint_file
from ..install import INSTALL_KEY
from ..scheduler import runner, tasks
from ..scheduler.values import files
from .common import failed
from .generations import _delete_files, plan_for

# Tasks a list shows at a time.
PAGE_SIZE = 20


def _ids(text: str) -> List[int]:
    return list(dict.fromkeys(int(v) for v in (text or "").split(",") if v.strip().isdigit()))


def _ours(db, task_id: int) -> Optional[Dict[str, Any]]:
    """A task this install queued, or None."""
    task = db.get_task(task_id)
    return task if task and task.get("install") == INSTALL_KEY else None


def _rows(db, found: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Each task's row, with how many images its run made, and whether Run next
    would move it (`ahead`: it runs before the other waiting tasks already).
    """
    made = db.task_images([t["id"] for t in found])
    ahead = runner.unmoved()
    return [{**tasks.summary(task), "image_count": len(made.get(task["id"], [])),
             "ahead": task["id"] in ahead} for task in found]


def task_page(db, which: str, page: int = 1, hidden: bool = False) -> Dict[str, Any]:
    """
    A page of the Active or History list (#157): Active in the order the
    tasks will run - Run next's first (#169) - History newest first, with
    `hidden` the tasks Clear history hid among them (#178).
    """
    page = max(1, int(page))
    found, total = db.list_tasks(INSTALL_KEY, which, (page - 1) * PAGE_SIZE, PAGE_SIZE, runner.first(), hidden)
    return {"which": which, "tasks": _rows(db, found),
            "total": total, "page": page, "pages": max(1, -(-total // PAGE_SIZE)),
            "page_size": PAGE_SIZE}


def cancel(db, task_ids: List[int]) -> Dict[str, Any]:
    """
    Take each pending task out of the queue (#177): cancelled, it stays in
    History, where Retry queues it again. One the queue has started is
    skipped: Stop ends it.
    """
    cancelled, skipped = [], []
    for task_id in task_ids:
        task = _ours(db, task_id)
        if task is None:
            skipped.append({"id": task_id, "why": "not found"})
        elif db.cancel_task(INSTALL_KEY, task_id):
            cancelled.append(task_id)
        else:
            now = _ours(db, task_id) or task
            skipped.append({"id": task_id, "why": f"already {now['status']}"})
    return {"cancelled": cancelled, "skipped": skipped}


def retry(db, task_ids: List[int], seed: str) -> Dict[str, Any]:
    """Queue a copy of each ended task, at the end of the queue (#161)."""
    queued, skipped = [], []
    for task_id in task_ids:
        task = _ours(db, task_id)
        if task is None:
            skipped.append({"id": task_id, "why": "not found"})
        elif task["status"] not in tasks.ENDED:
            skipped.append({"id": task_id, "why": f"still {task['status']}"})
        else:
            queued.append(db.add_task(tasks.retried(task, seed)))
    return {"queued": queued, "skipped": skipped}


def delete(db, task_ids: List[int], with_data: bool) -> Dict[str, Any]:
    """
    Delete each task, and with its data the generations it made - their
    rows and image files (#162). Either way its own input files go, but
    those a retry's copy still names. A running task is not deleted.
    """
    deleted, skipped, images, inputs = [], [], [], []
    for task_id in task_ids:
        task = _ours(db, task_id)
        if task is None:
            skipped.append({"id": task_id, "why": "not found"})
            continue
        gone, paths = db.delete_task(task_id, with_data)
        if gone is None:
            skipped.append({"id": task_id, "why": "running"})
            continue
        deleted.append(task_id)
        images += paths
        inputs += files(gone.get("inputs"))
    images_deleted, failed_files = _delete_files(list(dict.fromkeys(images))) if with_data else ([], [])
    in_use = set(db.task_files_in_use(inputs))
    inputs_deleted, failed_inputs = tasks.delete_inputs([p for p in dict.fromkeys(inputs) if p not in in_use])
    return {"deleted": deleted, "skipped": skipped, "deleted_files": len(images_deleted),
            "deleted_inputs": inputs_deleted, "failed": failed_files + failed_inputs}


def register(app: FastAPI):
    """Attach this module's endpoints to the app."""

    @app.get("/model-manager/queue/status")
    def get_status():
        """The queue's state, the task it is on, and how many tasks have each status."""
        try:
            return JSONResponse({"success": True, **runner.status()})
        except Exception as e:
            return failed(e, "Queue status error")

    @app.post("/model-manager/queue/start")
    def start(force: bool = False):
        """
        Start the queue. Unless forced, not while a pending task uses a
        script that is gone: those are answered, for the page to ask
        whether to run them without it (#151).
        """
        try:
            return JSONResponse({"success": True, **runner.start(force)})
        except Exception as e:
            return failed(e, "Queue start error")

    def _act(action: str):
        """`acted` is false with no queue running."""
        try:
            return JSONResponse({"success": True, "acted": getattr(runner, action)()})
        except Exception as e:
            return failed(e, f"Queue {action} error")

    @app.post("/model-manager/queue/stop")
    def stop():
        """End the running task and start no other (#152)."""
        return _act("stop")

    @app.post("/model-manager/queue/pause")
    def pause():
        """Let the running task finish, then start no other (#153)."""
        return _act("pause")

    @app.post("/model-manager/queue/resume")
    def resume():
        """Go on with the next pending task (#153)."""
        return _act("resume")

    @app.get("/model-manager/queue/tasks")
    def get_tasks(which: str = "active", page: int = 1, hidden: bool = False):
        """A page of the Active or History list. See task_page()."""
        if which not in ("active", "history"):
            return JSONResponse({"success": False, "error": f"No list {which}"}, status_code=404)
        try:
            return JSONResponse({"success": True, **task_page(get_models_db(), which, page, hidden)})
        except Exception as e:
            return failed(e, "Queue list error")

    @app.get("/model-manager/queue/tasks/{task_id}")
    def get_task(task_id: int):
        """A task's details (#159): its row, and everything it holds."""
        try:
            db = get_models_db()
            task = _ours(db, task_id)
            if task is None:
                return JSONResponse({"success": False, "error": "No such task"}, status_code=404)
            return JSONResponse({"success": True, "task": _rows(db, [task])[0],
                                 "inputs": tasks.details(task)})
        except Exception as e:
            return failed(e, "Queue task error")

    @app.get("/model-manager/queue/tasks/{task_id}/send-plan")
    def get_send_plan(task_id: int):
        """
        How to set Forge up before a task is loaded into its tab (#160): its
        checkpoint's UI preset, the checkpoint, and its VAE / text encoders,
        as a generation's Send does - plan_for(). A checkpoint this WebUI
        does not list is named in checkpoint_missing. A plain `def`: it may
        read the checkpoint's header.
        """
        try:
            db = get_models_db()
            task = _ours(db, task_id)
            if task is None:
                return JSONResponse({"success": False, "error": "No such task"}, status_code=404)
            path = checkpoint_file(task.get("checkpoint") or "")
            plan = plan_for(db, path or "", task.get("modules") or [])
            if task.get("checkpoint") and not path:
                plan["checkpoint_missing"] = task["checkpoint"]
            return JSONResponse({"success": True, "mode": task["mode"], **plan})
        except Exception as e:
            return failed(e, "Queue send plan error")

    @app.post("/model-manager/queue/run-next")
    def post_run_next(ids: str = Form(default=""), force: bool = Form(default=False)):
        """
        Run these pending tasks before any other (#169, #163): see
        runner.run_next(). Unless forced, tasks whose scripts are gone come
        back, as Start's do.
        """
        try:
            result = runner.run_next(_ids(ids), force)
            if result["first"]:
                say(f"Queue: run next {', '.join(f'#{i}' for i in result['first'])}")
            return JSONResponse({"success": True, **result})
        except Exception as e:
            return failed(e, "Queue run next error")

    @app.post("/model-manager/queue/cancel")
    def post_cancel(ids: str = Form(default="")):
        """
        Cancel these pending tasks (#177, #163).

        Returns:
            cancelled: the ids cancelled; skipped: each not, and why.
        """
        try:
            result = cancel(get_models_db(), _ids(ids))
            say(f"Queue: {len(result['cancelled'])} task(s) cancelled")
            return JSONResponse({"success": True, **result})
        except Exception as e:
            return failed(e, "Queue cancel error")

    @app.post("/model-manager/queue/retry")
    def post_retry(ids: str = Form(default=""), seed: str = Form(default="first")):
        """
        Retry these tasks (#161, #163): `seed` is "first", the first run's,
        or "random".

        Returns:
            queued: the copies' ids; skipped: each task not copied, and why.
        """
        if seed not in ("first", "random"):
            return JSONResponse({"success": False, "error": f"No seed choice {seed}"}, status_code=400)
        try:
            result = retry(get_models_db(), _ids(ids), seed)
            say(f"Queue: {len(result['queued'])} task(s) queued again")
            return JSONResponse({"success": True, **result})
        except Exception as e:
            return failed(e, "Queue retry error")

    @app.post("/model-manager/queue/delete")
    def post_delete(ids: str = Form(default=""), with_data: bool = Form(default=False)):
        """
        Delete these tasks (#162, #163), and with_data the generations they
        made, files included.

        Returns:
            deleted: the ids deleted; skipped: each not, and why;
            deleted_files: image files deleted; deleted_inputs: the tasks'
            own files deleted; failed: files that could not be, with why.
        """
        try:
            result = delete(get_models_db(), _ids(ids), with_data)
            say(f"Queue: deleted {len(result['deleted'])} task(s)"
                + (f", {result['deleted_files']} image file(s)" if with_data else ""))
            return JSONResponse({"success": True, **result})
        except Exception as e:
            return failed(e, "Queue delete error")

    @app.post("/model-manager/queue/unhide")
    def post_unhide(ids: str = Form(default="")):
        """
        Show these tasks in History again (#178, #163).

        Returns:
            unhidden: the ids unhidden; skipped: each not, and why.
        """
        try:
            db = get_models_db()
            unhidden, skipped = [], []
            for task_id in _ids(ids):
                if _ours(db, task_id) is None:
                    skipped.append({"id": task_id, "why": "not found"})
                elif db.unhide_task(INSTALL_KEY, task_id):
                    unhidden.append(task_id)
                else:
                    skipped.append({"id": task_id, "why": "not hidden"})
            say(f"Queue: {len(unhidden)} task(s) shown in History again")
            return JSONResponse({"success": True, "unhidden": unhidden, "skipped": skipped})
        except Exception as e:
            return failed(e, "Queue unhide error")

    @app.post("/model-manager/queue/history/clear")
    def clear_history():
        """Hide every task in History (#164); nothing is deleted. `hidden`: how many."""
        try:
            hidden = get_models_db().hide_task_history(INSTALL_KEY)
            say(f"Queue: {hidden} task(s) cleared from History")
            return JSONResponse({"success": True, "hidden": hidden})
        except Exception as e:
            return failed(e, "Queue clear error")
