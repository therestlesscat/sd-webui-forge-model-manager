"""
Internal module for the generation queue: tasks, and task_generations.

A task is one press of Queue (#150): every input Generate would have been
sent, by name, kept to run later. It is written once when queued; after that
only the queue's own record of it changes - its status, when it ran, its
first run's seed, its error - and the generations its run made are linked to
it. See migrations._migrate_to_v34.

A task's status:
  pending     queued, not yet run
  running     the queue is running it
  completed   it ran to the end
  stopped     Stop or Interrupt ended it, or a restart did (#152, #155)
  failed      Forge reported an error, or a file it names is missing
  cancelled   taken out of the queue before it ran (#177)

Active is pending and running, in run order; History the rest, newest first.
Every list is one install's: another WebUI sharing the database cannot run
its tasks.

Used by ModelsDatabase facade - do not import directly.
"""
import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..prompt_rules import trimmed_sql

ACTIVE = ("pending", "running")
HISTORY = ("completed", "stopped", "failed", "cancelled")

# Written when a task is queued; the rest is the queue's record of it.
_QUEUED_COLUMNS = ("install", "forge", "mode", "inputs", "checkpoint", "modules",
                   "username", "retry_of")
_JSON_COLUMNS = {"inputs", "modules"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _marks(values) -> str:
    return ", ".join("?" * len(values))


def _read(row) -> Dict[str, Any]:
    task = dict(row)
    for column in _JSON_COLUMNS & task.keys():
        if task[column] is not None:
            try:
                task[column] = json.loads(task[column])
            except (TypeError, ValueError):
                pass
    return task


def _add_links(cursor, tasks: List[Dict[str, Any]]) -> None:
    """Give each task the generations its run made, and the id of its copy."""
    if not tasks:
        return
    ids = [t["id"] for t in tasks]
    made: Dict[int, List[int]] = {}
    cursor.execute(f"SELECT task_id, generation_id FROM task_generations "
                   f"WHERE task_id IN ({_marks(ids)}) ORDER BY generation_id", ids)
    for task_id, generation_id in cursor.fetchall():
        made.setdefault(task_id, []).append(generation_id)
    copies: Dict[int, int] = {}
    cursor.execute(f"SELECT retry_of, MAX(id) FROM tasks WHERE retry_of IN ({_marks(ids)}) "
                   f"GROUP BY retry_of", ids)
    for original, copy in cursor.fetchall():
        copies[original] = copy
    for task in tasks:
        task["generations"] = made.get(task["id"], [])
        task["retried_as"] = copies.get(task["id"])


class TasksOps:
    """
    Operations for the tasks tables.

    Receives a cursor factory from the parent facade.
    """

    def __init__(self, cursor_factory: Callable):
        self._cursor = cursor_factory

    def add_task(self, task: Dict[str, Any]) -> int:
        """
        Queue a task. `task` holds its queued columns by name; `install`,
        `mode` and `inputs` are required. It starts pending.

        Returns:
            The task's id, which is also its place in the queue.
        """
        columns = [c for c in _QUEUED_COLUMNS if c in task]
        values = [json.dumps(task[c], ensure_ascii=False)
                  if c in _JSON_COLUMNS and task[c] is not None else task[c]
                  for c in columns]
        with self._cursor() as cursor:
            cursor.execute(
                f"INSERT INTO tasks ({', '.join(columns)}, status, created_at) "
                f"VALUES ({_marks(columns)}, 'pending', ?)", values + [_now()])
            return cursor.lastrowid

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """
        A task, with the generations its run made (`generations`, oldest
        first) and the id of its copy if it was retried (`retried_as`).
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                return None
            task = _read(row)
            _add_links(cursor, [task])
            return task

    def next_pending(self, install: str) -> Optional[Dict[str, Any]]:
        """This install's next task to run: its oldest pending one."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM tasks WHERE install = ? AND status = 'pending' "
                           "ORDER BY id LIMIT 1", (install,))
            row = cursor.fetchone()
            return _read(row) if row else None

    def start_task(self, task_id: int) -> bool:
        """Mark a pending task running. False if it was not pending."""
        with self._cursor() as cursor:
            cursor.execute("UPDATE tasks SET status = 'running', started_at = ? "
                           "WHERE id = ? AND status = 'pending'", (_now(), task_id))
            return cursor.rowcount == 1

    def finish_task(self, task_id: int, status: str, error: Optional[str] = None,
                    first_seed: Optional[int] = None) -> None:
        """
        Record how a task ended. Its first run's seed is kept once and never
        replaced: a retry is a new task, made from this one (#161).
        """
        if status not in HISTORY:
            raise ValueError(f"a task cannot finish as {status!r}")
        with self._cursor() as cursor:
            cursor.execute("UPDATE tasks SET status = ?, error = ?, finished_at = ?, "
                           "first_seed = COALESCE(first_seed, ?) WHERE id = ?",
                           (status, error, _now(), first_seed, task_id))

    def cancel(self, install: str, task_id: int) -> bool:
        """
        Take a pending task of this install's out of the queue: it ends as
        cancelled, and stays in History (#177). False if it was not pending -
        the queue may have started it meanwhile, and then Stop ends it.
        """
        with self._cursor() as cursor:
            cursor.execute("UPDATE tasks SET status = 'cancelled', finished_at = ? "
                           "WHERE id = ? AND install = ? AND status = 'pending'",
                           (_now(), task_id, install))
            return cursor.rowcount == 1

    def stop_running(self, install: str) -> int:
        """
        Mark this install's running tasks stopped. At startup nothing is
        running: a task still marked so was ended by a restart or a crash,
        and left running it could be neither deleted, retried nor run (#155).

        Returns:
            How many were stopped.
        """
        with self._cursor() as cursor:
            cursor.execute("UPDATE tasks SET status = 'stopped', finished_at = ? "
                           "WHERE install = ? AND status = 'running'", (_now(), install))
            return cursor.rowcount

    def link_generation(self, task_id: int, generation_id: int) -> None:
        """Note that a generation was made by this task's run."""
        with self._cursor() as cursor:
            cursor.execute("INSERT OR IGNORE INTO task_generations (task_id, generation_id) "
                           "VALUES (?, ?)", (task_id, generation_id))

    def list_tasks(self, install: str, which: str, offset: int = 0, limit: Optional[int] = None,
                   first: Optional[List[int]] = None) -> Tuple[List[Dict[str, Any]], int]:
        """
        A page of this install's Active or History list, and how many the
        whole list holds. Active is in run order: the running task, then
        `first` - Run next's, in the order asked (#169), which the database
        does not keep - then the rest as queued. History newest first, by
        when each ended and then by id - two can end in the same second.
        Hidden tasks are in neither (#164).
        """
        first = list(first or [])
        if which == "active":
            statuses = ACTIVE
            asked = " ".join(f"WHEN ? THEN {n}" for n in range(len(first)))
            order = "status = 'running' DESC" + (f", CASE id {asked} ELSE {len(first)} END" if first else "") + ", id"
        elif which == "history":
            statuses, order, first = HISTORY, "finished_at DESC, id DESC", []
        else:
            raise ValueError(f"no list {which!r}")
        where = f"install = ? AND hidden = 0 AND status IN ({_marks(statuses)})"
        args = [install, *statuses]
        with self._cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM tasks WHERE {where}", args)
            total = cursor.fetchone()[0]
            page = f" LIMIT {int(limit)} OFFSET {int(offset)}" if limit is not None else ""
            cursor.execute(f"SELECT * FROM tasks WHERE {where} ORDER BY {order}{page}", args + first)
            tasks = [_read(r) for r in cursor.fetchall()]
            _add_links(cursor, tasks)
            return tasks, total

    def count_tasks(self, install: str) -> Dict[str, int]:
        """How many of this install's tasks have each status, hidden ones left out."""
        counts = {status: 0 for status in ACTIVE + HISTORY}
        with self._cursor() as cursor:
            cursor.execute("SELECT status, COUNT(*) FROM tasks WHERE install = ? AND hidden = 0 "
                           "GROUP BY status", (install,))
            counts.update({status: count for status, count in cursor.fetchall()})
        return counts

    def hide_history(self, install: str) -> int:
        """
        Hide every task in this install's History. Nothing is deleted: the
        tasks, their generations and their files stay (#164).

        Returns:
            How many were hidden.
        """
        with self._cursor() as cursor:
            cursor.execute(f"UPDATE tasks SET hidden = 1 WHERE install = ? AND hidden = 0 "
                           f"AND status IN ({_marks(HISTORY)})", (install, *HISTORY))
            return cursor.rowcount

    def images_of(self, task_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        """
        The images each task's run made, by task: its generations oldest
        first, each image in its place - with what the Generations tab's
        switches read: its level, the user's rating when set, and how long
        its prompt is.
        """
        if not task_ids:
            return {}
        found: Dict[int, List[Dict[str, Any]]] = {}
        with self._cursor() as cursor:
            cursor.execute(f"""
                SELECT tg.task_id, gi.id, gi.generation_id, gi.position,
                       COALESCE(gi.user_nsfw_level, gi.prompt_nsfw_level) AS level,
                       LENGTH({trimmed_sql('gi.prompt')}) AS prompt_length
                FROM task_generations tg
                JOIN generation_images gi ON gi.generation_id = tg.generation_id
                WHERE tg.task_id IN ({_marks(task_ids)})
                ORDER BY tg.task_id, gi.generation_id, gi.position
            """, list(task_ids))
            for row in cursor.fetchall():
                image = dict(row)
                found.setdefault(image.pop("task_id"), []).append(image)
        return found

    def files_in_use(self, paths: List[str]) -> List[str]:
        """
        Which of these files a task still names in its inputs. A retry's copy
        names its original's files, which outlive the original (#161).
        """
        used = []
        with self._cursor() as cursor:
            for path in paths:
                # As add_task wrote it: a JSON string, quotes and all.
                cursor.execute("SELECT 1 FROM tasks WHERE instr(inputs, ?) > 0 LIMIT 1",
                               (json.dumps(path, ensure_ascii=False),))
                if cursor.fetchone():
                    used.append(path)
        return used

    def generations_of(self, cursor, task_id: int) -> List[int]:
        """The generations a task's run made, oldest first, inside a caller's transaction."""
        cursor.execute("SELECT generation_id FROM task_generations WHERE task_id = ? "
                       "ORDER BY generation_id", (task_id,))
        return [r[0] for r in cursor.fetchall()]

    def remove(self, cursor, task_id: int) -> Optional[Dict[str, Any]]:
        """
        Delete a task and its links, inside a caller's transaction. A running
        task is not deleted: the queue is running it (#162).

        Returns:
            The task as it was, or None if there was none, or it was running.
        """
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if not row or row["status"] == "running":
            return None
        cursor.execute("DELETE FROM task_generations WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return _read(row)
