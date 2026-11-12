"""
LoRA weights saved as 1 (#392): before 0.78.9 the recorder stored every LoRA
of a generation's first pass at weight 1, whatever its tag said - it read the
LoRA object Forge keeps, which stays at 1.0 while the tag's weight goes into
the model alone. Listed for the person to review, and corrected only in the
generations they tick.

The right weight is in the prompt Forge loaded the batch's LoRAs from: the
batch's first image's own (styles applied, the "Add network to prompt" tag
written in), read by the recorder's own rule (generations.prompt_lora_tags,
pair_lora_weights). An entry is corrected only where it holds what the bug
wrote - both weights 1.0 - and its tag gives another; a tag with no fixed
weight - Neo's schedule - gives none, as the recorder stores since 0.78.9.
A LoRA no tag names, or a batch whose first image was not kept, is left as
it is.

Correcting sets the two weights in the record (generation_image_details.loras)
and the index's copy (generation_resources.weight), nothing else.
"""
import json
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..forge_host import setting
from ..generations import GENERATIONS_HIDE_NSFW, pair_lora_weights, prompt_lora_tags
from ..nsfw import SFW_MAX, level_name

AREA = "generations"

# The recorded images with a LoRA the index holds at 1.0 - the bug's mark -
# with their records and where their batch starts. Narrowed in SQL to a
# range of generations or a list of them.
_CANDIDATES = """
    SELECT gi.id, gi.generation_id, gi.iteration, gd.batch_size, d.loras
    FROM generation_resources r
    JOIN generations g ON g.id = r.generation_id AND g.source_id IS NULL
    JOIN generation_images gi ON gi.id = r.image_id
    JOIN generation_image_details d ON d.image_id = gi.id
    LEFT JOIN generation_details gd ON gd.generation_id = gi.generation_id
    WHERE r.role = 'lora' AND r.weight = 1.0 AND {only}
    GROUP BY gi.id
"""

Change = Tuple[int, Any, Tuple[Optional[float], Optional[float]]]   # entry's place, its name, its weights


def _changes(loras: Any, prompt: Optional[str]) -> List[Change]:
    """Each base-pass entry the bug wrote - both weights 1.0 - whose tag in
    the batch's prompt gives other weights."""
    if not isinstance(loras, list):
        return []
    base = [(i, entry) for i, entry in enumerate(loras)
            if isinstance(entry, dict) and entry.get("pass") == "base"]
    paired = pair_lora_weights([entry.get("name") for _, entry in base], prompt_lora_tags(prompt))
    changes = []
    for (place, entry), weights in zip(base, paired):
        written = (entry.get("te_multiplier"), entry.get("unet_multiplier"))
        if weights is not None and written == (1.0, 1.0) and weights != written:
            changes.append((place, entry.get("name"), weights))
    return changes


def _scan(cursor, only: str, params: List[Any]) -> Dict[int, List[Tuple[int, Any, List[Change]]]]:
    """{generation: [(image, its record, its changes)]} of the generations
    whose weights differ from their prompts', among those `only` names."""
    cursor.execute(_CANDIDATES.format(only=only), params)
    rows = cursor.fetchall()
    if not rows:
        return {}
    cursor.execute("""
        SELECT x.generation_id, x.position, p.text FROM generation_images x
        LEFT JOIN generation_prompts p ON p.id = x.prompt_id
        WHERE x.generation_id IN (SELECT value FROM json_each(?))
    """, (json.dumps(sorted({row[1] for row in rows})),))
    prompts = {(generation, position): text for generation, position, text in cursor.fetchall()}
    found: Dict[int, List[Tuple[int, Any, List[Change]]]] = {}
    for image_id, generation_id, iteration, batch_size, stored in rows:
        if iteration is None or not batch_size:
            continue
        first = (generation_id, int(iteration) * int(batch_size))
        if first not in prompts:
            continue                      # its batch's first image was not kept: not guessed
        try:
            loras = json.loads(stored) if stored else []
        except ValueError:
            continue
        changes = _changes(loras, prompts[first])
        if changes:
            found.setdefault(generation_id, []).append((image_id, loras, changes))
    return found


def _in_range(cursor, after: int, through: int):
    return _scan(cursor, "r.generation_id > ? AND r.generation_id <= ?", [after, through])


def _of(cursor, generation_ids: Iterable[int]):
    ids = sorted({int(i) for i in generation_ids})
    if not ids:
        return {}
    return _scan(cursor, "r.generation_id IN (SELECT value FROM json_each(?))", [json.dumps(ids)])


# The answer, kept for this WebUI's process: the page asks about 21 times a
# load - the repairs' list once, each tab's notes for every note naming a
# repair, twice over - and a whole read is 107 ms warm on one library. The
# generations found and the last id read; later asks read only newer
# generations, and drop those deleted since. Correct takes off what it did,
# and the list sets it afresh. What it misses until then: a Correct in the
# other WebUI sharing the database, and a found generation whose batch's
# first image was deleted - the count stays one too high; the list, read
# afresh, shows what is left, and Correct reads everything again.
_LOCK = threading.Lock()
_KNOWN: Dict[str, Any] = {"db": None, "through": 0, "found": set()}


def _last_id(cursor) -> int:
    """The last id given to a generation. Never handed out again
    (AUTOINCREMENT), so deleting the newest does not lower it; a lower one
    is another database file."""
    cursor.execute("SELECT seq FROM sqlite_sequence WHERE name = 'generations'")
    row = cursor.fetchone()
    if row is None:
        cursor.execute("SELECT COALESCE(MAX(id), 0) FROM generations")
        row = cursor.fetchone()
    return int(row[0] or 0)


def _known(db, cursor) -> set:
    """The generations to correct, brought up to date. Under _LOCK."""
    newest = _last_id(cursor)
    if _KNOWN["db"] is not db or newest < _KNOWN["through"]:
        _KNOWN.update(db=db, through=0, found=set())
    if newest > _KNOWN["through"]:
        _KNOWN["found"] |= set(_in_range(cursor, _KNOWN["through"], newest))
        _KNOWN["through"] = newest
    if _KNOWN["found"]:
        cursor.execute("SELECT id FROM generations WHERE id IN (SELECT value FROM json_each(?))",
                       (json.dumps(sorted(_KNOWN["found"])),))
        _KNOWN["found"] = {row[0] for row in cursor.fetchall()}
    return _KNOWN["found"]


def needed(db) -> int:
    """How many generations hold LoRA weights saved as 1: the light check the page asks at load."""
    with _LOCK, db._cursor() as cursor:
        return len(_known(db, cursor))


def listing(db) -> List[Dict[str, Any]]:
    """
    Each generation to correct, newest first, read afresh: when it was made
    and in which tab, its batch count, its prompt, how many images change,
    each LoRA's change - its name, the 1 it holds, its tag's two weights -
    and its first image, hidden as the Generations tab would hide it.
    """
    hide = bool(setting(GENERATIONS_HIDE_NSFW))
    with _LOCK, db._cursor() as cursor:
        fresh = _of(cursor, _known(db, cursor))
        _KNOWN["found"] = set(fresh)
        rows = []
        for generation_id in sorted(fresh, reverse=True):
            cursor.execute("""
                SELECT g.created_at, g.mode, d.n_iter, p.text FROM generations g
                LEFT JOIN generation_details d ON d.generation_id = g.id
                LEFT JOIN generation_prompts p ON p.id = g.prompt_id
                WHERE g.id = ?""", (generation_id,))
            generation = cursor.fetchone()
            cursor.execute("""
                SELECT id, COALESCE(user_nsfw_level, prompt_nsfw_level) FROM generation_images
                WHERE generation_id = ? ORDER BY position LIMIT 1""", (generation_id,))
            first = cursor.fetchone()
            if generation is None or first is None:
                continue                  # deleted since it was read: Correct skips it too
            created_at, mode, n_iter, prompt = generation
            image_id, level = first
            hidden = hide and (level is None or level > SFW_MAX)
            changes, seen = [], set()
            for _, _, image_changes in fresh[generation_id]:
                for _, name, (te, unet) in image_changes:
                    if (name, te, unet) not in seen:
                        seen.add((name, te, unet))
                        changes.append({"name": name, "from": 1.0, "te": te, "unet": unet})
            rows.append({
                "id": generation_id, "created_at": created_at, "mode": mode, "batch_count": n_iter,
                "images": len(fresh[generation_id]), "changes": changes,
                "prompt": None if hidden else (prompt or "")[:300],
                "image_id": None if hidden else image_id,
                "hidden_level": level_name(level) if hidden else None,
            })
        return rows


def correct(db, ids: Iterable[int]) -> Dict[str, Any]:
    """
    Correct these generations, in one transaction, each read again first:
    one gone meanwhile, or whose weights no longer differ, is skipped and
    said why.

    Returns:
        corrected: the ids corrected; skipped: [{id, why}].
    """
    ids = sorted({int(i) for i in ids})
    if not ids:
        return {"corrected": [], "skipped": []}
    # Not under _LOCK: the write lock can be waited for - 30 s, an hour during
    # a compact - and the page's every check would wait with it. Nothing here
    # reads the kept answer; it is told only once this has committed.
    with db._cursor() as cursor:
        db._generations._write_lock(cursor)
        cursor.execute("SELECT id FROM generations WHERE id IN (SELECT value FROM json_each(?))",
                       (json.dumps(ids),))
        present = {row[0] for row in cursor.fetchall()}
        fresh = _of(cursor, present)
        skipped = [{"id": i, "why": "it is already gone" if i not in present
                    else "its LoRA weights already match its prompt, "
                         "or the image its batch's weights are read from is gone"}
                   for i in ids if i not in fresh]
        for images in fresh.values():
            for image_id, loras, changes in images:
                for place, _, (te, unet) in changes:
                    loras[place]["te_multiplier"] = te
                    loras[place]["unet_multiplier"] = unet
                    cursor.execute("UPDATE generation_resources SET weight = ? "
                                   "WHERE image_id = ? AND role = 'lora' AND position = ?",
                                   (te, image_id, place))
                cursor.execute("UPDATE generation_image_details SET loras = ? WHERE image_id = ?",
                               (json.dumps(loras, ensure_ascii=False), image_id))
    with _LOCK:
        if _KNOWN["db"] is db:
            _KNOWN["found"] -= set(ids)
    return {"corrected": sorted(fresh), "skipped": skipped}


def register(app, common) -> None:
    """Its two routes, under the Generations tab's switch: `common` is the
    API's (gate, failed), handed in - the repairs import nothing of the API."""
    from fastapi import Form
    from fastapi.responses import JSONResponse
    from ..db import get_models_db

    @app.get("/model-manager/repairs/lora-weights")
    @common.gate(AREA)
    def get_lora_weights():
        """Every generation whose LoRA weights were saved as 1, for the review window."""
        try:
            return JSONResponse({"success": True, "generations": listing(get_models_db())})
        except Exception as e:
            return common.failed(e, "Listing LoRA weights saved as 1")

    @app.post("/model-manager/repairs/lora-weights/correct")
    @common.gate(AREA)
    def correct_lora_weights(ids: str = Form(default="")):
        """Correct the generations ticked: ids comma-separated."""
        try:
            return JSONResponse({"success": True, **correct(get_models_db(),
                                                            [int(i) for i in ids.split(",") if i.strip()])})
        except Exception as e:
            return common.failed(e, "Correcting LoRA weights saved as 1")
