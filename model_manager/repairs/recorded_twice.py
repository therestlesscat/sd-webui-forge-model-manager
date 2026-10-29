"""
Generations recorded twice (#241, #364): the early copies a press left before
0.70.5, listed for the person to review, and removed only those they confirm.

ADetailer calls every script's end hook on a copy of the run at each batch's
first image, and the recorder took that for the end of the press: from batch 2
on, it wrote the press so far, and at the real end the whole press again. The
recorder no longer does (generations._notes); what it wrote stays in every
library that ran ADetailer at a batch count above 1, until removed here.

An early copy: a recorded generation - not one Sync images added - when a
later recorded one has the same creation time, to the second, and holds every
one of its images by path. The recorder stamps the time when the press
starts, so only one press shares it; two presses holding one file through
Forge's Override never do. Of a chain, every one but the last is listed, and
the last - which holds every image - is the one kept.

Removing one deletes its rows, as a delete from the Generations tab does,
never its files: the generation kept names every one. What the person set on
it goes to the one kept first - an image's rating, the generation's, the
queued task it came from, a kept source picture.
"""
from typing import Any, Dict, Iterable, List, Optional

from ..forge_host import setting
from ..generations import GENERATIONS_HIDE_NSFW
from ..nsfw import SFW_MAX, level_name

AREA = "generations"

# Each early copy with the generation kept: the last recorded one of its press
# holding all its images. Indexed on created_at and on each image's path:
# 0.4 to 3.4 ms over 7,930 generations.
_PAIRS = """
    SELECT a.id, MAX(b.id) FROM generations a
    JOIN generations b ON b.created_at = a.created_at AND b.id > a.id AND b.source_id IS NULL
    WHERE a.source_id IS NULL
      AND EXISTS (SELECT 1 FROM generation_images x WHERE x.generation_id = a.id)
      AND NOT EXISTS (
          SELECT 1 FROM generation_images ia WHERE ia.generation_id = a.id AND NOT EXISTS (
              SELECT 1 FROM generation_images ib
              WHERE ib.generation_id = b.id AND ib.path = ia.path COLLATE NOCASE))
    {only}
    GROUP BY a.id
"""


def _pairs(cursor, only: Optional[Iterable[int]] = None) -> Dict[int, int]:
    """{early copy: generation kept}, of every early copy or of these alone."""
    ids = list(only or [])
    if only is not None and not ids:
        return {}
    where = f"AND a.id IN ({', '.join('?' * len(ids))})" if only is not None else ""
    cursor.execute(_PAIRS.format(only=where), ids)
    return {early: kept for early, kept in cursor.fetchall()}


def needed(db) -> int:
    """How many early copies the library holds: the light check the page asks at load."""
    with db._cursor() as cursor:
        return len(_pairs(cursor))


def listing(db) -> List[Dict[str, Any]]:
    """
    Each early copy, newest first: when its press was made and in which tab,
    its batch count, its prompt, how many images it and the generation kept
    hold, and its first image - hidden as the Generations tab would hide it,
    the setting on and the image rated above PG-13, with its level's name.
    """
    hide = bool(setting(GENERATIONS_HIDE_NSFW))
    with db._cursor() as cursor:
        pairs = _pairs(cursor)
        rows = []
        for early, kept in sorted(pairs.items(), reverse=True):
            cursor.execute("""
                SELECT g.created_at, g.mode, g.image_count, d.n_iter, p.text,
                       (SELECT image_count FROM generations WHERE id = ?)
                FROM generations g
                LEFT JOIN generation_details d ON d.generation_id = g.id
                LEFT JOIN generation_prompts p ON p.id = g.prompt_id
                WHERE g.id = ?""", (kept, early))
            created_at, mode, count, n_iter, prompt, kept_count = cursor.fetchone()
            cursor.execute("""
                SELECT id, COALESCE(user_nsfw_level, prompt_nsfw_level) FROM generation_images
                WHERE generation_id = ? ORDER BY position LIMIT 1""", (early,))
            image_id, level = cursor.fetchone()
            hidden = hide and (level is None or level > SFW_MAX)
            rows.append({
                "id": early, "kept": kept, "created_at": created_at, "mode": mode,
                "batch_count": n_iter, "images": count, "kept_images": kept_count,
                # Of a chain, all but the last: the batch count says why.
                "same_press": sum(1 for k in pairs.values() if k == kept),
                "prompt": None if hidden else (prompt or "")[:300],
                "image_id": None if hidden else image_id,
                "hidden_level": level_name(level) if hidden else None,
            })
        return rows


def remove(db, ids: Iterable[int]) -> Dict[str, Any]:
    """
    Remove these early copies, in one transaction, each checked again first:
    one gone meanwhile, or no longer an early copy - its generation kept
    deleted since the list was drawn - is skipped, and said why.

    Returns:
        removed: the ids removed; skipped: [{id, why}].
    """
    ids = sorted({int(i) for i in ids})
    if not ids:
        return {"removed": [], "skipped": []}
    generations = db._generations
    with db._cursor() as cursor:
        generations._write_lock(cursor)
        pairs = _pairs(cursor, ids)
        cursor.execute(f"SELECT id FROM generations WHERE id IN ({', '.join('?' * len(ids))})", ids)
        present = {row[0] for row in cursor.fetchall()}
        skipped = [{"id": i, "why": "no longer recorded twice: the generation kept was deleted"
                    if i in present else "already gone"} for i in ids if i not in pairs]
        freed: set = set()
        for early, kept in pairs.items():
            _carry_over(cursor, early, kept)
            generations.remove(cursor, early, freed)
        generations.drop_unused_prompts(cursor, freed)
    return {"removed": sorted(pairs), "skipped": skipped}


def _carry_over(cursor, early: int, kept: int) -> None:
    """What the person set on an early copy, given to the generation kept
    where it has none of its own."""
    cursor.execute("""
        UPDATE generation_images SET user_nsfw_level = (
            SELECT e.user_nsfw_level FROM generation_images e
            WHERE e.generation_id = ? AND e.path = generation_images.path COLLATE NOCASE
              AND e.user_nsfw_level IS NOT NULL
            LIMIT 1)
        WHERE generation_id = ? AND user_nsfw_level IS NULL AND EXISTS (
            SELECT 1 FROM generation_images e
            WHERE e.generation_id = ? AND e.path = generation_images.path COLLATE NOCASE
              AND e.user_nsfw_level IS NOT NULL)
    """, (early, kept, early))
    cursor.execute("""
        UPDATE generations SET user_nsfw_level = (SELECT user_nsfw_level FROM generations WHERE id = ?)
        WHERE id = ? AND user_nsfw_level IS NULL
    """, (early, kept))
    cursor.execute("INSERT OR IGNORE INTO task_generations (task_id, generation_id) "
                   "SELECT task_id, ? FROM task_generations WHERE generation_id = ?", (kept, early))
    cursor.execute("""
        UPDATE generation_input_files SET generation_id = ?
        WHERE generation_id = ? AND name NOT IN (
            SELECT name FROM generation_input_files WHERE generation_id = ?)
    """, (kept, early, kept))


def register(app, common) -> None:
    """Its two routes, under the Generations tab's switch: `common` is the
    API's (gate, failed), handed in - the repairs import nothing of the API."""
    from fastapi import Form
    from fastapi.responses import JSONResponse
    from ..db import get_models_db
    from .. import generation_inputs

    @app.get("/model-manager/repairs/recorded-twice")
    @common.gate(AREA)
    def get_recorded_twice():
        """Every early copy, for the review window."""
        try:
            return JSONResponse({"success": True, "early": listing(get_models_db())})
        except Exception as e:
            return common.failed(e, "Listing generations recorded twice")

    @app.post("/model-manager/repairs/recorded-twice/remove")
    @common.gate(AREA)
    def remove_recorded_twice(ids: str = Form(default="")):
        """Remove the early copies ticked: ids comma-separated. The files stay."""
        try:
            db = get_models_db()
            answer = remove(db, [int(i) for i in ids.split(",") if i.strip()])
            # A source picture the kept generation had its own of is no
            # longer named: forget() deletes what no row names.
            generation_inputs.forget(db)
            return JSONResponse({"success": True, **answer})
        except Exception as e:
            return common.failed(e, "Removing generations recorded twice")
